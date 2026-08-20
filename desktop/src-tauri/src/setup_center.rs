//! Phase 6 Setup Center contracts and local orchestration boundary.
//!
//! This module owns only non-secret onboarding state, signed catalog intake,
//! and system checks. Component bytes, verification, activation, rollback,
//! and self-tests remain in `component_manager`; native process lifecycle and
//! authenticated readiness remain in `supervisor`.

use crate::component_manager::{
    self, ComponentError, ComponentManager, ComponentManifest, ManagerResult, SourcePolicy,
};
use crate::desktop_v2::get_canonical_paths;
use crate::supervisor::{SupervisorPhase, SupervisorState};
use reqwest::blocking::Client;
use reqwest::redirect::Policy;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::State;
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

pub const SETUP_STATE_SCHEMA: &str = "desktop.setup-state.v1";
pub const SETUP_CATALOG_SCHEMA: &str = "desktop.setup-catalog.v1";
pub const SETUP_CATALOG_FILE: &str = "setup-catalog.json";
pub const SETUP_STATE_FILE: &str = "setup-state.json";
pub const PRODUCTION_CATALOG_ENV: &str = "AIVE_SETUP_CATALOG_URL";
const MAX_CATALOG_BYTES: usize = 8 * 1024 * 1024;
const MAX_CATALOG_ENTRIES: usize = 64;
const MIN_SYSTEM_FREE_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CatalogSignature {
    pub algorithm: String,
    pub key_id: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SetupCatalogEntry {
    pub component_id: String,
    pub display_name: String,
    pub required: bool,
    pub availability: String,
    pub description: String,
    pub artifact_bytes: u64,
    pub license_version: String,
    pub license_name: String,
    pub source_url: Option<String>,
    pub unavailable_reason: Option<String>,
    /// The Phase 1/3 signed manifest. It is authenticated again by the
    /// component manager before being written to the machine catalog.
    pub manifest: Option<ComponentManifest>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SetupCatalog {
    pub schema_version: String,
    pub catalog_id: String,
    pub channel: String,
    pub generated_at: String,
    pub expires_at: String,
    pub entries: Vec<SetupCatalogEntry>,
    pub signature: CatalogSignature,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SetupCatalogInfo {
    pub catalog: SetupCatalog,
    pub source: String,
    pub verified_at_epoch_ms: u128,
    pub path: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SetupImportResult {
    pub catalog: SetupCatalogInfo,
    pub imported_manifest_ids: Vec<String>,
    pub catalog_only_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct SetupState {
    pub schema_version: String,
    pub selected_optional_packs: Vec<String>,
    pub accepted_license_versions: BTreeMap<String, String>,
    pub catalog_channel: String,
    pub last_successful_setup: Option<String>,
    pub incomplete_operation_ids: BTreeMap<String, String>,
    pub onboarding_completed: bool,
    pub updated_at_epoch_ms: u128,
}

impl Default for SetupState {
    fn default() -> Self {
        Self {
            schema_version: SETUP_STATE_SCHEMA.to_string(),
            selected_optional_packs: Vec::new(),
            accepted_license_versions: BTreeMap::new(),
            catalog_channel: "stable".to_string(),
            last_successful_setup: None,
            incomplete_operation_ids: BTreeMap::new(),
            onboarding_completed: false,
            updated_at_epoch_ms: now_epoch_ms(),
        }
    }
}

impl SetupState {
    fn validate(&self) -> ManagerResult<()> {
        if self.schema_version != SETUP_STATE_SCHEMA {
            return Err(setup_error(
                "SETUP_STATE_INVALID",
                "Saved setup preferences are from an unsupported version. They can be rebuilt safely.",
                false,
            ));
        }
        if !matches!(self.catalog_channel.as_str(), "stable" | "beta" | "nightly") {
            return Err(setup_error(
                "SETUP_STATE_INVALID",
                "The saved update channel is not supported.",
                false,
            ));
        }
        if self.selected_optional_packs.len() > MAX_CATALOG_ENTRIES
            || self.incomplete_operation_ids.len() > MAX_CATALOG_ENTRIES
        {
            return Err(setup_error(
                "SETUP_STATE_INVALID",
                "Saved setup selections exceed the safe limit.",
                false,
            ));
        }
        for value in self
            .selected_optional_packs
            .iter()
            .chain(self.incomplete_operation_ids.keys())
        {
            if !safe_identifier(value) {
                return Err(setup_error(
                    "SETUP_STATE_INVALID",
                    "Saved setup state contains an unsafe component identifier.",
                    false,
                ));
            }
        }
        for (component_id, license_version) in &self.accepted_license_versions {
            if !safe_identifier(component_id) || !safe_state_value(license_version) {
                return Err(setup_error(
                    "SETUP_STATE_INVALID",
                    "Saved license state contains an unsafe value.",
                    false,
                ));
            }
        }
        for operation_id in self.incomplete_operation_ids.values() {
            if !safe_state_value(operation_id) {
                return Err(setup_error(
                    "SETUP_STATE_INVALID",
                    "Saved operation recovery state contains an unsafe value.",
                    false,
                ));
            }
        }
        if self
            .last_successful_setup
            .as_deref()
            .map(|value| !safe_state_value(value))
            .unwrap_or(false)
        {
            return Err(setup_error(
                "SETUP_STATE_INVALID",
                "Saved setup completion state contains an unsafe value.",
                false,
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SetupSystemCheck {
    pub id: String,
    pub label: String,
    pub severity: String,
    pub explanation: String,
    pub remediation: String,
    pub technical_detail: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SetupSystemChecksResult {
    pub schema_version: String,
    pub generated_at_epoch_ms: u128,
    pub supported: bool,
    pub process_elevated: bool,
    pub architecture: String,
    pub free_space_bytes: Option<u64>,
    pub component_root: String,
    pub user_state_root: String,
    pub checks: Vec<SetupSystemCheck>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SetupCatalogConfiguration {
    pub channel: String,
    pub production_url_configured: bool,
    pub production_url: Option<String>,
    pub offline_import_supported: bool,
    pub trust_policy: String,
}

fn setup_error(code: &str, message: &str, retryable: bool) -> ComponentError {
    ComponentError::new(code, message, retryable)
}

fn now_epoch_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

fn safe_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 96
        && value.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
        })
}

fn safe_state_value(value: &str) -> bool {
    let lower = value.to_ascii_lowercase();
    value.len() <= 256
        && !lower.contains("token")
        && !lower.contains("secret")
        && !lower.contains("api_key")
        && !lower.contains("authorization")
        && !lower.contains("bearer ")
}

fn state_path() -> PathBuf {
    PathBuf::from(get_canonical_paths().user_state).join(SETUP_STATE_FILE)
}

fn catalog_path() -> PathBuf {
    PathBuf::from(get_canonical_paths().user_state).join(SETUP_CATALOG_FILE)
}

fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> ManagerResult<()> {
    let parent = path.parent().ok_or_else(|| {
        setup_error(
            "STORAGE_NOT_WRITABLE",
            "The per-user setup state directory could not be resolved.",
            true,
        )
    })?;
    fs::create_dir_all(parent).map_err(|_| {
        setup_error(
            "STORAGE_NOT_WRITABLE",
            "The per-user setup state directory is not writable.",
            true,
        )
    })?;
    let temporary = path.with_extension(format!("{}.part", now_epoch_ms()));
    let bytes = serde_json::to_vec_pretty(value).map_err(|_| {
        setup_error(
            "SETUP_STATE_SERIALIZATION_FAILED",
            "Setup state could not be serialized safely.",
            false,
        )
    })?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|_| {
            setup_error(
                "STORAGE_NOT_WRITABLE",
                "The per-user setup state file could not be created.",
                true,
            )
        })?;
    file.write_all(&bytes).map_err(|_| {
        setup_error(
            "STORAGE_NOT_WRITABLE",
            "The per-user setup state file could not be written.",
            true,
        )
    })?;
    file.sync_all().map_err(|_| {
        setup_error(
            "STORAGE_NOT_WRITABLE",
            "The per-user setup state file could not be flushed.",
            true,
        )
    })?;
    if path.exists() {
        fs::remove_file(path).map_err(|_| {
            setup_error(
                "STORAGE_NOT_WRITABLE",
                "The previous setup state could not be replaced safely.",
                true,
            )
        })?;
    }
    fs::rename(&temporary, path).map_err(|_| {
        setup_error(
            "STORAGE_NOT_WRITABLE",
            "The setup state could not be committed atomically.",
            true,
        )
    })
}

fn load_state() -> ManagerResult<SetupState> {
    let path = state_path();
    if !path.exists() {
        return Ok(SetupState::default());
    }
    let bytes = fs::read(&path).map_err(|_| {
        setup_error(
            "SETUP_STATE_UNREADABLE",
            "Saved setup preferences could not be read. They can be rebuilt safely.",
            true,
        )
    })?;
    if bytes.len() > 256 * 1024 {
        return Err(setup_error(
            "SETUP_STATE_INVALID",
            "Saved setup preferences exceed the safe size limit.",
            false,
        ));
    }
    let state: SetupState = serde_json::from_slice(&bytes).map_err(|_| {
        setup_error(
            "SETUP_STATE_INVALID",
            "Saved setup preferences are not valid Desktop V2 state.",
            false,
        )
    })?;
    state.validate()?;
    Ok(state)
}

fn catalog_signature_payload(catalog: &SetupCatalog) -> ManagerResult<Vec<u8>> {
    let mut value = serde_json::to_value(catalog).map_err(|_| {
        setup_error(
            "CATALOG_PAYLOAD_INVALID",
            "The signed catalog could not be normalized for verification.",
            false,
        )
    })?;
    if let Value::Object(root) = &mut value {
        if let Some(Value::Object(signature)) = root.get_mut("signature") {
            signature.insert("value".to_string(), Value::String(String::new()));
        }
    }
    serde_json::to_vec(&value).map_err(|_| {
        setup_error(
            "CATALOG_PAYLOAD_INVALID",
            "The signed catalog could not be normalized for verification.",
            false,
        )
    })
}

fn validate_timestamp(value: &str, field: &str) -> ManagerResult<()> {
    if value.len() < 16
        || !value.contains('T')
        || !value.ends_with('Z')
        || OffsetDateTime::parse(value, &Rfc3339).is_err()
    {
        return Err(setup_error(
            "CATALOG_SCHEMA_INVALID",
            &format!("The catalog {field} timestamp is not an ISO-8601 UTC value."),
            false,
        ));
    }
    Ok(())
}

fn validate_catalog_shape(catalog: &SetupCatalog) -> ManagerResult<()> {
    if catalog.schema_version != SETUP_CATALOG_SCHEMA {
        return Err(setup_error(
            "CATALOG_SCHEMA_UNSUPPORTED",
            "This setup catalog version is not supported by the installed shell.",
            false,
        ));
    }
    if !safe_identifier(&catalog.catalog_id)
        || !matches!(catalog.channel.as_str(), "stable" | "beta" | "nightly")
    {
        return Err(setup_error(
            "CATALOG_SCHEMA_INVALID",
            "The setup catalog identity or update channel is invalid.",
            false,
        ));
    }
    validate_timestamp(&catalog.generated_at, "generatedAt")?;
    validate_timestamp(&catalog.expires_at, "expiresAt")?;
    let expires_at = OffsetDateTime::parse(&catalog.expires_at, &Rfc3339).map_err(|_| {
        setup_error(
            "CATALOG_SCHEMA_INVALID",
            "The catalog expiry timestamp is invalid.",
            false,
        )
    })?;
    if expires_at <= OffsetDateTime::now_utc() {
        return Err(setup_error(
            "CATALOG_EXPIRED",
            "This setup catalog has expired. Refresh the production catalog or import a current signed offline catalog.",
            false,
        ));
    }
    if catalog.entries.is_empty() || catalog.entries.len() > MAX_CATALOG_ENTRIES {
        return Err(setup_error(
            "CATALOG_SCHEMA_INVALID",
            "The setup catalog does not contain a safe number of entries.",
            false,
        ));
    }
    let mut ids = BTreeSet::new();
    for entry in &catalog.entries {
        if !safe_identifier(&entry.component_id)
            || entry.display_name.trim().is_empty()
            || entry.description.len() > 8 * 1024
            || !ids.insert(entry.component_id.clone())
        {
            return Err(setup_error(
                "CATALOG_SCHEMA_INVALID",
                "The setup catalog contains an unsafe or duplicate component entry.",
                false,
            ));
        }
        if !matches!(
            entry.availability.as_str(),
            "available" | "catalog-only" | "unavailable"
        ) {
            return Err(setup_error(
                "CATALOG_SCHEMA_INVALID",
                "The setup catalog contains an unknown component availability state.",
                false,
            ));
        }
        if entry.required && entry.availability != "available" {
            return Err(setup_error(
                "REQUIRED_COMPONENT_UNAVAILABLE",
                "A required component is not available in this catalog.",
                false,
            ));
        }
        if entry.availability == "available" && entry.manifest.is_none() {
            return Err(setup_error(
                "CATALOG_MANIFEST_MISSING",
                "An installable catalog entry has no signed component manifest.",
                false,
            ));
        }
        if entry.availability != "available" && entry.manifest.is_some() {
            return Err(setup_error(
                "CATALOG_SCHEMA_INVALID",
                "A catalog-only entry must not claim to carry an installable manifest.",
                false,
            ));
        }
        if let Some(manifest) = &entry.manifest {
            if manifest.component.id != entry.component_id
                || entry.artifact_bytes != manifest.artifact.byte_size
            {
                return Err(setup_error(
                    "CATALOG_MANIFEST_MISMATCH",
                    "A catalog entry does not match the identity or size in its manifest.",
                    false,
                ));
            }
        }
        if entry.required && !matches!(entry.component_id.as_str(), "aive-engine" | "ffmpeg") {
            return Err(setup_error(
                "CATALOG_REQUIRED_COMPONENT_INVALID",
                "Only the core engine and FFmpeg may be required by this Setup Center.",
                false,
            ));
        }
    }
    for required in ["aive-engine", "ffmpeg"] {
        let found = catalog
            .entries
            .iter()
            .find(|entry| entry.component_id == required && entry.required);
        if found.is_none() {
            return Err(setup_error(
                "REQUIRED_COMPONENT_MISSING",
                "The signed setup catalog does not describe both required components.",
                false,
            ));
        }
    }
    Ok(())
}

fn catalog_source_policy(source: &str) -> ManagerResult<SourcePolicy> {
    match source {
        "production" => Ok(SourcePolicy::PRODUCTION),
        "offline-import" if cfg!(debug_assertions)
            && env::var("AIVE_COMPONENT_MANAGER_TEST_MODE").ok().as_deref() == Some("1") =>
        {
            Ok(SourcePolicy::development_test())
        }
        "offline-import" => Err(setup_error(
            "OFFLINE_IMPORT_REQUIRES_TEST_POLICY",
            "Offline catalogs are limited to an explicit lecturer/test build policy; no production trust bypass is enabled.",
            false,
        )),
        _ => Err(setup_error(
            "CATALOG_SOURCE_INVALID",
            "The catalog source is not recognized.",
            false,
        )),
    }
}

fn verify_and_intake_catalog(catalog_json: &str, source: &str) -> ManagerResult<SetupImportResult> {
    if catalog_json.len() > MAX_CATALOG_BYTES {
        return Err(setup_error(
            "CATALOG_TOO_LARGE",
            "The setup catalog exceeds the bounded intake size.",
            false,
        ));
    }
    let catalog: SetupCatalog = serde_json::from_str(catalog_json).map_err(|_| {
        setup_error(
            "CATALOG_SCHEMA_INVALID",
            "The selected setup catalog is not compatible with this shell.",
            false,
        )
    })?;
    validate_catalog_shape(&catalog)?;
    let payload = catalog_signature_payload(&catalog)?;
    component_manager::verify_trusted_detached_payload(
        &catalog.signature.algorithm,
        &catalog.signature.key_id,
        &catalog.signature.value,
        &payload,
    )?;
    let policy = catalog_source_policy(source)?;
    let manager = ComponentManager::new(
        PathBuf::from(get_canonical_paths().program_data_root).join("AI Video Editor"),
    );
    let mut imported_manifest_ids = Vec::new();
    let mut catalog_only_ids = Vec::new();
    for entry in &catalog.entries {
        if let Some(manifest) = &entry.manifest {
            let manifest_json = serde_json::to_string(manifest).map_err(|_| {
                setup_error(
                    "CATALOG_MANIFEST_INVALID",
                    "A signed component manifest could not be read from the catalog.",
                    false,
                )
            })?;
            manager.intake_manifest(&manifest_json, policy)?;
            imported_manifest_ids.push(entry.component_id.clone());
        } else {
            catalog_only_ids.push(entry.component_id.clone());
        }
    }
    let info = SetupCatalogInfo {
        catalog: catalog.clone(),
        source: source.to_string(),
        verified_at_epoch_ms: now_epoch_ms(),
        path: catalog_path().to_string_lossy().to_string(),
    };
    atomic_write_json(Path::new(&info.path), &info)?;
    Ok(SetupImportResult {
        catalog: info,
        imported_manifest_ids,
        catalog_only_ids,
    })
}

fn load_catalog() -> ManagerResult<Option<SetupCatalogInfo>> {
    let path = catalog_path();
    if !path.exists() {
        return Ok(None);
    }
    let bytes = fs::read(&path).map_err(|_| {
        setup_error(
            "CATALOG_CACHE_UNREADABLE",
            "The cached setup catalog could not be read. Import it again from a trusted source.",
            true,
        )
    })?;
    if bytes.len() > MAX_CATALOG_BYTES {
        return Err(setup_error(
            "CATALOG_TOO_LARGE",
            "The cached setup catalog exceeds the bounded intake size.",
            false,
        ));
    }
    let info: SetupCatalogInfo = serde_json::from_slice(&bytes).map_err(|_| {
        setup_error(
            "CATALOG_CACHE_INVALID",
            "The cached setup catalog is not valid. Import a signed catalog again.",
            false,
        )
    })?;
    validate_catalog_shape(&info.catalog)?;
    let payload = catalog_signature_payload(&info.catalog)?;
    component_manager::verify_trusted_detached_payload(
        &info.catalog.signature.algorithm,
        &info.catalog.signature.key_id,
        &info.catalog.signature.value,
        &payload,
    )?;
    Ok(Some(info))
}

fn configured_catalog_url() -> Option<String> {
    if let Some(value) = option_env!("AIVE_SETUP_CATALOG_URL") {
        if !value.trim().is_empty() {
            return Some(value.to_string());
        }
    }
    // Runtime configuration is intentionally available only in debug builds
    // for lecturer/test environments. Release catalogs are build-time input.
    if cfg!(debug_assertions) {
        return env::var(PRODUCTION_CATALOG_ENV)
            .ok()
            .filter(|value| !value.trim().is_empty());
    }
    None
}

fn validate_production_catalog_url(url: &str) -> ManagerResult<()> {
    let parsed = url::Url::parse(url).map_err(|_| {
        setup_error(
            "CATALOG_URL_INVALID",
            "The configured catalog URL is not valid.",
            false,
        )
    })?;
    if parsed.scheme() != "https" {
        return Err(setup_error(
            "HTTPS_REQUIRED",
            "Production setup catalogs must use HTTPS.",
            false,
        ));
    }
    Ok(())
}

#[tauri::command]
pub fn setup_get_state() -> ManagerResult<SetupState> {
    load_state()
}

#[tauri::command]
pub fn setup_save_state(mut state: SetupState) -> ManagerResult<SetupState> {
    state.schema_version = SETUP_STATE_SCHEMA.to_string();
    state.updated_at_epoch_ms = now_epoch_ms();
    state.validate()?;
    atomic_write_json(&state_path(), &state)?;
    Ok(state)
}

#[tauri::command]
pub fn setup_get_catalog() -> ManagerResult<Option<SetupCatalogInfo>> {
    load_catalog()
}

#[tauri::command]
pub fn setup_import_catalog(
    catalog_json: String,
    source: String,
) -> ManagerResult<SetupImportResult> {
    verify_and_intake_catalog(&catalog_json, &source)
}

#[tauri::command]
pub fn setup_catalog_configuration(
    channel: Option<String>,
) -> ManagerResult<SetupCatalogConfiguration> {
    let channel = channel.unwrap_or_else(|| "stable".to_string());
    if !matches!(channel.as_str(), "stable" | "beta" | "nightly") {
        return Err(setup_error(
            "CATALOG_CHANNEL_INVALID",
            "The selected update channel is not supported.",
            false,
        ));
    }
    let configured = configured_catalog_url();
    Ok(SetupCatalogConfiguration {
        channel,
        production_url_configured: configured.is_some(),
        production_url: configured,
        offline_import_supported: cfg!(debug_assertions),
        trust_policy: "Only the shell's compiled Ed25519 trust root is accepted; catalog-supplied keys are ignored, and every embedded component manifest is verified by the Phase 3 manager before intake.".to_string(),
    })
}

#[tauri::command]
pub fn setup_refresh_catalog() -> ManagerResult<SetupImportResult> {
    let url = configured_catalog_url().ok_or_else(|| {
        setup_error(
            "CATALOG_URL_NOT_CONFIGURED",
            "This build has no production catalog URL. Import a signed local catalog for lecturer/testing use.",
            false,
        )
    })?;
    validate_production_catalog_url(&url)?;
    let client = Client::builder()
        .timeout(Duration::from_secs(20))
        .redirect(Policy::limited(3))
        .build()
        .map_err(|_| {
            setup_error(
                "CATALOG_NETWORK_ERROR",
                "The catalog connection could not be prepared.",
                true,
            )
        })?;
    let response = client.get(url).send().map_err(|_| {
        setup_error(
            "CATALOG_NETWORK_ERROR",
            "The production catalog could not be reached. Check network, proxy, or TLS settings, or use offline import.",
            true,
        )
    })?;
    if !response.status().is_success() {
        return Err(setup_error(
            "CATALOG_NETWORK_ERROR",
            "The production catalog returned an unavailable response. Retry later or use offline import.",
            true,
        ));
    }
    let bytes = response.bytes().map_err(|_| {
        setup_error(
            "CATALOG_NETWORK_ERROR",
            "The production catalog response could not be read safely.",
            true,
        )
    })?;
    if bytes.len() > MAX_CATALOG_BYTES {
        return Err(setup_error(
            "CATALOG_TOO_LARGE",
            "The production catalog exceeds the bounded intake size.",
            false,
        ));
    }
    let json = String::from_utf8(bytes.to_vec()).map_err(|_| {
        setup_error(
            "CATALOG_SCHEMA_INVALID",
            "The production catalog is not valid UTF-8 JSON.",
            false,
        )
    })?;
    verify_and_intake_catalog(&json, "production")
}

fn push_check(
    checks: &mut Vec<SetupSystemCheck>,
    id: &str,
    label: &str,
    severity: &str,
    explanation: impl Into<String>,
    remediation: impl Into<String>,
    technical_detail: Option<String>,
) {
    checks.push(SetupSystemCheck {
        id: id.to_string(),
        label: label.to_string(),
        severity: severity.to_string(),
        explanation: explanation.into(),
        remediation: remediation.into(),
        technical_detail,
    });
}

fn free_space_bytes(path: &Path) -> Option<u64> {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;
        let mut wide: Vec<u16> = path.as_os_str().encode_wide().collect();
        wide.push(0);
        let mut free = 0_u64;
        // SAFETY: the path is NUL-terminated and all output pointers are
        // valid for the duration of the OS call.
        let result = unsafe {
            GetDiskFreeSpaceExW(
                wide.as_ptr(),
                &mut free,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        };
        if result != 0 {
            return Some(free);
        }
    }
    #[cfg(not(windows))]
    let _ = path;
    None
}

fn process_is_elevated() -> bool {
    if !cfg!(windows) {
        return false;
    }
    Command::new("whoami")
        .args(["/groups"])
        .output()
        .ok()
        .map(|output| {
            let text = String::from_utf8_lossy(&output.stdout).to_ascii_lowercase();
            text.contains("s-1-16-12288")
                || text.contains("s-1-16-16384")
                || text.contains("high mandatory level")
                || text.contains("system mandatory level")
        })
        .unwrap_or(false)
}

fn probe_writable_root(path: &Path) -> Result<(), String> {
    fs::create_dir_all(path).map_err(|error| error.kind().to_string())?;
    let probe = path.join(format!(".setup-center-write-check-{}", now_epoch_ms()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&probe)
        .map_err(|error| error.kind().to_string())?;
    file.write_all(b"desktop-v2-setup-check")
        .map_err(|error| error.kind().to_string())?;
    file.sync_all().map_err(|error| error.kind().to_string())?;
    fs::remove_file(probe).map_err(|error| error.kind().to_string())
}

fn network_check() -> (String, String, Option<String>) {
    let Some(url) = configured_catalog_url() else {
        return (
            "warning".to_string(),
            "No production catalog endpoint is configured in this build; offline signed import remains available.".to_string(),
            None,
        );
    };
    if validate_production_catalog_url(&url).is_err() {
        return (
            "error".to_string(),
            "The configured catalog endpoint is not a valid HTTPS URL.".to_string(),
            Some(
                "Rebuild with a reviewed HTTPS catalog URL or use a signed offline catalog."
                    .to_string(),
            ),
        );
    }
    let result = Client::builder()
        .timeout(Duration::from_secs(4))
        .redirect(Policy::limited(2))
        .build()
        .ok()
        .and_then(|client| client.get(url).send().ok())
        .map(|response| response.status().is_success());
    match result {
        Some(true) => (
            "pass".to_string(),
            "The configured catalog endpoint is reachable.".to_string(),
            None,
        ),
        _ => (
            "warning".to_string(),
            "The catalog endpoint is not reachable right now; setup can continue from a signed local catalog.".to_string(),
            Some("Check proxy/TLS/firewall settings, retry, or choose Offline import.".to_string()),
        ),
    }
}

#[tauri::command]
pub fn setup_run_system_checks(
    probe_network: bool,
    supervisor: State<'_, SupervisorState>,
) -> ManagerResult<SetupSystemChecksResult> {
    let paths = get_canonical_paths();
    let component_root = PathBuf::from(&paths.program_data_root).join("AI Video Editor");
    let user_state_root = PathBuf::from(&paths.user_state);
    let mut checks = Vec::new();
    let windows_supported = cfg!(windows);
    push_check(
        &mut checks,
        "platform",
        "Supported Windows platform",
        if windows_supported { "pass" } else { "error" },
        if windows_supported {
            "This build is running on Windows, the supported Desktop V2 platform."
        } else {
            "The native Setup Center requires Windows; browser/Vite mode remains available on other platforms."
        },
        if windows_supported {
            "No action required."
        } else {
            "Run the installed Tauri build on a supported Windows machine."
        },
        Some(format!("target_os={}", env::consts::OS)),
    );
    let architecture = env::consts::ARCH.to_string();
    let architecture_ok = matches!(architecture.as_str(), "x86_64" | "aarch64");
    push_check(
        &mut checks,
        "architecture",
        "Supported architecture",
        if architecture_ok { "pass" } else { "error" },
        if architecture_ok {
            format!(
                "The shell architecture {architecture} is supported by the Desktop V2 contract."
            )
        } else {
            format!("The shell architecture {architecture} is not supported by the signed component targets.")
        },
        if architecture_ok {
            "No action required."
        } else {
            "Install the x64 or arm64 build that matches this machine."
        },
        None,
    );
    push_check(
        &mut checks,
        "shell-version",
        "Shell version",
        "pass",
        format!("Desktop V2 shell {} can enforce component minimum-version requirements before install.", env!("CARGO_PKG_VERSION")),
        "No action required.",
        None,
    );

    let free_space = free_space_bytes(Path::new(&paths.program_data_root));
    let disk_severity = match free_space {
        Some(bytes) if bytes >= MIN_SYSTEM_FREE_BYTES => "pass",
        Some(_) => "error",
        None => "warning",
    };
    push_check(
        &mut checks,
        "disk-space",
        "Available component disk space",
        disk_severity,
        match free_space {
            Some(bytes) => format!("{} is available on the component volume; at least 512 MiB is reserved for staging and rollback.", format_bytes(bytes)),
            None => "The available disk space could not be measured before a catalog is selected.".to_string(),
        },
        if disk_severity == "pass" { "No action required." } else { "Free space on the ProgramData volume, then retry." },
        free_space.map(|bytes| format!("free_space_bytes={bytes}")),
    );

    let roots_ok = paths.path_invariants_hold();
    push_check(
        &mut checks,
        "storage-boundaries",
        "Storage boundaries",
        if roots_ok { "pass" } else { "error" },
        if roots_ok {
            "Program Files remains immutable, machine components remain under ProgramData, and user state remains under LocalAppData."
        } else {
            "The resolved storage layout does not satisfy the Desktop V2 boundary contract."
        },
        if roots_ok {
            "No action required."
        } else {
            "Repair the installation layout and open Diagnostics; the shell will not use an AppData runtime fallback."
        },
        None,
    );

    let component_permission = probe_writable_root(&component_root);
    let user_permission = probe_writable_root(&user_state_root);
    let permission_ok = component_permission.is_ok() && user_permission.is_ok();
    push_check(
        &mut checks,
        "permissions",
        "Component store permission",
        if permission_ok { "pass" } else { "error" },
        if permission_ok {
            "The installer-created component-store ACL permits this non-elevated shell to write only the scoped ProgramData component perimeter."
        } else {
            "The shell could not write the scoped ProgramData component perimeter. It will not silently redirect runtime files into AppData."
        },
        if permission_ok {
            "No action required."
        } else {
            "Run the per-machine installer again or ask an administrator to repair the component-store ACL; retry after UAC if prompted."
        },
        Some(format!(
            "component_store={:?}; user_state={:?}; process_elevated={}",
            component_permission,
            user_permission,
            process_is_elevated()
        )),
    );

    let active_statuses = ComponentManager::new(component_root.clone())
        .status(None)
        .unwrap_or_default();
    let active_required = ["aive-engine", "ffmpeg"].iter().all(|id| {
        active_statuses
            .iter()
            .find(|status| status.id == *id)
            .map(|status| status.state == "active")
            .unwrap_or(false)
    });
    push_check(
        &mut checks,
        "active-versions",
        "Existing active versions",
        if active_required { "pass" } else { "warning" },
        if active_required {
            "Both required components have active versions selected by the manager."
        } else {
            "One or more required components is not active yet; this is expected on first run."
        },
        if active_required {
            "No action required."
        } else {
            "Import a signed catalog and complete the required component setup stages."
        },
        Some(format!("status_count={}", active_statuses.len())),
    );

    let supervisor_status = supervisor.status();
    let native_health_ok = matches!(
        supervisor_status.state,
        SupervisorPhase::Ready | SupervisorPhase::Degraded
    ) && supervisor_status.engine_ready;
    push_check(
        &mut checks,
        "native-health",
        "Native engine and FFmpeg health",
        if native_health_ok {
            "pass"
        } else if active_required {
            "warning"
        } else {
            "info"
        },
        if native_health_ok {
            "The authenticated supervisor reports native engine readiness and capabilities."
        } else if active_required {
            "Required versions are present, but the authenticated supervisor has not reported readiness."
        } else {
            "Native health will be checked after required components activate."
        },
        if native_health_ok {
            "No action required."
        } else {
            "Complete setup, then start or retry the authenticated supervisor."
        },
        Some(format!("supervisor_state={:?}", supervisor_status.state)),
    );

    let (network_severity, network_explanation, network_remediation) = if probe_network {
        network_check()
    } else {
        (
            "info".to_string(),
            "Network reachability was not probed; setup can use a signed offline catalog.".to_string(),
            Some("Refresh the production catalog when network access is available, or use Offline import.".to_string()),
        )
    };
    push_check(
        &mut checks,
        "network",
        "Catalog network reachability",
        &network_severity,
        network_explanation,
        network_remediation.unwrap_or_else(|| "No action required.".to_string()),
        None,
    );
    push_check(
        &mut checks,
        "gpu-model",
        "Optional GPU/model capability",
        "info",
        "GPU acceleration and local model packs are optional; no capability is claimed until a signed pack and runtime are available.",
        "No action required. Select an available optional pack only when the catalog provides a verified manifest.",
        None,
    );

    let supported = windows_supported && architecture_ok && roots_ok && permission_ok;
    Ok(SetupSystemChecksResult {
        schema_version: "desktop.setup-system-checks.v1".to_string(),
        generated_at_epoch_ms: now_epoch_ms(),
        supported,
        process_elevated: process_is_elevated(),
        architecture,
        free_space_bytes: free_space,
        component_root: component_root.to_string_lossy().to_string(),
        user_state_root: user_state_root.to_string_lossy().to_string(),
        checks,
    })
}

fn format_bytes(bytes: u64) -> String {
    const UNITS: [&str; 4] = ["B", "KiB", "MiB", "GiB"];
    let mut value = bytes as f64;
    let mut index = 0;
    while value >= 1024.0 && index < UNITS.len() - 1 {
        value /= 1024.0;
        index += 1;
    }
    format!("{value:.1} {}", UNITS[index])
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn minimal_catalog() -> SetupCatalog {
        SetupCatalog {
            schema_version: SETUP_CATALOG_SCHEMA.to_string(),
            catalog_id: "test-catalog".to_string(),
            channel: "stable".to_string(),
            generated_at: "2026-01-01T00:00:00Z".to_string(),
            expires_at: "2099-01-01T00:00:00Z".to_string(),
            entries: vec![
                catalog_only("aive-engine", true),
                catalog_only("ffmpeg", true),
                catalog_only("local-transcription", false),
            ],
            signature: CatalogSignature {
                algorithm: "ed25519".to_string(),
                key_id: "unknown-test-key".to_string(),
                value: "".to_string(),
            },
        }
    }

    fn catalog_only(id: &str, required: bool) -> SetupCatalogEntry {
        SetupCatalogEntry {
            component_id: id.to_string(),
            display_name: id.to_string(),
            required,
            availability: "catalog-only".to_string(),
            description: "Test catalog entry".to_string(),
            artifact_bytes: 0,
            license_version: "1".to_string(),
            license_name: "MIT".to_string(),
            source_url: None,
            unavailable_reason: Some("No signed artifact in this fixture.".to_string()),
            manifest: None,
        }
    }

    #[test]
    fn state_defaults_are_non_secret_and_validate() {
        let state = SetupState::default();
        state.validate().expect("default setup state is valid");
        let encoded = serde_json::to_string(&state).expect("state serializes");
        assert!(!encoded.to_ascii_lowercase().contains("token"));
        assert!(!encoded.to_ascii_lowercase().contains("secret"));
    }

    #[test]
    fn state_recovery_ids_are_durable_but_secret_like_values_are_rejected() {
        let mut state = SetupState::default();
        state.incomplete_operation_ids.insert(
            "aive-engine".to_string(),
            "setup-aive-engine-123".to_string(),
        );
        state
            .validate()
            .expect("operation ids are valid recovery state");
        state.accepted_license_versions.insert(
            "aive-engine".to_string(),
            "token=should-not-persist".to_string(),
        );
        assert_eq!(
            state
                .validate()
                .expect_err("secret-like state must fail")
                .code,
            "SETUP_STATE_INVALID"
        );
    }

    #[test]
    fn catalog_trust_root_rejects_unknown_key_without_using_catalog_key_material() {
        let error = component_manager::verify_trusted_detached_payload(
            "ed25519",
            "catalog-supplied-key",
            "",
            b"setup-catalog-payload",
        )
        .expect_err("unknown catalog key must not be trusted");
        assert_eq!(error.code, "UNKNOWN_TRUST_KEY");
    }

    #[test]
    fn catalog_shape_requires_both_required_components_and_rejects_catalog_only_required() {
        let catalog = minimal_catalog();
        let error =
            validate_catalog_shape(&catalog).expect_err("required catalog-only entry must fail");
        assert_eq!(error.code, "REQUIRED_COMPONENT_UNAVAILABLE");

        let mut missing = minimal_catalog();
        missing.entries.remove(1);
        let error = validate_catalog_shape(&missing).expect_err("missing ffmpeg must fail");
        assert_eq!(error.code, "REQUIRED_COMPONENT_UNAVAILABLE");
    }

    #[test]
    fn catalog_signature_payload_blanks_only_the_signature_value() {
        let catalog = minimal_catalog();
        let payload = catalog_signature_payload(&catalog).expect("payload");
        let value: Value = serde_json::from_slice(&payload).expect("json payload");
        assert_eq!(value["signature"]["value"], json!(""));
        assert_eq!(value["signature"]["keyId"], json!("unknown-test-key"));
    }

    #[test]
    fn production_catalog_url_is_https_only() {
        assert!(
            validate_production_catalog_url("https://updates.example.test/catalog.json").is_ok()
        );
        assert_eq!(
            validate_production_catalog_url("http://localhost/catalog.json")
                .expect_err("http must be rejected")
                .code,
            "HTTPS_REQUIRED"
        );
    }
}
