#!/usr/bin/env python3
"""Freeze RC.6 release provenance inside a new, already-staged handoff.

This command never copies or reads a signing seed and never creates component
signatures. Component manifests and the catalog must already be freshly signed
by the existing packaging/signing commands. It refuses RC.4/RC.5 paths and
refuses to overwrite any provenance output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


VERSION = "2.0.0-rc.6"
FFMPEG_VERSION = "8.1.1"
PRODUCT = "AI Video Editor Desktop V2"
IDENTIFIER = "com.fyp.ai-video-editor.desktop-v2"
INSTALL_TARGET = "%ProgramFiles%/AI Video Editor Desktop V2/Shell"
FORBIDDEN_PRIVATE_NAMES = ("ed25519-seed", "private-key", ".pfx", ".p12", ".pem", ".key")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--signing-seed", type=Path, help="Existence check only; contents are never read.")
    parser.add_argument("--signing-profile", choices=("developer-test", "external-release"), default="developer-test")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def git_value(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def generated_at() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_new_rc6_root(root: Path, source_root: Path) -> None:
    lowered = str(root).lower().replace("_", "-")
    if "rc6" not in root.name.lower() or "rc4" in lowered or "rc5" in lowered:
        raise ValueError("handoff root must be a uniquely named RC.6 directory, never an RC.4/RC.5 output")
    output_root = (source_root / "output").resolve()
    if not root.is_dir() or root.parent != output_root:
        raise ValueError("handoff root must be a direct child of source_root/output")
    for name in ("release-manifest.json", "LICENSES-AND-SOURCES.md", "sbom.cdx.json", "SHA256SUMS.txt"):
        if (root / name).exists():
            raise ValueError(f"refusing to overwrite existing RC.6 provenance output: {name}")


def validate_private_material(root: Path, seed: Path | None, source_root: Path) -> bool:
    for path in root.rglob("*"):
        if path.is_file() and any(token in path.name.lower() for token in FORBIDDEN_PRIVATE_NAMES):
            raise ValueError(f"private key material is forbidden in handoff: {path.relative_to(root)}")
    if seed is None:
        return False
    resolved = seed.resolve()
    if not resolved.is_file():
        raise ValueError("external signing seed was specified but does not exist")
    if resolved == root or root in resolved.parents or resolved == source_root or source_root in resolved.parents:
        raise ValueError("signing seed must remain outside the repository and handoff")
    # Deliberately do not open, hash, print, copy, or serialize this path.
    return True


def main() -> int:
    args = parse_args()
    root = args.handoff_root.resolve()
    source_root = args.source_root.resolve()
    require_new_rc6_root(root, source_root)
    seed_present = validate_private_material(root, args.signing_seed, source_root)

    installer = root / f"{PRODUCT} Setup.exe"
    catalog_path = root / "Catalog" / "offline-catalog.json"
    catalog_sig = root / "Catalog" / "offline-catalog.sig"
    public_key = root / "Catalog" / "release-public-key.json"
    component_paths = {
        "aive-engine": root / "Components" / "aive-engine-manifest.json",
        "ffmpeg": root / "Components" / "ffmpeg-manifest.json",
    }
    required = [installer, catalog_path, catalog_sig, public_key]
    for manifest_path in component_paths.values():
        required.extend([manifest_path, manifest_path.with_suffix(".sig")])
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise ValueError("missing signed RC.6 release inputs: " + ", ".join(missing))

    catalog = read_json(catalog_path)
    trust = read_json(public_key)
    components: list[dict[str, object]] = []
    for component_id, manifest_path in component_paths.items():
        manifest = read_json(manifest_path)
        component = manifest.get("component")
        artifact = manifest.get("artifact")
        metadata = manifest.get("metadata")
        if not isinstance(component, dict) or component.get("id") != component_id:
            raise ValueError(f"component identity mismatch in {manifest_path.name}")
        if not isinstance(artifact, dict):
            raise ValueError(f"artifact is missing from {manifest_path.name}")
        if component_id == "ffmpeg":
            if component.get("version") != FFMPEG_VERSION:
                raise ValueError(f"RC.6 requires FFmpeg {FFMPEG_VERSION}")
            if not isinstance(metadata, dict) or metadata.get("license", {}).get("spdxId") != "GPL-3.0-only":
                raise ValueError("FFmpeg manifest must carry GPL-3.0-only license metadata")
        artifact_url = str(artifact.get("url", ""))
        if not artifact_url.startswith("offline:Components/") or ".." in artifact_url:
            raise ValueError(f"non-portable artifact URL in {manifest_path.name}")
        archive = root / "Components" / Path(artifact_url.removeprefix("offline:Components/")).name
        if not archive.is_file() or archive.stat().st_size != artifact.get("byteSize") or sha256(archive) != artifact.get("sha256"):
            raise ValueError(f"archive provenance mismatch for {component_id}")
        components.append({
            "componentId": component_id,
            "version": component.get("version"),
            "archive": record(root, archive),
            "manifest": record(root, manifest_path),
            "signature": record(root, manifest_path.with_suffix(".sig")),
        })

    manifest = {
        "schemaVersion": "desktop.release-manifest.v1",
        "product": {"name": PRODUCT, "identifier": IDENTIFIER, "version": VERSION, "channel": "beta"},
        "generatedAt": generated_at(),
        "source": {
            "commit": git_value(source_root, "rev-parse", "HEAD"),
            "branch": git_value(source_root, "branch", "--show-current"),
            "dirty": bool(git_value(source_root, "status", "--porcelain")),
        },
        "layout": {
            "shell": INSTALL_TARGET,
            "machineData": "%ProgramData%/AI Video Editor",
            "userState": "%LocalAppData%/AI Video Editor",
            "userContent": "%USERPROFILE%/Documents/AI Video Editor",
            "shortcuts": ["Desktop/AI Video Editor Desktop V2.lnk", "Start Menu/AI Video Editor Desktop V2/AI Video Editor Desktop V2.lnk"],
        },
        "installer": {**record(root, installer), "scope": "per-machine", "authenticode": "not-claimed"},
        "components": components,
        "catalog": {**record(root, catalog_path), "signature": record(root, catalog_sig), "catalogId": catalog.get("catalogId")},
        "trustRoot": {
            "algorithm": "ed25519",
            "keyId": trust.get("keyId"),
            "publicKeySha256": trust.get("publicKeySha256"),
            "privateSeedIncluded": False,
            "externalSeedPresenceChecked": seed_present,
            "productionSeedStatus": "not-asserted",
            "signingProfile": args.signing_profile,
            "shellTrustsCatalog": args.signing_profile == "developer-test",
        },
        "authenticode": {
            "status": "not-claimed",
            "certificateIncluded": False,
            "verificationRequiredBeforeCommercialRelease": True,
        },
        "releaseQualification": {
            "label": "developer/test" if args.signing_profile == "developer-test" else "external-release-candidate",
            "productionTrusted": False,
            "reason": "shell and artifacts share a deterministic public test trust root that is non-production" if args.signing_profile == "developer-test" else "external signing provenance still requires independent signature and clean-machine verification",
        },
        "verification": {"sbom": "sbom.cdx.json", "checksums": "SHA256SUMS.txt", "signatures": "verify-handoff-signatures.py"},
    }
    (root / "release-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (root / "LICENSES-AND-SOURCES.md").write_text(
        "# Licenses and sources — 2.0.0-rc.6\n\n"
        "- AI Video Editor Desktop V2: repository license applies; see the source checkout.\n"
        "- FFmpeg 8.1.1: GPL-3.0-only; source commit `239f2c733d`; build asset and exact SHA-256 are recorded in `Components/ffmpeg-manifest.json` and `Evidence/ffmpeg-8.1.1.provenance.json`.\n"
        "- Third-party notices shipped inside each component archive remain authoritative.\n"
        "- Ed25519 signatures authenticate component/catalog metadata only. Authenticode is not claimed by this record.\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run([
        sys.executable,
        str(source_root / "scripts" / "desktop-v2" / "generate_sbom.py"),
        "--root", str(root), "--output", str(root / "sbom.cdx.json"), "--version", VERSION,
    ], check=True, cwd=source_root)
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(root).as_posix()}\n" for path in files),
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({"status": "provenance-frozen", "version": VERSION, "files": len(files), "seedPresent": seed_present}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"generate_rc6_release_provenance.py: error: {error}")
