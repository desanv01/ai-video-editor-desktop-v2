#!/usr/bin/env python3
"""Package a frozen/source native engine through the Phase 3 component packager."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGER = ROOT / "scripts" / "desktop-v2" / "package_component.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--engine-dir", type=Path, help="PyInstaller dist/aive-engine onedir output.")
    source.add_argument("--test-fixture", action="store_true", help="Build a deterministic non-production package fixture.")
    parser.add_argument("--test-signature", action="store_true", help="Use the Phase 3 non-production signing key with a real staged engine tree.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("stable", "beta", "nightly"), default="stable")
    parser.add_argument("--minimum-shell-version", default="1.0.0")
    parser.add_argument("--notice-file", type=Path)
    parser.add_argument("--source-metadata", type=Path)
    parser.add_argument("--artifact-url")
    parser.add_argument("--offline-local-source", action="store_true")
    parser.add_argument("--private-key-file", type=Path)
    parser.add_argument("--key-id")
    parser.add_argument("--repository-url", default="https://example.test/aive-engine")
    parser.add_argument("--release-url", default="https://example.test/aive-engine/releases")
    return parser.parse_args()


def _write_fixture(stage: Path, version: str) -> None:
    (stage / "bin").mkdir(parents=True)
    (stage / "LICENSES").mkdir()
    (stage / "metadata").mkdir()
    # This is deliberately not an executable.  It is only a package-manager
    # intake fixture; source and frozen-engine self-tests exercise the real
    # entrypoint separately.
    (stage / "bin" / "aive-engine.exe").write_bytes(
        b"AIVE DESKTOP V2 TEST COMPONENT PLACEHOLDER\n"
    )
    (stage / "LICENSES" / "NOTICE.txt").write_text(
        "NON-PRODUCTION Desktop V2 component fixture.\n", encoding="utf-8", newline="\n"
    )
    (stage / "metadata" / "source.json").write_text(
        json.dumps(
            {
                "source": "synthetic-fixture",
                "version": version,
                "warning": "not a production engine binary",
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _copy_engine_tree(engine_dir: Path, stage: Path, notice_file: Path, source_metadata: Path) -> None:
    if not engine_dir.is_dir():
        raise ValueError(f"--engine-dir does not exist: {engine_dir}")
    executable_names = ("aive-engine.exe", "aive-engine")
    if not any((engine_dir / name).is_file() for name in executable_names):
        raise ValueError("--engine-dir must be a PyInstaller onedir directory containing aive-engine(.exe)")
    bin_dir = stage / "bin"
    shutil.copytree(engine_dir, bin_dir, symlinks=False)
    if not (bin_dir / "aive-engine.exe").is_file() and not (bin_dir / "aive-engine").is_file():
        raise ValueError("copied engine tree did not contain its entrypoint")
    (stage / "LICENSES").mkdir()
    (stage / "metadata").mkdir()
    shutil.copy2(notice_file, stage / "LICENSES" / "NOTICE.txt")
    shutil.copy2(source_metadata, stage / "metadata" / "source.json")


def main() -> int:
    args = parse_args()
    if not args.test_fixture and args.engine_dir is None:
        raise ValueError("choose --engine-dir or --test-fixture")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    staging_root = output_dir / ".staging"
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True)
    stage = staging_root / "component"
    stage.mkdir()
    try:
        if args.test_fixture:
            _write_fixture(stage, args.version)
            self_test = ["cmd.exe", "/D", "/C", "exit 0"]
        else:
            if args.notice_file is None or args.source_metadata is None:
                raise ValueError("production packaging requires --notice-file and --source-metadata")
            _copy_engine_tree(
                args.engine_dir.resolve(),
                stage,
                args.notice_file.resolve(),
                args.source_metadata.resolve(),
            )
            self_test = ["bin/aive-engine.exe"]

        executable = "bin/aive-engine.exe" if not args.test_fixture else "bin/aive-engine.exe"
        command = [
            sys.executable,
            str(PACKAGER),
            "--component-dir",
            str(stage),
            "--output-dir",
            str(output_dir),
            "--component-id",
            "aive-engine",
            "--component-type",
            "backend",
            "--version",
            args.version,
            "--channel",
            args.channel,
            "--minimum-shell-version",
            args.minimum_shell_version,
            "--display-name",
            "AI Video Editor Native Core Engine",
            "--entrypoint",
            executable,
            "--notice-file",
            "LICENSES/NOTICE.txt",
            "--repository-url",
            args.repository_url,
            "--release-url",
            args.release_url,
            "--self-test-command",
            *self_test,
            "--capability",
            "api",
            "--capability",
            "database",
            "--capability",
            "vector-store",
            "--capability",
            "ffmpeg",
            "--capability",
            "rendering",
        ]
        if args.private_key_file:
            command.extend(["--private-key-file", str(args.private_key_file.resolve())])
        if args.key_id:
            command.extend(["--key-id", args.key_id])
        if args.offline_local_source:
            command.append("--offline-local-source")
        if not args.test_fixture:
            command.extend(["--self-test-argument=--self-test"])
        if args.test_fixture:
            command.append("--test-fixture")
        elif args.test_signature:
            command.append("--test-fixture")
        elif args.artifact_url:
            command.extend(["--artifact-url", args.artifact_url])
        subprocess.run(command, cwd=ROOT, check=True)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"package_native_engine.py: error: {error}")
