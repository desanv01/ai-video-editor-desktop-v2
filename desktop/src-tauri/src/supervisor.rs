//! Phase 5 native engine supervisor.
//!
//! The supervisor owns the only native engine process started by Desktop V2.
//! It resolves launch inputs from verified ProgramData activation records,
//! keeps the per-launch bearer token in memory, authenticates all probes, and
//! exposes a safe status/bridge surface to the WebView.  No supervisor state
//! serialized to disk or emitted to the UI contains the bearer token.

use crate::component_manager::{
    ComponentError, ComponentManager, ComponentType, SourcePolicy, VerifiedActiveComponent,
};
use crate::contracts::{
    parse_capabilities, parse_health_readiness, CapabilitiesPayload, HealthOverallState,
    HealthReadinessPayload,
};
use crate::desktop_v2::get_canonical_paths;
use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use reqwest::blocking::{Client, Response};
use reqwest::Method;
use ring::rand::{SecureRandom, SystemRandom};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, State};

pub const SUPERVISOR_STATUS_EVENT: &str = "desktop-engine-status";
pub const SUPERVISOR_CAPABILITIES_EVENT: &str = "desktop-engine-capabilities";
pub const STARTUP_HANDSHAKE_PROTOCOL: &str = "desktop.engine-handshake.v1";
pub const SUPERVISOR_STATUS_SCHEMA: &str = "desktop.supervisor-status.v1";
pub const SUPERVISOR_DIAGNOSTICS_SCHEMA: &str = "desktop.supervisor-diagnostics.v1";
const ENGINE_COMPONENT_ID: &str = "aive-engine";
const FFMPEG_COMPONENT_ID: &str = "ffmpeg";
const MAX_RETRIES: u32 = 3;
const STARTUP_DEADLINE: Duration = Duration::from_secs(120);
const STOP_GRACE_PERIOD: Duration = Duration::from_secs(10);
const MAX_HANDSHAKE_LINE_BYTES: usize = 16 * 1024;
const MAX_OUTPUT_LINE_BYTES: usize = 64 * 1024;
const MAX_RESPONSE_BYTES: usize = 32 * 1024 * 1024;
const MAX_REQUEST_BYTES: usize = 128 * 1024 * 1024;
const MAX_LOG_BYTES: u64 = 1024 * 1024;
const MAX_LOG_ROTATIONS: usize = 3;
const RECOVERY_MAX_AGE: Duration = Duration::from_secs(24 * 60 * 60);
const BACKOFFS: [Duration; 3] = [
    Duration::from_millis(250),
    Duration::from_secs(1),
    Duration::from_secs(3),
];

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum SupervisorPhase {
    Stopped,
    Resolving,
    Starting,
    WaitingForHandshake,
    Probing,
    Ready,
    Degraded,
    Stopping,
    CrashedBackoff,
    RepairRequired,
    Fatal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SupervisorEvent {
    Resolve,
    Launch,
    WaitForHandshake,
    Probe,
    Ready,
    Degraded,
    Stop,
    Crash,
    Repair,
    Fatal,
    Reset,
}

/// Pure state transition helper used by the worker and deterministic tests.
/// Invalid events leave the state unchanged; callers must explicitly reset a
/// terminal state before retrying it.
pub fn transition_state(state: SupervisorPhase, event: SupervisorEvent) -> SupervisorPhase {
    match (state, event) {
        (_, SupervisorEvent::Stop) => SupervisorPhase::Stopping,
        (_, SupervisorEvent::Repair) => SupervisorPhase::RepairRequired,
        (_, SupervisorEvent::Fatal) => SupervisorPhase::Fatal,
        (_, SupervisorEvent::Reset) => SupervisorPhase::Stopped,
        (SupervisorPhase::Stopped, SupervisorEvent::Resolve)
        | (SupervisorPhase::CrashedBackoff, SupervisorEvent::Resolve) => SupervisorPhase::Resolving,
        (SupervisorPhase::Resolving, SupervisorEvent::Launch)
        | (SupervisorPhase::CrashedBackoff, SupervisorEvent::Launch) => SupervisorPhase::Starting,
        (SupervisorPhase::Starting, SupervisorEvent::WaitForHandshake) => {
            SupervisorPhase::WaitingForHandshake
        }
        (SupervisorPhase::WaitingForHandshake, SupervisorEvent::Probe) => SupervisorPhase::Probing,
        (SupervisorPhase::Probing, SupervisorEvent::Ready) => SupervisorPhase::Ready,
        (SupervisorPhase::Probing, SupervisorEvent::Degraded) => SupervisorPhase::Degraded,
        (SupervisorPhase::Ready | SupervisorPhase::Degraded, SupervisorEvent::Crash) => {
            SupervisorPhase::CrashedBackoff
        }
        (current, _) => current,
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StartupHandshake {
    pub handshake_type: String,
    pub protocol_version: String,
    pub host: String,
    pub port: u16,
    pub pid: u32,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SupervisorStatus {
    pub schema_version: String,
    pub state: SupervisorPhase,
    pub engine_ready: bool,
    pub component_id: Option<String>,
    pub component_version: Option<String>,
    pub host: Option<String>,
    pub port: Option<u16>,
    pub pid: Option<u32>,
    pub protocol_version: Option<String>,
    pub retry_count: u32,
    pub max_retries: u32,
    pub detail: String,
    pub remediation_codes: Vec<String>,
    pub last_error: Option<String>,
    pub next_retry_at_epoch_ms: Option<u128>,
    pub capabilities: Option<CapabilitiesPayload>,
    pub log_path: Option<String>,
    pub rollback_requested: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SupervisorDiagnostics {
    pub schema_version: String,
    pub status: SupervisorStatus,
    pub owned_process: bool,
    pub recovery_metadata_path: String,
    pub stale_recovery_metadata: bool,
    pub log_tail: Vec<String>,
    pub session_policy: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineApiRequest {
    pub method: String,
    pub path: String,
    #[serde(default)]
    pub body_base64: Option<String>,
    #[serde(default)]
    pub content_type: Option<String>,
    #[serde(default = "default_bridge_timeout_ms")]
    pub timeout_ms: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineApiResponse {
    pub status: u16,
    pub headers: HashMap<String, String>,
    pub body_base64: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct RecoveryMetadata {
    schema_version: String,
    state: SupervisorPhase,
    component_id: Option<String>,
    component_version: Option<String>,
    retry_count: u32,
    last_exit_code: Option<i32>,
    updated_at_epoch_ms: u128,
    rollback_requested: bool,
}

#[derive(Debug, Clone)]
struct SessionSecrets {
    session_id: String,
    bearer_token: String,
}

#[derive(Debug, Clone)]
struct LaunchBundle {
    engine: VerifiedActiveComponent,
    ffmpeg: VerifiedActiveComponent,
    user_data_root: PathBuf,
    user_logs_root: PathBuf,
}

#[derive(Debug, Clone)]
struct StartupFailure {
    code: String,
    message: String,
    retryable: bool,
    repair_required: bool,
    remediation_codes: Vec<String>,
}

impl StartupFailure {
    fn retryable(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.to_string(),
            message: message.into(),
            retryable: true,
            repair_required: false,
            remediation_codes: vec!["RESTART_REQUIRED".to_string()],
        }
    }

    fn repair(code: &str, message: impl Into<String>, remediation: &str) -> Self {
        Self {
            code: code.to_string(),
            message: message.into(),
            retryable: false,
            repair_required: true,
            remediation_codes: vec![remediation.to_string()],
        }
    }

    fn fatal(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.to_string(),
            message: message.into(),
            retryable: false,
            repair_required: false,
            remediation_codes: vec!["RESTART_REQUIRED".to_string()],
        }
    }
}

struct SupervisorRuntime {
    status: SupervisorStatus,
    process: Option<Arc<OwnedProcess>>,
    session: Option<SessionSecrets>,
    stop_requested: Option<Arc<AtomicBool>>,
    start_in_progress: bool,
    stop_in_progress: bool,
    restart_after_stop: bool,
    app_closed: bool,
    recovery_path: PathBuf,
    stale_recovery_metadata: bool,
}

#[derive(Clone)]
pub struct SupervisorState {
    inner: Arc<Mutex<SupervisorRuntime>>,
}

impl Default for SupervisorState {
    fn default() -> Self {
        Self::new()
    }
}

impl SupervisorState {
    pub fn new() -> Self {
        let paths = get_canonical_paths();
        let recovery_path = PathBuf::from(&paths.user_state).join("supervisor-recovery.json");
        let (stale, recovered_retry_count, recovered_rollback) = load_recovery(&recovery_path);
        let detail = if stale {
            "No active engine process is owned; stale recovery metadata was discarded.".to_string()
        } else if recovered_retry_count > 0 {
            "Supervisor is stopped; bounded recovery history is available for this launch."
                .to_string()
        } else {
            "No native engine process is owned.".to_string()
        };
        Self {
            inner: Arc::new(Mutex::new(SupervisorRuntime {
                status: SupervisorStatus {
                    schema_version: SUPERVISOR_STATUS_SCHEMA.to_string(),
                    state: SupervisorPhase::Stopped,
                    engine_ready: false,
                    component_id: None,
                    component_version: None,
                    host: None,
                    port: None,
                    pid: None,
                    protocol_version: None,
                    retry_count: recovered_retry_count,
                    max_retries: MAX_RETRIES,
                    detail,
                    remediation_codes: Vec::new(),
                    last_error: None,
                    next_retry_at_epoch_ms: None,
                    capabilities: None,
                    log_path: None,
                    rollback_requested: recovered_rollback,
                },
                process: None,
                session: None,
                stop_requested: None,
                start_in_progress: false,
                stop_in_progress: false,
                restart_after_stop: false,
                app_closed: false,
                recovery_path,
                stale_recovery_metadata: stale,
            })),
        }
    }

    pub fn status(&self) -> SupervisorStatus {
        self.inner
            .lock()
            .expect("supervisor state lock poisoned")
            .status
            .clone()
    }

    pub fn diagnostics(&self) -> SupervisorDiagnostics {
        let (status, owned_process, recovery_path, stale_recovery) = {
            let runtime = self.inner.lock().expect("supervisor state lock poisoned");
            (
                runtime.status.clone(),
                runtime.process.is_some(),
                runtime.recovery_path.clone(),
                runtime.stale_recovery_metadata,
            )
        };
        let log_tail = status
            .log_path
            .as_deref()
            .map(read_log_tail)
            .unwrap_or_default();
        SupervisorDiagnostics {
            schema_version: SUPERVISOR_DIAGNOSTICS_SCHEMA.to_string(),
            status,
            owned_process,
            recovery_metadata_path: redact_path(&recovery_path),
            stale_recovery_metadata: stale_recovery,
            log_tail,
            session_policy: "Bearer token is generated per launch, held only in supervisor memory, and rotated on every restart.".to_string(),
        }
    }

    pub fn start(&self, app: AppHandle) -> SupervisorStatus {
        let should_spawn = {
            let mut runtime = self.inner.lock().expect("supervisor state lock poisoned");
            if start_request_is_blocked(
                runtime.start_in_progress,
                runtime.stop_in_progress,
                runtime.app_closed,
                runtime.status.state,
            ) {
                return runtime.status.clone();
            }
            runtime.start_in_progress = true;
            runtime.stop_requested = Some(Arc::new(AtomicBool::new(false)));
            runtime.status.state = transition_state(runtime.status.state, SupervisorEvent::Resolve);
            runtime.status.engine_ready = false;
            runtime.status.detail =
                "Resolving verified active core-engine and FFmpeg components.".to_string();
            runtime.status.last_error = None;
            runtime.status.remediation_codes.clear();
            runtime.status.next_retry_at_epoch_ms = None;
            persist_recovery(&runtime);
            true
        };
        if should_spawn {
            emit_status(&app, &self.status());
            let state = self.clone();
            thread::spawn(move || run_startup(state, app));
        }
        self.status()
    }

    pub fn retry(&self, app: AppHandle) -> SupervisorStatus {
        {
            let mut runtime = self.inner.lock().expect("supervisor state lock poisoned");
            if runtime.start_in_progress || runtime.stop_in_progress || runtime.app_closed {
                return runtime.status.clone();
            }
            runtime.status.retry_count = 0;
            runtime.status.rollback_requested = false;
            runtime.status.last_error = None;
            runtime.status.remediation_codes.clear();
            runtime.status.state = SupervisorPhase::Stopped;
            runtime.status.detail =
                "Manual retry requested; resolving activated components again.".to_string();
            persist_recovery(&runtime);
        }
        self.start(app)
    }

    pub fn restart(&self, app: AppHandle) -> SupervisorStatus {
        let (process, session, stop_flag, spawn_stop_worker) = {
            let mut runtime = self.inner.lock().expect("supervisor state lock poisoned");
            if runtime.stop_in_progress || runtime.app_closed {
                return runtime.status.clone();
            }
            runtime.restart_after_stop = true;
            let stop_flag = runtime
                .stop_requested
                .get_or_insert_with(|| Arc::new(AtomicBool::new(false)))
                .clone();
            stop_flag.store(true, Ordering::SeqCst);
            runtime.status.state = transition_state(runtime.status.state, SupervisorEvent::Stop);
            runtime.status.engine_ready = false;
            runtime.status.retry_count = 0;
            runtime.status.rollback_requested = false;
            runtime.status.last_error = None;
            runtime.status.detail =
                "Restart requested; stopping the owned engine process.".to_string();
            runtime.status.remediation_codes.clear();
            runtime.stop_in_progress = true;
            (
                runtime.process.clone(),
                runtime.session.clone(),
                stop_flag,
                true,
            )
        };
        let _ = stop_flag;
        emit_status(&app, &self.status());
        if spawn_stop_worker {
            let state = self.clone();
            thread::spawn(move || stop_worker(state, app, process, session));
        }
        self.status()
    }

    pub fn stop(&self, app: AppHandle) -> SupervisorStatus {
        let (process, session, should_spawn) = {
            let mut runtime = self.inner.lock().expect("supervisor state lock poisoned");
            if runtime.stop_in_progress {
                return runtime.status.clone();
            }
            if let Some(stop_flag) = &runtime.stop_requested {
                stop_flag.store(true, Ordering::SeqCst);
            } else {
                runtime.stop_requested = Some(Arc::new(AtomicBool::new(true)));
            }
            runtime.restart_after_stop = false;
            runtime.status.state = transition_state(runtime.status.state, SupervisorEvent::Stop);
            runtime.status.engine_ready = false;
            runtime.status.detail = "Stopping the owned engine process.".to_string();
            runtime.status.remediation_codes.clear();
            runtime.stop_in_progress = true;
            (runtime.process.clone(), runtime.session.clone(), true)
        };
        emit_status(&app, &self.status());
        if should_spawn {
            let state = self.clone();
            thread::spawn(move || stop_worker(state, app, process, session));
        }
        self.status()
    }

    pub fn api_request(&self, request: EngineApiRequest) -> Result<EngineApiResponse, String> {
        validate_bridge_request(&request)?;
        let (port, session, ready) = {
            let runtime = self
                .inner
                .lock()
                .map_err(|_| "Supervisor state lock poisoned".to_string())?;
            (
                runtime.status.port,
                runtime.session.clone(),
                runtime.status.engine_ready && runtime.status.state == SupervisorPhase::Ready,
            )
        };
        if !ready {
            return Err("ENGINE_NOT_READY: the authenticated native engine bridge is locked until readiness.".to_string());
        }
        let port = port
            .ok_or_else(|| "ENGINE_NOT_READY: no owned loopback port is available.".to_string())?;
        let session = session
            .ok_or_else(|| "ENGINE_NOT_READY: the native session is not active.".to_string())?;
        let body = decode_body(request.body_base64.as_deref())?;
        let client = Client::builder()
            .timeout(Duration::from_millis(
                request.timeout_ms.clamp(100, 600_000),
            ))
            .build()
            .map_err(|error| format!("BRIDGE_CLIENT_FAILED: {error}"))?;
        let url = format!("http://127.0.0.1:{port}{}", request.path);
        let method = Method::from_bytes(request.method.as_bytes())
            .map_err(|_| "BRIDGE_METHOD_INVALID: unsupported HTTP method.".to_string())?;
        let mut builder = client
            .request(method, url)
            .header("Authorization", format!("Bearer {}", session.bearer_token));
        if let Some(content_type) = request.content_type.as_deref() {
            builder = builder.header("Content-Type", content_type);
        }
        if let Some(body) = body {
            builder = builder.body(body);
        }
        let response = builder
            .send()
            .map_err(|error| format!("BRIDGE_REQUEST_FAILED: {error}"))?;
        response_to_bridge(response)
    }

    /// Internal JSON helper for Tauri-native workflows that must use the same
    /// authenticated bridge as the WebView without exposing a loopback URL.
    pub fn api_request_json<T: Serialize, R: DeserializeOwned>(
        &self,
        method: &str,
        path: &str,
        payload: Option<&T>,
    ) -> Result<R, String> {
        let body_base64 = payload
            .map(|value| {
                serde_json::to_vec(value)
                    .map(|bytes| BASE64.encode(bytes))
                    .map_err(|error| format!("BRIDGE_BODY_SERIALIZATION_FAILED: {error}"))
            })
            .transpose()?;
        let response = self.api_request(EngineApiRequest {
            method: method.to_string(),
            path: path.to_string(),
            body_base64,
            content_type: payload.map(|_| "application/json".to_string()),
            timeout_ms: default_bridge_timeout_ms(),
        })?;
        let body = BASE64.decode(response.body_base64).map_err(|_| {
            "BRIDGE_RESPONSE_INVALID: response body was not valid base64.".to_string()
        })?;
        if response.status >= 400 {
            return Err(format!(
                "BRIDGE_HTTP_{}: engine request was rejected.",
                response.status
            ));
        }
        serde_json::from_slice(&body)
            .map_err(|error| format!("BRIDGE_RESPONSE_SCHEMA_INVALID: {error}"))
    }

    pub fn stop_for_app_close(&self) {
        let (process, session) = {
            let mut runtime = self.inner.lock().expect("supervisor state lock poisoned");
            if let Some(flag) = &runtime.stop_requested {
                flag.store(true, Ordering::SeqCst);
            }
            runtime.app_closed = true;
            runtime.restart_after_stop = false;
            runtime.status.state = SupervisorPhase::Stopping;
            runtime.status.engine_ready = false;
            (runtime.process.take(), runtime.session.clone())
        };
        if let Some(process) = process {
            if let Some(session) = session.filter(|_| process.port() != 0) {
                request_graceful_shutdown(process.port(), &session.bearer_token);
                if !process.wait_for_exit(Duration::from_secs(2)) {
                    process.kill_owned();
                }
            } else {
                process.kill_owned();
            }
            let _ = process.wait_for_exit(Duration::from_secs(2));
        }
        if let Ok(mut runtime) = self.inner.lock() {
            runtime.session = None;
            runtime.start_in_progress = false;
            runtime.stop_in_progress = false;
            runtime.status.state = SupervisorPhase::Stopped;
            runtime.status.detail =
                "The Desktop V2 window closed; the owned engine tree was terminated.".to_string();
            persist_recovery(&runtime);
        }
    }
}

fn default_bridge_timeout_ms() -> u64 {
    30_000
}

fn start_request_is_blocked(
    start_in_progress: bool,
    stop_in_progress: bool,
    app_closed: bool,
    state: SupervisorPhase,
) -> bool {
    app_closed
        || start_in_progress
        || stop_in_progress
        || matches!(
            state,
            SupervisorPhase::Ready
                | SupervisorPhase::Degraded
                | SupervisorPhase::RepairRequired
                | SupervisorPhase::Fatal
        )
}

fn run_startup(state: SupervisorState, app: AppHandle) {
    loop {
        let stop_requested = state
            .inner
            .lock()
            .ok()
            .and_then(|runtime| runtime.stop_requested.clone())
            .map(|flag| flag.load(Ordering::SeqCst))
            .unwrap_or(true);
        if stop_requested {
            finish_stopped(
                &state,
                &app,
                "Startup was cancelled before the engine became ready.",
            );
            return;
        }

        let attempt_number = {
            let mut runtime = match state.inner.lock() {
                Ok(runtime) => runtime,
                Err(_) => return,
            };
            runtime.status.retry_count = runtime.status.retry_count.saturating_add(1);
            runtime.status.state = transition_state(runtime.status.state, SupervisorEvent::Launch);
            runtime.status.detail = format!(
                "Starting verified native engine (attempt {}/{MAX_RETRIES}).",
                runtime.status.retry_count
            );
            runtime.status.remediation_codes.clear();
            persist_recovery(&runtime);
            runtime.status.retry_count
        };
        emit_status(&app, &state.status());

        match startup_attempt(&state, &app) {
            Ok(outcome) => {
                let (process, phase) = {
                    let mut runtime = match state.inner.lock() {
                        Ok(runtime) => runtime,
                        Err(_) => return,
                    };
                    runtime.start_in_progress = false;
                    runtime.stop_in_progress = false;
                    runtime.status.state = match outcome {
                        StartupOutcome::Ready => SupervisorPhase::Ready,
                        StartupOutcome::Degraded => SupervisorPhase::Degraded,
                    };
                    runtime.status.engine_ready = matches!(outcome, StartupOutcome::Ready);
                    runtime.status.detail = match outcome {
                        StartupOutcome::Ready => "Authenticated native engine readiness confirmed.".to_string(),
                        StartupOutcome::Degraded => "Native engine is authenticated but one or more optional capabilities are degraded.".to_string(),
                    };
                    persist_recovery(&runtime);
                    (runtime.process.clone(), runtime.status.state)
                };
                emit_status(&app, &state.status());
                if let Some(process) = process {
                    start_exit_monitor(state.clone(), app.clone(), process);
                }
                if phase == SupervisorPhase::Ready {
                    if let Some(capabilities) = state.status().capabilities {
                        let _ = app.emit(SUPERVISOR_CAPABILITIES_EVENT, capabilities);
                    }
                }
                return;
            }
            Err(failure) => {
                cleanup_failed_process(&state);
                if failure.code == "STOP_REQUESTED" {
                    finish_stopped(&state, &app, &failure.message);
                    return;
                }
                if failure.repair_required {
                    set_terminal_failure(&state, &app, SupervisorPhase::RepairRequired, failure);
                    return;
                }
                if !failure.retryable || attempt_number >= MAX_RETRIES {
                    if attempt_number >= MAX_RETRIES {
                        request_last_known_good_rollback(&state);
                    }
                    set_terminal_failure(&state, &app, SupervisorPhase::Fatal, failure);
                    return;
                }
                let backoff = BACKOFFS[(attempt_number as usize - 1).min(BACKOFFS.len() - 1)];
                {
                    if let Ok(mut runtime) = state.inner.lock() {
                        runtime.status.state =
                            transition_state(runtime.status.state, SupervisorEvent::Crash);
                        runtime.status.engine_ready = false;
                        runtime.status.detail = format!(
                            "Engine startup failed; retrying after {} ms.",
                            backoff.as_millis()
                        );
                        runtime.status.last_error = Some(format!(
                            "{}: {}",
                            failure.code,
                            redact_sensitive(&failure.message, "")
                        ));
                        runtime.status.remediation_codes = failure.remediation_codes.clone();
                        runtime.status.next_retry_at_epoch_ms =
                            Some(now_epoch_ms() + backoff.as_millis() as u128);
                        persist_recovery(&runtime);
                    }
                }
                emit_status(&app, &state.status());
                if !sleep_with_stop(&state, backoff) {
                    finish_stopped(&state, &app, "Startup retry was cancelled.");
                    return;
                }
            }
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum StartupOutcome {
    Ready,
    Degraded,
}

fn startup_attempt(
    state: &SupervisorState,
    app: &AppHandle,
) -> Result<StartupOutcome, StartupFailure> {
    let bundle = resolve_launch_bundle()?;
    if stop_requested(state) {
        return Err(StartupFailure::repair(
            "STOP_REQUESTED",
            "Startup was cancelled by the user.",
            "ENGINE_NOT_RUNNING",
        ));
    }
    set_phase(
        state,
        app,
        SupervisorPhase::Starting,
        format!(
            "Launching {} {} from its verified active path.",
            bundle.engine.component_id, bundle.engine.component_version
        ),
        Vec::new(),
    );
    let session =
        new_session().map_err(|error| StartupFailure::fatal("SESSION_GENERATION_FAILED", error))?;
    let log_path =
        create_log_path(&bundle.user_logs_root, &session.session_id).map_err(|error| {
            StartupFailure::repair(
                "LOG_PATH_UNAVAILABLE",
                error.to_string(),
                "STORAGE_NOT_WRITABLE",
            )
        })?;
    let log = Arc::new(RotatingLog::new(log_path.clone()));
    let (process, handshake_rx) =
        launch_engine(&bundle, &session, log).map_err(|failure| failure)?;
    let expected_pid = process.pid;
    {
        let mut runtime = state.inner.lock().map_err(|_| {
            StartupFailure::fatal("SUPERVISOR_LOCK_FAILED", "Supervisor state lock poisoned.")
        })?;
        runtime.process = Some(process.clone());
        runtime.session = Some(session.clone());
        runtime.status.component_id = Some(bundle.engine.component_id.clone());
        runtime.status.component_version = Some(bundle.engine.component_version.clone());
        runtime.status.pid = Some(expected_pid);
        runtime.status.log_path = Some(log_path.to_string_lossy().to_string());
        persist_recovery(&runtime);
    }
    set_phase(
        state,
        app,
        transition_state(SupervisorPhase::Starting, SupervisorEvent::WaitForHandshake),
        "Waiting for the bounded token-free native startup handshake.".to_string(),
        Vec::new(),
    );
    let handshake = wait_for_handshake(
        &handshake_rx,
        &process,
        expected_pid,
        STARTUP_DEADLINE,
        state,
    )?;
    {
        let mut runtime = state.inner.lock().map_err(|_| {
            StartupFailure::fatal("SUPERVISOR_LOCK_FAILED", "Supervisor state lock poisoned.")
        })?;
        runtime.status.host = Some(handshake.host.clone());
        runtime.status.port = Some(handshake.port);
        runtime.status.protocol_version = Some(handshake.protocol_version.clone());
        persist_recovery(&runtime);
    }
    process.set_port(handshake.port);
    set_phase(
        state,
        app,
        transition_state(SupervisorPhase::WaitingForHandshake, SupervisorEvent::Probe),
        "Authenticating readiness and capability probes on the announced loopback port."
            .to_string(),
        Vec::new(),
    );
    let (health, capabilities, outcome) = probe_until_ready(
        &session,
        &handshake,
        &bundle.engine.component_version,
        state,
    )?;
    if capabilities.component_id != ENGINE_COMPONENT_ID
        || capabilities.component_version != bundle.engine.component_version
    {
        return Err(StartupFailure::repair(
            "CAPABILITIES_PROCESS_MISMATCH",
            "The native engine capabilities payload does not identify the verified active component.",
            "COMPONENT_VERSION_INCOMPATIBLE",
        ));
    }
    {
        let mut runtime = state.inner.lock().map_err(|_| {
            StartupFailure::fatal("SUPERVISOR_LOCK_FAILED", "Supervisor state lock poisoned.")
        })?;
        runtime.status.capabilities = Some(capabilities.clone());
        runtime.status.engine_ready = matches!(outcome, StartupOutcome::Ready);
        runtime.status.detail = health_detail(&health);
        runtime.status.remediation_codes = health
            .remediation_codes
            .iter()
            .map(|code| format!("{code:?}").to_ascii_uppercase())
            .collect();
        persist_recovery(&runtime);
    }
    let _ = app.emit(SUPERVISOR_CAPABILITIES_EVENT, capabilities);
    Ok(outcome)
}

fn resolve_launch_bundle() -> Result<LaunchBundle, StartupFailure> {
    let paths = get_canonical_paths();
    let machine_root = PathBuf::from(&paths.program_data_root).join("AI Video Editor");
    let manager = ComponentManager::new(machine_root);
    let engine = manager
        .verified_active_component(
            ENGINE_COMPONENT_ID,
            ComponentType::Backend,
            SourcePolicy::PRODUCTION,
        )
        .map_err(component_failure)?;
    let ffmpeg = manager
        .verified_active_component(
            FFMPEG_COMPONENT_ID,
            ComponentType::Ffmpeg,
            SourcePolicy::PRODUCTION,
        )
        .map_err(component_failure)?;
    let user_data_root = PathBuf::from(&paths.user_root);
    let user_logs_root = PathBuf::from(&paths.user_logs);
    fs::create_dir_all(&user_data_root).map_err(|error| {
        StartupFailure::repair(
            "USER_DATA_UNAVAILABLE",
            format!("Could not prepare the per-user engine data root: {error}"),
            "STORAGE_NOT_WRITABLE",
        )
    })?;
    Ok(LaunchBundle {
        engine,
        ffmpeg,
        user_data_root,
        user_logs_root,
    })
}

fn component_failure(error: ComponentError) -> StartupFailure {
    let remediation = if error.code == "ELEVATION_REQUIRED" {
        "STORAGE_NOT_WRITABLE"
    } else if error.code == "COMPONENT_NOT_ACTIVE" {
        "ENGINE_NOT_RUNNING"
    } else {
        "COMPONENT_VERSION_INCOMPATIBLE"
    };
    StartupFailure::repair(
        &error.code,
        "A verified active native component could not be resolved; Docker and global tools were not attempted.",
        remediation,
    )
}

fn new_session() -> Result<SessionSecrets, String> {
    let random = SystemRandom::new();
    let mut token_bytes = [0_u8; 32];
    random
        .fill(&mut token_bytes)
        .map_err(|_| "The operating system secure random source is unavailable.".to_string())?;
    let mut session_bytes = [0_u8; 12];
    random
        .fill(&mut session_bytes)
        .map_err(|_| "The operating system secure random source is unavailable.".to_string())?;
    Ok(SessionSecrets {
        session_id: base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(session_bytes),
        bearer_token: base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(token_bytes),
    })
}

fn launch_engine(
    bundle: &LaunchBundle,
    session: &SessionSecrets,
    log: Arc<RotatingLog>,
) -> Result<(Arc<OwnedProcess>, Receiver<StdoutEvent>), StartupFailure> {
    let mut command = Command::new(&bundle.engine.executable_path);
    let manifest_arguments = sanitize_manifest_arguments(&bundle.engine.arguments)?;
    command.args(manifest_arguments);
    command.args([
        "--port",
        "0",
        "--data-root",
        bundle.user_data_root.to_string_lossy().as_ref(),
        "--session-id",
        session.session_id.as_str(),
        "--ffmpeg-component-root",
        bundle.ffmpeg.active_path.as_str(),
    ]);
    if let Some(working_directory) = &bundle.engine.working_directory {
        command.current_dir(working_directory);
    } else {
        command.current_dir(&bundle.engine.active_path);
    }
    command
        .env("RUNTIME_PROFILE", "desktop-native")
        .env("AIVE_ENGINE_BEARER_TOKEN", &session.bearer_token)
        .env("DESKTOP_BEARER_TOKEN", &session.bearer_token)
        .env("AIVE_ENGINE_SESSION_ID", &session.session_id)
        .env("DESKTOP_SESSION_ID", &session.session_id)
        .env("AIVE_DESKTOP_DATA_ROOT", &bundle.user_data_root)
        .env("AIVE_FFMPEG_COMPONENT_ROOT", &bundle.ffmpeg.active_path)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let mut child = command.spawn().map_err(|error| {
        StartupFailure::repair(
            "COMPONENT_LAUNCH_FAILED",
            format!("The verified native engine entrypoint could not be started: {error}"),
            "COMPONENT_VERSION_INCOMPATIBLE",
        )
    })?;
    let pid = child.id();
    #[cfg(windows)]
    let job = match JobHandle::for_child(&child) {
        Ok(job) => Some(job),
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(StartupFailure::fatal(
                "PROCESS_OWNERSHIP_FAILED",
                format!("The native engine could not be attached to an owned Windows Job Object: {error}"),
            ));
        }
    };
    #[cfg(not(windows))]
    let job = None;
    let stdout = child.stdout.take().ok_or_else(|| {
        StartupFailure::fatal(
            "STDOUT_PIPE_FAILED",
            "The native engine stdout pipe was not available.",
        )
    })?;
    let stderr = child.stderr.take().ok_or_else(|| {
        StartupFailure::fatal(
            "STDERR_PIPE_FAILED",
            "The native engine stderr pipe was not available.",
        )
    })?;
    let process = Arc::new(OwnedProcess::new(child, pid, job));
    let (handshake_tx, handshake_rx) = mpsc::channel();
    spawn_output_reader(
        stdout,
        true,
        log.clone(),
        Some(handshake_tx),
        &session.bearer_token,
    );
    spawn_output_reader(stderr, false, log, None, &session.bearer_token);
    Ok((process, handshake_rx))
}

fn sanitize_manifest_arguments(arguments: &[String]) -> Result<Vec<String>, StartupFailure> {
    const SUPERVISOR_VALUE_FLAGS: [&str; 5] = [
        "--port",
        "--data-root",
        "--session-id",
        "--ffmpeg-component-root",
        "--component-root",
    ];
    const SUPERVISOR_BOOLEAN_FLAGS: [&str; 2] = ["--self-test", "--allow-tool-fixture"];
    let mut sanitized = Vec::with_capacity(arguments.len());
    let mut consume_value = false;
    for argument in arguments {
        if consume_value {
            consume_value = false;
            continue;
        }
        let flag = argument
            .split_once('=')
            .map(|(flag, _)| flag)
            .unwrap_or(argument.as_str());
        if flag == "--bearer-token" {
            return Err(StartupFailure::repair(
                "COMPONENT_ARGUMENTS_UNSAFE",
                "The signed component attempted to provide a bearer token on its command line; the supervisor only supplies the per-launch token through the process environment.",
                "COMPONENT_VERSION_INCOMPATIBLE",
            ));
        }
        if SUPERVISOR_VALUE_FLAGS.contains(&flag) || SUPERVISOR_BOOLEAN_FLAGS.contains(&flag) {
            if SUPERVISOR_VALUE_FLAGS.contains(&flag) && !argument.contains('=') {
                consume_value = true;
            }
            continue;
        }
        sanitized.push(argument.clone());
    }
    Ok(sanitized)
}

#[derive(Debug, Clone)]
struct StdoutEvent {
    line: String,
    oversized: bool,
}

fn spawn_output_reader<R: Read + Send + 'static>(
    stream: R,
    stdout: bool,
    log: Arc<RotatingLog>,
    handshake_sender: Option<Sender<StdoutEvent>>,
    bearer_token: &str,
) {
    let bearer_token = bearer_token.to_string();
    thread::spawn(move || {
        let mut reader = BufReader::new(stream);
        loop {
            let Ok((line, oversized)) = read_bounded_line(&mut reader, MAX_OUTPUT_LINE_BYTES)
            else {
                break;
            };
            if line.is_empty() && !oversized {
                break;
            }
            let redacted = redact_sensitive(&line, &bearer_token);
            log.append(if stdout { "stdout" } else { "stderr" }, &redacted);
            if stdout {
                if let Some(sender) = &handshake_sender {
                    let _ = sender.send(StdoutEvent { line, oversized });
                }
            }
        }
    });
}

fn read_bounded_line<R: BufRead>(reader: &mut R, maximum: usize) -> io::Result<(String, bool)> {
    let mut bytes = Vec::with_capacity(maximum.min(4096));
    let mut oversized = false;
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            break;
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let consume = newline.map(|index| index + 1).unwrap_or(available.len());
        if bytes.len() < maximum {
            let remaining = maximum - bytes.len();
            let take = consume.min(remaining);
            bytes.extend_from_slice(&available[..take]);
            if take < consume {
                oversized = true;
            }
        } else if consume > 0 {
            oversized = true;
        }
        reader.consume(consume);
        if newline.is_some() {
            break;
        }
    }
    if bytes.last() == Some(&b'\n') {
        bytes.pop();
        if bytes.last() == Some(&b'\r') {
            bytes.pop();
        }
    }
    Ok((String::from_utf8_lossy(&bytes).to_string(), oversized))
}

pub fn parse_startup_handshake(line: &str) -> Result<StartupHandshake, String> {
    if line.as_bytes().len() > MAX_HANDSHAKE_LINE_BYTES {
        return Err("HANDSHAKE_TOO_LARGE".to_string());
    }
    #[derive(Debug, Deserialize)]
    #[serde(deny_unknown_fields)]
    struct RawHandshake {
        #[serde(rename = "type")]
        handshake_type: String,
        #[serde(rename = "protocolVersion")]
        protocol_version: String,
        host: String,
        port: u16,
        pid: u32,
    }
    let raw: RawHandshake =
        serde_json::from_str(line.trim()).map_err(|_| "HANDSHAKE_MALFORMED".to_string())?;
    if raw.handshake_type != "aive-engine-startup" {
        return Err("HANDSHAKE_TYPE_INVALID".to_string());
    }
    if raw.protocol_version != STARTUP_HANDSHAKE_PROTOCOL {
        return Err("HANDSHAKE_PROTOCOL_INVALID".to_string());
    }
    if raw.host != "127.0.0.1" {
        return Err("HANDSHAKE_HOST_INVALID".to_string());
    }
    if raw.port == 0 || raw.pid == 0 {
        return Err("HANDSHAKE_ALLOCATION_INVALID".to_string());
    }
    Ok(StartupHandshake {
        handshake_type: raw.handshake_type,
        protocol_version: raw.protocol_version,
        host: raw.host,
        port: raw.port,
        pid: raw.pid,
    })
}

fn wait_for_handshake(
    receiver: &Receiver<StdoutEvent>,
    process: &Arc<OwnedProcess>,
    expected_pid: u32,
    deadline: Duration,
    state: &SupervisorState,
) -> Result<StartupHandshake, StartupFailure> {
    let started = Instant::now();
    while started.elapsed() < deadline {
        if stop_requested(state) {
            return Err(StartupFailure::repair(
                "STOP_REQUESTED",
                "Startup was cancelled by the user.",
                "ENGINE_NOT_RUNNING",
            ));
        }
        if process.exit_status().is_some() {
            return Err(StartupFailure::retryable(
                "ENGINE_EXITED",
                "The owned engine exited before publishing its startup handshake.",
            ));
        }
        match receiver.recv_timeout(Duration::from_millis(100)) {
            Ok(event) => {
                if event.oversized {
                    return Err(StartupFailure::repair(
                        "HANDSHAKE_TOO_LARGE",
                        "The native engine startup handshake exceeded the bounded line limit.",
                        "COMPONENT_VERSION_INCOMPATIBLE",
                    ));
                }
                let marker = event.line.contains("aive-engine-startup")
                    || event.line.contains("protocolVersion");
                if !marker {
                    continue;
                }
                let handshake = parse_startup_handshake(&event.line).map_err(|code| {
                    StartupFailure::repair(
                        &code,
                        "The native engine emitted an invalid startup handshake.",
                        "COMPONENT_VERSION_INCOMPATIBLE",
                    )
                })?;
                if handshake.pid != expected_pid {
                    return Err(StartupFailure::repair(
                        "HANDSHAKE_PID_INVALID",
                        "The startup handshake PID does not belong to the owned process.",
                        "COMPONENT_VERSION_INCOMPATIBLE",
                    ));
                }
                return Ok(handshake);
            }
            Err(RecvTimeoutError::Timeout) => continue,
            Err(RecvTimeoutError::Disconnected) => {
                return Err(StartupFailure::retryable(
                    "STDOUT_PIPE_CLOSED",
                    "The native engine stdout pipe closed before the startup handshake.",
                ));
            }
        }
    }
    Err(StartupFailure::retryable(
        "STARTUP_TIMEOUT",
        "The native engine did not publish a valid startup handshake before the deadline.",
    ))
}

fn probe_until_ready(
    session: &SessionSecrets,
    handshake: &StartupHandshake,
    expected_component_version: &str,
    state: &SupervisorState,
) -> Result<(HealthReadinessPayload, CapabilitiesPayload, StartupOutcome), StartupFailure> {
    let client = Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|error| StartupFailure::fatal("PROBE_CLIENT_FAILED", error.to_string()))?;
    let started = Instant::now();
    loop {
        if stop_requested(state) {
            return Err(StartupFailure::repair(
                "STOP_REQUESTED",
                "Readiness probing was cancelled by the user.",
                "ENGINE_NOT_RUNNING",
            ));
        }
        if let Some(exit) = owned_exit_status(state) {
            return Err(StartupFailure::retryable(
                "ENGINE_EXITED",
                format!("The owned engine exited during readiness probing ({exit})."),
            ));
        }
        let url = format!("http://127.0.0.1:{}/readiness", handshake.port);
        match client
            .get(&url)
            .header("Authorization", format!("Bearer {}", session.bearer_token))
            .send()
        {
            Ok(response) if response.status().as_u16() == 401 => {
                return Err(StartupFailure::repair(
                    "SESSION_AUTH_FAILED",
                    "The native engine rejected the supervisor session bearer token.",
                    "SESSION_AUTH_FAILED",
                ));
            }
            Ok(response) if response.status().is_success() => {
                let body = bounded_response_text(response).map_err(|error| {
                    StartupFailure::repair(
                        "READINESS_PAYLOAD_INVALID",
                        error,
                        "COMPONENT_VERSION_INCOMPATIBLE",
                    )
                })?;
                let health = parse_health_readiness(&body).map_err(|_| {
                    StartupFailure::repair(
                        "READINESS_SCHEMA_INVALID",
                        "The native engine readiness payload failed the Phase 1 schema/version contract.",
                        "COMPONENT_VERSION_INCOMPATIBLE",
                    )
                })?;
                if health.process.pid != handshake.pid
                    || health.process.component_id != ENGINE_COMPONENT_ID
                    || health.process.component_version != expected_component_version
                {
                    return Err(StartupFailure::repair(
                        "READINESS_PROCESS_MISMATCH",
                        "The readiness payload does not identify the owned core engine process.",
                        "COMPONENT_VERSION_INCOMPATIBLE",
                    ));
                }
                match health.overall_state {
                    HealthOverallState::Ready | HealthOverallState::Degraded => {
                        let capabilities = probe_capabilities(&client, session, handshake.port)?;
                        let outcome = if health.overall_state == HealthOverallState::Ready {
                            StartupOutcome::Ready
                        } else {
                            StartupOutcome::Degraded
                        };
                        return Ok((health, capabilities, outcome));
                    }
                    HealthOverallState::Fatal => {
                        let retryable = health
                            .fatal_error
                            .as_ref()
                            .map(|error| error.retryable)
                            .unwrap_or(false);
                        let failure = if retryable {
                            StartupFailure::retryable(
                                "ENGINE_FATAL_STARTUP",
                                "The native engine reported a retryable fatal readiness state.",
                            )
                        } else {
                            StartupFailure::repair(
                                "ENGINE_FATAL_STARTUP",
                                "The native engine reported a non-retryable fatal readiness state.",
                                "COMPONENT_VERSION_INCOMPATIBLE",
                            )
                        };
                        return Err(failure);
                    }
                    HealthOverallState::Starting => {}
                }
            }
            Ok(response) if response.status().is_client_error() => {
                return Err(StartupFailure::repair(
                    "READINESS_REQUEST_REJECTED",
                    "The native engine rejected the authenticated readiness request.",
                    "COMPONENT_VERSION_INCOMPATIBLE",
                ));
            }
            Ok(_) | Err(_) => {}
        }
        if started.elapsed() >= STARTUP_DEADLINE {
            return Err(StartupFailure::retryable(
                "READINESS_TIMEOUT",
                "The native engine did not reach authenticated readiness before the deadline.",
            ));
        }
        thread::sleep(Duration::from_millis(150));
    }
}

fn probe_capabilities(
    client: &Client,
    session: &SessionSecrets,
    port: u16,
) -> Result<CapabilitiesPayload, StartupFailure> {
    let response = client
        .get(format!("http://127.0.0.1:{port}/capabilities"))
        .header("Authorization", format!("Bearer {}", session.bearer_token))
        .send()
        .map_err(|error| {
            StartupFailure::retryable("CAPABILITIES_REQUEST_FAILED", error.to_string())
        })?;
    if response.status().as_u16() == 401 {
        return Err(StartupFailure::repair(
            "SESSION_AUTH_FAILED",
            "The native engine rejected the authenticated capabilities request.",
            "SESSION_AUTH_FAILED",
        ));
    }
    if !response.status().is_success() {
        return Err(StartupFailure::repair(
            "CAPABILITIES_REQUEST_REJECTED",
            "The native engine capabilities endpoint returned a non-success response.",
            "COMPONENT_VERSION_INCOMPATIBLE",
        ));
    }
    let body = bounded_response_text(response).map_err(|error| {
        StartupFailure::repair(
            "CAPABILITIES_PAYLOAD_INVALID",
            error,
            "COMPONENT_VERSION_INCOMPATIBLE",
        )
    })?;
    parse_capabilities(&body).map_err(|_| {
        StartupFailure::repair(
            "CAPABILITIES_SCHEMA_INVALID",
            "The native engine capabilities payload failed the Phase 1 schema/version contract.",
            "COMPONENT_VERSION_INCOMPATIBLE",
        )
    })
}

fn owned_exit_status(state: &SupervisorState) -> Option<ExitStatus> {
    state
        .inner
        .lock()
        .ok()
        .and_then(|runtime| runtime.process.clone())
        .and_then(|process| process.exit_status())
}

fn start_exit_monitor(state: SupervisorState, app: AppHandle, process: Arc<OwnedProcess>) {
    thread::spawn(move || {
        while process.exit_status().is_none() {
            thread::sleep(Duration::from_millis(100));
        }
        let (should_restart, budget_exhausted) = {
            let mut runtime = match state.inner.lock() {
                Ok(runtime) => runtime,
                Err(_) => return,
            };
            let is_current = runtime
                .process
                .as_ref()
                .map(|current| Arc::ptr_eq(current, &process))
                .unwrap_or(false);
            let stop_requested = runtime
                .stop_requested
                .as_ref()
                .map(|flag| flag.load(Ordering::SeqCst))
                .unwrap_or(false);
            if !is_current || stop_requested || runtime.status.state == SupervisorPhase::Stopping {
                (false, false)
            } else if runtime.status.retry_count >= MAX_RETRIES {
                runtime.process = None;
                runtime.session = None;
                runtime.status.state = SupervisorPhase::Fatal;
                runtime.status.engine_ready = false;
                runtime.status.last_error = Some("ENGINE_CRASH_BUDGET_EXHAUSTED".to_string());
                runtime.status.detail =
                    "The owned engine crashed repeatedly; automatic recovery is paused."
                        .to_string();
                runtime.status.remediation_codes = vec![
                    "UPDATE_ROLLBACK_AVAILABLE".to_string(),
                    "RESTART_REQUIRED".to_string(),
                ];
                persist_recovery(&runtime);
                (false, true)
            } else {
                runtime.process = None;
                runtime.session = None;
                runtime.start_in_progress = true;
                runtime.status.state =
                    transition_state(runtime.status.state, SupervisorEvent::Crash);
                runtime.status.engine_ready = false;
                runtime.status.detail =
                    "The owned engine crashed; bounded recovery backoff is active.".to_string();
                runtime.status.last_error = Some("ENGINE_CRASHED".to_string());
                runtime.status.remediation_codes = vec!["RESTART_REQUIRED".to_string()];
                runtime.status.next_retry_at_epoch_ms =
                    Some(now_epoch_ms() + BACKOFFS[0].as_millis() as u128);
                persist_recovery(&runtime);
                (true, false)
            }
        };
        if budget_exhausted {
            request_last_known_good_rollback(&state);
        }
        emit_status(&app, &state.status());
        if should_restart {
            if sleep_with_stop(&state, BACKOFFS[0]) {
                run_startup(state, app);
            } else {
                finish_stopped(&state, &app, "Crash recovery was cancelled.");
            }
        }
    });
}

fn stop_worker(
    state: SupervisorState,
    app: AppHandle,
    process: Option<Arc<OwnedProcess>>,
    session: Option<SessionSecrets>,
) {
    if let (Some(process), Some(session)) = (&process, &session) {
        request_graceful_shutdown(process.port(), &session.bearer_token);
        if !process.wait_for_exit(STOP_GRACE_PERIOD) {
            process.kill_owned();
            let _ = process.wait_for_exit(Duration::from_secs(2));
        }
    } else if let Some(process) = &process {
        process.kill_owned();
        let _ = process.wait_for_exit(Duration::from_secs(2));
    }
    let restart = {
        let mut runtime = match state.inner.lock() {
            Ok(runtime) => runtime,
            Err(_) => return,
        };
        runtime.process = None;
        runtime.session = None;
        runtime.stop_in_progress = false;
        runtime.start_in_progress = false;
        runtime.stop_requested = None;
        let restart = runtime.restart_after_stop && !runtime.app_closed;
        runtime.restart_after_stop = false;
        runtime.status.state = SupervisorPhase::Stopped;
        runtime.status.engine_ready = false;
        runtime.status.port = None;
        runtime.status.pid = None;
        runtime.status.host = None;
        runtime.status.protocol_version = None;
        runtime.status.capabilities = None;
        runtime.status.detail = "The owned native engine stopped cleanly.".to_string();
        runtime.status.remediation_codes.clear();
        runtime.status.next_retry_at_epoch_ms = None;
        persist_recovery(&runtime);
        restart
    };
    emit_status(&app, &state.status());
    if restart {
        let _ = state.start(app);
    }
}

fn request_graceful_shutdown(port: u16, token: &str) {
    let Ok(client) = Client::builder().timeout(Duration::from_secs(2)).build() else {
        return;
    };
    let _ = client
        .post(format!("http://127.0.0.1:{port}/engine-control/shutdown"))
        .header("Authorization", format!("Bearer {token}"))
        .send();
}

fn cleanup_failed_process(state: &SupervisorState) {
    let process = state
        .inner
        .lock()
        .ok()
        .and_then(|mut runtime| runtime.process.take());
    if let Some(process) = process {
        process.kill_owned();
        let _ = process.wait_for_exit(Duration::from_secs(2));
    }
    if let Ok(mut runtime) = state.inner.lock() {
        runtime.session = None;
        runtime.status.engine_ready = false;
        runtime.status.port = None;
        runtime.status.pid = None;
        runtime.status.host = None;
        runtime.status.protocol_version = None;
        runtime.status.capabilities = None;
        persist_recovery(&runtime);
    }
}

fn finish_stopped(state: &SupervisorState, app: &AppHandle, detail: &str) {
    cleanup_failed_process(state);
    if let Ok(mut runtime) = state.inner.lock() {
        runtime.start_in_progress = false;
        runtime.stop_in_progress = false;
        runtime.session = None;
        runtime.status.state = SupervisorPhase::Stopped;
        runtime.status.engine_ready = false;
        runtime.status.detail = detail.to_string();
        runtime.status.remediation_codes.clear();
        runtime.status.next_retry_at_epoch_ms = None;
        persist_recovery(&runtime);
    }
    emit_status(app, &state.status());
}

fn set_terminal_failure(
    state: &SupervisorState,
    app: &AppHandle,
    phase: SupervisorPhase,
    failure: StartupFailure,
) {
    if let Ok(mut runtime) = state.inner.lock() {
        runtime.start_in_progress = false;
        runtime.stop_in_progress = false;
        runtime.session = None;
        runtime.status.state = phase;
        runtime.status.engine_ready = false;
        runtime.status.detail = if phase == SupervisorPhase::RepairRequired {
            "Native engine startup needs local component repair or setup.".to_string()
        } else {
            "Native engine startup failed after bounded recovery attempts.".to_string()
        };
        runtime.status.last_error = Some(format!(
            "{}: {}",
            failure.code,
            redact_sensitive(&failure.message, "")
        ));
        runtime.status.remediation_codes = failure.remediation_codes;
        runtime.status.next_retry_at_epoch_ms = None;
        persist_recovery(&runtime);
    }
    emit_status(app, &state.status());
}

fn request_last_known_good_rollback(state: &SupervisorState) {
    let manager = {
        let paths = get_canonical_paths();
        ComponentManager::new(PathBuf::from(paths.program_data_root).join("AI Video Editor"))
    };
    if manager
        .rollback(ENGINE_COMPONENT_ID, SourcePolicy::PRODUCTION, None)
        .is_ok()
    {
        if let Ok(mut runtime) = state.inner.lock() {
            runtime.status.rollback_requested = true;
            runtime
                .status
                .remediation_codes
                .push("UPDATE_ROLLBACK_AVAILABLE".to_string());
            persist_recovery(&runtime);
        }
    }
}

fn set_phase(
    state: &SupervisorState,
    app: &AppHandle,
    phase: SupervisorPhase,
    detail: String,
    remediation_codes: Vec<String>,
) {
    if let Ok(mut runtime) = state.inner.lock() {
        runtime.status.state = phase;
        runtime.status.engine_ready = false;
        runtime.status.detail = detail;
        runtime.status.remediation_codes = remediation_codes;
        persist_recovery(&runtime);
    }
    emit_status(app, &state.status());
}

fn stop_requested(state: &SupervisorState) -> bool {
    state
        .inner
        .lock()
        .ok()
        .and_then(|runtime| runtime.stop_requested.clone())
        .map(|flag| flag.load(Ordering::SeqCst))
        .unwrap_or(false)
}

fn sleep_with_stop(state: &SupervisorState, duration: Duration) -> bool {
    let started = Instant::now();
    while started.elapsed() < duration {
        if stop_requested(state) {
            return false;
        }
        thread::sleep(Duration::from_millis(50));
    }
    !stop_requested(state)
}

fn emit_status(app: &AppHandle, status: &SupervisorStatus) {
    let _ = app.emit(SUPERVISOR_STATUS_EVENT, status);
}

fn persist_recovery(runtime: &SupervisorRuntime) {
    let metadata = RecoveryMetadata {
        schema_version: "desktop.supervisor-recovery.v1".to_string(),
        state: runtime.status.state,
        component_id: runtime.status.component_id.clone(),
        component_version: runtime.status.component_version.clone(),
        retry_count: runtime.status.retry_count,
        last_exit_code: None,
        updated_at_epoch_ms: now_epoch_ms(),
        rollback_requested: runtime.status.rollback_requested,
    };
    if let Some(parent) = runtime.recovery_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(bytes) = serde_json::to_vec_pretty(&metadata) {
        let temporary = runtime.recovery_path.with_extension("json.part");
        if fs::write(&temporary, bytes).is_ok() {
            let _ = fs::remove_file(&runtime.recovery_path);
            let _ = fs::rename(temporary, &runtime.recovery_path);
        }
    }
}

fn load_recovery(path: &Path) -> (bool, u32, bool) {
    let Ok(bytes) = fs::read(path) else {
        return (false, 0, false);
    };
    let Ok(metadata) = serde_json::from_slice::<RecoveryMetadata>(&bytes) else {
        let _ = fs::remove_file(path);
        return (true, 0, false);
    };
    let age = now_epoch_ms().saturating_sub(metadata.updated_at_epoch_ms);
    if metadata.schema_version != "desktop.supervisor-recovery.v1"
        || age > RECOVERY_MAX_AGE.as_millis() as u128
        || metadata.state != SupervisorPhase::Stopped
    {
        let _ = fs::remove_file(path);
        return (true, 0, false);
    }
    (
        false,
        metadata.retry_count.min(MAX_RETRIES),
        metadata.rollback_requested,
    )
}

fn create_log_path(root: &Path, session_id: &str) -> io::Result<PathBuf> {
    fs::create_dir_all(root)?;
    Ok(root.join(format!("engine-supervisor-{session_id}.log")))
}

struct RotatingLog {
    path: PathBuf,
    lock: Mutex<()>,
}

impl RotatingLog {
    fn new(path: PathBuf) -> Self {
        Self {
            path,
            lock: Mutex::new(()),
        }
    }

    fn append(&self, stream: &str, line: &str) {
        let Ok(_guard) = self.lock.lock() else { return };
        if let Some(parent) = self.path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        if let Ok(metadata) = fs::metadata(&self.path) {
            if metadata.len() >= MAX_LOG_BYTES {
                for index in (1..=MAX_LOG_ROTATIONS).rev() {
                    let from = if index == 1 {
                        self.path.clone()
                    } else {
                        rotated_log_path(&self.path, index - 1)
                    };
                    let to = rotated_log_path(&self.path, index);
                    if from.exists() {
                        let _ = fs::remove_file(&to);
                        let _ = fs::rename(from, to);
                    }
                }
            }
        }
        if let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
        {
            let _ = writeln!(file, "{} [{}] {}", now_epoch_ms(), stream, line);
        }
    }
}

fn rotated_log_path(path: &Path, index: usize) -> PathBuf {
    PathBuf::from(format!("{}.{}", path.to_string_lossy(), index))
}

fn read_log_tail(path: &str) -> Vec<String> {
    let Ok(mut file) = File::open(path) else {
        return Vec::new();
    };
    let mut bytes = Vec::new();
    if file.read_to_end(&mut bytes).is_err() {
        return Vec::new();
    }
    let start = bytes.len().saturating_sub(8 * 1024);
    String::from_utf8_lossy(&bytes[start..])
        .lines()
        .map(|line| redact_sensitive(line, ""))
        .collect()
}

pub fn redact_sensitive(input: &str, token: &str) -> String {
    let mut output = input.to_string();
    if !token.is_empty() {
        output = output.replace(token, "[REDACTED]");
    }
    for marker in [
        "Bearer ",
        "bearerToken=",
        "bearer_token=",
        "token=",
        "api_key=",
        "password=",
        "secret=",
    ] {
        let mut search_from = 0;
        while let Some(relative) = output[search_from..].find(marker) {
            let start = search_from + relative + marker.len();
            let end = output[start..]
                .find(|character: char| character.is_whitespace() || ",;&\"'".contains(character))
                .map(|offset| start + offset)
                .unwrap_or(output.len());
            output.replace_range(start..end, "[REDACTED]");
            search_from = start + "[REDACTED]".len();
            if search_from >= output.len() {
                break;
            }
        }
    }
    output.chars().take(MAX_OUTPUT_LINE_BYTES).collect()
}

fn redact_path(path: &Path) -> String {
    path.to_string_lossy().replace('"', "'")
}

fn now_epoch_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

fn health_detail(health: &HealthReadinessPayload) -> String {
    format!("Authenticated readiness state: {:?}.", health.overall_state)
}

fn bounded_response_text(response: Response) -> Result<String, String> {
    let bytes = response
        .bytes()
        .map_err(|error| format!("Could not read the bounded engine response: {error}"))?;
    if bytes.len() > MAX_RESPONSE_BYTES {
        return Err(
            "Engine response exceeded the bounded diagnostics/readiness limit.".to_string(),
        );
    }
    String::from_utf8(bytes.to_vec())
        .map_err(|_| "Engine response was not valid UTF-8 JSON.".to_string())
}

fn validate_bridge_request(request: &EngineApiRequest) -> Result<(), String> {
    let method = request.method.to_ascii_uppercase();
    if !matches!(
        method.as_str(),
        "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD"
    ) {
        return Err("BRIDGE_METHOD_INVALID: unsupported HTTP method.".to_string());
    }
    if request.path.is_empty()
        || !request.path.starts_with('/')
        || request.path.contains("://")
        || request.path.contains("..")
        || request.path.contains('\0')
    {
        return Err("BRIDGE_PATH_INVALID: only relative engine paths are accepted.".to_string());
    }
    let path_lower = request.path.to_ascii_lowercase();
    if path_lower.contains("token=")
        || path_lower.contains("bearer=")
        || path_lower.contains("authorization=")
    {
        return Err(
            "BRIDGE_PATH_INVALID: credentials are never accepted in query strings.".to_string(),
        );
    }
    if !(path_lower == "/health"
        || path_lower == "/readiness"
        || path_lower == "/capabilities"
        || path_lower.starts_with("/api/v1/")
        || path_lower.starts_with("/media/")
        || path_lower.starts_with("/uploads/"))
    {
        return Err(
            "BRIDGE_PATH_INVALID: endpoint is outside the native engine API perimeter.".to_string(),
        );
    }
    if let Some(body) = &request.body_base64 {
        if body.len() > MAX_REQUEST_BYTES.saturating_mul(2) {
            return Err(
                "BRIDGE_BODY_TOO_LARGE: request body exceeds the bounded bridge limit.".to_string(),
            );
        }
    }
    Ok(())
}

fn decode_body(body: Option<&str>) -> Result<Option<Vec<u8>>, String> {
    let Some(body) = body else {
        return Ok(None);
    };
    let bytes = BASE64
        .decode(body)
        .map_err(|_| "BRIDGE_BODY_INVALID: request body is not valid base64.".to_string())?;
    if bytes.len() > MAX_REQUEST_BYTES {
        return Err(
            "BRIDGE_BODY_TOO_LARGE: request body exceeds the bounded bridge limit.".to_string(),
        );
    }
    Ok(Some(bytes))
}

fn response_to_bridge(response: Response) -> Result<EngineApiResponse, String> {
    let status = response.status().as_u16();
    let mut headers = HashMap::new();
    if let Some(value) = response.headers().get("content-type") {
        if let Ok(value) = value.to_str() {
            headers.insert("content-type".to_string(), value.to_string());
        }
    }
    let bytes = response
        .bytes()
        .map_err(|error| format!("BRIDGE_RESPONSE_FAILED: {error}"))?;
    if bytes.len() > MAX_RESPONSE_BYTES {
        return Err(
            "BRIDGE_RESPONSE_TOO_LARGE: engine response exceeds the bounded bridge limit."
                .to_string(),
        );
    }
    Ok(EngineApiResponse {
        status,
        headers,
        body_base64: BASE64.encode(bytes),
    })
}

#[cfg(windows)]
struct JobHandle {
    handle: *mut std::ffi::c_void,
}

#[cfg(windows)]
unsafe impl Send for JobHandle {}

#[cfg(windows)]
unsafe impl Sync for JobHandle {}

#[cfg(windows)]
impl JobHandle {
    fn for_child(child: &Child) -> io::Result<Self> {
        use std::os::windows::io::AsRawHandle;
        let handle = unsafe { create_job_object() }?;
        let assigned = unsafe {
            assign_process_to_job(handle, child.as_raw_handle() as *mut std::ffi::c_void)
        };
        if let Err(error) = assigned {
            unsafe { close_job_handle(handle) };
            return Err(error);
        }
        Ok(Self { handle })
    }

    fn terminate(&self) {
        unsafe {
            terminate_job(self.handle);
        }
    }
}

#[cfg(windows)]
impl Drop for JobHandle {
    fn drop(&mut self) {
        unsafe {
            close_job_handle(self.handle);
        }
    }
}

struct OwnedProcess {
    child: Arc<Mutex<Child>>,
    exit_status: Arc<Mutex<Option<ExitStatus>>>,
    pid: u32,
    port: Mutex<u16>,
    #[cfg(windows)]
    job: Option<JobHandle>,
}

impl OwnedProcess {
    #[cfg(windows)]
    fn new(child: Child, pid: u32, job: Option<JobHandle>) -> Self {
        Self::new_inner(child, pid, job)
    }

    #[cfg(not(windows))]
    fn new(child: Child, pid: u32, _job: Option<()>) -> Self {
        Self::new_inner(child, pid)
    }

    #[cfg(windows)]
    fn new_inner(child: Child, pid: u32, job: Option<JobHandle>) -> Self {
        let process = Self {
            child: Arc::new(Mutex::new(child)),
            exit_status: Arc::new(Mutex::new(None)),
            pid,
            port: Mutex::new(0),
            job,
        };
        process.start_waiter();
        process
    }

    #[cfg(not(windows))]
    fn new_inner(child: Child, pid: u32) -> Self {
        let process = Self {
            child: Arc::new(Mutex::new(child)),
            exit_status: Arc::new(Mutex::new(None)),
            pid,
            port: Mutex::new(0),
        };
        process.start_waiter();
        process
    }

    fn start_waiter(&self) {
        let child = self.child.clone();
        let exit_status = self.exit_status.clone();
        thread::spawn(move || loop {
            let result = child
                .lock()
                .ok()
                .and_then(|mut child| child.try_wait().ok().flatten());
            if let Some(status) = result {
                if let Ok(mut target) = exit_status.lock() {
                    *target = Some(status);
                }
                break;
            }
            thread::sleep(Duration::from_millis(50));
        });
    }

    fn exit_status(&self) -> Option<ExitStatus> {
        self.exit_status.lock().ok().and_then(|status| *status)
    }

    fn port(&self) -> u16 {
        self.port.lock().map(|port| *port).unwrap_or(0)
    }

    fn set_port(&self, port: u16) {
        if let Ok(mut current) = self.port.lock() {
            *current = port;
        }
    }

    fn wait_for_exit(&self, timeout: Duration) -> bool {
        let started = Instant::now();
        while started.elapsed() < timeout {
            if self.exit_status().is_some() {
                return true;
            }
            thread::sleep(Duration::from_millis(50));
        }
        self.exit_status().is_some()
    }

    fn kill_owned(&self) {
        #[cfg(windows)]
        if let Some(job) = &self.job {
            job.terminate();
            return;
        }
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
        }
    }
}

impl Drop for OwnedProcess {
    fn drop(&mut self) {
        if self.exit_status().is_none() {
            self.kill_owned();
        }
    }
}

#[cfg(windows)]
unsafe fn create_job_object() -> io::Result<*mut std::ffi::c_void> {
    use std::ptr::null_mut;
    #[repr(C)]
    struct IoCounters {
        read_operations: u64,
        write_operations: u64,
        other_operations: u64,
        read_bytes: u64,
        write_bytes: u64,
        other_bytes: u64,
    }
    #[repr(C)]
    struct BasicLimit {
        per_process_user_time: i64,
        per_job_user_time: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }
    #[repr(C)]
    struct ExtendedLimit {
        basic: BasicLimit,
        io: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(
            attributes: *mut std::ffi::c_void,
            name: *const u16,
        ) -> *mut std::ffi::c_void;
        fn SetInformationJobObject(
            job: *mut std::ffi::c_void,
            class: u32,
            info: *const std::ffi::c_void,
            length: u32,
        ) -> i32;
    }
    let handle = CreateJobObjectW(null_mut(), std::ptr::null());
    if handle.is_null() {
        return Err(io::Error::last_os_error());
    }
    let mut limits: ExtendedLimit = std::mem::zeroed();
    limits.basic.limit_flags = 0x0000_2000;
    if SetInformationJobObject(
        handle,
        9,
        &limits as *const _ as *const std::ffi::c_void,
        std::mem::size_of::<ExtendedLimit>() as u32,
    ) == 0
    {
        close_job_handle(handle);
        return Err(io::Error::last_os_error());
    }
    Ok(handle)
}

#[cfg(windows)]
unsafe fn assign_process_to_job(
    job: *mut std::ffi::c_void,
    process: *mut std::ffi::c_void,
) -> io::Result<()> {
    #[link(name = "kernel32")]
    extern "system" {
        fn AssignProcessToJobObject(
            job: *mut std::ffi::c_void,
            process: *mut std::ffi::c_void,
        ) -> i32;
    }
    if AssignProcessToJobObject(job, process) == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(windows)]
unsafe fn terminate_job(job: *mut std::ffi::c_void) {
    #[link(name = "kernel32")]
    extern "system" {
        fn TerminateJobObject(job: *mut std::ffi::c_void, code: u32) -> i32;
    }
    let _ = TerminateJobObject(job, 1);
}

#[cfg(windows)]
unsafe fn close_job_handle(job: *mut std::ffi::c_void) {
    #[link(name = "kernel32")]
    extern "system" {
        fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
    }
    let _ = CloseHandle(job);
}

#[tauri::command]
pub fn supervisor_status(state: State<'_, SupervisorState>) -> SupervisorStatus {
    state.inner().status()
}

#[tauri::command]
pub fn supervisor_start(app: AppHandle, state: State<'_, SupervisorState>) -> SupervisorStatus {
    state.inner().start(app)
}

#[tauri::command]
pub fn supervisor_stop(app: AppHandle, state: State<'_, SupervisorState>) -> SupervisorStatus {
    state.inner().stop(app)
}

#[tauri::command]
pub fn supervisor_restart(app: AppHandle, state: State<'_, SupervisorState>) -> SupervisorStatus {
    state.inner().restart(app)
}

#[tauri::command]
pub fn supervisor_retry(app: AppHandle, state: State<'_, SupervisorState>) -> SupervisorStatus {
    state.inner().retry(app)
}

#[tauri::command]
pub fn supervisor_diagnostics(state: State<'_, SupervisorState>) -> SupervisorDiagnostics {
    state.inner().diagnostics()
}

#[tauri::command]
pub fn engine_api_request(
    state: State<'_, SupervisorState>,
    request: EngineApiRequest,
) -> Result<EngineApiResponse, String> {
    state.inner().api_request(request)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn state_machine_covers_startup_crash_repair_and_reset() {
        let mut state = SupervisorPhase::Stopped;
        state = transition_state(state, SupervisorEvent::Resolve);
        assert_eq!(state, SupervisorPhase::Resolving);
        state = transition_state(state, SupervisorEvent::Launch);
        assert_eq!(state, SupervisorPhase::Starting);
        state = transition_state(state, SupervisorEvent::WaitForHandshake);
        assert_eq!(state, SupervisorPhase::WaitingForHandshake);
        state = transition_state(state, SupervisorEvent::Probe);
        assert_eq!(state, SupervisorPhase::Probing);
        state = transition_state(state, SupervisorEvent::Ready);
        assert_eq!(state, SupervisorPhase::Ready);
        assert_eq!(
            transition_state(state, SupervisorEvent::Crash),
            SupervisorPhase::CrashedBackoff
        );
        assert_eq!(
            transition_state(state, SupervisorEvent::Repair),
            SupervisorPhase::RepairRequired
        );
        assert_eq!(
            transition_state(state, SupervisorEvent::Fatal),
            SupervisorPhase::Fatal
        );
        assert_eq!(
            transition_state(state, SupervisorEvent::Reset),
            SupervisorPhase::Stopped
        );
        assert_eq!(
            transition_state(SupervisorPhase::Fatal, SupervisorEvent::Ready),
            SupervisorPhase::Fatal
        );
        assert_eq!(
            transition_state(SupervisorPhase::Ready, SupervisorEvent::Launch),
            SupervisorPhase::Ready
        );
    }

    #[test]
    fn handshake_accepts_dynamic_loopback_and_rejects_wrong_protocol_or_host() {
        let valid = r#"{"type":"aive-engine-startup","protocolVersion":"desktop.engine-handshake.v1","host":"127.0.0.1","port":43123,"pid":42}"#;
        let handshake = parse_startup_handshake(valid).expect("valid handshake");
        assert_eq!(handshake.port, 43123);
        assert!(parse_startup_handshake(&valid.replace("127.0.0.1", "0.0.0.0")).is_err());
        assert!(parse_startup_handshake(
            &valid.replace("desktop.engine-handshake.v1", "desktop.engine-handshake.v0")
        )
        .is_err());
    }

    #[test]
    fn malformed_and_oversized_handshakes_are_bounded() {
        assert_eq!(
            parse_startup_handshake("{\"type\":\"aive-engine-startup\"").unwrap_err(),
            "HANDSHAKE_MALFORMED"
        );
        assert_eq!(
            parse_startup_handshake(&"x".repeat(MAX_HANDSHAKE_LINE_BYTES + 1)).unwrap_err(),
            "HANDSHAKE_TOO_LARGE"
        );
    }

    #[test]
    fn secure_tokens_are_at_least_256_bits_and_rotate() {
        let first = new_session().expect("first session");
        let second = new_session().expect("second session");
        assert!(first.bearer_token.len() >= 43);
        assert_ne!(first.bearer_token, second.bearer_token);
        assert!(!serde_json::to_string(&RecoveryMetadata {
            schema_version: "desktop.supervisor-recovery.v1".to_string(),
            state: SupervisorPhase::Ready,
            component_id: Some("aive-engine".to_string()),
            component_version: Some("1.0.0".to_string()),
            retry_count: 1,
            last_exit_code: None,
            updated_at_epoch_ms: 1,
            rollback_requested: false,
        })
        .unwrap()
        .contains("bearer"));
    }

    #[test]
    fn backoff_and_budget_are_bounded() {
        assert_eq!(BACKOFFS.len(), 3);
        assert!(BACKOFFS[0] < BACKOFFS[1] && BACKOFFS[1] < BACKOFFS[2]);
        assert_eq!(MAX_RETRIES, 3);
    }

    #[test]
    fn rapid_start_requests_are_idempotently_blocked_by_lifecycle_guard() {
        assert!(start_request_is_blocked(
            true,
            false,
            false,
            SupervisorPhase::Starting
        ));
        assert!(start_request_is_blocked(
            false,
            true,
            false,
            SupervisorPhase::Stopping
        ));
        assert!(start_request_is_blocked(
            false,
            false,
            true,
            SupervisorPhase::Stopped
        ));
        assert!(start_request_is_blocked(
            false,
            false,
            false,
            SupervisorPhase::Ready
        ));
        assert!(start_request_is_blocked(
            false,
            false,
            false,
            SupervisorPhase::RepairRequired
        ));
        assert!(!start_request_is_blocked(
            false,
            false,
            false,
            SupervisorPhase::Stopped
        ));
        assert!(!start_request_is_blocked(
            false,
            false,
            false,
            SupervisorPhase::Resolving
        ));
    }

    #[test]
    fn component_resolution_failures_are_structured_repairs_without_fallback() {
        let missing = component_failure(ComponentError::new(
            "COMPONENT_NOT_ACTIVE",
            "missing",
            false,
        ));
        assert!(missing.repair_required);
        assert_eq!(missing.code, "COMPONENT_NOT_ACTIVE");
        assert_eq!(missing.remediation_codes, vec!["ENGINE_NOT_RUNNING"]);

        let elevation = component_failure(ComponentError::new(
            "ELEVATION_REQUIRED",
            "elevation",
            false,
        ));
        assert!(elevation.repair_required);
        assert_eq!(elevation.remediation_codes, vec!["STORAGE_NOT_WRITABLE"]);

        let corrupt = component_failure(ComponentError::new(
            "ACTIVATION_METADATA_INVALID",
            "corrupt",
            false,
        ));
        assert!(corrupt.repair_required);
        assert_eq!(
            corrupt.remediation_codes,
            vec!["COMPONENT_VERSION_INCOMPATIBLE"]
        );
    }

    #[test]
    fn bridge_rejects_before_readiness_and_never_accepts_absolute_urls_or_query_tokens() {
        let base = EngineApiRequest {
            method: "GET".to_string(),
            path: "/api/v1/projects".to_string(),
            body_base64: None,
            content_type: None,
            timeout_ms: 1000,
        };
        assert!(validate_bridge_request(&base).is_ok());
        assert!(validate_bridge_request(&EngineApiRequest {
            path: "http://127.0.0.1:1/api/v1/projects".to_string(),
            ..base.clone()
        })
        .is_err());
        assert!(validate_bridge_request(&EngineApiRequest {
            path: "/api/v1/projects?token=secret".to_string(),
            ..base
        })
        .is_err());
    }

    #[test]
    fn launch_arguments_cannot_override_runtime_paths_or_put_the_session_on_cli() {
        let arguments = vec![
            "--config".to_string(),
            "config/engine.json".to_string(),
            "--port".to_string(),
            "9999".to_string(),
            "--data-root=/unsafe".to_string(),
            "--self-test".to_string(),
        ];
        let sanitized = sanitize_manifest_arguments(&arguments).expect("safe arguments");
        assert_eq!(sanitized, vec!["--config", "config/engine.json"]);
        let token_argument = vec!["--bearer-token=should-never-be-here".to_string()];
        assert_eq!(
            sanitize_manifest_arguments(&token_argument)
                .unwrap_err()
                .code,
            "COMPONENT_ARGUMENTS_UNSAFE"
        );
    }

    #[test]
    fn log_redaction_removes_token_bearer_and_secret_values() {
        let redacted = redact_sensitive("token=abc Bearer xyz password=hunter2", "abc");
        assert!(!redacted.contains("abc"));
        assert!(!redacted.contains("xyz"));
        assert!(!redacted.contains("hunter2"));
        assert!(redacted.contains("[REDACTED]"));
    }

    #[test]
    fn stale_recovery_metadata_is_ignored_without_restoring_a_process() {
        let root = std::env::temp_dir().join(format!("aive-supervisor-test-{}", now_epoch_ms()));
        fs::create_dir_all(&root).expect("test root");
        let path = root.join("supervisor-recovery.json");
        fs::write(
            &path,
            serde_json::to_vec(&RecoveryMetadata {
                schema_version: "desktop.supervisor-recovery.v1".to_string(),
                state: SupervisorPhase::Ready,
                component_id: Some("aive-engine".to_string()),
                component_version: Some("1.0.0".to_string()),
                retry_count: 3,
                last_exit_code: Some(1),
                updated_at_epoch_ms: 1,
                rollback_requested: false,
            })
            .unwrap(),
        )
        .expect("metadata");
        let result = load_recovery(&path);
        assert_eq!(result, (true, 0, false));
        assert!(!path.exists());

        let recent_path = root.join("recent-recovery.json");
        fs::write(
            &recent_path,
            serde_json::to_vec(&RecoveryMetadata {
                schema_version: "desktop.supervisor-recovery.v1".to_string(),
                state: SupervisorPhase::Ready,
                component_id: Some("aive-engine".to_string()),
                component_version: Some("1.0.0".to_string()),
                retry_count: 1,
                last_exit_code: None,
                updated_at_epoch_ms: now_epoch_ms(),
                rollback_requested: false,
            })
            .unwrap(),
        )
        .expect("recent metadata");
        assert_eq!(load_recovery(&recent_path), (true, 0, false));
        assert!(!recent_path.exists());
        let _ = fs::remove_dir_all(root);
    }
}
