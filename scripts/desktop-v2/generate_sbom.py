#!/usr/bin/env python3
"""Generate a deterministic file-level SBOM and SHA-256 inventory for a handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    return parser.parse_args()


def file_record(root: Path, path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": size,
        "sha256": digest.hexdigest(),
    }


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"SBOM root does not exist: {root}")
    files = [path for path in root.rglob("*") if path.is_file() and path.resolve() != args.output.resolve()]
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:aive:desktop-v2:{args.version}",
        "version": 1,
        "metadata": {"component": {"name": "AI Video Editor Desktop V2 handoff", "version": args.version}},
        "components": [
            {"type": "file", "name": record["path"], "hashes": [{"alg": "SHA-256", "content": record["sha256"]}], "properties": [{"name": "bytes", "value": str(record["bytes"])}]}
            for record in sorted((file_record(root, path) for path in files), key=lambda item: str(item["path"]))
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(args.output.resolve()), "files": len(files), "version": args.version}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
