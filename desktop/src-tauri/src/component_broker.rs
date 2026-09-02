//! Bounded elevated helper for the machine-scoped component perimeter.
//!
//! The shell stays unelevated.  Only the five state-changing operations below
//! can cross the UAC boundary, and the helper re-resolves the canonical
//! ProgramData perimeter before it touches anything.  This is intentionally a
//! small native helper mode in the signed shell executable rather than a
//! general-purpose command runner or an AppData/Docker fallback.

use crate::component_manager::{ComponentError, ComponentManager, ManagerResult, SourcePolicy};
use crate::desktop_v2::{get_canonical_paths, USER_DATA_DIRECTORY};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::Value;
use std::env;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

pub const BROKER_SCHEMA: &str = "desktop.component-broker.v1";
pub const BROKER_MARKER_FILE: &str = "component-broker.json";
pub const BROKER_REQUEST_DIRECTORY: &str = "Broker\\Requests";
const MAX_REQUEST_BYTES: usize = 32 * 1024;
const MAX_RESPONSE_BYTES: usize = 256 * 1024;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum BrokerOperation {
    Activate,
    Reconcile,
    Repair,
    Rollback,
    Uninstall,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct BrokerRequest {
    pub schema_version: String,
    pub request_id: String,
    pub operation: BrokerOperation,
    pub component_id: Option<String>,
    pub component_version: Option<String>,
    pub operation_id: Option<String>,
    pub allow_offline_sources: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct BrokerResponse {
    schema_version: String,
    request_id: String,
    ok: bool,
    code: Option<String>,
    message: Option<String>,
    payload: Option<Value>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BrokerHealth {
    pub schema_version: String,
    pub installed: bool,
    pub marker_valid: bool,
    pub elevated: bool,
    pub ready: bool,
    pub status: String,
    pub detail: String,
}

#[tauri::command]
pub fn component_broker_health() -> BrokerHealth {
    broker_health()
}

pub fn should_delegate() -> bool {
    should_delegate_for(&machine_root())
}

/// Return whether a machine mutation must cross the installer-owned UAC
/// boundary.  Test/redirected managers deliberately stay local; only the
/// canonical ProgramData perimeter is eligible for the installed helper.
pub fn should_delegate_for(candidate_root: &Path) -> bool {
    #[cfg(windows)]
    {
        !is_broker_process()
            && !is_process_elevated()
            && normalize_path(candidate_root) == normalize_path(&machine_root())
    }
    #[cfg(not(windows))]
    {
        let _ = candidate_root;
        false
    }
}

pub fn broker_health() -> BrokerHealth {
    let marker = broker_marker_path();
    let installed = broker_executable_path().is_some();
    let marker_valid = marker
        .as_ref()
        .map(|path| validate_marker(path).is_ok())
        .unwrap_or(false);
    let elevated = is_process_elevated();
    let ready = marker_valid && (elevated || installed);
    BrokerHealth {
        schema_version: BROKER_SCHEMA.to_string(),
        installed,
        marker_valid,
        elevated,
        ready,
        status: if ready {
            "ready".to_string()
        } else if !installed {
            "not-installed".to_string()
        } else {
            "repair-required".to_string()
        },
        detail: if ready {
            "The bounded component helper is installed and can be invoked for machine operations."
                .to_string()
        } else {
            "The per-machine helper is missing or its signed installer marker is invalid."
                .to_string()
        },
    }
}

pub fn delegate<T>(mut request: BrokerRequest) -> ManagerResult<T>
where
    T: DeserializeOwned,
{
    validate_request(&request)?;
    if is_broker_process() {
        return Err(ComponentError::new(
            "BROKER_REENTRY_BLOCKED",
            "The elevated component helper cannot delegate back to itself.",
            false,
        ));
    }

    request.request_id = safe_request_id(&request.request_id)?;
    let requests = broker_request_directory();
    fs::create_dir_all(&requests).map_err(|error| {
        ComponentError::new(
            "ELEVATION_REQUIRED",
            format!("The per-machine repair helper is not writable: {error}"),
            true,
        )
    })?;
    let request_path = requests.join(format!("{}.request.json", request.request_id));
    let response_path = response_path_for(&request_path);
    ensure_child_path(&requests, &request_path)?;
    ensure_child_path(&requests, &response_path)?;
    let _ = fs::remove_file(&response_path);
    atomic_write_json(&request_path, &request).map_err(|error| {
        ComponentError::new(
            "ELEVATION_REQUIRED",
            format!("The component repair request could not be prepared: {error}"),
            true,
        )
    })?;

    #[cfg(windows)]
    let launch_error = launch_elevated_helper(&request_path);
    #[cfg(not(windows))]
    let launch_error: Result<(), String> = Err(
        "The bounded component helper is only available from the Windows installer build."
            .to_string(),
    );
    if let Err(error) = launch_error {
        let _ = fs::remove_file(&request_path);
        return Err(ComponentError::new(
            "ELEVATION_REQUIRED",
            format!("Approve the bounded per-machine repair request in Windows UAC: {error}"),
            true,
        ));
    }

    let response_bytes = fs::read(&response_path).map_err(|error| {
        ComponentError::new(
            "ELEVATION_REQUIRED",
            format!("The elevated component helper did not return a response: {error}"),
            true,
        )
    })?;
    if response_bytes.len() > MAX_RESPONSE_BYTES {
        return Err(ComponentError::new(
            "BROKER_RESPONSE_INVALID",
            "The elevated component helper response exceeded its bounded size.",
            false,
        ));
    }
    let response: BrokerResponse = serde_json::from_slice(&response_bytes).map_err(|error| {
        ComponentError::new(
            "BROKER_RESPONSE_INVALID",
            format!("The elevated component helper response was invalid: {error}"),
            false,
        )
    })?;
    let _ = fs::remove_file(&request_path);
    let _ = fs::remove_file(&response_path);
    if response.schema_version != BROKER_SCHEMA || response.request_id != request.request_id {
        return Err(ComponentError::new(
            "BROKER_RESPONSE_INVALID",
            "The elevated component helper response identity did not match the request.",
            false,
        ));
    }
    if !response.ok {
        return Err(ComponentError::new(
            response
                .code
                .as_deref()
                .unwrap_or("ELEVATED_OPERATION_FAILED"),
            response
                .message
                .unwrap_or_else(|| "The elevated component operation failed.".to_string()),
            true,
        ));
    }
    let payload = response.payload.ok_or_else(|| {
        ComponentError::new(
            "BROKER_RESPONSE_INVALID",
            "The elevated component helper returned no operation result.",
            false,
        )
    })?;
    serde_json::from_value(payload).map_err(|error| {
        ComponentError::new(
            "BROKER_RESPONSE_INVALID",
            format!("The elevated component result was invalid: {error}"),
            false,
        )
    })
}

pub fn run_broker_cli() -> bool {
    let mut args = env::args_os().skip(1);
    if args.next().as_deref() != Some(std::ffi::OsStr::new("--component-broker")) {
        return false;
    }
    let Some(request_path) = args.next() else {
        eprintln!("component broker requires one request path");
        std::process::exit(2);
    };
    if args.next().is_some() {
        eprintln!("component broker accepts no extra arguments");
        std::process::exit(2);
    }
    let code = match process_request(Path::new(&request_path)) {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("component broker failed: {}", error.message);
            1
        }
    };
    std::process::exit(code);
}

fn process_request(request_path: &Path) -> ManagerResult<()> {
    let request_root = broker_request_directory();
    ensure_child_path(&request_root, request_path)?;
    if request_path.extension().and_then(|value| value.to_str()) != Some("json")
        || !request_path
            .file_name()
            .and_then(|value| value.to_str())
            .is_some_and(|value| value.ends_with(".request.json"))
    {
        return Err(ComponentError::new(
            "BROKER_REQUEST_INVALID",
            "The helper accepts only request files in its bounded request directory.",
            false,
        ));
    }
    let bytes = fs::read(request_path).map_err(|error| storage_error(request_path, error))?;
    if bytes.len() > MAX_REQUEST_BYTES {
        return Err(ComponentError::new(
            "BROKER_REQUEST_INVALID",
            "The helper request exceeded its bounded size.",
            false,
        ));
    }
    let request: BrokerRequest = serde_json::from_slice(&bytes).map_err(|error| {
        ComponentError::new(
            "BROKER_REQUEST_INVALID",
            format!("The helper request was invalid: {error}"),
            false,
        )
    })?;
    validate_request(&request)?;
    if !is_process_elevated() && cfg!(windows) {
        return write_error_response(
            request_path,
            &request,
            ComponentError::new(
                "ELEVATION_REQUIRED",
                "The bounded helper was not elevated by Windows UAC.",
                true,
            ),
        );
    }
    let paths = get_canonical_paths();
    let machine_root = PathBuf::from(paths.program_data_root).join(USER_DATA_DIRECTORY);
    let manager = ComponentManager::new(machine_root);
    let result: ManagerResult<Value> = match request.operation {
        BrokerOperation::Activate => {
            let component_id = required_field(request.component_id.as_deref(), "componentId")?;
            let component_version =
                required_field(request.component_version.as_deref(), "componentVersion")?;
            let result = manager.activate_direct(
                component_id,
                component_version,
                policy_from_request(&request),
                request.operation_id.clone(),
                None,
            )?;
            serde_json::to_value(result).map_err(|error| {
                ComponentError::new("BROKER_RESPONSE_INVALID", error.to_string(), false)
            })
        }
        BrokerOperation::Reconcile => {
            let result = manager.recover_direct()?;
            serde_json::to_value(result).map_err(|error| {
                ComponentError::new("BROKER_RESPONSE_INVALID", error.to_string(), false)
            })
        }
        BrokerOperation::Repair => {
            let component_id = required_field(request.component_id.as_deref(), "componentId")?;
            let result =
                manager.repair_direct(component_id, policy_from_request(&request), None)?;
            serde_json::to_value(result).map_err(|error| {
                ComponentError::new("BROKER_RESPONSE_INVALID", error.to_string(), false)
            })
        }
        BrokerOperation::Rollback => {
            let component_id = required_field(request.component_id.as_deref(), "componentId")?;
            let result =
                manager.rollback_direct(component_id, policy_from_request(&request), None)?;
            serde_json::to_value(result).map_err(|error| {
                ComponentError::new("BROKER_RESPONSE_INVALID", error.to_string(), false)
            })
        }
        BrokerOperation::Uninstall => {
            let component_id = required_field(request.component_id.as_deref(), "componentId")?;
            let result = manager.uninstall_direct(component_id)?;
            serde_json::to_value(result).map_err(|error| {
                ComponentError::new("BROKER_RESPONSE_INVALID", error.to_string(), false)
            })
        }
    };
    match result {
        Ok(payload) => write_response(request_path, &request, true, None, None, Some(payload)),
        Err(error) => write_error_response(request_path, &request, error),
    }
}

fn write_error_response(
    request_path: &Path,
    request: &BrokerRequest,
    error: ComponentError,
) -> ManagerResult<()> {
    write_response(
        request_path,
        request,
        false,
        Some(error.code),
        Some(error.message),
        None,
    )
}

fn write_response(
    request_path: &Path,
    request: &BrokerRequest,
    ok: bool,
    code: Option<String>,
    message: Option<String>,
    payload: Option<Value>,
) -> ManagerResult<()> {
    atomic_write_json(
        &response_path_for(request_path),
        &BrokerResponse {
            schema_version: BROKER_SCHEMA.to_string(),
            request_id: request.request_id.clone(),
            ok,
            code,
            message,
            payload,
        },
    )
    .map_err(|error| storage_error(&response_path_for(request_path), error))
}

fn validate_request(request: &BrokerRequest) -> ManagerResult<()> {
    if request.schema_version != BROKER_SCHEMA {
        return Err(ComponentError::new(
            "BROKER_REQUEST_INVALID",
            "The helper request schema is not supported.",
            false,
        ));
    }
    safe_request_id(&request.request_id)?;
    if let Some(component_id) = &request.component_id {
        validate_safe_identifier(component_id, "component id")?;
    }
    if let Some(component_version) = &request.component_version {
        if component_version.len() > 64
            || component_version.contains(['\\', '/', ':'])
            || semver::Version::parse(component_version).is_err()
        {
            return Err(ComponentError::new(
                "BROKER_REQUEST_INVALID",
                "The helper request contains an invalid component version.",
                false,
            ));
        }
    }
    if let Some(operation_id) = &request.operation_id {
        safe_request_id(operation_id)?;
    }
    match request.operation {
        BrokerOperation::Activate => {
            if request.component_id.is_none() || request.component_version.is_none() {
                return Err(ComponentError::new(
                    "BROKER_REQUEST_INVALID",
                    "Activation requires a component id and version.",
                    false,
                ));
            }
        }
        BrokerOperation::Repair | BrokerOperation::Rollback | BrokerOperation::Uninstall => {
            if request.component_id.is_none() {
                return Err(ComponentError::new(
                    "BROKER_REQUEST_INVALID",
                    "This helper operation requires a component id.",
                    false,
                ));
            }
        }
        BrokerOperation::Reconcile => {}
    }
    Ok(())
}

fn policy_from_request(request: &BrokerRequest) -> SourcePolicy {
    match request.operation {
        // These operations only inspect immutable active/retained payloads.
        // They must remain usable when the original catalog was imported
        // offline, without turning that historical URL into a prerequisite.
        BrokerOperation::Repair | BrokerOperation::Rollback => SourcePolicy::INSTALLED_RUNTIME,
        BrokerOperation::Activate if request.allow_offline_sources => SourcePolicy::OFFLINE_IMPORT,
        _ => SourcePolicy::PRODUCTION,
    }
}

fn required_field<'a>(value: Option<&'a str>, name: &str) -> ManagerResult<&'a str> {
    value.ok_or_else(|| {
        ComponentError::new(
            "BROKER_REQUEST_INVALID",
            format!("The helper request is missing {name}."),
            false,
        )
    })
}

fn validate_safe_identifier(value: &str, label: &str) -> ManagerResult<()> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "-_ .".contains(character))
    {
        return Err(ComponentError::new(
            "BROKER_REQUEST_INVALID",
            format!("The helper request contains an invalid {label}."),
            false,
        ));
    }
    Ok(())
}

fn safe_request_id(value: &str) -> ManagerResult<String> {
    validate_safe_identifier(value, "request id")?;
    Ok(value.to_string())
}

fn machine_root() -> PathBuf {
    PathBuf::from(get_canonical_paths().program_data_root).join(USER_DATA_DIRECTORY)
}

fn broker_request_directory() -> PathBuf {
    machine_root().join("Broker").join("Requests")
}

fn response_path_for(request_path: &Path) -> PathBuf {
    request_path.with_extension("response.json")
}

fn broker_executable_path() -> Option<PathBuf> {
    let current = env::current_exe().ok()?;
    let paths = get_canonical_paths();
    let shell_root = PathBuf::from(paths.shell_install);
    if is_same_or_child(&shell_root, &current) && current.is_file() {
        Some(current)
    } else {
        None
    }
}

fn broker_marker_path() -> Option<PathBuf> {
    broker_executable_path()?
        .parent()
        .map(|path| path.join(BROKER_MARKER_FILE))
}

fn validate_marker(path: &Path) -> ManagerResult<()> {
    let bytes = fs::read(path).map_err(|error| storage_error(path, error))?;
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|error| ComponentError::new("BROKER_MARKER_INVALID", error.to_string(), false))?;
    if value.get("schemaVersion").and_then(Value::as_str) != Some(BROKER_SCHEMA)
        || value.get("identifier").and_then(Value::as_str) != Some("aive-component-broker")
        || value.get("scope").and_then(Value::as_str) != Some("per-machine")
    {
        return Err(ComponentError::new(
            "BROKER_MARKER_INVALID",
            "The installed component helper marker has the wrong identity.",
            false,
        ));
    }
    Ok(())
}

fn is_broker_process() -> bool {
    env::var("AIVE_COMPONENT_BROKER").ok().as_deref() == Some("1")
}

#[cfg(windows)]
fn is_process_elevated() -> bool {
    use std::mem::size_of;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::Security::{
        GetTokenInformation, TokenElevation, TOKEN_ELEVATION, TOKEN_QUERY,
    };
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    let mut token = std::ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
        return false;
    }
    let mut elevation = TOKEN_ELEVATION { TokenIsElevated: 0 };
    let mut returned = 0u32;
    let ok = unsafe {
        GetTokenInformation(
            token,
            TokenElevation,
            (&mut elevation as *mut TOKEN_ELEVATION).cast(),
            size_of::<TOKEN_ELEVATION>() as u32,
            &mut returned,
        )
    } != 0;
    unsafe {
        CloseHandle(token);
    }
    ok && elevation.TokenIsElevated != 0
}

#[cfg(not(windows))]
fn is_process_elevated() -> bool {
    false
}

#[cfg(windows)]
fn launch_elevated_helper(request_path: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::{CloseHandle, WAIT_OBJECT_0};
    use windows_sys::Win32::System::Threading::{
        GetExitCodeProcess, WaitForSingleObject, INFINITE,
    };
    use windows_sys::Win32::UI::Shell::{
        ShellExecuteExW, SEE_MASK_NOCLOSEPROCESS, SHELLEXECUTEINFOW, SHELLEXECUTEINFOW_0,
    };

    let executable = broker_executable_path().ok_or_else(|| {
        "the running shell is not under the canonical Program Files installation root".to_string()
    })?;
    let parameters = format!("--component-broker \"{}\"", request_path.display());
    let file: Vec<u16> = executable
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let verb: Vec<u16> = std::ffi::OsStr::new("runas")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let params: Vec<u16> = std::ffi::OsString::from(parameters)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut info = SHELLEXECUTEINFOW {
        cbSize: std::mem::size_of::<SHELLEXECUTEINFOW>() as u32,
        fMask: SEE_MASK_NOCLOSEPROCESS,
        hwnd: std::ptr::null_mut(),
        lpVerb: verb.as_ptr(),
        lpFile: file.as_ptr(),
        lpParameters: params.as_ptr(),
        lpDirectory: std::ptr::null(),
        nShow: 0,
        hInstApp: std::ptr::null_mut(),
        lpIDList: std::ptr::null_mut(),
        lpClass: std::ptr::null(),
        hkeyClass: std::ptr::null_mut(),
        dwHotKey: 0,
        Anonymous: SHELLEXECUTEINFOW_0 {
            hIcon: std::ptr::null_mut(),
        },
        hProcess: std::ptr::null_mut(),
    };
    if unsafe { ShellExecuteExW(&mut info) } == 0 {
        return Err("Windows UAC did not start the bounded component helper".to_string());
    }
    if info.hProcess.is_null() {
        return Err("Windows did not return a helper process handle".to_string());
    }
    let waited = unsafe { WaitForSingleObject(info.hProcess, INFINITE) };
    if waited != WAIT_OBJECT_0 {
        unsafe {
            CloseHandle(info.hProcess);
        }
        return Err("the bounded component helper did not finish cleanly".to_string());
    }
    let mut exit_code = 1u32;
    let got_code = unsafe { GetExitCodeProcess(info.hProcess, &mut exit_code) } != 0;
    unsafe {
        CloseHandle(info.hProcess);
    }
    if !got_code || exit_code != 0 {
        return Err("the bounded component helper returned a failure".to_string());
    }
    Ok(())
}

fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temp = path.with_extension("tmp");
    let bytes = serde_json::to_vec_pretty(value)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    fs::rename(temp, path)
}

fn ensure_child_path(root: &Path, candidate: &Path) -> ManagerResult<()> {
    let normalized_root = normalize_path(root);
    let normalized_candidate = normalize_path(candidate);
    let relative = normalized_candidate
        .strip_prefix(&(normalized_root.clone() + "\\"))
        .unwrap_or_default();
    if normalized_candidate != normalized_root && relative.is_empty() {
        return Err(ComponentError::new(
            "BROKER_PATH_BOUNDARY",
            "The helper request path is outside its trusted machine perimeter.",
            false,
        ));
    }
    if relative
        .split('\\')
        .any(|part| part.is_empty() || part == "." || part == "..")
    {
        return Err(ComponentError::new(
            "BROKER_PATH_BOUNDARY",
            "The helper request path contains traversal or an empty path segment.",
            false,
        ));
    }
    Ok(())
}

fn normalize_path(path: &Path) -> String {
    path.to_string_lossy()
        .replace('/', "\\")
        .trim_end_matches('\\')
        .to_ascii_lowercase()
}

fn is_same_or_child(root: &Path, candidate: &Path) -> bool {
    let root = normalize_path(root);
    let candidate = normalize_path(candidate);
    candidate == root || candidate.starts_with(&(root + "\\"))
}

fn storage_error(_path: &Path, error: io::Error) -> ComponentError {
    ComponentError::new(
        "BROKER_STORAGE_ERROR",
        format!("The bounded helper could not access the machine perimeter: {error}"),
        true,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_bounded_operations_are_serializable() {
        let request = BrokerRequest {
            schema_version: BROKER_SCHEMA.to_string(),
            request_id: "request-1".to_string(),
            operation: BrokerOperation::Reconcile,
            component_id: None,
            component_version: None,
            operation_id: None,
            allow_offline_sources: false,
        };
        validate_request(&request).expect("reconcile request should validate");
        assert!(serde_json::to_string(&request)
            .expect("request should serialize")
            .contains("reconcile"));
    }

    #[test]
    fn request_paths_cannot_escape_broker_directory() {
        let root = PathBuf::from(r"C:\ProgramData\AI Video Editor\Broker\Requests");
        assert!(ensure_child_path(&root, &root.join("a.request.json")).is_ok());
        assert!(ensure_child_path(&root, &root.join(r"..\secret.json")).is_err());
    }
}
