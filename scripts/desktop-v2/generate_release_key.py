#!/usr/bin/env python3
"""Generate a restricted Ed25519 trust root for a Desktop V2 release.

The output directory must be outside the repository.  The raw 32-byte seed is
written only there; the repository should receive the generated public-key
record, not the seed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def ensure_outside_repository(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError(f"refusing to write release secrets inside repository: {resolved}")


def secure_acl(path: Path) -> str:
    """Restrict the secret directory on Windows and return a non-secret note."""

    if os.name != "nt":
        try:
            path.chmod(0o700)
        except OSError:
            return "POSIX chmod could not be applied; review the directory ACL manually."
        return "Directory mode restricted to owner (0700)."

    username = os.environ.get("USERNAME")
    if not username:
        return "USERNAME was unavailable; review the directory ACL manually."
    command = [
        "icacls.exe",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"{username}:(OI)(CI)(F)",
        "*S-1-5-18:(OI)(CI)(F)",
        "/c",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return "icacls could not fully restrict the directory; review the ACL manually."
    return "Windows ACL inheritance removed; owner and Local System retain full control."


def write_newline(path: Path, content: str) -> None:
    path.write_text(content.rstrip("\n") + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", args.key_id):
        raise ValueError("key id must be a lowercase release identifier")
    output_dir = ensure_outside_repository(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    seed_path = output_dir / "ed25519-seed.hex"
    public_path = output_dir / "release-public-key.json"
    guidance_path = output_dir / "PRIVATE-KEY-PRESERVATION.md"
    if any(path.exists() for path in (seed_path, public_path, guidance_path)) and not args.force:
        raise ValueError(f"release secret files already exist under {output_dir}; use --force only to replace them")

    private_key = Ed25519PrivateKey.generate()
    seed = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(public_key).decode("ascii")
    fingerprint = hashlib.sha256(public_key).hexdigest()
    write_newline(seed_path, seed.hex())
    seed_path.chmod(0o600)
    public_path.write_text(
        json.dumps(
            {
                "algorithm": "ed25519",
                "keyId": args.key_id,
                "publicKeyBase64": public_b64,
                "publicKeySha256": fingerprint,
                "purpose": "AI Video Editor Desktop V2 lecturer release candidate artifact and catalog signatures",
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_newline(
        guidance_path,
        f"# Private release-key preservation\n\n"
        f"Key id: `{args.key_id}`\n"
        f"Public-key SHA-256: `{fingerprint}`\n\n"
        "The adjacent `ed25519-seed.hex` is the release signing root. It is intentionally outside the repository and must never be copied into source, build output, logs, shell history, handoff folders, archives, CI artifacts, or installer resources.\n\n"
        "Preserve the seed in an encrypted password-manager or hardware-backed release vault with at least one independent backup. Restrict access to the release owner and a designated backup custodian. Before every release, compare the public-key fingerprint with the committed trust-root record and record only the key id/fingerprint in the release evidence. If the seed is exposed, revoke this trust root by shipping a new public key in a reviewed shell release; do not attempt to hide or reuse a compromised seed.\n\n"
        "The generated key has no Authenticode certificate relationship. It authenticates Desktop V2 component manifests and catalogs only.\n",
    )
    acl_note = secure_acl(output_dir)
    print(json.dumps({"keyId": args.key_id, "publicKey": str(public_path), "publicKeySha256": fingerprint, "acl": acl_note}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"generate_release_key.py: error: {error}")
