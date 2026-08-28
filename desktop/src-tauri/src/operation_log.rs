//! Durable, bounded, redacted Desktop V2 operation evidence.

use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub const OPERATION_LOG_SCHEMA: &str = "desktop.operation-log.v1";
const LOG_FILE_NAME: &str = "desktop-operations.jsonl";
const MAX_LOG_BYTES: u64 = 512 * 1024;
const MAX_DETAIL_BYTES: usize = 1200;
const MAX_TAIL_ENTRIES: usize = 200;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OperationLogEntry {
    pub schema_version: String,
    pub at_epoch_ms: u128,
    pub operation: String,
    pub state: String,
    pub detail: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub component_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub component_version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub checkpoint: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub io_category: Option<String>,
}

pub fn redact_operation_text(value: &str) -> String {
    let mut output = value.chars().take(MAX_DETAIL_BYTES).collect::<String>();
    for marker in [
        "password=",
        "passwd=",
        "secret=",
        "token=",
        "api_key=",
        "api-key=",
        "authorization=",
        "bearer ",
    ] {
        let lower = output.to_ascii_lowercase();
        let mut search_from = 0;
        while let Some(relative) = lower[search_from..].find(marker) {
            let start = search_from + relative;
            let value_start = start + marker.len();
            let end = output[value_start..]
                .find(|character: char| {
                    character.is_whitespace() || matches!(character, ',' | ';' | '&')
                })
                .map(|offset| value_start + offset)
                .unwrap_or(output.len());
            output.replace_range(value_start..end, "[REDACTED]");
            search_from = value_start + "[REDACTED]".len();
            if search_from >= output.len() {
                break;
            }
        }
    }
    for (environment_key, replacement) in [
        ("USERPROFILE", "%USERPROFILE%"),
        ("LOCALAPPDATA", "%LOCALAPPDATA%"),
        ("PROGRAMDATA", "%PROGRAMDATA%"),
        ("PROGRAMFILES", "%PROGRAMFILES%"),
        ("PROGRAMFILES(X86)", "%PROGRAMFILES(X86)%"),
    ] {
        if let Ok(root) = std::env::var(environment_key) {
            if !root.is_empty() {
                output = output.replace(&root, replacement);
            }
        }
    }
    output
}

fn now_epoch_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

fn log_path(root: &Path) -> PathBuf {
    root.join(LOG_FILE_NAME)
}

fn append_operation_event_at(
    root: &Path,
    operation: &str,
    state: &str,
    detail: &str,
    component_id: Option<&str>,
    component_version: Option<&str>,
    checkpoint: Option<&str>,
    io_category: Option<&str>,
) -> Result<(), String> {
    fs::create_dir_all(root)
        .map_err(|_| "OPERATION_LOG_UNAVAILABLE: log directory is not writable.".to_string())?;
    let path = log_path(root);
    if fs::metadata(&path)
        .map(|metadata| metadata.len() > MAX_LOG_BYTES)
        .unwrap_or(false)
    {
        let rotated = root.join("desktop-operations.1.jsonl");
        let _ = fs::remove_file(&rotated);
        fs::rename(&path, rotated).map_err(|_| {
            "OPERATION_LOG_ROTATION_FAILED: the operation log could not rotate.".to_string()
        })?;
    }
    let entry = OperationLogEntry {
        schema_version: OPERATION_LOG_SCHEMA.to_string(),
        at_epoch_ms: now_epoch_ms(),
        operation: redact_operation_text(operation),
        state: redact_operation_text(state),
        detail: redact_operation_text(detail),
        component_id: component_id.map(redact_operation_text),
        component_version: component_version.map(redact_operation_text),
        checkpoint: checkpoint.map(redact_operation_text),
        io_category: io_category.map(redact_operation_text),
    };
    let line = serde_json::to_string(&entry).map_err(|_| {
        "OPERATION_LOG_SERIALIZE_FAILED: the operation record could not be encoded.".to_string()
    })?;
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|_| "OPERATION_LOG_UNAVAILABLE: operation log could not be opened.".to_string())?;
    file.write_all(line.as_bytes())
        .and_then(|_| file.write_all(b"\n"))
        .and_then(|_| file.flush())
        .map_err(|_| {
            "OPERATION_LOG_WRITE_FAILED: operation evidence could not be persisted.".to_string()
        })
}

pub fn append_operation(operation: &str, state: &str, detail: &str) {
    append_operation_event(operation, state, detail, None, None, None, None);
}

pub fn append_operation_event(
    operation: &str,
    state: &str,
    detail: &str,
    component_id: Option<&str>,
    component_version: Option<&str>,
    checkpoint: Option<&str>,
    io_category: Option<&str>,
) {
    if let Some(root) = dirs::data_local_dir().map(|path| path.join("AI Video Editor").join("Logs"))
    {
        let _ = append_operation_event_at(
            &root,
            operation,
            state,
            detail,
            component_id,
            component_version,
            checkpoint,
            io_category,
        );
    }
}

fn read_tail_at(root: &Path, limit: usize) -> Result<Vec<OperationLogEntry>, String> {
    let limit = limit.clamp(1, MAX_TAIL_ENTRIES);
    let path = log_path(root);
    let content = fs::read_to_string(path).unwrap_or_default();
    let mut entries = content
        .lines()
        .rev()
        .take(limit)
        .filter_map(|line| serde_json::from_str::<OperationLogEntry>(line).ok())
        .collect::<Vec<_>>();
    entries.reverse();
    Ok(entries)
}

pub(crate) fn current_tail(limit: usize) -> Vec<OperationLogEntry> {
    dirs::data_local_dir()
        .map(|path| path.join("AI Video Editor").join("Logs"))
        .and_then(|root| read_tail_at(&root, limit).ok())
        .unwrap_or_default()
}

#[tauri::command]
pub fn operation_log_tail(limit: Option<usize>) -> Result<Vec<OperationLogEntry>, String> {
    let root = dirs::data_local_dir()
        .map(|path| path.join("AI Video Editor").join("Logs"))
        .ok_or_else(|| "OPERATION_LOG_UNAVAILABLE: LocalAppData is unavailable.".to_string())?;
    read_tail_at(&root, limit.unwrap_or(50))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn operation_logs_are_redacted_and_bounded() {
        let root = std::env::temp_dir().join(format!(
            "aive-operation-log-{}-{}",
            std::process::id(),
            now_epoch_ms()
        ));
        append_operation_event_at(
            &root,
            "catalog-import",
            "failed",
            "api_key=super-secret token=private-value",
            None,
            None,
            None,
            None,
        )
        .expect("operation record");
        let entries = read_tail_at(&root, 10).expect("tail");
        assert_eq!(entries.len(), 1);
        assert!(!entries[0].detail.contains("super-secret"));
        assert!(!entries[0].detail.contains("private-value"));
        assert!(entries[0].detail.contains("[REDACTED]"));
        assert!(entries[0].component_id.is_none());
        let _ = fs::remove_dir_all(root);
    }
}
