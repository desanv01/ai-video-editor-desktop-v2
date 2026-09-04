import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = relative => readFile(path.join(root, relative), "utf8");
const readJson = async relative => JSON.parse(await read(relative));

const [pkg, lock, tauri, cargo, cargoLock, hook, trust, build, migration, credentials, uninstallSchema, releaseSchema, ffmpeg, nativePackager, ffmpegProvenance, catalog, assembler, provenance, verifier, docs, lecturerSetup, lecturerInstall, lecturerUse, lecturerTroubleshooting, lecturerUninstall, smoke, productE2E] = await Promise.all([
  readJson("desktop/package.json"), readJson("desktop/package-lock.json"), readJson("desktop/src-tauri/tauri.conf.json"),
  read("desktop/src-tauri/Cargo.toml"), read("desktop/src-tauri/Cargo.lock"), read("desktop/src-tauri/nsis/installer-hooks.nsh"),
  read("desktop/src-tauri/src/release_trust.rs"), read("desktop/src-tauri/build.rs"), read("desktop/src-tauri/src/migration.rs"),
  read("desktop/src-tauri/src/provider_credentials.rs"), readJson("contracts/desktop-v2/schemas/uninstall-plan.v1.schema.json"), readJson("contracts/desktop-v2/schemas/release-manifest.v1.schema.json"),
  read("scripts/desktop-v2/package_ffmpeg_component.py"), read("scripts/desktop-v2/package_native_engine.py"), readJson("contracts/desktop-v2/ffmpeg-8.1.1.provenance.json"),
  read("scripts/desktop-v2/generate_signed_catalog.py"), read("scripts/desktop-v2/assemble_rc6_handoff.py"),
  read("scripts/desktop-v2/generate_rc6_release_provenance.py"), read("scripts/desktop-v2/Verify-RC6Release.ps1"),
  read("docs/desktop-v2/RC6_RELEASE_PROVENANCE.md"),
  read("docs/desktop-v2/RC6_LECTURER_SETUP.md"), read("docs/desktop-v2/RC6_LECTURER_INSTALL.md"),
  read("docs/desktop-v2/RC6_LECTURER_USE.md"), read("docs/desktop-v2/RC6_LECTURER_TROUBLESHOOTING.md"),
  read("docs/desktop-v2/RC6_LECTURER_UNINSTALL.md"), read("scripts/desktop-v2/Run-DesktopV2Smoke.ps1"),
  read("scripts/desktop-v2/rc6-native-product-e2e.py"),
]);
const installerTemplate = await read("desktop/src-tauri/nsis/installer-template.nsi");

for (const value of [pkg.version, lock.version, lock.packages[""].version, tauri.version]) assert.equal(value, "2.0.0-rc.6");
assert.match(cargo, /version = "2\.0\.0-rc\.6"/);
assert.match(cargoLock, /name = "ai-video-editor"\r?\nversion = "2\.0\.0-rc\.6"/);
assert.match(pkg.scripts["test:desktop-v2"], /rc6-release-installer-tests\.mjs/);
assert.equal(tauri.bundle.windows.nsis.installMode, "perMachine");
assert.equal(tauri.bundle.windows.nsis.template, "nsis/installer-template.nsi");
assert.equal(tauri.bundle.windows.wix.version, "2.0.0.6");
assert.equal(tauri.bundle.windows.wix.upgradeCode, "6c4eeeed-9b7e-5899-9880-d52cc92d1ae2");
assert.equal(tauri.bundle.windows.wix.enableElevatedUpdateTask, false);

const executableHook = hook.split(/\r?\n/).filter(line => !/^\s*;/.test(line)).join("\n");
const executableTemplate = installerTemplate.split(/\r?\n/).filter(line => !/^\s*;/.test(line)).join("\n");
assert.match(installerTemplate, /AIVEINSTALLERPARENT "\$PROGRAMFILES64\\AI Video Editor Desktop V2"/);
assert.match(hook, /\$APPDATA\\AI Video Editor/);
assert.match(hook, /\$LOCALAPPDATA\\AI Video Editor/);
assert.doesNotMatch(executableHook, /CreateShortCut/i);
assert.equal((executableTemplate.match(/\bCreateShortcut\b/g) ?? []).length, 2, "template must own exactly one Desktop and one Start Menu shortcut");
assert.equal((installerTemplate.match(/IsShortcutTarget/g) ?? []).length, 6, "template must verify both shortcuts at install, uninstall, and interrupted-uninstall recovery");
assert.match(installerTemplate, /Call CreateAndVerifyRequiredShortcuts[\s\S]*?Call CommitInstallRegistration/);
assert.match(installerTemplate, /Delete \/REBOOTOK "\$INSTDIR\\\$\{AIVEIDENTITY\}"/);
assert.match(installerTemplate, /RMDir \/REBOOTOK "\$INSTDIR"/);
assert.doesNotMatch(installerTemplate, /RMDir \/r \/REBOOTOK "\$INSTDIR"/i);

assert.match(migration, /FULL_WIPE_CONFIRMATION: &str = "REMOVE ALL AI VIDEO EDITOR USER DATA"/);
assert.match(migration, /full_wipe_credential_targets/);
assert.match(migration, /delete_known_credentials_for_full_wipe\(options\.dry_run\)/);
assert.match(credentials, /KNOWN_PROVIDER_IDS: &\[&str\]/);
assert.match(credentials, /known_credential_targets/);
assert.match(credentials, /never enumerates the user's credential vault/i);
assert.match(credentials, /GetLastError/);
assert.match(uninstallSchema.properties.fullWipeCredentialTargets.items.pattern, /^\^AI Video Editor Desktop V2\/provider/);
assert.equal(releaseSchema.properties.product.properties.version.const, "2.0.0-rc.6");
assert.equal(releaseSchema.properties.authenticode.properties.status.const, "not-claimed");

assert.match(build, /test-fixture-2026/);
assert.match(build, /developer-test/);
assert.match(build, /AIVE_RELEASE_PUBLIC_KEY_B64/);
assert.doesNotMatch(build, /AIVE_[A-Z_]*(?:SEED|PRIVATE_KEY)/, "build-time trust override must accept public metadata only");
assert.match(trust, /release_trust_build\.rs/);
assert.match(trust, /RELEASE_TRUST_PROFILE/);

assert.equal(ffmpegProvenance.ffmpegVersion, "8.1.1");
assert.equal(ffmpegProvenance.sourceArchiveSha256, "49b28c5f16addd40239a66949973458769b7056fb7752c30ac0d53389d09a552");
assert.match(ffmpeg, /PINNED_FFMPEG_VERSION = "8\.1\.1"/);
assert.match(ffmpeg, /PINNED_SOURCE_ARCHIVE_SHA256/);
assert.match(ffmpeg, /source-metadata/);
assert.match(ffmpeg, /GPL-3\.0-only/);
assert.match(ffmpeg, /if args\.test_fixture or args\.test_signature:[\s\S]*?if args\.artifact_url:/);
assert.match(nativePackager, /if args\.test_fixture or args\.test_signature:[\s\S]*?if args\.artifact_url:/);
assert.match(catalog, /--test-fixture/);
assert.match(catalog, /test-fixture-2026/);
assert.match(catalog, /aive-desktop-v2-rc6-developer-test/);
assert.match(catalog, /cannot be combined with a release seed/i);
assert.match(await read("scripts/desktop-v2/package_component.py"), /publicKeySha256/);

for (const source of [assembler, provenance]) {
  assert.match(source, /2\.0\.0-rc\.6/);
  assert.match(source, /refus|reject/i);
  assert.match(source, /rc4/i);
  assert.match(source, /rc5/i);
}
assert.match(assembler, /AI-Video-Editor-Desktop-V2-RC6-Handoff-/);
assert.match(assembler, /developer\/test/i);
assert.match(assembler, /22094d0fd9318ff224ea22abeec545b5c5d653fd8be5b480790de2d7743bb404/);
assert.match(assembler, /deterministic_zip/);
assert.match(assembler, /verify-handoff-signatures\.py/);
assert.match(provenance, /release-manifest\.json/);
assert.match(provenance, /LICENSES-AND-SOURCES\.md/);
assert.match(provenance, /sbom\.cdx\.json/);
assert.match(provenance, /SHA256SUMS\.txt/);
assert.match(provenance, /productionSeedStatus.*not-asserted/s);
assert.match(verifier, /authenticode\.status -ne 'not-claimed'/);
assert.match(verifier, /FFmpeg 8\.1\.1/);
assert.match(docs, /No production signing seed was found/);
assert.match(docs, /not-claimed/);
for (const handoffName of ["LECTURER-SETUP.md", "INSTALL.md", "CONFIGURATION.md", "USE.md", "TROUBLESHOOTING.md", "UNINSTALL.md"]) {
  assert.match(assembler, new RegExp(handoffName.replace(".", "\\.")));
}
assert.match(assembler, /zipSha256/);
assert.match(assembler, /\.zip\.sha256/);
assert.match(assembler, /Run-DesktopV2Smoke\.ps1/);
assert.match(assembler, /rc6-native-product-e2e\.py/);
assert.match(assembler, /target \/ "SMOKE" \/ name/);
for (const guide of [lecturerSetup, lecturerInstall]) {
  assert.match(guide, /DEVELOPER\/TEST|developer\/test/i);
  assert.match(guide, /not Authenticode-signed|Authenticode is not claimed/i);
}
assert.match(lecturerSetup, /Verify-RC6Release\.ps1/);
assert.match(lecturerSetup, /not evidence of a clean-PC install/i);
assert.match(lecturerInstall, /Use the bundled catalog|bundled catalog/i);
assert.match(lecturerUse, /Create Project/);
assert.match(lecturerUse, /Import video/);
assert.match(lecturerUse, /playable video/i);
assert.match(lecturerTroubleshooting, /stdout is diagnostic only/i);
assert.match(lecturerTroubleshooting, /never promote a `\.part` file/i);
assert.match(lecturerUninstall, /REMOVE ALL AI VIDEO EDITOR USER DATA/);
assert.match(lecturerUninstall, /normal uninstall is intentionally data-preserving/i);
assert.match(smoke, /actual-component-archives-extracted-to-disposable-temp/);
assert.match(smoke, /cleanPcInstall = 'not-tested'/);
for (const requiredFlow of ["/api/v1/projects", "imports/native/primary", "/api/v1/jobs", "engine-control/shutdown"]) {
  assert.match(productE2E, new RegExp(requiredFlow.replaceAll("/", "\\/")));
}

console.log("Desktop V2 RC6 release/installer tests passed: coherent developer trust, lecturer guides, actual-artifact product smoke, bounded uninstall/full wipe, pinned FFmpeg provenance, and non-overwriting release assembly are frozen.");
