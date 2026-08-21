#!/usr/bin/env python3
"""Package a pinned FFmpeg/ffprobe tool component through the Phase 3 packager.

Production mode accepts only a caller-supplied local directory or archive and
requires its exact SHA-256.  It never downloads a release and never consults
PATH.  ``--test-fixture`` exercises the same staging/signing pipeline with the
small deterministic command fixtures in this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGER = ROOT / "scripts" / "desktop-v2" / "package_component.py"
FIXTURE_ROOT = ROOT / "fixtures" / "desktop-v2" / "native-tools"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source-dir", type=Path)
    source.add_argument("--source-archive", type=Path)
    source.add_argument("--test-fixture", action="store_true")
    parser.add_argument("--sha256", help="Exact SHA-256 for the local source directory fingerprint or archive.")
    parser.add_argument("--print-source-hash", action="store_true", help="Print the hash that production packaging will require.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("stable", "beta", "nightly"), default="stable")
    parser.add_argument("--minimum-shell-version", default="1.0.0")
    parser.add_argument("--repository-url", default="https://example.test/ffmpeg")
    parser.add_argument("--release-url", default="https://example.test/ffmpeg/releases")
    parser.add_argument("--artifact-url")
    parser.add_argument("--offline-local-source", action="store_true")
    parser.add_argument("--private-key-file", type=Path)
    parser.add_argument("--key-id")
    parser.add_argument("--test-signature", action="store_true", help="Use the Phase 3 non-production signing key for a real local source.")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"symlink/reparse source is not packageable: {path}")


def directory_fingerprint(root: Path) -> str:
    """Hash a source directory's names, types, sizes and bytes canonically."""

    if not root.is_dir():
        raise ValueError(f"source directory does not exist: {root}")
    digest = hashlib.sha256()
    for candidate in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        _reject_symlink(candidate)
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_dir():
            digest.update(f"D\t{relative}\n".encode("utf-8"))
        elif candidate.is_file():
            file_hash = sha256_file(candidate)
            digest.update(f"F\t{relative}\t{candidate.stat().st_size}\t{file_hash}\n".encode("utf-8"))
        else:
            raise ValueError(f"special source file is not packageable: {candidate}")
    return digest.hexdigest()


def _safe_archive_name(name: str) -> Path:
    normalized = name.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe archive member: {name}")
    if ":" in normalized or any(character in normalized for character in '<>"|?*'):
        raise ValueError(f"unsafe archive member: {name}")
    return path


def _extract_archive(archive_path: Path, destination: Path) -> Path:
    """Safely extract a tar/zip source and return the extraction root."""

    if not archive_path.is_file():
        raise ValueError(f"source archive does not exist: {archive_path}")
    destination.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                member = _safe_archive_name(info.filename)
                names.append(member.as_posix())
                if info.is_dir():
                    (destination / member).mkdir(parents=True, exist_ok=True)
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError(f"symlink archive member is not packageable: {info.filename}")
                target = destination / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    elif tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, "r:*") as archive:
            for info in archive.getmembers():
                member = _safe_archive_name(info.name)
                names.append(member.as_posix())
                if info.issym() or info.islnk() or not (info.isdir() or info.isfile()):
                    raise ValueError(f"link or special archive member is not packageable: {info.name}")
                target = destination / member
                target.parent.mkdir(parents=True, exist_ok=True)
                if info.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    stream = archive.extractfile(info)
                    if stream is None:
                        raise ValueError(f"could not read archive member: {info.name}")
                    with stream, target.open("wb") as output:
                        shutil.copyfileobj(stream, output)
    else:
        raise ValueError("source archive must be a zip or tar archive")
    top_levels = sorted({Path(name).parts[0] for name in names if name})
    if len(top_levels) == 1 and (destination / top_levels[0]).is_dir():
        return destination / top_levels[0]
    return destination


def _find_file(root: Path, names: set[str]) -> Path:
    matches = [candidate for candidate in root.rglob("*") if candidate.is_file() and candidate.name.lower() in names]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one of {sorted(names)} under {root}, found {len(matches)}")
    _reject_symlink(matches[0])
    return matches[0]


def _find_named_file(root: Path, names: set[str]) -> Path | None:
    matches = [candidate for candidate in root.rglob("*") if candidate.is_file() and candidate.name.lower() in names]
    if not matches:
        return None
    _reject_symlink(matches[0])
    return sorted(matches, key=lambda item: item.relative_to(root).as_posix())[0]


def _run_probe(tool: Path, version: str) -> dict[str, object]:
    command = [str(tool), "-version"]
    if tool.suffix.lower() in {".cmd", ".bat"}:
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/D", "/C", str(tool), "-version"]
    completed = subprocess.run(
        command,
        cwd=tool.parent,
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode != 0 or not output:
        raise ValueError(f"FFmpeg version probe failed for {tool}: exit {completed.returncode}")
    if version not in output and tool.suffix.lower() not in {".cmd", ".bat"}:
        raise ValueError(f"FFmpeg version probe for {tool} did not contain pinned version {version}")
    return {
        "path": tool.name,
        "command": [tool.name, "-version"],
        "returnCode": completed.returncode,
        "versionOutput": output.splitlines()[0][:500],
    }


def _write_fixture_source(destination: Path) -> tuple[Path, Path, Path]:
    destination.mkdir(parents=True)
    (destination / "bin").mkdir()
    (destination / "metadata").mkdir()
    (destination / "LICENSES").mkdir()
    for name in ("ffmpeg.cmd", "ffprobe.cmd", "NOTICE.txt"):
        shutil.copy2(
            FIXTURE_ROOT / name,
            destination / ("LICENSES" if name == "NOTICE.txt" else "bin") / name,
        )
    # Place deterministic placeholders with production names so the manifest
    # boundary and inventory are tested without pretending they are binaries.
    (destination / "bin" / "ffmpeg.exe").write_bytes(b"AIVE FFmpeg TEST FIXTURE PLACEHOLDER\n")
    (destination / "bin" / "ffprobe.exe").write_bytes(b"AIVE FFprobe TEST FIXTURE PLACEHOLDER\n")
    (destination / "metadata" / "source.json").write_text(
        json.dumps(
            {"source": "synthetic-fixture", "license": "fixture-only", "warning": "not a production binary"},
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination / "bin" / "ffmpeg.cmd", destination / "bin" / "ffprobe.cmd", destination / "LICENSES" / "NOTICE.txt"


def _stage_component(source_root: Path, stage: Path, version: str, fixture: bool) -> tuple[str, list[str], dict[str, object]]:
    ffmpeg_source = _find_file(source_root, {"ffmpeg.exe"})
    ffprobe_source = _find_file(source_root, {"ffprobe.exe"})
    license_source = _find_named_file(source_root, {"license", "license.txt", "notice", "notice.txt"})
    metadata_source = _find_named_file(source_root, {"source.json"})
    if license_source is None or metadata_source is None:
        raise ValueError("source must contain a license/notice file and source.json metadata")
    try:
        json.loads(metadata_source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"metadata source.json must be valid UTF-8 JSON: {metadata_source}") from exc

    (stage / "bin").mkdir(parents=True)
    (stage / "LICENSES").mkdir()
    (stage / "metadata").mkdir()
    shutil.copy2(ffmpeg_source, stage / "bin" / "ffmpeg.exe")
    shutil.copy2(ffprobe_source, stage / "bin" / "ffprobe.exe")
    shutil.copy2(license_source, stage / "LICENSES" / "NOTICE.txt")
    shutil.copy2(metadata_source, stage / "metadata" / "source.json")
    probe_tool = _find_file(source_root, {"ffmpeg.cmd"}) if fixture else ffmpeg_source
    probe_probe = _find_file(source_root, {"ffprobe.cmd"}) if fixture else ffprobe_source
    probes = {"ffmpeg": _run_probe(probe_tool, version), "ffprobe": _run_probe(probe_probe, version)}
    (stage / "metadata" / "version.txt").write_text(version + "\n", encoding="utf-8", newline="\n")
    (stage / "metadata" / "probe.json").write_text(
        json.dumps(probes, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    self_test = ["cmd.exe", "/D", "/C", "exit 0"] if fixture else ["bin/ffmpeg.exe"]
    return "bin/ffmpeg.exe", self_test, probes


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.print_source_hash:
        if args.test_fixture or (args.source_dir is None and args.source_archive is None):
            raise ValueError("--print-source-hash requires --source-dir or --source-archive")
        print(directory_fingerprint(args.source_dir.resolve()) if args.source_dir else sha256_file(args.source_archive.resolve()))
        return 0

    staging_root = output_dir / ".staging"
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True)
    try:
        temporary_root = staging_root
        if args.test_fixture:
            source_root = _write_fixture_source(temporary_root / "source")[0].parents[1]
            source_hash = directory_fingerprint(source_root)
            fixture = True
        elif args.source_dir:
            source_root = args.source_dir.resolve()
            source_hash = directory_fingerprint(source_root)
            fixture = False
        elif args.source_archive:
            archive = args.source_archive.resolve()
            source_hash = sha256_file(archive)
            source_root = _extract_archive(archive, temporary_root / "extracted")
            fixture = False
        else:
            raise ValueError("choose --source-dir, --source-archive, or --test-fixture")
        if args.sha256 and args.sha256.lower() != source_hash:
            raise ValueError(f"source SHA-256 mismatch: expected {args.sha256.lower()}, computed {source_hash}")
        if not args.test_fixture and not args.sha256:
            raise ValueError("production packaging requires --sha256 for the local source")

        stage = temporary_root / "component"
        stage.mkdir()
        entrypoint, self_test, probes = _stage_component(source_root, stage, args.version, fixture)
        (stage / "metadata" / "input-sha256.txt").write_text(source_hash + "\n", encoding="utf-8", newline="\n")
        command = [
            sys.executable,
            str(PACKAGER),
            "--component-dir",
            str(stage),
            "--output-dir",
            str(output_dir),
            "--component-id",
            "ffmpeg",
            "--component-type",
            "ffmpeg",
            "--version",
            args.version,
            "--channel",
            args.channel,
            "--minimum-shell-version",
            args.minimum_shell_version,
            "--display-name",
            "FFmpeg Native Desktop Tool Component",
            "--entrypoint",
            entrypoint,
            "--notice-file",
            "LICENSES/NOTICE.txt",
            "--license-spdx-id",
            "GPL-3.0-only",
            "--repository-url",
            args.repository_url,
            "--release-url",
            args.release_url,
            "--self-test-command",
            *self_test,
            "--capability",
            "ffmpeg",
            "--capability",
            "rendering",
        ]
        if not args.test_fixture:
            command.append("--self-test-argument=-version")
        if args.private_key_file:
            command.extend(["--private-key-file", str(args.private_key_file.resolve())])
        if args.key_id:
            command.extend(["--key-id", args.key_id])
        if args.offline_local_source:
            command.append("--offline-local-source")
        if args.test_fixture:
            command.append("--test-fixture")
        elif args.test_signature:
            command.append("--test-fixture")
        elif args.artifact_url:
            command.extend(["--artifact-url", args.artifact_url])
        subprocess.run(command, cwd=ROOT, check=True)
        print(json.dumps({"sourceSha256": source_hash, "probes": probes}, indent=2, sort_keys=True))
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"package_ffmpeg_component.py: error: {error}")
