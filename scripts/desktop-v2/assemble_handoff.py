#!/usr/bin/env python3
"""Assemble and describe the lecturer-ready Desktop V2 Phase 9 handoff.

This script copies already-built release artifacts into one new, dedicated
handoff directory and writes only release documentation, the public trust
root, checksums, and read-only verification helpers. It never copies private
keys, user data, models, databases, environments, or dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


VERSION = "2.0.0-rc.1"
CHANNEL = "beta"
BASE_PHASE8_COMMIT = "21298c927b745707b1bc02040a51f403743d4fa4"
BRANCH = "codex/desktop-v2-phase-9"
KEY_ID = "aive-desktop-v2-lecturer-2026"
PUBLIC_KEY_SHA256 = "471e7b08109f8723400afea495f63d1d93753e4757386e31560a7cbee6bd2a2d"
EXPECTED_TARGET = Path(r"C:\Users\Dv\Desktop\AI-Video-Editor-Desktop-V2-Handoff")
HANDOFF_FILES = {
    "AI Video Editor Desktop V2 Setup.exe",
    "Components/aive-engine-2.0.0-rc.1.tar.gz",
    "Components/aive-engine-manifest.json",
    "Components/aive-engine-manifest.sig",
    "Components/ffmpeg-8.1.1.tar.gz",
    "Components/ffmpeg-manifest.json",
    "Components/ffmpeg-manifest.sig",
    "Catalog/offline-catalog.json",
    "Catalog/offline-catalog.sig",
    "Catalog/lecturer-release-public-key.json",
    "Catalog/production-catalog.template.json",
    "START-HERE.md",
    "LECTURER-TEST-GUIDE.md",
    "SYSTEM-REQUIREMENTS.md",
    "TROUBLESHOOTING.md",
    "RELEASE-NOTES.md",
    "LICENSES-AND-SOURCES.md",
    "SHA256SUMS.txt",
    "VERIFY-HANDOFF.ps1",
    "verify-handoff-signatures.py",
    "release-manifest.json",
    "SMOKE/synthetic-source.mp4",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--expected-target", type=Path, default=EXPECTED_TARGET)
    parser.add_argument("--public-key-file", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="Resume only a previously-created partial handoff at the exact target.")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def size(path: Path) -> int:
    return path.stat().st_size


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def file_record(path: Path, root: Path) -> dict[str, object]:
    return {"path": rel(path, root), "byteSize": size(path), "sha256": sha256(path)}


def git_value(source_root: Path, args: list[str], fallback: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return fallback
    return result.stdout.strip() or fallback


def manifest_artifact_record(manifest: dict[str, object], root: Path) -> dict[str, object]:
    artifact = manifest["artifact"]
    assert isinstance(artifact, dict)
    archive_name = Path(str(artifact["url"]).split("/")[-1]).name
    archive = root / "Components" / archive_name
    return {
        "archive": archive_name,
        "path": rel(archive, root),
        "byteSize": size(archive),
        "sha256": sha256(archive),
        "manifestPath": None,
        "signaturePath": None,
    }


def create_docs(root: Path, engine: dict[str, object], ffmpeg: dict[str, object], installer: Path, catalog: Path, ffmpeg_source: dict[str, object]) -> None:
    engine_artifact = engine["artifact"]
    ffmpeg_artifact = ffmpeg["artifact"]
    assert isinstance(engine_artifact, dict) and isinstance(ffmpeg_artifact, dict)
    engine_archive = root / "Components" / Path(str(engine_artifact["url"]).split("/")[-1]).name
    ffmpeg_archive = root / "Components" / Path(str(ffmpeg_artifact["url"]).split("/")[-1]).name
    engine_manifest = root / "Components" / "aive-engine-manifest.json"
    ffmpeg_manifest = root / "Components" / "ffmpeg-manifest.json"
    engine_sig = root / "Components" / "aive-engine-manifest.sig"
    ffmpeg_sig = root / "Components" / "ffmpeg-manifest.sig"
    catalog_sig = root / "Catalog" / "offline-catalog.sig"
    trust = json.loads((root / "Catalog" / "lecturer-release-public-key.json").read_text(encoding="utf-8"))

    engine_exe = next(item for item in engine["files"] if item.get("path") == "bin/aive-engine.exe")
    ffmpeg_exe = next(item for item in ffmpeg["files"] if item.get("path") == "bin/ffmpeg.exe")
    ffprobe_exe = next(item for item in ffmpeg["files"] if item.get("path") == "bin/ffprobe.exe")

    write_text(
        root / "START-HERE.md",
        f"""# AI Video Editor Desktop V2 lecturer release candidate

        This folder is the complete offline release handoff for **{VERSION}** ({CHANNEL} channel). Keep the folder together in any convenient local directory. The `Catalog` and `Components` directories must remain siblings; the handoff is intentionally portable.

        The signed component manifests use portable `offline:Components/...` references. You may copy this complete folder to another machine or temporary directory; preserve the relative `Catalog` and `Components` layout when importing.

        ## Plug-and-play flow

        1. Confirm the machine meets [SYSTEM-REQUIREMENTS.md](SYSTEM-REQUIREMENTS.md).
        2. Double-click **AI Video Editor Desktop V2 Setup.exe**. Approve UAC. This is the small per-machine shell installer; it does not contain the heavy engine or FFmpeg payloads.
        3. If Windows SmartScreen warns that the installer is from an unknown publisher, choose **More info → Run anyway** only if this handoff was obtained from the lecturer. The installer is intentionally unsigned because no Authenticode certificate was available; the release does not claim commercial code signing.
        4. Launch **AI Video Editor Desktop V2** from the Start menu or desktop shortcut.
        5. Open **Setup Center**, choose **Offline catalog / Import catalog**, and select `Catalog\\offline-catalog.json` from this folder.
        6. Confirm the catalog trust indicator names `{KEY_ID}` and that both required components are available. Select/install **AI Video Editor Native Core Engine** and **FFmpeg Native Desktop Tool Component**. The Setup Center verifies the Ed25519 signatures and SHA-256 hashes before activation.
        7. Wait for authenticated readiness. The engine is loopback-only and uses a generated bearer token; no Docker, system Python, system Node.js, or system FFmpeg is required.
        8. Use `SMOKE\\synthetic-source.mp4` as the small source asset and follow [LECTURER-TEST-GUIDE.md](LECTURER-TEST-GUIDE.md).
        9. Close and reopen the desktop app once. Then open Setup Center and exercise **Repair** for a component. A previous active version is retained for rollback by the component manager; this handoff contains one version, so rollback is a recovery-path check rather than a downgrade.
        10. If uninstalling, use the default uninstall plan. It removes the shell while preserving user data unless an explicit destructive data option is selected.

        ## Honest limitations

        Provider credentials, Docker configuration, models, user projects, uploads, databases, and API keys are not included. The local engine/SQLite/vector degraded-mode and FFmpeg practical smoke are supported offline; provider-backed AI generation requires the lecturer to configure their own provider secrets after installation.

        See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) before changing permissions or moving the folder. Run `VERIFY-HANDOFF.ps1` before distribution; it is read-only and never executes the installer or component binaries.
        """,
    )
    write_text(
        root / "LECTURER-TEST-GUIDE.md",
        f"""# Lecturer smoke checklist

        Release: **{VERSION}**, channel **{CHANNEL}**. Expected result for each checked item is **PASS**.

        - [ ] Installer starts, requests elevation, installs under `C:\\Program Files\\AI Video Editor Desktop V2`, and creates Start-menu/desktop shortcuts.
        - [ ] Setup Center opens with zero components initially installed.
        - [ ] Import `Catalog\\offline-catalog.json`; trust is `{KEY_ID}` and both required entries are available.
        - [ ] Install/activate the engine and FFmpeg. SHA-256 and Ed25519 verification completes before activation.
        - [ ] Engine reaches authenticated readiness; unauthenticated requests are rejected.
        - [ ] Create a synthetic project/source using `SMOKE\\synthetic-source.mp4`.
        - [ ] Run the practical local smoke: project/source registration, local readiness, FFmpeg encode/probe/decode/export path.
        - [ ] Stop and restart the app; readiness returns without system Python/Node/FFmpeg.
        - [ ] Run Setup Center Repair. Verify the component remains usable.
        - [ ] Review the uninstall plan. Default plan preserves user data.

        Expected offline result: local project/database/vector degraded contract and FFmpeg processing pass. Provider-backed generation may be unavailable until lecturer-owned provider credentials are configured; record that as an honest limitation, not as a shell/component failure.
        """,
    )
    write_text(
        root / "SYSTEM-REQUIREMENTS.md",
        f"""# System requirements

        - Windows 10 or Windows 11, 64-bit x86 (`x86_64`).
        - WebView2 runtime for the Tauri desktop shell.
        - At least 2 GB free for the shell and release components; allow additional working space for projects and media. The engine archive is {size(engine_archive):,} bytes and FFmpeg archive is {size(ffmpeg_archive):,} bytes.
        - Local administrator approval for the per-machine Program Files installation.
        - Internet is optional for this handoff after the installer is present; the provided catalog and component artifacts are local.
        - Python, Node.js, Docker, and a system FFmpeg installation are **not** required by the installed release.
        - Provider API keys, models, media libraries, and project databases are intentionally not bundled.

        The base shell is a Windows x64 RC. Component archives are separately authenticated and target Windows x64 only.
        """,
    )
    write_text(
        root / "TROUBLESHOOTING.md",
        f"""# Troubleshooting

        ## SmartScreen / unknown publisher

        The NSIS installer was built with `--no-sign`; no Authenticode certificate was available. SmartScreen may display an unknown-publisher warning. Verify `SHA256SUMS.txt` and the public Ed25519 trust root before choosing **More info → Run anyway**. Do not treat this RC as commercially code-signed.

        ## UAC, Program Files, or permission errors

        Run the installer from a local folder and approve elevation. The base shell targets `C:\\Program Files\\AI Video Editor Desktop V2`; Setup Center stores machine component state below ProgramData and user data separately. Do not grant write access to the whole Windows directory.

        ## Catalog import says the artifact is missing

        Keep the `Catalog` and `Components` directories together. Portable offline references resolve only beneath the directory containing the imported catalog, with traversal and boundary checks. Do not rename an archive or open a copied catalog without its matching Components folder. Re-run `VERIFY-HANDOFF.ps1`.

        ## Network or production catalog

        Network access is not needed for the provided offline catalog. `Catalog\\production-catalog.template.json` is only a template with placeholders; it makes no fake HTTPS availability claim and must not be used until hosted artifacts, real HTTPS URLs, and a new signed catalog are supplied.

        ## Repair / rollback

        Use Setup Center's Repair action after selecting the installed component. The manager stages a verified copy and atomically activates it. If activation fails, the previous active version is retained when one exists. This handoff ships one version, so it cannot demonstrate a version downgrade without a second signed release.

        ## Uninstall

        The default plan removes the shell and preserves user data. Review the plan shown by Setup Center before selecting any explicit data-removal option.

        ## Provider-backed features

        No provider secrets or models are included. Configure lecturer-owned provider credentials only after the local engine and FFmpeg smoke passes.
        """,
    )
    write_text(
        root / "RELEASE-NOTES.md",
        f"""# Release notes — Desktop V2 {VERSION}

        - Release channel: **{CHANNEL}**.
        - Small per-machine Tauri/NSIS shell with stable Desktop V2 identity, Program Files target, shortcuts, migration hooks, and data-preserving uninstall defaults.
        - Real PyInstaller onedir Windows x64 native engine, self-test enabled, loopback authenticated API, local SQLite/vector degraded contract, and graceful shutdown.
        - Real Gyan.dev FFmpeg/FFprobe Windows x64 build pinned at **8.1.1**, packaged separately under GPL-3.0-only notices and tested for encode/decode/probe.
        - Signed offline catalog with required engine and FFmpeg entries, dependency/disk metadata, and portable `offline:Components/...` artifact references.
        - Ed25519 release trust root: `{KEY_ID}` (`{PUBLIC_KEY_SHA256}`).
        - Component manifests, archives, and catalog are Ed25519 signed and SHA-256 verified.
        - Windows Authenticode status: **unsigned**. SmartScreen/unknown-publisher warning is expected; no commercial certificate is claimed.

        ## Limitations

        The handoff contains no Docker environment, provider keys, models, user data, or production HTTPS catalog. The release is a lecturer RC and supports the documented offline/local smoke workflow. Provider-backed AI operations require external configuration.
        """,
    )
    write_text(
        root / "LICENSES-AND-SOURCES.md",
        f"""# Licenses, notices, and sources

        ## Desktop shell and native engine

        The shell and native engine are built from the AI Video Editor project source: <https://github.com/desanv01/ai-video-editor>. The engine is a local PyInstaller 6.11.1 Windows x64 onedir build from Python 3.11.15. PyInstaller's bundled runtime notices are included inside the engine archive under `LICENSES/NOTICE.txt`; the archive contains no provider credentials, models, or user data.

        ## FFmpeg / FFprobe

        - Distribution: Gyan.dev **FFmpeg 8.1.1 full build** for Windows x64.
        - Provenance: installed local Microsoft WinGet package `Gyan.FFmpeg` under the user's package root; no system PATH executable was used.
        - Build/version output: `{ffmpeg_source["versionOutput"]}`.
        - Source page: <{ffmpeg_source["sourcePage"]}>.
        - FFmpeg source commit: `{ffmpeg_source["sourceCommit"]}`.
        - License: **GPL-3.0-only**, with the distribution notice copied into the FFmpeg component archive as `LICENSES/NOTICE.txt`.
        - Included executables: `bin/ffmpeg.exe` and `bin/ffprobe.exe`; `ffplay.exe` is not bundled.

        ## Release trust and signing

        The lecturer release trust root is Ed25519 key `{KEY_ID}` with public-key SHA-256 `{PUBLIC_KEY_SHA256}`. The private seed is preserved outside the repository in a restricted release-secrets directory and is not present in this handoff, repository, logs, or archives. Component and catalog signatures are real Ed25519 signatures. The installer has no Authenticode signature; no commercial code-signing certificate is claimed.
        """,
    )


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    target_root = args.target_root.resolve()
    expected_target = args.expected_target.resolve()
    public_key_file = args.public_key_file.resolve()
    if target_root != expected_target or target_root != EXPECTED_TARGET.resolve():
        raise ValueError(f"refusing unexpected handoff target: {target_root}")
    if target_root.exists() and any(target_root.iterdir()):
        existing = {path.relative_to(target_root).as_posix() for path in target_root.rglob("*") if path.is_file()}
        allowed_partial = HANDOFF_FILES
        if not args.resume or not existing.issubset(allowed_partial):
            raise ValueError(f"handoff target must be new and empty, or an exact known partial assembly with --resume: {target_root}")
    if public_key_file.is_relative_to(source_root):
        raise ValueError("public key must be supplied from outside the repository")
    if not public_key_file.is_file():
        raise FileNotFoundError(public_key_file)
    target_root.mkdir(parents=True, exist_ok=True)

    build_root = source_root / "build" / "desktop-v2" / "phase9"
    installer = source_root / "desktop" / "src-tauri" / "target" / "release" / "bundle" / "nsis" / f"AI Video Editor Desktop V2_{VERSION}_x64-setup.exe"
    engine_manifest_path = build_root / "components" / "engine" / "manifest.json"
    ffmpeg_manifest_path = build_root / "components" / "ffmpeg" / "manifest.json"
    engine = json.loads(engine_manifest_path.read_text(encoding="utf-8"))
    ffmpeg = json.loads(ffmpeg_manifest_path.read_text(encoding="utf-8"))
    ffmpeg_source = json.loads((build_root / "ffmpeg-source" / "source.json").read_text(encoding="utf-8"))
    if engine["component"]["version"] != VERSION or ffmpeg["component"]["version"] != "8.1.1":
        raise ValueError("component versions do not match the frozen RC identity")
    if engine["signature"]["keyId"] != KEY_ID or ffmpeg["signature"]["keyId"] != KEY_ID:
        raise ValueError("component signatures are not made by the release trust root")
    if not installer.is_file():
        raise FileNotFoundError(installer)

    copy_file(installer, target_root / "AI Video Editor Desktop V2 Setup.exe")
    copy_file(build_root / "components" / "engine" / f"aive-engine-{VERSION}.tar.gz", target_root / "Components" / f"aive-engine-{VERSION}.tar.gz")
    copy_file(engine_manifest_path, target_root / "Components" / "aive-engine-manifest.json")
    copy_file(build_root / "components" / "engine" / "manifest.sig", target_root / "Components" / "aive-engine-manifest.sig")
    copy_file(build_root / "components" / "ffmpeg" / "ffmpeg-8.1.1.tar.gz", target_root / "Components" / "ffmpeg-8.1.1.tar.gz")
    copy_file(ffmpeg_manifest_path, target_root / "Components" / "ffmpeg-manifest.json")
    copy_file(build_root / "components" / "ffmpeg" / "manifest.sig", target_root / "Components" / "ffmpeg-manifest.sig")
    copy_file(build_root / "catalog" / "offline-catalog.json", target_root / "Catalog" / "offline-catalog.json")
    copy_file(build_root / "catalog" / "offline-catalog.sig", target_root / "Catalog" / "offline-catalog.sig")
    copy_file(build_root / "catalog" / "production-catalog.template.json", target_root / "Catalog" / "production-catalog.template.json")
    copy_file(public_key_file, target_root / "Catalog" / "lecturer-release-public-key.json")
    copy_file(build_root / "ffmpeg-smoke.mp4", target_root / "SMOKE" / "synthetic-source.mp4")
    copy_file(source_root / "scripts" / "desktop-v2" / "VERIFY-HANDOFF.ps1", target_root / "VERIFY-HANDOFF.ps1")
    copy_file(source_root / "scripts" / "desktop-v2" / "verify_handoff_signatures.py", target_root / "verify-handoff-signatures.py")

    create_docs(target_root, engine, ffmpeg, target_root / "AI Video Editor Desktop V2 Setup.exe", target_root / "Catalog" / "offline-catalog.json", ffmpeg_source)

    trust = json.loads((target_root / "Catalog" / "lecturer-release-public-key.json").read_text(encoding="utf-8"))
    if trust.get("keyId") != KEY_ID or trust.get("publicKeySha256") != PUBLIC_KEY_SHA256:
        raise ValueError("copied public trust root does not match compiled release identity")

    component_records: list[dict[str, object]] = []
    for component_id, manifest_name, signature_name in (
        ("aive-engine", "aive-engine-manifest.json", "aive-engine-manifest.sig"),
        ("ffmpeg", "ffmpeg-manifest.json", "ffmpeg-manifest.sig"),
    ):
        manifest = json.loads((target_root / "Components" / manifest_name).read_text(encoding="utf-8"))
        artifact = manifest["artifact"]
        assert isinstance(artifact, dict)
        archive_path = target_root / "Components" / Path(str(artifact["url"]).split("/")[-1]).name
        component_records.append(
            {
                "componentId": component_id,
                "version": manifest["component"]["version"],
                "archive": file_record(archive_path, target_root),
                "manifest": file_record(target_root / "Components" / manifest_name, target_root),
                "signature": file_record(target_root / "Components" / signature_name, target_root),
                "manifestArtifact": {"byteSize": artifact["byteSize"], "sha256": artifact["sha256"], "url": artifact["url"]},
            }
        )
    catalog_record = {
        "catalog": file_record(target_root / "Catalog" / "offline-catalog.json", target_root),
        "signature": file_record(target_root / "Catalog" / "offline-catalog.sig", target_root),
        "schemaVersion": "desktop.setup-catalog.v1",
        "catalogId": json.loads((target_root / "Catalog" / "offline-catalog.json").read_text(encoding="utf-8"))["catalogId"],
        "channel": CHANNEL,
    }
    ffmpeg_files = {entry["path"]: entry for entry in ffmpeg["files"]}
    release_manifest = {
        "schemaVersion": "desktop.release-manifest.v1",
        "product": {"name": "AI Video Editor Desktop V2", "identifier": "com.aivideoeditor.desktop.v2", "version": VERSION, "channel": CHANNEL},
        "source": {"branch": BRANCH, "basePhase8Commit": BASE_PHASE8_COMMIT, "phase9SourceCommit": "recorded by the final Phase 9 commit", "repository": "https://github.com/desanv01/ai-video-editor"},
        "contracts": {"shell": "desktop.shell-identity.v1", "engine": "desktop.health-readiness.v1", "componentManifest": "desktop.component-manifest.v1", "catalog": "desktop.setup-catalog.v1"},
        "requirements": {"minimumWindows": "Windows 10 64-bit", "architectures": ["x86_64"], "webView2": True, "minimumFreeBytes": 2147483648, "systemRuntimesRequired": []},
        "trustRoot": {"algorithm": "ed25519", "keyId": KEY_ID, "publicKeySha256": PUBLIC_KEY_SHA256, "publicKeyPath": "Catalog/lecturer-release-public-key.json", "privateKeyInHandoff": False},
        "authenticode": {"status": "unsigned", "commercialCertificate": False, "smartScreenExpectedWarning": True, "buildFlag": "--no-sign"},
        "installer": {"path": "AI Video Editor Desktop V2 Setup.exe", "target": "C:/Program Files/AI Video Editor Desktop V2", "requiresElevation": True, "shortcuts": ["Start Menu", "Desktop"], "file": file_record(target_root / "AI Video Editor Desktop V2 Setup.exe", target_root)},
        "components": component_records,
        "ffmpegProvenance": {**ffmpeg_source, "archive": file_record(target_root / "Components" / "ffmpeg-8.1.1.tar.gz", target_root), "ffmpegExe": ffmpeg_files["bin/ffmpeg.exe"], "ffprobeExe": ffmpeg_files["bin/ffprobe.exe"]},
        "catalog": catalog_record,
        "offlineFlow": {"artifactReferenceScheme": "offline:Components/<filename>", "artifactRoot": "directory-containing-Catalog-and-Components", "requiredComponents": ["aive-engine", "ffmpeg"], "productionTemplateIsUnsigned": True},
        "dataSafety": {"bundledUserProjects": False, "bundledUploads": False, "bundledModels": False, "bundledDatabases": False, "bundledEnvironmentFiles": False, "bundledApiKeys": False},
        "verification": {"script": "VERIFY-HANDOFF.ps1", "readOnly": True, "executesInstallerOrComponents": False, "sha256File": "SHA256SUMS.txt"},
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    write_json(target_root / "release-manifest.json", release_manifest)

    expected_files = sorted(path for path in target_root.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
    sums = "".join(f"{sha256(path)}  {rel(path, target_root)}\n" for path in expected_files)
    write_text(target_root / "SHA256SUMS.txt", sums)
    print(json.dumps({"status": "assembled", "target": str(target_root), "files": len(expected_files) + 1, "installerBytes": size(target_root / "AI Video Editor Desktop V2 Setup.exe"), "engineArchiveBytes": size(target_root / "Components" / f"aive-engine-{VERSION}.tar.gz"), "ffmpegArchiveBytes": size(target_root / "Components" / "ffmpeg-8.1.1.tar.gz")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"assemble_handoff.py: error: {error}")
