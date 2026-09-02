//! Provider onboarding after local engine readiness.
//!
//! Only lecturer-owned password-field keys are accepted. Values are written
//! to the current Windows user's Credential Manager target and are never put
//! in setup state, diagnostics, operation logs, or command-line arguments.
//! Credential Manager uses the Windows user/machine protection boundary; the
//! release procedure documents the equivalent DPAPI boundary and does not
//! provide a plaintext fallback.

use crate::supervisor::SupervisorState;
use serde::{Deserialize, Serialize};
use tauri::State;

pub const PROVIDER_CREDENTIAL_SCHEMA: &str = "desktop.provider-credential.v1";
pub const PROVIDER_CREDENTIAL_STORAGE: &str = "windows-credential-manager-per-user";
const MAX_PROVIDER_ID_BYTES: usize = 64;
const MAX_KEY_NAME_BYTES: usize = 64;
const MAX_SECRET_BYTES: usize = 4096;
pub const TARGET_PREFIX: &str = "AI Video Editor Desktop V2/provider/";
pub const KNOWN_PROVIDER_IDS: &[&str] = &["mistral", "openai", "deepseek", "alibaba"];
pub const ALLOWED_SECRET_KEYS: &[&str] = &[
    "api_key",
    "access_token",
    "password",
    "hf_token",
    "custom_endpoint_key",
];

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderCredentialStatus {
    pub schema_version: String,
    pub provider_id: String,
    pub key_name: String,
    pub configured: bool,
    pub storage_verified: bool,
    pub provider_verified: bool,
    pub verification: String,
    pub storage: String,
    pub manual_default: bool,
    pub detail: String,
    pub remediation_codes: Vec<String>,
}

fn valid_identifier(value: &str, max_bytes: usize) -> bool {
    !value.is_empty()
        && value.len() <= max_bytes
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn validate_provider_key(provider_id: &str, key_name: &str) -> Result<(), String> {
    if !valid_identifier(provider_id, MAX_PROVIDER_ID_BYTES)
        || provider_id == "local"
        || !KNOWN_PROVIDER_IDS.contains(&provider_id)
    {
        return Err("PROVIDER_ID_INVALID: choose one of the supported provider cards.".to_string());
    }
    if !valid_identifier(key_name, MAX_KEY_NAME_BYTES) || !ALLOWED_SECRET_KEYS.contains(&key_name) {
        return Err(
            "PROVIDER_KEY_INVALID: only lecturer-owned password-field keys are supported."
                .to_string(),
        );
    }
    Ok(())
}

fn credential_target(provider_id: &str, key_name: &str) -> Result<String, String> {
    validate_provider_key(provider_id, key_name)?;
    Ok(format!("{TARGET_PREFIX}{provider_id}/{key_name}"))
}

/// Exact Credential Manager target names owned by this release. Uninstall
/// never enumerates the user's credential vault and never matches by prefix.
pub fn known_credential_targets() -> Vec<String> {
    KNOWN_PROVIDER_IDS
        .iter()
        .flat_map(|provider| {
            ALLOWED_SECRET_KEYS
                .iter()
                .map(move |key| format!("{TARGET_PREFIX}{provider}/{key}"))
        })
        .collect()
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CredentialWipeResult {
    pub removed_targets: Vec<String>,
    pub warnings: Vec<String>,
}

fn status(
    provider_id: &str,
    key_name: &str,
    configured: bool,
    detail: &str,
) -> ProviderCredentialStatus {
    ProviderCredentialStatus {
        schema_version: PROVIDER_CREDENTIAL_SCHEMA.to_string(),
        provider_id: provider_id.to_string(),
        key_name: key_name.to_string(),
        configured,
        storage_verified: configured,
        provider_verified: false,
        verification: "not-requested".to_string(),
        storage: PROVIDER_CREDENTIAL_STORAGE.to_string(),
        manual_default: true,
        detail: detail.to_string(),
        remediation_codes: if configured {
            Vec::new()
        } else {
            vec!["PROVIDER_CREDENTIAL_NOT_CONFIGURED".to_string()]
        },
    }
}

#[cfg(windows)]
fn wide(value: &str) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    std::ffi::OsStr::new(value)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

#[cfg(windows)]
fn credential_value(target: &str) -> Result<Option<String>, String> {
    use std::ptr::null_mut;
    use windows_sys::Win32::Security::Credentials::{
        CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
    };

    let target = wide(target);
    let mut credential: *mut CREDENTIALW = null_mut();
    let read = unsafe { CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut credential) };
    if read == 0 {
        return Ok(None);
    }
    let result = unsafe {
        if credential.is_null() {
            Err("CREDENTIAL_STORE_INVALID: Credential Manager returned no record.".to_string())
        } else {
            let record = &*credential;
            if record.CredentialBlob.is_null()
                || record.CredentialBlobSize as usize > MAX_SECRET_BYTES
            {
                Err("CREDENTIAL_STORE_INVALID: Credential Manager returned an invalid bounded record.".to_string())
            } else {
                let bytes = std::slice::from_raw_parts(
                    record.CredentialBlob,
                    record.CredentialBlobSize as usize,
                );
                String::from_utf8(bytes.to_vec()).map(Some).map_err(|_| {
                    "CREDENTIAL_STORE_INVALID: stored credential is not UTF-8.".to_string()
                })
            }
        }
    };
    unsafe { CredFree(credential.cast()) };
    result
}

#[cfg(not(windows))]
fn credential_value(_target: &str) -> Result<Option<String>, String> {
    Err("CREDENTIAL_STORE_UNAVAILABLE: Windows Credential Manager is available only on Windows releases.".to_string())
}

#[cfg(windows)]
fn write_credential(target: &str, value: &str) -> Result<(), String> {
    use std::ptr::null_mut;
    use windows_sys::Win32::Security::Credentials::{
        CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    };

    if value.is_empty() || value.len() > MAX_SECRET_BYTES || value.chars().any(char::is_control) {
        return Err(
            "PROVIDER_SECRET_INVALID: enter a bounded credential value without control characters."
                .to_string(),
        );
    }
    let target = wide(target);
    let mut blob = value.as_bytes().to_vec();
    let credential = CREDENTIALW {
        Flags: 0,
        Type: CRED_TYPE_GENERIC,
        TargetName: target.as_ptr() as *mut u16,
        Comment: null_mut(),
        LastWritten: unsafe { std::mem::zeroed() },
        CredentialBlobSize: blob.len() as u32,
        CredentialBlob: blob.as_mut_ptr(),
        Persist: CRED_PERSIST_LOCAL_MACHINE,
        AttributeCount: 0,
        Attributes: null_mut(),
        TargetAlias: null_mut(),
        UserName: null_mut(),
    };
    let written = unsafe { CredWriteW(&credential, 0) };
    blob.fill(0);
    if written == 0 {
        return Err(
            "CREDENTIAL_STORE_WRITE_FAILED: Windows Credential Manager rejected the credential."
                .to_string(),
        );
    }
    Ok(())
}

#[cfg(not(windows))]
fn write_credential(_target: &str, _value: &str) -> Result<(), String> {
    Err("CREDENTIAL_STORE_UNAVAILABLE: Windows Credential Manager is available only on Windows releases.".to_string())
}

#[cfg(windows)]
fn delete_credential(target: &str) -> Result<(), String> {
    use windows_sys::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
    use windows_sys::Win32::Security::Credentials::{CredDeleteW, CRED_TYPE_GENERIC};
    let target = wide(target);
    let deleted = unsafe { CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0) };
    if deleted == 0 {
        let error = unsafe { GetLastError() };
        if error != ERROR_NOT_FOUND {
            return Err(format!(
                "CREDENTIAL_STORE_DELETE_FAILED: Windows rejected a product-owned credential target (error {error})."
            ));
        }
    }
    Ok(())
}

#[cfg(not(windows))]
fn delete_credential(_target: &str) -> Result<(), String> {
    Err("CREDENTIAL_STORE_UNAVAILABLE: Windows Credential Manager is available only on Windows releases.".to_string())
}

fn provider_verification_status(
    provider_id: &str,
    key_name: &str,
    verified: bool,
    detail: &str,
) -> ProviderCredentialStatus {
    let mut value = status(provider_id, key_name, true, detail);
    value.provider_verified = verified;
    value.verification = if verified { "verified" } else { "not-verified" }.to_string();
    value.remediation_codes = if verified {
        Vec::new()
    } else {
        vec!["PROVIDER_NOT_VERIFIED".to_string()]
    };
    value
}

#[derive(Serialize)]
struct ProviderVerificationRequest<'a> {
    provider_id: &'a str,
    model: Option<&'a str>,
}

#[derive(Deserialize)]
struct ProviderVerificationResponse {
    provider_id: String,
    usable: bool,
}

/// Remove only compiled product-owned targets after the separate uninstall
/// full-wipe phrase has already been validated by the caller. No secret value
/// is returned, logged, or included in the uninstall report.
pub fn delete_known_credentials_for_full_wipe(dry_run: bool) -> CredentialWipeResult {
    let mut result = CredentialWipeResult::default();
    for target in known_credential_targets() {
        if dry_run {
            result.removed_targets.push(target);
            continue;
        }
        match credential_value(&target) {
            Ok(Some(_)) => match delete_credential(&target) {
                Ok(()) => result.removed_targets.push(target),
                Err(error) => result.warnings.push(error),
            },
            Ok(None) => {}
            Err(error) => result.warnings.push(error),
        }
    }
    result
}

#[tauri::command]
pub fn provider_credential_status(
    provider_id: String,
    key_name: String,
) -> Result<ProviderCredentialStatus, String> {
    let target = credential_target(&provider_id, &key_name)?;
    let configured = credential_value(&target)?.is_some();
    Ok(status(
        &provider_id,
        &key_name,
        configured,
        if configured {
            "A protected credential is configured for this provider field."
        } else {
            "No protected credential is configured. The local/manual provider remains available."
        },
    ))
}

#[tauri::command]
pub fn provider_credential_save(
    provider_id: String,
    key_name: String,
    secret: String,
) -> Result<ProviderCredentialStatus, String> {
    if secret.is_empty() || secret.len() > MAX_SECRET_BYTES || secret.chars().any(char::is_control)
    {
        return Err(
            "PROVIDER_SECRET_INVALID: enter a bounded credential value without control characters."
                .to_string(),
        );
    }
    let target = credential_target(&provider_id, &key_name)?;
    write_credential(&target, &secret)?;
    let matches = credential_value(&target)?.as_deref() == Some(secret.as_str());
    if !matches {
        return Err(
            "CREDENTIAL_STORE_VERIFY_FAILED: the protected credential could not be read back."
                .to_string(),
        );
    }
    Ok(status(
        &provider_id,
        &key_name,
        true,
        "Protected storage read-back passed. Provider connectivity has not been verified yet.",
    ))
}

/// Compatibility alias for older rc.3 clients. It performs protected storage
/// save/read-back only and never claims provider connectivity was tested.
#[tauri::command]
pub fn provider_credential_test(
    provider_id: String,
    key_name: String,
    secret: String,
) -> Result<ProviderCredentialStatus, String> {
    provider_credential_save(provider_id, key_name, secret)
}

#[tauri::command]
pub fn provider_credential_verify(
    supervisor: State<'_, SupervisorState>,
    provider_id: String,
    key_name: String,
) -> Result<ProviderCredentialStatus, String> {
    let target = credential_target(&provider_id, &key_name)?;
    if credential_value(&target)?.is_none() {
        return Ok(status(
            &provider_id,
            &key_name,
            false,
            "Save a credential securely before verifying this provider.",
        ));
    }
    let request = ProviderVerificationRequest {
        provider_id: &provider_id,
        model: None,
    };
    let response = supervisor
        .inner()
        .api_request_json::<_, ProviderVerificationResponse>(
            "POST",
            "/api/v1/settings/ai/test-provider",
            Some(&request),
        );
    match response {
        Ok(result) if result.provider_id == provider_id && result.usable => Ok(
            provider_verification_status(
                &provider_id,
                &key_name,
                true,
                "The local engine verified that this provider is available.",
            ),
        ),
        Ok(_) => Ok(provider_verification_status(
            &provider_id,
            &key_name,
            false,
            "The credential is stored securely, but the provider did not report as available.",
        )),
        Err(_) => Ok(provider_verification_status(
            &provider_id,
            &key_name,
            false,
            "The credential is stored securely, but provider verification is unavailable right now.",
        )),
    }
}

#[tauri::command]
pub fn provider_credential_clear(
    provider_id: String,
    key_name: String,
) -> Result<ProviderCredentialStatus, String> {
    let target = credential_target(&provider_id, &key_name)?;
    delete_credential(&target)?;
    Ok(status(
        &provider_id,
        &key_name,
        false,
        "The protected credential was cleared. No provider secret was written to application state.",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn credential_targets_are_bounded_and_never_include_secret_values() {
        let target = credential_target("openai", "api_key").expect("allowed key");
        assert_eq!(target, "AI Video Editor Desktop V2/provider/openai/api_key");
        assert!(!target.contains("secret"));
        assert!(credential_target("open ai", "api_key").is_err());
        assert!(credential_target("openai", "database_password").is_err());
        let targets = known_credential_targets();
        assert_eq!(
            targets.len(),
            KNOWN_PROVIDER_IDS.len() * ALLOWED_SECRET_KEYS.len()
        );
        assert!(targets.contains(&"AI Video Editor Desktop V2/provider/openai/api_key".to_string()));
        assert!(targets
            .iter()
            .all(|target| target.starts_with(TARGET_PREFIX)));
    }

    #[test]
    fn status_is_redacted_and_manual_by_default() {
        let value = status("custom", "api_key", false, "not configured");
        assert!(value.manual_default);
        assert!(!value.detail.contains("secret"));
        assert!(value.detail.contains("configured") || value.detail.contains("not"));
    }
}
