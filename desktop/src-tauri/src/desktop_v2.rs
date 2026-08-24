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
/// The per-machine installer identity. This is deliberately distinct from
/// the historical user-data directory so an upgrade cannot move projects or
/// settings merely because the Program Files display name was corrected.
pub const PROGRAM_FILES_DIRECTORY: &str = "AI Video Editor Desktop V2";
pub const USER_DATA_DIRECTORY: &str = "AI Video Editor";
pub const SHELL_STATE_VERSION: &str = "desktop.shell-state.v1";
pub const DIAGNOSTIC_SNAPSHOT_VERSION: &str = "desktop.diagnostics.v1";
const ACTIVE_METADATA_FILENAME: &str = "aive-engine.json";
const MAX_ACTIVATION_METADATA_BYTES: usize = 128 * 1024;
const MAX_DIAGNOSTIC_TEXT_BYTES: usize = 2 * 1024;
const MAX_SINGLE_INSTANCE_ARGUMENTS: usize = 32;
const MAX_SINGLE_INSTANCE_ARGUMENT_BYTES: usize = 1024;
const MAX_WEBVIEW2_VERSION_DIRECTORIES: usize = 64;
const MIN_WEBVIEW2_EXECUTABLE_BYTES: u64 = 1024 * 1024;
const MAX_WEBVIEW2_EXECUTABLE_BYTES: u64 = 1024 * 1024 * 1024;
pub const WEBVIEW2_RUNTIME_SCHEMA: &str = "desktop.webview2-runtime.v1";
pub const WEBVIEW2_INSTALL_POLICY: &str =
    "detect-before-launch; Evergreen bootstrapper online or Standalone Installer offline; no-silent-download";
const WEBVIEW2_CLIENT_KEY: &str =
    r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4A67-A3F6-CFC0C4E1D5A1}";

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
pub struct ForwardedLaunchArgs {
    pub catalog_path: Option<String>,
    pub handoff_root: Option<String>,
    pub cwd: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WebView2RuntimeStatus {
    pub schema_version: String,
    pub available: bool,
    pub version: Option<String>,
    pub source: String,
    pub install_policy: String,
    pub detail: String,
    pub remediation_codes: Vec<String>,
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
        let user_root = roots.local_app_data.join(USER_DATA_DIRECTORY);
        let shell_install = roots
            .program_files
            .join(PROGRAM_FILES_DIRECTORY)
            .join("Shell");
        let shared_components = roots
            .program_data
            .join(USER_DATA_DIRECTORY)
            .join("Components");
        let activation_metadata = roots
            .program_data
            .join(USER_DATA_DIRECTORY)
            .join("Activation");
        let download_staging = roots
            .program_data
            .join(USER_DATA_DIRECTORY)
            .join("Downloads")
            .join("Staging");
        let user_config = user_root.join("Config");
        let user_cache = user_root.join("Cache");
        let user_logs = user_root.join("Logs");
        let user_state = user_root.join("State");
        let projects = roots
            .user_profile
            .join("Documents")
            .join(USER_DATA_DIRECTORY)
            .join("Projects");
        let exports = roots
            .user_profile
            .join("Documents")
            .join(USER_DATA_DIRECTORY)
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

#[cfg(windows)]
fn query_webview2_registry_version(
    root: windows_sys::Win32::System::Registry::HKEY,
    view: u32,
) -> Option<String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::System::Registry::{
        RegCloseKey, RegOpenKeyExW, RegQueryValueExW, HKEY, KEY_READ,
    };

    let key_name: Vec<u16> = std::ffi::OsStr::new(WEBVIEW2_CLIENT_KEY)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let value_name: Vec<u16> = std::ffi::OsStr::new("pv")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut key: HKEY = std::ptr::null_mut();
    let opened = unsafe { RegOpenKeyExW(root, key_name.as_ptr(), 0, KEY_READ | view, &mut key) };
    if opened != 0 {
        return None;
    }

    let mut value_type = 0u32;
    let mut byte_count = 0u32;
    let sized = unsafe {
        RegQueryValueExW(
            key,
            value_name.as_ptr(),
            std::ptr::null(),
            &mut value_type,
            std::ptr::null_mut(),
            &mut byte_count,
        )
    };
    if sized != 0 || byte_count == 0 || byte_count > 4096 {
        unsafe {
            RegCloseKey(key);
        }
        return None;
    }

    let mut value = vec![0u16; (byte_count as usize / 2).saturating_add(1)];
    let mut actual_bytes = byte_count;
    let queried = unsafe {
        RegQueryValueExW(
            key,
            value_name.as_ptr(),
            std::ptr::null(),
            &mut value_type,
            value.as_mut_ptr().cast::<u8>(),
            &mut actual_bytes,
        )
    };
    unsafe {
        RegCloseKey(key);
    }
    if queried != 0 {
        return None;
    }
    let version = String::from_utf16_lossy(&value)
        .trim_matches('\0')
        .trim()
        .to_string();
    (!version.is_empty()).then_some(version)
}

fn parse_four_part_version(value: &str) -> Option<[u16; 4]> {
    let mut parts = value.split('.');
    let parsed = [
        parts.next()?.parse().ok()?,
        parts.next()?.parse().ok()?,
        parts.next()?.parse().ok()?,
        parts.next()?.parse().ok()?,
    ];
    if parts.next().is_some() {
        return None;
    }
    Some(parsed)
}

fn format_four_part_version(version: [u16; 4]) -> String {
    format!(
        "{}.{}.{}.{}",
        version[0], version[1], version[2], version[3]
    )
}

#[cfg(windows)]
fn webview2_filesystem_roots() -> Vec<PathBuf> {
    ["ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"]
        .into_iter()
        .filter_map(env::var_os)
        .map(|root| {
            PathBuf::from(root)
                .join("Microsoft")
                .join("EdgeWebView")
                .join("Application")
        })
        .collect()
}

#[cfg(windows)]
fn windows_pe_product_version(path: &Path) -> Option<String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileVersionInfoSizeW, GetFileVersionInfoW, VerQueryValueW, VS_FIXEDFILEINFO,
    };

    let metadata = fs::metadata(path).ok()?;
    let length = metadata.len();
    if !(MIN_WEBVIEW2_EXECUTABLE_BYTES..=MAX_WEBVIEW2_EXECUTABLE_BYTES).contains(&length) {
        return None;
    }
    let file_name: Vec<u16> = path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let info_size = unsafe { GetFileVersionInfoSizeW(file_name.as_ptr(), std::ptr::null_mut()) };
    if info_size == 0 || info_size > 1024 * 1024 {
        return None;
    }
    let mut info = vec![0u8; info_size as usize];
    let loaded =
        unsafe { GetFileVersionInfoW(file_name.as_ptr(), 0, info_size, info.as_mut_ptr().cast()) };
    if loaded == 0 {
        return None;
    }

    let sub_block: Vec<u16> = std::ffi::OsStr::new("\\")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut value_ptr: *mut std::ffi::c_void = std::ptr::null_mut();
    let mut value_length = 0u32;
    let queried = unsafe {
        VerQueryValueW(
            info.as_ptr().cast(),
            sub_block.as_ptr(),
            &mut value_ptr,
            &mut value_length,
        )
    };
    if queried == 0
        || value_ptr.is_null()
        || value_length < std::mem::size_of::<VS_FIXEDFILEINFO>() as u32
    {
        return None;
    }
    let fixed = unsafe { &*(value_ptr.cast::<VS_FIXEDFILEINFO>()) };
    if fixed.dwSignature != 0xFEEF04BD {
        return None;
    }
    let version = [
        (fixed.dwProductVersionMS >> 16) as u16,
        (fixed.dwProductVersionMS & 0xFFFF) as u16,
        (fixed.dwProductVersionLS >> 16) as u16,
        (fixed.dwProductVersionLS & 0xFFFF) as u16,
    ];
    (version != [0, 0, 0, 0]).then(|| format_four_part_version(version))
}

#[cfg(windows)]
fn detect_webview2_filesystem() -> Option<(String, String)> {
    let mut version_directories = Vec::new();
    for root in webview2_filesystem_roots() {
        let Ok(entries) = fs::read_dir(&root) else {
            continue;
        };
        for entry in entries.take(MAX_WEBVIEW2_VERSION_DIRECTORIES) {
            let Ok(entry) = entry else {
                continue;
            };
            let Ok(file_type) = entry.file_type() else {
                continue;
            };
            if !file_type.is_dir() {
                continue;
            }
            let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
                continue;
            };
            let Some(version) = parse_four_part_version(&name) else {
                continue;
            };
            version_directories.push((version, entry.path(), root.clone()));
        }
    }
    version_directories.sort_by(|left, right| right.0.cmp(&left.0));

    for (directory_version, directory, root) in version_directories {
        let executable = directory.join("msedgewebview2.exe");
        let Ok(canonical_root) = fs::canonicalize(root) else {
            continue;
        };
        let Ok(canonical_executable) = fs::canonicalize(&executable) else {
            continue;
        };
        if !is_same_or_child(&canonical_root, &canonical_executable)
            || canonical_executable
                .file_name()
                .and_then(|name| name.to_str())
                != Some("msedgewebview2.exe")
        {
            continue;
        }
        let Some(file_version) = windows_pe_product_version(&canonical_executable) else {
            continue;
        };
        let Some(file_version_parts) = parse_four_part_version(&file_version) else {
            continue;
        };
        if file_version_parts != directory_version {
            continue;
        }
        return Some(("evergreen-filesystem".to_string(), file_version));
    }
    None
}

#[cfg(windows)]
fn detect_webview2_runtime() -> Option<(String, String)> {
    use windows_sys::Win32::System::Registry::{
        HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, KEY_WOW64_32KEY, KEY_WOW64_64KEY,
    };

    if let Some(folder) = env::var_os("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER") {
        let folder = PathBuf::from(folder);
        if let Some(version) = windows_pe_product_version(&folder.join("msedgewebview2.exe")) {
            return Some(("fixed-runtime".to_string(), version));
        }
    }
    for (source, root) in [
        ("evergreen-user", HKEY_CURRENT_USER),
        ("evergreen-machine", HKEY_LOCAL_MACHINE),
    ] {
        for view in [KEY_WOW64_64KEY, KEY_WOW64_32KEY] {
            if let Some(version) = query_webview2_registry_version(root, view) {
                return Some((source.to_string(), version));
            }
        }
    }
    detect_webview2_filesystem()
}

#[cfg(not(windows))]
fn detect_webview2_runtime() -> Option<(String, String)> {
    Some((
        "non-windows-development-host".to_string(),
        "development-only".to_string(),
    ))
}

pub fn webview2_runtime_status() -> WebView2RuntimeStatus {
    match detect_webview2_runtime() {
        Some((source, version)) => WebView2RuntimeStatus {
            schema_version: WEBVIEW2_RUNTIME_SCHEMA.to_string(),
            available: true,
            version: Some(version),
            source,
            install_policy: WEBVIEW2_INSTALL_POLICY.to_string(),
            detail: "A WebView2 runtime was detected before shell launch; the shell will not download one silently.".to_string(),
            remediation_codes: Vec::new(),
        },
        None => WebView2RuntimeStatus {
            schema_version: WEBVIEW2_RUNTIME_SCHEMA.to_string(),
            available: false,
            version: None,
            source: "not-detected".to_string(),
            install_policy: WEBVIEW2_INSTALL_POLICY.to_string(),
            detail: "Microsoft WebView2 Runtime is required before Desktop V2 can launch. Install the approved Evergreen bootstrapper while online or the approved Standalone Installer while offline; no runtime download is attempted by this shell.".to_string(),
            remediation_codes: vec!["WEBVIEW2_RUNTIME_REQUIRED".to_string()],
        },
    }
}

#[tauri::command]
pub fn get_webview2_runtime_status() -> WebView2RuntimeStatus {
    webview2_runtime_status()
}

fn resolve_forwarded_path(value: &str, cwd: &Path) -> Option<PathBuf> {
    if value.is_empty() || value.len() > MAX_SINGLE_INSTANCE_ARGUMENT_BYTES {
        return None;
    }
    let candidate = PathBuf::from(value);
    let candidate = if candidate.is_absolute() {
        candidate
    } else {
        cwd.join(candidate)
    };
    fs::canonicalize(candidate).ok()
}

fn approved_catalog_path(value: &str, cwd: &Path) -> Option<PathBuf> {
    let path = resolve_forwarded_path(value, cwd)?;
    if !path.is_file()
        || !path
            .extension()
            .and_then(|extension| extension.to_str())
            .map(|extension| extension.eq_ignore_ascii_case("json"))
            .unwrap_or(false)
        || path
            .parent()
            .and_then(|parent| parent.file_name())
            .and_then(|name| name.to_str())
            .map(|name| !name.eq_ignore_ascii_case("Catalog"))
            .unwrap_or(true)
    {
        return None;
    }
    let root = path.parent()?.parent()?;
    if root.join("Components").is_dir() {
        Some(path)
    } else {
        None
    }
}

fn approved_handoff_root(value: &str, cwd: &Path) -> Option<PathBuf> {
    let path = resolve_forwarded_path(value, cwd)?;
    if !path.is_dir() || !path.join("Catalog").is_dir() || !path.join("Components").is_dir() {
        return None;
    }
    Some(path)
}

/// Return only the bounded, explicitly supported handoff arguments from a
/// second process. The single-instance callback forwards these values to the
/// UI, where the same catalog signature, manifest, hash, and containment
/// checks still run before import. Arbitrary command-line values are ignored.
pub fn approved_single_instance_args(args: &[String], cwd: &Path) -> Option<ForwardedLaunchArgs> {
    if args.len() > MAX_SINGLE_INSTANCE_ARGUMENTS {
        return None;
    }
    let mut catalog_path = None;
    let mut handoff_root = None;
    let mut index = 0;
    while index < args.len() {
        let argument = &args[index];
        if argument.len() > MAX_SINGLE_INSTANCE_ARGUMENT_BYTES {
            index += 1;
            continue;
        }
        let (key, inline_value) = argument
            .split_once('=')
            .map_or((argument.as_str(), None), |(key, value)| (key, Some(value)));
        let value = if let Some(value) = inline_value {
            Some(value.to_string())
        } else if matches!(key, "--catalog" | "--handoff") {
            index += 1;
            args.get(index).cloned()
        } else {
            None
        };
        match key {
            "--catalog" => {
                if let Some(value) = value
                    .as_deref()
                    .and_then(|value| approved_catalog_path(value, cwd))
                {
                    catalog_path = Some(value.to_string_lossy().to_string());
                }
            }
            "--handoff" => {
                if let Some(value) = value
                    .as_deref()
                    .and_then(|value| approved_handoff_root(value, cwd))
                {
                    handoff_root = Some(value.to_string_lossy().to_string());
                }
            }
            _ => {}
        }
        index += 1;
    }
    if catalog_path.is_none() && handoff_root.is_none() {
        return None;
    }
    Some(ForwardedLaunchArgs {
        catalog_path,
        handoff_root,
        cwd: cwd.to_string_lossy().to_string(),
    })
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
        assert_eq!(
            paths.shell_install,
            r"C:\Program Files\AI Video Editor Desktop V2\Shell"
        );
        assert!(paths.user_state.starts_with(r"C:\Users\Test\AppData\Local"));
        assert!(!paths.user_state.starts_with(&paths.program_files_root));
    }

    #[test]
    fn single_instance_forwards_only_approved_catalog_and_handoff_arguments() {
        let root = env::temp_dir().join(format!(
            "aive-single-instance-{}-{}",
            std::process::id(),
            now_epoch_ms()
        ));
        let catalog = root.join("Catalog").join("offline-catalog.json");
        fs::create_dir_all(catalog.parent().expect("catalog parent")).expect("catalog directory");
        fs::create_dir_all(root.join("Components")).expect("components directory");
        fs::write(&catalog, b"{}").expect("catalog file");

        let forwarded = approved_single_instance_args(
            &[
                "AI Video Editor Desktop V2.exe".to_string(),
                "--catalog".to_string(),
                catalog.to_string_lossy().to_string(),
                "--token=should-not-forward".to_string(),
            ],
            Path::new(r"C:\Users\Test"),
        )
        .expect("approved catalog argument");
        assert_eq!(
            forwarded.catalog_path,
            Some(
                fs::canonicalize(&catalog)
                    .unwrap()
                    .to_string_lossy()
                    .to_string()
            )
        );
        assert!(forwarded.handoff_root.is_none());

        let rejected = approved_single_instance_args(
            &[
                "--catalog".to_string(),
                root.join("notes.txt").to_string_lossy().to_string(),
            ],
            Path::new(r"C:\Users\Test"),
        );
        assert!(rejected.is_none());
        let _ = fs::remove_dir_all(root);
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

    #[test]
    fn webview2_file_version_fallback_requires_exact_four_numeric_parts() {
        assert_eq!(
            parse_four_part_version("151.0.4129.101"),
            Some([151, 0, 4129, 101])
        );
        assert_eq!(
            format_four_part_version([151, 0, 4129, 101]),
            "151.0.4129.101"
        );
        assert!(parse_four_part_version("151.0.4129").is_none());
        assert!(parse_four_part_version("151.0.4129.101.extra").is_none());
        assert!(parse_four_part_version("151.0.4129.beta").is_none());
        assert!(parse_four_part_version("..\\msedgewebview2.exe").is_none());
    }
}
