#!/usr/bin/env python3
"""Package an actual Windows onedir engine; no execution, signing or publishing.

Approved dependency inventory JSON is a nonempty list of {name, version} objects.
Approved source metadata JSON is a nonempty object. Identity is supplied explicitly,
never inferred from the local checkout. ZIP bytes are deterministic for identical
inputs and the same Python/zlib implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

from build_engine import AUTHORIZED_ROOT, ROOT, validate_output

VERSION = "2.1.0-rebuild.2"
ARCHIVE = f"aive-engine-{VERSION}-win32-x64.zip"
FORBIDDEN_PARTS = {".git", ".venv", "venv", "env", "profiles", "user-data", "userdata", "__pycache__"}
FORBIDDEN_FILES = {"credentials.json", "credentials.yaml", "secrets.json", "secrets.yaml", "id_rsa", "id_ed25519"}


def regular(path: Path) -> os.stat_result:
    for candidate in (path.absolute(), *path.absolute().parents):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Symlink/reparse input rejected: {candidate}")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Expected regular file: {path}")
    return info


def safe_name(name: str) -> str:
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or "\\" in name or ":" in name or any(
        p in ("", ".", "..") or p.endswith((".", " ")) or any(ord(c) < 32 for c in p)
        for p in parts
    ):
        raise ValueError(f"Unsafe archive path: {name}")
    return name


def digest(path: Path) -> str:
    regular(path)
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onedir", required=True, type=Path)
    parser.add_argument("--source-commit", required=True, help="Exact 40-character source commit SHA")
    parser.add_argument("--ci-identity", required=True, help="Actual build CI identity, supplied by main")
    parser.add_argument("--notice", required=True, type=Path)
    parser.add_argument("--source-metadata", required=True, type=Path)
    parser.add_argument("--dependency-inventory", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build" / "rebuild" / "engine-pack")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[a-fA-F0-9]{40}", args.source_commit):
        raise ValueError("--source-commit must be an exact 40-character commit SHA")
    if not args.ci_identity.strip() or any(ord(c) < 32 for c in args.ci_identity):
        raise ValueError("--ci-identity must be a nonempty actual build identity")
    output = validate_output(args.output_dir)
    source = args.onedir.absolute()
    # Traverse without resolving away evidence of symlinks/reparse points.
    for candidate in (source, *source.parents):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Symlink/reparse source rejected: {candidate}")
    source = source.resolve()
    if not source.is_relative_to(AUTHORIZED_ROOT) or not source.is_dir():
        raise ValueError("--onedir must be an actual directory under authorized rebuild root")
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Package output and onedir source must not overlap")
    executable = source / "aive-engine.exe"
    if regular(executable).st_size == 0:
        raise ValueError("Empty engine executable rejected")
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Engine entrypoint must be an actual Windows executable")
    internal = source / "_internal"
    if not internal.is_dir():
        raise ValueError("Complete onedir _internal tree is required")
    files: dict[str, Path] = {}
    for current, dirs, names in os.walk(source, followlinks=False):
        for name in sorted(dirs + names):
            item = Path(current) / name
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"Symlink/reparse tree entry rejected: {item}")
            relative = item.relative_to(source)
            folded = [p.casefold() for p in relative.parts]
            if any(p in FORBIDDEN_PARTS or p == ".env" or p.startswith(".env.") for p in folded) or folded[-1] in FORBIDDEN_FILES:
                raise ValueError(f"Private/development entry rejected: {relative}")
            if len(relative.parts) == 1 and name != "_internal" and name != "aive-engine.exe":
                if not stat.S_ISREG(info.st_mode) or item.suffix.lower() not in {".dll", ".pyd", ".so", ".dylib", ".manifest"}:
                    raise ValueError(f"Unrelated onedir sibling rejected: {relative}")
            if stat.S_ISDIR(info.st_mode):
                continue
            regular(item)
            archive_name = safe_name("bin/" + relative.as_posix())
            if archive_name.casefold() in {n.casefold() for n in files}:
                raise ValueError(f"Case-colliding archive entry: {archive_name}")
            files[archive_name] = item
    if not any(name.startswith("bin/_internal/") for name in files):
        raise ValueError("Empty _internal tree rejected")
    for metadata_input in (args.notice, args.source_metadata, args.dependency_inventory):
        if regular(metadata_input).st_size == 0:
            raise ValueError(f"Required approved metadata is empty: {metadata_input}")
    notice = args.notice.read_bytes()
    metadata = json.loads(args.source_metadata.read_text(encoding="utf-8-sig"))
    inventory = json.loads(args.dependency_inventory.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict) or not metadata:
        raise ValueError("Approved source metadata must be a nonempty JSON object")
    if not isinstance(inventory, list) or not inventory or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip()
        or not isinstance(item.get("version"), str) or not item["version"].strip() for item in inventory
    ):
        raise ValueError("Approved dependency inventory must be a nonempty list of name/version objects")
    for required in ("lancedb", "pyarrow"):
        if required not in {item["name"].casefold().replace("_", "-") for item in inventory}:
            raise ValueError(f"Approved dependency inventory missing {required}")
    data = {
        "NOTICE.txt": notice,
        "dependency-inventory.json": encode(inventory),
        "source-identity.json": encode({"component": "aive-engine", "version": VERSION,
            "sourceCommit": args.source_commit.lower(), "ciIdentity": args.ci_identity, "metadata": metadata}),
    }
    hashes = {name: digest(path) for name, path in files.items()}
    hashes.update({name: hashlib.sha256(value).hexdigest() for name, value in data.items()})
    data["SHA256SUMS.txt"] = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)).encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ARCHIVE
    descriptor_path = output / "engine-component.json"
    partial = output / (ARCHIVE + ".part")
    for target in (archive, descriptor_path, partial):
        validate_output(target)
        if target.exists():
            raise ValueError(f"Refusing to overwrite existing package output: {target}")
    expanded = 0
    try:
        with partial.open("xb") as raw, zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as pack:
            for name in sorted(set(files) | set(data)):
                info = zipfile.ZipInfo(safe_name(name), date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = 9
                actual_hash = hashlib.sha256()
                with pack.open(info, "w", force_zip64=True) as destination:
                    if name in data:
                        value = data[name]
                        destination.write(value)
                        expanded += len(value)
                    else:
                        regular(files[name])
                        with files[name].open("rb") as origin:
                            for block in iter(lambda: origin.read(1024 * 1024), b""):
                                destination.write(block)
                                actual_hash.update(block)
                                expanded += len(block)
                        if actual_hash.hexdigest() != hashes[name]:
                            raise ValueError(f"Source changed while packaging: {name}")
        # Windows rename refuses replacement; all destinations were checked above.
        partial.rename(archive)
    except BaseException:
        if partial.exists():
            validate_output(partial)
            partial.unlink()
        raise
    component = {"id": "aive-engine", "version": VERSION, "archive": ARCHIVE,
        "sha256": digest(archive), "sizeBytes": archive.stat().st_size,
        "expandedBytes": expanded, "required": True,
        "entrypoints": {"engine": "bin/aive-engine.exe"},
        "probes": [{"kind": "engine-self-test", "entrypoint": "engine"}]}
    descriptor = {"schemaVersion": "aive.components.v1", "releaseVersion": VERSION,
        "platform": "win32", "architecture": "x64", "components": [component]}
    with descriptor_path.open("xb") as stream:
        stream.write(encode(descriptor))
    print(json.dumps({"archive": str(archive), "descriptor": str(descriptor_path), "component": component}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        raise SystemExit(f"package_engine.py: error: {error}")
