import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const libSource = fs.readFileSync(path.join(repoRoot, "desktop", "src-tauri", "src", "lib.rs"), "utf8");
const installerSource = fs.readFileSync(
  path.join(repoRoot, "desktop", "src-tauri", "nsis", "installer-hooks.nsh"),
  "utf8",
);

assert.match(libSource, /fn webview_user_data_directory\(local_app_data: &Path\)/);
assert.match(libSource, /local_app_data\.join\(desktop_v2::PRODUCT_IDENTIFIER\)/);
assert.match(libSource, /dirs::data_local_dir\(\)/);
assert.match(libSource, /fs::create_dir_all\(&directory\)/);
assert.match(libSource, /create_new\(true\)/);
assert.match(libSource, /per-user WebView2 data directory/);
assert.match(libSource, /ensure_webview_user_data_directory\(\)/);
const runIndex = libSource.indexOf("pub fn run()");
const preflightCallIndex = libSource.indexOf("ensure_webview_user_data_directory()", runIndex);
assert.ok(
  preflightCallIndex >= 0 && preflightCallIndex < libSource.indexOf("tauri::Builder::default()", runIndex),
  "the per-user WebView2 preflight must run before Tauri constructs its first window",
);
assert.doesNotMatch(
  installerSource,
  /(?:APPDATA|LOCALAPPDATA)[^\r\n]*com\.fyp\.ai-video-editor\.desktop-v2/,
  "the per-machine installer must not create a per-user WebView2 directory for the installing administrator",
);

console.log("webview-user-data-tests: PASS (launch-user preflight and installer separation)");
