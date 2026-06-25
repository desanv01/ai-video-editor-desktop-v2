from __future__ import annotations

import ast
import csv
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".venv-py314",
    "node_modules",
    "target",
    "dist",
    "__pycache__",
    ".pytest_cache",
    "pytest-cache-files-j2de5rnb",
    ".audit",
    ".codex-analysis",
    "uploads",
    "outputs",
    "tmp_img2800_review",
    "tmp_test16_forensic",
    "tmp_test7_analysis",
    "fyp_context_pack",
}

SOURCE_EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".js": "JavaScript",
    ".mjs": "JavaScript module",
    ".rs": "Rust",
    ".json": "JSON",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".css": "CSS",
    ".html": "HTML",
    ".sh": "Shell",
    ".nsh": "NSIS",
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def included(path: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts):
        return False
    if path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".pdf", ".png", ".jpg", ".jpeg", ".ico", ".exe", ".dll", ".pdb"}:
        return False
    if path.name in {"package-lock.json", "Cargo.lock"}:
        return False
    return True


def source_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and included(path)
    )


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def literal(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def python_inventory(files: list[Path]) -> dict:
    endpoints = []
    models = []
    schemas = []
    functions = []
    prompts = []
    mcp_tools = []
    config_keys = []
    parse_errors = []

    for path in files:
        if path.suffix != ".py":
            continue
        text = read(path)
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append({"path": rel(path), "error": str(exc)})
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(
                    {
                        "path": rel(path),
                        "symbol": node.name,
                        "line": node.lineno,
                        "async": isinstance(node, ast.AsyncFunctionDef),
                    }
                )
                for decorator in node.decorator_list:
                    call = decorator if isinstance(decorator, ast.Call) else None
                    target = dotted_name(call.func if call else decorator)
                    if target.startswith("router.") or target.startswith("app."):
                        method = target.split(".")[-1].upper()
                        if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                            route = literal(call.args[0]) if call and call.args else None
                            response_model = None
                            tags = None
                            for keyword in call.keywords if call else []:
                                if keyword.arg == "response_model":
                                    response_model = dotted_name(keyword.value) or repr(literal(keyword.value))
                                if keyword.arg == "tags":
                                    tags = literal(keyword.value)
                            endpoints.append(
                                {
                                    "method": method,
                                    "route": route,
                                    "path": rel(path),
                                    "line": node.lineno,
                                    "symbol": node.name,
                                    "response_model": response_model,
                                    "tags": tags,
                                }
                            )
                    if target.endswith(".tool") or target in {"mcp.tool", "server.tool"}:
                        mcp_tools.append(
                            {
                                "server": path.stem,
                                "tool": node.name,
                                "path": rel(path),
                                "line": node.lineno,
                                "doc": ast.get_docstring(node) or "",
                                "parameters": [arg.arg for arg in node.args.args],
                            }
                        )

            if isinstance(node, ast.ClassDef):
                bases = {dotted_name(base) for base in node.bases}
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        fields.append({"name": item.target.id, "line": item.lineno})
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                fields.append({"name": target.id, "line": item.lineno})
                record = {
                    "name": node.name,
                    "path": rel(path),
                    "line": node.lineno,
                    "bases": sorted(bases),
                    "fields": fields,
                }
                if "Base" in bases and rel(path).endswith("db/models.py"):
                    models.append(record)
                if any(base.endswith("BaseModel") for base in bases):
                    schemas.append(record)
                if node.name == "Settings" and rel(path).endswith("config.py"):
                    config_keys.extend(fields)

            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
                    value = node.value
                else:
                    targets = [node.target.id] if isinstance(node.target, ast.Name) else []
                    value = node.value
                for target in targets:
                    if "prompt" in target.lower() and isinstance(value, (ast.Constant, ast.JoinedStr)):
                        prompts.append(
                            {
                                "path": rel(path),
                                "symbol": target,
                                "line": node.lineno,
                            }
                        )

    return {
        "endpoints": sorted(endpoints, key=lambda x: (x["path"], x["line"])),
        "models": models,
        "schemas": schemas,
        "functions": functions,
        "prompts": prompts,
        "mcp_tools": mcp_tools,
        "config_keys": config_keys,
        "parse_errors": parse_errors,
    }


def frontend_inventory(files: list[Path]) -> dict:
    api_functions = []
    api_calls = []
    components = []
    tauri_commands = []
    for path in files:
        if path.suffix not in {".ts", ".tsx", ".rs"}:
            continue
        text = read(path)
        lines = text.splitlines()
        if path.suffix in {".ts", ".tsx"}:
            for index, line in enumerate(lines, 1):
                match = re.search(r"export\s+async\s+function\s+(\w+)", line)
                if match:
                    api_functions.append({"name": match.group(1), "path": rel(path), "line": index})
                for call in re.finditer(r"\bapi\.(\w+)\s*\(", line):
                    api_calls.append({"name": call.group(1), "path": rel(path), "line": index})
            if path.suffix == ".tsx":
                for index, line in enumerate(lines, 1):
                    match = re.search(r"(?:export\s+)?(?:default\s+)?function\s+(\w+)|const\s+(\w+)\s*=.*(?:=>|forwardRef)", line)
                    if match:
                        name = match.group(1) or match.group(2)
                        if name and name[0].isupper():
                            components.append({"name": name, "path": rel(path), "line": index})
        if path.suffix == ".rs":
            for index, line in enumerate(lines, 1):
                if "#[tauri::command]" in line:
                    for offset in range(index, min(index + 8, len(lines))):
                        match = re.search(r"(?:async\s+)?fn\s+(\w+)", lines[offset])
                        if match:
                            tauri_commands.append({"name": match.group(1), "path": rel(path), "line": offset + 1})
                            break
    return {
        "api_functions": api_functions,
        "api_calls": api_calls,
        "components": components,
        "tauri_commands": tauri_commands,
    }


def statistics(files: list[Path]) -> dict:
    by_extension = Counter()
    by_language = Counter()
    non_empty_lines = Counter()
    source_lines = 0
    frontend_files = 0
    backend_files = 0
    test_files = 0
    migration_files = 0
    for path in files:
        extension = path.suffix.lower() or "[no extension]"
        by_extension[extension] += 1
        language = SOURCE_EXTENSIONS.get(extension, "Other")
        by_language[language] += 1
        if extension in SOURCE_EXTENSIONS:
            count = sum(1 for line in read(path).splitlines() if line.strip())
            non_empty_lines[language] += count
            source_lines += count
        rp = rel(path)
        frontend_files += int(rp.startswith("desktop/src/") or rp.startswith("desktop/src-tauri/src/"))
        backend_files += int(rp.startswith("backend/app/") and "/tests/" not in rp)
        test_files += int(path.name.startswith("test_") or "/tests/" in rp)
        migration_files += int(rp.startswith("backend/app/alembic/versions/") and path.suffix == ".py")
    return {
        "files_total": len(files),
        "files_by_extension": dict(sorted(by_extension.items())),
        "files_by_language": dict(sorted(by_language.items())),
        "non_empty_lines_by_language": dict(sorted(non_empty_lines.items())),
        "approximate_non_empty_lines": source_lines,
        "frontend_files": frontend_files,
        "backend_files": backend_files,
        "test_files": test_files,
        "migration_files": migration_files,
    }


def technical_debt(files: list[Path]) -> list[dict]:
    pattern = re.compile(r"\b(TODO|FIXME|HACK|XXX|NotImplemented|placeholder|mock|temporary|hard[- ]coded)\b", re.I)
    findings = []
    for path in files:
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        for index, line in enumerate(read(path).splitlines(), 1):
            if pattern.search(line):
                findings.append({"path": rel(path), "line": index, "text": line.strip()[:300]})
    return findings


def dependencies() -> list[dict]:
    rows = []
    package_path = ROOT / "desktop" / "package.json"
    if package_path.exists():
        package = json.loads(read(package_path))
        for group in ("dependencies", "devDependencies"):
            for name, version in sorted(package.get(group, {}).items()):
                rows.append({"ecosystem": "npm", "group": group, "name": name, "version": version, "source": rel(package_path)})
    req_path = ROOT / "backend" / "requirements.txt"
    if req_path.exists():
        for line in read(req_path).splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            match = re.match(r"([^<>=~!\[]+)(.*)", clean)
            rows.append({"ecosystem": "pip", "group": "runtime", "name": match.group(1).strip(), "version": match.group(2).strip(), "source": rel(req_path)})
    cargo_path = ROOT / "desktop" / "src-tauri" / "Cargo.toml"
    if cargo_path.exists():
        group = ""
        for line in read(cargo_path).splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                group = stripped.strip("[]")
            elif group.endswith("dependencies") and "=" in stripped and not stripped.startswith("#"):
                name, version = [part.strip() for part in stripped.split("=", 1)]
                rows.append({"ecosystem": "cargo", "group": group, "name": name, "version": version, "source": rel(cargo_path)})
    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = sorted({key for row in rows for key in row}) if rows else ["value"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = source_files()
    py = python_inventory(files)
    frontend = frontend_inventory(files)
    stats = statistics(files)
    deps = dependencies()
    inventory = {
        "repository": {
            "branch": git("branch", "--show-current"),
            "head": git("rev-parse", "HEAD"),
            "head_date": git("show", "-s", "--format=%cI", "HEAD"),
            "head_subject": git("show", "-s", "--format=%s", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
        },
        "statistics": stats,
        "python": py,
        "frontend": frontend,
        "dependencies": deps,
        "technical_debt": technical_debt(files),
    }
    (OUT / "_inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (OUT / "CODE_STATISTICS.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    write_csv(
        OUT / "FILE_TYPE_STATISTICS.csv",
        [
            {
                "extension": extension,
                "file_count": count,
                "language": SOURCE_EXTENSIONS.get(extension, "Other"),
                "non_empty_lines": stats["non_empty_lines_by_language"].get(SOURCE_EXTENSIONS.get(extension, "Other"), 0),
            }
            for extension, count in stats["files_by_extension"].items()
        ],
        ["extension", "language", "file_count", "non_empty_lines"],
    )
    write_csv(OUT / "DEPENDENCY_INVENTORY.csv", deps, ["ecosystem", "group", "name", "version", "source"])
    write_csv(OUT / "_API_EXTRACT.csv", py["endpoints"], ["method", "route", "symbol", "response_model", "tags", "path", "line"])
    write_csv(OUT / "_MCP_EXTRACT.csv", py["mcp_tools"], ["server", "tool", "parameters", "path", "line", "doc"])
    write_csv(OUT / "_MODELS_EXTRACT.csv", py["models"], ["name", "path", "line", "bases", "fields"])
    write_csv(OUT / "_PROMPTS_EXTRACT.csv", py["prompts"], ["symbol", "path", "line"])
    write_csv(OUT / "_TEST_EXTRACT.csv", [f for f in py["functions"] if f["symbol"].startswith("test_")], ["symbol", "path", "line", "async"])
    write_csv(OUT / "_FRONTEND_API_EXTRACT.csv", frontend["api_functions"], ["name", "path", "line"])
    write_csv(OUT / "_FRONTEND_CALLS_EXTRACT.csv", frontend["api_calls"], ["name", "path", "line"])
    write_csv(OUT / "_TAURI_COMMANDS_EXTRACT.csv", frontend["tauri_commands"], ["name", "path", "line"])


if __name__ == "__main__":
    main()
