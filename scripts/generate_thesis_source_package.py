"""Generate the sanitised source archive and reproducibility manifest for the FYP thesis."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "thesis_source_package"
ARCHIVE_NAME = "AIVE_FYP_Source_Code_v1.0.zip"

CODE_EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "React TypeScript",
    ".js": "JavaScript",
    ".mjs": "JavaScript module",
    ".rs": "Rust",
    ".css": "CSS",
    ".html": "HTML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".ps1": "PowerShell",
}

INCLUDE_ROOTS = (
    "backend/app",
    "backend/tests",
    "backend/revideo",
    "desktop/src",
    "desktop/src-tauri/src",
    "desktop/src-tauri/nsis",
    "desktop/revideo",
    "scripts",
)

INCLUDE_FILES = (
    ".env.example",
    ".gitignore",
    "README.md",
    "check_renderer.py",
    "docker-compose.yml",
    "docker-compose.desktop.yml",
    "backend/Dockerfile",
    "backend/alembic.ini",
    "backend/entrypoint.sh",
    "backend/requirements.txt",
    "desktop/package.json",
    "desktop/package-lock.json",
    "desktop/index.html",
    "desktop/postcss.config.js",
    "desktop/tailwind.config.js",
    "desktop/tsconfig.json",
    "desktop/tsconfig.node.json",
    "desktop/vite.config.ts",
    "desktop/src-tauri/Cargo.toml",
    "desktop/src-tauri/Cargo.lock",
    "desktop/src-tauri/build.rs",
    "desktop/src-tauri/tauri.conf.json",
    "desktop/src-tauri/tauri.bundle.override.json",
    "docs/reproducibility/REPRODUCIBILITY_GUIDE.md",
    "docs/reproducibility/VERIFICATION_RESULTS.md",
)

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".venv-py314",
    "node_modules",
    "target",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    "gen",
    "icons",
    "uploads",
    "outputs",
    "output",
    "tmp",
    ".audit",
    ".codex-analysis",
}

EXCLUDED_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".wav",
    ".mp3",
    ".db",
    ".sqlite",
    ".log",
    ".pyc",
}

SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(rb"(?im)^(?:OPENAI|DEEPSEEK|MISTRAL|ALIBABA|DASHSCOPE)_API_KEY\s*=\s*[^\s#][^\r\n]+"),
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def should_include(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS or part.startswith("tmp_") for part in relative.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name in {".env", ".env.local", "runtime-render-plan.json"}:
        return False
    if "output" in path.stem.lower() and path.suffix.lower() in {".json", ".csv"}:
        return False
    return path.is_file()


def source_files() -> list[Path]:
    selected: set[Path] = set()
    for root_name in INCLUDE_ROOTS:
        root = ROOT / root_name
        if root.exists():
            selected.update(path for path in root.rglob("*") if should_include(path))
    for filename in INCLUDE_FILES:
        path = ROOT / filename
        if path.exists() and should_include(path):
            selected.add(path)
    return sorted(selected, key=lambda path: path.relative_to(ROOT).as_posix().lower())


def text_statistics(data: bytes) -> tuple[int, int]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return len(lines), sum(1 for line in lines if line.strip())


def category(relative: str) -> str:
    if relative.startswith("backend/tests/"):
        return "automated_test"
    if relative.startswith("scripts/") or relative == "check_renderer.py":
        return "utility_script"
    if relative.startswith(("backend/app/", "backend/revideo/", "desktop/src/", "desktop/src-tauri/src/", "desktop/revideo/")):
        return "core_source"
    if relative.startswith("docs/") or relative.endswith("README.md"):
        return "documentation"
    return "configuration"


def language(path: Path) -> str:
    if path.name == "Dockerfile":
        return "Dockerfile"
    if path.suffix.lower() in CODE_EXTENSIONS:
        return CODE_EXTENSIONS[path.suffix.lower()]
    if path.suffix.lower() in {".yml", ".yaml"}:
        return "YAML"
    if path.suffix.lower() == ".toml":
        return "TOML"
    if path.suffix.lower() == ".json":
        return "JSON"
    if path.suffix.lower() == ".md":
        return "Markdown"
    return path.suffix.lower().lstrip(".") or "text"


def assert_no_secrets(path: Path, data: bytes) -> None:
    relative = path.relative_to(ROOT).as_posix()
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise RuntimeError(f"Potential credential detected; source package aborted: {relative}")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = source_files()
    rows: list[dict[str, object]] = []
    totals_by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "physical_lines": 0, "nonblank_lines": 0, "bytes": 0})
    totals_by_language: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "physical_lines": 0, "nonblank_lines": 0, "bytes": 0})

    for path in files:
        data = path.read_bytes()
        assert_no_secrets(path, data)
        relative = path.relative_to(ROOT).as_posix()
        physical, nonblank = text_statistics(data)
        item = {
            "path": relative,
            "category": category(relative),
            "language": language(path),
            "physical_lines": physical,
            "nonblank_lines": nonblank,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        rows.append(item)
        for totals, key in ((totals_by_category, str(item["category"])), (totals_by_language, str(item["language"]))):
            totals[key]["files"] += 1
            totals[key]["physical_lines"] += physical
            totals[key]["nonblank_lines"] += nonblank
            totals[key]["bytes"] += len(data)

    manifest_path = OUTPUT / "SOURCE_MANIFEST.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    status = git("status", "--porcelain")
    summary = {
        "project": "AI-Agent Assisted Video Editing Framework",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git("rev-parse", "HEAD"),
        "git_commit_short": git("rev-parse", "--short", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "git_tags_at_commit": [tag for tag in git("tag", "--points-at", "HEAD").splitlines() if tag],
        "working_tree_clean": not bool(status),
        "counting_method": "Physical and nonblank UTF-8 text lines over the sanitised package include set; dependencies, generated outputs, credentials, media, caches and temporary analysis are excluded.",
        "totals": {
            "files": len(rows),
            "physical_lines": sum(int(row["physical_lines"]) for row in rows),
            "nonblank_lines": sum(int(row["nonblank_lines"]) for row in rows),
            "bytes": sum(int(row["bytes"]) for row in rows),
        },
        "by_category": dict(sorted(totals_by_category.items())),
        "by_language": dict(sorted(totals_by_language.items())),
    }
    summary_path = OUTPUT / "SOURCE_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    archive_path = OUTPUT / ARCHIVE_NAME
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, arcname=f"ai-video-editor/{path.relative_to(ROOT).as_posix()}")
        archive.write(manifest_path, arcname="ai-video-editor/SOURCE_MANIFEST.csv")
        archive.write(summary_path, arcname="ai-video-editor/SOURCE_SUMMARY.json")

    checksum_path = OUTPUT / "CHECKSUMS.sha256"
    checksum_path.write_text(
        f"{hashlib.sha256(archive_path.read_bytes()).hexdigest()}  {archive_path.name}\n",
        encoding="ascii",
    )
    print(json.dumps(summary, indent=2))
    print(f"Archive: {archive_path}")
    print(f"Checksums: {checksum_path}")


if __name__ == "__main__":
    main()
