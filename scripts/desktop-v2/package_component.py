#!/usr/bin/env python3
"""Create a deterministic Desktop V2 component fixture package.

This tool emits a tar.gz archive, exact file inventory, manifest, and detached
Ed25519 signature. The --test-fixture mode is deliberately the only mode that
uses a deterministic fixture key derived from a public label. It is not a
production signing secret. Production release automation must pass a private
key from a protected secret store and must never commit it to this repository.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import tarfile
from pathlib import Path
from typing import Iterable

Q = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, Q - 2, Q)) % Q
I = pow(2, (Q - 1) // 4, Q)
BY = (4 * pow(5, Q - 2, Q)) % Q

# NON-PRODUCTION TEST KEY ONLY. No private seed is stored in the repository;
# fixture mode derives a reproducible throwaway key from this public label.
TEST_KEY_ID = "test-fixture-2026"
TEST_KEY_LABEL = b"Desktop V2 Phase 3 NON-PRODUCTION FIXTURE KEY"


def xrecover(y: int) -> int:
    xx = ((y * y - 1) * pow(D * y * y + 1, Q - 2, Q)) % Q
    x = pow(xx, (Q + 3) // 8, Q)
    if (x * x - xx) % Q != 0:
        x = (x * I) % Q
    if x & 1:
        x = Q - x
    return x


B = (xrecover(BY), BY)


def edwards(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = q
    denom_x = pow(1 + D * x1 * x2 * y1 * y2, Q - 2, Q)
    denom_y = pow(1 - D * x1 * x2 * y1 * y2, Q - 2, Q)
    return (
        ((x1 * y2 + x2 * y1) * denom_x) % Q,
        ((y1 * y2 + x1 * x2) * denom_y) % Q,
    )


def scalarmult(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    if scalar == 0:
        return (0, 1)
    doubled = scalarmult(point, scalar // 2)
    result = edwards(doubled, doubled)
    if scalar & 1:
        result = edwards(result, point)
    return result


def encodepoint(point: tuple[int, int]) -> bytes:
    x, y = point
    return (y + ((x & 1) << 255)).to_bytes(32, "little")


def public_key(seed: bytes) -> bytes:
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return encodepoint(scalarmult(B, scalar))


def sign(seed: bytes, message: bytes) -> bytes:
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    prefix = digest[32:]
    nonce = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % L
    encoded_r = encodepoint(scalarmult(B, nonce))
    challenge = int.from_bytes(
        hashlib.sha512(encoded_r + public_key(seed) + message).digest(), "little"
    ) % L
    response = (nonce + challenge * scalar) % L
    return encoded_r + response.to_bytes(32, "little")


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(path: str) -> str:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in normalized
        or any(part in ("", ".", "..") for part in parts)
        or any(character in normalized for character in '<>:"|?*')
    ):
        raise ValueError(f"unsafe relative path: {path}")
    return normalized


def iter_source_entries(source: Path) -> Iterable[tuple[Path, str]]:
    for candidate in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        relative = safe_relative(candidate.relative_to(source).as_posix())
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode) or candidate.is_symlink():
            raise ValueError(f"symlink/reparse source is not packageable: {candidate}")
        if candidate.is_dir():
            yield candidate, relative + "/"
        elif candidate.is_file():
            yield candidate, relative
        else:
            raise ValueError(f"special source file is not packageable: {candidate}")


def add_tar_entry(archive: tarfile.TarFile, source: Path, archive_name: str) -> None:
    info = tarfile.TarInfo(archive_name)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    if source.is_dir():
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        archive.addfile(info)
    else:
        info.type = tarfile.REGTYPE
        info.mode = 0o755 if os.access(source, os.X_OK) else 0o644
        info.size = source.stat().st_size
        with source.open("rb") as stream:
            archive.addfile(info, stream)


def create_archive(source: Path, output: Path, root_directory: str) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    empty_hash = hashlib.sha256(b"").hexdigest()
    entries = list(iter_source_entries(source))
    with output.open("wb") as raw:
        import gzip

        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT
            ) as archive:
                root_info = tarfile.TarInfo(root_directory + "/")
                root_info.type = tarfile.DIRTYPE
                root_info.mode = 0o755
                root_info.mtime = 0
                root_info.uid = 0
                root_info.gid = 0
                root_info.uname = ""
                root_info.gname = ""
                archive.addfile(root_info)
                for source_path, relative in entries:
                    add_tar_entry(archive, source_path, f"{root_directory}/{relative}")
                    inventory.append(
                        {
                            "path": relative.rstrip("/"),
                            "kind": "directory"
                            if source_path.is_dir()
                            else "file",
                            "byteSize": 0
                            if source_path.is_dir()
                            else source_path.stat().st_size,
                            "sha256": empty_hash
                            if source_path.is_dir()
                            else sha256_file(source_path),
                            "executable": bool(
                                source_path.is_file() and os.access(source_path, os.X_OK)
                            ),
                        }
                    )
    return inventory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--component-id", required=True)
    parser.add_argument(
        "--component-type",
        choices=("backend", "database", "vector-store", "ffmpeg", "model", "renderer", "utility"),
        default="utility",
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--display-name", default="Synthetic Desktop V2 Component")
    parser.add_argument("--publisher", default="AI Video Editor")
    parser.add_argument(
        "--repository-url", default="https://example.test/repository"
    )
    parser.add_argument("--release-url", default="https://example.test/release")
    parser.add_argument("--artifact-url")
    parser.add_argument("--private-key-hex")
    parser.add_argument("--private-key-file", type=Path)
    parser.add_argument("--key-id")
    parser.add_argument("--test-fixture", action="store_true")
    parser.add_argument(
        "--target-os", choices=("windows", "macos", "linux"), default="windows"
    )
    parser.add_argument(
        "--target-arch", choices=("x86", "x86_64", "aarch64"), default="x86_64"
    )
    parser.add_argument("--entrypoint", default="bin/synthetic-engine.exe")
    parser.add_argument("--notice-file", default="LICENSES/NOTICE.txt")
    parser.add_argument("--self-test-command", nargs="+")
    parser.add_argument(
        "--self-test-argument",
        action="append",
        default=[],
        help="Append an argument to --self-test-command; use = form for values beginning with '-'.",
    )
    parser.add_argument(
        "--dependency", action="append", default=[], metavar="ID=CONSTRAINT"
    )
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        metavar="CAPABILITY",
        help="Manifest capability; may be repeated (defaults to api).",
    )
    return parser.parse_args()


def load_seed(args: argparse.Namespace) -> tuple[str, bytes]:
    if args.test_fixture:
        if args.private_key_hex or args.private_key_file or args.key_id:
            raise ValueError(
                "--test-fixture cannot be combined with a production key or key id"
            )
        return TEST_KEY_ID, hashlib.sha256(TEST_KEY_LABEL).digest()
    if args.private_key_hex:
        seed = bytes.fromhex(args.private_key_hex)
    elif args.private_key_file:
        seed = bytes.fromhex(args.private_key_file.read_text(encoding="ascii").strip())
    else:
        raise ValueError(
            "production packaging requires --private-key-hex or --private-key-file from a protected secret store"
        )
    if len(seed) != 32:
        raise ValueError("Ed25519 private seed must contain exactly 32 bytes")
    if not args.key_id:
        raise ValueError("production packaging requires --key-id")
    return args.key_id, seed


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", args.component_id):
        raise ValueError("component id is not a safe lowercase identifier")
    if not re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?",
        args.version,
    ):
        raise ValueError("version must be a semantic version")
    if not args.component_dir.is_dir():
        raise ValueError("component directory does not exist")
    key_id, seed = load_seed(args)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    root_directory = f"{args.component_id}-{args.version}"
    archive_path = output_dir / f"{root_directory}.tar.gz"
    inventory = create_archive(args.component_dir.resolve(), archive_path, root_directory)
    entrypoint = safe_relative(args.entrypoint)
    notice_file = safe_relative(args.notice_file)
    inventory_paths = {str(entry["path"]) for entry in inventory}
    if entrypoint not in inventory_paths or notice_file not in inventory_paths:
        raise ValueError(
            "entrypoint and notice-file must be present in the component directory"
        )
    dependencies = []
    for raw_dependency in args.dependency:
        dependency_id, separator, constraint = raw_dependency.partition("=")
        if not separator or not dependency_id or not constraint:
            raise ValueError(f"dependency must use ID=CONSTRAINT: {raw_dependency}")
        dependencies.append(
            {
                "id": safe_relative(dependency_id),
                "versionConstraint": constraint,
                "optional": False,
            }
        )
    if args.self_test_command:
        self_test_command = args.self_test_command + args.self_test_argument
    elif args.self_test_argument:
        raise ValueError("--self-test-argument requires --self-test-command")
    elif args.target_os == "windows":
        self_test_command = ["cmd.exe", "/D", "/C", "exit 0"]
    else:
        self_test_command = ["sh", "-c", "exit 0"]
    artifact_url = args.artifact_url
    if artifact_url is None:
        if args.test_fixture:
            artifact_url = archive_path.as_uri()
        else:
            raise ValueError("production packaging requires --artifact-url=https://...")
    if not (
        artifact_url.startswith("https://")
        or (
            args.test_fixture
            and artifact_url.startswith(
                ("file://", "http://localhost", "http://127.0.0.1")
            )
        )
    ):
        raise ValueError(
            "artifact URL must be HTTPS, except explicit test fixture file/localhost sources"
        )
    manifest = {
        "schemaVersion": "desktop.component-manifest.v1",
        "component": {
            "id": args.component_id,
            "type": args.component_type,
            "version": args.version,
            "channel": "stable",
        },
        "target": {
            "operatingSystems": [args.target_os],
            "architectures": [args.target_arch],
        },
        "requirements": {"minimumShellVersion": "1.0.0", "requiresElevation": False},
        "artifact": {
            "url": artifact_url,
            "byteSize": archive_path.stat().st_size,
            "sha256": sha256_file(archive_path),
        },
        "signature": {"algorithm": "ed25519", "value": "", "keyId": key_id},
        "archive": {"format": "tar.gz", "rootDirectory": root_directory},
        "install": {
            "rootKind": "program-data-components",
            "relativePath": f"{args.component_id}/{args.version}",
            "immutable": True,
            "activation": {
                "strategy": "stage-then-atomic-rename",
                "activePath": f"{args.component_id}/active",
                "stagingPath": f"{args.component_id}/.staging/{args.version}",
                "metadataPath": f"{args.component_id}/activation.json",
                "atomicCommit": True,
            },
        },
        "entrypoint": {
            "kind": "executable",
            "relativePath": entrypoint,
            "arguments": ["--self-test"],
        },
        "dependencies": dependencies,
        "capabilities": args.capability or ["api"],
        "metadata": {
            "displayName": args.display_name,
            "publisher": args.publisher,
            "license": {"spdxId": "MIT", "noticeFile": notice_file},
            "source": {
                "repositoryUrl": args.repository_url,
                "releaseUrl": args.release_url,
            },
        },
        "files": inventory,
        "selfTest": {
            "command": self_test_command,
            "timeoutMs": 5000,
            "expectedExitCode": 0,
        },
        "health": {
            "probe": "http",
            "path": "/health",
            "method": "GET",
            "timeoutMs": 1000,
            "readinessSchemaVersion": "desktop.health-readiness.v1",
            "requiresBearerToken": True,
        },
        "rollback": {
            "strategy": "retain-previous-active",
            "retentionCount": 2,
            "metadataPath": f"{args.component_id}/activation.json",
            "onActivationFailure": "rollback-automatically",
        },
    }
    payload = canonical_json(manifest)
    signature = sign(seed, payload)
    manifest["signature"]["value"] = base64.b64encode(signature).decode("ascii")
    manifest_path = output_dir / "manifest.json"
    signature_path = output_dir / "manifest.sig"
    manifest_path.write_bytes(
        json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    )
    signature_path.write_bytes(signature)
    if args.test_fixture:
        public_key_path = output_dir / "test-public-key.json"
        public_key_path.write_bytes(
            (
                json.dumps(
                    {
                        "warning": "NON-PRODUCTION TEST KEY ONLY",
                        "keyId": TEST_KEY_ID,
                        "algorithm": "ed25519",
                        "publicKeyBase64": base64.b64encode(
                            public_key(seed)
                        ).decode("ascii"),
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
        )
    print(
        json.dumps(
            {
                "archive": str(archive_path),
                "manifest": str(manifest_path),
                "signature": str(signature_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit(f"package_component.py: error: {error}")
