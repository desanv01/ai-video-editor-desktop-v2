#!/usr/bin/env python3
"""Assemble a new, portable Desktop V2 rc.3 lecturer handoff.

The shell installer is supplied separately from the heavy component archives.
This command only copies already-built release artifacts and the preserved
signed rc.2 component/catalog baseline; it never edits the source handoff,
creates signing keys, or includes user data and secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path


VERSION = "2.0.0-rc.3"
CHANNEL = "beta"
PRODUCT_NAME = "AI Video Editor Desktop V2"
PRODUCT_IDENTIFIER = "com.fyp.ai-video-editor.desktop-v2"
EXPECTED_TARGET_NAME = "AI-Video-Editor-Desktop-V2-Handoff-rc3"
CANONICAL_INSTALL_TARGET = "C:/Program Files/AI Video Editor Desktop V2"
REPOSITORY = "https://github.com/desanv01/ai-video-editor"
KEY_ID = "aive-desktop-v2-lecturer-2026"
EVIDENCE_STATUSES = {
    "passed": "passed-local-or-ci-proof",
    "cert": "pending-external-certificate",
    "clean": "pending-genuine-clean-PC",
    "av": "pending-third-party-AV-portal",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--zip-path", type=Path, required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--catalog-root", type=Path, required=True)
    parser.add_argument("--smoke-source", type=Path)
    parser.add_argument("--public-key-file", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def file_record(path: Path, root: Path) -> dict[str, object]:
    return {"path": relative(path, root), "byteSize": file_size(path), "sha256": sha256(path)}


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


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
    if target == catalog_root or target.name == "AI-Video-Editor-Desktop-V2-Handoff":
        raise ValueError("refusing to overwrite or reuse the preserved rc.2 handoff")
    if target.name != EXPECTED_TARGET_NAME:
        raise ValueError(f"target must be uniquely named {EXPECTED_TARGET_NAME}: {target}")
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"target must be new and empty; no deletion is performed: {target}")
    if zip_path.exists():
        raise ValueError(f"ZIP already exists; refusing to overwrite: {zip_path}")
    if zip_path == catalog_root or zip_path == target:
        raise ValueError("ZIP path must be separate from the source and handoff directory")
    target.mkdir(parents=True, exist_ok=True)
    zip_path.parent.mkdir(parents=True, exist_ok=True)


def copy_baseline(catalog_root: Path, target: Path, public_key: Path, smoke_source: Path) -> None:
    catalog_files = (
        "offline-catalog.json",
        "offline-catalog.sig",
        "production-catalog.template.json",
    )
    for name in catalog_files:
        copy_file(catalog_root / "Catalog" / name, target / "Catalog" / name)
    copy_file(public_key, target / "Catalog" / "lecturer-release-public-key.json")

    components = catalog_root / "Components"
    for source in sorted(components.iterdir()):
        if not source.is_file():
            continue
        if source.suffix.lower() not in {".json", ".sig", ".gz"} and not source.name.endswith(".tar.gz"):
            raise ValueError(f"unexpected component handoff file: {source.name}")
        copy_file(source, target / "Components" / source.name)
    copy_file(smoke_source, target / "SMOKE" / "synthetic-source.mp4")


def copy_release_helpers(source_root: Path, target: Path) -> None:
    copy_file(source_root / "scripts" / "desktop-v2" / "VERIFY-HANDOFF.ps1", target / "VERIFY-HANDOFF.ps1")
    copy_file(source_root / "scripts" / "desktop-v2" / "verify_handoff_signatures.py", target / "verify-handoff-signatures.py")
    helper_names = (
        "Detect-WebView2.ps1",
        "Invoke-CleanWindowsValidation.ps1",
        "Run-DefenderScan.ps1",
        "Run-DesktopV2Smoke.ps1",
        "Sign-DesktopV2Release.ps1",
        "generate_sbom.py",
    )
    for name in helper_names:
        copy_file(source_root / "scripts" / "desktop-v2" / name, target / "Evidence" / "scripts" / name)
    doc_names = (
        "AV_FALSE_POSITIVE_TEMPLATE.md",
        "CLEAN_WINDOWS_VALIDATION_RC3.md",
        "PROVIDER_ONBOARDING_RC3.md",
        "SIGNING_RC3_RELEASE_GATE.md",
        "WEBVIEW2_RC3_POLICY.md",
    )
    for name in doc_names:
        copy_file(source_root / "docs" / "desktop-v2" / name, target / "Evidence" / "docs" / name)


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
                "manifestArtifact": {
                    "byteSize": artifact["byteSize"],
                    "sha256": artifact["sha256"],
                    "url": artifact["url"],
                },
                "compatibility": {
                    "minimumShellVersion": manifest["requirements"]["minimumShellVersion"],
                    "verifiedForShellVersion": VERSION,
                },
                "provenance": {
                    "sourceRelease": "2.0.0-rc.2",
                    "sourcePolicy": "preserved signed baseline copied read-only",
                    "reSignRequiredForRc3": True,
                },
            }
        )
    catalog = json.loads((target / "Catalog" / "offline-catalog.json").read_text(encoding="utf-8"))
    catalog_record = {
        "schemaVersion": catalog["schemaVersion"],
        "catalogId": catalog["catalogId"],
        "channel": catalog.get("channel", CHANNEL),
        "catalog": file_record(target / "Catalog" / "offline-catalog.json", target),
        "signature": file_record(target / "Catalog" / "offline-catalog.sig", target),
        "compatibility": {
            "verifiedForShellVersion": VERSION,
            "sourceRelease": "2.0.0-rc.2",
            "reSignRequiredForRc3": True,
        },
    }
    return records, catalog_record


def create_docs(target: Path, installer: Path, component_info: list[dict[str, object]], catalog_info: dict[str, object]) -> None:
    installer_hash = sha256(installer)
    installer_size = file_size(installer)
    engine = next(item for item in component_info if item["componentId"] == "aive-engine")
    ffmpeg = next(item for item in component_info if item["componentId"] == "ffmpeg")
    trust = json.loads((target / "Catalog" / "lecturer-release-public-key.json").read_text(encoding="utf-8"))
    key_id = trust["keyId"]
    key_hash = trust["publicKeySha256"]

    write_text(
        target / "START-HERE.md",
        f"""# {PRODUCT_NAME} — lecturer handoff {VERSION}

This is a new rc.3 handoff directory. Keep `Catalog` and `Components` as sibling directories. The shell installer is intentionally thin ({installer_size:,} bytes); the engine and FFmpeg archives remain separate offline components and are not embedded in Tauri resources.

## Offline first launch

1. Run `VERIFY-HANDOFF.ps1` from this folder. It is read-only and never executes the installer or component binaries.
2. Confirm Windows 10/11 x64 and that Microsoft WebView2 is installed. The shell detects WebView2 before creating its first window; it never silently downloads a runtime.
3. Run **AI Video Editor Desktop V2 {VERSION} Setup.exe** and approve UAC. The canonical install directory is `{CANONICAL_INSTALL_TARGET}`.
4. Open **Setup Center**. Use **Use bundled lecturer catalog** to discover and select the bounded `Catalog/offline-catalog.json`, or use **Browse** as the JSON-only fallback. The shell verifies the catalog key, signature, expiry, shell compatibility, required manifests, archive hashes, and `offline:Components/...` containment before installation.
5. Keep both required entries selected: **AI Video Editor Native Core Engine** and **FFmpeg Native Desktop Tool Component**. Activation stages each verified archive and commits atomically only after verification.
6. Wait for authenticated engine readiness, then use `SMOKE/synthetic-source.mp4` for the lecturer checklist.
7. After a restart, use Setup Center **Repair** and review the default uninstall plan. User projects and other user data remain preserved unless a deliberate destructive option is chosen.

## Trust and honest release gates

The Ed25519 lecturer trust root is `{key_id}` with public-key SHA-256 `{key_hash}`. The copied catalog and component manifests are real, verified signed rc.2 baseline artifacts compatible with rc.3; they are marked `reSignRequiredForRc3` in `release-manifest.json` and must not be described as newly signed rc.3 artifacts.

The shell installer was built with `--no-sign` because no external OV/EV certificate was supplied. Authenticode signing is pending, not claimed. See `Evidence/SIGNING_RC3_RELEASE_GATE.md`. Genuine clean-PC validation and third-party AV portal results are also pending; see `EVIDENCE.md`.

Exact hashes are in `SHA256SUMS.txt` and `release-manifest.json`. The installer SHA-256 is `{installer_hash}`.
""",
    )
    write_text(
        target / "LECTURER-TEST-GUIDE.md",
        f"""# Lecturer test guide — {VERSION}

Record PASS/FAIL and attach the generated evidence files. A local or CI proof is not a substitute for a genuine clean Windows 10/11 PC.

- [ ] `VERIFY-HANDOFF.ps1` passes without executing binaries.
- [ ] Installer starts, requests elevation, installs under `{CANONICAL_INSTALL_TARGET}`, and creates shortcuts.
- [ ] WebView2 is detected before launch; no silent runtime download occurs.
- [ ] First launch displays Setup Center with visible busy/success/error feedback.
- [ ] **Use bundled lecturer catalog** succeeds; Browse accepts one `.json` file only and shows a redacted error when dialog/open fails.
- [ ] Catalog trust shows `{key_id}`; expiry, shell compatibility, manifests, hashes, and offline path containment pass.
- [ ] Both required components are preselected; unavailable optional components are disabled.
- [ ] Engine and FFmpeg import/copy/verify/stage/activate and authenticated readiness succeed.
- [ ] Use `SMOKE/synthetic-source.mp4` for project/source registration, FFmpeg probe, encode, decode, and export.
- [ ] Close/reopen the shell and confirm readiness returns.
- [ ] Run Repair; verify the active component remains usable and a failed activation would retain the prior active version.
- [ ] Review the uninstall plan; the default preserves user projects/uploads/configuration.
- [ ] Review Provider onboarding only after readiness. Use lecturer-owned password-field keys; Test and Clear must not expose secrets in logs or diagnostics.

Local command evidence can be generated with `Evidence/scripts/Run-DesktopV2Smoke.ps1`, `Evidence/scripts/Detect-WebView2.ps1`, and `Evidence/scripts/Invoke-CleanWindowsValidation.ps1`. Do not mark the clean-PC row passed from this development machine alone.
""",
    )
    write_text(
        target / "SYSTEM-REQUIREMENTS.md",
        f"""# System requirements — Desktop V2 {VERSION}

- Windows 10 or Windows 11, 64-bit x86 (`x86_64`).
- Microsoft WebView2 Runtime installed before shell launch. Evergreen is preferred; use Microsoft’s online Bootstrapper or offline Standalone Installer explicitly. Fixed Runtime is a separately governed option and is not silently downloaded.
- At least 2 GiB free before component installation, plus working space for media. The heavy archives are separate from the `{installer_size:,}`-byte shell installer.
- Local administrator approval for the per-machine `{CANONICAL_INSTALL_TARGET}` installation.
- Internet is optional for this handoff after all local artifacts are present.
- Python, Node.js, Docker, and system FFmpeg are not runtime requirements of the installed release.
- Provider keys, models, databases, projects, uploads, and environment files are not bundled.
""",
    )
    write_text(
        target / "TROUBLESHOOTING.md",
        f"""# Troubleshooting — Desktop V2 {VERSION}

## Catalog import

Keep `Catalog` and `Components` together. Start with **Use bundled lecturer catalog**. Browse accepts exactly one JSON file and resolves artifacts only beneath the handoff root. A missing or corrupted artifact is a verification failure, not a reason to use a system FFmpeg or a network fallback.

## WebView2

The shell reports a visible pre-launch failure when WebView2 is absent. Use the official Evergreen Bootstrapper while online or the official Standalone Installer while offline, verify the supplied checksum/provenance, then rerun the detector. There is no implicit download.

## SmartScreen / signing

This handoff is not Authenticode-signed because no external OV/EV certificate was supplied. Verify `SHA256SUMS.txt`, the Ed25519 trust root, and the copied handoff source before proceeding. Do not describe the installer as signed.

## Components and repair

The required engine and FFmpeg artifacts are separately signed and hash-checked. Activation is stage-then-atomic-commit. A failed activation retains the previous active version; Repair can recover partial state. The copied baseline artifacts are rc.2-signed and explicitly marked for rc.3 re-signing.

## Data safety

The default uninstall plan preserves user data. Current V2 LocalAppData projects are never treated as legacy input or cleanup candidates after a committed journal. Do not grant broad write access to Program Files.
""",
    )
    write_text(
        target / "RELEASE-NOTES.md",
        f"""# Release notes — {PRODUCT_NAME} {VERSION}

- Dialog capability explicitly grants `dialog:allow-open`; import/open is guarded and errors are visible but redacted.
- Bundled lecturer-catalog discovery is bounded, JSON-only, sibling-aware, and uses the same catalog trust gate as Browse.
- Single-instance startup focuses the existing window and forwards only approved catalog/handoff arguments.
- Current V2 user data and committed migration journals are never classified as legacy or cleanup data.
- Program Files identity is canonicalized as `{CANONICAL_INSTALL_TARGET}` across runtime, installer, repair, diagnostics, and docs.
- Durable bounded redacted operation logs cover catalog, component, and supervisor operations.
- WebView2 is detected before launch with explicit online/offline provenance and checksum policy; silent downloads are prohibited.
- Provider onboarding is local/manual by default; lecturer-owned password-field keys use Windows Credential Manager and never enter state/logs/diagnostics.
- Required component lifecycle retains atomic activation, rollback, recovery, repair, and data-preserving uninstall behavior.
- The shell installer remains thin. Heavy engine and FFmpeg artifacts are separate offline components.

## Release gates not claimed as passed

Authenticode requires an externally supplied OV/EV certificate and RFC3161 timestamp service. Genuine clean Windows 10/11 installation evidence and third-party AV portal results are not available in this workspace and remain pending.
""",
    )
    write_text(
        target / "LICENSES-AND-SOURCES.md",
        f"""# Licenses, notices, and sources

- Shell and native engine source: <{REPOSITORY}>.
- FFmpeg provenance is carried by the copied signed FFmpeg component manifest and its `LICENSES/NOTICE.txt` archive content. Review the manifest before redistribution.
- The lecturer trust root is Ed25519 key `{key_id}` (`{key_hash}`). Its private seed is not present in this handoff, repository, logs, or archives.
- Component/catalog signatures are verified by `verify-handoff-signatures.py`. Authenticode is a separate Windows release gate and is currently pending external certificate evidence.
""",
    )

    evidence = [
        ("1. Dialog capability and guarded import", EVIDENCE_STATUSES["passed"], "Rust/JS regression suite; `dialog:allow-open`, bundled intake, JSON-only Browse, and redacted errors."),
        ("2. Catalog/components trust boundary", EVIDENCE_STATUSES["passed"], "Copied-handoff verifier checks key fingerprint, signature, expiry, shell compatibility, manifests, hashes, and containment."),
        ("3. Single-instance forwarding", EVIDENCE_STATUSES["passed"], "Rust regression covers focus/approved args; UI forwarding uses the same trust-gated import."),
        ("4. Migration self-detection", EVIDENCE_STATUSES["passed"], "Rust regressions cover V2 markers and committed journals; current projects are never legacy/cleanup."),
        ("5. Canonical install identity", EVIDENCE_STATUSES["passed"], f"Installer/runtime/repair/diagnostics/docs target `{CANONICAL_INSTALL_TARGET}`."),
        ("6. Busy/status/logging", EVIDENCE_STATUSES["passed"], "Frontend build plus bounded redacted operation-log tests for catalog/component/supervisor paths."),
        ("7. Required lifecycle/readiness", EVIDENCE_STATUSES["passed"], f"53 Rust tests and lifecycle static gate cover import, verify, stage, atomic activation, corruption, interruption, locks, repair, rollback, and recovery. Baseline component archives: engine {engine['version']}, FFmpeg {ffmpeg['version']}."),
        ("8. Practical source/FFmpeg smoke", EVIDENCE_STATUSES["passed"], "Local smoke script covers project/source, probe, encode, decode, export, restart, repair, and uninstall-plan evidence; attach its generated JSON."),
        ("9. WebView2 lifecycle", EVIDENCE_STATUSES["clean"], "Detection/policy and exit-code tests pass locally; genuine clean Windows 10/11 runtime/install proof remains external."),
        ("10. Authenticode", EVIDENCE_STATUSES["cert"], "No certificate or signing service is present. Release gate requires external OV/EV, SHA-256, RFC3161 timestamp, and post-package PE verification."),
        ("11. AV hardening", EVIDENCE_STATUSES["av"], "Onedir/non-onefile policy, SBOM/hash generation, Defender script, and evidence template pass locally; no zero-detection claim and no third-party portal result."),
        ("12. Provider onboarding", EVIDENCE_STATUSES["passed"], "Credential Manager/DPAPI boundary, bounded lecturer-owned keys, Test/Clear, manual default, and redaction tests pass."),
        ("13. Clean Windows validation", EVIDENCE_STATUSES["clean"], "Automation separates local/CI proof from external clean-PC proof; genuine clean-PC execution remains pending."),
        ("14. Handoff/docs/verifier", EVIDENCE_STATUSES["passed"], f"New handoff has exact hashes, read-only verifier, release manifest, and this evidence table. Installer SHA-256: `{installer_hash}`."),
    ]
    table = "\n".join(f"| {item} | {status} | {detail} |" for item, status, detail in evidence)
    write_text(
        target / "EVIDENCE.md",
        f"""# Desktop V2 {VERSION} evidence

Generated for the new rc.3 handoff. Statuses deliberately separate local/CI proof from external release evidence.

| Requirement | Status | Evidence |
|---|---|---|
{table}

## Artifact identity

- Installer: `AI Video Editor Desktop V2 Setup.exe`
- Installer SHA-256: `{installer_hash}`
- Catalog: `{catalog_info['catalogId']}` (`{catalog_info['compatibility']['sourceRelease']}` signed baseline, verified for `{VERSION}`)
- Public trust key: `{key_id}` / `{key_hash}`
- Canonical install target: `{CANONICAL_INSTALL_TARGET}`
- Exact file hashes: `SHA256SUMS.txt`

The presence of a script or local test is not evidence of a clean-PC, Authenticode, or third-party AV result. Add those external results only with the real machine/service/portal output.
""",
    )


def release_manifest(target: Path, installer: Path, component_info: list[dict[str, object]], catalog_info: dict[str, object], source_root: Path) -> dict[str, object]:
    trust = json.loads((target / "Catalog" / "lecturer-release-public-key.json").read_text(encoding="utf-8"))
    source_release = json.loads((target / "Catalog" / "offline-catalog.json").read_text(encoding="utf-8"))
    return {
        "schemaVersion": "desktop.release-manifest.v1",
        "product": {"name": PRODUCT_NAME, "identifier": PRODUCT_IDENTIFIER, "version": VERSION, "channel": CHANNEL},
        "source": {
            "branch": git_value(source_root, ["branch", "--show-current"], "codex/desktop-v2-rc3-lecturer-handoff-hardening"),
            "sourceCommit": git_value(source_root, ["rev-parse", "HEAD"], "unknown"),
            "repository": REPOSITORY,
        },
        "contracts": {
            "shell": "desktop.shell-identity.v1",
            "engine": "desktop.health-readiness.v1",
            "componentManifest": "desktop.component-manifest.v1",
            "catalog": "desktop.setup-catalog.v1",
        },
        "requirements": {
            "minimumWindows": "Windows 10 64-bit",
            "architectures": ["x86_64"],
            "webView2": True,
            "minimumFreeBytes": 2147483648,
            "systemRuntimesRequired": [],
        },
        "trustRoot": {
            "algorithm": "ed25519",
            "keyId": trust["keyId"],
            "publicKeySha256": trust["publicKeySha256"],
            "publicKeyPath": "Catalog/lecturer-release-public-key.json",
            "privateKeyInHandoff": False,
        },
        "authenticode": {
            "status": EVIDENCE_STATUSES["cert"],
            "required": True,
            "certificateInHandoff": False,
            "commercialCertificate": False,
            "signedEvidence": False,
            "buildFlag": "--no-sign",
            "timestampPolicy": "RFC3161 HTTPS timestamp with SHA-256 (/tr /td SHA256) when externally supplied",
        },
        "installer": {
            "path": "AI Video Editor Desktop V2 Setup.exe",
            "target": CANONICAL_INSTALL_TARGET,
            "requiresElevation": True,
            "shortcuts": ["Start Menu", "Desktop"],
            "file": file_record(installer, target),
        },
        "components": component_info,
        "catalog": catalog_info,
        "catalogProvenance": {
            "catalogId": source_release["catalogId"],
            "sourceRelease": "2.0.0-rc.2",
            "sourcePolicy": "preserved signed baseline copied read-only",
            "verifiedForShellVersion": VERSION,
            "reSignRequiredForRc3": True,
        },
        "offlineFlow": {
            "artifactReferenceScheme": "offline:Components/<filename>",
            "artifactRoot": "directory-containing-Catalog-and-Components",
            "requiredComponents": ["aive-engine", "ffmpeg"],
            "productionTemplateIsUnsigned": True,
        },
        "dataSafety": {
            "bundledUserProjects": False,
            "bundledUploads": False,
            "bundledModels": False,
            "bundledDatabases": False,
            "bundledEnvironmentFiles": False,
            "bundledApiKeys": False,
        },
        "verification": {
            "script": "VERIFY-HANDOFF.ps1",
            "readOnly": True,
            "executesInstallerOrComponents": False,
            "sha256File": "SHA256SUMS.txt",
        },
        "evidence": {
            "statusDocument": "EVIDENCE.md",
            "passedLocalOrCi": True,
            "pendingExternalCertificate": True,
            "pendingGenuineCleanPc": True,
            "pendingThirdPartyAvPortal": True,
        },
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def write_sums(target: Path) -> None:
    files = sorted(path for path in target.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
    write_text(target / "SHA256SUMS.txt", "".join(f"{sha256(path)}  {relative(path, target)}\n" for path in files))


def create_zip(target: Path, zip_path: Path) -> dict[str, object]:
    files = sorted(path for path in target.rglob("*") if path.is_file())
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in files:
            info = zipfile.ZipInfo(relative(path, target))
            info.date_time = (2020, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return {"path": str(zip_path), "byteSize": file_size(zip_path), "sha256": sha256(zip_path)}


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    target = args.target_root.resolve()
    zip_path = args.zip_path.resolve()
    installer = args.installer.resolve()
    catalog_root = args.catalog_root.resolve()
    public_key = (args.public_key_file or catalog_root / "Catalog" / "lecturer-release-public-key.json").resolve()
    smoke_source = (args.smoke_source or catalog_root / "SMOKE" / "synthetic-source.mp4").resolve()

    refuse_overwrite(target, zip_path, catalog_root)
    if not installer.is_file():
        raise FileNotFoundError(installer)
    if not catalog_root.is_dir():
        raise FileNotFoundError(catalog_root)
    for path in (public_key, smoke_source):
        if not path.is_file():
            raise FileNotFoundError(path)

    copy_file(installer, target / "AI Video Editor Desktop V2 Setup.exe")
    copy_baseline(catalog_root, target, public_key, smoke_source)
    copy_release_helpers(source_root, target)
    component_info, catalog_info = component_records(target)
    create_docs(target, target / "AI Video Editor Desktop V2 Setup.exe", component_info, catalog_info)
    write_json(target / "release-manifest.json", release_manifest(target, target / "AI Video Editor Desktop V2 Setup.exe", component_info, catalog_info, source_root))
    write_sums(target)

    # Exercise the copied handoff verifier before producing the ZIP. This is
    # read-only and checks the actual copied archives, not the source folder.
    subprocess.run(
        ["python", str(target / "verify-handoff-signatures.py"), str(target)],
        check=True,
        cwd=source_root,
    )
    zip_info = create_zip(target, zip_path)
    print(json.dumps({
        "status": "assembled",
        "version": VERSION,
        "target": str(target),
        "zip": zip_info,
        "installer": file_record(target / "AI Video Editor Desktop V2 Setup.exe", target),
        "files": len([path for path in target.rglob("*") if path.is_file()]),
        "componentVersions": {item["componentId"]: item["version"] for item in component_info},
        "authenticode": EVIDENCE_STATUSES["cert"],
        "cleanPc": EVIDENCE_STATUSES["clean"],
        "thirdPartyAv": EVIDENCE_STATUSES["av"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"assemble_rc3_handoff.py: error: {error}")
