//! Phase 3 component delivery and activation manager.
//!
//! The manager is intentionally independent of the Phase 2 shell bootstrap.
//! It owns only the machine-scoped ProgramData component perimeter. It never
//! writes to Program Files, AppData, projects, exports, or the browser/Docker
//! development paths. The lecturer release trust root is compiled into the
//! application; the fixture key below is retained only for debug/unit tests.

use crate::release_trust::{RELEASE_KEY_ID, RELEASE_PUBLIC_KEY_B64};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use flate2::read::GzDecoder;
use reqwest::blocking::{Client, Response};
use reqwest::redirect::Policy;
use ring::signature::{UnparsedPublicKey, ED25519};
use semver::{Version, VersionReq};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
#[cfg(test)]
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, State};
use url::Url;

pub const COMPONENT_MANIFEST_SCHEMA: &str = "desktop.component-manifest.v1";
pub const ACTIVATION_SCHEMA: &str = "desktop.component-activation.v1";
pub const DOWNLOAD_STATE_SCHEMA: &str = "desktop.component-download.v1";
pub const COMPONENT_PROGRESS_EVENT: &str = "component-operation-progress";

// This is a deterministic non-production fixture public key. Its throwaway
// seed is derived from a public label only in fixture/test code; it is not a
// production key and must never be used to ship a real component. Production
// roots belong in a separately reviewed release build and are never accepted
// from a manifest.
pub const TEST_FIXTURE_KEY_ID: &str = "test-fixture-2026";
pub const TEST_FIXTURE_PUBLIC_KEY_B64: &str = "hfqZ1Gk2qemcp+23vgMKpdMauxUlEXuBWF3NilhYA44=";

// The frozen onedir engine carries a complete exact file inventory. Keep
// intake bounded, but allow the signed inventory for the real release.
const MAX_MANIFEST_BYTES: usize = 4 * 1024 * 1024;
const MAX_ARTIFACT_BYTES: u64 = 512 * 1024 * 1024;
const MAX_FILE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_UNCOMPRESSED_BYTES: u64 = 1024 * 1024 * 1024;
const MAX_ARCHIVE_ENTRIES: usize = 50_000;
const MAX_REDIRECTS: usize = 3;
const MAX_DOWNLOAD_RETRIES: usize = 3;
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(30);
const RETRY_BACKOFF: [Duration; MAX_DOWNLOAD_RETRIES] = [
    Duration::from_millis(100),
    Duration::from_millis(250),
    Duration::from_millis(500),
];
const LOCK_STALE_AFTER: Duration = Duration::from_secs(6 * 60 * 60);
const DOWNLOAD_BUFFER_BYTES: usize = 64 * 1024;
const FREE_SPACE_MARGIN_BYTES: u64 = 16 * 1024 * 1024;
const OFFLINE_ROOT_SCHEMA: &str = "desktop.offline-root.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ComponentError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
    pub remediation_codes: Vec<String>,
}

pub type ManagerResult<T> = Result<T, ComponentError>;

impl ComponentError {
    pub(crate) fn new(code: &str, message: impl Into<String>, retryable: bool) -> Self {
        let remediation_codes = match code {
            "ELEVATION_REQUIRED" | "STORAGE_NOT_WRITABLE" => {
                vec!["STORAGE_NOT_WRITABLE".to_string()]
            }
            "DISK_SPACE_LOW" => vec!["DISK_SPACE_LOW".to_string()],
            "ROLLBACK_AVAILABLE" => vec!["UPDATE_ROLLBACK_AVAILABLE".to_string()],
            _ => Vec::new(),
        };
        Self {
            code: code.to_string(),
            message: message.into(),
            retryable,
            remediation_codes,
        }
    }
}

impl std::fmt::Display for ComponentError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for ComponentError {}

#[derive(Debug, Clone, Copy)]
pub struct SourcePolicy {
    pub allow_local_test_sources: bool,
}

impl SourcePolicy {
    pub const PRODUCTION: Self = Self {
        allow_local_test_sources: false,
    };

    pub const OFFLINE_IMPORT: Self = Self {
        allow_local_test_sources: true,
    };

    pub const fn development_test() -> Self {
        Self {
            allow_local_test_sources: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ComponentType {
    Backend,
    Database,
    #[serde(rename = "vector-store")]
    VectorStore,
    Ffmpeg,
    Model,
    Renderer,
    Utility,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ReleaseChannel {
    Stable,
    Beta,
    Nightly,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum OperatingSystem {
    Windows,
    Macos,
    Linux,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Architecture {
    X86,
    #[serde(rename = "x86_64")]
    X86_64,
    Aarch64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ArchiveFormat {
    Zip,
    #[serde(rename = "tar.gz")]
    TarGz,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ComponentManifest {
    pub schema_version: String,
    pub component: ComponentIdentity,
    pub target: Target,
    pub requirements: Requirements,
    pub artifact: Artifact,
    pub signature: DetachedSignature,
    pub archive: Archive,
    pub install: InstallLayout,
    pub entrypoint: Entrypoint,
    pub dependencies: Vec<Dependency>,
    pub capabilities: Vec<String>,
    pub metadata: ComponentMetadata,
    pub files: Vec<FileInventoryEntry>,
    pub self_test: SelfTest,
    pub health: HealthContract,
    pub rollback: RollbackMetadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ComponentIdentity {
    pub id: String,
    #[serde(rename = "type")]
    pub component_type: ComponentType,
    pub version: String,
    pub channel: ReleaseChannel,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct Target {
    pub operating_systems: Vec<OperatingSystem>,
    pub architectures: Vec<Architecture>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct Requirements {
    pub minimum_shell_version: String,
    #[serde(default)]
    pub requires_elevation: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct Artifact {
    pub url: String,
    pub byte_size: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct DetachedSignature {
    pub algorithm: String,
    pub value: String,
    pub key_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct Archive {
    pub format: ArchiveFormat,
    pub root_directory: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct InstallLayout {
    pub root_kind: String,
    pub relative_path: String,
    pub immutable: bool,
    pub activation: ActivationLayout,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ActivationLayout {
    pub strategy: String,
    pub active_path: String,
    pub staging_path: String,
    pub metadata_path: String,
    pub atomic_commit: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct Entrypoint {
    pub kind: String,
    pub relative_path: String,
    pub arguments: Vec<String>,
    pub working_directory: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct Dependency {
    pub id: String,
    pub version_constraint: String,
    pub optional: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ComponentMetadata {
    pub display_name: String,
    pub publisher: String,
    pub license: LicenseMetadata,
    pub source: SourceMetadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct LicenseMetadata {
    pub spdx_id: String,
    pub notice_file: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SourceMetadata {
    pub repository_url: String,
    pub release_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct FileInventoryEntry {
    pub path: String,
    pub kind: String,
    pub byte_size: u64,
    pub sha256: String,
    pub executable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SelfTest {
    pub command: Vec<String>,
    pub timeout_ms: u64,
    pub expected_exit_code: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct HealthContract {
    pub probe: String,
    pub path: String,
    pub method: String,
    pub timeout_ms: u64,
    pub readiness_schema_version: String,
    pub requires_bearer_token: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct RollbackMetadata {
    pub strategy: String,
    pub retention_count: usize,
    pub metadata_path: String,
    pub on_activation_failure: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ManifestIntakeResult {
    pub component_id: String,
    pub component_version: String,
    pub signature_key_id: String,
    pub artifact_bytes: u64,
    pub catalog_path: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InstallationPlan {
    pub component_id: String,
    pub target_version: String,
    pub artifact_bytes: u64,
    pub requires_elevation: bool,
    pub dependencies: Vec<DependencyPlanItem>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DependencyPlanItem {
    pub id: String,
    pub version_constraint: String,
    pub resolved_version: Option<String>,
    pub optional: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ComponentStatusResult {
    pub id: String,
    pub display_name: Option<String>,
    pub version: Option<String>,
    pub state: String,
    pub active_path: Option<String>,
    pub downloaded_bytes: u64,
    pub detail: String,
    pub remediation_codes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ComponentProgress {
    pub operation_id: String,
    pub component_id: String,
    pub component_version: String,
    pub operation: String,
    pub state: String,
    pub bytes_downloaded: u64,
    pub total_bytes: u64,
    pub percent: f64,
    pub message: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadResult {
    pub operation_id: String,
    pub component_id: String,
    pub component_version: String,
    pub archive_path: String,
    pub bytes_downloaded: u64,
    pub resumed: bool,
    pub state: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VerificationResult {
    pub component_id: String,
    pub component_version: String,
    pub artifact_bytes: u64,
    pub artifact_sha256: String,
    pub signature_key_id: String,
    pub inventory_entries: usize,
    pub state: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StageResult {
    pub component_id: String,
    pub component_version: String,
    pub operation_id: String,
    pub stage_path: String,
    pub inventory_entries: usize,
    pub state: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ActivationResult {
    pub component_id: String,
    pub component_version: String,
    pub active_path: String,
    pub previous_version: Option<String>,
    pub state: String,
}

/// A read-only launch plan assembled from a verified active component.
///
/// The supervisor is deliberately not allowed to launch a path copied from
/// the WebView or from an arbitrary environment variable.  This value is
/// produced only after the active metadata, signed manifest, exact installed
/// inventory, and entrypoint boundary have all been checked.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VerifiedActiveComponent {
    pub component_id: String,
    pub component_version: String,
    pub active_path: String,
    pub executable_path: String,
    pub entrypoint: String,
    pub arguments: Vec<String>,
    pub working_directory: Option<String>,
    pub capabilities: Vec<String>,
    pub manifest_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecoveryResult {
    pub recovered_journals: usize,
    pub cleaned_staging_directories: usize,
    pub resumable_downloads: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RepairResult {
    pub component_id: String,
    pub state: String,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UninstallResult {
    pub component_id: String,
    pub removed_paths: Vec<String>,
    pub preserved_user_data: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct DownloadState {
    schema_version: String,
    operation_id: String,
    component_id: String,
    component_version: String,
    url: String,
    expected_bytes: u64,
    bytes_downloaded: u64,
    sha256: String,
    temp_path: String,
    archive_path: String,
    resumable: bool,
    status: String,
    recovery: DownloadRecovery,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct DownloadRecovery {
    status: String,
    resume_from_byte: u64,
    last_verified_byte: u64,
    etag: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ActivationMetadata {
    schema_version: String,
    state: String,
    component_id: String,
    component_version: String,
    active_path: String,
    previous_version: Option<String>,
    previous_path: Option<String>,
    manifest_path: String,
    activated_at_epoch_ms: u128,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ActivationJournal {
    schema_version: String,
    operation_id: String,
    component_id: String,
    component_version: String,
    manifest_path: String,
    stage_path: String,
    published_path: String,
    metadata_path: String,
    checkpoint: String,
    previous_version: Option<String>,
    previous_path: Option<String>,
    updated_at_epoch_ms: u128,
}

#[derive(Debug, Clone)]
struct ManagerPaths {
    machine_root: PathBuf,
    components_root: PathBuf,
    activation_root: PathBuf,
    downloads_root: PathBuf,
    catalog_root: PathBuf,
    offline_root_metadata: PathBuf,
    journal_root: PathBuf,
    lock_path: PathBuf,
}

impl ManagerPaths {
    fn new(machine_root: PathBuf) -> Self {
        let components_root = machine_root.join("Components");
        let activation_root = machine_root.join("Activation");
        let downloads_root = machine_root.join("Downloads").join("Staging");
        let catalog_root = machine_root.join("Catalog");
        let offline_root_metadata = catalog_root.join("offline-root.json");
        let journal_root = activation_root.join("Journal");
        let lock_path = machine_root.join("component-manager.lock");
        Self {
            machine_root,
            components_root,
            activation_root,
            downloads_root,
            catalog_root,
            offline_root_metadata,
            journal_root,
            lock_path,
        }
    }
}

#[derive(Clone)]
pub(crate) struct OperationControl {
    cancel: Arc<AtomicBool>,
    pause: Arc<AtomicBool>,
}

impl Default for OperationControl {
    fn default() -> Self {
        Self {
            cancel: Arc::new(AtomicBool::new(false)),
            pause: Arc::new(AtomicBool::new(false)),
        }
    }
}

#[derive(Default)]
pub struct ComponentManagerState {
    controls: Arc<Mutex<HashMap<String, OperationControl>>>,
}

impl ComponentManagerState {
    fn register(&self, operation_id: &str) -> OperationControl {
        let control = OperationControl::default();
        if let Ok(mut controls) = self.controls.lock() {
            controls.insert(operation_id.to_string(), control.clone());
        }
        control
    }

    fn remove(&self, operation_id: &str) {
        if let Ok(mut controls) = self.controls.lock() {
            controls.remove(operation_id);
        }
    }

    fn set_pause(&self, operation_id: &str, paused: bool) -> bool {
        self.controls
            .lock()
            .ok()
            .and_then(|controls| controls.get(operation_id).cloned())
            .map(|control| {
                control.pause.store(paused, Ordering::Relaxed);
                true
            })
            .unwrap_or(false)
    }

    fn set_cancel(&self, operation_id: &str) -> bool {
        self.controls
            .lock()
            .ok()
            .and_then(|controls| controls.get(operation_id).cloned())
            .map(|control| {
                control.cancel.store(true, Ordering::Relaxed);
                true
            })
            .unwrap_or(false)
    }
}

#[derive(Clone)]
pub struct ComponentManager {
    paths: ManagerPaths,
    offline_root: Option<PathBuf>,
}

impl ComponentManager {
    pub fn new(machine_root: PathBuf) -> Self {
        Self {
            paths: ManagerPaths::new(machine_root),
            offline_root: None,
        }
    }

    pub fn with_offline_root(machine_root: PathBuf, offline_root: PathBuf) -> Self {
        Self {
            paths: ManagerPaths::new(machine_root),
            offline_root: Some(offline_root),
        }
    }

    pub fn machine_root(&self) -> &Path {
        &self.paths.machine_root
    }

    fn ensure_machine_storage(&self) -> ManagerResult<()> {
        for path in [
            &self.paths.machine_root,
            &self.paths.components_root,
            &self.paths.activation_root,
            &self.paths.downloads_root,
            &self.paths.catalog_root,
            &self.paths.journal_root,
        ] {
            fs::create_dir_all(path).map_err(|error| storage_error(path, error))?;
        }
        Ok(())
    }

    fn persist_offline_root(&self) -> ManagerResult<()> {
        let configured = self.offline_root.as_ref().ok_or_else(|| {
            ComponentError::new(
                "OFFLINE_ROOT_REQUIRED",
                "A portable offline artifact reference requires the imported catalog directory.",
                false,
            )
        })?;
        let canonical = fs::canonicalize(configured).map_err(|error| {
            ComponentError::new(
                "OFFLINE_ROOT_INVALID",
                format!("The imported offline catalog directory could not be resolved: {error}"),
                false,
            )
        })?;
        if !canonical.is_dir() {
            return Err(ComponentError::new(
                "OFFLINE_ROOT_INVALID",
                "The imported offline catalog root is not a directory.",
                false,
            ));
        }
        atomic_write_json(
            &self.paths.offline_root_metadata,
            &OfflineRootRecord {
                schema_version: OFFLINE_ROOT_SCHEMA.to_string(),
                root: canonical.to_string_lossy().to_string(),
            },
        )
    }

    fn configured_offline_root(&self) -> ManagerResult<PathBuf> {
        let configured = if let Some(root) = &self.offline_root {
            root.clone()
        } else {
            let bytes = fs::read(&self.paths.offline_root_metadata).map_err(|error| {
                ComponentError::new(
                    "OFFLINE_ROOT_REQUIRED",
                    format!("No imported offline catalog root is available: {error}"),
                    false,
                )
            })?;
            if bytes.len() > 16 * 1024 {
                return Err(ComponentError::new(
                    "OFFLINE_ROOT_INVALID",
                    "The persisted offline catalog root record is too large.",
                    false,
                ));
            }
            let record: OfflineRootRecord = serde_json::from_slice(&bytes).map_err(|error| {
                ComponentError::new(
                    "OFFLINE_ROOT_INVALID",
                    format!("The persisted offline catalog root record is invalid: {error}"),
                    false,
                )
            })?;
            if record.schema_version != OFFLINE_ROOT_SCHEMA {
                return Err(ComponentError::new(
                    "OFFLINE_ROOT_INVALID",
                    "The persisted offline catalog root record is unsupported.",
                    false,
                ));
            }
            PathBuf::from(record.root)
        };
        fs::canonicalize(&configured).map_err(|error| {
            ComponentError::new(
                "OFFLINE_ROOT_INVALID",
                format!("The imported offline catalog root is no longer available: {error}"),
                true,
            )
        })
    }

    fn resolve_offline_artifact_path(&self, value: &str) -> ManagerResult<PathBuf> {
        let relative = offline_artifact_relative_path(value)?;
        let root = self.configured_offline_root()?;
        let candidate = root.join(relative);
        let resolved = fs::canonicalize(&candidate).map_err(|error| {
            ComponentError::new(
                "OFFLINE_ARTIFACT_UNAVAILABLE",
                format!("The signed offline artifact is not available under the imported catalog root: {error}"),
                false,
            )
        })?;
        ensure_child_path(&root, &resolved)?;
        if !resolved.is_file() || is_reparse_or_symlink(&resolved) {
            return Err(ComponentError::new(
                "OFFLINE_ARTIFACT_INVALID",
                "The signed offline artifact is not a regular file under the imported catalog root.",
                false,
            ));
        }
        Ok(resolved)
    }

    pub fn intake_manifest(
        &self,
        manifest_json: &str,
        policy: SourcePolicy,
    ) -> ManagerResult<ManifestIntakeResult> {
        if manifest_json.len() > MAX_MANIFEST_BYTES {
            return Err(ComponentError::new(
                "MANIFEST_TOO_LARGE",
                "The manifest exceeds the bounded intake size.",
                false,
            ));
        }
        let manifest: ComponentManifest = serde_json::from_str(manifest_json).map_err(|error| {
            ComponentError::new(
                "MANIFEST_SCHEMA_INVALID",
                format!("The component manifest is not compatible with the v1 schema: {error}"),
                false,
            )
        })?;
        self.validate_manifest(&manifest, policy)?;
        self.ensure_machine_storage()?;
        if policy.allow_local_test_sources && manifest.artifact.url.starts_with("offline:") {
            self.persist_offline_root()?;
        }
        let path = self.catalog_path(&manifest.component.id, &manifest.component.version)?;
        atomic_write_json(&path, &manifest)?;
        Ok(ManifestIntakeResult {
            component_id: manifest.component.id,
            component_version: manifest.component.version,
            signature_key_id: manifest.signature.key_id,
            artifact_bytes: manifest.artifact.byte_size,
            catalog_path: path.to_string_lossy().to_string(),
        })
    }

    fn validate_manifest(
        &self,
        manifest: &ComponentManifest,
        policy: SourcePolicy,
    ) -> ManagerResult<()> {
        if manifest.schema_version != COMPONENT_MANIFEST_SCHEMA {
            return Err(ComponentError::new(
                "SCHEMA_VERSION_UNSUPPORTED",
                format!(
                    "Unsupported component manifest schema: {}",
                    manifest.schema_version
                ),
                false,
            ));
        }
        validate_component_id(&manifest.component.id)?;
        parse_version(&manifest.component.version, "component.version")?;
        let shell_version = Version::parse(env!("CARGO_PKG_VERSION")).map_err(|error| {
            ComponentError::new(
                "SHELL_VERSION_INVALID",
                format!("The shell build version is invalid: {error}"),
                false,
            )
        })?;
        let minimum_shell = parse_version(
            &manifest.requirements.minimum_shell_version,
            "requirements.minimumShellVersion",
        )?;
        if shell_version < minimum_shell {
            return Err(ComponentError::new(
                "SHELL_VERSION_INCOMPATIBLE",
                format!(
                    "Component {} requires shell {}, current shell is {}.",
                    manifest.component.id, minimum_shell, shell_version
                ),
                false,
            ));
        }
        let current_os = current_operating_system();
        if !manifest.target.operating_systems.contains(&current_os) {
            return Err(ComponentError::new(
                "OS_INCOMPATIBLE",
                format!("The component does not target {:?}.", current_os),
                false,
            ));
        }
        let current_arch = current_architecture();
        if !manifest.target.architectures.contains(&current_arch) {
            return Err(ComponentError::new(
                "ARCHITECTURE_INCOMPATIBLE",
                format!("The component does not target {:?}.", current_arch),
                false,
            ));
        }
        if manifest.artifact.byte_size == 0 || manifest.artifact.byte_size > MAX_ARTIFACT_BYTES {
            return Err(ComponentError::new(
                "ARTIFACT_LIMIT_EXCEEDED",
                "The artifact byte size is outside the bounded download limit.",
                false,
            ));
        }
        validate_sha256(&manifest.artifact.sha256, "artifact.sha256")?;
        validate_artifact_url(&manifest.artifact.url, policy)?;
        if manifest.signature.algorithm != "ed25519" {
            return Err(ComponentError::new(
                "SIGNATURE_ALGORITHM_UNSUPPORTED",
                "Only detached Ed25519 signatures are accepted.",
                false,
            ));
        }
        if trusted_key(&manifest.signature.key_id).is_none() {
            return Err(ComponentError::new(
                "UNKNOWN_TRUST_KEY",
                format!(
                    "The signature key id is not compiled into this shell: {}",
                    manifest.signature.key_id
                ),
                false,
            ));
        }
        let signature = BASE64.decode(&manifest.signature.value).map_err(|error| {
            ComponentError::new(
                "SIGNATURE_ENCODING_INVALID",
                format!("The detached signature is not valid base64: {error}"),
                false,
            )
        })?;
        if signature.len() != 64 {
            return Err(ComponentError::new(
                "SIGNATURE_LENGTH_INVALID",
                "An Ed25519 signature must contain exactly 64 bytes.",
                false,
            ));
        }
        verify_manifest_signature(manifest, &signature)?;

        validate_safe_relative_path(&manifest.archive.root_directory, "archive.rootDirectory")?;
        validate_safe_relative_path(&manifest.install.relative_path, "install.relativePath")?;
        validate_safe_relative_path(
            &manifest.install.activation.active_path,
            "install.activation.activePath",
        )?;
        validate_safe_relative_path(
            &manifest.install.activation.staging_path,
            "install.activation.stagingPath",
        )?;
        validate_safe_relative_path(
            &manifest.install.activation.metadata_path,
            "install.activation.metadataPath",
        )?;
        let component_prefix = format!("{}/", manifest.component.id);
        let expected_install_path =
            format!("{}/{}", manifest.component.id, manifest.component.version);
        let expected_metadata_path = format!("{}activation.json", component_prefix);
        if manifest.install.relative_path != expected_install_path
            || manifest.install.activation.metadata_path != expected_metadata_path
            || manifest.rollback.metadata_path != expected_metadata_path
            || !manifest
                .install
                .activation
                .active_path
                .starts_with(&component_prefix)
            || !manifest
                .install
                .activation
                .staging_path
                .starts_with(&component_prefix)
        {
            return Err(ComponentError::new(
                "INSTALL_LAYOUT_UNSAFE",
                "Component install and activation paths must remain inside its own versioned ProgramData scope.",
                false,
            ));
        }
        if manifest.install.root_kind != "program-data-components"
            || !manifest.install.immutable
            || manifest.install.activation.strategy != "stage-then-atomic-rename"
            || !manifest.install.activation.atomic_commit
        {
            return Err(ComponentError::new(
                "INSTALL_LAYOUT_UNSAFE",
                "The manifest does not use the immutable ProgramData stage-then-atomic-rename layout.",
                false,
            ));
        }
        validate_safe_relative_path(
            &manifest.entrypoint.relative_path,
            "entrypoint.relativePath",
        )?;
        if let Some(working_directory) = &manifest.entrypoint.working_directory {
            validate_safe_relative_path(working_directory, "entrypoint.workingDirectory")?;
        }
        if !matches!(manifest.entrypoint.kind.as_str(), "executable" | "script") {
            return Err(ComponentError::new(
                "ENTRYPOINT_INVALID",
                "Entrypoint kind must be executable or script.",
                false,
            ));
        }
        if manifest
            .entrypoint
            .arguments
            .iter()
            .any(|argument| argument.contains('\0'))
        {
            return Err(ComponentError::new(
                "ENTRYPOINT_INVALID",
                "Entrypoint arguments cannot contain NUL characters.",
                false,
            ));
        }
        if manifest.dependencies.iter().any(|dependency| {
            validate_component_id(&dependency.id).is_err()
                || VersionReq::parse(&dependency.version_constraint).is_err()
        }) {
            return Err(ComponentError::new(
                "DEPENDENCY_CONSTRAINT_INVALID",
                "At least one dependency id or version constraint is invalid.",
                false,
            ));
        }
        if manifest.capabilities.is_empty()
            || manifest.metadata.display_name.trim().is_empty()
            || manifest.metadata.publisher.trim().is_empty()
        {
            return Err(ComponentError::new(
                "MANIFEST_SCHEMA_INVALID",
                "A component must declare a display name, publisher, and capability.",
                false,
            ));
        }
        validate_https_url(
            &manifest.metadata.source.repository_url,
            "metadata.source.repositoryUrl",
        )?;
        validate_https_url(
            &manifest.metadata.source.release_url,
            "metadata.source.releaseUrl",
        )?;
        validate_safe_relative_path(
            &manifest.metadata.license.notice_file,
            "metadata.license.noticeFile",
        )?;
        validate_safe_relative_path(&manifest.rollback.metadata_path, "rollback.metadataPath")?;
        if manifest.rollback.strategy != "retain-previous-active"
            || !(1..=5).contains(&manifest.rollback.retention_count)
            || !matches!(
                manifest.rollback.on_activation_failure.as_str(),
                "rollback-automatically" | "mark-failed"
            )
        {
            return Err(ComponentError::new(
                "ROLLBACK_POLICY_INVALID",
                "The manifest rollback policy is not supported.",
                false,
            ));
        }
        if manifest.self_test.command.is_empty()
            || !(1_000..=600_000).contains(&manifest.self_test.timeout_ms)
            || manifest.self_test.expected_exit_code != 0
            || manifest.health.probe != "http"
            || manifest.health.method != "GET"
            || !manifest.health.path.starts_with('/')
            || !(100..=60_000).contains(&manifest.health.timeout_ms)
            || manifest.health.readiness_schema_version != "desktop.health-readiness.v1"
            || !manifest.health.requires_bearer_token
        {
            return Err(ComponentError::new(
                "SELF_TEST_OR_HEALTH_INVALID",
                "The self-test or health contract is incompatible with the Phase 3 manager.",
                false,
            ));
        }
        validate_inventory_shape(&manifest.files)?;
        Ok(())
    }

    fn catalog_path(&self, component_id: &str, version: &str) -> ManagerResult<PathBuf> {
        validate_component_id(component_id)?;
        parse_version(version, "component.version")?;
        let path = self
            .paths
            .catalog_root
            .join(component_id)
            .join(format!("{version}.json"));
        ensure_child_path(&self.paths.catalog_root, &path)?;
        Ok(path)
    }

    fn manifest_path(&self, component_id: &str, version: &str) -> ManagerResult<PathBuf> {
        self.catalog_path(component_id, version)
    }

    fn read_manifest(
        &self,
        component_id: &str,
        version: &str,
        policy: SourcePolicy,
    ) -> ManagerResult<ComponentManifest> {
        let path = self.manifest_path(component_id, version)?;
        let bytes = fs::read(&path).map_err(|error| {
            if error.kind() == io::ErrorKind::NotFound {
                ComponentError::new(
                    "MANIFEST_NOT_FOUND",
                    "No catalog manifest is installed for this component version.",
                    false,
                )
            } else {
                storage_error(&path, error)
            }
        })?;
        if bytes.len() > MAX_MANIFEST_BYTES {
            return Err(ComponentError::new(
                "MANIFEST_TOO_LARGE",
                "The catalog manifest exceeds the bounded intake size.",
                false,
            ));
        }
        let manifest: ComponentManifest = serde_json::from_slice(&bytes).map_err(|error| {
            ComponentError::new(
                "MANIFEST_SCHEMA_INVALID",
                format!("The stored catalog manifest is invalid: {error}"),
                false,
            )
        })?;
        if manifest.component.id != component_id || manifest.component.version != version {
            return Err(ComponentError::new(
                "MANIFEST_ID_MISMATCH",
                "The catalog path and manifest identity do not match.",
                false,
            ));
        }
        self.validate_manifest(&manifest, policy)?;
        Ok(manifest)
    }
}

impl ComponentManager {
    pub fn resolve_plan(
        &self,
        component_id: &str,
        target_version: Option<&str>,
        policy: SourcePolicy,
    ) -> ManagerResult<InstallationPlan> {
        validate_component_id(component_id)?;
        let versions = self.catalog_versions(component_id)?;
        if versions.is_empty() {
            return Err(ComponentError::new(
                "MANIFEST_NOT_FOUND",
                "No compatible catalog versions are available for this component.",
                false,
            ));
        }
        let selected_version = if let Some(target) = target_version {
            parse_version(target, "targetVersion")?;
            if !versions.iter().any(|version| version == target) {
                return Err(ComponentError::new(
                    "MANIFEST_NOT_FOUND",
                    format!("No catalog manifest is available for {component_id} {target}."),
                    false,
                ));
            }
            target.to_string()
        } else {
            versions
                .iter()
                .rev()
                .find(|version| self.read_manifest(component_id, version, policy).is_ok())
                .cloned()
                .ok_or_else(|| {
                    ComponentError::new(
                        "NO_COMPATIBLE_VERSION",
                        "No catalog version is compatible with this shell and platform.",
                        false,
                    )
                })?
        };
        let manifest = self.read_manifest(component_id, &selected_version, policy)?;
        let mut dependencies = Vec::with_capacity(manifest.dependencies.len());
        for dependency in &manifest.dependencies {
            let resolved_version =
                self.read_activation(&dependency.id)?
                    .and_then(|(_, activation)| {
                        Version::parse(&activation.component_version)
                            .ok()
                            .filter(|version| {
                                VersionReq::parse(&dependency.version_constraint)
                                    .map(|requirement| requirement.matches(version))
                                    .unwrap_or(false)
                            })
                            .map(|_| activation.component_version)
                    });
            if resolved_version.is_none() && !dependency.optional {
                return Err(ComponentError::new(
                    "DEPENDENCY_UNSATISFIED",
                    format!(
                        "Required dependency {} {} is not active.",
                        dependency.id, dependency.version_constraint
                    ),
                    false,
                ));
            }
            dependencies.push(DependencyPlanItem {
                id: dependency.id.clone(),
                version_constraint: dependency.version_constraint.clone(),
                resolved_version,
                optional: dependency.optional,
            });
        }
        Ok(InstallationPlan {
            component_id: manifest.component.id,
            target_version: manifest.component.version,
            artifact_bytes: manifest.artifact.byte_size,
            requires_elevation: manifest.requirements.requires_elevation,
            dependencies,
        })
    }

    /// Resolve an active component for a process launch without performing
    /// any activation or fallback discovery.  In particular, this never
    /// searches PATH, Docker, or a global tool installation.
    pub fn verified_active_component(
        &self,
        component_id: &str,
        expected_type: ComponentType,
        policy: SourcePolicy,
    ) -> ManagerResult<VerifiedActiveComponent> {
        validate_component_id(component_id)?;
        let Some((metadata_path, activation)) = self.read_activation(component_id)? else {
            return Err(ComponentError::new(
                "COMPONENT_NOT_ACTIVE",
                format!("No active {component_id} component is selected in ProgramData."),
                false,
            ));
        };
        if activation.state != "active"
            || activation.component_id != component_id
            || activation.component_version.is_empty()
        {
            return Err(ComponentError::new(
                "ACTIVATION_METADATA_INVALID",
                "The component activation record is not at a valid active checkpoint.",
                false,
            ));
        }

        let manifest = self.read_manifest(component_id, &activation.component_version, policy)?;
        if manifest.component.id != component_id
            || manifest.component.version != activation.component_version
            || manifest.component.component_type != expected_type
        {
            return Err(ComponentError::new(
                "COMPONENT_VERSION_INCOMPATIBLE",
                "The active component identity does not match its signed manifest.",
                false,
            ));
        }
        if expected_type == ComponentType::Backend && manifest.entrypoint.kind != "executable" {
            return Err(ComponentError::new(
                "ENTRYPOINT_INVALID",
                "The active core-engine component must expose a native executable entrypoint.",
                false,
            ));
        }
        let active_path = PathBuf::from(&activation.active_path);
        ensure_safe_existing_path(&self.paths.components_root, &active_path)?;
        let expected_active_path = self.published_path(&manifest)?;
        if path_key(&active_path.to_string_lossy())
            != path_key(&expected_active_path.to_string_lossy())
        {
            return Err(ComponentError::new(
                "ACTIVATION_METADATA_INVALID",
                "The active path does not match the immutable version selected by the manifest.",
                false,
            ));
        }
        verify_installed_inventory(&active_path, &manifest)?;

        let executable_path = active_path.join(&manifest.entrypoint.relative_path);
        ensure_safe_existing_path(&active_path, &executable_path)?;
        if !executable_path.is_file() || is_reparse_or_symlink(&executable_path) {
            return Err(ComponentError::new(
                "ENTRYPOINT_MISSING",
                "The signed component entrypoint is missing or unsafe.",
                false,
            ));
        }
        let working_directory = if let Some(relative) = &manifest.entrypoint.working_directory {
            let path = active_path.join(relative);
            ensure_safe_existing_path(&active_path, &path)?;
            if !path.is_dir() || is_reparse_or_symlink(&path) {
                return Err(ComponentError::new(
                    "WORKING_DIRECTORY_INVALID",
                    "The signed component working directory is missing or unsafe.",
                    false,
                ));
            }
            Some(path.to_string_lossy().to_string())
        } else {
            None
        };

        Ok(VerifiedActiveComponent {
            component_id: manifest.component.id,
            component_version: manifest.component.version,
            active_path: active_path.to_string_lossy().to_string(),
            executable_path: executable_path.to_string_lossy().to_string(),
            entrypoint: manifest.entrypoint.relative_path,
            arguments: manifest.entrypoint.arguments,
            working_directory,
            capabilities: manifest.capabilities,
            manifest_path: metadata_path.to_string_lossy().to_string(),
        })
    }

    pub fn status(&self, component_id: Option<&str>) -> ManagerResult<Vec<ComponentStatusResult>> {
        let ids = if let Some(component_id) = component_id {
            validate_component_id(component_id)?;
            vec![component_id.to_string()]
        } else {
            self.catalog_component_ids()?
        };
        let mut statuses = Vec::new();
        for id in ids {
            let activation = self.read_activation(&id)?;
            let manifest = self.latest_catalog_manifest_unvalidated(&id)?;
            let download = self.latest_download_state(&id)?;
            let status = if let Some((_, activation)) = &activation {
                let exact_manifest = self
                    .read_manifest(
                        &id,
                        &activation.component_version,
                        SourcePolicy::OFFLINE_IMPORT,
                    )
                    .ok();
                let active_verified = activation.state == "active"
                    && exact_manifest.as_ref().is_some_and(|manifest| {
                        verify_installed_inventory(Path::new(&activation.active_path), manifest)
                            .is_ok()
                    });
                if active_verified {
                    ComponentStatusResult {
                        id: id.clone(),
                        display_name: manifest
                            .as_ref()
                            .map(|manifest| manifest.metadata.display_name.clone()),
                        version: Some(activation.component_version.clone()),
                        state: "active".to_string(),
                        active_path: Some(activation.active_path.clone()),
                        downloaded_bytes: 0,
                        detail: "A verified immutable version is atomically selected.".to_string(),
                        remediation_codes: Vec::new(),
                    }
                } else {
                    ComponentStatusResult {
                        id: id.clone(),
                        display_name: manifest
                            .as_ref()
                            .map(|manifest| manifest.metadata.display_name.clone()),
                        version: Some(activation.component_version.clone()),
                        state: "repair-required".to_string(),
                        active_path: Some(activation.active_path.clone()),
                        downloaded_bytes: 0,
                        detail:
                            "Activation metadata exists but the selected version is not readable."
                                .to_string(),
                        remediation_codes: vec!["COMPONENT_VERSION_INCOMPATIBLE".to_string()],
                    }
                }
            } else if let Some(download) = download {
                ComponentStatusResult {
                    id: id.clone(),
                    display_name: manifest
                        .as_ref()
                        .map(|manifest| manifest.metadata.display_name.clone()),
                    version: Some(download.component_version),
                    state: download.status,
                    active_path: None,
                    downloaded_bytes: download.bytes_downloaded,
                    detail: "A bounded resumable download state is present.".to_string(),
                    remediation_codes: Vec::new(),
                }
            } else if manifest.is_some() {
                ComponentStatusResult {
                    id: id.clone(),
                    display_name: manifest
                        .as_ref()
                        .map(|manifest| manifest.metadata.display_name.clone()),
                    version: manifest.map(|manifest| manifest.component.version),
                    state: "available".to_string(),
                    active_path: None,
                    downloaded_bytes: 0,
                    detail: "A signed catalog manifest is available for installation.".to_string(),
                    remediation_codes: vec!["SETUP_REQUIRED".to_string()],
                }
            } else {
                ComponentStatusResult {
                    id: id.clone(),
                    display_name: None,
                    version: None,
                    state: "not-installed".to_string(),
                    active_path: None,
                    downloaded_bytes: 0,
                    detail: "No catalog or activation record is present.".to_string(),
                    remediation_codes: vec!["SETUP_REQUIRED".to_string()],
                }
            };
            statuses.push(status);
        }
        Ok(statuses)
    }

    pub(crate) fn download(
        &self,
        component_id: &str,
        component_version: &str,
        policy: SourcePolicy,
        operation_id: Option<String>,
        control: OperationControl,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<DownloadResult> {
        let _lock = self.acquire_lock()?;
        let manifest = self.read_manifest(component_id, component_version, policy)?;
        self.ensure_machine_storage()?;
        let operation_id = operation_id.unwrap_or_else(|| {
            format!(
                "component-{}-{}-{}",
                component_id,
                component_version.replace('.', "-"),
                now_epoch_ms()
            )
        });
        let (part_path, archive_path, state_path) =
            self.download_paths(component_id, component_version)?;
        ensure_free_space(&self.paths.downloads_root, manifest.artifact.byte_size)?;
        let mut state = self
            .read_download_state(&state_path)?
            .unwrap_or_else(|| DownloadState {
                schema_version: DOWNLOAD_STATE_SCHEMA.to_string(),
                operation_id: operation_id.clone(),
                component_id: component_id.to_string(),
                component_version: component_version.to_string(),
                url: manifest.artifact.url.clone(),
                expected_bytes: manifest.artifact.byte_size,
                bytes_downloaded: 0,
                sha256: manifest.artifact.sha256.clone(),
                temp_path: part_path.to_string_lossy().to_string(),
                archive_path: archive_path.to_string_lossy().to_string(),
                resumable: true,
                status: "interrupted".to_string(),
                recovery: DownloadRecovery {
                    status: "none".to_string(),
                    resume_from_byte: 0,
                    last_verified_byte: 0,
                    etag: None,
                },
            });
        state.operation_id = operation_id.clone();
        state.status = "downloading".to_string();
        state.recovery.status = "resume-available".to_string();
        state.recovery.resume_from_byte = 0;
        state.recovery.last_verified_byte = 0;
        if part_path.exists() {
            let part_size = fs::metadata(&part_path)
                .map_err(|error| storage_error(&part_path, error))?
                .len();
            if part_size > manifest.artifact.byte_size {
                fs::remove_file(&part_path).map_err(|error| storage_error(&part_path, error))?;
                state.bytes_downloaded = 0;
            } else {
                state.bytes_downloaded = part_size;
                state.recovery.resume_from_byte = part_size;
            }
        } else {
            state.bytes_downloaded = 0;
        }
        let resumed = state.bytes_downloaded > 0;
        self.persist_download_state(&state_path, &state)?;
        emit_progress(
            progress,
            ComponentProgress {
                operation_id: operation_id.clone(),
                component_id: component_id.to_string(),
                component_version: component_version.to_string(),
                operation: "download".to_string(),
                state: "downloading".to_string(),
                bytes_downloaded: state.bytes_downloaded,
                total_bytes: manifest.artifact.byte_size,
                percent: percentage(state.bytes_downloaded, manifest.artifact.byte_size),
                message: if resumed {
                    "Resuming the verified staging cursor.".to_string()
                } else {
                    "Starting a bounded component download.".to_string()
                },
            },
        );

        let mut final_error = None;
        for attempt in 0..MAX_DOWNLOAD_RETRIES {
            match self.download_once(
                &manifest,
                &part_path,
                &state_path,
                &mut state,
                &control,
                policy,
                progress,
            ) {
                Ok(()) => {
                    final_error = None;
                    break;
                }
                Err(error) if error.code == "DOWNLOAD_PAUSED" => {
                    state.status = "paused".to_string();
                    self.persist_download_state(&state_path, &state)?;
                    return Err(error);
                }
                Err(error) if error.code == "DOWNLOAD_CANCELLED" => {
                    state.status = "cancelled".to_string();
                    self.persist_download_state(&state_path, &state)?;
                    return Err(error);
                }
                Err(error) if error.retryable && attempt + 1 < MAX_DOWNLOAD_RETRIES => {
                    final_error = Some(error);
                    thread::sleep(RETRY_BACKOFF[attempt]);
                }
                Err(error) => {
                    final_error = Some(error);
                    break;
                }
            }
        }
        if let Some(error) = final_error {
            state.status = "interrupted".to_string();
            state.recovery.status = "resume-available".to_string();
            state.recovery.resume_from_byte = state.bytes_downloaded;
            self.persist_download_state(&state_path, &state)?;
            return Err(error);
        }
        if state.bytes_downloaded != manifest.artifact.byte_size {
            return Err(ComponentError::new(
                "ARTIFACT_SIZE_MISMATCH",
                format!(
                    "Downloaded {} bytes but manifest requires {}.",
                    state.bytes_downloaded, manifest.artifact.byte_size
                ),
                false,
            ));
        }
        if archive_path.exists() {
            fs::remove_file(&archive_path).map_err(|error| storage_error(&archive_path, error))?;
        }
        fs::rename(&part_path, &archive_path)
            .map_err(|error| storage_error(&archive_path, error))?;
        state.status = "downloaded".to_string();
        state.bytes_downloaded = manifest.artifact.byte_size;
        state.recovery.status = "none".to_string();
        state.recovery.resume_from_byte = manifest.artifact.byte_size;
        state.recovery.last_verified_byte = manifest.artifact.byte_size;
        self.persist_download_state(&state_path, &state)?;
        emit_progress(
            progress,
            ComponentProgress {
                operation_id: operation_id.clone(),
                component_id: component_id.to_string(),
                component_version: component_version.to_string(),
                operation: "download".to_string(),
                state: "downloaded".to_string(),
                bytes_downloaded: manifest.artifact.byte_size,
                total_bytes: manifest.artifact.byte_size,
                percent: 100.0,
                message: "Component archive download completed.".to_string(),
            },
        );
        Ok(DownloadResult {
            operation_id,
            component_id: component_id.to_string(),
            component_version: component_version.to_string(),
            archive_path: archive_path.to_string_lossy().to_string(),
            bytes_downloaded: manifest.artifact.byte_size,
            resumed,
            state: "downloaded".to_string(),
        })
    }

    pub(crate) fn retry_download(
        &self,
        component_id: &str,
        component_version: &str,
        operation_id: Option<String>,
        policy: SourcePolicy,
        control: OperationControl,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<DownloadResult> {
        self.download(
            component_id,
            component_version,
            policy,
            operation_id,
            control,
            progress,
        )
    }

    fn download_once(
        &self,
        manifest: &ComponentManifest,
        part_path: &Path,
        state_path: &Path,
        state: &mut DownloadState,
        control: &OperationControl,
        policy: SourcePolicy,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<()> {
        let mut offset = state.bytes_downloaded;
        if offset == 0 {
            let file = OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .open(part_path)
                .map_err(|error| storage_error(part_path, error))?;
            file.sync_data()
                .map_err(|error| storage_error(part_path, error))?;
        }
        let parsed_url = Url::parse(&manifest.artifact.url).map_err(|error| {
            ComponentError::new(
                "URL_INVALID",
                format!("Could not parse artifact URL: {error}"),
                false,
            )
        })?;
        let offline_source_path = if parsed_url.scheme() == "offline" {
            Some(self.resolve_offline_artifact_path(&manifest.artifact.url)?)
        } else {
            None
        };
        let mut response = if offline_source_path.is_some() || parsed_url.scheme() == "file" {
            None
        } else {
            Some(open_http_response(&manifest.artifact.url, offset, policy)?)
        };
        if let Some(http_response) = &mut response {
            if offset > 0 && http_response.status() == reqwest::StatusCode::OK {
                offset = 0;
                let file = OpenOptions::new()
                    .write(true)
                    .truncate(true)
                    .open(part_path)
                    .map_err(|error| storage_error(part_path, error))?;
                file.sync_data()
                    .map_err(|error| storage_error(part_path, error))?;
            } else if offset > 0 && http_response.status() != reqwest::StatusCode::PARTIAL_CONTENT {
                return Err(ComponentError::new(
                    "RANGE_RESUME_REJECTED",
                    "The artifact server did not honor the resumable range request.",
                    true,
                ));
            }
            if let Some(etag) = http_response.headers().get(reqwest::header::ETAG) {
                state.recovery.etag = etag.to_str().ok().map(ToOwned::to_owned);
            }
        }
        state.bytes_downloaded = offset;
        state.recovery.resume_from_byte = offset;
        let mut writer = OpenOptions::new()
            .create(true)
            .write(true)
            .append(true)
            .open(part_path)
            .map_err(|error| storage_error(part_path, error))?;
        let mut buffer = vec![0_u8; DOWNLOAD_BUFFER_BYTES];
        loop {
            if control.cancel.load(Ordering::Relaxed) {
                return Err(ComponentError::new(
                    "DOWNLOAD_CANCELLED",
                    "The component download was cancelled before activation.",
                    false,
                ));
            }
            if control.pause.load(Ordering::Relaxed) {
                state.recovery.status = "resume-available".to_string();
                state.recovery.resume_from_byte = state.bytes_downloaded;
                self.persist_download_state(state_path, state)?;
                return Err(ComponentError::new(
                    "DOWNLOAD_PAUSED",
                    "The component download is paused and can be resumed from ProgramData staging.",
                    true,
                ));
            }
            let read = if let Some(http_response) = &mut response {
                http_response.read(&mut buffer).map_err(|error| {
                    ComponentError::new("DOWNLOAD_NETWORK_FAILED", error.to_string(), true)
                })?
            } else {
                let source_path = if let Some(path) = &offline_source_path {
                    path.clone()
                } else {
                    parsed_url.to_file_path().map_err(|_| {
                        ComponentError::new(
                            "TEST_SOURCE_INVALID",
                            "The file URL did not resolve to a local path.",
                            false,
                        )
                    })?
                };
                let mut source =
                    File::open(&source_path).map_err(|error| storage_error(&source_path, error))?;
                source
                    .seek(SeekFrom::Start(state.bytes_downloaded))
                    .map_err(|error| storage_error(&source_path, error))?;
                let read = source
                    .read(&mut buffer)
                    .map_err(|error| storage_error(&source_path, error))?;
                if read > 0 {
                    writer
                        .write_all(&buffer[..read])
                        .map_err(|error| storage_error(part_path, error))?;
                    state.bytes_downloaded = state.bytes_downloaded.saturating_add(read as u64);
                }
                if read == 0 {
                    break;
                }
                persist_download_progress(self, state_path, state, progress)?;
                continue;
            };
            if read == 0 {
                break;
            }
            writer
                .write_all(&buffer[..read])
                .map_err(|error| storage_error(part_path, error))?;
            state.bytes_downloaded = state.bytes_downloaded.saturating_add(read as u64);
            if state.bytes_downloaded > manifest.artifact.byte_size {
                return Err(ComponentError::new(
                    "ARTIFACT_BYTE_LIMIT_EXCEEDED",
                    "The download exceeded the manifest byte size and was stopped.",
                    false,
                ));
            }
            persist_download_progress(self, state_path, state, progress)?;
        }
        writer
            .sync_all()
            .map_err(|error| storage_error(part_path, error))?;
        Ok(())
    }

    fn download_paths(
        &self,
        component_id: &str,
        component_version: &str,
    ) -> ManagerResult<(PathBuf, PathBuf, PathBuf)> {
        validate_component_id(component_id)?;
        parse_version(component_version, "component.version")?;
        let directory = self.paths.downloads_root.join(component_id);
        let part = directory.join(format!("{component_version}.part"));
        let archive = directory.join(format!("{component_version}.archive"));
        let state = directory.join(format!("{component_version}.state.json"));
        for path in [&directory, &part, &archive, &state] {
            ensure_child_path(&self.paths.downloads_root, path)?;
        }
        Ok((part, archive, state))
    }

    fn persist_download_state(&self, path: &Path, state: &DownloadState) -> ManagerResult<()> {
        atomic_write_json(path, state)
    }

    fn read_download_state(&self, path: &Path) -> ManagerResult<Option<DownloadState>> {
        if !path.exists() {
            return Ok(None);
        }
        let bytes = fs::read(path).map_err(|error| storage_error(path, error))?;
        let state: DownloadState = serde_json::from_slice(&bytes).map_err(|error| {
            ComponentError::new(
                "DOWNLOAD_STATE_INVALID",
                format!("The resumable download state is invalid: {error}"),
                false,
            )
        })?;
        if state.schema_version != DOWNLOAD_STATE_SCHEMA {
            return Err(ComponentError::new(
                "DOWNLOAD_STATE_INCOMPATIBLE",
                "The resumable download state schema is not supported.",
                false,
            ));
        }
        Ok(Some(state))
    }

    fn latest_download_state(&self, component_id: &str) -> ManagerResult<Option<DownloadState>> {
        let directory = self.paths.downloads_root.join(component_id);
        if !directory.exists() {
            return Ok(None);
        }
        let mut states = Vec::new();
        for entry in fs::read_dir(&directory).map_err(|error| storage_error(&directory, error))? {
            let entry = entry.map_err(|error| storage_error(&directory, error))?;
            if entry
                .path()
                .extension()
                .and_then(|extension| extension.to_str())
                != Some("json")
            {
                continue;
            }
            if let Ok(Some(state)) = self.read_download_state(&entry.path()) {
                states.push(state);
            }
        }
        states.sort_by(|left, right| left.component_version.cmp(&right.component_version));
        Ok(states.pop())
    }

    pub fn recover_downloads(&self) -> ManagerResult<usize> {
        self.ensure_machine_storage()?;
        let mut count = 0;
        if !self.paths.downloads_root.exists() {
            return Ok(0);
        }
        for component in fs::read_dir(&self.paths.downloads_root)
            .map_err(|error| storage_error(&self.paths.downloads_root, error))?
        {
            let component =
                component.map_err(|error| storage_error(&self.paths.downloads_root, error))?;
            if !component.path().is_dir() || is_reparse_or_symlink(&component.path()) {
                continue;
            }
            for entry in fs::read_dir(component.path())
                .map_err(|error| storage_error(&component.path(), error))?
            {
                let entry = entry.map_err(|error| storage_error(&component.path(), error))?;
                if entry
                    .path()
                    .extension()
                    .and_then(|extension| extension.to_str())
                    != Some("json")
                {
                    continue;
                }
                let Some(mut state) = self.read_download_state(&entry.path())? else {
                    continue;
                };
                let part = PathBuf::from(&state.temp_path);
                if part.exists() {
                    let size = fs::metadata(&part)
                        .map_err(|error| storage_error(&part, error))?
                        .len();
                    if size <= state.expected_bytes {
                        state.bytes_downloaded = size;
                        state.recovery.status = if size > 0 {
                            "resume-available".to_string()
                        } else {
                            "restart-required".to_string()
                        };
                        state.recovery.resume_from_byte = size;
                        state.status = "interrupted".to_string();
                        self.persist_download_state(&entry.path(), &state)?;
                        count += 1;
                    }
                }
            }
        }
        Ok(count)
    }

    pub fn verify(
        &self,
        component_id: &str,
        component_version: &str,
        policy: SourcePolicy,
    ) -> ManagerResult<VerificationResult> {
        let _lock = self.acquire_lock()?;
        let manifest = self.read_manifest(component_id, component_version, policy)?;
        let result = self.verify_artifact(&manifest)?;
        let verification_root = self
            .paths
            .components_root
            .join(component_id)
            .join(".verification")
            .join(format!("{}-{}", component_version, now_epoch_ms()));
        ensure_child_path(&self.paths.components_root, &verification_root)?;
        fs::create_dir_all(&verification_root)
            .map_err(|error| storage_error(&verification_root, error))?;
        let extraction = extract_archive(
            &self.archive_path(&manifest)?,
            &manifest,
            &verification_root,
        );
        let _ = fs::remove_dir_all(&verification_root);
        let extraction = extraction?;
        Ok(VerificationResult {
            component_id: manifest.component.id,
            component_version: manifest.component.version,
            artifact_bytes: result.0,
            artifact_sha256: result.1,
            signature_key_id: manifest.signature.key_id,
            inventory_entries: extraction,
            state: "verified".to_string(),
        })
    }

    pub fn stage(
        &self,
        component_id: &str,
        component_version: &str,
        policy: SourcePolicy,
        operation_id: Option<String>,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<StageResult> {
        let _lock = self.acquire_lock()?;
        let manifest = self.read_manifest(component_id, component_version, policy)?;
        self.resolve_plan(component_id, Some(component_version), policy)?;
        let (artifact_bytes, artifact_sha256) = self.verify_artifact(&manifest)?;
        let operation_id = operation_id.unwrap_or_else(|| {
            format!(
                "stage-{}-{}-{}",
                component_id,
                component_version.replace('.', "-"),
                now_epoch_ms()
            )
        });
        let stage_path = self
            .paths
            .components_root
            .join(component_id)
            .join(".staging")
            .join(format!("{component_version}-{operation_id}"));
        ensure_child_path(&self.paths.components_root, &stage_path)?;
        if stage_path.exists() {
            fs::remove_dir_all(&stage_path).map_err(|error| storage_error(&stage_path, error))?;
        }
        fs::create_dir_all(&stage_path).map_err(|error| storage_error(&stage_path, error))?;
        let published_path = self.published_path(&manifest)?;
        let metadata_path = self.metadata_path(&manifest)?;
        let journal_path = self.journal_path(&operation_id)?;
        let manifest_path = self.manifest_path(component_id, component_version)?;
        let previous = self.read_activation(component_id)?;
        let mut journal = ActivationJournal {
            schema_version: ACTIVATION_SCHEMA.to_string(),
            operation_id: operation_id.clone(),
            component_id: component_id.to_string(),
            component_version: component_version.to_string(),
            manifest_path: manifest_path.to_string_lossy().to_string(),
            stage_path: stage_path.to_string_lossy().to_string(),
            published_path: published_path.to_string_lossy().to_string(),
            metadata_path: metadata_path.to_string_lossy().to_string(),
            checkpoint: "verifying".to_string(),
            previous_version: previous
                .as_ref()
                .map(|(_, value)| value.component_version.clone()),
            previous_path: previous
                .as_ref()
                .map(|(_, value)| value.active_path.clone()),
            updated_at_epoch_ms: now_epoch_ms(),
        };
        atomic_write_json(&journal_path, &journal)?;
        emit_progress(
            progress,
            ComponentProgress {
                operation_id: operation_id.clone(),
                component_id: component_id.to_string(),
                component_version: component_version.to_string(),
                operation: "stage".to_string(),
                state: "verifying".to_string(),
                bytes_downloaded: artifact_bytes,
                total_bytes: artifact_bytes,
                percent: 100.0,
                message: format!("Verified archive SHA-256 {artifact_sha256}."),
            },
        );
        let inventory_entries =
            match extract_archive(&self.archive_path(&manifest)?, &manifest, &stage_path) {
                Ok(entries) => entries,
                Err(error) => {
                    journal.checkpoint = "failed".to_string();
                    journal.updated_at_epoch_ms = now_epoch_ms();
                    let _ = atomic_write_json(&journal_path, &journal);
                    let _ = fs::remove_dir_all(&stage_path);
                    return Err(error);
                }
            };
        journal.checkpoint = "staged".to_string();
        journal.updated_at_epoch_ms = now_epoch_ms();
        atomic_write_json(&journal_path, &journal)?;
        run_manifest_self_test(&manifest, &stage_path)?;
        emit_progress(
            progress,
            ComponentProgress {
                operation_id: operation_id.clone(),
                component_id: component_id.to_string(),
                component_version: component_version.to_string(),
                operation: "stage".to_string(),
                state: "staged".to_string(),
                bytes_downloaded: artifact_bytes,
                total_bytes: artifact_bytes,
                percent: 100.0,
                message: "Archive inventory and constrained self-test passed.".to_string(),
            },
        );
        Ok(StageResult {
            component_id: component_id.to_string(),
            component_version: component_version.to_string(),
            operation_id,
            stage_path: stage_path.to_string_lossy().to_string(),
            inventory_entries,
            state: "staged".to_string(),
        })
    }

    fn verify_artifact(&self, manifest: &ComponentManifest) -> ManagerResult<(u64, String)> {
        let archive_path = self.archive_path(manifest)?;
        if !archive_path.exists() {
            return Err(ComponentError::new(
                "ARCHIVE_NOT_DOWNLOADED",
                "Download the exact manifest artifact before verification.",
                true,
            ));
        }
        let metadata =
            fs::metadata(&archive_path).map_err(|error| storage_error(&archive_path, error))?;
        if metadata.len() != manifest.artifact.byte_size {
            return Err(ComponentError::new(
                "ARTIFACT_SIZE_MISMATCH",
                format!(
                    "Archive is {} bytes but the manifest requires {}.",
                    metadata.len(),
                    manifest.artifact.byte_size
                ),
                false,
            ));
        }
        let (bytes, digest) = write_file_hash(&archive_path)?;
        if digest != manifest.artifact.sha256 {
            return Err(ComponentError::new(
                "ARTIFACT_HASH_MISMATCH",
                format!("Archive SHA-256 {digest} does not match the signed manifest digest."),
                false,
            ));
        }
        Ok((bytes, digest))
    }

    fn archive_path(&self, manifest: &ComponentManifest) -> ManagerResult<PathBuf> {
        let (_, archive, _) =
            self.download_paths(&manifest.component.id, &manifest.component.version)?;
        ensure_child_path(&self.paths.downloads_root, &archive)?;
        Ok(archive)
    }

    fn published_path(&self, manifest: &ComponentManifest) -> ManagerResult<PathBuf> {
        let path = self
            .paths
            .components_root
            .join(&manifest.install.relative_path);
        ensure_child_path(&self.paths.components_root, &path)?;
        Ok(path)
    }

    fn metadata_path(&self, manifest: &ComponentManifest) -> ManagerResult<PathBuf> {
        let path = self
            .paths
            .activation_root
            .join(&manifest.rollback.metadata_path);
        ensure_child_path(&self.paths.activation_root, &path)?;
        Ok(path)
    }

    fn journal_path(&self, operation_id: &str) -> ManagerResult<PathBuf> {
        if operation_id.is_empty()
            || operation_id.len() > 128
            || !operation_id
                .chars()
                .all(|character| character.is_ascii_alphanumeric() || "-_.".contains(character))
        {
            return Err(ComponentError::new(
                "OPERATION_ID_INVALID",
                "Operation ids must be short safe ASCII identifiers.",
                false,
            ));
        }
        let path = self.paths.journal_root.join(format!("{operation_id}.json"));
        ensure_child_path(&self.paths.journal_root, &path)?;
        Ok(path)
    }

    pub fn activate(
        &self,
        component_id: &str,
        component_version: &str,
        policy: SourcePolicy,
        operation_id: Option<String>,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<ActivationResult> {
        if crate::component_broker::should_delegate_for(self.machine_root()) {
            let request_id = operation_id
                .clone()
                .unwrap_or_else(|| format!("activate-{}", now_epoch_ms()));
            return crate::component_broker::delegate(crate::component_broker::BrokerRequest {
                schema_version: crate::component_broker::BROKER_SCHEMA.to_string(),
                request_id,
                operation: crate::component_broker::BrokerOperation::Activate,
                component_id: Some(component_id.to_string()),
                component_version: Some(component_version.to_string()),
                operation_id,
                allow_offline_sources: policy.allow_local_test_sources,
            });
        }
        self.activate_direct(
            component_id,
            component_version,
            policy,
            operation_id,
            progress,
        )
    }

    pub(crate) fn activate_direct(
        &self,
        component_id: &str,
        component_version: &str,
        policy: SourcePolicy,
        operation_id: Option<String>,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<ActivationResult> {
        let _lock = self.acquire_lock()?;
        let manifest = self.read_manifest(component_id, component_version, policy)?;
        let mut journal = if let Some(operation_id) = operation_id {
            let path = self.journal_path(&operation_id)?;
            let bytes = fs::read(&path).map_err(|error| storage_error(&path, error))?;
            serde_json::from_slice::<ActivationJournal>(&bytes).map_err(|error| {
                ComponentError::new(
                    "ACTIVATION_JOURNAL_INVALID",
                    format!("Activation journal is invalid: {error}"),
                    false,
                )
            })?
        } else {
            self.latest_journal(component_id, component_version)?
                .ok_or_else(|| {
                    ComponentError::new(
                        "STAGE_NOT_FOUND",
                        "Stage the verified component before activation.",
                        false,
                    )
                })?
        };
        if journal.component_id != component_id || journal.component_version != component_version {
            return Err(ComponentError::new(
                "ACTIVATION_JOURNAL_MISMATCH",
                "The activation journal does not match the requested component.",
                false,
            ));
        }
        let stage_path = PathBuf::from(&journal.stage_path);
        let published_path = self.published_path(&manifest)?;
        let metadata_path = self.metadata_path(&manifest)?;
        ensure_safe_existing_path(&self.paths.components_root, &stage_path)?;
        let journal_path = self.journal_path(&journal.operation_id)?;
        let previous = self.read_activation(component_id)?;

        // A retry after the metadata checkpoint is already successful.  The
        // inventory check is intentionally repeated here instead of trusting
        // the old metadata file, so a damaged active directory cannot be
        // reported as healthy.
        if let Some((_, active)) = &previous {
            if active.component_version == component_version
                && path_key(&active.active_path) == path_key(&published_path.to_string_lossy())
                && verify_installed_inventory(Path::new(&active.active_path), &manifest).is_ok()
            {
                journal.checkpoint = "active".to_string();
                journal.updated_at_epoch_ms = now_epoch_ms();
                atomic_write_json(&journal_path, &journal)?;
                return Ok(ActivationResult {
                    component_id: component_id.to_string(),
                    component_version: component_version.to_string(),
                    active_path: active.active_path.clone(),
                    previous_version: active.previous_version.clone(),
                    state: "already-active".to_string(),
                });
            }
        }

        // A process can die after the same-volume publish but before the
        // activation metadata commit.  A verified published directory is a
        // recoverable checkpoint, not a retry dead end
        // error.  An unverified directory is quarantined before a retry can
        // publish over it.
        if published_path.exists() {
            ensure_safe_existing_path(&self.paths.components_root, &published_path)?;
            if verify_installed_inventory(&published_path, &manifest).is_err() {
                let component_root = self.paths.components_root.join(component_id);
                let quarantine_root = component_root.join(".quarantine");
                ensure_child_path(&self.paths.components_root, &component_root)?;
                ensure_child_path(&self.paths.components_root, &quarantine_root)?;
                fs::create_dir_all(&quarantine_root)
                    .map_err(|error| storage_error(&quarantine_root, error))?;
                let quarantine_path = quarantine_root.join(format!(
                    "{}-{}",
                    component_version.replace('.', "-"),
                    journal.operation_id
                ));
                ensure_child_path(&self.paths.components_root, &quarantine_path)?;
                checkpoint_failure("quarantine")?;
                fs::rename(&published_path, &quarantine_path)
                    .map_err(|error| storage_error(&quarantine_path, error))?;
                journal.checkpoint = "quarantined".to_string();
                journal.updated_at_epoch_ms = now_epoch_ms();
                atomic_write_json(&journal_path, &journal)?;
                crate::operation_log::append_operation_event(
                    "activate",
                    "checkpoint",
                    "Conflicting published payload was quarantined inside the machine perimeter.",
                    Some(component_id),
                    Some(component_version),
                    Some("quarantined"),
                    Some("same-volume-rename"),
                );
            } else {
                // The immutable payload survived.  Remove only the matching
                // stale staging directory and reconcile its activation record.
                if stage_path.exists() {
                    fs::remove_dir_all(&stage_path)
                        .map_err(|error| storage_error(&stage_path, error))?;
                }
                journal.published_path = published_path.to_string_lossy().to_string();
                journal.checkpoint = "published".to_string();
                journal.updated_at_epoch_ms = now_epoch_ms();
                atomic_write_json(&journal_path, &journal)?;
                return self.commit_published_activation(
                    &manifest,
                    &published_path,
                    &metadata_path,
                    &mut journal,
                    &journal_path,
                    previous.as_ref(),
                    progress,
                    "recovered-published",
                );
            }
        }

        if !stage_path.is_dir() {
            return Err(ComponentError::new(
                "STAGE_NOT_FOUND",
                "The versioned immutable staging directory is missing; resume staging and retry activation.",
                true,
            ));
        }

        // Persist intent before the first mutating publish operation.  This
        // lets startup reconciliation distinguish an interrupted activation
        // from an abandoned staging directory.
        journal.checkpoint = "activation-intent".to_string();
        journal.updated_at_epoch_ms = now_epoch_ms();
        atomic_write_json(&journal_path, &journal)?;
        crate::operation_log::append_operation_event(
            "activate",
            "checkpoint",
            "Activation intent persisted before publish.",
            Some(component_id),
            Some(component_version),
            Some("activation-intent"),
            Some("journal-write"),
        );
        checkpoint_failure("activation-intent")?;
        if let Some(parent) = published_path.parent() {
            fs::create_dir_all(parent).map_err(|error| storage_error(parent, error))?;
        }
        fs::rename(&stage_path, &published_path)
            .map_err(|error| storage_error(&published_path, error))?;
        journal.published_path = published_path.to_string_lossy().to_string();
        journal.checkpoint = "published".to_string();
        journal.updated_at_epoch_ms = now_epoch_ms();
        atomic_write_json(&journal_path, &journal)?;
        crate::operation_log::append_operation_event(
            "activate",
            "checkpoint",
            "Immutable component directory published.",
            Some(component_id),
            Some(component_version),
            Some("published"),
            Some("same-volume-rename"),
        );
        checkpoint_failure("published")?;
        emit_progress(
            progress,
            ComponentProgress {
                operation_id: journal.operation_id.clone(),
                component_id: component_id.to_string(),
                component_version: component_version.to_string(),
                operation: "activate".to_string(),
                state: "published".to_string(),
                bytes_downloaded: 0,
                total_bytes: 0,
                percent: 100.0,
                message: "Published the immutable version inside ProgramData.".to_string(),
            },
        );
        self.commit_published_activation(
            &manifest,
            &published_path,
            &metadata_path,
            &mut journal,
            &journal_path,
            previous.as_ref(),
            progress,
            "active",
        )
    }

    fn commit_published_activation(
        &self,
        manifest: &ComponentManifest,
        published_path: &Path,
        metadata_path: &Path,
        journal: &mut ActivationJournal,
        journal_path: &Path,
        previous: Option<&(PathBuf, ActivationMetadata)>,
        progress: Option<&dyn Fn(ComponentProgress)>,
        state: &str,
    ) -> ManagerResult<ActivationResult> {
        verify_installed_inventory(published_path, manifest)?;
        checkpoint_failure("metadata")?;
        let metadata = ActivationMetadata {
            schema_version: ACTIVATION_SCHEMA.to_string(),
            state: "active".to_string(),
            component_id: manifest.component.id.clone(),
            component_version: manifest.component.version.clone(),
            active_path: published_path.to_string_lossy().to_string(),
            previous_version: previous.map(|(_, value)| value.component_version.clone()),
            previous_path: previous.map(|(_, value)| value.active_path.clone()),
            manifest_path: self
                .manifest_path(&manifest.component.id, &manifest.component.version)?
                .to_string_lossy()
                .to_string(),
            activated_at_epoch_ms: now_epoch_ms(),
        };
        atomic_write_json(metadata_path, &metadata)?;
        crate::operation_log::append_operation_event(
            "activate",
            "checkpoint",
            "Active metadata replaced atomically.",
            Some(&manifest.component.id),
            Some(&manifest.component.version),
            Some("metadata-written"),
            Some("atomic-replace"),
        );
        checkpoint_failure("metadata-written")?;
        journal.published_path = published_path.to_string_lossy().to_string();
        journal.checkpoint = "active".to_string();
        journal.updated_at_epoch_ms = now_epoch_ms();
        atomic_write_json(journal_path, journal)?;
        crate::operation_log::append_operation_event(
            "activate",
            "checkpoint",
            "Activation journal reached the active checkpoint.",
            Some(&manifest.component.id),
            Some(&manifest.component.version),
            Some("active"),
            Some("journal-write"),
        );
        checkpoint_failure("active")?;

        // Re-read both records after the commit.  A successful response must
        // describe the state that a fresh supervisor process would observe.
        let Some((_, committed)) = self.read_activation(&manifest.component.id)? else {
            return Err(ComponentError::new(
                "ACTIVATION_COMMIT_NOT_VISIBLE",
                "Activation metadata was written but could not be re-read.",
                true,
            ));
        };
        if committed.component_version != manifest.component.version
            || path_key(&committed.active_path) != path_key(&published_path.to_string_lossy())
        {
            return Err(ComponentError::new(
                "ACTIVATION_COMMIT_MISMATCH",
                "Activation metadata did not match the published component after commit.",
                false,
            ));
        }
        verify_installed_inventory(Path::new(&committed.active_path), manifest)?;
        self.cleanup_retained_versions(manifest, &committed)?;
        emit_progress(
            progress,
            ComponentProgress {
                operation_id: journal.operation_id.clone(),
                component_id: manifest.component.id.clone(),
                component_version: manifest.component.version.clone(),
                operation: "activate".to_string(),
                state: state.to_string(),
                bytes_downloaded: 0,
                total_bytes: 0,
                percent: 100.0,
                message: "Activation metadata was committed and re-read successfully.".to_string(),
            },
        );
        Ok(ActivationResult {
            component_id: manifest.component.id.clone(),
            component_version: manifest.component.version.clone(),
            active_path: committed.active_path,
            previous_version: committed.previous_version,
            state: state.to_string(),
        })
    }

    pub fn rollback(
        &self,
        component_id: &str,
        policy: SourcePolicy,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<ActivationResult> {
        if crate::component_broker::should_delegate_for(self.machine_root()) {
            return crate::component_broker::delegate(crate::component_broker::BrokerRequest {
                schema_version: crate::component_broker::BROKER_SCHEMA.to_string(),
                request_id: format!("rollback-{}", now_epoch_ms()),
                operation: crate::component_broker::BrokerOperation::Rollback,
                component_id: Some(component_id.to_string()),
                component_version: None,
                operation_id: None,
                allow_offline_sources: policy.allow_local_test_sources,
            });
        }
        self.rollback_direct(component_id, policy, progress)
    }

    pub(crate) fn rollback_direct(
        &self,
        component_id: &str,
        policy: SourcePolicy,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<ActivationResult> {
        let _lock = self.acquire_lock()?;
        self.rollback_locked(component_id, policy, progress)
    }

    fn rollback_locked(
        &self,
        component_id: &str,
        policy: SourcePolicy,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<ActivationResult> {
        validate_component_id(component_id)?;
        let (_, current) = self.read_activation(component_id)?.ok_or_else(|| {
            ComponentError::new(
                "ROLLBACK_UNAVAILABLE",
                "No active component with a retained previous version is available.",
                false,
            )
        })?;
        let previous_version = current.previous_version.clone().ok_or_else(|| {
            ComponentError::new(
                "ROLLBACK_UNAVAILABLE",
                "The active component has no retained previous version.",
                false,
            )
        })?;
        let previous_path = current.previous_path.clone().ok_or_else(|| {
            ComponentError::new(
                "ROLLBACK_UNAVAILABLE",
                "The active component has no retained previous path.",
                false,
            )
        })?;
        let previous_path_buf = PathBuf::from(&previous_path);
        ensure_safe_existing_path(&self.paths.components_root, &previous_path_buf)?;
        if !previous_path_buf.is_dir() {
            return Err(ComponentError::new(
                "ROLLBACK_TARGET_MISSING",
                "The retained previous component version is no longer present.",
                false,
            ));
        }
        let previous_manifest = self.read_manifest(component_id, &previous_version, policy)?;
        verify_installed_inventory(&previous_path_buf, &previous_manifest)?;
        let metadata_path = self.metadata_path(&previous_manifest)?;
        let metadata = ActivationMetadata {
            schema_version: ACTIVATION_SCHEMA.to_string(),
            state: "active".to_string(),
            component_id: component_id.to_string(),
            component_version: previous_version.clone(),
            active_path: previous_path.clone(),
            previous_version: Some(current.component_version.clone()),
            previous_path: Some(current.active_path.clone()),
            manifest_path: self
                .manifest_path(component_id, &previous_version)?
                .to_string_lossy()
                .to_string(),
            activated_at_epoch_ms: now_epoch_ms(),
        };
        atomic_write_json(&metadata_path, &metadata)?;
        emit_progress(
            progress,
            ComponentProgress {
                operation_id: format!("rollback-{}", now_epoch_ms()),
                component_id: component_id.to_string(),
                component_version: previous_version.clone(),
                operation: "rollback".to_string(),
                state: "rolled-back".to_string(),
                bytes_downloaded: 0,
                total_bytes: 0,
                percent: 100.0,
                message: "Last-known-good component version is active again.".to_string(),
            },
        );
        Ok(ActivationResult {
            component_id: component_id.to_string(),
            component_version: previous_version,
            active_path: previous_path,
            previous_version: metadata.previous_version,
            state: "rolled-back".to_string(),
        })
    }

    pub fn repair(
        &self,
        component_id: &str,
        policy: SourcePolicy,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<RepairResult> {
        if crate::component_broker::should_delegate_for(self.machine_root()) {
            return crate::component_broker::delegate(crate::component_broker::BrokerRequest {
                schema_version: crate::component_broker::BROKER_SCHEMA.to_string(),
                request_id: format!("repair-{}", now_epoch_ms()),
                operation: crate::component_broker::BrokerOperation::Repair,
                component_id: Some(component_id.to_string()),
                component_version: None,
                operation_id: None,
                allow_offline_sources: policy.allow_local_test_sources,
            });
        }
        self.repair_direct(component_id, policy, progress)
    }

    pub(crate) fn repair_direct(
        &self,
        component_id: &str,
        policy: SourcePolicy,
        progress: Option<&dyn Fn(ComponentProgress)>,
    ) -> ManagerResult<RepairResult> {
        let _lock = self.acquire_lock()?;
        let Some((_, activation)) = self.read_activation(component_id)? else {
            return Err(ComponentError::new(
                "COMPONENT_NOT_ACTIVE",
                "There is no active component version to repair.",
                false,
            ));
        };
        let active_path = PathBuf::from(&activation.active_path);
        let manifest = self.read_manifest(component_id, &activation.component_version, policy)?;
        match verify_installed_inventory(&active_path, &manifest) {
            Ok(()) => Ok(RepairResult {
                component_id: component_id.to_string(),
                state: "healthy".to_string(),
                detail: "The active immutable component matches its signed inventory.".to_string(),
            }),
            Err(error) if activation.previous_version.is_some() => {
                let rolled_back = self.rollback_locked(component_id, policy, progress)?;
                Ok(RepairResult {
                    component_id: component_id.to_string(),
                    state: "rolled-back".to_string(),
                    detail: format!(
                        "Active version was corrupt ({}); retained version {} is active.",
                        error.code, rolled_back.component_version
                    ),
                })
            }
            Err(error) => Err(ComponentError::new(
                "REPAIR_FAILED",
                format!(
                    "The active component failed exact inventory repair and has no rollback: {}",
                    error.message
                ),
                false,
            )),
        }
    }

    pub fn uninstall(&self, component_id: &str) -> ManagerResult<UninstallResult> {
        if crate::component_broker::should_delegate_for(self.machine_root()) {
            return crate::component_broker::delegate(crate::component_broker::BrokerRequest {
                schema_version: crate::component_broker::BROKER_SCHEMA.to_string(),
                request_id: format!("uninstall-{}", now_epoch_ms()),
                operation: crate::component_broker::BrokerOperation::Uninstall,
                component_id: Some(component_id.to_string()),
                component_version: None,
                operation_id: None,
                allow_offline_sources: false,
            });
        }
        self.uninstall_direct(component_id)
    }

    pub(crate) fn uninstall_direct(&self, component_id: &str) -> ManagerResult<UninstallResult> {
        let _lock = self.acquire_lock()?;
        validate_component_id(component_id)?;
        self.ensure_machine_storage()?;
        let components = self.paths.components_root.join(component_id);
        let downloads = self.paths.downloads_root.join(component_id);
        let catalog = self.paths.catalog_root.join(component_id);
        for path in [&components, &downloads, &catalog] {
            ensure_child_path(
                if path == &components {
                    &self.paths.components_root
                } else if path == &downloads {
                    &self.paths.downloads_root
                } else {
                    &self.paths.catalog_root
                },
                path,
            )?;
        }
        let mut removed_paths = Vec::new();
        for path in [&components, &downloads, &catalog] {
            if path.exists() {
                if is_reparse_or_symlink(path) {
                    return Err(ComponentError::new(
                        "REPARSE_POINT_REJECTED",
                        format!(
                            "Refusing to uninstall through a reparse point at {}.",
                            path.display()
                        ),
                        false,
                    ));
                }
                fs::remove_dir_all(path).map_err(|error| storage_error(path, error))?;
                removed_paths.push(path.to_string_lossy().to_string());
            }
        }
        self.remove_activation_records(component_id, &mut removed_paths)?;
        Ok(UninstallResult {
            component_id: component_id.to_string(),
            removed_paths,
            preserved_user_data: true,
        })
    }

    pub fn recover(&self) -> ManagerResult<RecoveryResult> {
        if crate::component_broker::should_delegate_for(self.machine_root()) {
            return crate::component_broker::delegate(crate::component_broker::BrokerRequest {
                schema_version: crate::component_broker::BROKER_SCHEMA.to_string(),
                request_id: format!("reconcile-{}", now_epoch_ms()),
                operation: crate::component_broker::BrokerOperation::Reconcile,
                component_id: None,
                component_version: None,
                operation_id: None,
                allow_offline_sources: false,
            });
        }
        self.recover_direct()
    }

    pub(crate) fn recover_direct(&self) -> ManagerResult<RecoveryResult> {
        let _lock = self.acquire_lock()?;
        self.ensure_machine_storage()?;
        let recovered_journals = self.recover_journals_locked()?;
        let cleaned_staging_directories = self.cleanup_abandoned_staging()?;
        let resumable_downloads = self.recover_downloads()?;
        Ok(RecoveryResult {
            recovered_journals,
            cleaned_staging_directories,
            resumable_downloads,
        })
    }

    fn recover_journals_locked(&self) -> ManagerResult<usize> {
        let mut recovered = 0;
        if !self.paths.journal_root.exists() {
            return Ok(0);
        }
        for entry in fs::read_dir(&self.paths.journal_root)
            .map_err(|error| storage_error(&self.paths.journal_root, error))?
        {
            let entry = entry.map_err(|error| storage_error(&self.paths.journal_root, error))?;
            if entry
                .path()
                .extension()
                .and_then(|extension| extension.to_str())
                != Some("json")
            {
                continue;
            }
            let bytes =
                fs::read(entry.path()).map_err(|error| storage_error(&entry.path(), error))?;
            let mut journal: ActivationJournal = match serde_json::from_slice(&bytes) {
                Ok(journal) => journal,
                Err(_) => continue,
            };
            if !matches!(
                journal.checkpoint.as_str(),
                "activation-intent" | "published" | "quarantined"
            ) {
                continue;
            }
            let manifest_bytes = fs::read(&journal.manifest_path)
                .map_err(|error| storage_error(Path::new(&journal.manifest_path), error))?;
            let manifest: ComponentManifest =
                serde_json::from_slice(&manifest_bytes).map_err(|error| {
                    ComponentError::new(
                        "ACTIVATION_RECOVERY_FAILED",
                        format!("Published journal manifest is invalid: {error}"),
                        false,
                    )
                })?;
            let published = PathBuf::from(&journal.published_path);
            ensure_safe_existing_path(&self.paths.components_root, &published)?;
            if !published.is_dir() {
                continue;
            }
            if verify_installed_inventory(&published, &manifest).is_err() {
                continue;
            }
            let metadata = ActivationMetadata {
                schema_version: ACTIVATION_SCHEMA.to_string(),
                state: "active".to_string(),
                component_id: journal.component_id.clone(),
                component_version: journal.component_version.clone(),
                active_path: published.to_string_lossy().to_string(),
                previous_version: journal.previous_version.clone(),
                previous_path: journal.previous_path.clone(),
                manifest_path: journal.manifest_path.clone(),
                activated_at_epoch_ms: now_epoch_ms(),
            };
            let metadata_path = PathBuf::from(&journal.metadata_path);
            ensure_child_path(&self.paths.activation_root, &metadata_path)?;
            checkpoint_failure("recovery-metadata")?;
            atomic_write_json(&metadata_path, &metadata)?;
            journal.checkpoint = "active".to_string();
            journal.updated_at_epoch_ms = now_epoch_ms();
            atomic_write_json(&entry.path(), &journal)?;
            recovered += 1;
        }
        Ok(recovered)
    }

    fn cleanup_abandoned_staging(&self) -> ManagerResult<usize> {
        let mut referenced = BTreeSet::new();
        if self.paths.journal_root.exists() {
            for entry in fs::read_dir(&self.paths.journal_root)
                .map_err(|error| storage_error(&self.paths.journal_root, error))?
            {
                let entry =
                    entry.map_err(|error| storage_error(&self.paths.journal_root, error))?;
                if entry
                    .path()
                    .extension()
                    .and_then(|extension| extension.to_str())
                    != Some("json")
                {
                    continue;
                }
                if let Ok(bytes) = fs::read(entry.path()) {
                    if let Ok(journal) = serde_json::from_slice::<ActivationJournal>(&bytes) {
                        if matches!(
                            journal.checkpoint.as_str(),
                            "staged" | "activation-intent" | "quarantined"
                        ) {
                            referenced.insert(journal.stage_path);
                        }
                    }
                }
            }
        }
        let mut removed = 0;
        if !self.paths.components_root.exists() {
            return Ok(0);
        }
        for component in fs::read_dir(&self.paths.components_root)
            .map_err(|error| storage_error(&self.paths.components_root, error))?
        {
            let component =
                component.map_err(|error| storage_error(&self.paths.components_root, error))?;
            if !component.path().is_dir() || is_reparse_or_symlink(&component.path()) {
                continue;
            }
            let staging = component.path().join(".staging");
            if !staging.exists() {
                continue;
            }
            for entry in fs::read_dir(&staging).map_err(|error| storage_error(&staging, error))? {
                let entry = entry.map_err(|error| storage_error(&staging, error))?;
                let path = entry.path();
                if referenced.contains(&path.to_string_lossy().to_string()) {
                    continue;
                }
                ensure_child_path(&self.paths.components_root, &path)?;
                if is_reparse_or_symlink(&path) {
                    return Err(ComponentError::new(
                        "REPARSE_POINT_REJECTED",
                        format!(
                            "Abandoned staging contains a reparse point at {}.",
                            path.display()
                        ),
                        false,
                    ));
                }
                fs::remove_dir_all(&path).map_err(|error| storage_error(&path, error))?;
                removed += 1;
            }
        }
        Ok(removed)
    }

    fn cleanup_retained_versions(
        &self,
        manifest: &ComponentManifest,
        metadata: &ActivationMetadata,
    ) -> ManagerResult<()> {
        let component_root = self.paths.components_root.join(&manifest.component.id);
        ensure_child_path(&self.paths.components_root, &component_root)?;
        if !component_root.exists() {
            return Ok(());
        }
        let mut versions = Vec::new();
        for entry in
            fs::read_dir(&component_root).map_err(|error| storage_error(&component_root, error))?
        {
            let entry = entry.map_err(|error| storage_error(&component_root, error))?;
            if !entry.path().is_dir() || is_reparse_or_symlink(&entry.path()) {
                continue;
            }
            let Some(name) = entry.file_name().to_str().map(ToOwned::to_owned) else {
                continue;
            };
            if let Ok(version) = Version::parse(&name) {
                versions.push((version, entry.path()));
            }
        }
        versions.sort_by(|left, right| right.0.cmp(&left.0));
        let keep = manifest.rollback.retention_count.saturating_add(1);
        for (_, path) in versions.into_iter().skip(keep) {
            if path.to_string_lossy() == metadata.active_path
                || metadata.previous_path.as_deref() == Some(path.to_string_lossy().as_ref())
            {
                continue;
            }
            fs::remove_dir_all(&path).map_err(|error| storage_error(&path, error))?;
        }
        Ok(())
    }

    fn remove_activation_records(
        &self,
        component_id: &str,
        removed_paths: &mut Vec<String>,
    ) -> ManagerResult<()> {
        if !self.paths.activation_root.exists() {
            return Ok(());
        }
        let mut candidates = Vec::new();
        collect_matching_activation_files(
            &self.paths.activation_root,
            &self.paths.activation_root,
            component_id,
            &mut candidates,
        )?;
        for path in candidates {
            ensure_child_path(&self.paths.activation_root, &path)?;
            if path.exists() {
                fs::remove_file(&path).map_err(|error| storage_error(&path, error))?;
                removed_paths.push(path.to_string_lossy().to_string());
            }
        }
        Ok(())
    }

    fn acquire_lock(&self) -> ManagerResult<MachineLock> {
        self.ensure_machine_storage()?;
        for attempt in 0..2 {
            match OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&self.paths.lock_path)
            {
                Ok(mut file) => {
                    let record =
                        format!("pid={}\ncreatedAt={}\n", std::process::id(), now_epoch_ms());
                    file.write_all(record.as_bytes())
                        .and_then(|_| file.sync_all())
                        .map_err(|error| storage_error(&self.paths.lock_path, error))?;
                    return Ok(MachineLock {
                        path: self.paths.lock_path.clone(),
                    });
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists && attempt == 0 => {
                    let stale = fs::metadata(&self.paths.lock_path)
                        .ok()
                        .and_then(|metadata| metadata.modified().ok())
                        .and_then(|modified| modified.elapsed().ok())
                        .is_some_and(|age| age > LOCK_STALE_AFTER);
                    if stale {
                        let _ = fs::remove_file(&self.paths.lock_path);
                        continue;
                    }
                    return Err(ComponentError::new(
                        "LOCK_CONTENDED",
                        "Another installer/update-service operation owns the ProgramData component lock.",
                        true,
                    ));
                }
                Err(error) => return Err(storage_error(&self.paths.lock_path, error)),
            }
        }
        Err(ComponentError::new(
            "LOCK_CONTENDED",
            "The ProgramData component lock could not be acquired.",
            true,
        ))
    }
}

fn now_epoch_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

fn checkpoint_failure(checkpoint: &str) -> ManagerResult<()> {
    if env::var("AIVE_ACTIVATION_FAIL_CHECKPOINT")
        .ok()
        .is_some_and(|value| value.eq_ignore_ascii_case(checkpoint))
    {
        return Err(ComponentError::new(
            "FAILURE_INJECTED",
            format!("Activation failure injected at checkpoint {checkpoint}."),
            true,
        ));
    }
    Ok(())
}

fn validate_component_id(value: &str) -> ManagerResult<()> {
    let valid = (2..=64).contains(&value.len())
        && value
            .chars()
            .next()
            .is_some_and(|character| character.is_ascii_lowercase() || character.is_ascii_digit())
        && value.chars().all(|character| {
            character.is_ascii_lowercase()
                || character.is_ascii_digit()
                || "._-".contains(character)
        });
    if valid {
        Ok(())
    } else {
        Err(ComponentError::new(
            "COMPONENT_ID_INVALID",
            "Component ids must be 2-64 lowercase ASCII characters using [a-z0-9._-].",
            false,
        ))
    }
}

fn parse_version(value: &str, field: &str) -> ManagerResult<Version> {
    Version::parse(value).map_err(|error| {
        ComponentError::new(
            "VERSION_INVALID",
            format!("{field} is not a valid semantic version: {error}"),
            false,
        )
    })
}

fn validate_sha256(value: &str, field: &str) -> ManagerResult<()> {
    if value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        Ok(())
    } else {
        Err(ComponentError::new(
            "SHA256_INVALID",
            format!("{field} must be a lowercase 64-character SHA-256 digest."),
            false,
        ))
    }
}

fn validate_safe_relative_path(value: &str, field: &str) -> ManagerResult<()> {
    let invalid = value.is_empty()
        || value.starts_with('/')
        || value.starts_with('\\')
        || value.contains('\\')
        || value.contains('\0')
        || value.contains(':')
        || value.chars().any(|character| "<>\"|?*".contains(character))
        || value
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..");
    if invalid {
        Err(ComponentError::new(
            "UNSAFE_PATH",
            format!("{field} must be a non-empty, normalized relative path without traversal or reparse syntax."),
            false,
        ))
    } else {
        Ok(())
    }
}

fn path_key(path: &str) -> String {
    path.replace('\\', "/").to_ascii_lowercase()
}

fn ensure_child_path(root: &Path, candidate: &Path) -> ManagerResult<()> {
    if candidate.strip_prefix(root).is_err() || candidate == root {
        return Err(ComponentError::new(
            "PATH_BOUNDARY_VIOLATION",
            format!(
                "Resolved path {} is outside the authorized root {}.",
                candidate.display(),
                root.display()
            ),
            false,
        ));
    }
    for component in candidate.strip_prefix(root).unwrap().components() {
        if matches!(
            component,
            std::path::Component::ParentDir
                | std::path::Component::RootDir
                | std::path::Component::Prefix(_)
        ) {
            return Err(ComponentError::new(
                "UNSAFE_PATH",
                format!(
                    "Resolved path {} contains an unsafe path component.",
                    candidate.display()
                ),
                false,
            ));
        }
    }
    Ok(())
}

fn storage_error(path: &Path, error: io::Error) -> ComponentError {
    if error.kind() == io::ErrorKind::PermissionDenied {
        ComponentError::new(
            "ELEVATION_REQUIRED",
            format!(
                "The machine-scoped component store is not writable at {}. Run the per-machine installer or update service elevated; no AppData fallback is used.",
                path.display()
            ),
            true,
        )
    } else {
        ComponentError::new(
            "STORAGE_NOT_WRITABLE",
            format!(
                "Could not access the machine-scoped component store at {}: {error}",
                path.display()
            ),
            true,
        )
    }
}

fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> ManagerResult<()> {
    let parent = path.parent().ok_or_else(|| {
        ComponentError::new(
            "PATH_BOUNDARY_VIOLATION",
            "A metadata path has no authorized parent directory.",
            false,
        )
    })?;
    fs::create_dir_all(parent).map_err(|error| storage_error(parent, error))?;
    let temporary = path.with_extension(format!(
        "{}.part",
        path.extension()
            .and_then(|extension| extension.to_str())
            .unwrap_or("json")
    ));
    let bytes = serde_json::to_vec_pretty(value).map_err(|error| {
        ComponentError::new(
            "STATE_SERIALIZATION_FAILED",
            format!("Could not serialize component state: {error}"),
            false,
        )
    })?;
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&temporary)
        .map_err(|error| storage_error(&temporary, error))?;
    file.write_all(&bytes)
        .map_err(|error| storage_error(&temporary, error))?;
    file.sync_all()
        .map_err(|error| storage_error(&temporary, error))?;
    atomic_replace_file(&temporary, path).map_err(|error| storage_error(path, error))?;
    Ok(())
}

/// Replace a metadata file without exposing a delete-then-create window.
///
/// POSIX rename replaces the destination atomically. Windows needs the
/// replace-existing flag because `std::fs::rename` does not replace an
/// existing file there. `MoveFileExW` keeps the operation on the same volume
/// and asks the filesystem to flush the move before returning.
#[cfg(not(windows))]
fn atomic_replace_file(temporary: &Path, destination: &Path) -> io::Result<()> {
    fs::rename(temporary, destination)
}

#[cfg(windows)]
fn atomic_replace_file(temporary: &Path, destination: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;

    const MOVEFILE_REPLACE_EXISTING: u32 = 0x0000_0001;
    const MOVEFILE_WRITE_THROUGH: u32 = 0x0000_0008;

    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(existing_name: *const u16, new_name: *const u16, flags: u32) -> i32;
    }

    let existing_name: Vec<u16> = temporary
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let new_name: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let replaced = unsafe {
        MoveFileExW(
            existing_name.as_ptr(),
            new_name.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if replaced == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn validate_https_url(value: &str, field: &str) -> ManagerResult<()> {
    let parsed = Url::parse(value).map_err(|error| {
        ComponentError::new(
            "URL_INVALID",
            format!("{field} is not a valid URL: {error}"),
            false,
        )
    })?;
    if parsed.scheme() != "https" {
        return Err(ComponentError::new(
            "HTTPS_REQUIRED",
            format!("{field} must use HTTPS."),
            false,
        ));
    }
    Ok(())
}

fn validate_artifact_url(value: &str, policy: SourcePolicy) -> ManagerResult<()> {
    let parsed = Url::parse(value).map_err(|error| {
        ComponentError::new(
            "URL_INVALID",
            format!("artifact.url is not a valid URL: {error}"),
            false,
        )
    })?;
    if parsed.scheme() == "https" {
        return Ok(());
    }
    if !policy.allow_local_test_sources {
        return Err(ComponentError::new(
            "HTTPS_REQUIRED",
            "Production artifact URLs must use HTTPS. Local sources are accepted only for a signed offline catalog import.",
            false,
        ));
    }
    match parsed.scheme() {
        "offline" => {
            offline_artifact_relative_path(value)?;
            Ok(())
        }
        "file" => {
            if parsed.to_file_path().is_err() {
                return Err(ComponentError::new(
                    "TEST_SOURCE_INVALID",
                    "The test file URL does not resolve to a local file path.",
                    false,
                ));
            }
            Ok(())
        }
        "http" => {
            let host = parsed.host_str().unwrap_or_default();
            if matches!(host, "localhost" | "127.0.0.1" | "::1") {
                Ok(())
            } else {
                Err(ComponentError::new(
                    "TEST_SOURCE_INVALID",
                    "Development HTTP sources are limited to localhost.",
                    false,
                ))
            }
        }
        _ => Err(ComponentError::new(
            "ARTIFACT_URL_POLICY_REJECTED",
            "Only HTTPS production URLs or explicit portable offline-import sources are accepted.",
            false,
        )),
    }
}

fn offline_artifact_relative_path(value: &str) -> ManagerResult<&str> {
    let relative = value.strip_prefix("offline:").ok_or_else(|| {
        ComponentError::new(
            "OFFLINE_ARTIFACT_INVALID",
            "Portable offline artifacts must use the offline: URI scheme.",
            false,
        )
    })?;
    validate_safe_relative_path(relative, "artifact.url")?;
    if !relative.starts_with("Components/") || relative.len() <= "Components/".len() {
        return Err(ComponentError::new(
            "OFFLINE_ARTIFACT_INVALID",
            "Portable offline artifacts must resolve below the handoff Components directory.",
            false,
        ));
    }
    Ok(relative)
}

fn validate_inventory_shape(files: &[FileInventoryEntry]) -> ManagerResult<()> {
    if files.is_empty() {
        return Err(ComponentError::new(
            "INVENTORY_EMPTY",
            "The manifest must contain a non-empty exact file inventory.",
            false,
        ));
    }
    let mut seen = BTreeSet::new();
    for file in files {
        validate_safe_relative_path(&file.path, "files.path")?;
        if !matches!(file.kind.as_str(), "file" | "directory") {
            return Err(ComponentError::new(
                "INVENTORY_KIND_INVALID",
                format!("Inventory entry {} has an unsupported kind.", file.path),
                false,
            ));
        }
        if file.byte_size > MAX_FILE_BYTES {
            return Err(ComponentError::new(
                "FILE_LIMIT_EXCEEDED",
                format!(
                    "Inventory entry {} exceeds the bounded file limit.",
                    file.path
                ),
                false,
            ));
        }
        validate_sha256(&file.sha256, "files.sha256")?;
        if !seen.insert(path_key(&file.path)) {
            return Err(ComponentError::new(
                "DUPLICATE_PATH",
                format!(
                    "The manifest contains duplicate inventory path {}.",
                    file.path
                ),
                false,
            ));
        }
    }
    Ok(())
}

fn current_operating_system() -> OperatingSystem {
    if cfg!(windows) {
        OperatingSystem::Windows
    } else if cfg!(target_os = "macos") {
        OperatingSystem::Macos
    } else {
        OperatingSystem::Linux
    }
}

fn current_architecture() -> Architecture {
    match env::consts::ARCH {
        "x86" | "i686" => Architecture::X86,
        "aarch64" => Architecture::Aarch64,
        _ => Architecture::X86_64,
    }
}

fn trusted_key(key_id: &str) -> Option<Vec<u8>> {
    if key_id == RELEASE_KEY_ID {
        return BASE64.decode(RELEASE_PUBLIC_KEY_B64).ok();
    }
    #[cfg(debug_assertions)]
    if key_id == TEST_FIXTURE_KEY_ID {
        return BASE64.decode(TEST_FIXTURE_PUBLIC_KEY_B64).ok();
    }
    None
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct OfflineRootRecord {
    schema_version: String,
    root: String,
}

/// Verify a detached payload against the shell's compiled trust root.
///
/// Setup catalogs are authenticated with the same read-only trust root as
/// component manifests. The catalog may identify a key, but it cannot provide
/// or replace the public key used here.
pub(crate) fn verify_trusted_detached_payload(
    algorithm: &str,
    key_id: &str,
    value: &str,
    payload: &[u8],
) -> ManagerResult<()> {
    if algorithm != "ed25519" {
        return Err(ComponentError::new(
            "SIGNATURE_ALGORITHM_UNSUPPORTED",
            "Only detached Ed25519 signatures are accepted.",
            false,
        ));
    }
    let key = trusted_key(key_id).ok_or_else(|| {
        ComponentError::new(
            "UNKNOWN_TRUST_KEY",
            "The signature key is not in the compiled read-only trust root.",
            false,
        )
    })?;
    let signature = BASE64.decode(value).map_err(|_| {
        ComponentError::new(
            "SIGNATURE_ENCODING_INVALID",
            "The detached signature is not valid base64.",
            false,
        )
    })?;
    if signature.len() != 64 {
        return Err(ComponentError::new(
            "SIGNATURE_LENGTH_INVALID",
            "An Ed25519 signature must contain exactly 64 bytes.",
            false,
        ));
    }
    UnparsedPublicKey::new(&ED25519, key)
        .verify(payload, &signature)
        .map_err(|_| {
            ComponentError::new(
                "SIGNATURE_INVALID",
                "The detached Ed25519 signature does not authenticate the catalog payload.",
                false,
            )
        })
}

fn manifest_signature_payload(manifest: &ComponentManifest) -> ManagerResult<Vec<u8>> {
    let mut value = serde_json::to_value(manifest).map_err(|error| {
        ComponentError::new(
            "SIGNATURE_PAYLOAD_INVALID",
            format!("Could not serialize the manifest for signature verification: {error}"),
            false,
        )
    })?;
    if let Value::Object(root) = &mut value {
        if let Some(Value::Object(signature)) = root.get_mut("signature") {
            signature.insert("value".to_string(), Value::String(String::new()));
        }
    }
    serde_json::to_vec(&value).map_err(|error| {
        ComponentError::new(
            "SIGNATURE_PAYLOAD_INVALID",
            format!("Could not canonicalize the manifest for signature verification: {error}"),
            false,
        )
    })
}

fn verify_manifest_signature(manifest: &ComponentManifest, signature: &[u8]) -> ManagerResult<()> {
    let payload = manifest_signature_payload(manifest)?;
    let encoded = BASE64.encode(signature);
    verify_trusted_detached_payload(
        &manifest.signature.algorithm,
        &manifest.signature.key_id,
        &encoded,
        &payload,
    )
}

fn write_file_hash(path: &Path) -> ManagerResult<(u64, String)> {
    let mut file = File::open(path).map_err(|error| storage_error(path, error))?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; DOWNLOAD_BUFFER_BYTES];
    let mut total = 0_u64;
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| storage_error(path, error))?;
        if read == 0 {
            break;
        }
        total = total.saturating_add(read as u64);
        if total > MAX_FILE_BYTES {
            return Err(ComponentError::new(
                "FILE_LIMIT_EXCEEDED",
                format!("File {} exceeds the bounded file limit.", path.display()),
                false,
            ));
        }
        hasher.update(&buffer[..read]);
    }
    Ok((total, hex_digest(&hasher.finalize())))
}

fn hex_digest(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push_str(&format!("{byte:02x}"));
    }
    output
}

fn is_reparse_or_symlink(path: &Path) -> bool {
    let Ok(metadata) = fs::symlink_metadata(path) else {
        return false;
    };
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return true;
        }
    }
    false
}

fn ensure_safe_existing_path(root: &Path, candidate: &Path) -> ManagerResult<()> {
    if root.exists() && is_reparse_or_symlink(root) {
        return Err(ComponentError::new(
            "REPARSE_POINT_REJECTED",
            format!(
                "Reparse point or symlink encountered at authorized root {}.",
                root.display()
            ),
            false,
        ));
    }
    if candidate != root {
        ensure_child_path(root, candidate)?;
    }
    let relative = candidate.strip_prefix(root).map_err(|_| {
        ComponentError::new(
            "PATH_BOUNDARY_VIOLATION",
            "A staging path escaped its authorized root.",
            false,
        )
    })?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        current.push(component.as_os_str());
        if current.exists() && is_reparse_or_symlink(&current) {
            return Err(ComponentError::new(
                "REPARSE_POINT_REJECTED",
                format!(
                    "Reparse point or symlink encountered at {}.",
                    current.display()
                ),
                false,
            ));
        }
    }
    Ok(())
}

#[cfg(windows)]
fn available_space_bytes(path: &Path) -> io::Result<u64> {
    use std::os::windows::ffi::OsStrExt;
    extern "system" {
        fn GetDiskFreeSpaceExW(
            directory_name: *const u16,
            free_bytes_available: *mut u64,
            total_number_of_bytes: *mut u64,
            total_number_of_free_bytes: *mut u64,
        ) -> i32;
    }
    let mut wide: Vec<u16> = path.as_os_str().encode_wide().collect();
    wide.push(0);
    let mut available = 0_u64;
    let mut total = 0_u64;
    let mut free = 0_u64;
    let result =
        unsafe { GetDiskFreeSpaceExW(wide.as_ptr(), &mut available, &mut total, &mut free) };
    if result == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(available)
    }
}

#[cfg(not(windows))]
fn available_space_bytes(_path: &Path) -> io::Result<u64> {
    // The production target is Windows. Non-Windows unit tests run in an
    // isolated temporary directory and retain the bounded byte-limit check.
    Ok(u64::MAX)
}

fn ensure_free_space(path: &Path, required: u64) -> ManagerResult<()> {
    let required_with_margin = required.saturating_add(FREE_SPACE_MARGIN_BYTES);
    let available = available_space_bytes(path).map_err(|error| storage_error(path, error))?;
    if available < required_with_margin {
        return Err(ComponentError::new(
            "DISK_SPACE_LOW",
            format!(
                "The component operation needs at least {required_with_margin} bytes free in {}.",
                path.display()
            ),
            true,
        ));
    }
    Ok(())
}

fn percentage(downloaded: u64, total: u64) -> f64 {
    if total == 0 {
        0.0
    } else {
        ((downloaded as f64 / total as f64) * 100.0).min(100.0)
    }
}

fn emit_progress(progress: Option<&dyn Fn(ComponentProgress)>, event: ComponentProgress) {
    if let Some(progress) = progress {
        progress(event);
    }
}

fn persist_download_progress(
    manager: &ComponentManager,
    state_path: &Path,
    state: &DownloadState,
    progress: Option<&dyn Fn(ComponentProgress)>,
) -> ManagerResult<()> {
    manager.persist_download_state(state_path, state)?;
    emit_progress(
        progress,
        ComponentProgress {
            operation_id: state.operation_id.clone(),
            component_id: state.component_id.clone(),
            component_version: state.component_version.clone(),
            operation: "download".to_string(),
            state: "downloading".to_string(),
            bytes_downloaded: state.bytes_downloaded,
            total_bytes: state.expected_bytes,
            percent: percentage(state.bytes_downloaded, state.expected_bytes),
            message: "Downloading into ProgramData staging.".to_string(),
        },
    );
    Ok(())
}

fn open_http_response(raw_url: &str, offset: u64, policy: SourcePolicy) -> ManagerResult<Response> {
    validate_artifact_url(raw_url, policy)?;
    let client = Client::builder()
        .redirect(Policy::none())
        .connect_timeout(DOWNLOAD_TIMEOUT)
        .timeout(DOWNLOAD_TIMEOUT)
        .build()
        .map_err(|error| {
            ComponentError::new(
                "DOWNLOAD_NETWORK_FAILED",
                format!("Could not create the bounded HTTP client: {error}"),
                true,
            )
        })?;
    let mut current = Url::parse(raw_url).map_err(|error| {
        ComponentError::new(
            "URL_INVALID",
            format!("Could not parse the artifact URL: {error}"),
            false,
        )
    })?;
    for redirect_count in 0..=MAX_REDIRECTS {
        validate_artifact_url(current.as_str(), policy)?;
        let mut request = client.get(current.clone());
        if offset > 0 {
            request = request.header(reqwest::header::RANGE, format!("bytes={offset}-"));
        }
        let response = request.send().map_err(|error| {
            ComponentError::new(
                "DOWNLOAD_NETWORK_FAILED",
                format!("Artifact request failed: {error}"),
                true,
            )
        })?;
        if response.status().is_redirection() {
            if redirect_count == MAX_REDIRECTS {
                return Err(ComponentError::new(
                    "REDIRECT_LIMIT_EXCEEDED",
                    "The artifact URL exceeded the bounded redirect count.",
                    false,
                ));
            }
            let location = response
                .headers()
                .get(reqwest::header::LOCATION)
                .and_then(|value| value.to_str().ok())
                .ok_or_else(|| {
                    ComponentError::new(
                        "REDIRECT_POLICY_REJECTED",
                        "The artifact redirect did not contain a valid Location header.",
                        false,
                    )
                })?;
            let next = current.join(location).map_err(|error| {
                ComponentError::new(
                    "REDIRECT_POLICY_REJECTED",
                    format!("The artifact redirect could not be resolved: {error}"),
                    false,
                )
            })?;
            if current.scheme() == "https" && next.scheme() != "https" {
                return Err(ComponentError::new(
                    "REDIRECT_DOWNGRADE_REJECTED",
                    "An HTTPS artifact redirect attempted to downgrade transport security.",
                    false,
                ));
            }
            validate_artifact_url(next.as_str(), policy)?;
            current = next;
            continue;
        }
        if !response.status().is_success() {
            return Err(ComponentError::new(
                "DOWNLOAD_NETWORK_FAILED",
                format!("Artifact server returned HTTP {}.", response.status()),
                true,
            ));
        }
        return Ok(response);
    }
    Err(ComponentError::new(
        "REDIRECT_LIMIT_EXCEEDED",
        "The artifact URL exceeded the bounded redirect count.",
        false,
    ))
}

impl ComponentManager {
    fn catalog_component_ids(&self) -> ManagerResult<Vec<String>> {
        if !self.paths.catalog_root.exists() {
            return Ok(Vec::new());
        }
        let mut ids = Vec::new();
        for entry in fs::read_dir(&self.paths.catalog_root)
            .map_err(|error| storage_error(&self.paths.catalog_root, error))?
        {
            let entry = entry.map_err(|error| storage_error(&self.paths.catalog_root, error))?;
            if !entry.path().is_dir() || is_reparse_or_symlink(&entry.path()) {
                continue;
            }
            let Some(id) = entry.file_name().to_str().map(ToOwned::to_owned) else {
                continue;
            };
            if validate_component_id(&id).is_ok() {
                ids.push(id);
            }
        }
        ids.sort();
        Ok(ids)
    }

    fn catalog_versions(&self, component_id: &str) -> ManagerResult<Vec<String>> {
        validate_component_id(component_id)?;
        let directory = self.paths.catalog_root.join(component_id);
        if !directory.exists() {
            return Ok(Vec::new());
        }
        if is_reparse_or_symlink(&directory) {
            return Err(ComponentError::new(
                "REPARSE_POINT_REJECTED",
                format!(
                    "Catalog component directory {} is a reparse point.",
                    directory.display()
                ),
                false,
            ));
        }
        let mut versions = Vec::new();
        for entry in fs::read_dir(&directory).map_err(|error| storage_error(&directory, error))? {
            let entry = entry.map_err(|error| storage_error(&directory, error))?;
            if entry
                .path()
                .extension()
                .and_then(|extension| extension.to_str())
                != Some("json")
            {
                continue;
            }
            let entry_path = entry.path();
            let Some(stem) = entry_path.file_stem().and_then(|stem| stem.to_str()) else {
                continue;
            };
            if Version::parse(stem).is_ok() {
                versions.push(stem.to_string());
            }
        }
        versions.sort_by(|left, right| {
            Version::parse(left)
                .unwrap_or_else(|_| Version::new(0, 0, 0))
                .cmp(&Version::parse(right).unwrap_or_else(|_| Version::new(0, 0, 0)))
        });
        Ok(versions)
    }

    fn latest_catalog_manifest_unvalidated(
        &self,
        component_id: &str,
    ) -> ManagerResult<Option<ComponentManifest>> {
        let mut latest = None;
        for version in self.catalog_versions(component_id)? {
            let path = self.catalog_path(component_id, &version)?;
            let bytes = fs::read(&path).map_err(|error| storage_error(&path, error))?;
            if let Ok(manifest) = serde_json::from_slice::<ComponentManifest>(&bytes) {
                latest = Some(manifest);
            }
        }
        Ok(latest)
    }

    fn read_activation(
        &self,
        component_id: &str,
    ) -> ManagerResult<Option<(PathBuf, ActivationMetadata)>> {
        validate_component_id(component_id)?;
        let mut candidates = Vec::new();
        let catalog_directory = self.paths.catalog_root.join(component_id);
        if catalog_directory.exists() && !is_reparse_or_symlink(&catalog_directory) {
            for entry in fs::read_dir(&catalog_directory)
                .map_err(|error| storage_error(&catalog_directory, error))?
            {
                let entry = entry.map_err(|error| storage_error(&catalog_directory, error))?;
                if entry
                    .path()
                    .extension()
                    .and_then(|extension| extension.to_str())
                    != Some("json")
                {
                    continue;
                }
                if let Ok(bytes) = fs::read(entry.path()) {
                    if let Ok(manifest) = serde_json::from_slice::<ComponentManifest>(&bytes) {
                        if let Ok(path) = self.metadata_path(&manifest) {
                            candidates.push(path);
                        }
                    }
                }
            }
        }
        candidates.push(
            self.paths
                .activation_root
                .join(format!("{component_id}.json")),
        );
        candidates.sort();
        candidates.dedup();
        for path in candidates {
            ensure_child_path(&self.paths.activation_root, &path)?;
            if !path.exists() {
                continue;
            }
            let bytes = fs::read(&path).map_err(|error| storage_error(&path, error))?;
            let activation: ActivationMetadata =
                serde_json::from_slice(&bytes).map_err(|error| {
                    ComponentError::new(
                        "ACTIVATION_METADATA_INVALID",
                        format!("Activation metadata {} is invalid: {error}", path.display()),
                        false,
                    )
                })?;
            if activation.schema_version != ACTIVATION_SCHEMA
                || activation.state != "active"
                || activation.component_id != component_id
            {
                return Err(ComponentError::new(
                    "ACTIVATION_METADATA_INVALID",
                    "Activation metadata is not at the active checkpoint or has the wrong component identity.",
                    false,
                ));
            }
            let active_path = PathBuf::from(&activation.active_path);
            ensure_safe_existing_path(&self.paths.components_root, &active_path)?;
            return Ok(Some((path, activation)));
        }
        Ok(None)
    }

    fn latest_journal(
        &self,
        component_id: &str,
        component_version: &str,
    ) -> ManagerResult<Option<ActivationJournal>> {
        if !self.paths.journal_root.exists() {
            return Ok(None);
        }
        let mut journals = Vec::new();
        for entry in fs::read_dir(&self.paths.journal_root)
            .map_err(|error| storage_error(&self.paths.journal_root, error))?
        {
            let entry = entry.map_err(|error| storage_error(&self.paths.journal_root, error))?;
            if entry
                .path()
                .extension()
                .and_then(|extension| extension.to_str())
                != Some("json")
            {
                continue;
            }
            let bytes =
                fs::read(entry.path()).map_err(|error| storage_error(&entry.path(), error))?;
            if let Ok(journal) = serde_json::from_slice::<ActivationJournal>(&bytes) {
                if journal.component_id == component_id
                    && journal.component_version == component_version
                    && matches!(
                        journal.checkpoint.as_str(),
                        "staged" | "activation-intent" | "published" | "quarantined"
                    )
                {
                    journals.push(journal);
                }
            }
        }
        journals.sort_by_key(|journal| journal.updated_at_epoch_ms);
        Ok(journals.pop())
    }
}

fn collect_matching_activation_files(
    root: &Path,
    current: &Path,
    component_id: &str,
    matches: &mut Vec<PathBuf>,
) -> ManagerResult<()> {
    if is_reparse_or_symlink(current) {
        return Err(ComponentError::new(
            "REPARSE_POINT_REJECTED",
            format!(
                "Activation tree contains a reparse point at {}.",
                current.display()
            ),
            false,
        ));
    }
    for entry in fs::read_dir(current).map_err(|error| storage_error(current, error))? {
        let entry = entry.map_err(|error| storage_error(current, error))?;
        let path = entry.path();
        ensure_child_path(root, &path)?;
        if is_reparse_or_symlink(&path) {
            return Err(ComponentError::new(
                "REPARSE_POINT_REJECTED",
                format!(
                    "Activation tree contains a reparse point at {}.",
                    path.display()
                ),
                false,
            ));
        }
        if path.is_dir() {
            collect_matching_activation_files(root, &path, component_id, matches)?;
        } else if path.extension().and_then(|extension| extension.to_str()) == Some("json") {
            let bytes = fs::read(&path).map_err(|error| storage_error(&path, error))?;
            let value: Value = match serde_json::from_slice(&bytes) {
                Ok(value) => value,
                Err(_) => continue,
            };
            if value.get("componentId").and_then(Value::as_str) == Some(component_id) {
                matches.push(path);
            }
        }
    }
    matches.sort();
    matches.dedup();
    Ok(())
}

#[derive(Debug)]
struct MachineLock {
    path: PathBuf,
}

impl Drop for MachineLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

fn verify_installed_inventory(root: &Path, manifest: &ComponentManifest) -> ManagerResult<()> {
    if !root.is_dir() || is_reparse_or_symlink(root) {
        return Err(ComponentError::new(
            "ACTIVE_PATH_INVALID",
            format!(
                "The active component path {} is missing or unsafe.",
                root.display()
            ),
            false,
        ));
    }
    let expected: BTreeMap<String, &FileInventoryEntry> = manifest
        .files
        .iter()
        .map(|entry| (path_key(&entry.path), entry))
        .collect();
    let mut observed: BTreeMap<String, (String, u64, String)> = BTreeMap::new();
    collect_inventory(root, root, &mut observed)?;
    if expected.len() != observed.len() {
        return Err(ComponentError::new(
            "INVENTORY_MISMATCH",
            "The installed component contains an unexpected or missing inventory entry.",
            false,
        ));
    }
    for (key, entry) in expected {
        let Some((kind, size, digest)) = observed.get(&key) else {
            return Err(ComponentError::new(
                "INVENTORY_MISMATCH",
                format!("Installed component is missing {}.", entry.path),
                false,
            ));
        };
        if entry.kind != *kind || entry.byte_size != *size || entry.sha256 != *digest {
            return Err(ComponentError::new(
                "INVENTORY_MISMATCH",
                format!(
                    "Installed inventory entry {} does not match the signed manifest.",
                    entry.path
                ),
                false,
            ));
        }
    }
    Ok(())
}

fn collect_inventory(
    root: &Path,
    current: &Path,
    observed: &mut BTreeMap<String, (String, u64, String)>,
) -> ManagerResult<()> {
    for entry in fs::read_dir(current).map_err(|error| storage_error(current, error))? {
        let entry = entry.map_err(|error| storage_error(current, error))?;
        let path = entry.path();
        ensure_safe_existing_path(root, &path)?;
        let relative = path
            .strip_prefix(root)
            .map_err(|_| {
                ComponentError::new(
                    "PATH_BOUNDARY_VIOLATION",
                    "Inventory path escaped its root.",
                    false,
                )
            })?
            .to_string_lossy()
            .replace('\\', "/");
        validate_safe_relative_path(&relative, "installed inventory path")?;
        let key = path_key(&relative);
        if is_reparse_or_symlink(&path) {
            return Err(ComponentError::new(
                "REPARSE_POINT_REJECTED",
                format!(
                    "Installed component contains a reparse point at {}.",
                    path.display()
                ),
                false,
            ));
        }
        let metadata = fs::metadata(&path).map_err(|error| storage_error(&path, error))?;
        if metadata.is_dir() {
            let empty_digest = hex_digest(&Sha256::digest([]));
            if observed
                .insert(key, ("directory".to_string(), 0, empty_digest))
                .is_some()
            {
                return Err(ComponentError::new(
                    "DUPLICATE_PATH",
                    "Installed inventory paths are duplicated.",
                    false,
                ));
            }
            collect_inventory(root, &path, observed)?;
        } else if metadata.is_file() {
            let (size, digest) = write_file_hash(&path)?;
            if observed
                .insert(key, ("file".to_string(), size, digest))
                .is_some()
            {
                return Err(ComponentError::new(
                    "DUPLICATE_PATH",
                    "Installed inventory paths are duplicated.",
                    false,
                ));
            }
        } else {
            return Err(ComponentError::new(
                "SPECIAL_FILE_REJECTED",
                format!(
                    "Special file {} is not allowed in a component.",
                    path.display()
                ),
                false,
            ));
        }
    }
    Ok(())
}

fn run_manifest_self_test(manifest: &ComponentManifest, stage_root: &Path) -> ManagerResult<()> {
    let command = &manifest.self_test.command;
    let first = command.first().ok_or_else(|| {
        ComponentError::new(
            "SELF_TEST_FAILED",
            "The manifest self-test command is empty.",
            false,
        )
    })?;
    let (program, arguments): (PathBuf, Vec<String>) = if is_allowed_test_interpreter(first) {
        (
            allowed_interpreter(first),
            command.iter().skip(1).cloned().collect(),
        )
    } else if is_safe_command_path(first) {
        let path = stage_root.join(first);
        ensure_safe_existing_path(stage_root, &path)?;
        if !path.is_file() {
            return Err(ComponentError::new(
                "SELF_TEST_FAILED",
                format!(
                    "Self-test executable {} is missing from the stage.",
                    path.display()
                ),
                false,
            ));
        }
        (path, command.iter().skip(1).cloned().collect())
    } else {
        return Err(ComponentError::new(
            "SELF_TEST_COMMAND_REJECTED",
            "Self-test must execute a staged relative command or an allowlisted local interpreter.",
            false,
        ));
    };
    if arguments.iter().any(|argument| argument.contains('\0')) {
        return Err(ComponentError::new(
            "SELF_TEST_COMMAND_REJECTED",
            "Self-test arguments cannot contain NUL characters.",
            false,
        ));
    }
    let working_directory = if let Some(working_directory) = &manifest.entrypoint.working_directory
    {
        let path = stage_root.join(working_directory);
        ensure_safe_existing_path(stage_root, &path)?;
        path
    } else {
        stage_root.to_path_buf()
    };
    if !working_directory.is_dir() {
        return Err(ComponentError::new(
            "SELF_TEST_FAILED",
            "The constrained self-test working directory is missing.",
            false,
        ));
    }
    let mut command = Command::new(&program);
    command
        .args(&arguments)
        .current_dir(&working_directory)
        // Do not inherit arbitrary caller variables, but retain the minimal
        // Windows loader/runtime perimeter required by real frozen binaries.
        .env_clear();
    #[cfg(windows)]
    for key in [
        "SystemRoot",
        "WINDIR",
        "PATH",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
    ] {
        if let Some(value) = env::var_os(key) {
            command.env(key, value);
        }
    }
    #[cfg(not(windows))]
    if let Some(value) = env::var_os("PATH") {
        command.env("PATH", value);
    }
    let mut child = command
        .env("AIVE_COMPONENT_SELF_TEST", "1")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| {
            ComponentError::new(
                "SELF_TEST_FAILED",
                format!("Could not start the constrained component self-test: {error}"),
                false,
            )
        })?;
    let deadline = std::time::Instant::now() + Duration::from_millis(manifest.self_test.timeout_ms);
    loop {
        if let Some(status) = child.try_wait().map_err(|error| {
            ComponentError::new(
                "SELF_TEST_FAILED",
                format!("Could not observe the component self-test: {error}"),
                false,
            )
        })? {
            let code = status.code().unwrap_or(-1);
            if code == manifest.self_test.expected_exit_code {
                return Ok(());
            }
            return Err(ComponentError::new(
                "SELF_TEST_FAILED",
                format!(
                    "Component self-test exited with code {code}, expected {}.",
                    manifest.self_test.expected_exit_code
                ),
                false,
            ));
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(ComponentError::new(
                "SELF_TEST_TIMEOUT",
                "The component self-test exceeded its bounded timeout.",
                false,
            ));
        }
        thread::sleep(Duration::from_millis(10));
    }
}

fn is_safe_command_path(value: &str) -> bool {
    let normalized = value.replace('\\', "/");
    !normalized.is_empty()
        && !normalized.starts_with('/')
        && !normalized.contains(':')
        && !normalized.contains('\0')
        && !normalized
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
}

fn is_allowed_test_interpreter(value: &str) -> bool {
    matches!(
        value.to_ascii_lowercase().as_str(),
        "cmd" | "cmd.exe" | "sh" | "sh.exe"
    )
}

fn allowed_interpreter(value: &str) -> PathBuf {
    if value.to_ascii_lowercase().starts_with("cmd") {
        #[cfg(windows)]
        {
            return env::var_os("ComSpec")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(r"C:\Windows\System32\cmd.exe"));
        }
        #[cfg(not(windows))]
        {
            return PathBuf::from("/bin/sh");
        }
    }
    #[cfg(windows)]
    {
        PathBuf::from(r"C:\Windows\System32\bash.exe")
    }
    #[cfg(not(windows))]
    {
        PathBuf::from("/bin/sh")
    }
}

fn extract_archive(
    archive_path: &Path,
    manifest: &ComponentManifest,
    stage_root: &Path,
) -> ManagerResult<usize> {
    let metadata =
        fs::metadata(archive_path).map_err(|error| storage_error(archive_path, error))?;
    if metadata.len() != manifest.artifact.byte_size || metadata.len() > MAX_ARTIFACT_BYTES {
        return Err(ComponentError::new(
            "ARTIFACT_SIZE_MISMATCH",
            "The archive changed after download and does not match its signed byte size.",
            false,
        ));
    }
    ensure_safe_existing_path(stage_root.parent().unwrap_or(stage_root), stage_root)?;
    match manifest.archive.format {
        ArchiveFormat::TarGz => extract_tar_gz(archive_path, manifest, stage_root),
        ArchiveFormat::Zip => extract_zip(archive_path, manifest, stage_root),
    }
}

fn archive_relative_path(name: &str, root_directory: &str) -> ManagerResult<Option<String>> {
    let normalized = name.trim_end_matches('/');
    if normalized == root_directory {
        return Ok(None);
    }
    let prefix = format!("{root_directory}/");
    let relative = normalized.strip_prefix(&prefix).ok_or_else(|| {
        ComponentError::new(
            "ARCHIVE_ROOT_MISMATCH",
            format!("Archive entry {name} is outside the signed archive root {root_directory}."),
            false,
        )
    })?;
    validate_safe_relative_path(relative, "archive entry path")?;
    Ok(Some(relative.to_string()))
}

fn register_archive_entry(
    observed: &mut BTreeMap<String, (String, u64, String)>,
    relative: &str,
    kind: &str,
    size: u64,
    digest: String,
) -> ManagerResult<()> {
    let key = path_key(relative);
    if observed
        .insert(key, (kind.to_string(), size, digest))
        .is_some()
    {
        return Err(ComponentError::new(
            "DUPLICATE_PATH",
            format!("Archive contains duplicate path {relative}."),
            false,
        ));
    }
    Ok(())
}

fn create_archive_directory(stage_root: &Path, relative: &str) -> ManagerResult<()> {
    if relative.is_empty() {
        if !stage_root.is_dir() || is_reparse_or_symlink(stage_root) {
            return Err(ComponentError::new(
                "ARCHIVE_ROOT_INVALID",
                "Archive root staging directory is missing or unsafe.",
                false,
            ));
        }
        return Ok(());
    }
    let target = stage_root.join(relative);
    ensure_child_path(stage_root, &target)?;
    if target.exists() {
        if is_reparse_or_symlink(&target) || !target.is_dir() {
            return Err(ComponentError::new(
                "ARCHIVE_PATH_COLLISION",
                format!(
                    "Archive directory path {} collides with an unsafe entry.",
                    target.display()
                ),
                false,
            ));
        }
        return Ok(());
    }
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent).map_err(|error| storage_error(parent, error))?;
        ensure_safe_existing_path(stage_root, parent)?;
    }
    fs::create_dir(&target).map_err(|error| storage_error(&target, error))?;
    Ok(())
}

fn create_archive_file(stage_root: &Path, relative: &str) -> ManagerResult<File> {
    let target = stage_root.join(relative);
    ensure_child_path(stage_root, &target)?;
    if target.exists() {
        return Err(ComponentError::new(
            "DUPLICATE_PATH",
            format!("Archive file path {} is duplicated.", target.display()),
            false,
        ));
    }
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent).map_err(|error| storage_error(parent, error))?;
        ensure_safe_existing_path(stage_root, parent)?;
    }
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&target)
        .map_err(|error| storage_error(&target, error))
}

fn validate_archive_inventory(
    observed: &BTreeMap<String, (String, u64, String)>,
    manifest: &ComponentManifest,
) -> ManagerResult<usize> {
    let expected: BTreeMap<String, &FileInventoryEntry> = manifest
        .files
        .iter()
        .map(|entry| (path_key(&entry.path), entry))
        .collect();
    if expected.len() != observed.len() {
        return Err(ComponentError::new(
            "INVENTORY_MISMATCH",
            format!(
                "Archive inventory count {} does not match signed manifest count {}.",
                observed.len(),
                expected.len()
            ),
            false,
        ));
    }
    for (key, entry) in expected {
        let Some((kind, size, digest)) = observed.get(&key) else {
            return Err(ComponentError::new(
                "INVENTORY_MISMATCH",
                format!("Archive is missing signed inventory entry {}.", entry.path),
                false,
            ));
        };
        if entry.kind != *kind || entry.byte_size != *size || entry.sha256 != *digest {
            return Err(ComponentError::new(
                "INVENTORY_MISMATCH",
                format!(
                    "Archive inventory entry {} does not match the signed manifest.",
                    entry.path
                ),
                false,
            ));
        }
    }
    Ok(observed.len())
}

fn extract_tar_gz(
    archive_path: &Path,
    manifest: &ComponentManifest,
    stage_root: &Path,
) -> ManagerResult<usize> {
    let file = File::open(archive_path).map_err(|error| storage_error(archive_path, error))?;
    let mut decoder = GzDecoder::new(file);
    let mut observed = BTreeMap::new();
    let mut total_uncompressed = 0_u64;
    let mut entries = 0_usize;
    loop {
        let Some(header) = read_tar_header(&mut decoder)? else {
            break;
        };
        entries += 1;
        if entries > MAX_ARCHIVE_ENTRIES {
            return Err(ComponentError::new(
                "ARCHIVE_ENTRY_LIMIT_EXCEEDED",
                "Archive contains more entries than the bounded inventory limit.",
                false,
            ));
        }
        let name = header.name;
        let relative = archive_relative_path(&name, &manifest.archive.root_directory)?;
        let typeflag = header.typeflag;
        let is_directory = typeflag == b'5' || name.ends_with('/');
        if !is_directory && typeflag != 0 && typeflag != b'0' {
            return Err(ComponentError::new(
                "ARCHIVE_LINK_OR_SPECIAL_FILE",
                format!(
                    "Tar entry {name} is a symlink, hardlink, device, or unsupported special file."
                ),
                false,
            ));
        }
        let Some(relative) = relative else {
            if !is_directory || header.size != 0 {
                return Err(ComponentError::new(
                    "ARCHIVE_ROOT_INVALID",
                    "The signed archive root must be a directory entry.",
                    false,
                ));
            }
            create_archive_directory(stage_root, "")?;
            continue;
        };
        if is_directory {
            if header.size != 0 {
                return Err(ComponentError::new(
                    "ARCHIVE_DIRECTORY_INVALID",
                    format!("Directory entry {name} declares non-zero content."),
                    false,
                ));
            }
            create_archive_directory(stage_root, &relative)?;
            let digest = hex_digest(&Sha256::digest([]));
            register_archive_entry(&mut observed, &relative, "directory", 0, digest)?;
            continue;
        }
        if header.size > MAX_FILE_BYTES
            || total_uncompressed.saturating_add(header.size) > MAX_UNCOMPRESSED_BYTES
        {
            return Err(ComponentError::new(
                "DECOMPRESSION_LIMIT_EXCEEDED",
                format!("Tar entry {name} exceeds the bounded decompression limits."),
                false,
            ));
        }
        let mut output = create_archive_file(stage_root, &relative)?;
        let mut remaining = header.size;
        let mut buffer = vec![0_u8; DOWNLOAD_BUFFER_BYTES];
        let mut hasher = Sha256::new();
        while remaining > 0 {
            let requested = remaining.min(buffer.len() as u64) as usize;
            let read = decoder.read(&mut buffer[..requested]).map_err(|error| {
                ComponentError::new(
                    "ARCHIVE_READ_FAILED",
                    format!("Could not read tar entry {name}: {error}"),
                    false,
                )
            })?;
            if read == 0 {
                return Err(ComponentError::new(
                    "ARCHIVE_TRUNCATED",
                    format!("Tar entry {name} ended before its declared byte size."),
                    false,
                ));
            }
            output
                .write_all(&buffer[..read])
                .map_err(|error| storage_error(&stage_root.join(&relative), error))?;
            hasher.update(&buffer[..read]);
            remaining -= read as u64;
        }
        output
            .sync_all()
            .map_err(|error| storage_error(&stage_root.join(&relative), error))?;
        let padding = (512 - (header.size % 512)) % 512;
        skip_bytes(&mut decoder, padding)?;
        total_uncompressed = total_uncompressed.saturating_add(header.size);
        register_archive_entry(
            &mut observed,
            &relative,
            "file",
            header.size,
            hex_digest(&hasher.finalize()),
        )?;
    }
    let mut second_terminator = [0_u8; 512];
    decoder
        .read_exact(&mut second_terminator)
        .map_err(|error| {
            ComponentError::new(
                "ARCHIVE_TERMINATOR_INVALID",
                format!("Tar archive is missing its second zero terminator block: {error}"),
                false,
            )
        })?;
    if second_terminator.iter().any(|byte| *byte != 0) {
        return Err(ComponentError::new(
            "ARCHIVE_TRAILING_DATA",
            "Tar archive contains non-zero data after its first terminator block.",
            false,
        ));
    }
    let mut trailing = [0_u8; 1];
    if decoder.read(&mut trailing).map_err(|error| {
        ComponentError::new(
            "ARCHIVE_READ_FAILED",
            format!("Could not check tar archive trailing data: {error}"),
            false,
        )
    })? != 0
    {
        return Err(ComponentError::new(
            "ARCHIVE_TRAILING_DATA",
            "Tar archive contains data after its required terminator blocks.",
            false,
        ));
    }
    validate_archive_inventory(&observed, manifest)
}

#[derive(Debug)]
struct TarHeader {
    name: String,
    size: u64,
    typeflag: u8,
}

fn read_tar_header(reader: &mut impl Read) -> ManagerResult<Option<TarHeader>> {
    let mut header = [0_u8; 512];
    let mut first = [0_u8; 1];
    let read = reader.read(&mut first).map_err(|error| {
        ComponentError::new(
            "ARCHIVE_READ_FAILED",
            format!("Could not read tar header: {error}"),
            false,
        )
    })?;
    if read == 0 {
        return Ok(None);
    }
    header[0] = first[0];
    reader.read_exact(&mut header[1..]).map_err(|error| {
        ComponentError::new(
            "ARCHIVE_TRUNCATED",
            format!("Tar header is truncated: {error}"),
            false,
        )
    })?;
    if header.iter().all(|byte| *byte == 0) {
        return Ok(None);
    }
    let expected_checksum = parse_tar_number(&header[148..156], "tar checksum")?;
    let mut checksum_header = header;
    for byte in &mut checksum_header[148..156] {
        *byte = b' ';
    }
    let actual_checksum: u64 = checksum_header.iter().map(|byte| *byte as u64).sum();
    if expected_checksum != actual_checksum {
        return Err(ComponentError::new(
            "ARCHIVE_CHECKSUM_INVALID",
            "Tar header checksum does not match.",
            false,
        ));
    }
    let name = tar_string(&header[0..100])?;
    let prefix = tar_string(&header[345..500])?;
    let full_name = if prefix.is_empty() {
        name
    } else {
        format!("{prefix}/{name}")
    };
    let size = parse_tar_number(&header[124..136], "tar entry size")?;
    Ok(Some(TarHeader {
        name: full_name,
        size,
        typeflag: header[156],
    }))
}

fn tar_string(bytes: &[u8]) -> ManagerResult<String> {
    let length = bytes
        .iter()
        .position(|byte| *byte == 0)
        .unwrap_or(bytes.len());
    std::str::from_utf8(&bytes[..length])
        .map(ToOwned::to_owned)
        .map_err(|error| {
            ComponentError::new(
                "ARCHIVE_NAME_INVALID",
                format!("Tar entry name is not UTF-8: {error}"),
                false,
            )
        })
}

fn parse_tar_number(bytes: &[u8], field: &str) -> ManagerResult<u64> {
    let trimmed = bytes
        .iter()
        .copied()
        .skip_while(|byte| *byte == 0 || *byte == b' ')
        .take_while(|byte| *byte != 0 && *byte != b' ')
        .collect::<Vec<_>>();
    if trimmed.is_empty() {
        return Ok(0);
    }
    if trimmed.iter().any(|byte| !(b'0'..=b'7').contains(byte)) {
        return Err(ComponentError::new(
            "ARCHIVE_NUMBER_INVALID",
            format!("{field} is not a bounded octal number."),
            false,
        ));
    }
    u64::from_str_radix(std::str::from_utf8(&trimmed).unwrap_or("0"), 8).map_err(|error| {
        ComponentError::new(
            "ARCHIVE_NUMBER_INVALID",
            format!("{field} is invalid: {error}"),
            false,
        )
    })
}

fn skip_bytes(reader: &mut impl Read, mut amount: u64) -> ManagerResult<()> {
    let mut buffer = [0_u8; DOWNLOAD_BUFFER_BYTES];
    while amount > 0 {
        let requested = amount.min(buffer.len() as u64) as usize;
        let read = reader.read(&mut buffer[..requested]).map_err(|error| {
            ComponentError::new(
                "ARCHIVE_READ_FAILED",
                format!("Could not skip archive padding: {error}"),
                false,
            )
        })?;
        if read == 0 {
            return Err(ComponentError::new(
                "ARCHIVE_TRUNCATED",
                "Archive ended before its padding was consumed.",
                false,
            ));
        }
        amount -= read as u64;
    }
    Ok(())
}

fn extract_zip(
    archive_path: &Path,
    manifest: &ComponentManifest,
    stage_root: &Path,
) -> ManagerResult<usize> {
    let metadata =
        fs::metadata(archive_path).map_err(|error| storage_error(archive_path, error))?;
    if metadata.len() > MAX_ARTIFACT_BYTES || metadata.len() < 22 {
        return Err(ComponentError::new(
            "ARCHIVE_LIMIT_EXCEEDED",
            "ZIP archive is outside the bounded archive size.",
            false,
        ));
    }
    let mut file = File::open(archive_path).map_err(|error| storage_error(archive_path, error))?;
    let read_length = metadata.len().min(65_557) as usize;
    file.seek(SeekFrom::End(-(read_length as i64)))
        .map_err(|error| storage_error(archive_path, error))?;
    let mut tail = vec![0_u8; read_length];
    file.read_exact(&mut tail)
        .map_err(|error| storage_error(archive_path, error))?;
    let eocd_offset = tail
        .windows(4)
        .rposition(|window| window == b"PK\x05\x06")
        .ok_or_else(|| {
            ComponentError::new(
                "ZIP_DIRECTORY_INVALID",
                "ZIP end-of-central-directory record is missing.",
                false,
            )
        })?;
    if eocd_offset + 22 > tail.len() {
        return Err(ComponentError::new(
            "ZIP_DIRECTORY_INVALID",
            "ZIP directory record is truncated.",
            false,
        ));
    }
    let disk = read_u16(&tail, eocd_offset + 4)?;
    let central_disk = read_u16(&tail, eocd_offset + 6)?;
    let entries_on_disk = read_u16(&tail, eocd_offset + 8)?;
    let entries_total = read_u16(&tail, eocd_offset + 10)?;
    let central_size = read_u32(&tail, eocd_offset + 12)? as u64;
    let central_offset = read_u32(&tail, eocd_offset + 16)? as u64;
    if disk != 0
        || central_disk != 0
        || entries_on_disk != entries_total
        || entries_total == 0xffff
        || central_size > MAX_ARTIFACT_BYTES
        || central_offset > metadata.len()
    {
        return Err(ComponentError::new(
            "ZIP64_OR_MULTI_DISK_UNSUPPORTED",
            "ZIP64 and multi-disk archives are not accepted by the bounded verifier.",
            false,
        ));
    }
    let central_end = central_offset.saturating_add(central_size);
    if central_end > metadata.len() {
        return Err(ComponentError::new(
            "ZIP_DIRECTORY_INVALID",
            "ZIP central directory lies outside the archive.",
            false,
        ));
    }
    file.seek(SeekFrom::Start(central_offset))
        .map_err(|error| storage_error(archive_path, error))?;
    let mut central = vec![0_u8; central_size as usize];
    file.read_exact(&mut central)
        .map_err(|error| storage_error(archive_path, error))?;
    let mut cursor = 0_usize;
    let mut observed = BTreeMap::new();
    let mut total_uncompressed = 0_u64;
    for _ in 0..entries_total {
        if observed.len() >= MAX_ARCHIVE_ENTRIES {
            return Err(ComponentError::new(
                "ARCHIVE_ENTRY_LIMIT_EXCEEDED",
                "ZIP archive contains more entries than the bounded inventory limit.",
                false,
            ));
        }
        if cursor + 46 > central.len() || read_u32(&central, cursor)? != 0x0201_4b50 {
            return Err(ComponentError::new(
                "ZIP_DIRECTORY_INVALID",
                "ZIP central-directory entry is invalid.",
                false,
            ));
        }
        let flags = read_u16(&central, cursor + 8)?;
        let method = read_u16(&central, cursor + 10)?;
        let compressed_size = read_u32(&central, cursor + 20)? as u64;
        let uncompressed_size = read_u32(&central, cursor + 24)? as u64;
        let name_length = read_u16(&central, cursor + 28)? as usize;
        let extra_length = read_u16(&central, cursor + 30)? as usize;
        let comment_length = read_u16(&central, cursor + 32)? as usize;
        let external_attributes = read_u32(&central, cursor + 38)?;
        let local_offset = read_u32(&central, cursor + 42)? as u64;
        let end = cursor
            .checked_add(46)
            .and_then(|value| value.checked_add(name_length))
            .and_then(|value| value.checked_add(extra_length))
            .and_then(|value| value.checked_add(comment_length))
            .ok_or_else(|| {
                ComponentError::new(
                    "ZIP_DIRECTORY_INVALID",
                    "ZIP directory lengths overflowed.",
                    false,
                )
            })?;
        if end > central.len() {
            return Err(ComponentError::new(
                "ZIP_DIRECTORY_INVALID",
                "ZIP central-directory entry is truncated.",
                false,
            ));
        }
        if flags & 1 != 0 {
            return Err(ComponentError::new(
                "ZIP_ENCRYPTED_REJECTED",
                "Encrypted ZIP entries cannot be verified offline.",
                false,
            ));
        }
        if method != 0 && method != 8 {
            return Err(ComponentError::new(
                "ZIP_COMPRESSION_UNSUPPORTED",
                "Only stored and deflate ZIP entries are supported.",
                false,
            ));
        }
        let name = std::str::from_utf8(&central[cursor + 46..cursor + 46 + name_length])
            .map_err(|error| {
                ComponentError::new(
                    "ARCHIVE_NAME_INVALID",
                    format!("ZIP entry name is not UTF-8: {error}"),
                    false,
                )
            })?
            .to_string();
        if ((external_attributes >> 16) & 0o170000) == 0o120000 {
            return Err(ComponentError::new(
                "ARCHIVE_LINK_OR_SPECIAL_FILE",
                format!("ZIP entry {name} is marked as a symlink or special file."),
                false,
            ));
        }
        let relative = archive_relative_path(&name, &manifest.archive.root_directory)?;
        let local_offset_usize = usize::try_from(local_offset).map_err(|_| {
            ComponentError::new(
                "ZIP_DIRECTORY_INVALID",
                "ZIP local-header offset is too large.",
                false,
            )
        })?;
        if local_offset_usize + 30 > metadata.len() as usize
            || read_u32_from_file(&mut file, local_offset_usize)? != 0x0403_4b50
        {
            return Err(ComponentError::new(
                "ZIP_LOCAL_HEADER_INVALID",
                "ZIP local header is invalid.",
                false,
            ));
        }
        file.seek(SeekFrom::Start(local_offset + 26))
            .map_err(|error| storage_error(archive_path, error))?;
        let mut lengths = [0_u8; 4];
        file.read_exact(&mut lengths)
            .map_err(|error| storage_error(archive_path, error))?;
        let local_name_length = u16::from_le_bytes([lengths[0], lengths[1]]) as usize;
        let local_extra_length = u16::from_le_bytes([lengths[2], lengths[3]]) as usize;
        let data_offset = local_offset
            .saturating_add(30)
            .saturating_add(local_name_length as u64)
            .saturating_add(local_extra_length as u64);
        if data_offset.saturating_add(compressed_size) > metadata.len() {
            return Err(ComponentError::new(
                "ZIP_ENTRY_TRUNCATED",
                format!("ZIP entry {name} exceeds archive bounds."),
                false,
            ));
        }
        file.seek(SeekFrom::Start(data_offset))
            .map_err(|error| storage_error(archive_path, error))?;
        let mut compressed = vec![0_u8; compressed_size as usize];
        file.read_exact(&mut compressed)
            .map_err(|error| storage_error(archive_path, error))?;
        let is_directory = name.ends_with('/');
        let Some(relative) = relative else {
            if !is_directory || uncompressed_size != 0 {
                return Err(ComponentError::new(
                    "ARCHIVE_ROOT_INVALID",
                    "The signed ZIP root must be a directory.",
                    false,
                ));
            }
            cursor = end;
            continue;
        };
        if is_directory {
            if uncompressed_size != 0 {
                return Err(ComponentError::new(
                    "ARCHIVE_DIRECTORY_INVALID",
                    format!("ZIP directory {name} declares content."),
                    false,
                ));
            }
            create_archive_directory(stage_root, &relative)?;
            register_archive_entry(
                &mut observed,
                &relative,
                "directory",
                0,
                hex_digest(&Sha256::digest([])),
            )?;
        } else {
            if uncompressed_size > MAX_FILE_BYTES
                || total_uncompressed.saturating_add(uncompressed_size) > MAX_UNCOMPRESSED_BYTES
            {
                return Err(ComponentError::new(
                    "DECOMPRESSION_LIMIT_EXCEEDED",
                    format!("ZIP entry {name} exceeds the bounded decompression limits."),
                    false,
                ));
            }
            let target = stage_root.join(&relative);
            let mut output = create_archive_file(stage_root, &relative)?;
            let mut hasher = Sha256::new();
            let mut written = 0_u64;
            if method == 0 {
                output
                    .write_all(&compressed)
                    .map_err(|error| storage_error(&target, error))?;
                hasher.update(&compressed);
                written = compressed.len() as u64;
            } else {
                let mut decoder = flate2::read::DeflateDecoder::new(compressed.as_slice());
                let mut buffer = vec![0_u8; DOWNLOAD_BUFFER_BYTES];
                loop {
                    let read = decoder.read(&mut buffer).map_err(|error| {
                        ComponentError::new(
                            "ARCHIVE_READ_FAILED",
                            format!("Could not inflate ZIP entry {name}: {error}"),
                            false,
                        )
                    })?;
                    if read == 0 {
                        break;
                    }
                    written = written.saturating_add(read as u64);
                    if written > uncompressed_size || written > MAX_FILE_BYTES {
                        return Err(ComponentError::new(
                            "DECOMPRESSION_LIMIT_EXCEEDED",
                            format!("ZIP entry {name} exceeded its declared size."),
                            false,
                        ));
                    }
                    output
                        .write_all(&buffer[..read])
                        .map_err(|error| storage_error(&target, error))?;
                    hasher.update(&buffer[..read]);
                }
            }
            if written != uncompressed_size {
                return Err(ComponentError::new(
                    "ZIP_SIZE_MISMATCH",
                    format!("ZIP entry {name} inflated to {written} bytes, expected {uncompressed_size}."),
                    false,
                ));
            }
            output
                .sync_all()
                .map_err(|error| storage_error(&target, error))?;
            total_uncompressed = total_uncompressed.saturating_add(written);
            register_archive_entry(
                &mut observed,
                &relative,
                "file",
                written,
                hex_digest(&hasher.finalize()),
            )?;
        }
        cursor = end;
    }
    if cursor != central.len() {
        // A non-empty remainder is usually an unsupported central-directory
        // extension; rejecting it avoids silently ignoring duplicate records.
        return Err(ComponentError::new(
            "ZIP_DIRECTORY_INVALID",
            "ZIP central directory contains unparsed bytes.",
            false,
        ));
    }
    validate_archive_inventory(&observed, manifest)
}

fn read_u16(bytes: &[u8], offset: usize) -> ManagerResult<u16> {
    let slice = bytes.get(offset..offset + 2).ok_or_else(|| {
        ComponentError::new(
            "ARCHIVE_TRUNCATED",
            "Archive integer field is truncated.",
            false,
        )
    })?;
    Ok(u16::from_le_bytes([slice[0], slice[1]]))
}

fn read_u32(bytes: &[u8], offset: usize) -> ManagerResult<u32> {
    let slice = bytes.get(offset..offset + 4).ok_or_else(|| {
        ComponentError::new(
            "ARCHIVE_TRUNCATED",
            "Archive integer field is truncated.",
            false,
        )
    })?;
    Ok(u32::from_le_bytes([slice[0], slice[1], slice[2], slice[3]]))
}

fn read_u32_from_file(file: &mut File, offset: usize) -> ManagerResult<u32> {
    file.seek(SeekFrom::Start(offset as u64))
        .map_err(|error| ComponentError::new("ZIP_READ_FAILED", error.to_string(), false))?;
    let mut bytes = [0_u8; 4];
    file.read_exact(&mut bytes)
        .map_err(|error| ComponentError::new("ZIP_READ_FAILED", error.to_string(), false))?;
    Ok(u32::from_le_bytes(bytes))
}

fn tauri_manager() -> ComponentManager {
    let paths = crate::desktop_v2::get_canonical_paths();
    ComponentManager::new(PathBuf::from(paths.program_data_root).join("AI Video Editor"))
}

fn command_policy(requested_offline_sources: bool) -> SourcePolicy {
    SourcePolicy {
        allow_local_test_sources: requested_offline_sources,
    }
}

fn emit_tauri_progress(app: &AppHandle, event: ComponentProgress) {
    let _ = app.emit(COMPONENT_PROGRESS_EVENT, event);
}

fn join_error(error: tauri::Error) -> ComponentError {
    ComponentError::new(
        "COMPONENT_OPERATION_FAILED",
        format!("Component operation task failed: {error}"),
        true,
    )
}

fn record_component_result<T>(operation: &str, result: &ManagerResult<T>) {
    match result {
        Ok(_) => crate::operation_log::append_operation("component", "success", operation),
        Err(error) => crate::operation_log::append_operation(
            "component",
            "error",
            &format!("{operation}: {}", error.code),
        ),
    }
}

#[tauri::command]
pub fn component_intake_manifest(
    manifest_json: String,
    allow_test_sources: bool,
) -> ManagerResult<ManifestIntakeResult> {
    let result =
        tauri_manager().intake_manifest(&manifest_json, command_policy(allow_test_sources));
    record_component_result("manifest-intake", &result);
    result
}

#[tauri::command]
pub fn component_resolve_plan(
    component_id: String,
    target_version: Option<String>,
    allow_test_sources: bool,
) -> ManagerResult<InstallationPlan> {
    let result = tauri_manager().resolve_plan(
        &component_id,
        target_version.as_deref(),
        command_policy(allow_test_sources),
    );
    record_component_result("resolve-plan", &result);
    result
}

#[tauri::command]
pub fn component_status(component_id: Option<String>) -> ManagerResult<Vec<ComponentStatusResult>> {
    tauri_manager().status(component_id.as_deref())
}

#[tauri::command]
pub async fn component_download(
    app: AppHandle,
    state: State<'_, ComponentManagerState>,
    component_id: String,
    component_version: String,
    operation_id: Option<String>,
    allow_test_sources: bool,
) -> ManagerResult<DownloadResult> {
    let operation_id = operation_id.unwrap_or_else(|| format!("download-{}", now_epoch_ms()));
    let control = state.register(&operation_id);
    let manager = tauri_manager();
    let progress_app = app.clone();
    let policy = command_policy(allow_test_sources);
    let operation_id_for_task = operation_id.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        let emit = |event: ComponentProgress| emit_tauri_progress(&progress_app, event);
        manager.download(
            &component_id,
            &component_version,
            policy,
            Some(operation_id_for_task),
            control,
            Some(&emit),
        )
    })
    .await
    .map_err(join_error)?;
    state.remove(&operation_id);
    record_component_result("download", &result);
    result
}

#[tauri::command]
pub fn component_pause(
    state: State<'_, ComponentManagerState>,
    operation_id: String,
) -> ManagerResult<bool> {
    if state.set_pause(&operation_id, true) {
        Ok(true)
    } else {
        Err(ComponentError::new(
            "OPERATION_NOT_FOUND",
            "No active component download owns that operation id.",
            false,
        ))
    }
}

#[tauri::command]
pub fn component_cancel(
    state: State<'_, ComponentManagerState>,
    operation_id: String,
) -> ManagerResult<bool> {
    if state.set_cancel(&operation_id) {
        Ok(true)
    } else {
        Err(ComponentError::new(
            "OPERATION_NOT_FOUND",
            "No active component download owns that operation id.",
            false,
        ))
    }
}

#[tauri::command]
pub async fn component_retry(
    app: AppHandle,
    state: State<'_, ComponentManagerState>,
    component_id: String,
    component_version: String,
    operation_id: Option<String>,
    allow_test_sources: bool,
) -> ManagerResult<DownloadResult> {
    let operation_id = operation_id.unwrap_or_else(|| format!("retry-{}", now_epoch_ms()));
    let control = state.register(&operation_id);
    let manager = tauri_manager();
    let progress_app = app.clone();
    let policy = command_policy(allow_test_sources);
    let operation_id_for_task = operation_id.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        let emit = |event: ComponentProgress| emit_tauri_progress(&progress_app, event);
        manager.retry_download(
            &component_id,
            &component_version,
            Some(operation_id_for_task),
            policy,
            control,
            Some(&emit),
        )
    })
    .await
    .map_err(join_error)?;
    state.remove(&operation_id);
    record_component_result("retry", &result);
    result
}

#[tauri::command]
pub fn component_verify(
    component_id: String,
    component_version: String,
    allow_test_sources: bool,
) -> ManagerResult<VerificationResult> {
    let result = tauri_manager().verify(
        &component_id,
        &component_version,
        command_policy(allow_test_sources),
    );
    record_component_result("verify", &result);
    result
}

#[tauri::command]
pub fn component_stage(
    app: AppHandle,
    component_id: String,
    component_version: String,
    operation_id: Option<String>,
    allow_test_sources: bool,
) -> ManagerResult<StageResult> {
    let progress = |event: ComponentProgress| emit_tauri_progress(&app, event);
    let result = tauri_manager().stage(
        &component_id,
        &component_version,
        command_policy(allow_test_sources),
        operation_id,
        Some(&progress),
    );
    record_component_result("stage", &result);
    result
}

#[tauri::command]
pub fn component_activate(
    app: AppHandle,
    component_id: String,
    component_version: String,
    operation_id: Option<String>,
    allow_test_sources: bool,
) -> ManagerResult<ActivationResult> {
    let progress = |event: ComponentProgress| emit_tauri_progress(&app, event);
    let result = tauri_manager().activate(
        &component_id,
        &component_version,
        command_policy(allow_test_sources),
        operation_id,
        Some(&progress),
    );
    record_component_result("activate", &result);
    result
}

#[tauri::command]
pub fn component_rollback(
    app: AppHandle,
    component_id: String,
    allow_test_sources: bool,
) -> ManagerResult<ActivationResult> {
    let progress = |event: ComponentProgress| emit_tauri_progress(&app, event);
    let result = tauri_manager().rollback(
        &component_id,
        command_policy(allow_test_sources),
        Some(&progress),
    );
    record_component_result("rollback", &result);
    result
}

#[tauri::command]
pub fn component_repair(
    app: AppHandle,
    component_id: String,
    allow_test_sources: bool,
) -> ManagerResult<RepairResult> {
    let progress = |event: ComponentProgress| emit_tauri_progress(&app, event);
    let result = tauri_manager().repair(
        &component_id,
        command_policy(allow_test_sources),
        Some(&progress),
    );
    record_component_result("repair", &result);
    result
}

#[tauri::command]
pub fn component_uninstall(component_id: String) -> ManagerResult<UninstallResult> {
    let result = tauri_manager().uninstall(&component_id);
    record_component_result("uninstall", &result);
    result
}

#[tauri::command]
pub fn component_recover() -> ManagerResult<RecoveryResult> {
    let result = tauri_manager().recover();
    record_component_result("recover", &result);
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::GzEncoder;
    use flate2::Compression;
    use ring::signature::{Ed25519KeyPair, KeyPair};

    // Non-production fixture material only. No private seed is committed;
    // both the Rust tests and Python packager derive the throwaway key from
    // this public label.
    const TEST_FIXTURE_KEY_LABEL: &[u8] = b"Desktop V2 Phase 3 NON-PRODUCTION FIXTURE KEY";
    static TEST_ROOT_COUNTER: AtomicUsize = AtomicUsize::new(0);

    struct TestRoot {
        root: PathBuf,
        manager: ComponentManager,
    }

    impl TestRoot {
        fn new() -> Self {
            let root = env::temp_dir().join(format!(
                "aive-component-manager-{}-{}-{}",
                std::process::id(),
                now_epoch_ms(),
                TEST_ROOT_COUNTER.fetch_add(1, Ordering::Relaxed)
            ));
            let _ = fs::remove_dir_all(&root);
            let manager = ComponentManager::new(root.join("machine"));
            Self { root, manager }
        }

        fn fixture(&self, version: &str) -> ComponentManifest {
            let archive_root = format!("synthetic-{version}");
            let engine = b"synthetic engine fixture\n".to_vec();
            let notice = b"synthetic notice\n".to_vec();
            let entries = vec![
                (format!("{archive_root}/"), b'5', Vec::new(), None),
                (format!("{archive_root}/bin/"), b'5', Vec::new(), None),
                (format!("{archive_root}/LICENSES/"), b'5', Vec::new(), None),
                (
                    format!("{archive_root}/bin/synthetic-engine.exe"),
                    b'0',
                    engine.clone(),
                    None,
                ),
                (
                    format!("{archive_root}/LICENSES/NOTICE.txt"),
                    b'0',
                    notice.clone(),
                    None,
                ),
            ];
            let archive_path = self.root.join(format!("synthetic-{version}.tar.gz"));
            write_test_tar(&archive_path, &entries);
            let (byte_size, sha256) = write_file_hash(&archive_path).expect("test archive hash");
            let mut manifest = base_manifest(
                version,
                archive_root,
                archive_path,
                byte_size,
                sha256,
                vec![
                    inventory_directory("bin"),
                    inventory_directory("LICENSES"),
                    inventory_file("bin/synthetic-engine.exe", &engine),
                    inventory_file("LICENSES/NOTICE.txt", &notice),
                ],
            );
            sign_test_manifest(&mut manifest);
            manifest
        }

        fn intake(&self, manifest: &ComponentManifest) {
            self.manager
                .intake_manifest(
                    &serde_json::to_string(manifest).expect("manifest json"),
                    SourcePolicy::development_test(),
                )
                .expect("manifest intake");
        }
    }

    impl Drop for TestRoot {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn inventory_directory(path: &str) -> FileInventoryEntry {
        FileInventoryEntry {
            path: path.to_string(),
            kind: "directory".to_string(),
            byte_size: 0,
            sha256: hex_digest(&Sha256::digest([])),
            executable: false,
        }
    }

    fn inventory_file(path: &str, data: &[u8]) -> FileInventoryEntry {
        FileInventoryEntry {
            path: path.to_string(),
            kind: "file".to_string(),
            byte_size: data.len() as u64,
            sha256: hex_digest(&Sha256::digest(data)),
            executable: path.ends_with(".exe"),
        }
    }

    fn base_manifest(
        version: &str,
        archive_root: String,
        archive_path: PathBuf,
        byte_size: u64,
        sha256: String,
        files: Vec<FileInventoryEntry>,
    ) -> ComponentManifest {
        ComponentManifest {
            schema_version: COMPONENT_MANIFEST_SCHEMA.to_string(),
            component: ComponentIdentity {
                id: "synthetic".to_string(),
                component_type: ComponentType::Utility,
                version: version.to_string(),
                channel: ReleaseChannel::Stable,
            },
            target: Target {
                operating_systems: vec![current_operating_system()],
                architectures: vec![current_architecture()],
            },
            requirements: Requirements {
                minimum_shell_version: "1.0.0".to_string(),
                requires_elevation: false,
            },
            artifact: Artifact {
                url: Url::from_file_path(archive_path)
                    .expect("file url")
                    .to_string(),
                byte_size,
                sha256,
            },
            signature: DetachedSignature {
                algorithm: "ed25519".to_string(),
                value: String::new(),
                key_id: TEST_FIXTURE_KEY_ID.to_string(),
            },
            archive: Archive {
                format: ArchiveFormat::TarGz,
                root_directory: archive_root,
            },
            install: InstallLayout {
                root_kind: "program-data-components".to_string(),
                relative_path: format!("synthetic/{version}"),
                immutable: true,
                activation: ActivationLayout {
                    strategy: "stage-then-atomic-rename".to_string(),
                    active_path: "synthetic/active".to_string(),
                    staging_path: format!("synthetic/.staging/{version}"),
                    metadata_path: "synthetic/activation.json".to_string(),
                    atomic_commit: true,
                },
            },
            entrypoint: Entrypoint {
                kind: "executable".to_string(),
                relative_path: "bin/synthetic-engine.exe".to_string(),
                arguments: vec!["--self-test".to_string()],
                working_directory: None,
            },
            dependencies: Vec::new(),
            capabilities: vec!["api".to_string()],
            metadata: ComponentMetadata {
                display_name: "Synthetic Component".to_string(),
                publisher: "Phase 3 Tests".to_string(),
                license: LicenseMetadata {
                    spdx_id: "MIT".to_string(),
                    notice_file: "LICENSES/NOTICE.txt".to_string(),
                },
                source: SourceMetadata {
                    repository_url: "https://example.test/repository".to_string(),
                    release_url: "https://example.test/release".to_string(),
                },
            },
            files,
            self_test: SelfTest {
                command: if cfg!(windows) {
                    vec![
                        "cmd.exe".to_string(),
                        "/D".to_string(),
                        "/C".to_string(),
                        "exit 0".to_string(),
                    ]
                } else {
                    vec!["sh".to_string(), "-c".to_string(), "exit 0".to_string()]
                },
                timeout_ms: 5_000,
                expected_exit_code: 0,
            },
            health: HealthContract {
                probe: "http".to_string(),
                path: "/health".to_string(),
                method: "GET".to_string(),
                timeout_ms: 1_000,
                readiness_schema_version: "desktop.health-readiness.v1".to_string(),
                requires_bearer_token: true,
            },
            rollback: RollbackMetadata {
                strategy: "retain-previous-active".to_string(),
                retention_count: 2,
                metadata_path: "synthetic/activation.json".to_string(),
                on_activation_failure: "rollback-automatically".to_string(),
            },
        }
    }

    fn sign_test_manifest(manifest: &mut ComponentManifest) {
        let seed = Sha256::digest(TEST_FIXTURE_KEY_LABEL);
        let key = Ed25519KeyPair::from_seed_unchecked(seed.as_ref()).expect("test key");
        let payload = manifest_signature_payload(manifest).expect("signature payload");
        manifest.signature.value = BASE64.encode(key.sign(&payload).as_ref());
        assert_eq!(
            BASE64.encode(key.public_key().as_ref()),
            TEST_FIXTURE_PUBLIC_KEY_B64
        );
    }

    fn write_test_tar(path: &Path, entries: &[(String, u8, Vec<u8>, Option<u64>)]) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("archive parent");
        }
        let file = File::create(path).expect("archive");
        let mut encoder = GzEncoder::new(file, Compression::default());
        for (name, typeflag, data, declared_size) in entries {
            let size = declared_size.unwrap_or(data.len() as u64);
            let mut header = [0_u8; 512];
            let name_bytes = name.as_bytes();
            assert!(name_bytes.len() < 100);
            header[..name_bytes.len()].copy_from_slice(name_bytes);
            write_octal(&mut header[100..108], 0o644);
            write_octal(&mut header[108..116], 0);
            write_octal(&mut header[116..124], 0);
            write_octal(&mut header[124..136], size);
            write_octal(&mut header[136..148], 0);
            header[148..156].fill(b' ');
            header[156] = *typeflag;
            header[257..263].copy_from_slice(b"ustar\0");
            header[263..265].copy_from_slice(b"00");
            let checksum: u64 = header.iter().map(|byte| *byte as u64).sum();
            let checksum_text = format!("{checksum:06o}\0 ");
            header[148..156].copy_from_slice(checksum_text.as_bytes());
            encoder.write_all(&header).expect("tar header");
            encoder.write_all(data).expect("tar data");
            let padding = (512 - (size % 512)) % 512;
            if padding > 0 {
                encoder
                    .write_all(&vec![0_u8; padding as usize])
                    .expect("tar padding");
            }
        }
        encoder.write_all(&[0_u8; 1024]).expect("tar terminator");
        encoder.finish().expect("gzip finish");
    }

    fn write_octal(destination: &mut [u8], value: u64) {
        let text = format!("{value:0width$o}\0", width = destination.len() - 1);
        destination.copy_from_slice(text.as_bytes());
    }

    fn assert_code<T: std::fmt::Debug>(result: ManagerResult<T>, code: &str) {
        let error = result.expect_err("operation unexpectedly succeeded");
        assert_eq!(error.code, code, "unexpected component error: {error}");
    }

    #[test]
    fn valid_component_can_be_packaged_downloaded_verified_staged_and_activated() {
        let root = TestRoot::new();
        let manifest = root.fixture("1.0.0");
        root.intake(&manifest);
        let plan = root
            .manager
            .resolve_plan("synthetic", Some("1.0.0"), SourcePolicy::development_test())
            .expect("plan");
        assert_eq!(plan.target_version, "1.0.0");
        let download = root
            .manager
            .download(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("download-valid".to_string()),
                OperationControl::default(),
                None,
            )
            .expect("download");
        assert_eq!(download.state, "downloaded");
        let verification = root
            .manager
            .verify("synthetic", "1.0.0", SourcePolicy::development_test())
            .expect("verification");
        assert_eq!(verification.state, "verified");
        let stage = root
            .manager
            .stage(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("stage-valid".to_string()),
                None,
            )
            .expect("stage");
        let activation = root
            .manager
            .activate(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some(stage.operation_id),
                None,
            )
            .expect("activation");
        assert_eq!(activation.state, "active");
        let statuses = root.manager.status(Some("synthetic")).expect("status");
        assert_eq!(statuses[0].state, "active");
        assert!(statuses[0]
            .active_path
            .as_deref()
            .is_some_and(|path| path.contains("Components")));
        let verified = root
            .manager
            .verified_active_component(
                "synthetic",
                ComponentType::Utility,
                SourcePolicy::development_test(),
            )
            .expect("verified launch plan");
        assert_eq!(verified.component_version, "1.0.0");
        assert!(verified.executable_path.ends_with("synthetic-engine.exe"));
    }

    #[test]
    fn bad_hash_signature_unknown_key_schema_and_target_are_rejected() {
        let root = TestRoot::new();
        let base = root.fixture("1.0.0");

        // Hash mismatch is detected after a downloaded archive is available;
        // manifest intake itself remains catalog-only.
        let mut bad_hash_intake = base.clone();
        bad_hash_intake.artifact.sha256 = "0".repeat(64);
        sign_test_manifest(&mut bad_hash_intake);
        let result = root.manager.intake_manifest(
            &serde_json::to_string(&bad_hash_intake).unwrap(),
            SourcePolicy::development_test(),
        );
        assert!(result.is_ok());
        root.manager
            .download(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("bad-hash-download".to_string()),
                OperationControl::default(),
                None,
            )
            .expect("download bad hash fixture");
        assert_code(
            root.manager
                .verify("synthetic", "1.0.0", SourcePolicy::development_test()),
            "ARTIFACT_HASH_MISMATCH",
        );

        let mut bad_signature = base.clone();
        bad_signature.signature.value = BASE64.encode([0_u8; 64]);
        assert_code(
            root.manager.intake_manifest(
                &serde_json::to_string(&bad_signature).unwrap(),
                SourcePolicy::development_test(),
            ),
            "SIGNATURE_INVALID",
        );

        let mut unknown_key = base.clone();
        unknown_key.signature.key_id = "manifest-key-2026".to_string();
        assert_code(
            root.manager.intake_manifest(
                &serde_json::to_string(&unknown_key).unwrap(),
                SourcePolicy::development_test(),
            ),
            "UNKNOWN_TRUST_KEY",
        );

        let mut wrong_schema = base.clone();
        wrong_schema.schema_version = "desktop.component-manifest.v2".to_string();
        sign_test_manifest(&mut wrong_schema);
        assert_code(
            root.manager.intake_manifest(
                &serde_json::to_string(&wrong_schema).unwrap(),
                SourcePolicy::development_test(),
            ),
            "SCHEMA_VERSION_UNSUPPORTED",
        );

        let mut wrong_arch = base.clone();
        wrong_arch.target.architectures = vec![match current_architecture() {
            Architecture::X86 => Architecture::X86_64,
            Architecture::X86_64 => Architecture::X86,
            Architecture::Aarch64 => Architecture::X86_64,
        }];
        sign_test_manifest(&mut wrong_arch);
        assert_code(
            root.manager.intake_manifest(
                &serde_json::to_string(&wrong_arch).unwrap(),
                SourcePolicy::development_test(),
            ),
            "ARCHITECTURE_INCOMPATIBLE",
        );
    }

    #[test]
    fn production_requires_https_and_dependency_plan_is_explicit() {
        let root = TestRoot::new();
        let mut manifest = root.fixture("1.0.0");
        assert_code(
            root.manager.intake_manifest(
                &serde_json::to_string(&manifest).unwrap(),
                SourcePolicy::PRODUCTION,
            ),
            "HTTPS_REQUIRED",
        );
        let source = Url::parse("https://example.test/synthetic.tar.gz").unwrap();
        manifest.artifact.url = source.to_string();
        manifest.dependencies.push(Dependency {
            id: "missing-dependency".to_string(),
            version_constraint: ">=1.0.0".to_string(),
            optional: false,
        });
        sign_test_manifest(&mut manifest);
        root.manager
            .intake_manifest(
                &serde_json::to_string(&manifest).unwrap(),
                SourcePolicy::PRODUCTION,
            )
            .expect("HTTPS catalog intake");
        assert_code(
            root.manager
                .resolve_plan("synthetic", Some("1.0.0"), SourcePolicy::PRODUCTION),
            "DEPENDENCY_UNSATISFIED",
        );
    }

    #[test]
    fn traversal_duplicate_and_decompression_bomb_archives_fail_before_activation() {
        let root = TestRoot::new();
        let base = root.fixture("1.0.0");
        let archive_root = "synthetic-1.0.0";

        let traversal_path = root.root.join("traversal.tar.gz");
        write_test_tar(
            &traversal_path,
            &[
                (format!("{archive_root}/"), b'5', Vec::new(), None),
                (
                    format!("{archive_root}/../evil.txt"),
                    b'0',
                    b"evil".to_vec(),
                    None,
                ),
            ],
        );
        let (size, digest) = write_file_hash(&traversal_path).unwrap();
        let mut traversal = base.clone();
        traversal.artifact.url = Url::from_file_path(&traversal_path).unwrap().to_string();
        traversal.artifact.byte_size = size;
        traversal.artifact.sha256 = digest;
        sign_test_manifest(&mut traversal);
        root.intake(&traversal);
        root.manager
            .download(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("traversal-download".to_string()),
                OperationControl::default(),
                None,
            )
            .unwrap();
        assert_code(
            root.manager.stage(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("traversal-stage".to_string()),
                None,
            ),
            "UNSAFE_PATH",
        );
        assert!(!root
            .manager
            .machine_root()
            .join("Components/synthetic/1.0.0")
            .exists());

        let duplicate_path = root.root.join("duplicate.tar.gz");
        write_test_tar(
            &duplicate_path,
            &[
                (format!("{archive_root}/"), b'5', Vec::new(), None),
                (format!("{archive_root}/bin/"), b'5', Vec::new(), None),
                (format!("{archive_root}/bin/a"), b'0', b"a".to_vec(), None),
                (format!("{archive_root}/bin/a"), b'0', b"b".to_vec(), None),
            ],
        );
        let (size, digest) = write_file_hash(&duplicate_path).unwrap();
        let mut duplicate = base.clone();
        duplicate.artifact.url = Url::from_file_path(&duplicate_path).unwrap().to_string();
        duplicate.artifact.byte_size = size;
        duplicate.artifact.sha256 = digest;
        duplicate.files = vec![inventory_directory("bin"), inventory_file("bin/a", b"a")];
        sign_test_manifest(&mut duplicate);
        root.manager
            .intake_manifest(
                &serde_json::to_string(&duplicate).unwrap(),
                SourcePolicy::development_test(),
            )
            .unwrap();
        root.manager
            .download(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("duplicate-download".to_string()),
                OperationControl::default(),
                None,
            )
            .unwrap();
        assert_code(
            root.manager.stage(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("duplicate-stage".to_string()),
                None,
            ),
            "DUPLICATE_PATH",
        );

        let bomb_path = root.root.join("bomb.tar.gz");
        write_test_tar(
            &bomb_path,
            &[
                (format!("{archive_root}/"), b'5', Vec::new(), None),
                (
                    format!("{archive_root}/bomb.bin"),
                    b'0',
                    Vec::new(),
                    Some(MAX_FILE_BYTES + 1),
                ),
            ],
        );
        let (size, digest) = write_file_hash(&bomb_path).unwrap();
        let mut bomb = base;
        bomb.artifact.url = Url::from_file_path(&bomb_path).unwrap().to_string();
        bomb.artifact.byte_size = size;
        bomb.artifact.sha256 = digest;
        bomb.files = vec![inventory_file("bomb.bin", &[])];
        sign_test_manifest(&mut bomb);
        root.manager
            .intake_manifest(
                &serde_json::to_string(&bomb).unwrap(),
                SourcePolicy::development_test(),
            )
            .unwrap();
        root.manager
            .download(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("bomb-download".to_string()),
                OperationControl::default(),
                None,
            )
            .unwrap();
        assert_code(
            root.manager.stage(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("bomb-stage".to_string()),
                None,
            ),
            "DECOMPRESSION_LIMIT_EXCEEDED",
        );
    }

    #[test]
    fn interrupted_download_resumes_and_cancel_preserves_no_activation() {
        let root = TestRoot::new();
        let manifest = root.fixture("1.0.0");
        root.intake(&manifest);
        let (part, _, state) = root.manager.download_paths("synthetic", "1.0.0").unwrap();
        fs::create_dir_all(part.parent().unwrap()).unwrap();
        let source = PathBuf::from(
            Url::parse(&manifest.artifact.url)
                .unwrap()
                .to_file_path()
                .unwrap(),
        );
        let source_bytes = fs::read(source).unwrap();
        fs::write(&part, &source_bytes[..source_bytes.len() / 2]).unwrap();
        assert!(!state.exists());
        let resumed = root
            .manager
            .download(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("resume-download".to_string()),
                OperationControl::default(),
                None,
            )
            .unwrap();
        assert!(resumed.resumed);
        assert_eq!(resumed.bytes_downloaded, manifest.artifact.byte_size);

        let second = root.fixture("2.0.0");
        root.intake(&second);
        let control = OperationControl::default();
        control.cancel.store(true, Ordering::Relaxed);
        assert_code(
            root.manager.download(
                "synthetic",
                "2.0.0",
                SourcePolicy::development_test(),
                Some("cancel-download".to_string()),
                control,
                None,
            ),
            "DOWNLOAD_CANCELLED",
        );
        assert!(!root
            .manager
            .machine_root()
            .join("Components/synthetic/2.0.0")
            .exists());
    }

    #[test]
    fn activation_retains_previous_rolls_back_and_uninstall_preserves_user_data() {
        let root = TestRoot::new();
        let user_data = root.root.join("user-projects").join("keep.txt");
        fs::create_dir_all(user_data.parent().unwrap()).unwrap();
        fs::write(&user_data, b"user data").unwrap();
        for version in ["1.0.0", "2.0.0"] {
            let manifest = root.fixture(version);
            root.intake(&manifest);
            root.manager
                .download(
                    "synthetic",
                    version,
                    SourcePolicy::development_test(),
                    Some(format!("download-{version}")),
                    OperationControl::default(),
                    None,
                )
                .unwrap();
            let stage = root
                .manager
                .stage(
                    "synthetic",
                    version,
                    SourcePolicy::development_test(),
                    Some(format!("stage-{version}")),
                    None,
                )
                .unwrap();
            root.manager
                .activate(
                    "synthetic",
                    version,
                    SourcePolicy::development_test(),
                    Some(stage.operation_id),
                    None,
                )
                .unwrap();
        }
        let rollback = root
            .manager
            .rollback("synthetic", SourcePolicy::development_test(), None)
            .unwrap();
        assert_eq!(rollback.component_version, "1.0.0");
        let uninstall = root.manager.uninstall("synthetic").unwrap();
        assert!(uninstall.preserved_user_data);
        assert!(user_data.exists());
        assert!(!root
            .manager
            .machine_root()
            .join("Components/synthetic")
            .exists());
    }

    #[test]
    fn repair_rolls_back_corrupt_active_version_and_lock_contention_is_explicit() {
        let root = TestRoot::new();
        let first = root.fixture("1.0.0");
        root.intake(&first);
        root.manager
            .download(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("download-one".to_string()),
                OperationControl::default(),
                None,
            )
            .unwrap();
        let stage = root
            .manager
            .stage(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some("stage-one".to_string()),
                None,
            )
            .unwrap();
        root.manager
            .activate(
                "synthetic",
                "1.0.0",
                SourcePolicy::development_test(),
                Some(stage.operation_id),
                None,
            )
            .unwrap();
        let second = root.fixture("2.0.0");
        root.intake(&second);
        root.manager
            .download(
                "synthetic",
                "2.0.0",
                SourcePolicy::development_test(),
                Some("download-two".to_string()),
                OperationControl::default(),
                None,
            )
            .unwrap();
        let stage = root
            .manager
            .stage(
                "synthetic",
                "2.0.0",
                SourcePolicy::development_test(),
                Some("stage-two".to_string()),
                None,
            )
            .unwrap();
        root.manager
            .activate(
                "synthetic",
                "2.0.0",
                SourcePolicy::development_test(),
                Some(stage.operation_id),
                None,
            )
            .unwrap();
        let active = root.manager.status(Some("synthetic")).unwrap()[0]
            .active_path
            .clone()
            .unwrap();
        fs::write(
            PathBuf::from(active).join("bin/synthetic-engine.exe"),
            b"tampered",
        )
        .unwrap();
        let repaired = root
            .manager
            .repair("synthetic", SourcePolicy::development_test(), None)
            .unwrap();
        assert_eq!(repaired.state, "rolled-back");
        assert_eq!(
            root.manager.status(Some("synthetic")).unwrap()[0]
                .version
                .as_deref(),
            Some("1.0.0")
        );

        let lock = root.manager.acquire_lock().unwrap();
        assert_code(root.manager.acquire_lock(), "LOCK_CONTENDED");
        drop(lock);
        root.manager.acquire_lock().expect("lock released");
    }

    #[test]
    fn recovery_marks_partial_state_and_removes_abandoned_staging() {
        let root = TestRoot::new();
        let manifest = root.fixture("1.0.0");
        root.intake(&manifest);
        let (part, _, state_path) = root.manager.download_paths("synthetic", "1.0.0").unwrap();
        fs::create_dir_all(part.parent().unwrap()).unwrap();
        fs::write(&part, b"partial").unwrap();
        let state = DownloadState {
            schema_version: DOWNLOAD_STATE_SCHEMA.to_string(),
            operation_id: "interrupted".to_string(),
            component_id: "synthetic".to_string(),
            component_version: "1.0.0".to_string(),
            url: manifest.artifact.url.clone(),
            expected_bytes: manifest.artifact.byte_size,
            bytes_downloaded: 0,
            sha256: manifest.artifact.sha256.clone(),
            temp_path: part.to_string_lossy().to_string(),
            archive_path: root
                .manager
                .download_paths("synthetic", "1.0.0")
                .unwrap()
                .1
                .to_string_lossy()
                .to_string(),
            resumable: true,
            status: "downloading".to_string(),
            recovery: DownloadRecovery {
                status: "none".to_string(),
                resume_from_byte: 0,
                last_verified_byte: 0,
                etag: None,
            },
        };
        atomic_write_json(&state_path, &state).unwrap();
        let orphan = root
            .manager
            .machine_root()
            .join("Components/synthetic/.staging/orphan");
        fs::create_dir_all(&orphan).unwrap();
        fs::write(orphan.join("file"), b"orphan").unwrap();
        let recovery = root.manager.recover().unwrap();
        assert_eq!(recovery.resumable_downloads, 1);
        assert_eq!(recovery.cleaned_staging_directories, 1);
        let recovered = root
            .manager
            .read_download_state(&state_path)
            .unwrap()
            .unwrap();
        assert_eq!(recovered.recovery.status, "resume-available");
        assert!(!orphan.exists());
    }

    #[test]
    fn offline_artifact_references_are_portable_and_bounded() {
        assert_eq!(
            offline_artifact_relative_path("offline:Components/aive-engine-2.0.0-rc.2.tar.gz")
                .unwrap(),
            "Components/aive-engine-2.0.0-rc.2.tar.gz"
        );
        for invalid in [
            "file:///C:/Users/Dv/Desktop/aive-engine.tar.gz",
            "offline:C:/Users/Dv/Desktop/aive-engine.tar.gz",
            "offline:/Components/aive-engine.tar.gz",
            "offline:../Components/aive-engine.tar.gz",
            "offline:Components/../aive-engine.tar.gz",
            "offline:Components/a/../../aive-engine.tar.gz",
            "offline:Components/",
        ] {
            assert!(
                offline_artifact_relative_path(invalid).is_err(),
                "unsafe offline reference was accepted: {invalid}"
            );
        }
    }

    fn copy_tree_for_release_test(source: &Path, destination: &Path) -> io::Result<()> {
        fs::create_dir_all(destination)?;
        for entry in fs::read_dir(source)? {
            let entry = entry?;
            let source_path = entry.path();
            let destination_path = destination.join(entry.file_name());
            if is_reparse_or_symlink(&source_path) {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!(
                        "release test source contains a reparse point: {}",
                        source_path.display()
                    ),
                ));
            }
            if source_path.is_dir() {
                copy_tree_for_release_test(&source_path, &destination_path)?;
            } else {
                fs::copy(&source_path, &destination_path)?;
            }
        }
        Ok(())
    }

    #[test]
    fn phase9_real_release_artifacts_install_verify_and_activate_from_portable_copy() {
        let Some(handoff_value) = env::var_os("AIVE_PHASE9_HANDOFF_ROOT") else {
            return;
        };
        let source_handoff = fs::canonicalize(PathBuf::from(handoff_value)).unwrap();
        assert!(
            source_handoff.is_dir(),
            "Phase 9 handoff root is missing: {}",
            source_handoff.display()
        );
        let portable_handoff = env::temp_dir().join(format!(
            "aive-phase9-portable-handoff-{}-{}",
            std::process::id(),
            now_epoch_ms()
        ));
        let _ = fs::remove_dir_all(&portable_handoff);
        copy_tree_for_release_test(&source_handoff, &portable_handoff).unwrap();
        let portable_handoff = fs::canonicalize(&portable_handoff).unwrap();
        assert_ne!(source_handoff, portable_handoff);

        let catalog_json =
            fs::read_to_string(portable_handoff.join("Catalog/offline-catalog.json")).unwrap();
        let catalog: crate::setup_center::SetupCatalog =
            serde_json::from_str(&catalog_json).unwrap();
        let catalog_signature = BASE64.decode(&catalog.signature.value).unwrap();
        assert_eq!(
            fs::read(portable_handoff.join("Catalog/offline-catalog.sig")).unwrap(),
            catalog_signature
        );
        let catalog_payload = crate::setup_center::catalog_signature_payload(&catalog).unwrap();
        verify_trusted_detached_payload(
            &catalog.signature.algorithm,
            &catalog.signature.key_id,
            &catalog.signature.value,
            &catalog_payload,
        )
        .unwrap();
        let root = env::temp_dir().join(format!(
            "aive-phase9-real-components-{}-{}",
            std::process::id(),
            now_epoch_ms()
        ));
        let _ = fs::remove_dir_all(&root);
        let manager =
            ComponentManager::with_offline_root(root.join("machine"), portable_handoff.clone());
        let policy = SourcePolicy::OFFLINE_IMPORT;
        let components = [
            (
                "aive-engine",
                "2.0.0-rc.2",
                "Components/aive-engine-manifest.json",
                ComponentType::Backend,
            ),
            (
                "ffmpeg",
                "8.1.1",
                "Components/ffmpeg-manifest.json",
                ComponentType::Ffmpeg,
            ),
        ];
        for (component_id, version, manifest_path, expected_type) in components {
            let entry = catalog
                .entries
                .iter()
                .find(|entry| entry.component_id == component_id)
                .unwrap();
            let manifest = entry.manifest.as_ref().unwrap();
            assert_eq!(manifest.component.version, version);
            assert!(manifest.artifact.url.starts_with("offline:Components/"));
            assert!(!manifest.artifact.url.contains("C:\\Users\\"));
            let manifest_json = serde_json::to_string(manifest).unwrap();
            assert!(portable_handoff.join(manifest_path).is_file());
            manager
                .intake_manifest(&manifest_json, policy)
                .unwrap_or_else(|error| {
                    panic!("real Phase 9 {component_id} intake failed: {error}")
                });
            manager
                .resolve_plan(component_id, Some(version), policy)
                .unwrap();
            let downloaded = manager
                .download(
                    component_id,
                    version,
                    policy,
                    Some(format!("phase9-download-{component_id}")),
                    OperationControl::default(),
                    None,
                )
                .unwrap();
            assert_eq!(downloaded.state, "downloaded");
            let verified = manager.verify(component_id, version, policy).unwrap();
            assert_eq!(verified.state, "verified");
            let staged = manager
                .stage(
                    component_id,
                    version,
                    policy,
                    Some(format!("phase9-stage-{component_id}")),
                    None,
                )
                .unwrap();
            assert_eq!(staged.state, "staged");
            let activated = manager
                .activate(
                    component_id,
                    version,
                    policy,
                    Some(staged.operation_id),
                    None,
                )
                .unwrap();
            assert_eq!(activated.state, "active");
            let active = manager
                .verified_active_component(component_id, expected_type, policy)
                .unwrap();
            assert_eq!(active.component_version, version);
            assert!(Path::new(&active.executable_path).is_file());
            assert_eq!(
                manager.status(Some(component_id)).unwrap()[0].state,
                "active"
            );
        }

        let engine = manager
            .verified_active_component("aive-engine", ComponentType::Backend, policy)
            .unwrap();
        let ffmpeg = manager
            .verified_active_component("ffmpeg", ComponentType::Ffmpeg, policy)
            .unwrap();
        let engine_self_test = Command::new(&engine.executable_path)
            .arg("--self-test")
            .current_dir(&engine.active_path)
            .output()
            .unwrap();
        assert!(
            engine_self_test.status.success(),
            "portable frozen engine self-test failed: {:?}",
            engine_self_test
        );
        let ffmpeg_version = Command::new(&ffmpeg.executable_path)
            .arg("-version")
            .output()
            .unwrap();
        assert!(
            ffmpeg_version.status.success(),
            "portable FFmpeg version probe failed"
        );

        let source = portable_handoff.join("SMOKE/synthetic-source.mp4");
        let export = root.join("portable-ffmpeg-export.mp4");
        let encode = Command::new(&ffmpeg.executable_path)
            .args(["-y", "-i"])
            .arg(&source)
            .args(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
            .arg(&export)
            .output()
            .unwrap();
        assert!(
            encode.status.success(),
            "portable FFmpeg encode failed: {:?}",
            encode
        );
        assert!(export.is_file());

        let engine_data = root.join("engine-data");
        fs::create_dir_all(&engine_data).unwrap();
        let token = "phase9-portable-lifecycle-token-20260821-abcdefghijklmnopqrstuvwxyz";
        let port = 38_000 + (now_epoch_ms() % 1_000) as u16;
        let mut engine_command = Command::new(&engine.executable_path);
        engine_command
            .args([
                "--data-root",
                engine_data.to_string_lossy().as_ref(),
                "--port",
                &port.to_string(),
                "--bearer-token",
                token,
                "--component-root",
                &engine.active_path,
                "--ffmpeg-component-root",
                &ffmpeg.active_path,
            ])
            .current_dir(&engine.active_path)
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(windows)]
        for key in [
            "SystemRoot",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "COMSPEC",
            "PATHEXT",
        ] {
            if let Some(value) = env::var_os(key) {
                engine_command.env(key, value);
            }
        }
        let mut child = engine_command.spawn().unwrap();
        let client = Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        let base = format!("http://127.0.0.1:{port}");
        let mut live = false;
        for _ in 0..60 {
            if client.get(format!("{base}/live")).send().is_ok() {
                live = true;
                break;
            }
            thread::sleep(Duration::from_millis(500));
        }
        assert!(live, "portable engine did not become live");
        let unauthorized = client.get(format!("{base}/readiness")).send().unwrap();
        assert_eq!(unauthorized.status(), reqwest::StatusCode::UNAUTHORIZED);
        let readiness = client
            .get(format!("{base}/readiness"))
            .bearer_auth(token)
            .send()
            .unwrap();
        assert!(readiness.status().is_success());
        let readiness_text = readiness.text().unwrap();
        assert!(readiness_text.contains("desktop.health-readiness.v1"));
        assert!(readiness_text.contains("2.0.0-rc.2"));
        let shutdown = client
            .post(format!("{base}/engine-control/shutdown"))
            .bearer_auth(token)
            .send()
            .unwrap();
        assert!(shutdown.status().is_success());
        for _ in 0..30 {
            if child.try_wait().unwrap().is_some() {
                break;
            }
            thread::sleep(Duration::from_millis(500));
        }
        if child.try_wait().unwrap().is_none() {
            let _ = child.kill();
        }
        assert!(child.wait().unwrap().success());
        let _ = fs::remove_dir_all(&root);
        let _ = fs::remove_dir_all(&portable_handoff);
    }
}
