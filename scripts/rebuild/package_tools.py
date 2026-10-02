#!/usr/bin/env python3
"""Stream approved complete tool runtimes into deterministic managed ZIPs.

No downloads, execution, signing or functional-readiness claims. Every input is
explicit and contained under AIVE_REBUILD_ROOT (or its exact local default).
Dependency inventory is a nonempty JSON list of name/version objects; source
metadata is an approved nonempty object. Reproducible ZIP bytes assume identical
inputs and the same Python/zlib implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import zipfile
from pathlib import Path

from build_engine import AUTHORIZED_ROOT, validate_output
from package_engine import FORBIDDEN_FILES, FORBIDDEN_PARTS, digest, encode, regular

SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
RESERVED = {"notice.txt", "source-identity.json", "dependency-inventory.json", "sha256sums.txt"}


DOCUMENT_STDLIB_VENV = ('program', 'python-core-3.12.14', 'lib', 'venv')


def document_private_relative(relative: Path) -> Path:
    # Preserve this exact upstream stdlib module, never an actual environment.
    parts = relative.parts
    if parts[:len(DOCUMENT_STDLIB_VENV)] == DOCUMENT_STDLIB_VENV:
        tail = parts[len(DOCUMENT_STDLIB_VENV):]
        allowed = (
            not tail
            or tail in (('__init__.py',), ('__main__.py',), ('__pycache__',))
            or (len(tail) == 2 and tail[0] == '__pycache__' and re.fullmatch(
                r'__(?:init|main)__\.cpython-[0-9]+(?:\.opt-[0-9]+)?\.pyc', tail[1]
            ) is not None)
        )
        if not allowed:
            raise ValueError(f"Unexpected entry in approved stock stdlib venv module: {relative}")
        # Cache files still require the existing regular sibling-source check.
        return Path(*parts[:3], *parts[4:])
    return relative


def contained_input(
    path: Path, *, directory: bool = False, document_cache: bool = False,
    documents_source_root: Path | None = None,
) -> Path:
    selected = path.absolute()
    validate_output(selected)
    if directory:
        for candidate in (selected, *selected.parents):
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"Symlink/reparse input rejected: {candidate}")
        if not selected.is_dir():
            raise ValueError(f"Expected source directory: {selected}")
    else:
        regular(selected)
    resolved = selected.resolve()
    if not resolved.is_relative_to(AUTHORIZED_ROOT):
        raise ValueError(f"Input outside authorized rebuild root: {selected}")
    relative = resolved.relative_to(AUTHORIZED_ROOT)
    if documents_source_root is not None:
        approved_source = contained_input(documents_source_root, directory=True)
        if not resolved.is_relative_to(approved_source):
            raise ValueError(f"Document payload escaped approved source root: {selected}")
        runtime_relative = document_private_relative(resolved.relative_to(approved_source))
        relative = Path(*approved_source.relative_to(AUTHORIZED_ROOT).parts, *runtime_relative.parts)
    if document_cache:
        # Only documents collection opts in; retain every other private guard.
        relative = Path(*(part for part in relative.parts if part.casefold() != '__pycache__'))
    reject_private(relative)
    return resolved


def safe_name(name: str) -> str:
    parts = name.split("/")
    if not parts or any(
        not part or part in (".", "..") or part.endswith((".", " "))
        or ":" in part or "\\" in part or any(ord(char) < 32 for char in part)
        for part in parts
    ):
        raise ValueError(f"Unsafe archive path: {name}")
    return name


def reject_private(relative: Path) -> None:
    parts = [part.casefold() for part in relative.parts]
    if any(part in FORBIDDEN_PARTS or part == ".env" or part.startswith(".env.") for part in parts) or parts[-1] in FORBIDDEN_FILES:
        raise ValueError(f"Private/development entry rejected: {relative}")


def require_pe(path: Path) -> None:
    size = regular(path).st_size
    if size < 64:
        raise ValueError(f"Missing/empty Windows PE entrypoint: {path}")
    with path.open("rb") as stream:
        header = stream.read(64)
        if header[:2] != b"MZ":
            raise ValueError(f"Entrypoint lacks MZ header: {path}")
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        if offset < 64 or offset + 4 > size:
            raise ValueError(f"Invalid PE header offset: {path}")
        stream.seek(offset)
        if stream.read(4) != b"PE\x00\x00":
            raise ValueError(f"Entrypoint lacks PE signature: {path}")


def collect_payload(component: str, source: Path) -> tuple[dict[str, Path], list[str], list[str]]:
    if component == "ffmpeg":
        files = {name: contained_input(source / name) for name in ("bin/ffmpeg.exe", "bin/ffprobe.exe")}
        for path in files.values():
            require_pe(path)
        return files, [], []
    require_pe(contained_input(source / "program" / "soffice.com"))
    require_pe(contained_input(source / "program" / "soffice.exe"))
    files: dict[str, Path] = {}
    excluded: list[str] = []
    generated_caches: list[str] = []
    seen: set[str] = set()

    def fail_walk(error: OSError) -> None:
        raise error

    for current, dirs, names in os.walk(source, followlinks=False, onerror=fail_walk):
        for name in sorted(dirs + names):
            path = Path(current) / name
            relative = path.relative_to(source)
            archive_name = safe_name(relative.as_posix())
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"Symlink/reparse tree entry rejected: {path}")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError(f"Nonregular runtime entry rejected: {path}")
            private_relative = document_private_relative(relative)
            cache_parts = [part for part in relative.parts if part.casefold() == '__pycache__']
            if cache_parts:
                private_relative = Path(*(part for part in private_relative.parts if part.casefold() != '__pycache__'))
                if private_relative.parts:
                    reject_private(private_relative)
            else:
                reject_private(private_relative)
            folded = archive_name.casefold()
            if folded in seen or folded in RESERVED:
                raise ValueError(f"Case-colliding/reserved archive entry: {archive_name}")
            seen.add(folded)
            if cache_parts:
                if len(cache_parts) != 1:
                    raise ValueError(f"Nested generated cache entry rejected: {relative}")
                if stat.S_ISDIR(info.st_mode):
                    if path.name.casefold() != '__pycache__':
                        raise ValueError(f"Unexpected directory inside Python cache: {relative}")
                    # All child entries still undergo safe-path/regular/reparse checks.
                    continue
                if path.parent.name.casefold() != '__pycache__':
                    raise ValueError(f"Unexpected nested Python cache file: {relative}")
                match = re.fullmatch(r'(.+)\.cpython-[0-9]+(?:\.opt-[0-9]+)?\.pyc', path.name)
                if match is None:
                    raise ValueError(f"Unrecognized generated Python cache: {relative}")
                sibling_source = path.parent.parent / (match.group(1) + '.py')
                contained_input(sibling_source, documents_source_root=source)
                contained_input(path, document_cache=True, documents_source_root=source)
                generated_caches.append(archive_name)
                continue
            if stat.S_ISDIR(info.st_mode):
                continue
            contained_input(path, documents_source_root=source)
            if len(relative.parts) == 1 and path.suffix.casefold() == ".msi":
                excluded.append(archive_name)
                continue
            files[archive_name] = path
    return files, sorted(excluded), sorted(generated_caches)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", required=True, choices=("ffmpeg", "documents"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--notice", required=True, type=Path)
    parser.add_argument("--source-metadata", required=True, type=Path)
    parser.add_argument("--dependency-inventory", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for value in (args.version, args.release_version):
        if not SEMVER.fullmatch(value):
            raise ValueError(f"Expected explicit component/release semver: {value}")
    source = contained_input(args.source_root, directory=True)
    output = validate_output(args.output_dir)
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Source and package output must not overlap")
    notice_path = contained_input(args.notice)
    metadata_path = contained_input(args.source_metadata)
    inventory_path = contained_input(args.dependency_inventory)
    for path in (notice_path, metadata_path, inventory_path):
        if regular(path).st_size == 0:
            raise ValueError(f"Required approved input is empty: {path}")
        if path.is_relative_to(output):
            raise ValueError(f"Approved input overlaps package output: {path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict) or not metadata:
        raise ValueError("Approved source metadata must be a nonempty JSON object")
    if not isinstance(inventory, list) or not inventory or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip()
        or not isinstance(item.get("version"), str) or not item["version"].strip() for item in inventory
    ):
        raise ValueError("Approved dependency inventory requires nonempty name/version objects")
    files, excluded, generated_caches = collect_payload(args.component, source)
    data = {
        "NOTICE.txt": notice_path.read_bytes(),
        "dependency-inventory.json": encode(inventory),
        "source-identity.json": encode({"component": args.component, "version": args.version,
            "releaseVersion": args.release_version, "metadata": metadata,
            "excludedTopLevelMsi": excluded,
            "excludedGeneratedPythonCaches": generated_caches}),
    }
    hashes = {name: digest(path) for name, path in files.items()}
    hashes.update({name: hashlib.sha256(value).hexdigest() for name, value in data.items()})
    data["SHA256SUMS.txt"] = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)).encode("utf-8")
    archive_name = f"{args.component}-{args.version}-win32-x64.zip"
    archive = output / archive_name
    descriptor_path = output / f"{args.component}-component.json"
    partial = output / (archive_name + ".part")
    for target in (archive, descriptor_path, partial):
        validate_output(target)
        if target.exists():
            raise ValueError(f"Refusing existing output: {target}")
    output.mkdir(parents=True, exist_ok=True)
    expanded = 0
    created_partial = False
    try:
        with partial.open("xb") as raw:
            created_partial = True
            with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as pack:
                for name in sorted(set(files) | set(data)):
                    info = zipfile.ZipInfo(safe_name(name), date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info._compresslevel = 9
                    actual_hash = hashlib.sha256()
                    with pack.open(info, "w", force_zip64=True) as destination:
                        if name in data:
                            destination.write(data[name])
                            expanded += len(data[name])
                        else:
                            contained_input(
                                files[name], documents_source_root=source if args.component == "documents" else None
                            )
                            with files[name].open("rb") as origin:
                                for block in iter(lambda: origin.read(1024 * 1024), b""):
                                    destination.write(block)
                                    actual_hash.update(block)
                                    expanded += len(block)
                            if actual_hash.hexdigest() != hashes[name]:
                                raise ValueError(f"Source changed during packaging: {name}")
        # Publish without replacing any concurrent/existing archive on any OS.
        os.link(partial, archive)
        partial.unlink()
        created_partial = False
    except BaseException:
        if created_partial and partial.exists():
            validate_output(partial)
            partial.unlink()
        raise
    if args.component == "ffmpeg":
        entrypoints = {"ffmpeg": "bin/ffmpeg.exe", "ffprobe": "bin/ffprobe.exe"}
        probes = [{"kind": "ffmpeg-version", "entrypoint": "ffmpeg"},
            {"kind": "ffprobe-version", "entrypoint": "ffprobe"},
            {"kind": "filter-codec-check", "entrypoint": "ffmpeg"}]
    else:
        entrypoints = {"libreoffice": "program/soffice.com"}
        probes = [{"kind": "document-tool-version", "entrypoint": "libreoffice"}]
    component = {"id": args.component, "version": args.version, "archive": archive_name,
        "sha256": digest(archive), "sizeBytes": regular(archive).st_size,
        "expandedBytes": expanded, "required": True, "entrypoints": entrypoints, "probes": probes}
    descriptor = {"schemaVersion": "aive.components.v1", "releaseVersion": args.release_version,
        "platform": "win32", "architecture": "x64", "components": [component]}
    with descriptor_path.open("xb") as stream:
        stream.write(encode(descriptor))
    print(json.dumps({"archive": str(archive), "descriptor": str(descriptor_path), "component": component}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        raise SystemExit(f"package_tools.py: error: {error}")
