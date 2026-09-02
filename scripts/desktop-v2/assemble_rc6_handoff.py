#!/usr/bin/env python3
"""Assemble a fresh, timestamped Desktop V2 RC.6 handoff and ZIP.

Inputs are caller-built installer, component package directories, catalog,
public key, and optional evidence. RC.2/RC.4/RC.5 inputs and existing outputs
are rejected. The default profile is a coherent developer/test trust root and
is never described as lecturer-ready or production-trusted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


VERSION = "2.0.0-rc.6"
TARGET_PREFIX = "AI-Video-Editor-Desktop-V2-RC6-Handoff-"
FORBIDDEN_PRIOR = ("rc2", "rc.2", "rc4", "rc.4", "rc5", "rc.5")
TEST_PUBLIC_KEY_SHA256 = "22094d0fd9318ff224ea22abeec545b5c5d653fd8be5b480790de2d7743bb404"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--engine-package", type=Path, required=True)
    parser.add_argument("--ffmpeg-package", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--catalog-signature", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--signing-profile", choices=("developer-test", "external-release"), default="developer-test")
    parser.add_argument("--signing-seed", type=Path, help="Forwarded for existence/location check only; never copied.")
    parser.add_argument("--timestamp", help="UTC YYYYMMDD-HHMMSS; defaults to current time or SOURCE_DATE_EPOCH.")
    return parser.parse_args()


def timestamp(args: argparse.Namespace) -> str:
    if args.timestamp:
        datetime.strptime(args.timestamp, "%Y%m%d-%H%M%S")
        return args.timestamp
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return moment.strftime("%Y%m%d-%H%M%S")


def reject_prior(path: Path) -> None:
    lowered = str(path.resolve()).lower().replace("_", "-")
    if any(token in lowered for token in FORBIDDEN_PRIOR):
        raise ValueError(f"RC.6 assembler rejects copied prior-RC input: {path}")


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def package_files(package: Path, component_id: str) -> tuple[Path, Path, Path, dict[str, object]]:
    reject_prior(package)
    manifest_path = package / "manifest.json"
    signature_path = package / "manifest.sig"
    manifest = load_object(manifest_path)
    component = manifest.get("component")
    requirements = manifest.get("requirements")
    artifact = manifest.get("artifact")
    if not isinstance(component, dict) or component.get("id") != component_id:
        raise ValueError(f"wrong component package identity: {package}")
    if not isinstance(requirements, dict) or requirements.get("minimumShellVersion") != VERSION:
        raise ValueError(f"{component_id} lacks fresh RC.6 minimumShellVersion provenance")
    if component_id == "ffmpeg" and component.get("version") != "8.1.1":
        raise ValueError("RC.6 requires FFmpeg 8.1.1")
    if not isinstance(artifact, dict):
        raise ValueError(f"artifact metadata missing: {manifest_path}")
    archives = [path for path in package.iterdir() if path.is_file() and path.name not in {"manifest.json", "manifest.sig", "test-public-key.json"}]
    if len(archives) != 1:
        raise ValueError(f"{component_id} package must contain exactly one archive")
    if not signature_path.is_file():
        raise ValueError(f"detached signature missing: {signature_path}")
    return manifest_path, signature_path, archives[0], manifest


def copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def deterministic_zip(root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            info = zipfile.ZipInfo(path.relative_to(root.parent).as_posix(), (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    output_root = (args.output_dir or source_root / "output").resolve()
    if output_root != (source_root / "output").resolve():
        raise ValueError("RC.6 output-dir must be exactly source_root/output")
    output_root.mkdir(parents=True, exist_ok=True)
    final_target = output_root / f"{TARGET_PREFIX}{timestamp(args)}"
    target = output_root / f".{final_target.name}.partial"
    zip_path = final_target.with_suffix(".zip")
    if target.exists() or final_target.exists() or zip_path.exists():
        raise ValueError("refusing to overwrite an existing timestamped RC.6 handoff, partial staging root, or ZIP")

    for path in [args.installer, args.catalog, args.catalog_signature, args.public_key, *args.evidence]:
        reject_prior(path)
    engine_manifest, engine_sig, engine_archive, engine = package_files(args.engine_package.resolve(), "aive-engine")
    ffmpeg_manifest, ffmpeg_sig, ffmpeg_archive, ffmpeg = package_files(args.ffmpeg_package.resolve(), "ffmpeg")
    catalog = load_object(args.catalog.resolve())
    if "rc6" not in str(catalog.get("catalogId", "")).lower().replace(".", ""):
        raise ValueError("catalogId must explicitly identify a freshly generated RC.6 catalog")
    entries = catalog.get("entries")
    if not isinstance(entries, list) or len(entries) != 2:
        raise ValueError("RC.6 catalog must contain exactly the engine and FFmpeg entries")
    manifest_key_ids = {engine.get("signature", {}).get("keyId"), ffmpeg.get("signature", {}).get("keyId")}
    catalog_key_id = catalog.get("signature", {}).get("keyId")
    public_key = load_object(args.public_key.resolve())
    if manifest_key_ids != {catalog_key_id} or public_key.get("keyId") != catalog_key_id:
        raise ValueError("shell handoff, component manifests, catalog, and public key must use one coherent trust root")
    if args.signing_profile == "developer-test" and catalog_key_id != "test-fixture-2026":
        raise ValueError("developer/test handoff must use the deterministic test-fixture-2026 trust root")
    if args.signing_profile == "developer-test" and public_key.get("publicKeySha256") != TEST_PUBLIC_KEY_SHA256:
        raise ValueError("developer/test public key does not match the RC.6 shell's compiled test trust root")
    if args.signing_profile == "external-release" and catalog_key_id == "test-fixture-2026":
        raise ValueError("external-release profile cannot use the test fixture key")

    target.mkdir()
    copy(args.installer.resolve(), target / "AI Video Editor Desktop V2 Setup.exe")
    for component_id, manifest_path, signature_path, archive in (
        ("aive-engine", engine_manifest, engine_sig, engine_archive),
        ("ffmpeg", ffmpeg_manifest, ffmpeg_sig, ffmpeg_archive),
    ):
        copy(manifest_path, target / "Components" / f"{component_id}-manifest.json")
        copy(signature_path, target / "Components" / f"{component_id}-manifest.sig")
        copy(archive, target / "Components" / archive.name)
    copy(args.catalog.resolve(), target / "Catalog" / "offline-catalog.json")
    copy(args.catalog_signature.resolve(), target / "Catalog" / "offline-catalog.sig")
    copy(args.public_key.resolve(), target / "Catalog" / "release-public-key.json")
    for evidence in args.evidence:
        copy(evidence.resolve(), target / "Evidence" / evidence.name)
    for name in ("verify_handoff_signatures.py", "Verify-RC6Release.ps1", "Sign-DesktopV2Release.ps1"):
        copy(source_root / "scripts" / "desktop-v2" / name, target / ("verify-handoff-signatures.py" if name == "verify_handoff_signatures.py" else name))
    copy(source_root / "docs" / "desktop-v2" / "RC6_RELEASE_PROVENANCE.md", target / "Evidence" / "RC6_RELEASE_PROVENANCE.md")
    copy(source_root / "contracts" / "desktop-v2" / "ffmpeg-8.1.1.provenance.json", target / "Evidence" / "ffmpeg-8.1.1.provenance.json")
    label = "DEVELOPER/TEST — NOT PRODUCTION-TRUSTED" if args.signing_profile == "developer-test" else "EXTERNAL RELEASE CANDIDATE — VERIFICATION REQUIRED"
    (target / "START-HERE.md").write_text(
        f"# AI Video Editor Desktop V2 {VERSION}\n\n**{label}**\n\n"
        "Run `Verify-RC6Release.ps1` and `verify-handoff-signatures.py` before installation. "
        "The default developer/test trust root is coherent with this shell build but is public and non-production. "
        "Authenticode is not claimed. Do not distribute as lecturer-ready or commercial release evidence.\n",
        encoding="utf-8", newline="\n",
    )
    command = [
        sys.executable, str(source_root / "scripts" / "desktop-v2" / "generate_rc6_release_provenance.py"),
        "--source-root", str(source_root), "--handoff-root", str(target), "--signing-profile", args.signing_profile,
    ]
    if args.signing_seed:
        command.extend(["--signing-seed", str(args.signing_seed.resolve())])
    subprocess.run(command, check=True, cwd=source_root)
    subprocess.run([sys.executable, str(target / "verify-handoff-signatures.py"), str(target)], check=True, cwd=source_root)
    subprocess.run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(target / "Verify-RC6Release.ps1"), "-HandoffRoot", str(target),
    ], check=True, cwd=source_root)
    target.rename(final_target)
    deterministic_zip(final_target, zip_path)
    print(json.dumps({
        "status": "assembled", "version": VERSION, "label": label,
        "handoff": str(final_target), "zip": str(zip_path), "keyId": catalog_key_id,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"assemble_rc6_handoff.py: error: {error}")
