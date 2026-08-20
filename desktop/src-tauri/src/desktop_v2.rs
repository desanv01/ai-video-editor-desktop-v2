//! Desktop V2 Phase 2 thin-shell bootstrap.
//!
//! This module is deliberately boring: it discovers paths, reads activation
//! metadata, persists a small per-user shell state file, and writes redacted
//! diagnostics. It does not start a process, make an HTTP request, invoke
//! Docker, or inspect a backend service. Component installation and engine
//! supervision belong to later phases.

use crate::contracts::{canonical_windows_storage_layout, StorageLayout, STORAGE_LAYOUT_VERSION};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub const PRODUCT_NAME: &str = "AI Video Editor Desktop V2";
pub const PRODUCT_LINE: &str = "Desktop V2";
pub const PRODUCT_IDENTIFIER: &str = "com.fyp.ai-video-editor.desktop-v2";
pub const SHELL_STATE_VERSION: &str = "desktop.shell-state.v1";
pub const DIAGNOSTIC_SNAPSHOT_VERSION: &str = "desktop.diagnostics.v1";
const ACTIVE_METADATA_FILENAME: &str = "aive-engine.json";
const MAX_ACTIVATION_METADATA_BYTES: usize = 128 * 1024;
const MAX_DIAGNOSTIC_TEXT_BYTES: usize = 2 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ShellBootState {
    Starting,
    ShellReady,
    SetupRequired,
    EngineAvailable,
    RecoverableError,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BootEvent {
    ShellReady,
    ComponentMissing,
    ComponentAvailable,
    ComponentInvalid,
    SupervisorReady,
    RecoverableError,
}

pub fn transition_boot_state(state: ShellBootState, event: BootEvent) -> ShellBootState {
    if event == BootEvent::RecoverableError {
        return ShellBootState::RecoverableError;
    }
    match (state, event) {
        (ShellBootState::Starting, BootEvent::ShellReady) => ShellBootState::ShellReady,
        (ShellBootState::ShellReady, BootEvent::ComponentMissing) => ShellBootState::SetupRequired,
        (ShellBootState::ShellReady, BootEvent::ComponentAvailable) => {
            ShellBootState::EngineAvailable
        }
        (ShellBootState::ShellReady, BootEvent::ComponentInvalid) => {
            ShellBootState::RecoverableError
        }
        (ShellBootState::EngineAvailable, BootEvent::SupervisorReady) => {
            ShellBootState::EngineAvailable
        }
        (current, _) => current,
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShellInfo {
    pub product_name: String,
    pub product_line: String,
    pub shell_version: String,
    pub identifier: String,
    pub launch_mode: String,
    pub bootstrap_policy: String,
    pub storage_layout_version: String,
    pub shell_install_path: String,
    pub user_state_path: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResolvedDesktopPaths {
    pub schema_version: String,
    pub platform: String,
    pub program_files_root: String,
    pub program_data_root: String,
    pub local_app_data_root: String,
    pub user_profile_root: String,
    pub storage_layout: StorageLayout,
    pub shell_install: String,
    pub shared_components: String,
    pub activation_metadata: String,
    pub activation_metadata_file: String,
    pub download_staging: String,
    pub user_root: String,
    pub user_config: String,
    pub user_cache: String,
    pub user_logs: String,
    pub user_state: String,
    pub shell_state_file: String,
    pub projects: String,
    pub exports: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ActivationMetadataInspection {
    pub status: String,
    pub metadata_path: String,
    pub present: bool,
    pub component_id: Option<String>,
    pub component_version: Option<String>,
    pub active_path: Option<String>,
    pub detail_code: String,
    pub detail: String,
    pub remediation_codes: Vec<String>,
}

#[derive(Debug, Clone)]
struct ActivationMetadataInspectionInternal {
    public: ActivationMetadataInspection,
    technical_detail: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ComponentStatus {
    pub id: String,
    pub display_name: String,
    pub state: String,
    pub required: bool,
    pub detail: String,
    pub remediation_codes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShellRemediation {
    pub code: String,
    pub title: String,
    pub action: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShellBootstrapError {
    pub code: String,
    pub message: String,
    pub remediation_codes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopV2BootstrapResult {
    pub shell_info: ShellInfo,
    pub paths: ResolvedDesktopPaths,
    pub boot_state: ShellBootState,
    pub engine_ready: bool,
    pub setup_required: bool,
    pub component_status: Vec<ComponentStatus>,
    pub activation: ActivationMetadataInspection,
    pub remediation: Vec<ShellRemediation>,
    pub persisted_state_path: String,
    pub error: Option<ShellBootstrapError>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SafeLogDirectoryResult {
    pub available: bool,
    pub path: String,
    pub created: bool,
    pub detail: String,
    pub remediation_codes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiagnosticSnapshotResult {
    pub created: bool,
    pub diagnostic_id: String,
    pub path: Option<String>,
    pub detail: String,
    pub remediation_codes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedShellState {
    schema_version: String,
    boot_state: ShellBootState,
    engine_ready: bool,
    updated_at_epoch_ms: u128,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DiagnosticSnapshot {
    schema_version: String,
    generated_at_epoch_ms: u128,
    shell_info: ShellInfo,
    boot_state: ShellBootState,
    engine_ready: bool,
    component_status: Vec<ComponentStatus>,
    activation_status: String,
    activation_detail_code: String,
    storage_layout_version: String,
    technical_details: Vec<String>,
}

#[derive(Debug, Clone)]
struct PathRoots {
    program_files: PathBuf,
    program_data: PathBuf,
    local_app_data: PathBuf,
    user_profile: PathBuf,
}

impl ResolvedDesktopPaths {
    fn from_roots(roots: &PathRoots) -> Self {
        let product_root = Path::new("AI Video Editor");
        let user_root = roots.local_app_data.join(product_root);
        let shell_install = roots.program_files.join(product_root).join("Shell");
        let shared_components = roots.program_data.join(product_root).join("Components");
        let activation_metadata = roots.program_data.join(product_root).join("Activation");
        let download_staging = roots
            .program_data
            .join(product_root)
            .join("Downloads")
            .join("Staging");
        let user_config = user_root.join("Config");
        let user_cache = user_root.join("Cache");
        let user_logs = user_root.join("Logs");
        let user_state = user_root.join("State");
        let projects = roots
            .user_profile
            .join("Documents")
            .join(product_root)
            .join("Projects");
        let exports = roots
            .user_profile
            .join("Documents")
            .join(product_root)
            .join("Exports");

        Self {
            schema_version: STORAGE_LAYOUT_VERSION.to_string(),
            platform: "windows".to_string(),
            program_files_root: roots.program_files.to_string_lossy().to_string(),
            program_data_root: roots.program_data.to_string_lossy().to_string(),
            local_app_data_root: roots.local_app_data.to_string_lossy().to_string(),
            user_profile_root: roots.user_profile.to_string_lossy().to_string(),
            storage_layout: canonical_windows_storage_layout(),
            shell_install: shell_install.to_string_lossy().to_string(),
            shared_components: shared_components.to_string_lossy().to_string(),
            activation_metadata: activation_metadata.to_string_lossy().to_string(),
            activation_metadata_file: activation_metadata
                .join(ACTIVE_METADATA_FILENAME)
                .to_string_lossy()
                .to_string(),
            download_staging: download_staging.to_string_lossy().to_string(),
            user_root: user_root.to_string_lossy().to_string(),
            user_config: user_config.to_string_lossy().to_string(),
            user_cache: user_cache.to_string_lossy().to_string(),
            user_logs: user_logs.to_string_lossy().to_string(),
            user_state: user_state.to_string_lossy().to_string(),
            shell_state_file: user_state
                .join("shell-state.json")
                .to_string_lossy()
                .to_string(),
            projects: projects.to_string_lossy().to_string(),
            exports: exports.to_string_lossy().to_string(),
        }
    }

    fn storage_root(&self, path: &str) -> PathBuf {
        PathBuf::from(path)
    }

    pub fn path_invariants_hold(&self) -> bool {
        let program_files = self.storage_root(&self.program_files_root);
        let program_data = self.storage_root(&self.program_data_root);
        let local_app_data = self.storage_root(&self.local_app_data_root);
        let user_profile = self.storage_root(&self.user_profile_root);
        let user_root = self.storage_root(&self.user_root);

        is_same_or_child(&program_files, &self.storage_root(&self.shell_install))
            && !is_same_or_child(&program_files, &self.storage_root(&self.user_root))
            && is_same_or_child(&program_data, &self.storage_root(&self.shared_components))
            && is_same_or_child(&program_data, &self.storage_root(&self.activation_metadata))
            && is_same_or_child(&program_data, &self.storage_root(&self.download_staging))
            && is_same_or_child(&local_app_data, &user_root)
            && is_same_or_child(&user_root, &self.storage_root(&self.user_config))
            && is_same_or_child(&user_root, &self.storage_root(&self.user_cache))
            && is_same_or_child(&user_root, &self.storage_root(&self.user_logs))
            && is_same_or_child(&user_root, &self.storage_root(&self.user_state))
            && is_same_or_child(&user_profile, &self.storage_root(&self.projects))
            && is_same_or_child(&user_profile, &self.storage_root(&self.exports))
            && !self.storage_layout.program_files_runtime_writable
            && self.storage_layout.validate().is_ok()
    }
}

fn is_same_or_child(root: &Path, candidate: &Path) -> bool {
    let normalized_root = root
        .to_string_lossy()
        .replace('\\', "/")
        .trim_end_matches('/')
        .to_ascii_lowercase();
    let normalized_candidate = candidate
        .to_string_lossy()
        .replace('\\', "/")
        .trim_end_matches('/')
        .to_ascii_lowercase();
    normalized_candidate == normalized_root
        || normalized_candidate.starts_with(&(normalized_root + "/"))
}

fn env_path(name: &str) -> Option<PathBuf> {
    env::var_os(name)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
}

fn path_roots() -> PathRoots {
    let user_profile = env_path("USERPROFILE")
        .or_else(dirs::home_dir)
        .unwrap_or_else(|| PathBuf::from(r"C:\Users\Unknown"));
    let local_app_data = env_path("LOCALAPPDATA")
        .or_else(dirs::data_local_dir)
        .unwrap_or_else(|| user_profile.join("AppData").join("Local"));

    PathRoots {
        program_files: env_path("PROGRAMFILES")
            .unwrap_or_else(|| PathBuf::from(r"C:\Program Files")),
        program_data: env_path("PROGRAMDATA").unwrap_or_else(|| PathBuf::from(r"C:\ProgramData")),
        local_app_data,
        user_profile,
    }
}

fn resolved_paths() -> ResolvedDesktopPaths {
    ResolvedDesktopPaths::from_roots(&path_roots())
}

fn shell_info(paths: &ResolvedDesktopPaths) -> ShellInfo {
    ShellInfo {
        product_name: PRODUCT_NAME.to_string(),
        product_line: PRODUCT_LINE.to_string(),
        shell_version: env!("CARGO_PKG_VERSION").to_string(),
        identifier: PRODUCT_IDENTIFIER.to_string(),
        launch_mode: "tauri-desktop-v2".to_string(),
        bootstrap_policy: "offline-safe; no engine, backend, Docker, or network startup"
            .to_string(),
        storage_layout_version: STORAGE_LAYOUT_VERSION.to_string(),
        shell_install_path: paths.shell_install.clone(),
        user_state_path: paths.shell_state_file.clone(),
    }
}

fn now_epoch_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
}

fn nested_string_field(value: &Value, object_key: &str, key: &str) -> Option<String> {
    value
        .get(object_key)
        .and_then(|object| string_field(object, key))
}

fn inspect_activation_metadata_internal(
    paths: &ResolvedDesktopPaths,
) -> ActivationMetadataInspectionInternal {
    let primary_path = PathBuf::from(&paths.activation_metadata_file);
    let metadata_path = [
        primary_path.clone(),
        PathBuf::from(&paths.activation_metadata).join("active.json"),
        PathBuf::from(&paths.activation_metadata)
            .join("aive-engine")
            .join("activation.json"),
    ]
    .into_iter()
    .find(|candidate| candidate.exists())
    .unwrap_or(primary_path);
    let metadata_path_string = metadata_path.to_string_lossy().to_string();
    if !metadata_path.exists() {
        return ActivationMetadataInspectionInternal {
            public: ActivationMetadataInspection {
                status: "missing".to_string(),
                metadata_path: metadata_path_string,
                present: false,
                component_id: None,
                component_version: None,
                active_path: None,
                detail_code: "ENGINE_NOT_RUNNING".to_string(),
                detail: "No verified activation metadata is installed yet.".to_string(),
                remediation_codes: vec!["ENGINE_NOT_RUNNING".to_string()],
            },
            technical_detail: None,
        };
    }

    let bytes = match fs::read(&metadata_path) {
        Ok(bytes) => bytes,
        Err(error) => {
            return ActivationMetadataInspectionInternal {
                public: ActivationMetadataInspection {
                    status: "unreadable".to_string(),
                    metadata_path: metadata_path_string,
                    present: true,
                    component_id: None,
                    component_version: None,
                    active_path: None,
                    detail_code: "STORAGE_NOT_WRITABLE".to_string(),
                    detail: "Activation metadata exists but could not be read. Open Diagnostics for details.".to_string(),
                    remediation_codes: vec!["STORAGE_NOT_WRITABLE".to_string()],
                },
                technical_detail: Some(format!("activation metadata read failed: {error}")),
            };
        }
    };

    if bytes.len() > MAX_ACTIVATION_METADATA_BYTES {
        return invalid_activation(
            metadata_path_string,
            "activation metadata exceeds the safe inspection limit",
        );
    }

    let value: Value = match serde_json::from_slice(&bytes) {
        Ok(value) => value,
        Err(error) => {
            return invalid_activation_with_technical(
                metadata_path_string,
                "activation metadata is not valid JSON",
                format!("activation metadata JSON parse failed: {error}"),
            );
        }
    };

    let component_id = string_field(&value, "componentId")
        .or_else(|| nested_string_field(&value, "component", "id"));
    let component_version = string_field(&value, "componentVersion")
        .or_else(|| nested_string_field(&value, "component", "version"));
    let active_path = string_field(&value, "activePath")
        .or_else(|| nested_string_field(&value, "activation", "activePath"));
    let state = string_field(&value, "state")
        .or_else(|| nested_string_field(&value, "activation", "checkpoint"));

    let Some(component_id) = component_id else {
        return invalid_activation(
            metadata_path_string,
            "activation metadata has no component identity",
        );
    };
    let Some(component_version) = component_version else {
        return invalid_activation(
            metadata_path_string,
            "activation metadata has no component version",
        );
    };
    if state.as_deref() != Some("active") {
        return invalid_activation(
            metadata_path_string,
            "activation metadata is not at an active checkpoint",
        );
    }
    let Some(active_path) = active_path else {
        return invalid_activation(
            metadata_path_string,
            "activation metadata has no active path",
        );
    };

    let active_path_buf = PathBuf::from(&active_path);
    let components_root = PathBuf::from(&paths.shared_components);
    if !is_same_or_child(&components_root, &active_path_buf)
        || is_same_or_child(&PathBuf::from(&paths.program_files_root), &active_path_buf)
    {
        return invalid_activation(
            metadata_path_string,
            "active component path is outside the immutable ProgramData components root",
        );
    }

    ActivationMetadataInspectionInternal {
        public: ActivationMetadataInspection {
            status: "available".to_string(),
            metadata_path: metadata_path_string,
            present: true,
            component_id: Some(component_id),
            component_version: Some(component_version),
            active_path: Some(active_path),
            detail_code: "ENGINE_NOT_RUNNING".to_string(),
            detail: "Activation metadata is valid; the Phase 2 shell does not start the engine supervisor.".to_string(),
            remediation_codes: vec!["ENGINE_NOT_RUNNING".to_string()],
        },
        technical_detail: None,
    }
}

fn invalid_activation(metadata_path: String, detail: &str) -> ActivationMetadataInspectionInternal {
    invalid_activation_with_technical(metadata_path, detail, detail.to_string())
}

fn invalid_activation_with_technical(
    metadata_path: String,
    _detail: &str,
    technical_detail: String,
) -> ActivationMetadataInspectionInternal {
    ActivationMetadataInspectionInternal {
        public: ActivationMetadataInspection {
            status: "invalid".to_string(),
            metadata_path,
            present: true,
            component_id: None,
            component_version: None,
            active_path: None,
            detail_code: "COMPONENT_VERSION_INCOMPATIBLE".to_string(),
            detail: "Activation metadata could not be validated. Open Diagnostics for the technical detail.".to_string(),
            remediation_codes: vec!["COMPONENT_VERSION_INCOMPATIBLE".to_string()],
        },
        technical_detail: Some(technical_detail),
    }
}

fn core_component_status(activation: &ActivationMetadataInspection) -> ComponentStatus {
    if activation.status == "available" && activation.component_id.as_deref() == Some("aive-engine")
    {
        return ComponentStatus {
            id: "aive-engine".to_string(),
            display_name: "Core engine".to_string(),
            state: "available".to_string(),
            required: true,
            detail: format!(
                "Verified core engine component {} is selected; supervisor readiness is deferred.",
                activation
                    .component_version
                    .as_deref()
                    .unwrap_or("unknown version")
            ),
            remediation_codes: vec!["ENGINE_NOT_RUNNING".to_string()],
        };
    }

    ComponentStatus {
        id: "aive-engine".to_string(),
        display_name: "Core engine".to_string(),
        state: if activation.status == "missing" {
            "not-installed".to_string()
        } else {
            "unavailable".to_string()
        },
        required: true,
        detail: if activation.status == "missing" {
            "Core engine not installed. Use Setup Center when component delivery is available."
                .to_string()
        } else {
            activation.detail.clone()
        },
        remediation_codes: activation.remediation_codes.clone(),
    }
}

fn shell_component_status() -> ComponentStatus {
    ComponentStatus {
        id: "desktop-v2-shell".to_string(),
        display_name: "Desktop V2 shell".to_string(),
        state: "available".to_string(),
        required: true,
        detail: "Thin shell is installed and can run without engine components.".to_string(),
        remediation_codes: Vec::new(),
    }
}

fn boot_state_for_activation(activation: &ActivationMetadataInspection) -> ShellBootState {
    let shell_ready = transition_boot_state(ShellBootState::Starting, BootEvent::ShellReady);
    match activation.status.as_str() {
        "missing" => transition_boot_state(shell_ready, BootEvent::ComponentMissing),
        "available" if activation.component_id.as_deref() == Some("aive-engine") => {
            transition_boot_state(shell_ready, BootEvent::ComponentAvailable)
        }
        _ => transition_boot_state(shell_ready, BootEvent::ComponentInvalid),
    }
}

fn state_persistence_error(
    paths: &ResolvedDesktopPaths,
    state: &PersistedShellState,
) -> Result<(), String> {
    let state_dir = PathBuf::from(&paths.user_state);
    if !is_same_or_child(&PathBuf::from(&paths.local_app_data_root), &state_dir) {
        return Err("shell state path is outside LocalAppData".to_string());
    }
    fs::create_dir_all(&state_dir)
        .map_err(|error| format!("could not create shell state directory: {error}"))?;
    let state_path = PathBuf::from(&paths.shell_state_file);
    let temp_path = state_path.with_extension("json.part");
    let serialized = serde_json::to_vec_pretty(state)
        .map_err(|error| format!("could not serialize shell state: {error}"))?;
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&temp_path)
        .map_err(|error| format!("could not open shell state staging file: {error}"))?;
    file.write_all(&serialized)
        .map_err(|error| format!("could not write shell state: {error}"))?;
    file.sync_all()
        .map_err(|error| format!("could not flush shell state: {error}"))?;
    if state_path.exists() {
        fs::remove_file(&state_path)
            .map_err(|error| format!("could not replace shell state: {error}"))?;
    }
    fs::rename(&temp_path, &state_path)
        .map_err(|error| format!("could not commit shell state: {error}"))?;
    Ok(())
}

fn remediation_for_boot_state(state: &ShellBootState) -> Vec<ShellRemediation> {
    match state {
        ShellBootState::SetupRequired => vec![ShellRemediation {
            code: "SETUP_REQUIRED".to_string(),
            title: "Install the core engine".to_string(),
            action: "Open Setup Center".to_string(),
        }],
        ShellBootState::RecoverableError => vec![ShellRemediation {
            code: "RECOVERABLE_SHELL_ERROR".to_string(),
            title: "Review Desktop Diagnostics".to_string(),
            action: "Generate a redacted diagnostic snapshot".to_string(),
        }],
        ShellBootState::EngineAvailable => vec![ShellRemediation {
            code: "ENGINE_NOT_RUNNING".to_string(),
            title: "Wait for the engine supervisor".to_string(),
            action: "Engine-dependent views remain gated in Phase 2".to_string(),
        }],
        ShellBootState::Starting | ShellBootState::ShellReady => Vec::new(),
    }
}

fn technical_detail_list(
    activation: &ActivationMetadataInspectionInternal,
    persistence_error: Option<&str>,
) -> Vec<String> {
    let mut details = Vec::new();
    if let Some(detail) = &activation.technical_detail {
        details.push(redact_diagnostic_text(detail));
    }
    if let Some(detail) = persistence_error {
        details.push(redact_diagnostic_text(detail));
    }
    details
}

#[tauri::command]
pub fn get_shell_info() -> ShellInfo {
    let paths = resolved_paths();
    shell_info(&paths)
}

#[tauri::command]
pub fn get_canonical_paths() -> ResolvedDesktopPaths {
    resolved_paths()
}

#[tauri::command]
pub fn inspect_activation_metadata() -> ActivationMetadataInspection {
    let paths = resolved_paths();
    inspect_activation_metadata_internal(&paths).public
}

#[tauri::command]
pub fn get_safe_log_directory() -> SafeLogDirectoryResult {
    let paths = resolved_paths();
    let log_path = PathBuf::from(&paths.user_logs);
    let local_app_data = PathBuf::from(&paths.local_app_data_root);
    if !is_same_or_child(&local_app_data, &log_path) {
        return SafeLogDirectoryResult {
            available: false,
            path: log_path.to_string_lossy().to_string(),
            created: false,
            detail: "The resolved log directory is outside the authorized LocalAppData root."
                .to_string(),
            remediation_codes: vec!["STORAGE_NOT_WRITABLE".to_string()],
        };
    }

    let existed = log_path.exists();
    match fs::create_dir_all(&log_path) {
        Ok(()) => SafeLogDirectoryResult {
            available: true,
            path: log_path.to_string_lossy().to_string(),
            created: !existed,
            detail: "Redacted shell and diagnostic logs may be written here.".to_string(),
            remediation_codes: Vec::new(),
        },
        Err(_) => SafeLogDirectoryResult {
            available: false,
            path: log_path.to_string_lossy().to_string(),
            created: false,
            detail: "The per-user log directory could not be prepared. Open Diagnostics after correcting storage permissions.".to_string(),
            remediation_codes: vec!["STORAGE_NOT_WRITABLE".to_string()],
        },
    }
}

#[tauri::command]
pub fn desktop_v2_bootstrap() -> DesktopV2BootstrapResult {
    let paths = resolved_paths();
    let info = shell_info(&paths);
    let activation = inspect_activation_metadata_internal(&paths);
    let mut boot_state = boot_state_for_activation(&activation.public);
    let mut engine_ready = false;
    let mut persistence_error = None;
    let persisted = PersistedShellState {
        schema_version: SHELL_STATE_VERSION.to_string(),
        boot_state: boot_state.clone(),
        engine_ready,
        updated_at_epoch_ms: now_epoch_ms(),
    };
    if let Err(error) = state_persistence_error(&paths, &persisted) {
        persistence_error = Some(error);
        boot_state = ShellBootState::RecoverableError;
        engine_ready = false;
    }

    let mut remediation = remediation_for_boot_state(&boot_state);
    let mut error = None;
    if let Some(detail) = &persistence_error {
        remediation.push(ShellRemediation {
            code: "STORAGE_NOT_WRITABLE".to_string(),
            title: "Repair per-user storage access".to_string(),
            action: "Check LocalAppData permissions and generate Diagnostics".to_string(),
        });
        error = Some(ShellBootstrapError {
            code: "SHELL_STATE_PERSIST_FAILED".to_string(),
            message:
                "The shell is running in recovery mode because per-user state could not be saved."
                    .to_string(),
            remediation_codes: vec!["STORAGE_NOT_WRITABLE".to_string()],
        });
        let _ = detail;
    }

    let component_status = vec![
        shell_component_status(),
        core_component_status(&activation.public),
    ];
    if boot_state == ShellBootState::EngineAvailable {
        // Phase 2 can discover an activated component but has no supervisor.
        // Keep all API-dependent views gated until a later ready message.
        engine_ready = false;
    }

    DesktopV2BootstrapResult {
        shell_info: info,
        paths: paths.clone(),
        boot_state,
        engine_ready,
        setup_required: activation.public.status == "missing",
        component_status,
        activation: activation.public,
        remediation,
        persisted_state_path: paths.shell_state_file,
        error,
    }
}

#[tauri::command]
pub fn generate_diagnostic_snapshot() -> DiagnosticSnapshotResult {
    let paths = resolved_paths();
    let log_access = get_safe_log_directory();
    if !log_access.available {
        return DiagnosticSnapshotResult {
            created: false,
            diagnostic_id: format!("diag-{}", now_epoch_ms()),
            path: None,
            detail: log_access.detail,
            remediation_codes: log_access.remediation_codes,
        };
    }

    let activation = inspect_activation_metadata_internal(&paths);
    let boot_state = boot_state_for_activation(&activation.public);
    let snapshot = DiagnosticSnapshot {
        schema_version: DIAGNOSTIC_SNAPSHOT_VERSION.to_string(),
        generated_at_epoch_ms: now_epoch_ms(),
        shell_info: shell_info(&paths),
        boot_state: boot_state.clone(),
        engine_ready: false,
        component_status: vec![
            shell_component_status(),
            core_component_status(&activation.public),
        ],
        activation_status: activation.public.status.clone(),
        activation_detail_code: activation.public.detail_code.clone(),
        storage_layout_version: STORAGE_LAYOUT_VERSION.to_string(),
        technical_details: technical_detail_list(&activation, None),
    };
    let diagnostic_id = format!("diag-{}", snapshot.generated_at_epoch_ms);
    let log_path = PathBuf::from(&paths.user_logs);
    let path = log_path.join(format!("{diagnostic_id}.json"));
    let serialized = match serde_json::to_vec_pretty(&snapshot) {
        Ok(serialized) => serialized,
        Err(_) => {
            return DiagnosticSnapshotResult {
                created: false,
                diagnostic_id,
                path: None,
                detail: "The redacted diagnostic snapshot could not be serialized.".to_string(),
                remediation_codes: vec!["STORAGE_NOT_WRITABLE".to_string()],
            };
        }
    };
    match OpenOptions::new().write(true).create_new(true).open(&path) {
        Ok(mut file) => {
            if file.write_all(&serialized).is_ok() && file.sync_all().is_ok() {
                DiagnosticSnapshotResult {
                    created: true,
                    diagnostic_id,
                    path: Some(path.to_string_lossy().to_string()),
                    detail: "Redacted diagnostics were written to the per-user Logs directory."
                        .to_string(),
                    remediation_codes: Vec::new(),
                }
            } else {
                DiagnosticSnapshotResult {
                    created: false,
                    diagnostic_id,
                    path: None,
                    detail: "The diagnostic snapshot could not be written to the per-user Logs directory.".to_string(),
                    remediation_codes: vec!["STORAGE_NOT_WRITABLE".to_string()],
                }
            }
        }
        Err(_) => DiagnosticSnapshotResult {
            created: false,
            diagnostic_id,
            path: None,
            detail: "The diagnostic snapshot could not be created in the per-user Logs directory."
                .to_string(),
            remediation_codes: vec!["STORAGE_NOT_WRITABLE".to_string()],
        },
    }
}

fn replace_sensitive_value(input: &str, marker: &str) -> String {
    let lower = input.to_ascii_lowercase();
    let marker_lower = marker.to_ascii_lowercase();
    let Some(start) = lower.find(&marker_lower) else {
        return input.to_string();
    };
    let value_start = start + marker.len();
    let value_end = input[value_start..]
        .find(|character: char| character.is_whitespace() || matches!(character, '&' | ';' | ','))
        .map(|offset| value_start + offset)
        .unwrap_or(input.len());
    let mut output = String::with_capacity(input.len());
    output.push_str(&input[..value_start]);
    output.push_str("[REDACTED]");
    output.push_str(&input[value_end..]);
    output
}

pub(crate) fn redact_diagnostic_text(input: &str) -> String {
    let mut value = input
        .chars()
        .take(MAX_DIAGNOSTIC_TEXT_BYTES)
        .collect::<String>();
    for marker in [
        "password=",
        "passwd=",
        "secret=",
        "token=",
        "api_key=",
        "apikey=",
        "authorization=",
    ] {
        value = replace_sensitive_value(&value, marker);
    }
    let lower = value.to_ascii_lowercase();
    if let Some(start) = lower.find("bearer ") {
        let value_start = start + "bearer ".len();
        let value_end = value[value_start..]
            .find(char::is_whitespace)
            .map(|offset| value_start + offset)
            .unwrap_or(value.len());
        value.replace_range(value_start..value_end, "[REDACTED]");
    }
    for prefix in ["sk-", "pk-", "ghp_"] {
        let lower = value.to_ascii_lowercase();
        if let Some(start) = lower.find(prefix) {
            let value_end = value[start..]
                .find(char::is_whitespace)
                .map(|offset| start + offset)
                .unwrap_or(value.len());
            value.replace_range(start..value_end, "[REDACTED_TOKEN]");
        }
    }
    value
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_paths() -> ResolvedDesktopPaths {
        ResolvedDesktopPaths::from_roots(&PathRoots {
            program_files: PathBuf::from(r"C:\Program Files"),
            program_data: PathBuf::from(r"C:\ProgramData"),
            local_app_data: PathBuf::from(r"C:\Users\Test\AppData\Local"),
            user_profile: PathBuf::from(r"C:\Users\Test"),
        })
    }

    #[test]
    fn boot_state_missing_component_requires_setup() {
        let paths = test_paths();
        let activation = inspect_activation_metadata_internal(&paths);
        assert_eq!(activation.public.status, "missing");
        assert_eq!(
            boot_state_for_activation(&activation.public),
            ShellBootState::SetupRequired
        );
        assert_eq!(
            core_component_status(&activation.public).state,
            "not-installed"
        );
    }

    #[test]
    fn boot_state_machine_has_explicit_supervisor_gate() {
        let shell_ready = transition_boot_state(ShellBootState::Starting, BootEvent::ShellReady);
        assert_eq!(shell_ready, ShellBootState::ShellReady);
        assert_eq!(
            transition_boot_state(shell_ready.clone(), BootEvent::ComponentMissing),
            ShellBootState::SetupRequired
        );
        assert_eq!(
            transition_boot_state(shell_ready.clone(), BootEvent::ComponentAvailable),
            ShellBootState::EngineAvailable
        );
        assert_eq!(
            transition_boot_state(shell_ready, BootEvent::ComponentInvalid),
            ShellBootState::RecoverableError
        );
        assert_eq!(
            transition_boot_state(ShellBootState::EngineAvailable, BootEvent::SupervisorReady),
            ShellBootState::EngineAvailable
        );
    }

    #[test]
    fn path_invariants_keep_runtime_writes_out_of_program_files() {
        let paths = test_paths();
        assert!(paths.path_invariants_hold());
        assert!(paths.shell_install.starts_with(r"C:\Program Files"));
        assert!(paths.user_state.starts_with(r"C:\Users\Test\AppData\Local"));
        assert!(!paths.user_state.starts_with(&paths.program_files_root));
    }

    #[test]
    fn invalid_activation_metadata_is_recoverable_without_raw_error() {
        let inspection = invalid_activation(
            r"C:\ProgramData\AI Video Editor\Activation\active.json".to_string(),
            "metadata is malformed",
        );
        assert_eq!(inspection.public.status, "invalid");
        assert!(inspection.public.detail.contains("Diagnostics"));
        assert!(!inspection.public.detail.contains("metadata is malformed"));
        assert!(inspection
            .technical_detail
            .unwrap()
            .contains("metadata is malformed"));
    }

    #[test]
    fn diagnostics_redact_credentials_and_tokens() {
        let redacted =
            redact_diagnostic_text("password=secret token=abc Bearer very-secret sk-short");
        assert!(!redacted.contains("secret"));
        assert!(!redacted.contains("very-secret"));
        assert!(!redacted.contains("sk-short"));
        assert!(redacted.contains("[REDACTED]"));
    }
}
