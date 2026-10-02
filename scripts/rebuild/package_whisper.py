#!/usr/bin/env python3
"""Package explicitly approved Whisper CPU runtime, small model and probe audio.

No acquisition, executable probes or dependency-closure claims. All inputs are
absolute paths beneath the authorized rebuild root. Deterministic ZIP bytes
assume identical approved inputs and the same Python/zlib implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import zipfile
from pathlib import Path

from build_engine import validate_output
from package_engine import digest, encode, regular
from package_tools import SEMVER, contained_input, safe_name

COMPONENT = "whisper-small"
CORE_RUNTIME = ("whisper-cli.exe", "whisper.dll", "ggml.dll", "ggml-base.dll")
CPU_BASE = "ggml-cpu-x64.dll"
VC_RUNTIME = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll")


def approved_input(path: Path, *, directory: bool = False) -> Path:
    if not path.is_absolute():
        raise ValueError(f"Input must be an absolute owned path: {path}")
    return contained_input(path, directory=directory)


def require_x64_pe(path: Path) -> None:
    size = regular(path).st_size
    if size < 64:
        raise ValueError(f"Empty/truncated runtime PE: {path}")
    with path.open("rb") as stream:
        header = stream.read(64)
        if header[:2] != b"MZ":
            raise ValueError(f"Runtime lacks MZ header: {path}")
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        if offset < 64 or offset + 26 > size:
            raise ValueError(f"Invalid runtime PE header offset: {path}")
        stream.seek(offset)
        pe = stream.read(26)
        if pe[:4] != b"PE\x00\x00" or struct.unpack_from("<H", pe, 4)[0] != 0x8664:
            raise ValueError(f"Runtime must have an AMD64 PE identity: {path}")
        if struct.unpack_from("<H", pe, 24)[0] != 0x20B:
            raise ValueError(f"Runtime must have a PE32+ optional header: {path}")


def collect_runtime(runtime: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    seen: set[str] = set()
    # Only top-level verified Release files are eligible, never other engines.
    candidates = list(CORE_RUNTIME)
    candidates += sorted(
        path.name for path in runtime.iterdir()
        if re.fullmatch(r"ggml-cpu-.+\.dll", path.name, flags=re.IGNORECASE)
    )
    if CPU_BASE not in candidates:
        raise ValueError(f"Required baseline CPU backend missing: {CPU_BASE}")
    for name in candidates:
        archive_name = safe_name("bin/" + name)
        if archive_name.casefold() in seen:
            raise ValueError(f"Case-colliding runtime file: {name}")
        seen.add(archive_name.casefold())
        path = approved_input(runtime / name)
        if path.parent != runtime:
            raise ValueError(f"Runtime input escaped verified Release root: {path}")
        require_x64_pe(path)
        files[archive_name] = path
    return files


def collect_vc_runtime(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for name in VC_RUNTIME:
        path = approved_input(root / name)
        if path.parent != root:
            raise ValueError(f"VC runtime input escaped approved flat folder: {path}")
        require_x64_pe(path)
        files[safe_name('bin/' + name)] = path
    return files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--vc-runtime-root", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--probe-audio", required=True, type=Path)
    parser.add_argument("--expected-text", required=True)
    parser.add_argument("--notice", required=True, type=Path)
    parser.add_argument("--source-metadata", required=True, type=Path)
    parser.add_argument("--dependency-inventory", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for value in (args.version, args.release_version):
        if not SEMVER.fullmatch(value) or "+" in value:
            raise ValueError(f"Expected explicit component-contract semver: {value}")
    if not 5 <= len(args.expected_text) <= 200 or not args.expected_text.strip() or any(
        ord(char) < 32 or ord(char) == 127 for char in args.expected_text
    ):
        raise ValueError("Expected probe text must be 5..200 characters without control characters")
    if not args.output_dir.is_absolute():
        raise ValueError("Output must be an absolute owned path")
    output = validate_output(args.output_dir)
    runtime = approved_input(args.runtime_root, directory=True)
    vc_root = approved_input(args.vc_runtime_root, directory=True)
    if output == runtime or output.is_relative_to(runtime) or runtime.is_relative_to(output):
        raise ValueError("Output and verified runtime root must not overlap")
    if output == vc_root or output.is_relative_to(vc_root) or vc_root.is_relative_to(output):
        raise ValueError("Output and approved VC runtime root must not overlap")
    model = approved_input(args.model)
    audio = approved_input(args.probe_audio)
    notice = approved_input(args.notice)
    metadata_path = approved_input(args.source_metadata)
    inventory_path = approved_input(args.dependency_inventory)
    for path in (model, audio, notice, metadata_path, inventory_path):
        if regular(path).st_size == 0:
            raise ValueError(f"Required approved input is empty: {path}")
        if path.is_relative_to(output):
            raise ValueError(f"Input overlaps package output: {path}")
    if model.name != "ggml-small.bin":
        raise ValueError("Selected model must be the explicit ggml-small.bin file")
    with audio.open("rb") as stream:
        wav_header = stream.read(12)
    if len(wav_header) != 12 or wav_header[:4] != b"RIFF" or wav_header[8:12] != b"WAVE":
        raise ValueError("Probe audio must be a nonempty RIFF WAV file")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict) or not metadata:
        raise ValueError("Approved source metadata must be a nonempty JSON object")
    if not isinstance(inventory, list) or not inventory or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip()
        or not isinstance(item.get("version"), str) or not item["version"].strip() for item in inventory
    ):
        raise ValueError("Approved inventory requires nonempty name/version objects")
    runtime_files = collect_runtime(runtime)
    vc_files = collect_vc_runtime(vc_root)
    if {name.casefold() for name in runtime_files} & {name.casefold() for name in vc_files}:
        raise ValueError('Whisper and Microsoft VC runtime archive files collide')
    files = dict(runtime_files)
    files.update(vc_files)
    files["models/ggml-small.bin"] = model
    files["probes/jfk.wav"] = audio
    hashes = {name: digest(path) for name, path in files.items()}
    data = {
        "NOTICE.txt": notice.read_bytes(),
        "dependency-inventory.json": encode(inventory),
        "source-identity.json": encode({"component": COMPONENT, "version": args.version,
            "releaseVersion": args.release_version, "metadata": metadata,
            "includedRuntimeInputFiles": [{"inputFile": path.name, "archivePath": name,
                "originGroup": 'whisper' if name in runtime_files else 'MicrosoftVC',
                "sizeBytes": regular(path).st_size, "sha256": hashes[name]}
                for name, path in sorted((runtime_files | vc_files).items())]}),
    }
    hashes.update({name: hashlib.sha256(value).hexdigest() for name, value in data.items()})
    data["SHA256SUMS.txt"] = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)).encode("utf-8")
    archive_name = f"{COMPONENT}-{args.version}-win32-x64.zip"
    archive = output / archive_name
    partial = output / (archive_name + ".part")
    descriptor_path = output / "whisper-small-component.json"
    for target in (archive, partial, descriptor_path):
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
                    info.external_attr = 0o100644 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info._compresslevel = 9
                    actual_hash = hashlib.sha256()
                    with pack.open(info, "w", force_zip64=True) as destination:
                        if name in data:
                            destination.write(data[name])
                            expanded += len(data[name])
                        else:
                            approved_input(files[name])
                            with files[name].open("rb") as origin:
                                for block in iter(lambda: origin.read(1024 * 1024), b""):
                                    destination.write(block)
                                    actual_hash.update(block)
                                    expanded += len(block)
                            if actual_hash.hexdigest() != hashes[name]:
                                raise ValueError(f"Source changed during packaging: {name}")
        # Publish without replacing a pre-existing/concurrent valid archive.
        os.link(partial, archive)
        partial.unlink()
        created_partial = False
    except BaseException:
        if created_partial and partial.exists():
            validate_output(partial)
            partial.unlink()
        raise
    component = {"id": COMPONENT, "version": args.version, "archive": archive_name,
        "sha256": digest(archive), "sizeBytes": regular(archive).st_size,
        "expandedBytes": expanded, "required": True,
        "entrypoints": {"whisper": "bin/whisper-cli.exe", "model": "models/ggml-small.bin", "audio": "probes/jfk.wav"},
        "probes": [{"kind": "whisper-runtime", "entrypoint": "whisper"},
            {"kind": "whisper-model", "entrypoint": "model", "runtimeEntrypoint": "whisper",
                "audioEntrypoint": "audio", "expectedText": args.expected_text}]}
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
        raise SystemExit(f"package_whisper.py: error: {error}")
