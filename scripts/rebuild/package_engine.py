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


EXTERNAL_MSVC_INPUTS = {
    "_internal/MSVCP140.dll": "7c26614e1d733892c2deac7e245ce115504b1d80592dd0a01b08e3e5a55f89ca",
    "_internal/VCRUNTIME140.dll": "d5e4d9a3e835fa679450145d6a7d94e36573a509317111904d9b3712c30d9066",
    "_internal/VCRUNTIME140_1.dll": "1f2d41c4aa5db0bc33ebf7b66d72943a817d7ce6cbe880502a9403823633093f",
    "_internal/api-ms-win-crt-conio-l1-1-0.dll": "54ee5ec719a051496ff60aa00dbeaa94b9a7d2cdac27fe9b7317f1a666b6a2aa",
    "_internal/api-ms-win-crt-convert-l1-1-0.dll": "8b94662429171019fcd63c70bbf2095a075170599704a5e7dcdbe3da13f3a429",
    "_internal/api-ms-win-crt-environment-l1-1-0.dll": "39e5929593709e8af3bc9e0a75ec1155778d6f4a247f4cdfc58928ad6db88434",
    "_internal/api-ms-win-crt-filesystem-l1-1-0.dll": "5a8ecebac32edf4e1f3c5c6c1c8ea1a1add6cda4f9c9cb26f752fb295bea6865",
    "_internal/api-ms-win-crt-heap-l1-1-0.dll": "c71080cbcb43bf1f8f3e391deb12a582eb0abefc80946f340675a2c616e4feb4",
    "_internal/api-ms-win-crt-locale-l1-1-0.dll": "6c68648e524187e03c4ad9aaa4a99113c6ee9f29fb39cc0ed93f951975138e63",
    "_internal/api-ms-win-crt-math-l1-1-0.dll": "d4fbcccbe29371cbce431e43b2eb4f7ba9a6f04a3d740a071f02457a505e9dc8",
    "_internal/api-ms-win-crt-private-l1-1-0.dll": "29bf3d90617d3781d19b332d6ceb9f20ba5ce082ec74bf6c34d5d4aee56e48a1",
    "_internal/api-ms-win-crt-process-l1-1-0.dll": "47c1935942e3ac0812e4dcf18c0e265e565f0194a3349111c299712f5565f7ac",
    "_internal/api-ms-win-crt-runtime-l1-1-0.dll": "72adc1b3677e0814d9c4ebf0964000e84bb2acf67336c8963061665e44f78029",
    "_internal/api-ms-win-crt-stdio-l1-1-0.dll": "900afc3989673c9bb1a687ed38c192f46db9e6ba6d11a668898a539e7fc23798",
    "_internal/api-ms-win-crt-string-l1-1-0.dll": "fcf12466cc12fd3b73611fc0763a5a1f9d44e90349513c34a0c83b0f36421793",
    "_internal/api-ms-win-crt-time-l1-1-0.dll": "886e57c4a6adb299b38f02945369f590a67da4e79a798359fc60aaa067212d7c",
    "_internal/api-ms-win-crt-utility-l1-1-0.dll": "5f8f26b216ade615b67a41f6fbbb910972fc6153315a65bb8f09912be50215b1",
    "_internal/numpy.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll": "a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde",
    "_internal/pyarrow.libs/msvcp140-6e7bcb4ffac2ac140bf7bcc6de529ee1.dll": "6e7bcb4ffac2ac140bf7bcc6de529ee196dc377bbdb44bbd15e96184a219444b",
    "_internal/pyarrow.libs/msvcp140_atomic_wait-4325193497a3e8a7f3eeff01c806f206.dll": "771bfb8ee58d0e9bf608c524eb5cda93a0c8e727539f8a2914de59cec155d644",
    "_internal/ucrtbase.dll": "3239227d27667ba20d10a880751924e5719de0078f9fce232d149d383f7681f6"
}
MSVC_SUPPLIER_PACKAGE_SHA256 = "843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c"

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


def select_external_msvc(files: dict[str, Path]) -> dict[str, object]:
    """Exclude only exact known inputs from a NEW ZIP; frozen onedir is untouched."""
    expected = {"bin/" + name: digest_value for name, digest_value in EXTERNAL_MSVC_INPUTS.items()}
    observed = {name for name in files if Path(name).name.casefold().endswith(".dll")
                and Path(name).name.casefold().startswith(("msvcp", "vcruntime", "concrt", "vcomp", "ucrtbase", "api-ms-win-crt-"))}
    if observed != set(expected):
        raise ValueError("Microsoft runtime namespace changed; explicit source binding required")
    for name, expected_sha256 in expected.items():
        if digest(files[name]) != expected_sha256:
            raise ValueError("Microsoft runtime input drift: " + name)
    for name in expected:
        del files[name]
    return {"schema": "aive.external-msvc.v1", "component": "aive-engine",
            "minimumWindowsMajor": 10, "packageSha256": MSVC_SUPPLIER_PACKAGE_SHA256,
            "excludedInputHashes": EXTERNAL_MSVC_INPUTS,
            "composition": "Direct original Microsoft download; private verified runtime before engine probe",
            "systemUCRT": "Windows10/11 OS UCRT; no app-local UCRT/api-ms-win-crt copies"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onedir", required=True, type=Path)
    parser.add_argument("--source-commit", required=True, help="Exact 40-character source commit SHA")
    parser.add_argument("--ci-identity", required=True, help="Actual build CI identity, supplied by main")
    parser.add_argument("--notice", required=True, type=Path)
    parser.add_argument("--source-metadata", required=True, type=Path)
    parser.add_argument("--dependency-inventory", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build" / "rebuild" / "engine-pack")
    parser.add_argument("--external-msvc-runtime", action="store_true", help="Omit exact pinned CRT copies from fresh output; supplier composition is required before use.")
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
    if args.external_msvc_runtime:
        runtime_policy = select_external_msvc(files)
        data["bin/.msvc-supplier-required.json"] = encode(runtime_policy)
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
    if args.external_msvc_runtime:
        component["requiresMsvcSupplier"] = True
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
