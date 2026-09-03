//! Durable, user-facing desktop provisioning and authoritative boot hydration.
//!
//! The component manager owns bytes and activation.  This coordinator owns the
//! commercial first-launch journey around those operations: one serialized
//! operation, durable ProgramData checkpoints, safe cancellation boundaries,
//! and a single reconciled snapshot consumed by React.

use crate::component_manager::{ComponentManager, ComponentStatusResult, SourcePolicy};
use crate::desktop_v2::{get_canonical_paths, ShellBootState, USER_DATA_DIRECTORY};
use crate::setup_center::{self, BundledCatalogDiscovery};
use crate::supervisor::{SupervisorState, SupervisorStatus};
use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, State};

pub const BOOT_SNAPSHOT_SCHEMA: &str = "desktop.boot-snapshot.v1";
pub const PROVISIONING_JOURNAL_SCHEMA: &str = "desktop.provisioning-journal.v1";
pub const FIRST_LAUNCH_SCHEMA: &str = "desktop.first-launch.v1";
const JOURNAL_FILE: &str = "current.json";
const FIRST_LAUNCH_FILE: &str = "first-launch.json";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum DesktopHydrationRoute {
    Booting,
    NeedsCoreSetup,
    ResumableSetup,
    StartingEngine,
    NeedsOptionalAiChoice,
    Ready,
    RepairRequired,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ProvisioningOperationKind {
    CoreSetup,
    LocalTranscriptionRuntime,
    LocalTranscriptionModel,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ProvisioningState {
    Running,
    Cancelling,
    Cancelled,
    Interrupted,
    Failed,
    Completed,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "kebab-case")]
pub enum ProvisioningCheckpoint {
    Discovered,
    CatalogReconciled,
    Downloading,
    Downloaded,
    Verified,
    Staged,
    Activated,
    Complete,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ProvisioningJournal {
    pub schema_version: String,
    pub operation_id: String,
    pub operation_kind: ProvisioningOperationKind,
    pub target_id: String,
    pub state: ProvisioningState,
    pub checkpoint: ProvisioningCheckpoint,
    pub phase_label: String,
    pub bytes_downloaded: u64,
    pub total_bytes: u64,
    pub percent: u8,
    pub cancel_requested: bool,
    pub in_atomic_section: bool,
    pub retry_count: u8,
    pub last_error_code: Option<String>,
    pub updated_at_epoch_ms: u128,
}

impl ProvisioningJournal {
    fn new(kind: ProvisioningOperationKind, target_id: String, total_bytes: u64) -> Self {
        let now = now_epoch_ms();
        Self {
            schema_version: PROVISIONING_JOURNAL_SCHEMA.to_string(),
            operation_id: format!("provision-{now}"),
            operation_kind: kind,
            target_id,
            state: ProvisioningState::Running,
            checkpoint: ProvisioningCheckpoint::Discovered,
            phase_label: "Preparing setup".to_string(),
            bytes_downloaded: 0,
            total_bytes,
            percent: 0,
            cancel_requested: false,
            in_atomic_section: false,
            retry_count: 0,
            last_error_code: None,
            updated_at_epoch_ms: now,
        }
    }

    fn active(&self) -> bool {
        matches!(
            self.state,
            ProvisioningState::Running | ProvisioningState::Cancelling
        )
    }

    fn resumable(&self) -> bool {
        matches!(
            self.state,
            ProvisioningState::Running
                | ProvisioningState::Cancelling
                | ProvisioningState::Interrupted
                | ProvisioningState::Failed
        )
    }

    fn update_truthful_progress(&mut self) {
        self.percent = match self.checkpoint {
            ProvisioningCheckpoint::Discovered => 0,
            ProvisioningCheckpoint::CatalogReconciled => 5,
            ProvisioningCheckpoint::Downloading => {
                if self.total_bytes == 0 {
                    5
                } else {
                    let ratio = self.bytes_downloaded.min(self.total_bytes) as f64
                        / self.total_bytes as f64;
                    (5.0 + ratio * 70.0).round() as u8
                }
            }
            ProvisioningCheckpoint::Downloaded => 75,
            ProvisioningCheckpoint::Verified => 85,
            ProvisioningCheckpoint::Staged => 92,
            ProvisioningCheckpoint::Activated => 98,
            ProvisioningCheckpoint::Complete => 100,
        };
        if self.state == ProvisioningState::Completed {
            self.percent = 100;
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct FirstLaunchState {
    pub schema_version: String,
    pub optional_ai_choice: Option<String>,
    pub completed: bool,
    pub updated_at_epoch_ms: u128,
}

impl Default for FirstLaunchState {
    fn default() -> Self {
        Self {
            schema_version: FIRST_LAUNCH_SCHEMA.to_string(),
            optional_ai_choice: None,
            completed: false,
            updated_at_epoch_ms: now_epoch_ms(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BootCatalogSummary {
    pub available: bool,
    pub trusted: bool,
    pub auto_discovered: bool,
    pub source: Option<String>,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopBootSnapshot {
    pub schema_version: String,
    pub hydration_complete: bool,
    pub reconciled: bool,
    pub route: DesktopHydrationRoute,
    pub generated_at_epoch_ms: u128,
    pub shell_boot_state: ShellBootState,
    pub core_components: Vec<ComponentStatusResult>,
    pub catalog: BootCatalogSummary,
    pub provisioning: Option<ProvisioningJournal>,
    pub supervisor: SupervisorStatus,
    pub first_launch: FirstLaunchState,
    pub friendly_title: String,
    pub friendly_detail: String,
    pub remediation_codes: Vec<String>,
}

pub struct ProvisioningCoordinator {
    root: PathBuf,
    gate: Mutex<()>,
}

impl Default for ProvisioningCoordinator {
    fn default() -> Self {
        let paths = get_canonical_paths();
        Self::at(
            PathBuf::from(paths.program_data_root)
                .join(USER_DATA_DIRECTORY)
                .join("Provisioning"),
        )
    }
}

impl ProvisioningCoordinator {
    pub fn at(root: PathBuf) -> Self {
        Self {
            root,
            gate: Mutex::new(()),
        }
    }

    fn journal_path(&self) -> PathBuf {
        self.root.join("operations").join(JOURNAL_FILE)
    }

    pub fn status(&self) -> Result<Option<ProvisioningJournal>, String> {
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        self.load_unlocked()
    }

    pub fn begin(
        &self,
        kind: ProvisioningOperationKind,
        target_id: String,
        total_bytes: u64,
    ) -> Result<ProvisioningJournal, String> {
        validate_target(&target_id)?;
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        if self
            .load_unlocked()?
            .as_ref()
            .is_some_and(ProvisioningJournal::active)
        {
            return Err(
                "PROVISIONING_BUSY: finish or cancel the current setup operation first."
                    .to_string(),
            );
        }
        let journal = ProvisioningJournal::new(kind, target_id, total_bytes);
        self.persist_unlocked(&journal)?;
        Ok(journal)
    }

    pub fn retry(&self) -> Result<ProvisioningJournal, String> {
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        let mut journal = self
            .load_unlocked()?
            .ok_or_else(|| "PROVISIONING_NOT_FOUND".to_string())?;
        if journal.active() || journal.state == ProvisioningState::Completed {
            return Err("PROVISIONING_RETRY_NOT_ALLOWED".to_string());
        }
        journal.state = ProvisioningState::Running;
        journal.cancel_requested = false;
        journal.in_atomic_section = false;
        journal.retry_count = journal.retry_count.saturating_add(1);
        journal.last_error_code = None;
        journal.phase_label = "Resuming safely".to_string();
        journal.updated_at_epoch_ms = now_epoch_ms();
        journal.update_truthful_progress();
        self.persist_unlocked(&journal)?;
        Ok(journal)
    }

    pub fn cancel(&self) -> Result<ProvisioningJournal, String> {
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        let mut journal = self
            .load_unlocked()?
            .ok_or_else(|| "PROVISIONING_NOT_FOUND".to_string())?;
        if !journal.active() {
            return Ok(journal);
        }
        journal.cancel_requested = true;
        if journal.in_atomic_section {
            journal.state = ProvisioningState::Cancelling;
            journal.phase_label = "Finishing a safe install step".to_string();
        } else {
            journal.state = ProvisioningState::Cancelled;
            journal.phase_label = "Setup stopped safely".to_string();
        }
        journal.updated_at_epoch_ms = now_epoch_ms();
        self.persist_unlocked(&journal)?;
        Ok(journal)
    }

    pub fn complete(&self) -> Result<ProvisioningJournal, String> {
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        let mut journal = self
            .load_unlocked()?
            .ok_or_else(|| "PROVISIONING_NOT_FOUND".to_string())?;
        if journal.cancel_requested {
            journal.state = ProvisioningState::Cancelled;
            journal.phase_label = "Setup stopped safely".to_string();
        } else {
            journal.checkpoint = ProvisioningCheckpoint::Complete;
            journal.state = ProvisioningState::Completed;
            journal.phase_label = "Ready".to_string();
        }
        journal.in_atomic_section = false;
        journal.updated_at_epoch_ms = now_epoch_ms();
        journal.update_truthful_progress();
        self.persist_unlocked(&journal)?;
        Ok(journal)
    }

    pub fn fail(&self, error_code: String) -> Result<ProvisioningJournal, String> {
        validate_target(&error_code)?;
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        let mut journal = self
            .load_unlocked()?
            .ok_or_else(|| "PROVISIONING_NOT_FOUND".to_string())?;
        journal.state = ProvisioningState::Failed;
        journal.in_atomic_section = false;
        journal.last_error_code = Some(error_code);
        journal.phase_label = "Setup needs attention".to_string();
        journal.updated_at_epoch_ms = now_epoch_ms();
        journal.update_truthful_progress();
        self.persist_unlocked(&journal)?;
        Ok(journal)
    }

    pub fn recover(&self) -> Result<Option<ProvisioningJournal>, String> {
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        let Some(mut journal) = self.load_unlocked()? else {
            return Ok(None);
        };
        if journal.active() {
            journal.in_atomic_section = false;
            if journal.cancel_requested {
                journal.state = ProvisioningState::Cancelled;
                journal.phase_label = "Setup stopped safely".to_string();
            } else {
                journal.state = ProvisioningState::Interrupted;
                journal.phase_label = "Setup can resume".to_string();
            }
            journal.updated_at_epoch_ms = now_epoch_ms();
            journal.update_truthful_progress();
            self.persist_unlocked(&journal)?;
        }
        Ok(Some(journal))
    }

    pub fn checkpoint(
        &self,
        checkpoint: ProvisioningCheckpoint,
        bytes_downloaded: u64,
    ) -> Result<ProvisioningJournal, String> {
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        let mut journal = self
            .load_unlocked()?
            .ok_or_else(|| "PROVISIONING_NOT_FOUND".to_string())?;
        if checkpoint < journal.checkpoint {
            return Err("PROVISIONING_CHECKPOINT_REGRESSION".to_string());
        }
        if journal.total_bytes > 0 && bytes_downloaded > journal.total_bytes {
            return Err("PROVISIONING_PROGRESS_INVALID".to_string());
        }
        if checkpoint == ProvisioningCheckpoint::Downloading
            && bytes_downloaded < journal.bytes_downloaded
        {
            return Err("PROVISIONING_PROGRESS_REGRESSION".to_string());
        }
        journal.checkpoint = checkpoint;
        journal.bytes_downloaded = bytes_downloaded;
        journal.updated_at_epoch_ms = now_epoch_ms();
        journal.update_truthful_progress();
        self.persist_unlocked(&journal)?;
        Ok(journal)
    }

    pub fn set_atomic_section(&self, active: bool) -> Result<ProvisioningJournal, String> {
        let _guard = self
            .gate
            .lock()
            .map_err(|_| "PROVISIONING_LOCK_POISONED".to_string())?;
        let mut journal = self
            .load_unlocked()?
            .ok_or_else(|| "PROVISIONING_NOT_FOUND".to_string())?;
        if !journal.active() {
            return Err("PROVISIONING_NOT_ACTIVE".to_string());
        }
        journal.in_atomic_section = active;
        if !active && journal.cancel_requested {
            journal.state = ProvisioningState::Cancelled;
            journal.phase_label = "Setup stopped safely".to_string();
        }
        journal.updated_at_epoch_ms = now_epoch_ms();
        self.persist_unlocked(&journal)?;
        Ok(journal)
    }

    fn load_unlocked(&self) -> Result<Option<ProvisioningJournal>, String> {
        let mut path = self.journal_path();
        let previous = path.with_extension("previous.json");
        if !path.exists() && previous.exists() {
            path = previous;
        }
        if !path.exists() {
            return Ok(None);
        }
        let bytes = fs::read(&path).map_err(|_| "PROVISIONING_JOURNAL_UNREADABLE".to_string())?;
        if bytes.len() > 256 * 1024 {
            return Err("PROVISIONING_JOURNAL_INVALID".to_string());
        }
        let journal: ProvisioningJournal = serde_json::from_slice(&bytes)
            .map_err(|_| "PROVISIONING_JOURNAL_INVALID".to_string())?;
        if journal.schema_version != PROVISIONING_JOURNAL_SCHEMA {
            return Err("PROVISIONING_JOURNAL_UNSUPPORTED".to_string());
        }
        Ok(Some(journal))
    }

    fn persist_unlocked(&self, journal: &ProvisioningJournal) -> Result<(), String> {
        atomic_write_json(&self.journal_path(), journal)
    }
}

fn validate_target(value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 96
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        return Err("PROVISIONING_TARGET_INVALID".to_string());
    }
    Ok(())
}

fn now_epoch_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_millis())
        .unwrap_or_default()
}

fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "PROVISIONING_PATH_INVALID".to_string())?;
    fs::create_dir_all(parent).map_err(|_| "PROVISIONING_STORAGE_NOT_WRITABLE".to_string())?;
    let temporary = path.with_extension(format!("{}.part", now_epoch_ms()));
    let bytes = serde_json::to_vec_pretty(value)
        .map_err(|_| "PROVISIONING_SERIALIZATION_FAILED".to_string())?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|_| "PROVISIONING_STORAGE_NOT_WRITABLE".to_string())?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| "PROVISIONING_STORAGE_NOT_WRITABLE".to_string())?;
    let previous = path.with_extension("previous.json");
    if previous.exists() {
        fs::remove_file(&previous).map_err(|_| "PROVISIONING_STORAGE_NOT_WRITABLE".to_string())?;
    }
    if path.exists() {
        fs::rename(path, &previous).map_err(|_| "PROVISIONING_STORAGE_NOT_WRITABLE".to_string())?;
    }
    if fs::rename(&temporary, path).is_err() {
        if previous.exists() {
            let _ = fs::rename(&previous, path);
        }
        return Err("PROVISIONING_STORAGE_NOT_WRITABLE".to_string());
    }
    if previous.exists() {
        let _ = fs::remove_file(previous);
    }
    Ok(())
}

fn first_launch_path() -> PathBuf {
    PathBuf::from(get_canonical_paths().user_state).join(FIRST_LAUNCH_FILE)
}

fn load_first_launch() -> FirstLaunchState {
    fs::read(first_launch_path())
        .ok()
        .and_then(|bytes| serde_json::from_slice::<FirstLaunchState>(&bytes).ok())
        .filter(|state| state.schema_version == FIRST_LAUNCH_SCHEMA)
        .unwrap_or_default()
}

#[tauri::command]
pub fn desktop_complete_optional_ai_choice(choice: String) -> Result<FirstLaunchState, String> {
    if !matches!(choice.as_str(), "local" | "cloud" | "decide-later") {
        return Err("OPTIONAL_AI_CHOICE_INVALID".to_string());
    }
    let state = FirstLaunchState {
        schema_version: FIRST_LAUNCH_SCHEMA.to_string(),
        optional_ai_choice: Some(choice),
        completed: true,
        updated_at_epoch_ms: now_epoch_ms(),
    };
    atomic_write_json(&first_launch_path(), &state)?;
    Ok(state)
}

#[tauri::command]
pub fn provisioning_begin(
    coordinator: State<'_, ProvisioningCoordinator>,
    operation_kind: ProvisioningOperationKind,
    target_id: String,
    total_bytes: u64,
) -> Result<ProvisioningJournal, String> {
    coordinator.begin(operation_kind, target_id, total_bytes)
}

#[tauri::command]
pub fn provisioning_status(
    coordinator: State<'_, ProvisioningCoordinator>,
) -> Result<Option<ProvisioningJournal>, String> {
    coordinator.status()
}

#[tauri::command]
pub fn provisioning_retry(
    coordinator: State<'_, ProvisioningCoordinator>,
) -> Result<ProvisioningJournal, String> {
    coordinator.retry()
}

#[tauri::command]
pub fn provisioning_cancel(
    coordinator: State<'_, ProvisioningCoordinator>,
) -> Result<ProvisioningJournal, String> {
    coordinator.cancel()
}

#[tauri::command]
pub fn provisioning_complete(
    coordinator: State<'_, ProvisioningCoordinator>,
) -> Result<ProvisioningJournal, String> {
    coordinator.complete()
}

#[tauri::command]
pub fn provisioning_fail(
    coordinator: State<'_, ProvisioningCoordinator>,
    error_code: String,
) -> Result<ProvisioningJournal, String> {
    coordinator.fail(error_code)
}

#[tauri::command]
pub fn provisioning_checkpoint(
    coordinator: State<'_, ProvisioningCoordinator>,
    checkpoint: ProvisioningCheckpoint,
    bytes_downloaded: u64,
) -> Result<ProvisioningJournal, String> {
    coordinator.checkpoint(checkpoint, bytes_downloaded)
}

#[tauri::command]
pub fn provisioning_set_atomic_section(
    coordinator: State<'_, ProvisioningCoordinator>,
    active: bool,
) -> Result<ProvisioningJournal, String> {
    coordinator.set_atomic_section(active)
}

fn status_for(manager: &ComponentManager, id: &str) -> ComponentStatusResult {
    manager
        .status(Some(id))
        .ok()
        .and_then(|mut items| items.pop())
        .unwrap_or(ComponentStatusResult {
            id: id.to_string(),
            display_name: None,
            version: None,
            state: "not-installed".to_string(),
            active_path: None,
            downloaded_bytes: 0,
            detail: "This required component still needs setup.".to_string(),
            remediation_codes: vec!["SETUP_REQUIRED".to_string()],
        })
}

fn friendly_copy(route: &DesktopHydrationRoute) -> (String, String) {
    match route {
        DesktopHydrationRoute::Booting => (
            "Opening your workspace".into(),
            "Checking the local tools you need.".into(),
        ),
        DesktopHydrationRoute::NeedsCoreSetup => (
            "Let’s finish setup".into(),
            "Install the core editing tools included with this release.".into(),
        ),
        DesktopHydrationRoute::ResumableSetup => (
            "Continue setup".into(),
            "Your previous progress is safe and ready to resume.".into(),
        ),
        DesktopHydrationRoute::StartingEngine => (
            "Starting your workspace".into(),
            "The editor will open as soon as its local services are ready.".into(),
        ),
        DesktopHydrationRoute::NeedsOptionalAiChoice => (
            "Choose how you want to use AI".into(),
            "You can work locally, connect a provider, or decide later.".into(),
        ),
        DesktopHydrationRoute::Ready => (
            "Your workspace is ready".into(),
            "Open the editor and continue creating.".into(),
        ),
        DesktopHydrationRoute::RepairRequired => (
            "A quick repair is needed".into(),
            "Your projects are safe. Repair the local app tools, then try again.".into(),
        ),
    }
}

fn cached_catalog_source_is_usable(catalog: &setup_center::SetupCatalogInfo) -> bool {
    if catalog.source != "offline-import" {
        return true;
    }
    let Some(source_path) = catalog.source_path.as_deref().map(Path::new) else {
        return false;
    };
    let Some(catalog_dir) = source_path.parent() else {
        return false;
    };
    let Some(handoff_root) = catalog_dir.parent() else {
        return false;
    };
    source_path.is_file()
        && catalog_dir
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.eq_ignore_ascii_case("Catalog"))
        && handoff_root.join("Components").is_dir()
}

fn catalog_needs_reconciliation(
    catalog: Option<&setup_center::SetupCatalogInfo>,
    discovery: Option<&BundledCatalogDiscovery>,
    core_components: &[ComponentStatusResult],
) -> bool {
    discovery.is_some_and(|value| value.available)
        && (catalog.is_none()
            || catalog.is_some_and(|value| !cached_catalog_source_is_usable(value))
            || core_components.iter().any(|item| item.state != "active"))
}

fn boot_route_after_reconciliation(
    recovered: bool,
    core_components: &[ComponentStatusResult],
    catalog_available: bool,
    provisioning: Option<&ProvisioningJournal>,
    supervisor_ready: bool,
    first_launch_completed: bool,
) -> DesktopHydrationRoute {
    let activation_repair_required = core_components
        .iter()
        .any(|item| item.state == "repair-required");
    let core_ready = core_components.iter().all(|item| item.state == "active");
    let resumable = provisioning.is_some_and(ProvisioningJournal::resumable);
    if !recovered {
        DesktopHydrationRoute::RepairRequired
    } else if activation_repair_required {
        if catalog_available {
            DesktopHydrationRoute::ResumableSetup
        } else {
            DesktopHydrationRoute::RepairRequired
        }
    } else if resumable {
        DesktopHydrationRoute::ResumableSetup
    } else if !core_ready {
        DesktopHydrationRoute::NeedsCoreSetup
    } else if !supervisor_ready {
        DesktopHydrationRoute::StartingEngine
    } else if !first_launch_completed {
        DesktopHydrationRoute::NeedsOptionalAiChoice
    } else {
        DesktopHydrationRoute::Ready
    }
}

fn build_boot_snapshot(
    app: &AppHandle,
    coordinator: &ProvisioningCoordinator,
    supervisor_state: &SupervisorState,
) -> DesktopBootSnapshot {
    let mut remediation_codes = Vec::new();
    let provisioning = match coordinator.recover() {
        Ok(value) => value,
        Err(code) => {
            remediation_codes.push(code);
            None
        }
    };
    let paths = get_canonical_paths();
    let machine_root = PathBuf::from(&paths.program_data_root).join(USER_DATA_DIRECTORY);
    let manager = ComponentManager::new(machine_root);
    let mut recovered = manager.recover().is_ok();
    let mut core_components = vec![
        status_for(&manager, "aive-engine"),
        status_for(&manager, "ffmpeg"),
    ];
    let mut auto_discovered = false;
    let discovery = match setup_center::setup_discover_bundled_catalog(app.clone()) {
        Ok(value) => Some(value),
        Err(error) => {
            remediation_codes.push(error.code);
            None
        }
    };
    let mut catalog = setup_center::setup_get_catalog().ok().flatten();
    if catalog_needs_reconciliation(catalog.as_ref(), discovery.as_ref(), &core_components) {
        if let Ok(imported) = setup_center::setup_import_bundled_catalog(app.clone()) {
            catalog = Some(imported.catalog);
            auto_discovered = true;
            // Re-run activation recovery after the repaired handoff has
            // refreshed manifests and the persisted offline artifact root.
            recovered = manager.recover().is_ok();
            core_components = vec![
                status_for(&manager, "aive-engine"),
                status_for(&manager, "ffmpeg"),
            ];
        }
    }

    // A repaired installer may leave a valid retained component behind a
    // corrupt active version. Installed-runtime repair is source-independent
    // and can safely roll back without downloading or touching user projects.
    if recovered {
        for component in core_components
            .iter()
            .filter(|item| item.state == "repair-required")
        {
            if let Err(error) = manager.repair(&component.id, SourcePolicy::INSTALLED_RUNTIME, None)
            {
                remediation_codes.push(error.code);
            }
        }
        core_components = vec![
            status_for(&manager, "aive-engine"),
            status_for(&manager, "ffmpeg"),
        ];
    }
    if !recovered {
        remediation_codes.push("COMPONENT_RECOVERY_REQUIRED".to_string());
    }
    let supervisor = supervisor_state.status();
    let first_launch = load_first_launch();
    let route = boot_route_after_reconciliation(
        recovered,
        &core_components,
        catalog.is_some(),
        provisioning.as_ref(),
        supervisor.engine_ready,
        first_launch.completed,
    );
    let (friendly_title, friendly_detail) = friendly_copy(&route);
    let trusted = catalog.is_some();
    let source = catalog.as_ref().map(|value| value.source.clone());
    let catalog_detail = if trusted {
        "The included release catalog was verified.".to_string()
    } else if discovery.as_ref().is_some_and(|value| value.available) {
        "The included release catalog was found but still needs attention.".to_string()
    } else {
        "No included release catalog is available yet.".to_string()
    };
    let shell_boot_state = if route == DesktopHydrationRoute::RepairRequired {
        ShellBootState::RecoverableError
    } else if core_components.iter().all(|item| item.state == "active") {
        ShellBootState::EngineAvailable
    } else {
        ShellBootState::SetupRequired
    };

    DesktopBootSnapshot {
        schema_version: BOOT_SNAPSHOT_SCHEMA.to_string(),
        hydration_complete: true,
        reconciled: true,
        route,
        generated_at_epoch_ms: now_epoch_ms(),
        shell_boot_state,
        core_components,
        catalog: BootCatalogSummary {
            available: catalog.is_some(),
            trusted,
            auto_discovered,
            source,
            detail: catalog_detail,
        },
        provisioning,
        supervisor,
        first_launch,
        friendly_title,
        friendly_detail,
        remediation_codes,
    }
}

#[tauri::command]
pub fn desktop_boot_snapshot(
    app: AppHandle,
    coordinator: State<'_, ProvisioningCoordinator>,
    supervisor: State<'_, SupervisorState>,
) -> DesktopBootSnapshot {
    build_boot_snapshot(&app, &coordinator, &supervisor)
}

#[tauri::command]
pub fn desktop_hydrate(
    app: AppHandle,
    coordinator: State<'_, ProvisioningCoordinator>,
    supervisor: State<'_, SupervisorState>,
) -> DesktopBootSnapshot {
    build_boot_snapshot(&app, &coordinator, &supervisor)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn component(id: &str, state: &str) -> ComponentStatusResult {
        ComponentStatusResult {
            id: id.to_string(),
            display_name: None,
            version: None,
            state: state.to_string(),
            active_path: None,
            downloaded_bytes: 0,
            detail: String::new(),
            remediation_codes: Vec::new(),
        }
    }

    fn test_root(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!("aive-provisioning-{name}-{}", now_epoch_ms()))
    }

    #[test]
    fn progress_only_reports_durable_checkpoints() {
        let root = test_root("progress");
        let coordinator = ProvisioningCoordinator::at(root.clone());
        coordinator
            .begin(
                ProvisioningOperationKind::CoreSetup,
                "aive-engine".into(),
                100,
            )
            .unwrap();
        let downloaded = coordinator
            .checkpoint(ProvisioningCheckpoint::Downloading, 50)
            .unwrap();
        assert_eq!(downloaded.percent, 40);
        let verified = coordinator
            .checkpoint(ProvisioningCheckpoint::Verified, 100)
            .unwrap();
        assert_eq!(verified.percent, 85);
        assert!(coordinator
            .checkpoint(ProvisioningCheckpoint::Downloading, 100)
            .is_err());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn cancellation_waits_for_atomic_boundary_and_recovers_safely() {
        let root = test_root("cancel");
        let coordinator = ProvisioningCoordinator::at(root.clone());
        coordinator
            .begin(
                ProvisioningOperationKind::LocalTranscriptionModel,
                "whisper-small".into(),
                100,
            )
            .unwrap();
        coordinator
            .checkpoint(ProvisioningCheckpoint::Verified, 100)
            .unwrap();
        coordinator.set_atomic_section(true).unwrap();
        let cancelling = coordinator.cancel().unwrap();
        assert_eq!(cancelling.state, ProvisioningState::Cancelling);
        let recovered = coordinator.recover().unwrap().unwrap();
        assert_eq!(recovered.state, ProvisioningState::Cancelled);
        assert_eq!(recovered.percent, 85);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_and_model_operations_are_serialized() {
        let root = test_root("serialize");
        let coordinator = ProvisioningCoordinator::at(root.clone());
        coordinator
            .begin(
                ProvisioningOperationKind::LocalTranscriptionRuntime,
                "whisper-cpp".into(),
                0,
            )
            .unwrap();
        assert!(coordinator
            .begin(
                ProvisioningOperationKind::LocalTranscriptionModel,
                "whisper-small".into(),
                100
            )
            .is_err());
        coordinator.cancel().unwrap();
        assert!(coordinator
            .begin(
                ProvisioningOperationKind::LocalTranscriptionModel,
                "whisper-small".into(),
                100
            )
            .is_ok());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn repaired_activation_routes_to_resume_when_trusted_reinstall_is_available() {
        let broken = vec![
            component("aive-engine", "repair-required"),
            component("ffmpeg", "active"),
        ];
        assert_eq!(
            boot_route_after_reconciliation(true, &broken, true, None, false, false),
            DesktopHydrationRoute::ResumableSetup
        );
        assert_eq!(
            boot_route_after_reconciliation(true, &broken, false, None, false, false),
            DesktopHydrationRoute::RepairRequired
        );
    }

    #[test]
    fn recovered_components_progress_idempotently_through_start_and_first_launch() {
        let active = vec![
            component("aive-engine", "active"),
            component("ffmpeg", "active"),
        ];
        assert_eq!(
            boot_route_after_reconciliation(true, &active, true, None, false, false),
            DesktopHydrationRoute::StartingEngine
        );
        assert_eq!(
            boot_route_after_reconciliation(true, &active, true, None, true, false),
            DesktopHydrationRoute::NeedsOptionalAiChoice
        );
        assert_eq!(
            boot_route_after_reconciliation(true, &active, true, None, true, true),
            DesktopHydrationRoute::Ready
        );
    }

    #[test]
    fn sibling_catalog_is_reconciled_for_missing_or_partial_core() {
        let discovery = BundledCatalogDiscovery {
            available: true,
            path: Some("Catalog/offline-catalog.json".to_string()),
            default_path: None,
            handoff_root: Some("handoff".to_string()),
            detail: String::new(),
        };
        let partial = vec![
            component("aive-engine", "available"),
            component("ffmpeg", "not-installed"),
        ];
        assert!(catalog_needs_reconciliation(
            None,
            Some(&discovery),
            &partial
        ));
        assert!(!catalog_needs_reconciliation(None, None, &partial));
    }
}
