// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if ai_video_editor_lib::component_broker::run_broker_cli() {
        return;
    }
    ai_video_editor_lib::run()
}
