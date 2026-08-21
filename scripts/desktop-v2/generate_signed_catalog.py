#!/usr/bin/env python3
"""Create a Phase 6-compatible signed catalog from signed component manifests.

The normal output is an offline catalog whose manifest artifact URLs use
portable ``offline:Components/...`` references. The shell resolves those
references only beneath the handoff root containing the imported ``Catalog``
directory and its sibling ``Components`` directory.
The optional production template is visibly unsigned and contains placeholders
that must be replaced and re-signed after a real HTTPS host is chosen.
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCHEMA_VERSION = "desktop.setup-catalog.v1"
COMPONENT_SCHEMA_VERSION = "desktop.component-manifest.v1"
REQUIRED_COMPONENTS = ("aive-engine", "ffmpeg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-manifest", type=Path, required=True)
    parser.add_argument("--ffmpeg-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--detached-signature", type=Path, required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--catalog-id", default="aive-desktop-v2-lecturer-rc-2.0.0-rc.1")
    parser.add_argument("--channel", choices=("stable", "beta", "nightly"), default="beta")
    parser.add_argument("--generated-at")
    parser.add_argument("--expires-at")
    parser.add_argument("--production-template", type=Path)
    return parser.parse_args()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def read_seed(path: Path) -> bytes:
    seed = bytes.fromhex(path.read_text(encoding="ascii").strip())
    if len(seed) != 32:
        raise ValueError("Ed25519 seed must contain exactly 32 bytes")
    return seed


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str, field: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp ending in Z")
    return value


def load_manifest(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != COMPONENT_SCHEMA_VERSION:
        raise ValueError(f"unsupported component manifest schema in {path}")
    component = manifest.get("component")
    artifact = manifest.get("artifact")
    metadata = manifest.get("metadata")
    signature = manifest.get("signature")
    if not isinstance(component, dict) or not isinstance(artifact, dict) or not isinstance(metadata, dict) or not isinstance(signature, dict):
        raise ValueError(f"component manifest is missing required objects: {path}")
    if not isinstance(component.get("id"), str) or component["id"] not in REQUIRED_COMPONENTS:
        raise ValueError(f"manifest component id is not a required Desktop V2 component: {path}")
    if signature.get("algorithm") != "ed25519" or not signature.get("value") or not signature.get("keyId"):
        raise ValueError(f"manifest signature is incomplete: {path}")
    if not isinstance(artifact.get("byteSize"), int) or not isinstance(artifact.get("sha256"), str):
        raise ValueError(f"manifest artifact metadata is incomplete: {path}")
    return manifest


def component_entry(manifest: dict[str, object]) -> dict[str, object]:
    component = manifest["component"]
    artifact = manifest["artifact"]
    metadata = manifest["metadata"]
    assert isinstance(component, dict) and isinstance(artifact, dict) and isinstance(metadata, dict)
    license_info = metadata.get("license")
    source = metadata.get("source")
    assert isinstance(license_info, dict) and isinstance(source, dict)
    component_id = str(component["id"])
    description = (
        "Authenticated PyInstaller onedir native core engine with local SQLite, "
        "local-vector degraded mode, and loopback bearer-token API."
        if component_id == "aive-engine"
        else "Pinned Gyan.dev Windows x64 FFmpeg/FFprobe toolchain for local media encode, decode, and probe."
    )
    return {
        "componentId": component_id,
        "displayName": str(metadata["displayName"]),
        "required": True,
        "availability": "available",
        "description": description,
        "artifactBytes": int(artifact["byteSize"]),
        "licenseVersion": str(license_info["spdxId"]),
        "licenseName": str(license_info["spdxId"]),
        "sourceUrl": str(source["repositoryUrl"]),
        "unavailableReason": None,
        "manifest": manifest,
    }


def empty_signature_catalog(catalog: dict[str, object]) -> dict[str, object]:
    unsigned = copy.deepcopy(catalog)
    signature = unsigned["signature"]
    assert isinstance(signature, dict)
    signature["value"] = ""
    return unsigned


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def production_template(catalog: dict[str, object]) -> dict[str, object]:
    template = copy.deepcopy(catalog)
    template["catalogId"] = "REPLACE_WITH_REAL_CATALOG_ID"
    template["generatedAt"] = "REPLACE_WITH_GENERATED_AT_UTC"
    template["expiresAt"] = "REPLACE_WITH_EXPIRY_UTC"
    signature = template["signature"]
    assert isinstance(signature, dict)
    signature["value"] = "REPLACE_WITH_BASE64_SIGNATURE_AFTER_REPLACEMENT"
    entries = template["entries"]
    assert isinstance(entries, list)
    for entry in entries:
        assert isinstance(entry, dict)
        manifest = entry["manifest"]
        assert isinstance(manifest, dict)
        artifact = manifest["artifact"]
        assert isinstance(artifact, dict)
        component_id = entry["componentId"]
        version = manifest["component"]["version"]
        artifact["url"] = f"https://<RELEASE_HOST>/components/{component_id}/{component_id}-{version}.tar.gz"
        manifest_signature = manifest["signature"]
        assert isinstance(manifest_signature, dict)
        manifest_signature["value"] = "REPLACE_WITH_BASE64_MANIFEST_SIGNATURE"
    return template


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.catalog_id):
        raise ValueError("catalog id contains unsafe characters")
    engine = load_manifest(args.engine_manifest.resolve())
    ffmpeg = load_manifest(args.ffmpeg_manifest.resolve())
    if engine["component"]["id"] != "aive-engine" or ffmpeg["component"]["id"] != "ffmpeg":
        raise ValueError("the two manifests must be aive-engine and ffmpeg")
    generated_at = parse_timestamp(args.generated_at, "generated-at") if args.generated_at else iso_now()
    expires_at = parse_timestamp(args.expires_at, "expires-at") if args.expires_at else (
        datetime.fromisoformat(generated_at.replace("Z", "+00:00")) + timedelta(days=180)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    catalog: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "catalogId": args.catalog_id,
        "channel": args.channel,
        "generatedAt": generated_at,
        "expiresAt": expires_at,
        "entries": [component_entry(engine), component_entry(ffmpeg)],
        "signature": {"algorithm": "ed25519", "keyId": args.key_id, "value": ""},
    }
    signature = Ed25519PrivateKey.from_private_bytes(read_seed(args.private_key_file.resolve())).sign(
        canonical_json(catalog)
    )
    catalog["signature"]["value"] = base64.b64encode(signature).decode("ascii")  # type: ignore[index]
    write_json(args.output.resolve(), catalog)
    args.detached_signature.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.detached_signature.resolve().write_bytes(signature)
    if args.production_template:
        write_json(args.production_template.resolve(), production_template(catalog))
    print(json.dumps({"catalog": str(args.output.resolve()), "detachedSignature": str(args.detached_signature.resolve()), "keyId": args.key_id, "channel": args.channel}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"generate_signed_catalog.py: error: {error}")
