use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::sleep;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, State, Window};

pub mod contracts;

#[derive(Serialize, Deserialize, Clone)]
pub struct ProjectFile {
    pub version: String,
    pub video_id: String,
    pub video_filename: String,
    pub backend_url: String,
    pub created_at: String,
    pub notes: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct AppSettings {
    #[serde(default = "default_backend_url")]
    pub backend_url: String,
    #[serde(default = "default_asr_provider")]
    pub asr_provider: String,
    #[serde(default)]
    pub domain_terms: Vec<String>,
    #[serde(default = "default_auto_accept_threshold")]
    pub auto_accept_threshold: f64,
    #[serde(default)]
    pub export_folder: Option<String>,
    #[serde(default = "default_appearance_theme")]
    pub appearance_theme: String,
    #[serde(default = "default_interface_density")]
    pub interface_density: String,
    #[serde(default = "default_true")]
    pub guided_tours_enabled: bool,
    #[serde(default = "default_true")]
    pub guided_hints_enabled: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            backend_url: default_backend_url(),
            asr_provider: default_asr_provider(),
            domain_terms: vec![],
            auto_accept_threshold: default_auto_accept_threshold(),
            export_folder: None,
            appearance_theme: default_appearance_theme(),
            interface_density: default_interface_density(),
            guided_tours_enabled: true,
            guided_hints_enabled: true,
        }
    }
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct NativeImportProgressEvent {
    token: String,
    project_id: String,
    filename: String,
    status: String,
    bytes_copied: u64,
    total_bytes: u64,
    percent: f64,
    bytes_per_second: f64,
    eta_seconds: Option<f64>,
    message: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NativeImportInitResponse {
    token: String,
    project_id: String,
    staging_relative_path: String,
    staging_part_relative_path: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeImportInitRequest {
    original_filename: String,
    file_size_bytes: u64,
    mime_type: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeImportFinalizeRequest {
    copied_file_size_bytes: u64,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeImportCommandResult {
    token: String,
    project_id: String,
    video_id: String,
    filename: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NativeImportFinalizeResponse {
    id: String,
    project_id: Option<String>,
    filename: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct AppStorageLayout {
    root_dir: String,
    uploads_dir: String,
    staging_dir: String,
    rendered_videos_dir: String,
    proxies_dir: String,
    temp_dir: String,
    logs_dir: String,
    config_dir: String,
    backups_dir: String,
}

#[derive(Default, Clone)]
struct NativeImportRegistry {
    flags: Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>,
}

impl NativeImportRegistry {
    fn register(&self, token: &str) -> Arc<AtomicBool> {
        let flag = Arc::new(AtomicBool::new(false));
        let mut flags = self.flags.lock().expect("native import registry lock poisoned");
        flags.insert(token.to_string(), flag.clone());
        flag
    }

    fn request_cancel(&self, token: &str) -> bool {
        let flags = self.flags.lock().expect("native import registry lock poisoned");
        if let Some(flag) = flags.get(token) {
            flag.store(true, Ordering::Relaxed);
            return true;
        }
        false
    }

    fn unregister(&self, token: &str) {
        let mut flags = self.flags.lock().expect("native import registry lock poisoned");
        flags.remove(token);
    }
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct ReadinessItem {
    key: String,
    label: String,
    status: String,
    detail: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct DesktopBootstrapResult {
    ready: bool,
    backend_url: String,
    compose_project_name: String,
    env_file: String,
    items: Vec<ReadinessItem>,
}

#[tauri::command]
fn save_project(path: String, project: ProjectFile) -> Result<(), String> {
    let json = serde_json::to_string_pretty(&project).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| format!("Failed to save project: {e}"))?;
    Ok(())
}

#[tauri::command]
fn load_project(path: String) -> Result<ProjectFile, String> {
    let json = fs::read_to_string(&path).map_err(|e| format!("Failed to read project: {e}"))?;
    serde_json::from_str(&json).map_err(|e| format!("Invalid project file: {e}"))
}

#[tauri::command]
fn save_settings(settings: AppSettings) -> Result<(), String> {
    let path = settings_path()?;
    let json = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    fs::write(&path, json).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn load_settings() -> Result<AppSettings, String> {
    let path = settings_path()?;
    if !path.exists() {
        return Ok(AppSettings::default());
    }
    let json = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&json).map_err(|e| e.to_string())
}

#[tauri::command]
fn get_app_data_dir() -> Result<String, String> {
    Ok(app_storage_root()?.to_string_lossy().to_string())
}

#[tauri::command]
fn get_app_storage_layout() -> Result<AppStorageLayout, String> {
    let layout = ensure_app_storage_layout()?;
    Ok(AppStorageLayout {
        root_dir: layout.root_dir.to_string_lossy().to_string(),
        uploads_dir: layout.uploads_dir.to_string_lossy().to_string(),
        staging_dir: layout.staging_dir.to_string_lossy().to_string(),
        rendered_videos_dir: layout.rendered_videos_dir.to_string_lossy().to_string(),
        proxies_dir: layout.proxies_dir.to_string_lossy().to_string(),
        temp_dir: layout.temp_dir.to_string_lossy().to_string(),
        logs_dir: layout.logs_dir.to_string_lossy().to_string(),
        config_dir: layout.config_dir.to_string_lossy().to_string(),
        backups_dir: layout.backups_dir.to_string_lossy().to_string(),
    })
}

#[tauri::command]
fn bootstrap_desktop_backend(app: AppHandle) -> Result<DesktopBootstrapResult, String> {
    const BACKEND_PORT: u16 = 18000;
    const COMPOSE_PROJECT_NAME: &str = "aive-desktop";

    let layout = ensure_app_storage_layout()?;
    let env_file = write_desktop_backend_env(&layout, BACKEND_PORT)?;
    let compose_file = desktop_compose_path(&app)?;
    let compose_dir = compose_file
        .parent()
        .ok_or_else(|| "Desktop compose file does not have a parent directory".to_string())?
        .to_path_buf();
    let backend_url = format!("http://127.0.0.1:{BACKEND_PORT}");
    let mut items = Vec::new();

    let docker_available = run_command("docker", &["--version"])?;
    items.push(ReadinessItem {
        key: "docker_cli".to_string(),
        label: "Docker Desktop".to_string(),
        status: "ready".to_string(),
        detail: docker_available.trim().to_string(),
    });

    let compose_available = run_command("docker", &["compose", "version"])?;
    items.push(ReadinessItem {
        key: "docker_compose".to_string(),
        label: "Docker Compose".to_string(),
        status: "ready".to_string(),
        detail: compose_available.trim().to_string(),
    });

    if run_command("docker", &["info"]).is_err() {
        let started = start_docker_desktop()?;
        items.push(ReadinessItem {
            key: "docker_engine".to_string(),
            label: "Docker engine".to_string(),
            status: "starting".to_string(),
            detail: started,
        });
        wait_for_docker_engine(Duration::from_secs(120))?;
    }
    items.push(ReadinessItem {
        key: "docker_engine".to_string(),
        label: "Docker engine".to_string(),
        status: "ready".to_string(),
        detail: "Docker engine is reachable.".to_string(),
    });

    run_command_in_dir(
        "docker",
        &[
            "compose",
            "--env-file",
            env_file.to_string_lossy().as_ref(),
            "-f",
            compose_file.to_string_lossy().as_ref(),
            "-p",
            COMPOSE_PROJECT_NAME,
            "up",
            "-d",
            "--build",
        ],
        compose_dir.as_path(),
    )?;

    let running_services = run_command_in_dir(
        "docker",
        &[
            "compose",
            "--env-file",
            env_file.to_string_lossy().as_ref(),
            "-f",
            compose_file.to_string_lossy().as_ref(),
            "-p",
            COMPOSE_PROJECT_NAME,
            "ps",
            "--services",
            "--status",
            "running",
        ],
        compose_dir.as_path(),
    )?;
    for service in ["backend", "db", "redis", "qdrant"] {
        let running = running_services.lines().any(|line| line.trim() == service);
        items.push(ReadinessItem {
            key: service.to_string(),
            label: match service {
                "db" => "PostgreSQL".to_string(),
                "redis" => "Redis".to_string(),
                "qdrant" => "Qdrant".to_string(),
                _ => "Backend".to_string(),
            },
            status: if running { "ready".to_string() } else { "warning".to_string() },
            detail: if running {
                "Service is running inside Docker.".to_string()
            } else {
                "Service is not yet reported as running.".to_string()
            },
        });
    }

    wait_for_http_health(&format!("{backend_url}/health"), Duration::from_secs(120))?;
    items.push(ReadinessItem {
        key: "backend_health".to_string(),
        label: "Backend health".to_string(),
        status: "ready".to_string(),
        detail: format!("Healthy at {backend_url}/health"),
    });
    items.push(ReadinessItem {
        key: "storage".to_string(),
        label: "Available storage".to_string(),
        status: "ready".to_string(),
        detail: layout.root_dir.to_string_lossy().to_string(),
    });

    Ok(DesktopBootstrapResult {
        ready: true,
        backend_url,
        compose_project_name: COMPOSE_PROJECT_NAME.to_string(),
        env_file: env_file.to_string_lossy().to_string(),
        items,
    })
}

#[tauri::command]
async fn start_native_primary_import(
    window: Window,
    registry_state: State<'_, NativeImportRegistry>,
    project_id: String,
    source_path: String,
    backend_url: String,
) -> Result<NativeImportCommandResult, String> {
    let registry = registry_state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let source = fs::canonicalize(Path::new(&source_path))
            .map_err(|e| format!("Could not access selected file: {e}"))?;
        let metadata = fs::metadata(&source).map_err(|e| format!("Could not read file metadata: {e}"))?;
        let filename = source
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| "Could not determine the selected file name".to_string())?
            .to_string();
        let file_size_bytes = metadata.len();
        let mime_type = infer_mime_type(&source);
        let client = Client::builder()
            .timeout(Duration::from_secs(120))
            .build()
            .map_err(|e| format!("Could not create HTTP client: {e}"))?;
        let api_base = api_base_url(&backend_url);

        let init_response = client
            .post(format!("{api_base}/projects/{project_id}/imports/native/primary/init"))
            .json(&NativeImportInitRequest {
                original_filename: filename.clone(),
                file_size_bytes,
                mime_type: mime_type.clone(),
            })
            .send()
            .and_then(|res| res.error_for_status())
            .map_err(|e| format!("Could not initialize native import: {e}"))?
            .json::<NativeImportInitResponse>()
            .map_err(|e| format!("Could not parse native import session: {e}"))?;

        let cancel_flag = registry.register(&init_response.token);
        emit_native_import_progress(
            &window,
            &NativeImportProgressEvent {
                token: init_response.token.clone(),
                project_id: init_response.project_id.clone(),
                filename: filename.clone(),
                status: "copying".to_string(),
                bytes_copied: 0,
                total_bytes: file_size_bytes,
                percent: 0.0,
                bytes_per_second: 0.0,
                eta_seconds: None,
                message: "Preparing native file copy...".to_string(),
            },
        );

        let result = (|| {
            let layout = ensure_app_storage_layout()?;
            let staged_path = layout
                .uploads_dir
                .join(init_response.staging_relative_path.replace('/', "\\"));
            let part_path = layout
                .uploads_dir
                .join(init_response.staging_part_relative_path.replace('/', "\\"));
            if let Some(parent) = part_path.parent() {
                fs::create_dir_all(parent).map_err(|e| format!("Could not prepare staging directory: {e}"))?;
            }

            copy_file_with_progress(
                &source,
                &part_path,
                &window,
                &project_id,
                &filename,
                &init_response.token,
                file_size_bytes,
                cancel_flag.clone(),
            )?;

            if part_path.exists() {
                fs::rename(&part_path, &staged_path).map_err(|e| format!("Could not finalize staged file: {e}"))?;
            }

            emit_native_import_progress(
                &window,
                &NativeImportProgressEvent {
                    token: init_response.token.clone(),
                    project_id: init_response.project_id.clone(),
                    filename: filename.clone(),
                    status: "finalizing".to_string(),
                    bytes_copied: file_size_bytes,
                    total_bytes: file_size_bytes,
                    percent: 100.0,
                    bytes_per_second: 0.0,
                    eta_seconds: Some(0.0),
                    message: "Finalizing import with the backend...".to_string(),
                },
            );

            let finalize_response = client
                .post(format!(
                    "{api_base}/projects/{project_id}/imports/native/primary/{}/finalize",
                    init_response.token
                ))
                .json(&NativeImportFinalizeRequest { copied_file_size_bytes: file_size_bytes })
                .send()
                .and_then(|res| res.error_for_status())
                .map_err(|e| format!("Could not finalize native import: {e}"))?
                .json::<NativeImportFinalizeResponse>()
                .map_err(|e| format!("Could not parse finalize response: {e}"))?;

            emit_native_import_progress(
                &window,
                &NativeImportProgressEvent {
                    token: init_response.token.clone(),
                    project_id: init_response.project_id.clone(),
                    filename: filename.clone(),
                    status: "completed".to_string(),
                    bytes_copied: file_size_bytes,
                    total_bytes: file_size_bytes,
                    percent: 100.0,
                    bytes_per_second: 0.0,
                    eta_seconds: Some(0.0),
                    message: "Native import completed.".to_string(),
                },
            );

            Ok(NativeImportCommandResult {
                token: init_response.token.clone(),
                project_id: finalize_response.project_id.unwrap_or(init_response.project_id.clone()),
                video_id: finalize_response.id,
                filename: finalize_response.filename,
            })
        })();

        if cancel_flag.load(Ordering::Relaxed) {
            let _ = client
                .post(format!(
                    "{api_base}/projects/{project_id}/imports/native/primary/{}/cancel",
                    init_response.token
                ))
                .send();
            emit_native_import_progress(
                &window,
                &NativeImportProgressEvent {
                    token: init_response.token.clone(),
                    project_id: init_response.project_id.clone(),
                    filename,
                    status: "cancelled".to_string(),
                    bytes_copied: 0,
                    total_bytes: file_size_bytes,
                    percent: 0.0,
                    bytes_per_second: 0.0,
                    eta_seconds: None,
                    message: "Native import cancelled.".to_string(),
                },
            );
        }

        registry.unregister(&init_response.token);
        result
    })
    .await
    .map_err(|e| format!("Native import task failed: {e}"))?
}

#[tauri::command]
fn cancel_native_import(
    registry_state: State<'_, NativeImportRegistry>,
    token: String,
) -> Result<bool, String> {
    Ok(registry_state.inner().request_cancel(&token))
}

fn emit_native_import_progress(window: &Window, payload: &NativeImportProgressEvent) {
    let _ = window.emit("native-import-progress", payload);
}

fn copy_file_with_progress(
    source: &Path,
    target: &Path,
    window: &Window,
    project_id: &str,
    filename: &str,
    token: &str,
    total_bytes: u64,
    cancel_flag: Arc<AtomicBool>,
) -> Result<(), String> {
    let mut reader = fs::File::open(source).map_err(|e| format!("Could not open source file: {e}"))?;
    let mut writer = fs::File::create(target).map_err(|e| format!("Could not create staging file: {e}"))?;
    let mut buffer = vec![0_u8; 8 * 1024 * 1024];
    let mut copied = 0_u64;
    let start = Instant::now();
    let mut last_emit = Instant::now();

    loop {
        if cancel_flag.load(Ordering::Relaxed) {
            drop(writer);
            let _ = fs::remove_file(target);
            return Err("Import cancelled.".to_string());
        }

        let read = reader.read(&mut buffer).map_err(|e| format!("Could not read source file: {e}"))?;
        if read == 0 {
            break;
        }
        writer
            .write_all(&buffer[..read])
            .map_err(|e| format!("Could not write staged file: {e}"))?;
        copied += read as u64;

        if last_emit.elapsed() >= Duration::from_millis(250) || copied == total_bytes {
            let elapsed = start.elapsed().as_secs_f64().max(0.001);
            let bytes_per_second = copied as f64 / elapsed;
            let remaining = total_bytes.saturating_sub(copied);
            let eta_seconds = if bytes_per_second > 0.0 {
                Some(remaining as f64 / bytes_per_second)
            } else {
                None
            };
            emit_native_import_progress(
                window,
                &NativeImportProgressEvent {
                    token: token.to_string(),
                    project_id: project_id.to_string(),
                    filename: filename.to_string(),
                    status: "copying".to_string(),
                    bytes_copied: copied,
                    total_bytes,
                    percent: if total_bytes == 0 {
                        0.0
                    } else {
                        (copied as f64 / total_bytes as f64) * 100.0
                    },
                    bytes_per_second,
                    eta_seconds,
                    message: "Copying file into application storage...".to_string(),
                },
            );
            last_emit = Instant::now();
        }
    }

    writer.flush().map_err(|e| format!("Could not flush staged file: {e}"))?;
    if copied != total_bytes {
        return Err(format!("Copied {copied} bytes but expected {total_bytes} bytes"));
    }
    Ok(())
}

#[derive(Clone)]
struct StorageLayoutPaths {
    root_dir: PathBuf,
    uploads_dir: PathBuf,
    staging_dir: PathBuf,
    rendered_videos_dir: PathBuf,
    proxies_dir: PathBuf,
    temp_dir: PathBuf,
    logs_dir: PathBuf,
    config_dir: PathBuf,
    backups_dir: PathBuf,
}

fn ensure_app_storage_layout() -> Result<StorageLayoutPaths, String> {
    let root_dir = app_storage_root()?;
    let uploads_dir = root_dir.join("uploads");
    let staging_dir = uploads_dir.join("staging").join("native-imports");
    let rendered_videos_dir = root_dir.join("rendered-videos");
    let proxies_dir = root_dir.join("proxies");
    let temp_dir = root_dir.join("temp");
    let logs_dir = root_dir.join("logs");
    let config_dir = root_dir.join("config");
    let backups_dir = root_dir.join("backups");

    for dir in [
        &root_dir,
        &uploads_dir,
        &staging_dir,
        &rendered_videos_dir,
        &proxies_dir,
        &temp_dir,
        &logs_dir,
        &config_dir,
        &backups_dir,
    ] {
        fs::create_dir_all(dir).map_err(|e| format!("Could not prepare app storage directory {}: {e}", dir.display()))?;
    }

    Ok(StorageLayoutPaths {
        root_dir,
        uploads_dir,
        staging_dir,
        rendered_videos_dir,
        proxies_dir,
        temp_dir,
        logs_dir,
        config_dir,
        backups_dir,
    })
}

fn settings_path() -> Result<PathBuf, String> {
    Ok(ensure_app_storage_layout()?.config_dir.join("settings.json"))
}

fn app_storage_root() -> Result<PathBuf, String> {
    dirs::data_local_dir()
        .map(|path| path.join("AI Video Editor"))
        .ok_or_else(|| "Cannot determine local application data directory".to_string())
}

fn default_backend_url() -> String {
    "http://localhost:8000".to_string()
}

fn default_asr_provider() -> String {
    "voxtral".to_string()
}

fn default_auto_accept_threshold() -> f64 {
    0.85
}

fn default_appearance_theme() -> String {
    "dark".to_string()
}

fn default_interface_density() -> String {
    "comfortable".to_string()
}

fn default_true() -> bool {
    true
}

fn infer_mime_type(path: &Path) -> Option<String> {
    match path.extension().and_then(|ext| ext.to_str()).map(|ext| ext.to_ascii_lowercase()) {
        Some(ext) if ext == "mp4" => Some("video/mp4".to_string()),
        Some(ext) if ext == "mov" => Some("video/quicktime".to_string()),
        Some(ext) if ext == "avi" => Some("video/x-msvideo".to_string()),
        Some(ext) if ext == "webm" => Some("video/webm".to_string()),
        Some(ext) if ext == "mpeg" || ext == "mpg" => Some("video/mpeg".to_string()),
        Some(ext) if ext == "mkv" => Some("video/x-matroska".to_string()),
        _ => None,
    }
}

fn desktop_workspace_root() -> Result<PathBuf, String> {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .map(Path::to_path_buf)
        .ok_or_else(|| "Could not determine the desktop workspace root".to_string())
}

fn desktop_compose_path(app: &AppHandle) -> Result<PathBuf, String> {
    let compose_path = desktop_workspace_root()?.join("docker-compose.desktop.yml");
    if compose_path.exists() {
        return Ok(compose_path);
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Could not resolve the app resource directory: {e}"))?;
    let bundled_path = resource_dir.join("docker-compose.desktop.yml");
    if bundled_path.exists() {
        return Ok(bundled_path);
    }

    Err(format!(
        "Desktop compose file not found at {} or {}",
        compose_path.display(),
        bundled_path.display()
    ))
}

fn write_desktop_backend_env(layout: &StorageLayoutPaths, backend_port: u16) -> Result<PathBuf, String> {
    let env_path = layout.config_dir.join("desktop-backend.env");
    let contents = format!(
        concat!(
            "AIVE_DESKTOP_ENV_FILE={env_path}\n",
            "AIVE_HOST_UPLOADS_DIR={uploads}\n",
            "AIVE_HOST_VIDEOS_DIR={videos}\n",
            "AIVE_HOST_TEMP_DIR={temp}\n",
            "AIVE_HOST_LOGS_DIR={logs}\n",
            "AIVE_HOST_CONFIG_DIR={config}\n",
            "AIVE_HOST_BACKUPS_DIR={backups}\n",
            "AIVE_HOST_PROXIES_DIR={proxies}\n",
            "AIVE_HOST_MODELS_DIR={models}\n",
            "AIVE_HOST_POSTGRES_DIR={postgres}\n",
            "AIVE_HOST_REDIS_DIR={redis}\n",
            "AIVE_HOST_QDRANT_DIR={qdrant}\n",
            "AIVE_BACKEND_PORT={backend_port}\n",
            "DATABASE_URL=postgresql+asyncpg://aive:aive_secret@db:5432/aive_db\n",
            "REDIS_URL=redis://redis:6379/0\n",
            "QDRANT_HOST=qdrant\n",
            "QDRANT_PORT=6333\n",
            "APP_ENV=production\n",
            "APP_DEBUG=false\n"
        ),
        env_path = env_path.to_string_lossy(),
        uploads = layout.uploads_dir.to_string_lossy(),
        videos = layout.rendered_videos_dir.to_string_lossy(),
        temp = layout.temp_dir.to_string_lossy(),
        logs = layout.logs_dir.to_string_lossy(),
        config = layout.config_dir.to_string_lossy(),
        backups = layout.backups_dir.to_string_lossy(),
        proxies = layout.proxies_dir.to_string_lossy(),
        models = layout.root_dir.join("models").to_string_lossy(),
        postgres = layout.root_dir.join("postgresql").to_string_lossy(),
        redis = layout.root_dir.join("redis").to_string_lossy(),
        qdrant = layout.root_dir.join("qdrant").to_string_lossy(),
        backend_port = backend_port,
    );
    fs::write(&env_path, contents).map_err(|e| format!("Could not write backend env file: {e}"))?;
    Ok(env_path)
}

fn run_command(program: &str, args: &[&str]) -> Result<String, String> {
    let output = Command::new(program)
        .args(args)
        .output()
        .map_err(|e| format!("Could not run {program}: {e}"))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

fn run_command_in_dir(program: &str, args: &[&str], dir: &Path) -> Result<String, String> {
    let output = Command::new(program)
        .current_dir(dir)
        .args(args)
        .output()
        .map_err(|e| format!("Could not run {program}: {e}"))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

fn start_docker_desktop() -> Result<String, String> {
    let candidates = [
        PathBuf::from(r"C:\Program Files\Docker\Docker\Docker Desktop.exe"),
        dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from(r"C:\Users\Public\AppData\Local"))
            .join("Programs")
            .join("Docker")
            .join("Docker")
            .join("Docker Desktop.exe"),
    ];

    for candidate in candidates {
        if candidate.exists() {
            Command::new("cmd")
                .args(["/C", "start", "", candidate.to_string_lossy().as_ref()])
                .spawn()
                .map_err(|e| format!("Could not start Docker Desktop: {e}"))?;
            return Ok(format!("Starting Docker Desktop from {}", candidate.display()));
        }
    }

    Err("Docker Desktop is installed neither in the default Program Files path nor the Local Programs path".to_string())
}

fn wait_for_docker_engine(timeout: Duration) -> Result<(), String> {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if run_command("docker", &["info"]).is_ok() {
            return Ok(());
        }
        sleep(Duration::from_secs(5));
    }
    Err("Docker engine did not become ready in time".to_string())
}

fn wait_for_http_health(url: &str, timeout: Duration) -> Result<(), String> {
    let client = Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|e| format!("Could not create HTTP client: {e}"))?;
    let started = Instant::now();
    while started.elapsed() < timeout {
        if let Ok(response) = client.get(url).send() {
            if response.status().is_success() {
                return Ok(());
            }
        }
        sleep(Duration::from_secs(5));
    }
    Err(format!("Backend health check did not become ready at {url}"))
}

fn api_base_url(raw: &str) -> String {
    let trimmed = raw.trim_end_matches('/');
    if trimmed.ends_with("/api/v1") {
        trimmed.to_string()
    } else {
        format!("{trimmed}/api/v1")
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(NativeImportRegistry::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            save_project,
            load_project,
            save_settings,
            load_settings,
            get_app_data_dir,
            get_app_storage_layout,
            bootstrap_desktop_backend,
            start_native_primary_import,
            cancel_native_import,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
