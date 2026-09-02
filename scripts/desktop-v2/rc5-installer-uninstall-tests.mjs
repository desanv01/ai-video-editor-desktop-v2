import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

const readSource = relativePath => readFile(path.join(repoRoot, relativePath), "utf8");

const [installer, migration, migrationClient, desktopV2, contracts, app, componentManager, nativeBuild, providerCredentials, tauriConfig] = await Promise.all([
  readSource("desktop/src-tauri/nsis/installer-hooks.nsh"),
  readSource("desktop/src-tauri/src/migration.rs"),
  readSource("desktop/src/migration.ts"),
  readSource("desktop/src-tauri/src/desktop_v2.rs"),
  readSource("desktop/src-tauri/src/contracts.rs"),
  readSource("desktop/src-tauri/src/lib.rs"),
  readSource("desktop/src-tauri/src/component_manager.rs"),
  readSource("scripts/desktop-v2/build_native_engine.py"),
  readSource("desktop/src-tauri/src/provider_credentials.rs"),
  readSource("desktop/src-tauri/tauri.conf.json"),
]);

function mustInclude(source, text, message) {
  assert.ok(source.includes(text), message);
}

const installerCode = installer
  .split(/\r?\n/)
  .filter(line => !/^\s*;/.test(line))
  .join("\n");

// The shell has one stable per-machine owner and the runtime never relocates
// that owner to a user-writable application-data directory.
mustInclude(migration, 'pub const V2_PROGRAM_FILES_DIRECTORY: &str = "AI Video Editor Desktop V2";', "migration must name the canonical V2 Program Files directory");
assert.match(
  migration,
  /fn v2_shell_path\(roots: &MigrationRoots\)[\s\S]*?roots\s*\.program_files\s*\.join\(V2_PROGRAM_FILES_DIRECTORY\)\s*\.join\("Shell"\)/,
  "migration must resolve the shell below Program Files\\AI Video Editor Desktop V2\\Shell",
);
assert.match(
  desktopV2,
  /let shell_install = roots\s*\.program_files\s*\.join\(PROGRAM_FILES_DIRECTORY\)\s*\.join\("Shell"\)/,
  "Desktop V2 path resolution must derive the shell from the Program Files root",
);
mustInclude(installer, 'StrCpy $INSTDIR "$PROGRAMFILES64\\AI Video Editor Desktop V2\\Shell"', "NSIS must install the shell at the canonical x64 Program Files path");
mustInclude(installer, "SetShellVarContext all", "the installer must use a per-machine shell context");
mustInclude(installer, "SetRegView 64", "the installer must use the 64-bit machine registry view");
mustInclude(installer, '"InstallPath" "$INSTDIR"', "the installer identity must point at the canonical shell directory");
assert.match(tauriConfig, /"installMode":\s*"perMachine"/, "Tauri must declare a per-machine installer");
assert.match(tauriConfig, /"startMenuFolder":\s*"AI Video Editor Desktop V2"/, "the Start Menu owner must use the V2 identity");
mustInclude(contracts, 'shell_install: storage_descriptor("%ProgramFiles%\\\\AI Video Editor Desktop V2\\\\Shell"', "storage contracts must publish the canonical shell path");
mustInclude(contracts, "program_files_runtime_writable: false", "Program Files must remain immutable at runtime");
assert.match(migration, /V2_PRODUCT_IDENTIFIER|com\.fyp\.ai-video-editor\.desktop-v2/, "installer identity ownership must be product-scoped");

// Tauri's generated NSIS section is the installer shortcut owner. Repair may
// restore the two known V2 links only when explicitly requested.
assert.doesNotMatch(installerCode, /CreateShortCut/i, "the custom NSIS hook must not create a duplicate shortcut");
assert.match(installer, /generated Tauri NSIS section is the sole shortcut owner/i, "shortcut ownership must be documented at the installer boundary");
assert.doesNotMatch(installerCode, /\bStrCmp\s+\/I\b/, "NSIS StrCmp does not accept an /I parameter");
const shortcutSectionStart = migration.indexOf("fn shortcut_paths_for_v2");
const shortcutSectionEnd = migration.indexOf("fn write_shortcut", shortcutSectionStart);
assert.ok(shortcutSectionStart >= 0 && shortcutSectionEnd > shortcutSectionStart, "V2 shortcut ownership helper must be present");
const shortcutSection = migration.slice(shortcutSectionStart, shortcutSectionEnd);
assert.match(shortcutSection, /if let Some\(desktop\)/, "repair must target the explicit Desktop location");
assert.match(shortcutSection, /if let Some\(start_menu\)/, "repair must target the explicit Start Menu location");
assert.equal(
  (shortcutSection.match(/AI Video Editor Desktop V2\.lnk/g) ?? []).length,
  2,
  "the repair helper must enumerate exactly the two known V2 shortcut locations",
);
assert.match(migration, /if options\.restore_shortcuts/, "shortcut repair must be opt-in rather than part of default installation");

// Default uninstall removes shell/runtime state only. User content and
// settings are represented as preserve-by-default paths, while credentials
// remain in the separately-owned Windows Credential Manager namespace.
const uninstallStart = migration.indexOf("fn uninstall_paths");
const processCandidatesStart = migration.indexOf("fn owned_process_candidates", uninstallStart);
assert.ok(uninstallStart >= 0 && processCandidatesStart > uninstallStart, "uninstall path policy must be present");
const uninstallSection = migration.slice(uninstallStart, processCandidatesStart);
const removalBuilder = uninstallSection.slice(
  uninstallSection.indexOf("let mut remove = Vec::new();"),
  uninstallSection.indexOf("let preserve_relatives = ["),
);
assert.doesNotMatch(removalBuilder, /Config|uploads|models|database|postgresql|qdrant|Projects|Exports/i, "default removal paths must not include user content or settings");
for (const relative of ["Config", "uploads", "models", "database", "postgresql", "qdrant"]) {
  assert.match(uninstallSection, new RegExp(`"${relative}"`), `default uninstall must preserve the V2 ${relative} path`);
}
for (const [relative, classification] of [["Projects", "projects"], ["Exports", "exports"], ["Models", "models"]]) {
  assert.match(
    uninstallSection,
    new RegExp(`documents\\.join\\("${relative}"\\)[\\s\\S]*?"${classification}"`),
    `default uninstall must preserve Documents\\${relative}`,
  );
}
assert.match(uninstallSection, /remove_by_default:\s*false[\s\S]*?preserve_by_default:\s*true/, "preserved paths must be excluded from the default removal set");
assert.match(migration, /default_choice:\s*"remove-shell-runtime-preserve-user-data"/, "the default uninstall choice must be data-preserving");
assert.match(installer, /Config, uploads, models, database,[\s\S]*projects, and exports are deliberately preserved/i, "the NSIS uninstall hook must state its data-preserving contract");
const destructiveHookLines = installerCode
  .split(/\r?\n/)
  .filter(line => /\b(?:RMDir|Delete)\b/i.test(line))
  .join("\n");
assert.doesNotMatch(destructiveHookLines, /\$5\\(?:Config|uploads|models|database|Projects|Exports)/i, "NSIS must not remove user content or settings roots");
assert.doesNotMatch(destructiveHookLines, /\$2\\(?:Config|uploads|models|database|Projects|Exports)/i, "machine cleanup must not reach user content names");
assert.doesNotMatch(installerCode, /CredDelete|provider_credential_clear|Credential Manager/i, "default NSIS uninstall must not clear provider credentials");
mustInclude(providerCredentials, 'pub const PROVIDER_CREDENTIAL_STORAGE: &str = "windows-credential-manager-per-user";', "provider credentials must have a protected per-user storage owner");
mustInclude(providerCredentials, "Credential Manager", "provider credential ownership must be explicit");
mustInclude(providerCredentials, "provider_credential_clear", "credential deletion must remain an explicit provider command");
assert.doesNotMatch(uninstallSection, /provider_credential_clear|CredDelete|provider\/|credential.*remove/i, "the default uninstall plan must not schedule provider credential deletion");

// Runtime payloads are immutable on disk and start in place from the verified
// component tree. AppData is reserved for per-user WebView2 data, not runtime
// extraction or native component installation.
assert.match(componentManager, /It never\s*\r?\n\/\/!\s+writes to Program Files, AppData, projects, exports/i, "component management must exclude AppData runtime writes");
assert.match(nativeBuild, /one-file\s+mode[\s\S]*engine can start directly from it without extraction at runtime/i, "native packaging must avoid runtime extraction");
assert.match(desktopV2, /let shared_components = roots[\s\S]*?\.program_data[\s\S]*?\.join\("Components"\)/, "native components must resolve under ProgramData");
assert.match(app, /fn webview_user_data_directory\(local_app_data: &Path\)[\s\S]*?local_app_data\.join\(desktop_v2::PRODUCT_IDENTIFIER\)/, "only per-user WebView2 data may use LocalAppData");
assert.doesNotMatch(installerCode, /\bSetOutPath\s+[^\r\n]*\$APPDATA/i, "NSIS must not extract runtime payloads into APPDATA");
assert.equal((installerCode.match(/\bSetOutPath\b/gi) ?? []).length, 1, "the custom hook must have one immutable shell output target");
mustInclude(installer, "SetOutPath $INSTDIR", "the custom hook output target must remain the canonical shell directory");
assert.doesNotMatch(tauriConfig, /AppData/i, "bundle configuration must not declare an AppData runtime payload");

// Full wipe is a separate, bounded operation: it defaults off, requires the
// exact phrase, and can only act on the precomputed safe-boundary paths.
mustInclude(migration, 'pub const FULL_WIPE_CONFIRMATION: &str = "REMOVE ALL AI VIDEO EDITOR USER DATA";', "full wipe must have one exact confirmation phrase");
assert.match(migrationClient, /FULL_WIPE_CONFIRMATION\s*=\s*"REMOVE ALL AI VIDEO EDITOR USER DATA"/, "the UI contract must expose the same exact full-wipe phrase");
assert.match(migration, /remove_all_user_data:\s*bool/, "full wipe must be an explicit uninstall option");
assert.match(migration, /remove_all_user_data:\s*false/, "full wipe must default to disabled");
assert.match(migration, /if options\.remove_all_user_data\s*&& options\.confirmation\.as_deref\(\) != Some\(FULL_WIPE_CONFIRMATION\)/, "full wipe must reject missing or incorrect confirmation");
assert.match(uninstallSection, /let full_wipe = preserve[\s\S]*?path\.remove_by_default = false;[\s\S]*?path\.preserve_by_default = false;[\s\S]*?Remove only after exact full-wipe confirmation/i, "full wipe must be limited to the explicit preserve set");
assert.match(migration, /if options\.remove_all_user_data\s*\{[\s\S]*?for item in &plan\.full_wipe_paths[\s\S]*?report\.preserved_paths\.clear\(\)/, "only an explicit full-wipe request may consume full-wipe paths");
assert.match(migration, /let allowlisted = plan[\s\S]*?all_allowlisted_roots\(\)/, "uninstall execution must derive an allowlisted root set");
assert.match(migration, /if !item\.safe_boundary[\s\S]*?path_has_reparse_between/, "uninstall execution must enforce safe boundaries and reject reparse escapes");
assert.doesNotMatch(installerCode, /RMDir\s+\/r\s+"\$5"/i, "NSIS must not recursively wipe the entire per-user root by default");

console.log("Desktop V2 RC5 installer/uninstall tests passed: canonical shell ownership, single-owner shortcuts, data-preserving default uninstall, Credential Manager retention, no AppData runtime extraction, and bounded explicit full wipe.");
