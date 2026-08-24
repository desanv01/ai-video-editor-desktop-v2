//! Desktop V2 Phase 1 wire contracts.
//!
//! These types are intentionally independent of the shell supervisor and
//! updater. They make the later runtime implementation consume the same
//! versioned JSON shapes as the TypeScript client and the checked-in schemas.

use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::collections::HashSet;
use std::fmt::{Display, Formatter};

pub const COMPONENT_MANIFEST_VERSION: &str = "desktop.component-manifest.v1";
pub const ENGINE_CONTROL_VERSION: &str = "desktop.engine-control.v1";
pub const HEALTH_READINESS_VERSION: &str = "desktop.health-readiness.v1";
pub const CAPABILITIES_VERSION: &str = "desktop.capabilities.v1";
pub const STORAGE_LAYOUT_VERSION: &str = "desktop.storage-layout.v1";
pub const UPDATE_STATE_VERSION: &str = "desktop.update-state.v1";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidationError {
    pub contract: String,
    pub issues: Vec<String>,
}

impl ValidationError {
    fn new(contract: &str, issues: Vec<String>) -> Self {
        Self {
            contract: contract.to_string(),
            issues,
        }
    }
}

impl Display for ValidationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "{} validation failed: {}",
            self.contract,
            self.issues.join("; ")
        )
    }
}

impl std::error::Error for ValidationError {}

#[derive(Debug)]
pub enum ContractError {
    Deserialize(serde_json::Error),
    Validation(ValidationError),
}

impl Display for ContractError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Deserialize(error) => write!(
                formatter,
                "contract JSON could not be deserialized: {error}"
            ),
            Self::Validation(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for ContractError {}

fn parse<T>(
    payload: &str,
    validate: impl FnOnce(&T) -> Result<(), ValidationError>,
) -> Result<T, ContractError>
where
    T: DeserializeOwned,
{
    let value = serde_json::from_str(payload).map_err(ContractError::Deserialize)?;
    validate(&value).map_err(ContractError::Validation)?;
    Ok(value)
}

fn require_non_empty(value: &str, path: &str, issues: &mut Vec<String>) {
    if value.is_empty() {
        issues.push(format!("{path} must not be empty"));
    }
}

fn check_semver(value: &str, path: &str, issues: &mut Vec<String>) {
    let mut parts = value.splitn(2, '-');
    let core = parts.next().unwrap_or_default();
    let core = core.splitn(2, '+').next().unwrap_or_default();
    let numbers: Vec<&str> = core.split('.').collect();
    let valid = numbers.len() == 3
        && numbers.iter().all(|part| {
            !part.is_empty() && part.chars().all(|character| character.is_ascii_digit())
        })
        && numbers
            .iter()
            .all(|part| *part == "0" || !part.starts_with('0'));
    if !valid {
        issues.push(format!("{path} must be a semantic version"));
    }
}

fn check_version_constraint(value: &str, path: &str, issues: &mut Vec<String>) {
    if value == "*" {
        return;
    }
    for part in value.split_whitespace() {
        let version = part.trim_start_matches(['<', '>', '=', '~', '^']);
        if version.is_empty() {
            issues.push(format!("{path} contains an empty version constraint"));
            continue;
        }
        check_semver(version, path, issues);
    }
}

fn check_identifier(value: &str, path: &str, issues: &mut Vec<String>) {
    require_non_empty(value, path, issues);
    let valid = value.len() <= 64
        && value
            .chars()
            .next()
            .is_some_and(|character| character.is_ascii_lowercase() || character.is_ascii_digit())
        && value.chars().all(|character| {
            character.is_ascii_lowercase()
                || character.is_ascii_digit()
                || matches!(character, '.' | '_' | '-')
        });
    if !valid {
        issues.push(format!("{path} must be a lowercase component identifier"));
    }
}

fn check_sha256(value: &str, path: &str, issues: &mut Vec<String>) {
    if value.len() != 64
        || !value
            .chars()
            .all(|character| character.is_ascii_hexdigit() && !character.is_ascii_uppercase())
    {
        issues.push(format!(
            "{path} must be 64 lowercase hexadecimal characters"
        ));
    }
}

fn check_https_url(value: &str, path: &str, issues: &mut Vec<String>) {
    if !value.starts_with("https://") || value.len() <= "https://".len() {
        issues.push(format!("{path} must be a non-empty https URL"));
    }
}

fn check_safe_relative_path(value: &str, path: &str, issues: &mut Vec<String>) {
    require_non_empty(value, path, issues);
    let has_parent = value.split(['/', '\\']).any(|part| part == "..");
    if value.starts_with(['/', '\\'])
        || value
            .as_bytes()
            .get(1)
            .is_some_and(|character| *character == b':')
        || has_parent
        || value.contains("//")
        || value.contains("\\\\")
        || value.chars().any(|character| {
            matches!(
                character,
                '<' | '>' | ':' | '"' | '|' | '?' | '*' | '\0'..='\u{1f}'
            )
        })
    {
        issues.push(format!("{path} must be a safe relative path"));
    }
}

fn check_unique<T: Serialize>(values: &[T], path: &str, issues: &mut Vec<String>) {
    let mut seen = HashSet::new();
    for value in values {
        match serde_json::to_string(value) {
            Ok(serialized) => {
                if !seen.insert(serialized) {
                    issues.push(format!("{path} must not contain duplicate items"));
                }
            }
            Err(error) => issues.push(format!(
                "{path} could not be checked for duplicates: {error}"
            )),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ComponentType {
    Backend,
    Database,
    VectorStore,
    Ffmpeg,
    Model,
    Renderer,
    Utility,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ReleaseChannel {
    Stable,
    Beta,
    Nightly,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum OperatingSystem {
    Windows,
    Macos,
    Linux,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum Architecture {
    #[serde(rename = "x86")]
    X86,
    #[serde(rename = "x86_64")]
    X86_64,
    #[serde(rename = "aarch64")]
    Aarch64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum CapabilityId {
    Api,
    Database,
    VectorStore,
    Ffmpeg,
    AiModel,
    Transcription,
    Rendering,
    Gpu,
    NativeImport,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
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
    pub capabilities: Vec<CapabilityId>,
    pub metadata: ComponentMetadata,
    pub files: Vec<FileInventoryEntry>,
    pub self_test: SelfTest,
    pub health: HealthContract,
    pub rollback: RollbackMetadata,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ComponentIdentity {
    pub id: String,
    #[serde(rename = "type")]
    pub component_type: ComponentType,
    pub version: String,
    pub channel: ReleaseChannel,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Target {
    pub operating_systems: Vec<OperatingSystem>,
    pub architectures: Vec<Architecture>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Requirements {
    pub minimum_shell_version: String,
    #[serde(default)]
    pub requires_elevation: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Artifact {
    pub url: String,
    pub byte_size: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DetachedSignature {
    pub algorithm: String,
    pub value: String,
    pub key_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Archive {
    pub format: ArchiveFormat,
    pub root_directory: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum ArchiveFormat {
    #[serde(rename = "zip")]
    Zip,
    #[serde(rename = "tar.gz")]
    TarGz,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct InstallLayout {
    pub root_kind: String,
    pub relative_path: String,
    pub immutable: bool,
    pub activation: ActivationLayout,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ActivationLayout {
    pub strategy: String,
    pub active_path: String,
    pub staging_path: String,
    pub metadata_path: String,
    pub atomic_commit: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Entrypoint {
    pub kind: EntrypointKind,
    pub relative_path: String,
    pub arguments: Vec<String>,
    #[serde(default)]
    pub working_directory: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum EntrypointKind {
    #[serde(rename = "executable")]
    Executable,
    #[serde(rename = "script")]
    Script,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Dependency {
    pub id: String,
    pub version_constraint: String,
    pub optional: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ComponentMetadata {
    pub display_name: String,
    pub publisher: String,
    pub license: LicenseMetadata,
    pub source: SourceMetadata,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LicenseMetadata {
    pub spdx_id: String,
    pub notice_file: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct SourceMetadata {
    pub repository_url: String,
    pub release_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct FileInventoryEntry {
    pub path: String,
    pub kind: FileInventoryKind,
    pub byte_size: u64,
    pub sha256: String,
    pub executable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum FileInventoryKind {
    #[serde(rename = "file")]
    File,
    #[serde(rename = "directory")]
    Directory,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct SelfTest {
    pub command: Vec<String>,
    pub timeout_ms: u64,
    pub expected_exit_code: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct HealthContract {
    pub probe: String,
    pub path: String,
    pub method: String,
    pub timeout_ms: u64,
    pub readiness_schema_version: String,
    pub requires_bearer_token: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RollbackMetadata {
    pub strategy: String,
    pub retention_count: u8,
    pub metadata_path: String,
    pub on_activation_failure: ActivationFailurePolicy,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum ActivationFailurePolicy {
    #[serde(rename = "rollback-automatically")]
    RollbackAutomatically,
    #[serde(rename = "mark-failed")]
    MarkFailed,
}

impl ComponentManifest {
    pub fn validate(&self) -> Result<(), ValidationError> {
        let mut issues = Vec::new();
        if self.schema_version != COMPONENT_MANIFEST_VERSION {
            issues.push("schema_version is not desktop.component-manifest.v1".to_string());
        }
        check_identifier(&self.component.id, "component.id", &mut issues);
        check_semver(&self.component.version, "component.version", &mut issues);
        check_semver(
            &self.requirements.minimum_shell_version,
            "requirements.minimum_shell_version",
            &mut issues,
        );
        if self.target.operating_systems.is_empty() {
            issues.push("target.operating_systems must not be empty".to_string());
        }
        if self.target.architectures.is_empty() {
            issues.push("target.architectures must not be empty".to_string());
        }
        check_unique(
            &self.target.operating_systems,
            "target.operating_systems",
            &mut issues,
        );
        check_unique(
            &self.target.architectures,
            "target.architectures",
            &mut issues,
        );
        check_https_url(&self.artifact.url, "artifact.url", &mut issues);
        if self.artifact.byte_size == 0 {
            issues.push("artifact.byte_size must be greater than zero".to_string());
        }
        check_sha256(&self.artifact.sha256, "artifact.sha256", &mut issues);
        if self.signature.algorithm != "ed25519" {
            issues.push("signature.algorithm must be ed25519".to_string());
        }
        require_non_empty(&self.signature.value, "signature.value", &mut issues);
        require_non_empty(&self.signature.key_id, "signature.key_id", &mut issues);
        if self.install.root_kind != "program-data-components" {
            issues.push("install.root_kind must be program-data-components".to_string());
        }
        if !self.install.immutable {
            issues.push("install.immutable must be true".to_string());
        }
        check_safe_relative_path(
            &self.install.relative_path,
            "install.relative_path",
            &mut issues,
        );
        if self.install.activation.strategy != "stage-then-atomic-rename"
            || !self.install.activation.atomic_commit
        {
            issues.push("install.activation must use atomic stage-then-atomic-rename".to_string());
        }
        check_safe_relative_path(
            &self.install.activation.active_path,
            "install.activation.active_path",
            &mut issues,
        );
        check_safe_relative_path(
            &self.install.activation.staging_path,
            "install.activation.staging_path",
            &mut issues,
        );
        check_safe_relative_path(
            &self.install.activation.metadata_path,
            "install.activation.metadata_path",
            &mut issues,
        );
        check_safe_relative_path(
            &self.entrypoint.relative_path,
            "entrypoint.relative_path",
            &mut issues,
        );
        if self
            .dependencies
            .iter()
            .any(|dependency| dependency.id == self.component.id)
        {
            issues.push("component cannot depend on itself".to_string());
        }
        for dependency in &self.dependencies {
            check_identifier(&dependency.id, "dependency.id", &mut issues);
            check_version_constraint(
                &dependency.version_constraint,
                "dependency.version_constraint",
                &mut issues,
            );
        }
        if self.capabilities.is_empty() {
            issues.push("capabilities must not be empty".to_string());
        }
        check_unique(&self.capabilities, "capabilities", &mut issues);
        if self.files.is_empty() {
            issues.push("files must not be empty".to_string());
        }
        for file in &self.files {
            check_safe_relative_path(&file.path, "files.path", &mut issues);
            check_sha256(&file.sha256, "files.sha256", &mut issues);
        }
        if self.self_test.command.is_empty() || self.self_test.command.iter().any(String::is_empty)
        {
            issues.push("self_test.command must not be empty".to_string());
        }
        if !(1_000..=600_000).contains(&self.self_test.timeout_ms) {
            issues.push("self_test.timeout_ms is outside 1000..600000".to_string());
        }
        if self.self_test.expected_exit_code != 0 {
            issues.push("self_test.expected_exit_code must be zero".to_string());
        }
        if self.health.probe != "http"
            || self.health.method != "GET"
            || !self.health.path.starts_with('/')
            || self.health.readiness_schema_version != HEALTH_READINESS_VERSION
            || !self.health.requires_bearer_token
        {
            issues.push(
                "health must be an authenticated GET probe for desktop.health-readiness.v1"
                    .to_string(),
            );
        }
        if self.rollback.strategy != "retain-previous-active"
            || !(1..=5).contains(&self.rollback.retention_count)
        {
            issues.push("rollback metadata is invalid".to_string());
        }
        check_safe_relative_path(
            &self.rollback.metadata_path,
            "rollback.metadata_path",
            &mut issues,
        );
        if issues.is_empty() {
            Ok(())
        } else {
            Err(ValidationError::new(COMPONENT_MANIFEST_VERSION, issues))
        }
    }
}

pub fn parse_component_manifest(payload: &str) -> Result<ComponentManifest, ContractError> {
    parse(payload, ComponentManifest::validate)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum StoragePlatform {
    #[serde(rename = "windows")]
    Windows,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum StorageScope {
    Machine,
    User,
    UserSelected,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum StorageOwner {
    MachineInstaller,
    MachineUpdateService,
    User,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum StorageWriter {
    Installer,
    UpdateService,
    UserRuntime,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct StoragePathDescriptor {
    pub path_template: String,
    pub scope: StorageScope,
    pub owner: StorageOwner,
    pub writer: StorageWriter,
    pub runtime_writable: bool,
    pub purpose: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct StoragePaths {
    pub shell_install: StoragePathDescriptor,
    pub shared_components: StoragePathDescriptor,
    pub activation_metadata: StoragePathDescriptor,
    pub download_staging: StoragePathDescriptor,
    pub user_config: StoragePathDescriptor,
    pub user_cache: StoragePathDescriptor,
    pub user_logs: StoragePathDescriptor,
    pub user_state: StoragePathDescriptor,
    pub projects: StoragePathDescriptor,
    pub exports: StoragePathDescriptor,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct StorageLayout {
    pub schema_version: String,
    pub platform: StoragePlatform,
    pub program_files_runtime_writable: bool,
    pub paths: StoragePaths,
}

fn storage_descriptor(
    path_template: &str,
    scope: StorageScope,
    owner: StorageOwner,
    writer: StorageWriter,
    runtime_writable: bool,
    purpose: &str,
) -> StoragePathDescriptor {
    StoragePathDescriptor {
        path_template: path_template.to_string(),
        scope,
        owner,
        writer,
        runtime_writable,
        purpose: purpose.to_string(),
    }
}

pub fn canonical_windows_storage_layout() -> StorageLayout {
    StorageLayout {
        schema_version: STORAGE_LAYOUT_VERSION.to_string(),
        platform: StoragePlatform::Windows,
        program_files_runtime_writable: false,
        paths: StoragePaths {
            shell_install: storage_descriptor("%ProgramFiles%\\AI Video Editor Desktop V2\\Shell", StorageScope::Machine, StorageOwner::MachineInstaller, StorageWriter::Installer, false, "Versioned thin shell binaries and static resources."),
            shared_components: storage_descriptor("%ProgramData%\\AI Video Editor\\Components", StorageScope::Machine, StorageOwner::MachineUpdateService, StorageWriter::UpdateService, false, "Verified immutable component versions selected by activation metadata."),
            activation_metadata: storage_descriptor("%ProgramData%\\AI Video Editor\\Activation", StorageScope::Machine, StorageOwner::MachineUpdateService, StorageWriter::UpdateService, false, "Atomic active-version pointers, update journals and rollback records."),
            download_staging: storage_descriptor("%ProgramData%\\AI Video Editor\\Downloads\\Staging", StorageScope::Machine, StorageOwner::MachineUpdateService, StorageWriter::UpdateService, false, "Resumable temporary downloads before digest, signature and inventory verification."),
            user_config: storage_descriptor("%LocalAppData%\\AI Video Editor\\Config", StorageScope::User, StorageOwner::User, StorageWriter::UserRuntime, true, "Per-user settings and non-secret preferences."),
            user_cache: storage_descriptor("%LocalAppData%\\AI Video Editor\\Cache", StorageScope::User, StorageOwner::User, StorageWriter::UserRuntime, true, "Rebuildable per-user caches and indexes."),
            user_logs: storage_descriptor("%LocalAppData%\\AI Video Editor\\Logs", StorageScope::User, StorageOwner::User, StorageWriter::UserRuntime, true, "Redacted per-user shell and engine logs."),
            user_state: storage_descriptor("%LocalAppData%\\AI Video Editor\\State", StorageScope::User, StorageOwner::User, StorageWriter::UserRuntime, true, "Per-user resumable operation state and local metadata."),
            projects: storage_descriptor("%USERPROFILE%\\Documents\\AI Video Editor\\Projects", StorageScope::UserSelected, StorageOwner::User, StorageWriter::UserRuntime, true, "User projects under Documents by default or an explicitly selected folder."),
            exports: storage_descriptor("%USERPROFILE%\\Documents\\AI Video Editor\\Exports", StorageScope::UserSelected, StorageOwner::User, StorageWriter::UserRuntime, true, "User-selected export destination, Documents by default."),
        },
    }
}

impl StorageLayout {
    pub fn validate(&self) -> Result<(), ValidationError> {
        let mut issues = Vec::new();
        if self.schema_version != STORAGE_LAYOUT_VERSION {
            issues.push("schema_version is not desktop.storage-layout.v1".to_string());
        }
        if self.platform != StoragePlatform::Windows {
            issues.push("platform must be windows".to_string());
        }
        if self.program_files_runtime_writable {
            issues.push("Program Files must never be runtime-writable".to_string());
        }
        let canonical = canonical_windows_storage_layout();
        let descriptors = [
            (
                "shell_install",
                &self.paths.shell_install,
                &canonical.paths.shell_install,
            ),
            (
                "shared_components",
                &self.paths.shared_components,
                &canonical.paths.shared_components,
            ),
            (
                "activation_metadata",
                &self.paths.activation_metadata,
                &canonical.paths.activation_metadata,
            ),
            (
                "download_staging",
                &self.paths.download_staging,
                &canonical.paths.download_staging,
            ),
            (
                "user_config",
                &self.paths.user_config,
                &canonical.paths.user_config,
            ),
            (
                "user_cache",
                &self.paths.user_cache,
                &canonical.paths.user_cache,
            ),
            (
                "user_logs",
                &self.paths.user_logs,
                &canonical.paths.user_logs,
            ),
            (
                "user_state",
                &self.paths.user_state,
                &canonical.paths.user_state,
            ),
            ("projects", &self.paths.projects, &canonical.paths.projects),
            ("exports", &self.paths.exports, &canonical.paths.exports),
        ];
        for (name, actual, expected) in descriptors {
            if actual.path_template != expected.path_template {
                issues.push(format!("paths.{name}.path_template is not canonical"));
            }
            if actual.scope != expected.scope
                || actual.owner != expected.owner
                || actual.writer != expected.writer
                || actual.runtime_writable != expected.runtime_writable
            {
                issues.push(format!("paths.{name} ownership or write policy is invalid"));
            }
            require_non_empty(
                &actual.purpose,
                &format!("paths.{name}.purpose"),
                &mut issues,
            );
        }
        if issues.is_empty() {
            Ok(())
        } else {
            Err(ValidationError::new(STORAGE_LAYOUT_VERSION, issues))
        }
    }
}

pub fn parse_storage_layout(payload: &str) -> Result<StorageLayout, ContractError> {
    parse(payload, StorageLayout::validate)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum EngineMessageType {
    Start,
    Ready,
    Shutdown,
    ShutdownAck,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct SessionIdentity {
    pub session_id: String,
    pub bearer_token: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EngineIdentity {
    pub id: String,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProcessIdentity {
    pub component_id: String,
    pub component_version: String,
    #[serde(default)]
    pub pid: Option<u32>,
    pub executable_path: String,
    pub entrypoint: String,
    pub arguments: Vec<String>,
    #[serde(default)]
    pub started_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LoopbackAllocation {
    pub host: String,
    pub allocation: String,
    pub requested_port: u16,
    #[serde(default)]
    pub assigned_port: Option<u16>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct EngineStoragePaths {
    pub layout_version: String,
    pub shell_install_root: String,
    pub shared_components_root: String,
    pub activation_metadata_root: String,
    pub download_staging_root: String,
    pub user_config_root: String,
    pub user_cache_root: String,
    pub user_logs_root: String,
    pub user_state_root: String,
    pub projects_root: String,
    pub exports_root: String,
    pub program_files_runtime_writable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct InstalledComponent {
    pub id: String,
    pub version: String,
    pub path: String,
    pub active: bool,
    pub capabilities: Vec<CapabilityId>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ShutdownPolicy {
    pub mode: String,
    pub grace_period_ms: u64,
    pub escalation: ShutdownEscalation,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum ShutdownEscalation {
    #[serde(rename = "terminate")]
    Terminate,
    #[serde(rename = "leave-running")]
    LeaveRunning,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ShutdownState {
    pub reason: String,
    pub requested_at: String,
    pub status: ShutdownStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ShutdownStatus {
    Requested,
    Completed,
    TimedOut,
    Rejected,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ReadinessReference {
    pub schema_version: String,
    pub endpoint: String,
    pub overall_state: HealthOverallState,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct EngineControlMessage {
    pub schema_version: String,
    pub message_type: EngineMessageType,
    pub session: SessionIdentity,
    pub engine: EngineIdentity,
    pub process: ProcessIdentity,
    pub loopback: LoopbackAllocation,
    pub storage_paths: EngineStoragePaths,
    pub installed_components: Vec<InstalledComponent>,
    pub requested_capabilities: Vec<CapabilityId>,
    pub log_path: String,
    pub startup_deadline_ms: u64,
    pub shutdown_policy: ShutdownPolicy,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shutdown: Option<ShutdownState>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub readiness: Option<ReadinessReference>,
}

impl EngineStoragePaths {
    fn validate(&self, issues: &mut Vec<String>) {
        if self.layout_version != STORAGE_LAYOUT_VERSION {
            issues.push("storage_paths.layout_version is invalid".to_string());
        }
        if self.program_files_runtime_writable {
            issues.push("storage_paths.program_files_runtime_writable must be false".to_string());
        }
        for (path, name) in [
            (&self.shell_install_root, "shell_install_root"),
            (&self.shared_components_root, "shared_components_root"),
            (&self.activation_metadata_root, "activation_metadata_root"),
            (&self.download_staging_root, "download_staging_root"),
            (&self.user_config_root, "user_config_root"),
            (&self.user_cache_root, "user_cache_root"),
            (&self.user_logs_root, "user_logs_root"),
            (&self.user_state_root, "user_state_root"),
            (&self.projects_root, "projects_root"),
            (&self.exports_root, "exports_root"),
        ] {
            require_non_empty(path, &format!("storage_paths.{name}"), issues);
        }
        for (path, name) in [
            (&self.shared_components_root, "shared_components_root"),
            (&self.activation_metadata_root, "activation_metadata_root"),
            (&self.download_staging_root, "download_staging_root"),
            (&self.user_config_root, "user_config_root"),
            (&self.user_cache_root, "user_cache_root"),
            (&self.user_logs_root, "user_logs_root"),
            (&self.user_state_root, "user_state_root"),
            (&self.projects_root, "projects_root"),
            (&self.exports_root, "exports_root"),
        ] {
            if path.to_ascii_lowercase().contains("program files")
                || path.to_ascii_lowercase().starts_with("%programfiles%")
            {
                issues.push(format!(
                    "storage_paths.{name} must not be under Program Files"
                ));
            }
        }
    }
}

impl EngineControlMessage {
    pub fn validate(&self) -> Result<(), ValidationError> {
        let mut issues = Vec::new();
        if self.schema_version != ENGINE_CONTROL_VERSION {
            issues.push("schema_version is invalid".to_string());
        }
        if self.engine.id != "aive-engine" {
            issues.push("engine.id must be aive-engine".to_string());
        }
        check_semver(&self.engine.version, "engine.version", &mut issues);
        if self.session.session_id.len() < 8 || self.session.session_id.len() > 64 {
            issues.push("session.session_id length is invalid".to_string());
        }
        if self.session.bearer_token.len() < 32 {
            issues.push(
                "session.bearer_token is mandatory and must be at least 32 characters".to_string(),
            );
        }
        if self.loopback.host != "127.0.0.1"
            || self.loopback.allocation != "dynamic"
            || self.loopback.requested_port != 0
        {
            issues.push("loopback must request a dynamically allocated 127.0.0.1 port".to_string());
        }
        if matches!(self.message_type, EngineMessageType::Ready)
            && self.loopback.assigned_port.is_none()
        {
            issues.push("ready messages require an assigned loopback port".to_string());
        }
        if matches!(self.message_type, EngineMessageType::Start)
            && self.loopback.assigned_port.is_some()
        {
            issues.push("start messages must not preassign a dynamic loopback port".to_string());
        }
        check_semver(
            &self.process.component_version,
            "process.component_version",
            &mut issues,
        );
        require_non_empty(
            &self.process.component_id,
            "process.component_id",
            &mut issues,
        );
        require_non_empty(
            &self.process.executable_path,
            "process.executable_path",
            &mut issues,
        );
        if self
            .process
            .executable_path
            .to_ascii_lowercase()
            .contains("program files")
        {
            issues.push("engine process must execute from an immutable ProgramData component, not Program Files".to_string());
        }
        if self.installed_components.is_empty() {
            issues.push("installed_components must not be empty".to_string());
        }
        for component in &self.installed_components {
            check_identifier(&component.id, "installed_components.id", &mut issues);
            check_semver(
                &component.version,
                "installed_components.version",
                &mut issues,
            );
            require_non_empty(&component.path, "installed_components.path", &mut issues);
            if component
                .path
                .to_ascii_lowercase()
                .contains("program files")
            {
                issues
                    .push("installed component paths must not be under Program Files".to_string());
            }
        }
        check_unique(
            &self.requested_capabilities,
            "requested_capabilities",
            &mut issues,
        );
        require_non_empty(&self.log_path, "log_path", &mut issues);
        if self.log_path.to_ascii_lowercase().contains("program files") {
            issues.push("log_path must not be under Program Files".to_string());
        }
        if !(1_000..=600_000).contains(&self.startup_deadline_ms) {
            issues.push("startup_deadline_ms is outside 1000..600000".to_string());
        }
        if self.shutdown_policy.mode != "graceful"
            || !(100..=120_000).contains(&self.shutdown_policy.grace_period_ms)
        {
            issues.push("shutdown_policy must define a bounded graceful shutdown".to_string());
        }
        self.storage_paths.validate(&mut issues);
        match self.message_type {
            EngineMessageType::Start => {
                if self.shutdown.is_some() {
                    issues.push("start messages cannot contain shutdown state".to_string());
                }
            }
            EngineMessageType::Ready => {
                if self.process.pid.is_none() {
                    issues.push("ready messages require process.pid".to_string());
                }
                if self.readiness.is_none() {
                    issues.push("ready messages require readiness".to_string());
                }
            }
            EngineMessageType::Shutdown | EngineMessageType::ShutdownAck => {
                if self.shutdown.is_none() {
                    issues.push("shutdown messages require shutdown state".to_string());
                }
            }
        }
        if issues.is_empty() {
            Ok(())
        } else {
            Err(ValidationError::new(ENGINE_CONTROL_VERSION, issues))
        }
    }
}

pub fn parse_engine_control(payload: &str) -> Result<EngineControlMessage, ContractError> {
    parse(payload, EngineControlMessage::validate)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum HealthOverallState {
    Starting,
    Ready,
    Degraded,
    Fatal,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum HealthCheckState {
    Healthy,
    Ready,
    Degraded,
    NotReady,
    NotConfigured,
    Fatal,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RemediationCode {
    EngineNotRunning,
    ApiUnhealthy,
    DatabaseUnavailable,
    VectorStoreUnavailable,
    FfmpegMissing,
    ModelNotInstalled,
    ModelLoadFailed,
    ComponentVersionIncompatible,
    PortAllocationFailed,
    SessionAuthFailed,
    StorageNotWritable,
    MigrationRequired,
    UpdateRollbackAvailable,
    RestartRequired,
    DiskSpaceLow,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProcessHealth {
    pub alive: bool,
    pub pid: u32,
    pub component_id: String,
    pub component_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct HealthCheck {
    pub state: HealthCheckState,
    pub required: bool,
    pub detail: String,
    pub remediation_codes: Vec<RemediationCode>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct HealthChecks {
    pub api: HealthCheck,
    pub database: HealthCheck,
    pub vector_store: HealthCheck,
    pub ffmpeg: HealthCheck,
    #[serde(default)]
    pub ai_model: Option<HealthCheck>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct HealthCapabilities {
    pub available: Vec<CapabilityId>,
    pub degraded: Vec<CapabilityId>,
    pub unavailable: Vec<CapabilityId>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct FatalError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct HealthReadinessPayload {
    pub schema_version: String,
    pub generated_at: String,
    pub overall_state: HealthOverallState,
    pub process: ProcessHealth,
    pub checks: HealthChecks,
    pub capabilities: HealthCapabilities,
    pub remediation_codes: Vec<RemediationCode>,
    #[serde(default)]
    pub fatal_error: Option<FatalError>,
}

impl HealthReadinessPayload {
    pub fn validate(&self) -> Result<(), ValidationError> {
        let mut issues = Vec::new();
        if self.schema_version != HEALTH_READINESS_VERSION {
            issues.push("schema_version is invalid".to_string());
        }
        require_non_empty(&self.generated_at, "generated_at", &mut issues);
        require_non_empty(
            &self.process.component_id,
            "process.component_id",
            &mut issues,
        );
        check_semver(
            &self.process.component_version,
            "process.component_version",
            &mut issues,
        );
        if matches!(self.overall_state, HealthOverallState::Fatal) && self.fatal_error.is_none() {
            issues.push("fatal_error is required for fatal state".to_string());
        }
        if matches!(self.overall_state, HealthOverallState::Ready) && !self.process.alive {
            issues.push("process.alive must be true for ready state".to_string());
        }
        check_unique(
            &self.capabilities.available,
            "capabilities.available",
            &mut issues,
        );
        check_unique(
            &self.capabilities.degraded,
            "capabilities.degraded",
            &mut issues,
        );
        check_unique(
            &self.capabilities.unavailable,
            "capabilities.unavailable",
            &mut issues,
        );
        let mut groups = HashSet::new();
        for capability in self
            .capabilities
            .available
            .iter()
            .chain(&self.capabilities.degraded)
            .chain(&self.capabilities.unavailable)
        {
            if !groups.insert(format!("{capability:?}")) {
                issues.push("capabilities groups must not overlap".to_string());
            }
        }
        check_unique(&self.remediation_codes, "remediation_codes", &mut issues);
        if issues.is_empty() {
            Ok(())
        } else {
            Err(ValidationError::new(HEALTH_READINESS_VERSION, issues))
        }
    }
}

pub fn parse_health_readiness(payload: &str) -> Result<HealthReadinessPayload, ContractError> {
    parse(payload, HealthReadinessPayload::validate)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum CapabilityState {
    Available,
    Degraded,
    Unavailable,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum CapabilitySource {
    Component,
    Backend,
    Model,
    Host,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CapabilityItem {
    pub id: CapabilityId,
    pub state: CapabilityState,
    pub source: CapabilitySource,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub detail: Option<String>,
    #[serde(default)]
    pub remediation_codes: Option<Vec<RemediationCode>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CapabilitiesPayload {
    pub schema_version: String,
    pub component_id: String,
    pub component_version: String,
    pub generated_at: String,
    pub requested: Vec<CapabilityId>,
    pub items: Vec<CapabilityItem>,
}

impl CapabilitiesPayload {
    pub fn validate(&self) -> Result<(), ValidationError> {
        let mut issues = Vec::new();
        if self.schema_version != CAPABILITIES_VERSION {
            issues.push("schema_version is invalid".to_string());
        }
        check_identifier(&self.component_id, "component_id", &mut issues);
        check_semver(&self.component_version, "component_version", &mut issues);
        require_non_empty(&self.generated_at, "generated_at", &mut issues);
        check_unique(&self.requested, "requested", &mut issues);
        check_unique(&self.items, "items", &mut issues);
        let mut ids = HashSet::new();
        for item in &self.items {
            if !ids.insert(format!("{:?}", item.id)) {
                issues.push("items must contain one entry per capability id".to_string());
            }
            if let Some(version) = &item.version {
                check_semver(version, "items.version", &mut issues);
            }
        }
        if issues.is_empty() {
            Ok(())
        } else {
            Err(ValidationError::new(CAPABILITIES_VERSION, issues))
        }
    }
}

pub fn parse_capabilities(payload: &str) -> Result<CapabilitiesPayload, ContractError> {
    parse(payload, CapabilitiesPayload::validate)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum UpdateStateName {
    Idle,
    Checking,
    Downloading,
    Paused,
    Downloaded,
    Verifying,
    Staged,
    Activating,
    Active,
    Interrupted,
    RollingBack,
    RolledBack,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum RecoveryStatus {
    None,
    ResumeAvailable,
    RestartRequired,
    Discarded,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DownloadRecovery {
    pub status: RecoveryStatus,
    pub resume_from_byte: u64,
    pub last_verified_byte: u64,
    #[serde(default)]
    pub etag: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DownloadState {
    pub url: String,
    pub expected_bytes: u64,
    pub bytes_downloaded: u64,
    pub sha256: String,
    pub temp_path: String,
    pub resumable: bool,
    pub recovery: DownloadRecovery,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ActivationCheckpoint {
    None,
    Downloaded,
    Verified,
    Staged,
    Active,
    RolledBack,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UpdateActivation {
    pub strategy: String,
    pub stage_path: String,
    pub active_path: String,
    pub metadata_path: String,
    pub current_version: String,
    pub target_version: String,
    pub checkpoint: ActivationCheckpoint,
    pub atomic_commit: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UpdateRollback {
    pub available: bool,
    #[serde(default)]
    pub previous_version: Option<String>,
    #[serde(default)]
    pub previous_path: Option<String>,
    pub automatic: bool,
    pub attempt_count: u8,
    pub max_attempts: u8,
    #[serde(default)]
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UpdateError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UpdateState {
    pub schema_version: String,
    pub operation_id: String,
    pub component_id: String,
    pub target_version: String,
    pub channel: ReleaseChannel,
    pub state: UpdateStateName,
    pub download: DownloadState,
    pub activation: UpdateActivation,
    pub rollback: UpdateRollback,
    #[serde(default)]
    pub error: Option<UpdateError>,
    pub updated_at: String,
}

impl UpdateState {
    pub fn validate(&self) -> Result<(), ValidationError> {
        let mut issues = Vec::new();
        if self.schema_version != UPDATE_STATE_VERSION {
            issues.push("schema_version is invalid".to_string());
        }
        if self.operation_id.len() < 8 || self.operation_id.len() > 64 {
            issues.push("operation_id length is invalid".to_string());
        }
        check_identifier(&self.component_id, "component_id", &mut issues);
        check_semver(&self.target_version, "target_version", &mut issues);
        check_https_url(&self.download.url, "download.url", &mut issues);
        if self.download.expected_bytes == 0
            || self.download.bytes_downloaded > self.download.expected_bytes
        {
            issues.push("download byte counts are invalid".to_string());
        }
        check_sha256(&self.download.sha256, "download.sha256", &mut issues);
        require_non_empty(&self.download.temp_path, "download.temp_path", &mut issues);
        if self.download.recovery.resume_from_byte > self.download.bytes_downloaded
            || self.download.recovery.last_verified_byte > self.download.bytes_downloaded
        {
            issues.push("download recovery offsets exceed downloaded bytes".to_string());
        }
        if self.activation.strategy != "stage-then-atomic-rename" || !self.activation.atomic_commit
        {
            issues.push(
                "activation must use an atomic stage-then-atomic-rename strategy".to_string(),
            );
        }
        check_semver(
            &self.activation.current_version,
            "activation.current_version",
            &mut issues,
        );
        check_semver(
            &self.activation.target_version,
            "activation.target_version",
            &mut issues,
        );
        if !(1..=5).contains(&self.rollback.max_attempts)
            || self.rollback.attempt_count > self.rollback.max_attempts
        {
            issues.push("rollback attempt limits are invalid".to_string());
        }
        if self.rollback.available
            && (self.rollback.previous_version.is_none() || self.rollback.previous_path.is_none())
        {
            issues
                .push("rollback previous version and path are required when available".to_string());
        }
        if matches!(self.state, UpdateStateName::Interrupted)
            && !matches!(
                self.download.recovery.status,
                RecoveryStatus::ResumeAvailable | RecoveryStatus::RestartRequired
            )
        {
            issues.push("interrupted state requires resumable recovery metadata".to_string());
        }
        if matches!(self.state, UpdateStateName::Active)
            && (!matches!(self.activation.checkpoint, ActivationCheckpoint::Active)
                || !self.activation.atomic_commit)
        {
            issues.push("active state requires atomic active checkpoint".to_string());
        }
        if matches!(self.state, UpdateStateName::Failed) && self.error.is_none() {
            issues.push("failed state requires an error".to_string());
        }
        if issues.is_empty() {
            Ok(())
        } else {
            Err(ValidationError::new(UPDATE_STATE_VERSION, issues))
        }
    }
}

pub fn parse_update_state(payload: &str) -> Result<UpdateState, ContractError> {
    parse(payload, UpdateState::validate)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    use std::fs;
    use std::path::PathBuf;

    fn fixture(name: &str) -> String {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/desktop-v2/contracts")
            .join(name);
        fs::read_to_string(path).expect("contract fixture must be available")
    }

    #[test]
    fn valid_component_manifest_round_trips_and_invalid_manifest_is_rejected() {
        let valid = fixture("valid-component-manifest.json");
        let manifest = parse_component_manifest(&valid).expect("valid component manifest");
        let round_trip: Value =
            serde_json::from_str(&serde_json::to_string(&manifest).expect("serialize manifest"))
                .expect("round-trip JSON");
        let original: Value = serde_json::from_str(&valid).expect("fixture JSON");
        assert_eq!(round_trip, original);
        assert!(parse_component_manifest(&fixture(
            "invalid-component-manifest-missing-signature.json"
        ))
        .is_err());
    }

    #[test]
    fn engine_control_requires_loopback_auth_and_dynamic_port() {
        assert!(parse_engine_control(&fixture("valid-engine-control-start.json")).is_ok());
        assert!(parse_engine_control(&fixture("invalid-engine-control-no-token.json")).is_err());
    }

    #[test]
    fn health_capabilities_storage_and_update_fixtures_validate() {
        assert!(parse_health_readiness(&fixture("valid-health-degraded.json")).is_ok());
        assert!(
            parse_health_readiness(&fixture("invalid-health-fatal-without-error.json")).is_err()
        );
        assert!(parse_capabilities(&fixture("valid-capabilities.json")).is_ok());
        assert!(parse_storage_layout(&fixture("valid-storage-layout.json")).is_ok());
        assert!(
            parse_storage_layout(&fixture("invalid-storage-program-files-writable.json")).is_err()
        );
        assert!(parse_update_state(&fixture("valid-update-interrupted.json")).is_ok());
        assert!(parse_update_state(&fixture("invalid-update-non-atomic.json")).is_err());
    }

    #[test]
    fn canonical_storage_layout_serializes_to_the_expected_fixture() {
        let expected: Value =
            serde_json::from_str(&fixture("valid-storage-layout.json")).expect("fixture JSON");
        let actual = serde_json::to_value(canonical_windows_storage_layout())
            .expect("serialize storage layout");
        assert_eq!(actual, expected);
    }
}
