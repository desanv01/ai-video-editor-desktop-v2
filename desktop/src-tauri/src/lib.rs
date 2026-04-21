use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

/// Project file structure — saved as JSON to disk
#[derive(Serialize, Deserialize, Clone)]
pub struct ProjectFile {
    pub version: String,
    pub video_id: String,
    pub video_filename: String,
    pub backend_url: String,
    pub created_at: String,
    pub notes: String,
}

/// App settings persisted to disk
#[derive(Serialize, Deserialize, Clone)]
pub struct AppSettings {
    pub backend_url: String,
    pub asr_provider: String,
    pub domain_terms: Vec<String>,
    pub auto_accept_threshold: f64,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            backend_url: "http://localhost:8000".to_string(),
            asr_provider: "voxtral".to_string(),
            domain_terms: vec![],
            auto_accept_threshold: 0.85,
        }
    }
}

// ─── Tauri Commands ───

/// Save a project file to disk
#[tauri::command]
fn save_project(path: String, project: ProjectFile) -> Result<(), String> {
    let json = serde_json::to_string_pretty(&project).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| format!("Failed to save project: {}", e))?;
    Ok(())
}

/// Load a project file from disk
#[tauri::command]
fn load_project(path: String) -> Result<ProjectFile, String> {
    let json = fs::read_to_string(&path).map_err(|e| format!("Failed to read project: {}", e))?;
    serde_json::from_str(&json).map_err(|e| format!("Invalid project file: {}", e))
}

/// Save app settings
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

/// Load app settings (returns defaults if file doesn't exist)
#[tauri::command]
fn load_settings() -> Result<AppSettings, String> {
    let path = settings_path()?;
    if !path.exists() {
        return Ok(AppSettings::default());
    }
    let json = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&json).map_err(|e| e.to_string())
}

/// Get the app data directory path
#[tauri::command]
fn get_app_data_dir() -> Result<String, String> {
    let dir = dirs_next().ok_or("Cannot determine app data directory")?;
    Ok(dir.to_string_lossy().to_string())
}

// ─── Helpers ───

fn settings_path() -> Result<PathBuf, String> {
    let dir = dirs_next().ok_or("Cannot determine app data directory")?;
    Ok(dir.join("settings.json"))
}

fn dirs_next() -> Option<PathBuf> {
    dirs::config_dir().map(|d| d.join("ai-video-editor"))
}

// ─── App Builder ───

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            save_project,
            load_project,
            save_settings,
            load_settings,
            get_app_data_dir,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
