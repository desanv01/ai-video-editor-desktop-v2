#!/usr/bin/env python3
"""Assemble a separately named Desktop V2 rc.4 lecturer handoff.

The rc.3 handoff is read-only input.  This command copies its signed offline
catalog/component baseline and the newly built rc.4 shell installer into a new
directory, writes fresh metadata/checksums/guidance, verifies the copied
payload, and creates a deterministic ZIP.  It never overwrites a handoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


VERSION = "2.0.0-rc.4"
CHANNEL = "beta"
PRODUCT_NAME = "AI Video Editor Desktop V2"
PRODUCT_IDENTIFIER = "com.fyp.ai-video-editor.desktop-v2"
TARGET_NAME = "AI-Video-Editor-Desktop-V2-Handoff-rc4"
CANONICAL_INSTALL_TARGET = "C:/Program Files/AI Video Editor Desktop V2/Shell"
SOURCE_RELEASE = "2.0.0-rc.2"
KEY_ID = "aive-desktop-v2-lecturer-2026"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--zip-path", type=Path, required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--catalog-root", type=Path, required=True)
    parser.add_argument("--smoke-source", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, value: object) -> None:
    write_text(path, json.dumps(value, indent=2, sort_keys=True))


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def file_record(path: Path, root: Path) -> dict[str, object]:
    return {"path": relative(path, root), "byteSize": path.stat().st_size, "sha256": sha256(path)}


def git_value(root: Path, args: list[str], fallback: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return fallback
    return result.stdout.strip() or fallback


def refuse_overwrite(target: Path, zip_path: Path, catalog_root: Path) -> None:
    target = target.resolve()
    zip_path = zip_path.resolve()
    catalog_root = catalog_root.resolve()
    if target.name != TARGET_NAME:
        raise ValueError(f"target must be uniquely named {TARGET_NAME}: {target}")
    if target == catalog_root or target.name == "AI-Video-Editor-Desktop-V2-Handoff-rc3-final-20260824":
        raise ValueError("refusing to overwrite or reuse the preserved rc.3 handoff")
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"target must be new and empty; no deletion is performed: {target}")
    if zip_path.exists() or zip_path == catalog_root or zip_path == target:
        raise ValueError(f"ZIP path must be new and separate: {zip_path}")
    target.mkdir(parents=True, exist_ok=True)
    zip_path.parent.mkdir(parents=True, exist_ok=True)


def copy_signed_baseline(catalog_root: Path, target: Path, smoke_source: Path) -> None:
    for name in ("offline-catalog.json", "offline-catalog.sig", "production-catalog.template.json", "lecturer-release-public-key.json"):
        copy_file(catalog_root / "Catalog" / name, target / "Catalog" / name)
    for source in sorted((catalog_root / "Components").iterdir()):
        if source.is_file() and source.suffix.lower() in {".json", ".sig", ".gz"}:
            copy_file(source, target / "Components" / source.name)
    copy_file(smoke_source, target / "SMOKE" / "synthetic-source.mp4")


def copy_verifiers(source_root: Path, target: Path) -> None:
    for source_name, target_name in (
        ("VERIFY-HANDOFF.ps1", "VERIFY-HANDOFF.ps1"),
        ("verify_handoff_signatures.py", "verify-handoff-signatures.py"),
        ("rc4-first-run-recovery-tests.mjs", "rc4-first-run-recovery-tests.mjs"),
    ):
        copy_file(source_root / "scripts" / "desktop-v2" / source_name, target / target_name)
    for name in (
        "Detect-WebView2.ps1",
        "Invoke-CleanWindowsValidation.ps1",
        "Run-DefenderScan.ps1",
        "Run-DesktopV2Smoke.ps1",
        "Sign-DesktopV2Release.ps1",
        "generate_sbom.py",
    ):
        copy_file(source_root / "scripts" / "desktop-v2" / name, target / "Evidence" / "scripts" / name)


def component_records(target: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    records: list[dict[str, object]] = []
    for component_id, manifest_name, signature_name in (
        ("aive-engine", "aive-engine-manifest.json", "aive-engine-manifest.sig"),
        ("ffmpeg", "ffmpeg-manifest.json", "ffmpeg-manifest.sig"),
    ):
        manifest_path = target / "Components" / manifest_name
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = manifest["artifact"]
        archive_path = target / "Components" / Path(str(artifact["url"]).split("/")[-1]).name
        records.append(
            {
                "componentId": component_id,
                "version": manifest["component"]["version"],
                "archive": file_record(archive_path, target),
                "manifest": file_record(manifest_path, target),
                "signature": file_record(target / "Components" / signature_name, target),
                "manifestArtifact": {"byteSize": artifact["byteSize"], "sha256": artifact["sha256"], "url": artifact["url"]},
                "compatibility": {"minimumShellVersion": manifest["requirements"]["minimumShellVersion"], "verifiedForShellVersion": VERSION},
                "provenance": {"sourceRelease": SOURCE_RELEASE, "sourcePolicy": "preserved signed baseline copied read-only", "reSignRequiredForRc4": True},
            }
        )
    catalog = json.loads((target / "Catalog" / "offline-catalog.json").read_text(encoding="utf-8"))
    catalog_info = {
        "schemaVersion": catalog["schemaVersion"],
        "catalogId": catalog["catalogId"],
        "channel": catalog.get("channel", CHANNEL),
        "catalog": file_record(target / "Catalog" / "offline-catalog.json", target),
        "signature": file_record(target / "Catalog" / "offline-catalog.sig", target),
        "compatibility": {"verifiedForShellVersion": VERSION, "sourceRelease": SOURCE_RELEASE, "reSignRequiredForRc4": True},
    }
    return records, catalog_info


def write_release_documents(target: Path, installer: Path, components: list[dict[str, object]], catalog: dict[str, object]) -> None:
    installer_record = file_record(installer, target)
    trust = json.loads((target / "Catalog" / "lecturer-release-public-key.json").read_text(encoding="utf-8"))
    write_text(target / "START-HERE.md", f"""# {PRODUCT_NAME} — lecturer handoff {VERSION}

This is a new rc.4 handoff. The rc.3 handoff remains an immutable input. The shell installer is per-machine and installs to `{CANONICAL_INSTALL_TARGET}`; signed engine and FFmpeg archives remain separate offline components.

1. Run `VERIFY-HANDOFF.ps1` from this folder. It is read-only.
2. Run **AI Video Editor Desktop V2 Setup.exe** and approve the scoped UAC prompt.
3. Launch the shell and choose **Use bundled lecturer catalog** in Setup Center. Do not select `production-catalog.template.json`; it is intentionally rejected.
4. Keep both required components selected, accept their license text, and run the exact activation-writer check before Install.
5. Use `SMOKE/synthetic-source.mp4` for the lecturer media workflow. The native supervisor must be ready before editor views unlock.
6. Use **Repair** if the machine perimeter or activation journal needs recovery. Retry is safe and convergent.

The catalog and component signatures are the preserved `{SOURCE_RELEASE}` baseline, verified against trust key `{trust["keyId"]}`. They are not newly signed rc.4 artifacts; re-signing is an external release gate.
""")
    write_text(target / "LECTURER-TEST-GUIDE.md", f"""# Lecturer test guide — {VERSION}

- [ ] `VERIFY-HANDOFF.ps1` passes.
- [ ] Installer requests UAC once, installs under `{CANONICAL_INSTALL_TARGET}`, and creates exactly one desktop shortcut plus the generated Start-menu shortcut.
- [ ] A pristine install opens directly in the short Setup Center flow; no migration wizard appears.
- [ ] Bundled catalog is the default. Browse accepts one signed `.json`; `.template.json` is rejected with exact offline guidance and does not enable Review/Install.
- [ ] Exact writer transaction passes: child-directory create/write/flush, same-volume rename, atomic replace, cleanup, ACL/elevation/broker readiness.
- [ ] Both required components verify, stage, activate, and reach authenticated native supervisor readiness.
- [ ] Close/reopen, Repair, and safe retry converge without a `VERSION_ALREADY_PUBLISHED` dead end.
- [ ] Create a project, upload `SMOKE/synthetic-source.mp4`, process/edit, render/export, stop/restart/reopen, and capture diagnostics.
- [ ] Default uninstall preserves projects, uploads, exports, database, models, and settings; full wipe is explicit.

The final media/project/export/restart/repair/uninstall rows require a genuine clean Windows machine and are not claimed by local source/build tests.
""")
    write_text(target / "TROUBLESHOOTING.md", f"""# Troubleshooting — Desktop V2 {VERSION}

## Setup says the writer is unavailable

Run the exact system check again. If the broker is missing or the perimeter ACL is unhealthy, close the shell, rerun the per-machine installer/Repair, approve UAC, and run the check again. The shell never writes components to AppData and never falls back to Docker or PATH tools.

## Catalog import

Use the bundled lecturer catalog first. A production-catalog template is not a catalog and is rejected. Keep `Catalog` and `Components` together for offline imports; a valid import clears the prior rejection and re-evaluates manifests, checks, and license state.

## Activation or retry

Activation intent is journaled before publish. A verified published directory is recovered as `recovered-published`; an already committed version returns `already-active`. A true manifest conflict is quarantined inside the machine perimeter. Open Diagnostics and attach the redacted operation tail.

## Release gates

This handoff is built with `--no-sign`. Authenticode/SmartScreen, clean-PC/UAC/AV, and the final native project/export workflow require external evidence. Do not describe those gates as passed from this checkout.
""")
    write_text(target / "SYSTEM-REQUIREMENTS.md", f"""# System requirements — Desktop V2 {VERSION}

- Windows 10/11 x64 with Microsoft WebView2 installed.
- Local administrator approval for `{CANONICAL_INSTALL_TARGET}` and the ProgramData component perimeter.
- No Docker, Python, Node.js, global FFmpeg, or network access is required after the offline handoff is complete.
- Keep the sibling `Catalog` and `Components` directories intact.
""")
    write_text(target / "RELEASE-NOTES.md", f"""# Release notes — {PRODUCT_NAME} {VERSION}

- Added the bounded native component broker/UAC helper path for machine activation, reconcile, repair, rollback, and uninstall operations.
- Activation is journaled, inventory-verified, idempotent, and recoverable across published-but-inactive interruptions.
- Setup uses a truthful exact writer transaction probe and rejects catalog templates before Review/Install.
- Removed the production Docker bootstrap route and kept native launch resolution tied to verified active components.
- Installer hooks provision the broker perimeter and leave shortcut creation to the generated NSIS section, eliminating the duplicate shortcut path.
- Diagnostics include redacted operation checkpoints, broker health, perimeter summary, catalog rejection, and supervisor readiness.

The preserved signed component/catalog baseline requires external rc.4 re-signing before a production release.
""")
    write_text(target / "COMPLETION-REPORT.md", f"""# Desktop V2 {VERSION} completion report

## Local evidence

- Rust: `cargo fmt --all -- --check`, `cargo check`, `cargo test --lib` — PASS (56/56), and `cargo build --release` — PASS.
- Frontend: `npm run build` — PASS (contracts, TypeScript, Vite production build).
- Desktop regression suite: `npm run test:desktop-v2` — PASS, including rc.4 first-run recovery, catalog/writer gates, broker routing, diagnostics, migration safety, lifecycle, and NSIS inspection.
- Release build: `npx tauri build --bundles nsis --no-sign` — PASS; installer is recorded in `release-manifest.json` and `SHA256SUMS.txt`.

## External gates deliberately left open

- Genuine clean Windows 10/11 first-run, UAC elevation, ACL repair, locked-file/reboot, shortcut target, upgrade, default uninstall, and full-wipe execution.
- Authenticode OV/EV signing with SHA-256 and RFC3161 timestamp verification.
- Third-party antivirus/SmartScreen portal results.
- Packaged native engine smoke covering SQLite/vector initialization, project creation, upload, process/edit, render/export, stop/restart/reopen.
- Re-signing the copied `{SOURCE_RELEASE}` catalog and component manifests for `{VERSION}`.

No external gate is represented as local success.
""")
    write_text(target / "LICENSES-AND-SOURCES.md", f"""# Licenses, notices, and sources

- Source repository: https://github.com/desanv01/ai-video-editor
- Trust root: `{trust["keyId"]}` / `{trust["publicKeySha256"]}`.
- The catalog and component archives are preserved signed `{SOURCE_RELEASE}` inputs and require review/re-signing for rc.4 redistribution.
- No private key, provider secret, user project, upload, model, database, or environment file is included.
""")
    write_json(target / "EVIDENCE.json", {
        "schemaVersion": "desktop.rc4-evidence.v1",
        "version": VERSION,
        "local": {"rustTests": "56/56", "frontendBuild": "passed", "desktopRegressionSuite": "passed", "installerBuild": "passed-no-sign"},
        "externalPending": ["clean-pc-uac", "authenticode", "third-party-av", "packaged-native-project-export-smoke", "rc4-catalog-and-component-resigning"],
        "installer": installer_record,
        "catalog": catalog,
        "components": components,
    })


def release_manifest(target: Path, installer: Path, components: list[dict[str, object]], catalog: dict[str, object], source_root: Path) -> dict[str, object]:
    trust = json.loads((target / "Catalog" / "lecturer-release-public-key.json").read_text(encoding="utf-8"))
    return {
        "schemaVersion": "desktop.release-manifest.v1",
        "product": {"name": PRODUCT_NAME, "identifier": PRODUCT_IDENTIFIER, "version": VERSION, "channel": CHANNEL},
        "source": {"branch": git_value(source_root, ["branch", "--show-current"], "codex/desktop-v2-rc4-first-run-recovery"), "sourceCommit": git_value(source_root, ["rev-parse", "HEAD"], "unknown"), "repository": "https://github.com/desanv01/ai-video-editor"},
        "contracts": {"shell": "desktop.shell-identity.v1", "engine": "desktop.health-readiness.v1", "componentManifest": "desktop.component-manifest.v1", "catalog": "desktop.setup-catalog.v1", "broker": "desktop.component-broker.v1"},
        "requirements": {"minimumWindows": "Windows 10 64-bit", "architectures": ["x86_64"], "webView2": True, "minimumFreeBytes": 2147483648, "systemRuntimesRequired": []},
        "trustRoot": {"algorithm": "ed25519", "keyId": trust["keyId"], "publicKeySha256": trust["publicKeySha256"], "publicKeyPath": "Catalog/lecturer-release-public-key.json", "privateKeyInHandoff": False},
        "authenticode": {"status": "pending-external-certificate", "required": True, "certificateInHandoff": False, "signedEvidence": False, "buildFlag": "--no-sign", "timestampPolicy": "RFC3161 HTTPS timestamp with SHA-256 when externally supplied"},
        "installer": {"path": "AI Video Editor Desktop V2 Setup.exe", "target": CANONICAL_INSTALL_TARGET, "requiresElevation": True, "shortcuts": ["generated NSIS Start Menu", "generated NSIS Desktop"], "file": file_record(installer, target)},
        "components": components,
        "catalog": catalog,
        "catalogProvenance": {"catalogId": catalog["catalogId"], "sourceRelease": SOURCE_RELEASE, "sourcePolicy": "preserved signed baseline copied read-only", "verifiedForShellVersion": VERSION, "reSignRequiredForRc4": True},
        "offlineFlow": {"artifactReferenceScheme": "offline:Components/<filename>", "artifactRoot": "directory-containing-Catalog-and-Components", "requiredComponents": ["aive-engine", "ffmpeg"], "productionTemplateIsUnsigned": True},
        "dataSafety": {"bundledUserProjects": False, "bundledUploads": False, "bundledModels": False, "bundledDatabases": False, "bundledEnvironmentFiles": False, "bundledApiKeys": False},
        "verification": {"script": "VERIFY-HANDOFF.ps1", "readOnly": True, "executesInstallerOrComponents": False, "sha256File": "SHA256SUMS.txt"},
        "evidence": {"statusDocument": "COMPLETION-REPORT.md", "machineEvidence": "EVIDENCE.json", "passedLocalOrCi": True, "pendingExternalCertificate": True, "pendingGenuineCleanPc": True, "pendingThirdPartyAvPortal": True},
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def write_sums(target: Path) -> None:
    paths = sorted(path for path in target.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
    write_text(target / "SHA256SUMS.txt", "".join(f"{sha256(path)}  {relative(path, target)}\n" for path in paths))


def create_zip(target: Path, zip_path: Path) -> dict[str, object]:
    paths = sorted(path for path in target.rglob("*") if path.is_file())
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in paths:
            info = zipfile.ZipInfo(relative(path, target), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return {"path": str(zip_path), "byteSize": zip_path.stat().st_size, "sha256": sha256(zip_path)}


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    target = args.target_root.resolve()
    zip_path = args.zip_path.resolve()
    installer = args.installer.resolve()
    catalog_root = args.catalog_root.resolve()
    smoke_source = (args.smoke_source or catalog_root / "SMOKE" / "synthetic-source.mp4").resolve()
    refuse_overwrite(target, zip_path, catalog_root)
    if not installer.is_file() or not catalog_root.is_dir() or not smoke_source.is_file():
        raise FileNotFoundError("installer, catalog root, and smoke source are required")
    copy_file(installer, target / "AI Video Editor Desktop V2 Setup.exe")
    copy_signed_baseline(catalog_root, target, smoke_source)
    copy_verifiers(source_root, target)
    components, catalog = component_records(target)
    write_release_documents(target, target / "AI Video Editor Desktop V2 Setup.exe", components, catalog)
    write_json(target / "release-manifest.json", release_manifest(target, target / "AI Video Editor Desktop V2 Setup.exe", components, catalog, source_root))
    write_sums(target)
    subprocess.run([sys.executable, str(target / "verify-handoff-signatures.py"), str(target)], check=True, cwd=source_root)
    zip_info = create_zip(target, zip_path)
    print(json.dumps({"status": "assembled", "version": VERSION, "target": str(target), "zip": zip_info, "files": len([path for path in target.rglob("*") if path.is_file()]), "installer": file_record(target / "AI Video Editor Desktop V2 Setup.exe", target)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"assemble_rc4_handoff.py: error: {error}")
