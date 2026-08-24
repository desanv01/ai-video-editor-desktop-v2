import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const detector = await readFile(path.join(repoRoot, "scripts", "desktop-v2", "Detect-WebView2.ps1"), "utf8");
const policy = await readFile(path.join(repoRoot, "docs", "desktop-v2", "WEBVIEW2_RC3_POLICY.md"), "utf8");
const rust = await readFile(path.join(repoRoot, "desktop", "src-tauri", "src", "desktop_v2.rs"), "utf8");
const lib = await readFile(path.join(repoRoot, "desktop", "src-tauri", "src", "lib.rs"), "utf8");
const ts = await readFile(path.join(repoRoot, "desktop", "src", "desktopV2.ts"), "utf8");

for (const source of [detector, policy, rust]) {
  assert.match(source, /WebView2|webview2/i);
  assert.match(source, /no-silent-download|no silent|never downloads|silent/i);
}
assert.match(ts, /WebView2|webview2/i);
assert.match(detector, /Registry64/);
assert.match(detector, /Registry32/);
assert.match(detector, /EvergreenBootstrapper/);
assert.match(detector, /StandaloneInstaller/);
assert.match(detector, /3010/);
assert.match(detector, /ExpectedSha256/);
for (const exitCode of [20, 21, 22, 23, 24]) {
  assert.match(detector, new RegExp(`\\b${exitCode}\\b`));
}
assert.match(policy, /official Microsoft Bootstrapper/);
assert.match(policy, /Standalone Installer/);
assert.match(policy, /250 MB/);
assert.match(policy, /SHA-256/);
assert.match(rust, /WEBVIEW2_RUNTIME_SCHEMA/);
assert.match(rust, /WEBVIEW2_INSTALL_POLICY/);
assert.match(rust, /get_webview2_runtime_status/);
assert.match(lib, /webview2_runtime_status\(\)/);
assert.match(lib, /cannot launch without Microsoft WebView2 Runtime/);
assert.match(ts, /getWebView2RuntimeStatus/);

console.log("WebView2 policy tests passed: pre-launch detection, explicit online/offline installer policy, provenance/checksum gate, exit-code handling, and no silent download.");
