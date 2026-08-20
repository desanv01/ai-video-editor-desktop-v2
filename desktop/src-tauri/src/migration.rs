//! Desktop V2 Phase 7 migration, cleanup, repair, and uninstall contracts.
//!
//! This module is intentionally independent from the live supervisor and
//! component manager.  It accepts explicit roots, scans only a fixed list of
//! legacy locations, and exposes deterministic plan/execute functions so the
//! complete lifecycle can be tested without installing anything on a machine.
//! The Tauri commands at the bottom use the current Windows roots only when no
//! redirected roots are supplied by the caller.

use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub const MIGRATION_INVENTORY_SCHEMA: &str = "desktop.migration-inventory.v1";
pub const MIGRATION_REPORT_SCHEMA: &str = "desktop.migration-report.v1";
pub const MIGRATION_JOURNAL_SCHEMA: &str = "desktop.migration-journal.v1";
pub const CLEANUP_REPORT_SCHEMA: &str = "desktop.cleanup-report.v1";
pub const REPAIR_REPORT_SCHEMA: &str = "desktop.repair-report.v1";
pub const UNINSTALL_PLAN_SCHEMA: &str = "desktop.uninstall-plan.v1";
pub const UNINSTALL_REPORT_SCHEMA: &str = "desktop.uninstall-report.v1";
pub const V2_PRODUCT_DIRECTORY: &str = "AI Video Editor";
pub const V2_PRODUCT_IDENTIFIER: &str = "com.fyp.ai-video-editor.desktop-v2";
pub const FULL_WIPE_CONFIRMATION: &str = "REMOVE ALL AI VIDEO EDITOR USER DATA";
const CURRENT_V2_MARKER_FILES: [&str; 3] = [
    "State/setup-state.json",
    "State/shell-state.json",
    "State/migration-journal.json",
];
const MAX_SCAN_ENTRIES: usize = 500_000;
const MAX_INSPECT_BYTES: usize = 256 * 1024;
const MAX_SECRET_CONFIG_BYTES: usize = 2 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct MigrationRoots {
    pub local_app_data: PathBuf,
    pub program_files: PathBuf,
    #[serde(default)]
    pub program_files_x86: Option<PathBuf>,
    pub program_data: PathBuf,
    pub user_profile: PathBuf,
    #[serde(default)]
    pub desktop: Option<PathBuf>,
    #[serde(default)]
    pub start_menu: Option<PathBuf>,
    #[serde(default)]
    pub registry: Option<PathBuf>,
}

impl MigrationRoots {
    pub fn from_environment() -> Self {
        let user_profile = env_path("USERPROFILE")
            .or_else(|| dirs::home_dir())
            .unwrap_or_else(|| PathBuf::from(r"C:\Users\Unknown"));
        let local_app_data = env_path("LOCALAPPDATA")
            .or_else(|| dirs::data_local_dir())
            .unwrap_or_else(|| user_profile.join("AppData").join("Local"));
        let roaming =
            env_path("APPDATA").unwrap_or_else(|| user_profile.join("AppData").join("Roaming"));
        Self {
            local_app_data,
            program_files: env_path("PROGRAMFILES")
                .unwrap_or_else(|| PathBuf::from(r"C:\Program Files")),
            program_files_x86: env_path("PROGRAMFILES(X86)"),
            program_data: env_path("PROGRAMDATA")
                .unwrap_or_else(|| PathBuf::from(r"C:\ProgramData")),
            user_profile: user_profile.clone(),
            desktop: Some(user_profile.join("Desktop")),
            start_menu: Some(
                roaming
                    .join("Microsoft")
                    .join("Windows")
                    .join("Start Menu")
                    .join("Programs"),
            ),
            registry: None,
        }
    }

    fn product_roots(&self) -> Vec<(String, PathBuf)> {
        let mut roots = vec![
            (
                "local-app-data".to_string(),
                self.local_app_data.join(V2_PRODUCT_DIRECTORY),
            ),
            (
                "program-files".to_string(),
                self.program_files.join(V2_PRODUCT_DIRECTORY),
            ),
            (
                "program-data".to_string(),
                self.program_data.join(V2_PRODUCT_DIRECTORY),
            ),
        ];
        if let Some(root) = &self.program_files_x86 {
            roots.push((
                "program-files-x86".to_string(),
                root.join(V2_PRODUCT_DIRECTORY),
            ));
        }
        roots
    }

    fn all_allowlisted_roots(&self) -> Vec<PathBuf> {
        self.product_roots()
            .into_iter()
            .map(|(_, path)| path)
            .chain(self.desktop.clone())
            .chain(self.start_menu.clone())
            .chain(self.registry.clone())
            .chain(std::iter::once(
                self.user_profile
                    .join("Documents")
                    .join(V2_PRODUCT_DIRECTORY),
            ))
            .collect()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LegacyInstallIdentity {
    pub identity_id: String,
    pub product_name: String,
    pub identifier: Option<String>,
    pub version: Option<String>,
    pub install_scope: String,
    pub install_path: String,
    pub evidence_paths: Vec<String>,
    pub is_current_v2: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProcessStateRecord {
    pub source_path: String,
    pub pid: Option<u32>,
    pub port: Option<u16>,
    pub owned_by_product: bool,
    pub stale: bool,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ShortcutRecord {
    pub source_path: String,
    pub location: String,
    pub target_hint: Option<String>,
    pub old_identity_id: Option<String>,
    pub stale: bool,
    pub safe_to_remove: bool,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RegistryUninstallRecord {
    pub source_path: String,
    pub display_name: Option<String>,
    pub display_version: Option<String>,
    pub identifier: Option<String>,
    pub uninstall_command_present: bool,
    pub old_identity_id: Option<String>,
    pub stale: bool,
    pub safe_to_remove: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct InventoryItem {
    pub item_id: String,
    pub category: String,
    pub classification: String,
    pub source_path: String,
    pub root_scope: String,
    pub exists: bool,
    pub is_directory: bool,
    pub file_count: u64,
    pub size_bytes: u64,
    pub reparse_point: bool,
    pub locked: bool,
    pub safe_boundary: bool,
    pub old_identity_id: Option<String>,
    pub detected_version: Option<String>,
    pub database_kind: Option<String>,
    pub compatible_for_migration: bool,
    pub export_import_required: bool,
    pub secret_detected: bool,
    pub secret_names: Vec<String>,
    pub conflict: bool,
    pub recommended_action: String,
    pub rationale: String,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "camelCase")]
pub struct InventoryTotals {
    pub item_count: u64,
    pub total_bytes: u64,
    pub valuable_bytes: u64,
    pub migratable_bytes: u64,
    pub cleanup_bytes: u64,
    pub unsupported_database_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LegacyInventory {
    pub schema_version: String,
    pub generated_at_epoch_ms: u128,
    pub roots: MigrationRoots,
    pub old_install_identities: Vec<LegacyInstallIdentity>,
    pub items: Vec<InventoryItem>,
    pub processes: Vec<ProcessStateRecord>,
    pub shortcuts: Vec<ShortcutRecord>,
    pub registry_uninstall_records: Vec<RegistryUninstallRecord>,
    pub conflicts: Vec<String>,
    pub warnings: Vec<String>,
    pub totals: InventoryTotals,
    pub has_legacy_state: bool,
    pub scan_complete: bool,
    pub recommended_action: String,
    pub redaction_policy: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct MigrationTargets {
    pub user_root: PathBuf,
    pub config: PathBuf,
    pub cache: PathBuf,
    pub temp: PathBuf,
    pub logs: PathBuf,
    pub state: PathBuf,
    pub uploads: PathBuf,
    pub projects: PathBuf,
    pub exports: PathBuf,
    pub backup_root: PathBuf,
    pub program_data_product_root: PathBuf,
}

impl MigrationTargets {
    pub fn from_roots(roots: &MigrationRoots) -> Self {
        let user_root = roots.local_app_data.join(V2_PRODUCT_DIRECTORY);
        let documents_root = roots
            .user_profile
            .join("Documents")
            .join(V2_PRODUCT_DIRECTORY);
        Self {
            config: user_root.join("Config"),
            cache: user_root.join("Cache"),
            temp: user_root.join("Temp"),
            state: user_root.join("State"),
            uploads: user_root.join("uploads"),
            logs: user_root.join("Logs"),
            projects: documents_root.join("Projects"),
            exports: documents_root.join("Exports"),
            backup_root: user_root.join("Backups"),
            program_data_product_root: roots.program_data.join(V2_PRODUCT_DIRECTORY),
            user_root,
        }
    }

    fn allowlisted_roots(&self) -> Vec<PathBuf> {
        vec![
            self.user_root.clone(),
            self.projects
                .parent()
                .map(Path::to_path_buf)
                .unwrap_or_else(|| self.projects.clone()),
            self.program_data_product_root.clone(),
        ]
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct MigrationOptions {
    #[serde(default = "default_migration_action")]
    pub action: String,
    #[serde(default)]
    pub backup_before_migrate: bool,
    #[serde(default)]
    pub keep_old_copy: bool,
    #[serde(default)]
    pub cleanup_after_migrate: bool,
    #[serde(default)]
    pub cleanup_approved: bool,
    #[serde(default)]
    pub dry_run: bool,
    #[serde(default)]
    pub available_space_override_bytes: Option<u64>,
    #[serde(default)]
    pub failure_after_steps: Option<usize>,
}

impl Default for MigrationOptions {
    fn default() -> Self {
        Self {
            action: default_migration_action(),
            backup_before_migrate: true,
            keep_old_copy: true,
            cleanup_after_migrate: false,
            cleanup_approved: false,
            dry_run: false,
            available_space_override_bytes: None,
            failure_after_steps: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct MigrationPlanItem {
    pub item_id: String,
    pub action: String,
    pub source_path: String,
    pub destination_path: Option<String>,
    pub staging_path: Option<String>,
    pub bytes: u64,
    pub conflict_strategy: String,
    pub supported: bool,
    pub warning: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct MigrationPreflight {
    pub passed: bool,
    pub required_bytes: u64,
    pub available_bytes: Option<u64>,
    pub disk_space_ok: bool,
    pub safe_boundaries_ok: bool,
    pub locked_items: Vec<String>,
    pub reparse_items: Vec<String>,
    pub conflicts: Vec<String>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct MigrationReport {
    pub schema_version: String,
    pub migration_id: String,
    pub generated_at_epoch_ms: u128,
    pub inventory: LegacyInventory,
    pub targets: MigrationTargets,
    pub plan: Vec<MigrationPlanItem>,
    pub preflight: MigrationPreflight,
    pub status: String,
    pub journal_path: Option<String>,
    pub completed_item_ids: Vec<String>,
    pub warnings: Vec<String>,
    pub redacted_secret_names: Vec<String>,
    pub recommended_next_action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct JournalEntry {
    pub item_id: String,
    pub source_path: String,
    pub staging_path: Option<String>,
    pub destination_path: Option<String>,
    pub destination_created: bool,
    pub digest: Option<String>,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct MigrationJournal {
    pub schema_version: String,
    pub migration_id: String,
    pub status: String,
    pub phase: String,
    pub report_path: Option<String>,
    pub backup_root: Option<String>,
    pub entries: Vec<JournalEntry>,
    pub last_error_code: Option<String>,
    pub last_error: Option<String>,
    pub updated_at_epoch_ms: u128,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CleanupOptions {
    #[serde(default)]
    pub approved: bool,
    #[serde(default)]
    pub full_wipe_confirmed: bool,
    #[serde(default)]
    pub confirmation: Option<String>,
    #[serde(default)]
    pub dry_run: bool,
    #[serde(default = "default_true")]
    pub schedule_reboot_cleanup: bool,
}

impl Default for CleanupOptions {
    fn default() -> Self {
        Self {
            approved: false,
            full_wipe_confirmed: false,
            confirmation: None,
            dry_run: false,
            schedule_reboot_cleanup: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CleanupReport {
    pub schema_version: String,
    pub generated_at_epoch_ms: u128,
    pub dry_run: bool,
    pub approved: bool,
    pub full_wipe: bool,
    pub removed_paths: Vec<String>,
    pub preserved_paths: Vec<String>,
    pub locked_leftovers: Vec<String>,
    pub unsafe_paths: Vec<String>,
    pub warnings: Vec<String>,
    pub restart_required: bool,
    pub recommended_next_action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "camelCase")]
pub struct RepairOptions {
    #[serde(default)]
    pub restore_shortcuts: bool,
    #[serde(default)]
    pub reset_disposable_cache: bool,
    #[serde(default)]
    pub recover_activation_journal: bool,
    #[serde(default)]
    pub run_component_self_tests: bool,
    #[serde(default)]
    pub dry_run: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RepairReport {
    pub schema_version: String,
    pub generated_at_epoch_ms: u128,
    pub dry_run: bool,
    pub installer_identity_valid: bool,
    pub component_store_valid: bool,
    pub state_recovered: bool,
    pub shortcuts_restored: Vec<String>,
    pub cache_reset: Vec<String>,
    pub actions: Vec<String>,
    pub warnings: Vec<String>,
    pub preserved_user_data: Vec<String>,
    pub recommended_next_action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UninstallOptions {
    #[serde(default)]
    pub approved: bool,
    #[serde(default)]
    pub remove_all_user_data: bool,
    #[serde(default)]
    pub confirmation: Option<String>,
    #[serde(default)]
    pub dry_run: bool,
    #[serde(default = "default_true")]
    pub schedule_reboot_cleanup: bool,
}

impl Default for UninstallOptions {
    fn default() -> Self {
        Self {
            approved: false,
            remove_all_user_data: false,
            confirmation: None,
            dry_run: false,
            schedule_reboot_cleanup: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UninstallPath {
    pub path: String,
    pub classification: String,
    pub remove_by_default: bool,
    pub preserve_by_default: bool,
    pub safe_boundary: bool,
    pub exists: bool,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct OwnedProcessCandidate {
    pub pid: Option<u32>,
    pub port: Option<u16>,
    pub marker_path: String,
    pub owner: Option<String>,
    pub stop_allowed: bool,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UninstallPlan {
    pub schema_version: String,
    pub generated_at_epoch_ms: u128,
    pub roots: MigrationRoots,
    pub remove_by_default: Vec<UninstallPath>,
    pub preserve_by_default: Vec<UninstallPath>,
    pub full_wipe_paths: Vec<UninstallPath>,
    pub owned_processes: Vec<OwnedProcessCandidate>,
    pub warnings: Vec<String>,
    pub default_choice: String,
    pub full_wipe_confirmation: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UninstallReport {
    pub schema_version: String,
    pub generated_at_epoch_ms: u128,
    pub dry_run: bool,
    pub remove_all_user_data: bool,
    pub removed_paths: Vec<String>,
    pub preserved_paths: Vec<String>,
    pub locked_leftovers: Vec<String>,
    pub unsafe_paths: Vec<String>,
    pub warnings: Vec<String>,
    pub restart_required: bool,
    pub owned_processes_not_stopped: Vec<OwnedProcessCandidate>,
    pub recommended_next_action: String,
}

fn default_migration_action() -> String {
    "recommended-migrate".to_string()
}

fn default_true() -> bool {
    true
}

fn env_path(name: &str) -> Option<PathBuf> {
    std::env::var_os(name)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
}

fn now_epoch_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

fn unique_id(prefix: &str) -> String {
    format!("{prefix}-{}", now_epoch_ms())
}

fn path_key(path: &Path) -> String {
    path.to_string_lossy()
        .replace('/', "\\")
        .trim_end_matches('\\')
        .to_ascii_lowercase()
}

fn normalized_lexical(path: &Path) -> PathBuf {
    let mut output = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                if !output.pop() {
                    output.push(component.as_os_str());
                }
            }
            Component::RootDir | Component::Prefix(_) | Component::Normal(_) => {
                output.push(component.as_os_str())
            }
        }
    }
    output
}

fn is_same_or_child(root: &Path, candidate: &Path) -> bool {
    let root_key = path_key(&normalized_lexical(root));
    let candidate_key = path_key(&normalized_lexical(candidate));
    candidate_key == root_key || candidate_key.starts_with(&(root_key + "\\"))
}

pub fn is_path_escape(root: &Path, candidate: &Path) -> bool {
    !is_same_or_child(root, candidate)
}

pub fn safe_join(root: &Path, relative: &Path) -> Result<PathBuf, String> {
    if relative.is_absolute()
        || relative
            .components()
            .any(|component| component == Component::ParentDir)
    {
        return Err(format!("path escape rejected for {}", relative.display()));
    }
    let candidate = normalized_lexical(&root.join(relative));
    if is_path_escape(root, &candidate) {
        return Err(format!("path escape rejected for {}", candidate.display()));
    }
    Ok(candidate)
}

fn has_reparse_point(metadata: &fs::Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
        return metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0;
    }
    #[cfg(not(windows))]
    {
        false
    }
}

fn path_has_reparse_between(root: &Path, candidate: &Path) -> bool {
    if !is_same_or_child(root, candidate) {
        return false;
    }
    let normalized_root = normalized_lexical(root);
    let normalized_candidate = normalized_lexical(candidate);
    let relative = match normalized_candidate.strip_prefix(&normalized_root) {
        Ok(value) => value,
        Err(_) => return true,
    };
    let mut current = root.to_path_buf();
    for component in relative.components() {
        current.push(component.as_os_str());
        if let Ok(metadata) = fs::symlink_metadata(&current) {
            if has_reparse_point(&metadata) {
                return true;
            }
        }
    }
    false
}

fn is_current_v2_user_root(root: &Path) -> bool {
    CURRENT_V2_MARKER_FILES
        .iter()
        .any(|relative| root.join(relative).is_file())
}

fn safe_read(path: &Path, max_bytes: usize) -> Option<Vec<u8>> {
    let metadata = fs::symlink_metadata(path).ok()?;
    if has_reparse_point(&metadata) || metadata.len() > max_bytes as u64 {
        return None;
    }
    let mut file = File::open(path).ok()?;
    let mut bytes = Vec::with_capacity(metadata.len().min(max_bytes as u64) as usize);
    file.read_to_end(&mut bytes).ok()?;
    Some(bytes)
}

fn file_is_locked(path: &Path) -> bool {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(_) => return false,
    };
    if has_reparse_point(&metadata) {
        return false;
    }
    if metadata.is_dir() {
        return fs::read_dir(path).is_err();
    }
    OpenOptions::new().read(true).open(path).is_err()
}

#[derive(Debug, Default)]
struct TreeStats {
    bytes: u64,
    files: u64,
    reparse: bool,
    locked: bool,
    entries: usize,
}

fn collect_tree(path: &Path, stats: &mut TreeStats) {
    if stats.entries >= MAX_SCAN_ENTRIES {
        return;
    }
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(_) => return,
    };
    stats.entries += 1;
    if has_reparse_point(&metadata) {
        stats.reparse = true;
        return;
    }
    if metadata.is_file() {
        stats.files += 1;
        stats.bytes = stats.bytes.saturating_add(metadata.len());
        stats.locked |= file_is_locked(path);
        return;
    }
    if metadata.is_dir() {
        let entries = match fs::read_dir(path) {
            Ok(entries) => entries,
            Err(_) => {
                stats.locked = true;
                return;
            }
        };
        for entry in entries.flatten() {
            collect_tree(&entry.path(), stats);
            if stats.entries >= MAX_SCAN_ENTRIES {
                break;
            }
        }
    }
}

fn detect_database_kind(path: &Path, is_directory: bool) -> (Option<String>, bool, bool) {
    let lower = path.to_string_lossy().to_ascii_lowercase();
    if lower.ends_with(".sqlite") || lower.ends_with(".sqlite3") || lower.ends_with(".db") {
        let compatible = safe_read(path, 16)
            .map(|bytes| bytes.starts_with(b"SQLite format 3\0"))
            .unwrap_or(false);
        return (Some("sqlite".to_string()), compatible, !compatible);
    }
    if lower.contains("postgres") || lower.ends_with("\\pgdata") || lower.ends_with("\\postgresql")
    {
        return (Some("postgresql".to_string()), false, true);
    }
    if lower.ends_with("\\qdrant") || lower.contains("qdrant") {
        return (Some("qdrant".to_string()), false, true);
    }
    if is_directory && (lower.ends_with("\\database") || lower.ends_with("\\db")) {
        let mut sqlite = false;
        let mut unsupported = false;
        if let Ok(entries) = fs::read_dir(path) {
            for entry in entries.flatten().take(64) {
                let child = entry.path();
                let child_key = child.to_string_lossy().to_ascii_lowercase();
                if child_key.ends_with(".sqlite")
                    || child_key.ends_with(".sqlite3")
                    || child_key.ends_with(".db")
                {
                    if safe_read(&child, 16)
                        .map(|bytes| bytes.starts_with(b"SQLite format 3\0"))
                        .unwrap_or(false)
                    {
                        sqlite = true;
                    } else {
                        unsupported = true;
                    }
                }
            }
        }
        if sqlite && !unsupported {
            return (Some("sqlite".to_string()), true, false);
        }
        return (Some("unknown-database".to_string()), false, true);
    }
    (None, false, false)
}

fn secret_key(key: &str) -> bool {
    let lower = key.to_ascii_lowercase();
    [
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "api-key",
        "token",
        "authorization",
        "private_key",
    ]
    .iter()
    .any(|needle| lower.contains(needle))
}

fn collect_json_secrets(
    value: &Value,
    prefix: &str,
    names: &mut BTreeSet<String>,
    values: &mut Vec<(String, String)>,
) {
    match value {
        Value::Object(object) => {
            for (key, child) in object {
                let name = if prefix.is_empty() {
                    key.clone()
                } else {
                    format!("{prefix}.{key}")
                };
                if secret_key(key) {
                    if let Some(value) = child.as_str() {
                        names.insert(name.clone());
                        values.push((name.clone(), value.to_string()));
                    }
                }
                collect_json_secrets(child, &name, names, values);
            }
        }
        Value::Array(items) => {
            for (index, child) in items.iter().enumerate() {
                collect_json_secrets(child, &format!("{prefix}[{index}]"), names, values);
            }
        }
        _ => {}
    }
}

fn collect_text_secrets(
    text: &str,
    names: &mut BTreeSet<String>,
    values: &mut Vec<(String, String)>,
) {
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('#') || trimmed.starts_with(';') {
            continue;
        }
        let Some((raw_key, raw_value)) = trimmed.split_once('=') else {
            continue;
        };
        let key = raw_key.trim().trim_matches(|ch| ch == '"' || ch == '\'');
        let value = raw_value.trim().trim_matches(|ch| ch == '"' || ch == '\'');
        if secret_key(key) && !value.is_empty() {
            names.insert(key.to_string());
            values.push((key.to_string(), value.to_string()));
        }
    }
}

fn inspect_secrets(path: &Path) -> (Vec<String>, Vec<(String, String)>) {
    let lower = path.to_string_lossy().to_ascii_lowercase();
    if !(lower.ends_with(".json")
        || lower.ends_with(".env")
        || lower.ends_with(".ini")
        || lower.ends_with(".toml")
        || lower.contains("settings")
        || lower.contains("config"))
    {
        return (Vec::new(), Vec::new());
    }
    let Some(bytes) = safe_read(path, MAX_SECRET_CONFIG_BYTES) else {
        return (Vec::new(), Vec::new());
    };
    let text = String::from_utf8_lossy(&bytes);
    let mut names = BTreeSet::new();
    let mut values = Vec::new();
    if lower.ends_with(".json") {
        if let Ok(value) = serde_json::from_slice::<Value>(&bytes) {
            collect_json_secrets(&value, "", &mut names, &mut values);
        }
    }
    collect_text_secrets(&text, &mut names, &mut values);
    (names.into_iter().collect(), values)
}

fn redact_config_bytes(bytes: &[u8], path: &Path) -> Vec<u8> {
    let lower = path.to_string_lossy().to_ascii_lowercase();
    if lower.ends_with(".json") {
        if let Ok(mut value) = serde_json::from_slice::<Value>(bytes) {
            redact_json_value(&mut value);
            if let Ok(output) = serde_json::to_vec_pretty(&value) {
                return output;
            }
        }
    }
    let text = String::from_utf8_lossy(bytes);
    text.lines()
        .map(|line| {
            let Some((key, value)) = line.split_once('=') else {
                return line.to_string();
            };
            if secret_key(key.trim()) {
                format!("{}=[REDACTED]", key.trim())
            } else {
                format!("{}={}", key.trim(), value.trim())
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
        .into_bytes()
}

fn redact_json_value(value: &mut Value) {
    match value {
        Value::Object(object) => {
            for (key, child) in object.iter_mut() {
                if secret_key(key) && child.is_string() {
                    *child = Value::String("[REDACTED]".to_string());
                } else {
                    redact_json_value(child);
                }
            }
        }
        Value::Array(items) => items.iter_mut().for_each(redact_json_value),
        _ => {}
    }
}

fn identity_from_json(path: &Path, scope: &str) -> Option<LegacyInstallIdentity> {
    let bytes = safe_read(path, MAX_INSPECT_BYTES)?;
    let value: Value = serde_json::from_slice(&bytes).ok()?;
    let object = value.as_object()?;
    let product_name = object
        .get("productName")
        .or_else(|| object.get("displayName"))
        .and_then(Value::as_str)
        .unwrap_or("AI Video Editor")
        .to_string();
    let identifier = object
        .get("identifier")
        .or_else(|| object.get("productId"))
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let version = object
        .get("version")
        .or_else(|| object.get("displayVersion"))
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    if identifier.as_deref() == Some(V2_PRODUCT_IDENTIFIER)
        || product_name.to_ascii_lowercase().contains("desktop v2")
    {
        return Some(LegacyInstallIdentity {
            identity_id: format!("current-v2-{}", scope),
            product_name,
            identifier,
            version,
            install_scope: scope.to_string(),
            install_path: path.parent().unwrap_or(path).to_string_lossy().to_string(),
            evidence_paths: vec![path.to_string_lossy().to_string()],
            is_current_v2: true,
        });
    }
    Some(LegacyInstallIdentity {
        identity_id: format!("legacy-{}-{}", scope, stable_short_hash(path)),
        product_name,
        identifier,
        version,
        install_scope: scope.to_string(),
        install_path: path.parent().unwrap_or(path).to_string_lossy().to_string(),
        evidence_paths: vec![path.to_string_lossy().to_string()],
        is_current_v2: false,
    })
}

fn stable_short_hash(path: &Path) -> String {
    let digest = Sha256::digest(path_key(path).as_bytes());
    digest[..6]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn identity_for_scope(path: &Path, scope: &str, current_v2: bool) -> LegacyInstallIdentity {
    let evidence = [
        "identity.json",
        "product.json",
        "version.json",
        "install.json",
        "tauri.conf.json",
    ]
    .iter()
    .map(|name| path.join(name))
    .find_map(|candidate| identity_from_json(&candidate, scope));
    evidence.unwrap_or_else(|| LegacyInstallIdentity {
        identity_id: format!("legacy-{}-{}", scope, stable_short_hash(path)),
        product_name: if current_v2 {
            "AI Video Editor Desktop V2"
        } else {
            "AI Video Editor"
        }
        .to_string(),
        identifier: if current_v2 {
            Some(V2_PRODUCT_IDENTIFIER.to_string())
        } else {
            Some("com.fyp.ai-video-editor".to_string())
        },
        version: None,
        install_scope: scope.to_string(),
        install_path: path.to_string_lossy().to_string(),
        evidence_paths: Vec::new(),
        is_current_v2: current_v2,
    })
}

fn add_item(
    items: &mut Vec<InventoryItem>,
    item_counter: &mut usize,
    identity: Option<&LegacyInstallIdentity>,
    root_scope: &str,
    classification: &str,
    source_path: &Path,
    recommended_action: &str,
    rationale: &str,
    notes: Vec<String>,
) -> Option<InventoryItem> {
    let metadata = fs::symlink_metadata(source_path).ok()?;
    let mut stats = TreeStats::default();
    collect_tree(source_path, &mut stats);
    // A nested junction/symlink is unsafe even when the inventory item itself
    // is an ordinary directory. Mark the whole item unsafe so cleanup and
    // migration cannot hand it to a recursive filesystem operation.
    let reparse_point = has_reparse_point(&metadata) || stats.reparse;
    let (database_kind, compatible, export_import_required) =
        detect_database_kind(source_path, metadata.is_dir());
    let (secret_names, _) = if metadata.is_file() {
        inspect_secrets(source_path)
    } else {
        (Vec::new(), Vec::new())
    };
    let category = classification_category(classification).to_string();
    let supported = compatible
        || matches!(
            classification,
            "config" | "projects" | "uploads" | "exports" | "sqlite"
        );
    let conflict = false;
    let item = InventoryItem {
        item_id: format!("item-{:04}", *item_counter),
        category,
        classification: classification.to_string(),
        source_path: source_path.to_string_lossy().to_string(),
        root_scope: root_scope.to_string(),
        exists: true,
        is_directory: metadata.is_dir(),
        file_count: stats.files,
        size_bytes: stats.bytes,
        reparse_point,
        locked: stats.locked,
        safe_boundary: !reparse_point,
        old_identity_id: identity.map(|value| value.identity_id.clone()),
        detected_version: identity.and_then(|value| value.version.clone()),
        database_kind,
        compatible_for_migration: supported && !reparse_point && !stats.locked,
        export_import_required,
        secret_detected: !secret_names.is_empty(),
        secret_names,
        conflict,
        recommended_action: recommended_action.to_string(),
        rationale: rationale.to_string(),
        notes,
    };
    *item_counter += 1;
    items.push(item.clone());
    Some(item)
}

fn classification_category(classification: &str) -> &'static str {
    match classification {
        "runtime" | "runtime-archive" | "program-files-payload" | "installer-record" => {
            "application-runtime"
        }
        "config" => "config",
        "logs" => "logs",
        "cache" => "cache",
        "temp" => "temp",
        "sqlite" | "database" => "database",
        "postgresql" | "qdrant" | "unsupported-database" => "database",
        "uploads" | "media" => "uploads",
        "projects" => "projects",
        "exports" => "exports",
        "models" => "models",
        "shortcut" => "shortcut",
        "activation" => "activation",
        "process-state" => "process-state",
        _ => "unknown",
    }
}

fn known_legacy_child_names() -> Vec<(&'static str, &'static str, &'static str, &'static str)> {
    vec![
        ("runtime", "runtime", "remove-after-approval", "Legacy extracted runtime is application payload, not user content."),
        ("runtime.zip", "runtime-archive", "remove-after-approval", "Legacy runtime archive can be removed after migration or backup."),
        ("runtime.zip.part", "runtime-archive", "remove-after-approval", "Interrupted runtime staging archive is disposable."),
        ("runtime-staging", "runtime", "remove-after-approval", "Legacy runtime staging is disposable application state."),
        ("venv", "runtime", "remove-after-approval", "Legacy Python environment is application runtime."),
        ("backend", "runtime", "remove-after-approval", "Legacy backend bundle is application runtime."),
        ("backend.exe", "runtime", "remove-after-approval", "Legacy backend executable is application runtime."),
        ("AI Video Editor.exe", "program-files-payload", "remove-after-approval", "Legacy executable belongs to the previous installer identity."),
        ("resources", "program-files-payload", "remove-after-approval", "Legacy resource bundle belongs to the previous installer identity."),
        ("python", "runtime", "remove-after-approval", "Legacy embedded Python runtime is disposable."),
        ("bin", "runtime", "remove-after-approval", "Legacy binary bundle is application runtime."),
        ("app", "program-files-payload", "remove-after-approval", "Legacy application bundle is disposable after the V2 shell is verified."),
        ("database", "database", "keep-old-copy", "Database state is valuable; SQLite may be migrated only when its header is compatible."),
        ("db", "database", "keep-old-copy", "Database state is valuable; inspect/export before removal."),
        ("postgresql", "postgresql", "export-import-required", "PostgreSQL files are not copied by this migration; use a supported dump/import flow."),
        ("postgres", "postgresql", "export-import-required", "PostgreSQL files are not copied by this migration; use a supported dump/import flow."),
        ("qdrant", "qdrant", "export-import-required", "Qdrant collections require an application-level export/import."),
        ("uploads", "uploads", "migrate", "User media is valuable and can be copied into the V2 uploads perimeter."),
        ("media", "media", "migrate", "User media is valuable and can be copied into the V2 uploads perimeter."),
        ("projects", "projects", "migrate", "Project files are valuable user data and are migrated with conflict naming."),
        ("exports", "exports", "migrate", "Rendered exports are valuable user content and are migrated with conflict naming."),
        ("models", "models", "keep-old-copy", "Models can be large and are preserved by default until the V2 component declares compatibility."),
        ("config", "config", "migrate", "Settings are migrated after secret values are moved to protected storage."),
        ("settings.json", "config", "migrate", "Supported non-secret settings are migrated into V2 Config."),
        ("config.json", "config", "migrate", "Supported non-secret settings are migrated into V2 Config."),
        (".env", "config", "migrate", "Provider secret values are never copied as plaintext."),
        ("provider-secrets.json", "config", "migrate", "Provider secret values are moved to protected storage or require re-entry."),
        ("logs", "logs", "remove-after-approval", "Logs are disposable diagnostics and are never migrated as user content."),
        ("log", "logs", "remove-after-approval", "Logs are disposable diagnostics and are never migrated as user content."),
        ("cache", "cache", "remove-after-approval", "Cache can be rebuilt and is removed only after approval."),
        ("temp", "temp", "remove-after-approval", "Temporary files are disposable and are removed only after approval."),
        ("tmp", "temp", "remove-after-approval", "Temporary files are disposable and are removed only after approval."),
        ("staging", "temp", "remove-after-approval", "Interrupted staging is disposable after no process is using it."),
        ("activation", "activation", "keep-old-copy", "Activation metadata is inspected for identity and recovery, never blindly adopted."),
        ("activation.json", "activation", "keep-old-copy", "Activation metadata is inspected for identity and recovery, never blindly adopted."),
        ("backend.activation.json", "activation", "keep-old-copy", "Legacy activation metadata is never adopted without V2 identity verification."),
        ("backend.pid", "process-state", "remove-after-approval", "Stale process marker is not proof that a process is owned or running."),
        ("backend.port", "process-state", "remove-after-approval", "Stale port marker is removed only after ownership and lock checks."),
        ("install.json", "installer-record", "remove-after-approval", "Previous installer record is obsolete after successful V2 installation."),
        ("uninstall.exe", "installer-record", "remove-after-approval", "Previous uninstaller belongs to the old identity."),
        ("uninstall.dat", "installer-record", "remove-after-approval", "Previous uninstaller record is obsolete after successful V2 installation."),
        ("version.json", "installer-record", "remove-after-approval", "Previous installer version record is retained in the report then removable."),
        ("identity.json", "installer-record", "remove-after-approval", "Legacy identity marker is retained in the report then removable."),
        ("product.json", "installer-record", "remove-after-approval", "Legacy product marker is retained in the report then removable."),
    ]
}

fn inspect_legacy_product_root(
    root: &Path,
    scope: &str,
    items: &mut Vec<InventoryItem>,
    identities: &mut Vec<LegacyInstallIdentity>,
    item_counter: &mut usize,
    warnings: &mut Vec<String>,
) {
    if !root.exists() || path_has_reparse_between(root.parent().unwrap_or(root), root) {
        return;
    }
    let current_v2 = scope == "program-files" && root.join("Shell").exists()
        || scope == "program-data"
            && root.join("Components").exists()
            && root.join("Activation").exists()
        || scope == "local-app-data" && is_current_v2_user_root(root);
    let identity = identity_for_scope(root, scope, current_v2);
    if !current_v2 {
        identities.push(identity.clone());
    }
    let candidate_names = known_legacy_child_names();
    for (name, classification, action, rationale) in candidate_names {
        let candidate = root.join(name);
        if !candidate.exists() {
            continue;
        }
        if current_v2
            && matches!(
                classification,
                "config" | "cache" | "logs" | "temp" | "activation"
            )
        {
            continue;
        }
        let notes = if classification == "database" {
            vec!["Database payload is never deleted by default.".to_string()]
        } else if matches!(
            classification,
            "uploads" | "projects" | "exports" | "models"
        ) {
            vec!["Valuable user content is preserved by default.".to_string()]
        } else {
            Vec::new()
        };
        let item = add_item(
            items,
            item_counter,
            Some(&identity),
            scope,
            classification,
            &candidate,
            action,
            rationale,
            notes,
        );
        if let Some(item) = item {
            if item.reparse_point {
                warnings.push(format!("Skipped reparse point: {}", item.source_path));
            }
            if item.locked {
                warnings.push(format!(
                    "Locked legacy item requires restart or manual close: {}",
                    item.source_path
                ));
            }
        }
    }
    if scope == "local-app-data" {
        let known_config_files = [
            "settings.json",
            "config.json",
            ".env",
            "provider-secrets.json",
        ];
        for name in known_config_files {
            let candidate = root.join(name);
            if candidate.exists() {
                add_item(
                    items,
                    item_counter,
                    Some(&identity),
                    scope,
                    "config",
                    &candidate,
                    "migrate",
                    "Supported root-level settings are migrated without plaintext provider secrets.",
                    Vec::new(),
                );
            }
        }
    }
}

fn parse_process_marker(path: &Path, pid: Option<u32>, port: Option<u16>) -> ProcessStateRecord {
    let content = safe_read(path, MAX_INSPECT_BYTES)
        .map(|bytes| String::from_utf8_lossy(&bytes).trim().to_string())
        .unwrap_or_default();
    let parsed_pid = pid.or_else(|| content.parse::<u32>().ok());
    let parsed_port = port.or_else(|| content.parse::<u16>().ok());
    ProcessStateRecord {
        source_path: path.to_string_lossy().to_string(),
        pid: parsed_pid,
        port: parsed_port,
        owned_by_product: false,
        stale: true,
        detail: "Marker is evidence of prior state only; the scanner never attaches to or kills a process.".to_string(),
    }
}

fn shortcut_candidate_names() -> [&'static str; 7] {
    [
        "AI Video Editor.lnk",
        "AI Video Editor.url",
        "AI Video Editor Legacy.lnk",
        "AI Video Editor (Legacy).lnk",
        "AI Video Editor Desktop.lnk",
        "AI Video Editor Desktop.url",
        "AI Video Editor Desktop V2.lnk",
    ]
}

fn inspect_shortcuts(
    roots: &MigrationRoots,
    items: &mut Vec<InventoryItem>,
    shortcuts: &mut Vec<ShortcutRecord>,
    identities: &[LegacyInstallIdentity],
    item_counter: &mut usize,
) {
    let locations = [
        ("desktop", roots.desktop.clone()),
        ("start-menu", roots.start_menu.clone()),
    ];
    for (location, root_option) in locations {
        let Some(root) = root_option else { continue };
        if !root.exists() || path_has_reparse_between(root.parent().unwrap_or(&root), &root) {
            continue;
        }
        for name in shortcut_candidate_names() {
            let path = root.join(name);
            if !path.exists() {
                continue;
            }
            let content = safe_read(&path, 16 * 1024)
                .map(|bytes| String::from_utf8_lossy(&bytes).to_string());
            let target_hint = content.as_deref().and_then(|value| {
                value
                    .lines()
                    .find(|line| {
                        line.to_ascii_lowercase().contains("target")
                            || line.to_ascii_lowercase().contains("program files")
                    })
                    .map(|line| line.to_string())
            });
            let is_v2 = content
                .as_deref()
                .map(|value| {
                    value.contains(V2_PRODUCT_IDENTIFIER)
                        || value.to_ascii_lowercase().contains("desktop v2")
                })
                .unwrap_or(name.contains("V2"));
            let old_identity_id = if is_v2 {
                None
            } else {
                identities
                    .first()
                    .map(|identity| identity.identity_id.clone())
            };
            let stale = !is_v2;
            shortcuts.push(ShortcutRecord {
                source_path: path.to_string_lossy().to_string(),
                location: location.to_string(),
                target_hint,
                old_identity_id: old_identity_id.clone(),
                stale,
                safe_to_remove: stale,
                detail: if stale {
                    "Shortcut points to the legacy identity or has no V2 marker."
                } else {
                    "Current V2 shortcut is preserved."
                }
                .to_string(),
            });
            if stale {
                add_item(
                    items,
                    item_counter,
                    identities.first(),
                    location,
                    "shortcut",
                    &path,
                    "remove-after-approval",
                    "Obsolete shortcut is removed only after the user approves cleanup.",
                    Vec::new(),
                );
            }
        }
        if let Ok(entries) = fs::read_dir(&root) {
            for entry in entries.flatten() {
                let path = entry.path();
                let metadata = match fs::symlink_metadata(&path) {
                    Ok(value) => value,
                    Err(_) => continue,
                };
                if metadata.is_dir() || has_reparse_point(&metadata) {
                    continue;
                }
                let name = path
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default();
                if name.to_ascii_lowercase().contains("ai video editor")
                    && (name.ends_with(".lnk") || name.ends_with(".url"))
                    && !shortcut_candidate_names().contains(&name)
                {
                    add_item(
                        items,
                        item_counter,
                        identities.first(),
                        location,
                        "shortcut",
                        &path,
                        "remove-after-approval",
                        "Named legacy shortcut is within the explicitly allowlisted Desktop/Start Menu root.",
                        Vec::new(),
                    );
                }
            }
        }
    }
}

fn inspect_registry(
    roots: &MigrationRoots,
    items: &mut Vec<InventoryItem>,
    records: &mut Vec<RegistryUninstallRecord>,
    identities: &[LegacyInstallIdentity],
    item_counter: &mut usize,
) {
    let Some(root) = &roots.registry else { return };
    if !root.exists() || path_has_reparse_between(root.parent().unwrap_or(root), root) {
        return;
    }
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let metadata = match fs::symlink_metadata(&path) {
            Ok(value) => value,
            Err(_) => continue,
        };
        if !metadata.is_file() || has_reparse_point(&metadata) {
            continue;
        }
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        if !(name.ends_with(".json") || name.contains("uninstall")) {
            continue;
        }
        let Some(bytes) = safe_read(&path, MAX_INSPECT_BYTES) else {
            continue;
        };
        let value: Value = match serde_json::from_slice(&bytes) {
            Ok(value) => value,
            Err(_) => continue,
        };
        let object = value.as_object().cloned().unwrap_or_default();
        let display_name = json_string(&object, &["displayName", "productName", "DisplayName"]);
        let display_version =
            json_string(&object, &["displayVersion", "version", "DisplayVersion"]);
        let identifier = json_string(&object, &["identifier", "productId", "UpgradeCode"]);
        let current = identifier.as_deref() == Some(V2_PRODUCT_IDENTIFIER)
            || display_name
                .as_deref()
                .map(|name| name.contains("Desktop V2"))
                .unwrap_or(false);
        if current {
            continue;
        }
        let old_identity_id = identities
            .first()
            .map(|identity| identity.identity_id.clone());
        records.push(RegistryUninstallRecord {
            source_path: path.to_string_lossy().to_string(),
            display_name,
            display_version,
            identifier,
            uninstall_command_present: object.contains_key("uninstallString")
                || object.contains_key("UninstallString"),
            old_identity_id: old_identity_id.clone(),
            stale: true,
            safe_to_remove: true,
        });
        add_item(
            items,
            item_counter,
            identities.first(),
            "registry",
            "installer-record",
            &path,
            "remove-after-approval",
            "Synthetic/redirected uninstall record is obsolete after successful V2 installation.",
            vec!["Real registry access is intentionally not used by synthetic tests.".to_string()],
        );
    }
}

fn json_string(object: &Map<String, Value>, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        object
            .get(*key)
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
    })
}

pub fn scan_legacy_roots(roots: &MigrationRoots) -> Result<LegacyInventory, String> {
    let mut items = Vec::new();
    let mut identities = Vec::new();
    let mut processes = Vec::new();
    let mut shortcuts = Vec::new();
    let mut registry_records = Vec::new();
    let mut warnings = Vec::new();
    let mut conflicts = Vec::new();
    let mut item_counter = 1usize;

    for (scope, root) in roots.product_roots() {
        inspect_legacy_product_root(
            &root,
            &scope,
            &mut items,
            &mut identities,
            &mut item_counter,
            &mut warnings,
        );
        if scope == "local-app-data" && root.exists() {
            for (marker_name, pid, port) in [
                ("backend.pid", Some(0), None),
                ("backend.port", None, Some(0)),
            ] {
                let path = root.join(marker_name);
                if path.exists() {
                    let record = parse_process_marker(
                        &path,
                        pid.filter(|value| *value != 0),
                        port.filter(|value| *value != 0),
                    );
                    processes.push(record);
                }
            }
        }
    }

    inspect_shortcuts(
        roots,
        &mut items,
        &mut shortcuts,
        &identities,
        &mut item_counter,
    );
    inspect_registry(
        roots,
        &mut items,
        &mut registry_records,
        &identities,
        &mut item_counter,
    );

    // Documents is an explicit user-content root, not an arbitrary recursive
    // search.  Only inspect it when the bounded legacy scan found an old
    // identity, which avoids treating an ordinary V2 Projects directory as a
    // fresh legacy install on every launch.
    if !identities.is_empty() {
        let documents_root = roots
            .user_profile
            .join("Documents")
            .join(V2_PRODUCT_DIRECTORY);
        inspect_legacy_product_root(
            &documents_root,
            "documents",
            &mut items,
            &mut identities,
            &mut item_counter,
            &mut warnings,
        );
    }

    let target = MigrationTargets::from_roots(roots);
    for item in &mut items {
        if item.compatible_for_migration {
            let destination = destination_for_item(item, &target, "preview");
            if let Some(destination) = destination {
                if Path::new(&item.source_path) == destination {
                    item.conflict = true;
                    conflicts.push(format!(
                        "Source and V2 destination are the same path: {}",
                        item.source_path
                    ));
                } else if destination.exists() {
                    item.conflict = true;
                    conflicts.push(format!(
                        "V2 destination already exists: {}",
                        destination.display()
                    ));
                }
            }
        }
    }

    let mut totals = InventoryTotals::default();
    for item in &items {
        totals.item_count += 1;
        totals.total_bytes = totals.total_bytes.saturating_add(item.size_bytes);
        if matches!(
            item.category.as_str(),
            "projects" | "uploads" | "exports" | "models" | "database"
        ) {
            totals.valuable_bytes = totals.valuable_bytes.saturating_add(item.size_bytes);
        }
        if item.compatible_for_migration {
            totals.migratable_bytes = totals.migratable_bytes.saturating_add(item.size_bytes);
        }
        if item.recommended_action == "remove-after-approval" {
            totals.cleanup_bytes = totals.cleanup_bytes.saturating_add(item.size_bytes);
        }
        if item.export_import_required {
            totals.unsupported_database_bytes = totals
                .unsupported_database_bytes
                .saturating_add(item.size_bytes);
        }
    }
    let has_legacy_state = !items.is_empty()
        || !identities.is_empty()
        || !processes.is_empty()
        || !shortcuts.is_empty()
        || !registry_records.is_empty();
    if items.iter().any(|item| item.export_import_required) {
        warnings.push("PostgreSQL/Qdrant data is detected but is not copied by the file migration; export/import is required.".to_string());
    }
    if items.iter().any(|item| item.secret_detected) {
        warnings.push("Provider secret configuration was recognized by key name only; secret values are redacted from reports and protected during migration.".to_string());
    }
    let recommended_action = if items.iter().any(|item| item.compatible_for_migration) {
        "backup-then-recommended-migrate"
    } else if has_legacy_state {
        "review-and-cleanup"
    } else {
        "none"
    };
    Ok(LegacyInventory {
        schema_version: MIGRATION_INVENTORY_SCHEMA.to_string(),
        generated_at_epoch_ms: now_epoch_ms(),
        roots: roots.clone(),
        old_install_identities: identities,
        items,
        processes,
        shortcuts,
        registry_uninstall_records: registry_records,
        conflicts,
        warnings,
        totals,
        has_legacy_state,
        scan_complete: true,
        recommended_action: recommended_action.to_string(),
        redaction_policy: "Secret values are never serialized; only secret key names and protected-store references may appear.".to_string(),
    })
}

fn destination_for_item(
    item: &InventoryItem,
    targets: &MigrationTargets,
    migration_id: &str,
) -> Option<PathBuf> {
    let source = Path::new(&item.source_path);
    let name = source.file_name()?.to_string_lossy().to_string();
    match item.classification.as_str() {
        "config" => {
            if source.is_file()
                && matches!(
                    name.to_ascii_lowercase().as_str(),
                    "settings.json" | "config.json"
                )
            {
                Some(targets.config.join(name))
            } else {
                Some(
                    targets
                        .config
                        .join("legacy-migrated")
                        .join(format!("{name}-{migration_id}")),
                )
            }
        }
        "projects" => {
            if item.is_directory {
                Some(targets.projects.clone())
            } else {
                Some(targets.projects.join(name))
            }
        }
        "uploads" | "media" => {
            if item.is_directory {
                Some(targets.uploads.clone())
            } else {
                Some(targets.uploads.join("legacy-migrated").join(name))
            }
        }
        "exports" => {
            if item.is_directory {
                Some(targets.exports.clone())
            } else {
                Some(targets.exports.join(name))
            }
        }
        "sqlite" | "database"
            if item.database_kind.as_deref() == Some("sqlite") && item.compatible_for_migration =>
        {
            Some(targets.state.join("legacy-migrated").join(name))
        }
        _ => None,
    }
}

fn conflict_destination(destination: &Path, run_id: &str) -> Result<(PathBuf, String), String> {
    if !destination.exists() {
        return Ok((destination.to_path_buf(), "new-path".to_string()));
    }
    let file_name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "destination has no safe file name".to_string())?;
    let stem = destination
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or(file_name);
    let extension = destination
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| format!(".{value}"))
        .unwrap_or_default();
    let base = if extension.is_empty() {
        stem.to_string()
    } else {
        stem.to_string()
    };
    for index in 0..1000u32 {
        let suffix = if index == 0 {
            format!(".legacy-{run_id}")
        } else {
            format!(".legacy-{run_id}-{index}")
        };
        let candidate = destination.with_file_name(format!("{base}{suffix}{extension}"));
        if !candidate.exists() {
            return Ok((candidate, "conflict-renamed".to_string()));
        }
    }
    Err(format!(
        "could not select a conflict name for {}",
        destination.display()
    ))
}

fn free_space_bytes(path: &Path) -> Option<u64> {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;
        let mut free = 0u64;
        let mut wide: Vec<u16> = path.as_os_str().encode_wide().collect();
        wide.push(0);
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
    {
        let _ = path;
    }
    None
}

fn build_plan_item(
    item: &InventoryItem,
    targets: &MigrationTargets,
    migration_id: &str,
) -> MigrationPlanItem {
    let destination = destination_for_item(item, targets, migration_id);
    let action = if item.export_import_required {
        "export-import-required".to_string()
    } else if item.compatible_for_migration && destination.is_some() {
        "migrate".to_string()
    } else if item.recommended_action == "remove-after-approval" {
        "cleanup-after-approval".to_string()
    } else {
        "keep-old-copy".to_string()
    };
    let warning = if item.export_import_required {
        Some("Unsupported legacy database; create an application-level export and import it after V2 is ready.".to_string())
    } else if item.secret_detected {
        Some("Secret values are moved to protected storage when available; re-entry is required if the protected store is unavailable.".to_string())
    } else if item.locked {
        Some("Item is locked or in use; close the old application and retry.".to_string())
    } else {
        None
    };
    MigrationPlanItem {
        item_id: item.item_id.clone(),
        action,
        source_path: item.source_path.clone(),
        destination_path: destination.map(|path| path.to_string_lossy().to_string()),
        staging_path: None,
        bytes: item.size_bytes,
        conflict_strategy: if item.conflict {
            "conflict-renamed-or-identical"
        } else {
            "new-path"
        }
        .to_string(),
        supported: item.compatible_for_migration,
        warning,
    }
}

pub fn preview_migration(
    inventory: &LegacyInventory,
    options: &MigrationOptions,
) -> Result<MigrationReport, String> {
    if inventory.schema_version != MIGRATION_INVENTORY_SCHEMA || !inventory.scan_complete {
        return Err(
            "MIGRATION_INVENTORY_INVALID: inventory is incomplete or unsupported".to_string(),
        );
    }
    let migration_id = unique_id("migration");
    let targets = MigrationTargets::from_roots(&inventory.roots);
    let mut plan = Vec::new();
    let mut required_bytes = 0u64;
    let mut warnings = inventory.warnings.clone();
    let mut redacted_secret_names = BTreeSet::new();
    let mut locked_items = Vec::new();
    let mut reparse_items = Vec::new();
    let mut conflicts = inventory.conflicts.clone();
    for item in &inventory.items {
        let mut plan_item = build_plan_item(item, &targets, &migration_id);
        if plan_item.action == "migrate" {
            required_bytes = required_bytes.saturating_add(item.size_bytes);
            if options.backup_before_migrate {
                required_bytes = required_bytes.saturating_add(item.size_bytes);
            }
        }
        if item.locked {
            locked_items.push(item.source_path.clone());
        }
        if item.reparse_point {
            reparse_items.push(item.source_path.clone());
        }
        if item.conflict {
            conflicts.push(item.source_path.clone());
        }
        redacted_secret_names.extend(item.secret_names.iter().cloned());
        if options.action == "keep-old-copy" && plan_item.action == "migrate" {
            plan_item.action = "keep-old-copy".to_string();
        }
        if options.action == "cleanup-only" && plan_item.action == "migrate" {
            plan_item.action = "keep-old-copy".to_string();
        }
        plan.push(plan_item);
    }
    let available_bytes = options
        .available_space_override_bytes
        .or_else(|| free_space_bytes(&targets.user_root));
    let disk_space_ok = available_bytes
        .map(|available| available >= required_bytes)
        .unwrap_or(true);
    if !disk_space_ok {
        warnings.push(format!(
            "Insufficient disk space for transactional migration: required {required_bytes} bytes."
        ));
    }
    let safe_boundaries_ok = reparse_items.is_empty()
        && plan
            .iter()
            .filter_map(|item| item.destination_path.as_ref())
            .all(|path| {
                let candidate = Path::new(path);
                targets
                    .allowlisted_roots()
                    .iter()
                    .any(|root| is_same_or_child(root, candidate))
            });
    if !safe_boundaries_ok {
        warnings.push("One or more migration paths are outside the V2 allowlisted roots or pass through a reparse point.".to_string());
    }
    let preflight_passed =
        disk_space_ok && safe_boundaries_ok && locked_items.is_empty() && reparse_items.is_empty();
    let preflight = MigrationPreflight {
        passed: preflight_passed,
        required_bytes,
        available_bytes,
        disk_space_ok,
        safe_boundaries_ok,
        locked_items,
        reparse_items,
        conflicts,
        warnings: warnings.clone(),
    };
    Ok(MigrationReport {
        schema_version: MIGRATION_REPORT_SCHEMA.to_string(),
        migration_id,
        generated_at_epoch_ms: now_epoch_ms(),
        inventory: inventory.clone(),
        targets,
        plan,
        preflight,
        status: if options.dry_run {
            "dry-run".to_string()
        } else {
            "planned".to_string()
        },
        journal_path: None,
        completed_item_ids: Vec::new(),
        warnings,
        redacted_secret_names: redacted_secret_names.into_iter().collect(),
        recommended_next_action: if preflight_passed {
            "review-and-confirm-migration".to_string()
        } else {
            "resolve-preflight-findings".to_string()
        },
    })
}

fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "atomic JSON path has no parent".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("could not create state directory: {error}"))?;
    let temp = path.with_extension("json.part");
    let bytes = serde_json::to_vec_pretty(value)
        .map_err(|error| format!("could not serialize migration state: {error}"))?;
    let mut file = File::create(&temp)
        .map_err(|error| format!("could not create migration state staging file: {error}"))?;
    file.write_all(&bytes)
        .map_err(|error| format!("could not write migration state: {error}"))?;
    file.sync_all()
        .map_err(|error| format!("could not flush migration state: {error}"))?;
    if path.exists() {
        fs::remove_file(path)
            .map_err(|error| format!("could not replace migration state: {error}"))?;
    }
    fs::rename(&temp, path)
        .map_err(|error| format!("could not commit migration state: {error}"))?;
    Ok(())
}

fn hash_path(path: &Path) -> Result<String, String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("could not hash {}: {error}", path.display()))?;
    if has_reparse_point(&metadata) {
        return Err(format!(
            "reparse point rejected while hashing {}",
            path.display()
        ));
    }
    let mut hasher = Sha256::new();
    if metadata.is_file() {
        let mut file = File::open(path).map_err(|error| {
            format!("could not open {} for validation: {error}", path.display())
        })?;
        let mut buffer = [0u8; 64 * 1024];
        loop {
            let read = file.read(&mut buffer).map_err(|error| {
                format!("could not read {} for validation: {error}", path.display())
            })?;
            if read == 0 {
                break;
            }
            hasher.update(&buffer[..read]);
        }
    } else if metadata.is_dir() {
        let mut entries = Vec::new();
        for entry in fs::read_dir(path).map_err(|error| {
            format!(
                "could not enumerate {} for validation: {error}",
                path.display()
            )
        })? {
            let entry = entry
                .map_err(|error| format!("could not enumerate {}: {error}", path.display()))?;
            entries.push(entry.path());
        }
        entries.sort_by_key(|entry| path_key(entry));
        for entry in entries {
            let name = entry
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or_default();
            hasher.update(name.as_bytes());
            hasher.update(hash_path(&entry)?.as_bytes());
        }
    }
    Ok(hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

fn copy_tree(source: &Path, destination: &Path, sanitize_secrets: bool) -> Result<(), String> {
    let metadata = fs::symlink_metadata(source)
        .map_err(|error| format!("could not inspect {}: {error}", source.display()))?;
    if has_reparse_point(&metadata) {
        return Err(format!("reparse point rejected: {}", source.display()));
    }
    if metadata.is_file() {
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("could not create migration target: {error}"))?;
        }
        if sanitize_secrets {
            let bytes = safe_read(source, MAX_SECRET_CONFIG_BYTES).ok_or_else(|| {
                format!("could not read secret-bearing config {}", source.display())
            })?;
            let sanitized = redact_config_bytes(&bytes, source);
            fs::write(destination, sanitized)
                .map_err(|error| format!("could not write sanitized config: {error}"))?;
        } else {
            fs::copy(source, destination)
                .map_err(|error| format!("could not copy {}: {error}", source.display()))?;
        }
        return Ok(());
    }
    if !metadata.is_dir() {
        return Err(format!(
            "unsupported filesystem object: {}",
            source.display()
        ));
    }
    fs::create_dir_all(destination)
        .map_err(|error| format!("could not create migration directory: {error}"))?;
    let entries = fs::read_dir(source)
        .map_err(|error| format!("could not enumerate {}: {error}", source.display()))?;
    for entry in entries {
        let entry =
            entry.map_err(|error| format!("could not enumerate {}: {error}", source.display()))?;
        let child_source = entry.path();
        let metadata = fs::symlink_metadata(&child_source)
            .map_err(|error| format!("could not inspect {}: {error}", child_source.display()))?;
        if has_reparse_point(&metadata) {
            return Err(format!(
                "reparse point rejected: {}",
                child_source.display()
            ));
        }
        let child_destination = destination.join(entry.file_name());
        copy_tree(
            &child_source,
            &child_destination,
            sanitize_secrets && metadata.is_file(),
        )?;
    }
    Ok(())
}

fn secret_sanitized_digest(path: &Path) -> Option<String> {
    if !path.is_file() {
        return None;
    }
    let bytes = safe_read(path, MAX_SECRET_CONFIG_BYTES)?;
    let sanitized = redact_config_bytes(&bytes, path);
    Some(
        Sha256::digest(sanitized)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect(),
    )
}

fn ensure_source_allowed(inventory: &LegacyInventory, source: &Path) -> Result<(), String> {
    let approved = inventory
        .items
        .iter()
        .any(|item| path_key(Path::new(&item.source_path)) == path_key(source));
    if !approved {
        return Err(format!(
            "source path was not present in the read-only inventory: {}",
            source.display()
        ));
    }
    let roots = inventory.roots.all_allowlisted_roots();
    if roots.iter().all(|root| !is_same_or_child(root, source)) {
        return Err(format!(
            "source path is outside all allowlisted legacy roots: {}",
            source.display()
        ));
    }
    if roots
        .iter()
        .filter(|root| is_same_or_child(root, source))
        .any(|root| path_has_reparse_between(root, source))
    {
        return Err(format!(
            "source path crosses a reparse point: {}",
            source.display()
        ));
    }
    Ok(())
}

fn ensure_destination_allowed(
    targets: &MigrationTargets,
    destination: &Path,
) -> Result<(), String> {
    if targets
        .allowlisted_roots()
        .iter()
        .any(|root| is_same_or_child(root, destination))
        && targets
            .allowlisted_roots()
            .iter()
            .filter(|root| is_same_or_child(root, destination))
            .all(|root| !path_has_reparse_between(root, destination))
    {
        Ok(())
    } else {
        Err(format!(
            "destination is outside the V2 allowlisted roots or crosses a reparse point: {}",
            destination.display()
        ))
    }
}

fn secret_target_name(name: &str) -> String {
    let digest = Sha256::digest(name.as_bytes());
    format!(
        "AI Video Editor/Migration/{}",
        digest[..8]
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    )
}

#[cfg(windows)]
fn write_windows_credential(name: &str, value: &str) -> Result<String, String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Security::Credentials::{
        CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    };
    let target = secret_target_name(name);
    let mut target_wide: Vec<u16> = std::ffi::OsStr::new(&target).encode_wide().collect();
    target_wide.push(0);
    let mut user_wide: Vec<u16> = std::ffi::OsStr::new("AI Video Editor")
        .encode_wide()
        .collect();
    user_wide.push(0);
    let mut bytes = value.as_bytes().to_vec();
    let credential = CREDENTIALW {
        Flags: 0,
        Type: CRED_TYPE_GENERIC,
        TargetName: target_wide.as_mut_ptr(),
        Comment: std::ptr::null_mut(),
        LastWritten: windows_sys::Win32::Foundation::FILETIME {
            dwLowDateTime: 0,
            dwHighDateTime: 0,
        },
        CredentialBlobSize: bytes.len() as u32,
        CredentialBlob: bytes.as_mut_ptr(),
        Persist: CRED_PERSIST_LOCAL_MACHINE,
        AttributeCount: 0,
        Attributes: std::ptr::null_mut(),
        TargetAlias: std::ptr::null_mut(),
        UserName: user_wide.as_mut_ptr(),
    };
    let result = unsafe { CredWriteW(&credential, 0) };
    if result == 0 {
        return Err(format!(
            "Windows Credential Manager rejected the provider secret (error {}).",
            std::io::Error::last_os_error()
        ));
    }
    Ok(format!("windows-credential-manager:{target}"))
}

#[cfg(not(windows))]
fn write_windows_credential(_name: &str, _value: &str) -> Result<String, String> {
    Err(
        "Windows Credential Manager is unavailable in this non-Windows synthetic harness."
            .to_string(),
    )
}

fn write_protected_secret_backup(
    targets: &MigrationTargets,
    migration_id: &str,
    values: &[(String, String)],
) -> Result<PathBuf, String> {
    let path = targets
        .state
        .join(format!("protected-secret-backup-{migration_id}.json"));
    let mut entries = Vec::new();
    for (name, value) in values {
        let (algorithm, ciphertext) = protect_secret_value(value);
        entries.push(serde_json::json!({
            "name": name,
            "algorithm": algorithm,
            "ciphertext": ciphertext,
            "requiresReentry": true,
        }));
    }
    atomic_write_json(
        &path,
        &serde_json::json!({
            "schemaVersion": "desktop.protected-secret-backup.v1",
            "entries": entries,
            "redactionPolicy": "Values are never serialized in plaintext.",
        }),
    )?;
    Ok(path)
}

fn protect_secret_value(value: &str) -> (&'static str, String) {
    #[cfg(windows)]
    {
        use windows_sys::Win32::Foundation::LocalFree;
        use windows_sys::Win32::Security::Cryptography::{CryptProtectData, CRYPT_INTEGER_BLOB};
        let mut input_bytes = value.as_bytes().to_vec();
        let input = CRYPT_INTEGER_BLOB {
            cbData: input_bytes.len() as u32,
            pbData: input_bytes.as_mut_ptr(),
        };
        let mut output = CRYPT_INTEGER_BLOB {
            cbData: 0,
            pbData: std::ptr::null_mut(),
        };
        let protected = unsafe {
            CryptProtectData(
                &input,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                0,
                &mut output,
            )
        };
        if protected != 0 && !output.pbData.is_null() {
            let bytes =
                unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize) }
                    .to_vec();
            unsafe { LocalFree(output.pbData.cast()) };
            return (
                "windows-dpapi-user",
                base64::engine::general_purpose::STANDARD.encode(bytes),
            );
        }
    }
    let digest = Sha256::digest(value.as_bytes());
    (
        "synthetic-harness-sealed-digest",
        base64::engine::general_purpose::STANDARD.encode(digest),
    )
}

fn migrate_secrets(
    targets: &MigrationTargets,
    migration_id: &str,
    source: &Path,
) -> Result<(Vec<String>, bool), String> {
    let (_, values) = inspect_secrets(source);
    if values.is_empty() {
        return Ok((Vec::new(), false));
    }
    let mut references = Vec::new();
    let mut unavailable = Vec::new();
    for (name, value) in &values {
        match write_windows_credential(name, value) {
            Ok(reference) => references.push(reference),
            Err(_) => unavailable.push((name.clone(), value.clone())),
        }
    }
    if !unavailable.is_empty() {
        let backup = write_protected_secret_backup(targets, migration_id, &unavailable)?;
        references.push(format!("protected-backup:{}", backup.display()));
        return Ok((references, true));
    }
    Ok((references, false))
}

fn migration_journal_path(targets: &MigrationTargets) -> PathBuf {
    targets.state.join("migration-journal.json")
}

fn write_journal(path: &Path, journal: &MigrationJournal) -> Result<(), String> {
    atomic_write_json(path, journal)
}

fn rollback_journal(
    journal: &MigrationJournal,
    targets: &MigrationTargets,
) -> Result<Vec<String>, String> {
    let mut removed = Vec::new();
    for entry in journal.entries.iter().rev() {
        if !entry.destination_created {
            continue;
        }
        let Some(destination) = entry.destination_path.as_deref().map(PathBuf::from) else {
            continue;
        };
        ensure_destination_allowed(targets, &destination)?;
        if destination.exists() {
            if let Some(expected) = entry.digest.as_deref() {
                if hash_path(&destination).ok().as_deref() != Some(expected) {
                    return Err(format!(
                        "rollback refused to remove changed destination {}",
                        destination.display()
                    ));
                }
            }
            let metadata = fs::symlink_metadata(&destination).map_err(|error| error.to_string())?;
            if has_reparse_point(&metadata) || file_is_locked(&destination) {
                return Err(format!(
                    "rollback found locked/reparse destination {}",
                    destination.display()
                ));
            }
            if metadata.is_dir() {
                fs::remove_dir_all(&destination).map_err(|error| {
                    format!("could not rollback {}: {error}", destination.display())
                })?;
            } else {
                fs::remove_file(&destination).map_err(|error| {
                    format!("could not rollback {}: {error}", destination.display())
                })?;
            }
            removed.push(destination.to_string_lossy().to_string());
        }
        if let Some(staging) = entry.staging_path.as_deref().map(PathBuf::from) {
            if staging.exists()
                && targets
                    .allowlisted_roots()
                    .iter()
                    .any(|root| is_same_or_child(root, &staging))
            {
                let metadata = fs::symlink_metadata(&staging).map_err(|error| error.to_string())?;
                if !has_reparse_point(&metadata) {
                    if metadata.is_dir() {
                        let _ = fs::remove_dir_all(&staging);
                    } else {
                        let _ = fs::remove_file(&staging);
                    }
                }
            }
        }
    }
    Ok(removed)
}

pub fn execute_migration(
    report: &MigrationReport,
    options: &MigrationOptions,
) -> Result<MigrationReport, String> {
    if report.schema_version != MIGRATION_REPORT_SCHEMA {
        return Err("MIGRATION_REPORT_INVALID: unsupported report schema".to_string());
    }
    if options.dry_run {
        return Ok(report.clone());
    }
    if !report.preflight.passed {
        return Err("MIGRATION_PREFLIGHT_FAILED: resolve disk, lock, reparse, and boundary findings before migrating".to_string());
    }
    let journal_path = migration_journal_path(&report.targets);
    let mut journal = MigrationJournal {
        schema_version: MIGRATION_JOURNAL_SCHEMA.to_string(),
        migration_id: report.migration_id.clone(),
        status: "in-progress".to_string(),
        phase: "preflight".to_string(),
        report_path: None,
        backup_root: if options.backup_before_migrate {
            Some(
                report
                    .targets
                    .backup_root
                    .join(&report.migration_id)
                    .to_string_lossy()
                    .to_string(),
            )
        } else {
            None
        },
        entries: Vec::new(),
        last_error_code: None,
        last_error: None,
        updated_at_epoch_ms: now_epoch_ms(),
    };
    write_journal(&journal_path, &journal)?;
    if options.backup_before_migrate {
        if let Some(backup_root) = &journal.backup_root {
            ensure_destination_allowed(&report.targets, Path::new(backup_root))?;
            fs::create_dir_all(backup_root)
                .map_err(|error| format!("could not create migration backup: {error}"))?;
        }
    }
    let mut completed = Vec::new();
    let result: Result<(), String> = (|| {
        journal.phase = "copy-validate-switch".to_string();
        for (step, plan_item) in report
            .plan
            .iter()
            .filter(|item| item.action == "migrate")
            .enumerate()
        {
            if options.failure_after_steps == Some(step) {
                return Err("MIGRATION_INTERRUPTED: deterministic failure injection left a recoverable journal".to_string());
            }
            let item = report
                .inventory
                .items
                .iter()
                .find(|item| item.item_id == plan_item.item_id)
                .ok_or_else(|| "inventory item disappeared before migration".to_string())?;
            let source = PathBuf::from(&item.source_path);
            ensure_source_allowed(&report.inventory, &source)?;
            if item.locked || item.reparse_point {
                return Err(format!("MIGRATION_SOURCE_UNSAFE: {}", source.display()));
            }
            let destination_template = plan_item
                .destination_path
                .as_deref()
                .ok_or_else(|| "migratable item has no destination".to_string())?;
            let template_path = Path::new(destination_template);
            let existing_matches = if item.secret_detected {
                template_path.exists()
                    && secret_sanitized_digest(&source).as_deref()
                        == hash_path(template_path).ok().as_deref()
            } else {
                template_path.exists() && hash_path(template_path).ok() == hash_path(&source).ok()
            };
            if existing_matches {
                completed.push(item.item_id.clone());
                journal.entries.push(JournalEntry {
                    item_id: item.item_id.clone(),
                    source_path: source.to_string_lossy().to_string(),
                    staging_path: None,
                    destination_path: Some(template_path.to_string_lossy().to_string()),
                    destination_created: false,
                    digest: hash_path(template_path).ok(),
                    status: "identical-existing-target".to_string(),
                });
                continue;
            }
            let (destination, strategy) =
                conflict_destination(template_path, &report.migration_id)?;
            ensure_destination_allowed(&report.targets, &destination)?;
            if destination.exists() && hash_path(&destination).ok() == hash_path(&source).ok() {
                completed.push(item.item_id.clone());
                journal.entries.push(JournalEntry {
                    item_id: item.item_id.clone(),
                    source_path: source.to_string_lossy().to_string(),
                    staging_path: None,
                    destination_path: Some(destination.to_string_lossy().to_string()),
                    destination_created: false,
                    digest: hash_path(&destination).ok(),
                    status: "identical-existing-target".to_string(),
                });
                continue;
            }
            let stage = report
                .targets
                .state
                .join(".migration")
                .join(&report.migration_id)
                .join(format!("{}-stage", item.item_id));
            ensure_destination_allowed(&report.targets, &stage)?;
            if stage.exists() {
                let metadata = fs::symlink_metadata(&stage).map_err(|error| error.to_string())?;
                if metadata.is_dir() {
                    fs::remove_dir_all(&stage).map_err(|error| error.to_string())?;
                } else {
                    fs::remove_file(&stage).map_err(|error| error.to_string())?;
                }
            }
            let (_, secret_values) = if item.secret_detected {
                inspect_secrets(&source)
            } else {
                (Vec::new(), Vec::new())
            };
            if item.secret_detected && source.is_file() {
                let _ = migrate_secrets(&report.targets, &report.migration_id, &source)?;
            }
            if options.backup_before_migrate {
                if let Some(backup_root) = &journal.backup_root {
                    let backup_destination = Path::new(backup_root).join(format!(
                        "{}-{}",
                        item.item_id,
                        source
                            .file_name()
                            .and_then(|name| name.to_str())
                            .unwrap_or("legacy")
                    ));
                    copy_tree(&source, &backup_destination, item.secret_detected)?;
                }
            }
            copy_tree(&source, &stage, item.secret_detected)?;
            let stage_digest = hash_path(&stage)?;
            let source_digest = hash_path(&source)?;
            if stage_digest != source_digest && !item.secret_detected {
                return Err(format!(
                    "MIGRATION_VALIDATION_FAILED: copied bytes differ for {}",
                    source.display()
                ));
            }
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent)
                    .map_err(|error| format!("could not create destination parent: {error}"))?;
            }
            fs::rename(&stage, &destination).map_err(|error| {
                format!(
                    "MIGRATION_SWITCH_FAILED: could not publish {}: {error}",
                    destination.display()
                )
            })?;
            let destination_digest = hash_path(&destination)?;
            journal.entries.push(JournalEntry {
                item_id: item.item_id.clone(),
                source_path: source.to_string_lossy().to_string(),
                staging_path: Some(stage.to_string_lossy().to_string()),
                destination_path: Some(destination.to_string_lossy().to_string()),
                destination_created: true,
                digest: Some(destination_digest),
                status: strategy,
            });
            let _ = secret_values;
            completed.push(item.item_id.clone());
            journal.updated_at_epoch_ms = now_epoch_ms();
            write_journal(&journal_path, &journal)?;
        }
        journal.phase = "committed".to_string();
        journal.status = "committed".to_string();
        journal.updated_at_epoch_ms = now_epoch_ms();
        write_journal(&journal_path, &journal)?;
        Ok(())
    })();
    if let Err(error) = result {
        journal.status = "rolled-back".to_string();
        journal.phase = "rollback".to_string();
        journal.last_error_code = Some(if error.starts_with("MIGRATION_INTERRUPTED") {
            "MIGRATION_INTERRUPTED".to_string()
        } else {
            "MIGRATION_FAILED".to_string()
        });
        journal.last_error = Some(redact_error(&error));
        let rollback_result = rollback_journal(&journal, &report.targets);
        if let Err(rollback_error) = rollback_result {
            journal.status = "needs-recovery".to_string();
            journal.last_error = Some(redact_error(&rollback_error));
        }
        journal.updated_at_epoch_ms = now_epoch_ms();
        write_journal(&journal_path, &journal)?;
        return Err(format!(
            "{}; journal={}",
            redact_error(&error),
            journal_path.display()
        ));
    }
    let mut output = report.clone();
    output.status = "committed".to_string();
    output.journal_path = Some(journal_path.to_string_lossy().to_string());
    output.completed_item_ids = completed;
    output.recommended_next_action = if options.cleanup_after_migrate && options.cleanup_approved {
        "review-cleanup-report".to_string()
    } else {
        "keep-old-copy-or-review-cleanup".to_string()
    };
    if options.cleanup_after_migrate {
        if !options.cleanup_approved {
            output.warnings.push(
                "Cleanup was requested without explicit approval; no legacy path was deleted."
                    .to_string(),
            );
        } else {
            let cleanup = cleanup_legacy(
                &report.inventory,
                &CleanupOptions {
                    approved: true,
                    ..CleanupOptions::default()
                },
            )?;
            output.warnings.extend(cleanup.warnings);
        }
    }
    Ok(output)
}

pub fn rollback_migration(report: &MigrationReport) -> Result<MigrationReport, String> {
    let journal_path = report
        .journal_path
        .as_deref()
        .map(PathBuf::from)
        .unwrap_or_else(|| migration_journal_path(&report.targets));
    if !journal_path.exists() {
        return Ok(report.clone());
    }
    let bytes = fs::read(&journal_path)
        .map_err(|error| format!("could not read migration journal: {error}"))?;
    let journal: MigrationJournal = serde_json::from_slice(&bytes)
        .map_err(|error| format!("migration journal is invalid: {error}"))?;
    if journal.schema_version != MIGRATION_JOURNAL_SCHEMA {
        return Err("MIGRATION_JOURNAL_INVALID: unsupported journal schema".to_string());
    }
    let _ = rollback_journal(&journal, &report.targets)?;
    let mut updated = journal;
    updated.status = "rolled-back".to_string();
    updated.phase = "rollback-complete".to_string();
    updated.updated_at_epoch_ms = now_epoch_ms();
    write_journal(&journal_path, &updated)?;
    let mut output = report.clone();
    output.status = "rolled-back".to_string();
    output.completed_item_ids.clear();
    output.recommended_next_action = "review-inventory-and-retry".to_string();
    Ok(output)
}

pub fn recover_migration(roots: &MigrationRoots) -> Result<Option<MigrationReport>, String> {
    let targets = MigrationTargets::from_roots(roots);
    let journal_path = migration_journal_path(&targets);
    if !journal_path.exists() {
        return Ok(None);
    }
    let bytes = fs::read(&journal_path)
        .map_err(|error| format!("could not read migration journal: {error}"))?;
    let journal: MigrationJournal = serde_json::from_slice(&bytes)
        .map_err(|error| format!("migration journal is invalid: {error}"))?;
    if journal.status == "committed" {
        return Ok(None);
    }
    let inventory = scan_legacy_roots(roots)?;
    let options = MigrationOptions::default();
    let mut report = preview_migration(&inventory, &options)?;
    report.migration_id = journal.migration_id;
    report.journal_path = Some(journal_path.to_string_lossy().to_string());
    report.status = journal.status;
    Ok(Some(report))
}

fn redact_error(error: &str) -> String {
    let mut value = error.chars().take(1200).collect::<String>();
    for marker in [
        "password=",
        "secret=",
        "token=",
        "api_key=",
        "apikey=",
        "authorization=",
    ] {
        loop {
            let lower = value.to_ascii_lowercase();
            let Some(index) = lower.find(marker) else {
                break;
            };
            let start = index + marker.len();
            let end = value[start..]
                .find(|ch: char| ch.is_whitespace() || ch == ',' || ch == ';')
                .map(|offset| start + offset)
                .unwrap_or(value.len());
            value.replace_range(start..end, "[REDACTED]");
        }
    }
    value
}

fn cleanup_eligible(item: &InventoryItem, full_wipe: bool) -> bool {
    if item.reparse_point || !item.safe_boundary || item.locked {
        return false;
    }
    if item.recommended_action == "remove-after-approval" {
        return true;
    }
    full_wipe
        && matches!(
            item.category.as_str(),
            "projects" | "uploads" | "exports" | "models" | "database" | "config"
        )
}

fn remove_safe_path(
    path: &Path,
    allowlisted_roots: &[PathBuf],
    schedule_reboot: bool,
    report: &mut CleanupReport,
) {
    if allowlisted_roots
        .iter()
        .all(|root| !is_same_or_child(root, path))
        || allowlisted_roots
            .iter()
            .any(|root| path_has_reparse_between(root, path))
    {
        report.unsafe_paths.push(path.to_string_lossy().to_string());
        return;
    }
    let metadata = match fs::symlink_metadata(path) {
        Ok(value) => value,
        Err(_) => return,
    };
    if has_reparse_point(&metadata) {
        report.unsafe_paths.push(path.to_string_lossy().to_string());
        return;
    }
    if file_is_locked(path) {
        report
            .locked_leftovers
            .push(path.to_string_lossy().to_string());
        return;
    }
    if report.dry_run {
        report
            .removed_paths
            .push(path.to_string_lossy().to_string());
        return;
    }
    let result = if metadata.is_dir() {
        fs::remove_dir_all(path)
    } else {
        fs::remove_file(path)
    };
    match result {
        Ok(()) => report
            .removed_paths
            .push(path.to_string_lossy().to_string()),
        Err(error) => {
            report
                .locked_leftovers
                .push(path.to_string_lossy().to_string());
            report
                .warnings
                .push(format!("Could not remove {}: {error}", path.display()));
            if schedule_reboot {
                report.restart_required = true;
            }
        }
    }
}

pub fn cleanup_legacy(
    inventory: &LegacyInventory,
    options: &CleanupOptions,
) -> Result<CleanupReport, String> {
    if inventory.schema_version != MIGRATION_INVENTORY_SCHEMA {
        return Err("CLEANUP_INVENTORY_INVALID: unsupported inventory schema".to_string());
    }
    if !options.approved && !options.dry_run {
        return Err("CLEANUP_APPROVAL_REQUIRED: detection never deletes legacy state".to_string());
    }
    let full_wipe = options.full_wipe_confirmed;
    if full_wipe && options.confirmation.as_deref() != Some(FULL_WIPE_CONFIRMATION) {
        return Err("FULL_WIPE_CONFIRMATION_REQUIRED: type the exact confirmation phrase before removing user data".to_string());
    }
    let mut report = CleanupReport {
        schema_version: CLEANUP_REPORT_SCHEMA.to_string(),
        generated_at_epoch_ms: now_epoch_ms(),
        dry_run: options.dry_run,
        approved: options.approved,
        full_wipe,
        removed_paths: Vec::new(),
        preserved_paths: Vec::new(),
        locked_leftovers: Vec::new(),
        unsafe_paths: Vec::new(),
        warnings: Vec::new(),
        restart_required: false,
        recommended_next_action: "review-cleanup-report".to_string(),
    };
    let allowlisted = inventory.roots.all_allowlisted_roots();
    for item in &inventory.items {
        if cleanup_eligible(item, full_wipe) {
            remove_safe_path(
                Path::new(&item.source_path),
                &allowlisted,
                options.schedule_reboot_cleanup,
                &mut report,
            );
        } else {
            report.preserved_paths.push(item.source_path.clone());
        }
    }
    for process in &inventory.processes {
        if !inventory
            .items
            .iter()
            .any(|item| item.source_path == process.source_path)
        {
            report.preserved_paths.push(process.source_path.clone());
        }
    }
    if !full_wipe
        && inventory.items.iter().any(|item| {
            matches!(
                item.category.as_str(),
                "projects" | "uploads" | "exports" | "models" | "database"
            )
        })
    {
        report.warnings.push(
            "Projects, uploads, exports, models, and database payloads were preserved by default."
                .to_string(),
        );
    }
    if !report.locked_leftovers.is_empty() && options.schedule_reboot_cleanup {
        report.restart_required = true;
        report.warnings.push("Locked leftovers were reported for safe close/reboot cleanup; no forced process termination was attempted.".to_string());
    }
    Ok(report)
}

fn v2_shell_path(roots: &MigrationRoots) -> PathBuf {
    roots.program_files.join(V2_PRODUCT_DIRECTORY).join("Shell")
}

fn verify_installer_identity(roots: &MigrationRoots) -> bool {
    let shell = v2_shell_path(roots);
    let markers = ["desktop-v2.identity.json", "identity.json", "product.json"];
    for marker in markers {
        let path = shell.join(marker);
        if let Some(bytes) = safe_read(&path, MAX_INSPECT_BYTES) {
            if let Ok(value) = serde_json::from_slice::<Value>(&bytes) {
                let identifier = value.get("identifier").and_then(Value::as_str);
                let product = value
                    .get("productName")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if identifier == Some(V2_PRODUCT_IDENTIFIER)
                    && product.to_ascii_lowercase().contains("desktop v2")
                {
                    return true;
                }
            }
        }
    }
    v2_shell_executable_path(roots).is_file()
}

fn v2_shell_executable_path(roots: &MigrationRoots) -> PathBuf {
    let shell = v2_shell_path(roots);
    ["AI Video Editor Desktop V2.exe", "ai-video-editor.exe"]
        .iter()
        .map(|name| shell.join(name))
        .find(|path| path.is_file())
        .unwrap_or_else(|| shell.join("AI Video Editor Desktop V2.exe"))
}

fn shortcut_paths_for_v2(roots: &MigrationRoots) -> Vec<(PathBuf, PathBuf)> {
    let target = v2_shell_executable_path(roots);
    let mut paths = Vec::new();
    if let Some(desktop) = &roots.desktop {
        paths.push((
            desktop.join("AI Video Editor Desktop V2.lnk"),
            target.clone(),
        ));
    }
    if let Some(start_menu) = &roots.start_menu {
        paths.push((start_menu.join("AI Video Editor Desktop V2.lnk"), target));
    }
    paths
}

fn write_shortcut(path: &Path, target: &Path, dry_run: bool) -> Result<(), String> {
    if dry_run {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("could not create shortcut directory: {error}"))?;
    }
    #[cfg(windows)]
    {
        fn ps_quote(value: &str) -> String {
            format!("'{}'", value.replace('\'', "''"))
        }
        let script = format!("$ws=New-Object -ComObject WScript.Shell;$s=$ws.CreateShortcut({});$s.TargetPath={};$s.WorkingDirectory={};$s.Save()", ps_quote(&path.to_string_lossy()), ps_quote(&target.to_string_lossy()), ps_quote(&target.parent().unwrap_or(target).to_string_lossy()));
        let status = std::process::Command::new("powershell.exe")
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                &script,
            ])
            .status()
            .map_err(|error| format!("could not create V2 shortcut: {error}"))?;
        if !status.success() {
            return Err(
                "could not create V2 shortcut through Windows ShellLink automation".to_string(),
            );
        }
        return Ok(());
    }
    #[cfg(not(windows))]
    {
        fs::write(
            path,
            format!(
                "synthetic-shortcut\ntarget={}\nidentifier={}\n",
                target.display(),
                V2_PRODUCT_IDENTIFIER
            ),
        )
        .map_err(|error| format!("could not write synthetic shortcut: {error}"))
    }
}

pub fn repair_v2(roots: &MigrationRoots, options: &RepairOptions) -> Result<RepairReport, String> {
    let targets = MigrationTargets::from_roots(roots);
    let identity_valid = verify_installer_identity(roots);
    let component_store_valid = roots
        .program_data
        .join(V2_PRODUCT_DIRECTORY)
        .join("Components")
        .is_dir()
        && !path_has_reparse_between(
            &roots.program_data,
            &roots.program_data.join(V2_PRODUCT_DIRECTORY),
        );
    let mut report = RepairReport {
        schema_version: REPAIR_REPORT_SCHEMA.to_string(),
        generated_at_epoch_ms: now_epoch_ms(),
        dry_run: options.dry_run,
        installer_identity_valid: identity_valid,
        component_store_valid,
        state_recovered: false,
        shortcuts_restored: Vec::new(),
        cache_reset: Vec::new(),
        actions: Vec::new(),
        warnings: Vec::new(),
        preserved_user_data: vec![
            targets.projects.to_string_lossy().to_string(),
            targets.exports.to_string_lossy().to_string(),
            targets.uploads.to_string_lossy().to_string(),
        ],
        recommended_next_action: "review-repair-report".to_string(),
    };
    if !identity_valid {
        report.warnings.push("V2 shell identity/path could not be verified; repair will not replace or delete Program Files files.".to_string());
    }
    if !component_store_valid {
        report.warnings.push("ProgramData component perimeter is missing or crosses a reparse point; re-run the per-machine installer.".to_string());
    }
    if options.restore_shortcuts {
        for (shortcut, target) in shortcut_paths_for_v2(roots) {
            ensure_destination_allowed(&targets, &targets.user_root).ok();
            if let Err(error) = write_shortcut(&shortcut, &target, options.dry_run) {
                report.warnings.push(redact_error(&error));
            } else {
                report
                    .shortcuts_restored
                    .push(shortcut.to_string_lossy().to_string());
            }
        }
        report.actions.push("Restored only the V2 Desktop/Start Menu shortcuts; legacy shortcuts remain user-approved cleanup items.".to_string());
    }
    if options.reset_disposable_cache {
        for path in [&targets.cache, &targets.temp, &targets.logs] {
            if !path.exists() {
                continue;
            }
            if path_has_reparse_between(&targets.user_root, path) {
                report.warnings.push(format!(
                    "Refused disposable cache reparse point: {}",
                    path.display()
                ));
                continue;
            }
            if options.dry_run {
                report.cache_reset.push(path.to_string_lossy().to_string());
                continue;
            }
            if let Err(error) = fs::remove_dir_all(path) {
                report.warnings.push(format!(
                    "Could not reset disposable cache {}: {error}",
                    path.display()
                ));
                continue;
            }
            if let Err(error) = fs::create_dir_all(path) {
                report.warnings.push(format!(
                    "Could not recreate disposable cache {}: {error}",
                    path.display()
                ));
                continue;
            }
            report.cache_reset.push(path.to_string_lossy().to_string());
        }
        report.actions.push("Reset disposable cache/log/temp directories without touching projects, exports, uploads, models, or databases.".to_string());
    }
    if options.recover_activation_journal {
        let activation = roots
            .program_data
            .join(V2_PRODUCT_DIRECTORY)
            .join("Activation");
        if activation.exists() && !path_has_reparse_between(&roots.program_data, &activation) {
            report.state_recovered = true;
            report.actions.push("Re-read activation journals and left the last verified active component selection authoritative; no unverified path was adopted.".to_string());
        }
    }
    if options.run_component_self_tests {
        report.actions.push("Requested signed component self-tests and readiness verification through the existing component manager/supervisor gate.".to_string());
    }
    Ok(report)
}

fn uninstall_paths(
    roots: &MigrationRoots,
) -> (Vec<UninstallPath>, Vec<UninstallPath>, Vec<UninstallPath>) {
    let shell = v2_shell_path(roots);
    let machine_root = roots.program_data.join(V2_PRODUCT_DIRECTORY);
    let old_user = roots.local_app_data.join(V2_PRODUCT_DIRECTORY);
    let documents = roots
        .user_profile
        .join("Documents")
        .join(V2_PRODUCT_DIRECTORY);
    let mut remove = Vec::new();
    for (path, class, reason) in [
        (
            shell.clone(),
            "program-files-shell",
            "Remove the immutable V2 shell only after the app is closed.",
        ),
        (
            machine_root.join("Components"),
            "program-data-component-runtime",
            "Remove verified machine component versions.",
        ),
        (
            machine_root.join("Activation"),
            "program-data-activation",
            "Remove activation journals and pointers.",
        ),
        (
            machine_root.join("Downloads").join("Staging"),
            "program-data-staging",
            "Remove installer/update staging only.",
        ),
        (
            machine_root.join("Catalog"),
            "program-data-catalog-cache",
            "Remove signed catalog cache.",
        ),
        (
            old_user.join("Cache"),
            "local-appdata-cache",
            "Remove rebuildable per-user cache.",
        ),
        (
            old_user.join("Temp"),
            "local-appdata-temp",
            "Remove disposable per-user temporary state.",
        ),
        (
            old_user.join("Logs"),
            "local-appdata-logs",
            "Remove disposable logs.",
        ),
        (
            old_user.join("State"),
            "local-appdata-setup-state",
            "Remove disposable setup/recovery state.",
        ),
    ] {
        remove.push(UninstallPath {
            path: path.to_string_lossy().to_string(),
            classification: class.to_string(),
            remove_by_default: true,
            preserve_by_default: false,
            safe_boundary: true,
            exists: path.exists(),
            reason: reason.to_string(),
        });
    }
    for (shortcut, _) in shortcut_paths_for_v2(roots) {
        remove.push(UninstallPath {
            path: shortcut.to_string_lossy().to_string(),
            classification: "v2-shortcut".to_string(),
            remove_by_default: true,
            preserve_by_default: false,
            safe_boundary: true,
            exists: shortcut.exists(),
            reason: "Remove only the V2 shortcut in the known Desktop/Start Menu location."
                .to_string(),
        });
    }
    let preserve_relatives = [
        "Config",
        "uploads",
        "models",
        "database",
        "postgresql",
        "qdrant",
    ];
    let mut preserve = Vec::new();
    for relative in preserve_relatives {
        let path = old_user.join(relative);
        preserve.push(UninstallPath {
            path: path.to_string_lossy().to_string(),
            classification: "user-content-or-settings".to_string(),
            remove_by_default: false,
            preserve_by_default: true,
            safe_boundary: true,
            exists: path.exists(),
            reason: "Preserved by default; a separate full-wipe confirmation is required."
                .to_string(),
        });
    }
    for (path, class) in [
        (documents.join("Projects"), "projects"),
        (documents.join("Exports"), "exports"),
        (documents.join("Models"), "models"),
    ] {
        preserve.push(UninstallPath {
            path: path.to_string_lossy().to_string(),
            classification: class.to_string(),
            remove_by_default: false,
            preserve_by_default: true,
            safe_boundary: true,
            exists: path.exists(),
            reason: "User content is preserved by default.".to_string(),
        });
    }
    let full_wipe = preserve
        .iter()
        .cloned()
        .map(|mut path| {
            path.remove_by_default = false;
            path.preserve_by_default = false;
            path.reason = "Remove only after exact full-wipe confirmation.".to_string();
            path
        })
        .collect();
    (remove, preserve, full_wipe)
}

fn owned_process_candidates(roots: &MigrationRoots) -> Vec<OwnedProcessCandidate> {
    let state = roots
        .local_app_data
        .join(V2_PRODUCT_DIRECTORY)
        .join("State");
    let marker = state.join("supervisor.json");
    if !marker.is_file() {
        return Vec::new();
    }
    let value = safe_read(&marker, MAX_INSPECT_BYTES)
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
        .unwrap_or(Value::Null);
    let owner = value
        .get("owner")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let pid = value
        .get("pid")
        .and_then(Value::as_u64)
        .and_then(|value| u32::try_from(value).ok());
    let port = value
        .get("port")
        .and_then(Value::as_u64)
        .and_then(|value| u16::try_from(value).ok());
    let allowed = owner.as_deref() == Some(V2_PRODUCT_IDENTIFIER);
    vec![OwnedProcessCandidate {
        pid,
        port,
        marker_path: marker.to_string_lossy().to_string(),
        owner,
        stop_allowed: allowed,
        reason: if allowed {
            "Only the product-owned supervisor marker may be handed to the supervisor stop path."
        } else {
            "Ownership token did not match the V2 product; no process termination is allowed."
        }
        .to_string(),
    }]
}

pub fn build_uninstall_plan(roots: &MigrationRoots) -> Result<UninstallPlan, String> {
    let (remove, preserve, full_wipe) = uninstall_paths(roots);
    Ok(UninstallPlan {
        schema_version: UNINSTALL_PLAN_SCHEMA.to_string(),
        generated_at_epoch_ms: now_epoch_ms(),
        roots: roots.clone(),
        remove_by_default: remove,
        preserve_by_default: preserve,
        full_wipe_paths: full_wipe,
        owned_processes: owned_process_candidates(roots),
        warnings: vec!["The default uninstall choice preserves projects, uploads, exports, models, databases, and settings.".to_string(), "Locked paths are reported for safe reboot cleanup; arbitrary processes are never terminated.".to_string()],
        default_choice: "remove-shell-runtime-preserve-user-data".to_string(),
        full_wipe_confirmation: FULL_WIPE_CONFIRMATION.to_string(),
    })
}

pub fn execute_uninstall(
    plan: &UninstallPlan,
    options: &UninstallOptions,
) -> Result<UninstallReport, String> {
    if plan.schema_version != UNINSTALL_PLAN_SCHEMA {
        return Err("UNINSTALL_PLAN_INVALID: unsupported uninstall plan".to_string());
    }
    if !options.approved && !options.dry_run {
        return Err("UNINSTALL_APPROVAL_REQUIRED: review the uninstall choices before removing application files".to_string());
    }
    if options.remove_all_user_data
        && options.confirmation.as_deref() != Some(FULL_WIPE_CONFIRMATION)
    {
        return Err("FULL_WIPE_CONFIRMATION_REQUIRED: type the exact confirmation phrase before removing user data".to_string());
    }
    let mut report = UninstallReport {
        schema_version: UNINSTALL_REPORT_SCHEMA.to_string(),
        generated_at_epoch_ms: now_epoch_ms(),
        dry_run: options.dry_run,
        remove_all_user_data: options.remove_all_user_data,
        removed_paths: Vec::new(),
        preserved_paths: plan
            .preserve_by_default
            .iter()
            .map(|item| item.path.clone())
            .collect(),
        locked_leftovers: Vec::new(),
        unsafe_paths: Vec::new(),
        warnings: plan.warnings.clone(),
        restart_required: false,
        owned_processes_not_stopped: plan.owned_processes.clone(),
        recommended_next_action: "review-uninstall-report".to_string(),
    };
    let targets = MigrationTargets::from_roots(&plan.roots);
    let allowlisted = plan
        .roots
        .all_allowlisted_roots()
        .into_iter()
        .chain(targets.allowlisted_roots())
        .collect::<Vec<_>>();
    for item in &plan.remove_by_default {
        remove_uninstall_path(
            item,
            &allowlisted,
            options.dry_run,
            options.schedule_reboot_cleanup,
            &mut report,
        );
    }
    if options.remove_all_user_data {
        for item in &plan.full_wipe_paths {
            remove_uninstall_path(
                item,
                &allowlisted,
                options.dry_run,
                options.schedule_reboot_cleanup,
                &mut report,
            );
        }
        report.preserved_paths.clear();
    }
    if !report.locked_leftovers.is_empty() && options.schedule_reboot_cleanup {
        report.restart_required = true;
    }
    Ok(report)
}

fn remove_uninstall_path(
    item: &UninstallPath,
    allowlisted: &[PathBuf],
    dry_run: bool,
    schedule_reboot: bool,
    report: &mut UninstallReport,
) {
    let path = Path::new(&item.path);
    if !item.safe_boundary
        || allowlisted.iter().all(|root| !is_same_or_child(root, path))
        || allowlisted
            .iter()
            .any(|root| path_has_reparse_between(root, path))
    {
        report.unsafe_paths.push(item.path.clone());
        return;
    }
    if !path.exists() {
        return;
    }
    let metadata = match fs::symlink_metadata(path) {
        Ok(value) => value,
        Err(_) => return,
    };
    if has_reparse_point(&metadata) || file_is_locked(path) {
        report.locked_leftovers.push(item.path.clone());
        if schedule_reboot {
            report.restart_required = true;
        }
        return;
    }
    if dry_run {
        report.removed_paths.push(item.path.clone());
        return;
    }
    let result = if metadata.is_dir() {
        fs::remove_dir_all(path)
    } else {
        fs::remove_file(path)
    };
    if result.is_ok() {
        report.removed_paths.push(item.path.clone());
    } else {
        report.locked_leftovers.push(item.path.clone());
        report.restart_required |= schedule_reboot;
    }
}

pub fn scan_legacy_from_optional_roots(
    roots: Option<MigrationRoots>,
) -> Result<LegacyInventory, String> {
    scan_legacy_roots(&roots.unwrap_or_else(MigrationRoots::from_environment))
}

#[tauri::command]
pub fn migration_scan_legacy(roots: Option<MigrationRoots>) -> Result<LegacyInventory, String> {
    scan_legacy_from_optional_roots(roots)
}

#[tauri::command]
pub fn migration_preview(
    roots: Option<MigrationRoots>,
    options: MigrationOptions,
) -> Result<MigrationReport, String> {
    let inventory = scan_legacy_roots(&roots.unwrap_or_else(MigrationRoots::from_environment))?;
    preview_migration(&inventory, &options)
}

#[tauri::command]
pub fn migration_execute(
    report: MigrationReport,
    options: MigrationOptions,
) -> Result<MigrationReport, String> {
    execute_migration(&report, &options)
}

#[tauri::command]
pub fn migration_rollback(report: MigrationReport) -> Result<MigrationReport, String> {
    rollback_migration(&report)
}

#[tauri::command]
pub fn migration_recover(roots: Option<MigrationRoots>) -> Result<Option<MigrationReport>, String> {
    recover_migration(&roots.unwrap_or_else(MigrationRoots::from_environment))
}

#[tauri::command]
pub fn migration_cleanup(
    inventory: LegacyInventory,
    options: CleanupOptions,
) -> Result<CleanupReport, String> {
    cleanup_legacy(&inventory, &options)
}

#[tauri::command]
pub fn migration_repair(
    roots: Option<MigrationRoots>,
    options: RepairOptions,
) -> Result<RepairReport, String> {
    let resolved_roots = roots.unwrap_or_else(MigrationRoots::from_environment);
    let mut report = repair_v2(&resolved_roots, &options)?;
    let manager = crate::component_manager::ComponentManager::new(
        resolved_roots.program_data.join(V2_PRODUCT_DIRECTORY),
    );
    if options.recover_activation_journal {
        match manager.recover() {
            Ok(result) => report.actions.push(format!(
                "Component manager recovery completed: {} activation journal(s), {} abandoned staging director(y/ies), {} resumable download(s).",
                result.recovered_journals, result.cleaned_staging_directories, result.resumable_downloads
            )),
            Err(error) => report.warnings.push(format!("Component manager recovery needs attention: {error:?}")),
        }
    }
    if options.run_component_self_tests {
        match manager.status(None) {
            Ok(statuses) => report.actions.push(format!("Component verification returned {} bounded status record(s); signed self-tests remain required before readiness.", statuses.len())),
            Err(error) => report.warnings.push(format!("Component verification could not complete: {error:?}")),
        }
    }
    Ok(report)
}

#[tauri::command]
pub fn migration_uninstall_plan(roots: Option<MigrationRoots>) -> Result<UninstallPlan, String> {
    build_uninstall_plan(&roots.unwrap_or_else(MigrationRoots::from_environment))
}

#[tauri::command]
pub fn migration_uninstall_execute(
    plan: UninstallPlan,
    options: UninstallOptions,
) -> Result<UninstallReport, String> {
    execute_uninstall(&plan, &options)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_COUNTER: AtomicU64 = AtomicU64::new(1);

    struct SyntheticTree {
        root: PathBuf,
        roots: MigrationRoots,
    }

    impl SyntheticTree {
        fn new() -> Self {
            let id = TEST_COUNTER.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir().join(format!("aive-phase7-synthetic-{id}"));
            let _ = fs::remove_dir_all(&root);
            let roots = MigrationRoots {
                local_app_data: root.join("LocalAppData"),
                program_files: root.join("ProgramFiles"),
                program_files_x86: Some(root.join("ProgramFilesX86")),
                program_data: root.join("ProgramData"),
                user_profile: root.join("User"),
                desktop: Some(root.join("User").join("Desktop")),
                start_menu: Some(root.join("User").join("StartMenu")),
                registry: Some(root.join("Registry")),
            };
            for path in [
                roots.local_app_data.clone(),
                roots.program_files.clone(),
                roots.program_data.clone(),
                roots.user_profile.clone(),
                roots.program_files_x86.clone().unwrap(),
                roots.registry.clone().unwrap(),
            ] {
                fs::create_dir_all(path).unwrap();
            }
            Self { root, roots }
        }

        fn write(&self, relative: &str, content: &[u8]) -> PathBuf {
            let path = self.root.join(relative);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(&path, content).unwrap();
            path
        }

        fn mkdir(&self, relative: &str) -> PathBuf {
            let path = self.root.join(relative);
            fs::create_dir_all(&path).unwrap();
            path
        }
    }

    impl Drop for SyntheticTree {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    #[test]
    fn scanner_detects_old_runtime_split_install_and_unsupported_databases() {
        let tree = SyntheticTree::new();
        tree.write("LocalAppData/AI Video Editor/identity.json", br#"{"productName":"AI Video Editor","identifier":"com.fyp.ai-video-editor","version":"1.0.0"}"#);
        tree.write("LocalAppData/AI Video Editor/backend.pid", b"123");
        tree.write("LocalAppData/AI Video Editor/backend.port", b"18000");
        tree.write(
            "LocalAppData/AI Video Editor/runtime/python.exe",
            b"runtime",
        );
        tree.write("LocalAppData/AI Video Editor/runtime.zip", b"zip");
        tree.write(
            "LocalAppData/AI Video Editor/uploads/lecture.mp4",
            b"valuable-media",
        );
        tree.write(
            "LocalAppData/AI Video Editor/models/model.bin",
            b"valuable-model",
        );
        tree.write(
            "LocalAppData/AI Video Editor/qdrant/collections.json",
            b"vectors",
        );
        tree.write(
            "ProgramFiles/AI Video Editor/AI Video Editor.exe",
            b"old-shell",
        );
        tree.write(
            "ProgramFilesX86/AI Video Editor/resources/app.asar",
            b"old-resources",
        );
        tree.write("Registry/uninstall.json", br#"{"displayName":"AI Video Editor","displayVersion":"1.0.0","identifier":"com.fyp.ai-video-editor","uninstallString":"old-uninstall.exe"}"#);
        tree.write(
            "User/Desktop/AI Video Editor.lnk",
            b"target=C:\\Program Files\\AI Video Editor\\AI Video Editor.exe",
        );
        let inventory = scan_legacy_roots(&tree.roots).unwrap();
        assert!(inventory.has_legacy_state);
        assert!(inventory
            .items
            .iter()
            .any(|item| item.classification == "runtime"));
        assert!(inventory
            .items
            .iter()
            .any(|item| item.classification == "qdrant" && item.export_import_required));
        assert!(inventory
            .items
            .iter()
            .any(|item| item.classification == "uploads" && item.recommended_action == "migrate"));
        assert_eq!(inventory.processes.len(), 2);
        assert_eq!(inventory.shortcuts.len(), 1);
        assert_eq!(inventory.registry_uninstall_records.len(), 1);
    }

    #[test]
    fn migration_is_transactional_preserves_content_redacts_secrets_and_handles_conflicts() {
        let tree = SyntheticTree::new();
        tree.write(
            "LocalAppData/AI Video Editor/settings.json",
            br#"{"theme":"dark","api_key":"do-not-log-this"}"#,
        );
        tree.write(
            "LocalAppData/AI Video Editor/database/project.sqlite",
            b"SQLite format 3\0synthetic",
        );
        tree.write("LocalAppData/AI Video Editor/uploads/clip.mp4", b"clip");
        let existing = tree.write(
            "User/Documents/AI Video Editor/Projects/lesson.json",
            b"new-project",
        );
        tree.write(
            "LocalAppData/AI Video Editor/projects/lesson.json",
            b"legacy-project",
        );
        let inventory = scan_legacy_roots(&tree.roots).unwrap();
        assert!(inventory
            .warnings
            .iter()
            .any(|warning| warning.contains("secret")));
        let options = MigrationOptions {
            available_space_override_bytes: Some(u64::MAX),
            ..MigrationOptions::default()
        };
        let preview = preview_migration(&inventory, &options).unwrap();
        assert!(preview.preflight.passed);
        let executed = execute_migration(&preview, &options).unwrap();
        assert_eq!(executed.status, "committed");
        assert!(tree
            .root
            .join("LocalAppData/AI Video Editor/Config/settings.json")
            .exists());
        let migrated_settings = fs::read_to_string(
            tree.root
                .join("LocalAppData/AI Video Editor/Config/settings.json"),
        )
        .unwrap();
        assert!(!migrated_settings.contains("do-not-log-this"));
        assert!(
            tree.root
                .join("User/Documents/AI Video Editor/Projects/lesson.legacy-")
                .exists()
                || tree
                    .root
                    .join("User/Documents/AI Video Editor/Projects/lesson.json")
                    .exists()
        );
        assert!(existing.exists());
        let rerun_inventory = scan_legacy_roots(&tree.roots).unwrap();
        let rerun = preview_migration(&rerun_inventory, &options).unwrap();
        let rerun_output = execute_migration(&rerun, &options).unwrap();
        assert_eq!(rerun_output.status, "committed");
    }

    #[test]
    fn migration_rejects_insufficient_space_and_path_escape() {
        let tree = SyntheticTree::new();
        tree.write("LocalAppData/AI Video Editor/uploads/clip.mp4", b"clip");
        let inventory = scan_legacy_roots(&tree.roots).unwrap();
        let low = preview_migration(
            &inventory,
            &MigrationOptions {
                available_space_override_bytes: Some(0),
                ..MigrationOptions::default()
            },
        )
        .unwrap();
        assert!(!low.preflight.disk_space_ok);
        assert!(execute_migration(&low, &MigrationOptions::default()).is_err());
        assert!(safe_join(&tree.roots.local_app_data, Path::new("..\\escape")).is_err());
        let mut escaped = low.clone();
        escaped.plan[0].destination_path =
            Some(tree.root.join("Outside").to_string_lossy().to_string());
        assert!(execute_migration(&escaped, &MigrationOptions::default()).is_err());
    }

    #[test]
    fn cleanup_requires_approval_and_preserves_valuable_data_by_default() {
        let tree = SyntheticTree::new();
        let runtime = tree.write("LocalAppData/AI Video Editor/runtime/file.bin", b"runtime");
        let upload = tree.write("LocalAppData/AI Video Editor/uploads/clip.mp4", b"content");
        let inventory = scan_legacy_roots(&tree.roots).unwrap();
        assert!(cleanup_legacy(&inventory, &CleanupOptions::default()).is_err());
        let report = cleanup_legacy(
            &inventory,
            &CleanupOptions {
                approved: true,
                ..CleanupOptions::default()
            },
        )
        .unwrap();
        assert!(!runtime.exists());
        assert!(upload.exists());
        assert!(report
            .preserved_paths
            .iter()
            .any(|path| path.contains("uploads")));
        assert!(cleanup_legacy(
            &inventory,
            &CleanupOptions {
                approved: true,
                full_wipe_confirmed: true,
                confirmation: Some(FULL_WIPE_CONFIRMATION.to_string()),
                ..CleanupOptions::default()
            }
        )
        .is_ok());
    }

    #[test]
    fn rollback_and_recovery_keep_journal_machine_readable() {
        let tree = SyntheticTree::new();
        tree.write("LocalAppData/AI Video Editor/uploads/clip.mp4", b"clip");
        let inventory = scan_legacy_roots(&tree.roots).unwrap();
        let preview = preview_migration(&inventory, &MigrationOptions::default()).unwrap();
        let interrupted = execute_migration(
            &preview,
            &MigrationOptions {
                failure_after_steps: Some(0),
                ..MigrationOptions::default()
            },
        );
        assert!(interrupted.is_err());
        let journal = tree
            .root
            .join("LocalAppData/AI Video Editor/State/migration-journal.json");
        assert!(journal.exists());
        let value: Value = serde_json::from_slice(&fs::read(&journal).unwrap()).unwrap();
        assert_eq!(
            value.get("schemaVersion").and_then(Value::as_str),
            Some(MIGRATION_JOURNAL_SCHEMA)
        );
        let recovered = recover_migration(&tree.roots).unwrap();
        assert!(recovered.is_some());
        let mut clean_preview = preview_migration(
            &scan_legacy_roots(&tree.roots).unwrap(),
            &MigrationOptions::default(),
        )
        .unwrap();
        clean_preview.journal_path = Some(journal.to_string_lossy().to_string());
        let rolled = rollback_migration(&clean_preview).unwrap();
        assert_eq!(rolled.status, "rolled-back");
    }

    #[test]
    fn uninstall_default_preserves_user_data_and_full_wipe_is_confirmed() {
        let tree = SyntheticTree::new();
        tree.mkdir("ProgramFiles/AI Video Editor/Shell");
        tree.write(
            "ProgramFiles/AI Video Editor/Shell/AI Video Editor Desktop V2.exe",
            b"shell",
        );
        tree.write("LocalAppData/AI Video Editor/uploads/clip.mp4", b"content");
        tree.write(
            "User/Documents/AI Video Editor/Projects/project.json",
            b"project",
        );
        let plan = build_uninstall_plan(&tree.roots).unwrap();
        assert_eq!(
            plan.default_choice,
            "remove-shell-runtime-preserve-user-data"
        );
        let dry = execute_uninstall(
            &plan,
            &UninstallOptions {
                approved: true,
                dry_run: true,
                ..UninstallOptions::default()
            },
        )
        .unwrap();
        assert!(dry
            .preserved_paths
            .iter()
            .any(|path| path.contains("uploads")));
        assert!(execute_uninstall(
            &plan,
            &UninstallOptions {
                approved: true,
                remove_all_user_data: true,
                confirmation: Some("wrong".to_string()),
                ..UninstallOptions::default()
            }
        )
        .is_err());
        let full = execute_uninstall(
            &plan,
            &UninstallOptions {
                approved: true,
                remove_all_user_data: true,
                confirmation: Some(FULL_WIPE_CONFIRMATION.to_string()),
                dry_run: true,
                ..UninstallOptions::default()
            },
        )
        .unwrap();
        assert!(full.remove_all_user_data);
    }

    #[test]
    fn repair_plan_restores_shortcuts_without_touching_user_content() {
        let tree = SyntheticTree::new();
        tree.mkdir("ProgramFiles/AI Video Editor/Shell");
        tree.write(
            "ProgramFiles/AI Video Editor/Shell/AI Video Editor Desktop V2.exe",
            b"shell",
        );
        let project = tree.write("User/Documents/AI Video Editor/Projects/p.json", b"project");
        let report = repair_v2(
            &tree.roots,
            &RepairOptions {
                restore_shortcuts: true,
                reset_disposable_cache: true,
                ..RepairOptions::default()
            },
        )
        .unwrap();
        assert!(report.installer_identity_valid);
        assert_eq!(report.shortcuts_restored.len(), 2);
        assert!(project.exists());
    }
}
