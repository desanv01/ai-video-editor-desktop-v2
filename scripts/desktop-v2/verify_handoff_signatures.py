#!/usr/bin/env python3
"""Read-only Ed25519 verification helper for VERIFY-HANDOFF.ps1."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def payload(value: dict[str, object]) -> bytes:
    normalized = json.loads(json.dumps(value))
    signature = normalized.get("signature")
    if isinstance(signature, dict):
        signature["value"] = ""
    return canonical(normalized)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_manifest(root: Path, path_text: str, key: Ed25519PublicKey, key_id: str) -> dict[str, object]:
    path = root / path_text
    manifest = json.loads(path.read_text(encoding="utf-8"))
    signature = manifest["signature"]
    if signature["algorithm"] != "ed25519" or signature["keyId"] != key_id:
        raise ValueError(f"manifest trust identity mismatch: {path_text}")
    encoded = signature["value"]
    raw = base64.b64decode(encoded, validate=True)
    detached = (root / path_text.replace("manifest.json", "manifest.sig")).read_bytes()
    if detached != raw:
        raise ValueError(f"detached manifest signature differs from embedded signature: {path_text}")
    key.verify(raw, payload(manifest))
    artifact = manifest["artifact"]
    url = artifact["url"]
    if not isinstance(url, str) or not url.startswith("offline:Components/"):
        raise ValueError(f"manifest has a non-portable artifact URL: {path_text}")
    relative = url.removeprefix("offline:")
    parts = relative.split("/")
    if len(parts) != 2 or parts[0] != "Components" or any(part in ("", ".", "..") or ":" in part for part in parts):
        raise ValueError(f"manifest has an unsafe portable artifact reference: {url}")
    archive = (root / Path(*parts)).resolve()
    root_resolved = root.resolve()
    try:
        if archive.relative_to(root_resolved).as_posix() != relative:
            raise ValueError(f"portable artifact escapes handoff root: {url}")
    except ValueError as error:
        raise ValueError(f"portable artifact escapes handoff root: {url}") from error
    if not archive.is_file() or archive.stat().st_size != artifact["byteSize"] or sha256(archive) != artifact["sha256"]:
        raise ValueError(f"manifest artifact hash/size mismatch: {archive}")
    return manifest


def check_no_creator_paths(root: Path) -> None:
    checked = [
        root / "Catalog" / "offline-catalog.json",
        root / "Components" / "aive-engine-manifest.json",
        root / "Components" / "ffmpeg-manifest.json",
        root / "release-manifest.json",
    ]
    for path in checked:
        text = path.read_text(encoding="utf-8")
        if "file://" in text.lower() or re.search(r"(?i)(?:[A-Z]:[\\/]Users[\\/]|\\\\[^\\/]+\\)", text):
            raise ValueError(f"creator-machine or absolute local path found in signed release metadata: {path}")


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else Path(__file__).resolve().parent
    trust = json.loads((root / "Catalog" / "lecturer-release-public-key.json").read_text(encoding="utf-8"))
    key_id = trust["keyId"]
    public_key_bytes = base64.b64decode(trust["publicKeyBase64"], validate=True)
    if hashlib.sha256(public_key_bytes).hexdigest() != trust["publicKeySha256"]:
        raise ValueError("public trust root fingerprint mismatch")
    key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    check_no_creator_paths(root)
    engine = check_manifest(root, "Components/aive-engine-manifest.json", key, key_id)
    ffmpeg = check_manifest(root, "Components/ffmpeg-manifest.json", key, key_id)
    catalog_path = root / "Catalog" / "offline-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_signature = catalog["signature"]
    if catalog_signature["algorithm"] != "ed25519" or catalog_signature["keyId"] != key_id:
        raise ValueError("catalog trust identity mismatch")
    raw_catalog_signature = base64.b64decode(catalog_signature["value"], validate=True)
    if (root / "Catalog" / "offline-catalog.sig").read_bytes() != raw_catalog_signature:
        raise ValueError("detached catalog signature differs from embedded signature")
    key.verify(raw_catalog_signature, payload(catalog))
    entries = {entry["componentId"]: entry for entry in catalog["entries"]}
    for component_id, manifest in (("aive-engine", engine), ("ffmpeg", ffmpeg)):
        if entries[component_id]["manifest"] != manifest:
            raise ValueError(f"catalog manifest differs from component manifest: {component_id}")
    print(json.dumps({"status": "ok", "keyId": key_id, "catalog": catalog["catalogId"], "components": ["aive-engine", "ffmpeg"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"verify_handoff_signatures.py: FAIL: {error}")
