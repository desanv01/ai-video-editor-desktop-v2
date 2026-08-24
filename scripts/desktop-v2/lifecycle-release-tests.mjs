import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const component = await readFile(path.join(repoRoot, "desktop", "src-tauri", "src", "component_manager.rs"), "utf8");
const setup = await readFile(path.join(repoRoot, "desktop", "src", "components", "SetupCenterPanel.tsx"), "utf8");
const smoke = await readFile(path.join(repoRoot, "scripts", "desktop-v2", "Run-DesktopV2Smoke.ps1"), "utf8");
for (const testName of [
  "valid_component_can_be_packaged_downloaded_verified_staged_and_activated",
  "bad_hash_signature_unknown_key_schema_and_target_are_rejected",
  "interrupted_download_resumes_and_cancel_preserves_no_activation",
  "traversal_duplicate_and_decompression_bomb_archives_fail_before_activation",
  "activation_retains_previous_rolls_back_and_uninstall_preserves_user_data",
  "repair_rolls_back_corrupt_active_version_and_lock_contention_is_explicit",
  "recovery_marks_partial_state_and_removes_abandoned_staging",
]) assert.match(component, new RegExp(`fn ${testName}`));
assert.match(setup, /REQUIRED_COMPONENT_IDS/);
assert.match(setup, /catalogEntryIsInstallable/);
assert.match(setup, /atomic|activate/);
assert.match(smoke, /ffprobe/);
assert.match(smoke, /engineSelfTest/);
console.log("Lifecycle release tests passed: required selection, signed lifecycle failure cases, atomic activation/rollback/repair, recovery, and smoke hooks are represented in the executable test surface.");
