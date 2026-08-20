"""Explicit, isolated native desktop storage paths.

The native engine does not guess a writable location from the current working
directory and does not use the shell's Program Files directory.  A data root
must be supplied by the launcher/CLI; every derived path is reported so the
Phase 5 supervisor can later pass the same contract without owning storage
policy in the backend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class NativePathError(ValueError):
    """Raised when a native runtime path violates the write boundary."""


def _normal(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _same_or_child(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _program_files_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "ProgramFiles"):
        value = os.environ.get(name)
        if value:
            roots.append(_normal(value))
    # This catches a test/portable environment that has not exported the
    # Windows variables while still allowing ordinary folders named "program".
    if os.name == "nt":
        roots.extend((_normal(r"C:\Program Files"), _normal(r"C:\Program Files (x86)")))
    return tuple(dict.fromkeys(roots))


def reject_program_files(path: Path, *, label: str) -> None:
    candidate = _normal(path)
    if any(part.casefold() in {"program files", "program files (x86)"} for part in candidate.parts):
        raise NativePathError(
            f"{label} cannot be under a Program Files directory: {candidate}"
        )
    for program_files in _program_files_roots():
        if _same_or_child(candidate, program_files):
            raise NativePathError(
                f"{label} cannot be under Program Files; native runtime data must be writable "
                f"by the user: {candidate}"
            )


def _env_path(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


@dataclass(frozen=True)
class NativeDesktopPaths:
    """Resolved native runtime paths; all are explicit in the report."""

    data_root: Path
    database: Path
    vector_root: Path
    uploads: Path
    proxies: Path
    temp: Path
    logs: Path
    config: Path
    backups: Path
    models: Path
    projects: Path
    exports: Path
    components: Path
    ffmpeg_component: Path

    @classmethod
    def from_environment(
        cls,
        *,
        data_root: str | os.PathLike[str] | None = None,
        overrides: dict[str, str | os.PathLike[str] | None] | None = None,
    ) -> "NativeDesktopPaths":
        values = overrides or {}
        root_value = data_root or values.get("data_root") or _env_path(
            "AIVE_DESKTOP_DATA_ROOT", "DESKTOP_DATA_ROOT"
        )
        if not root_value:
            raise NativePathError(
                "AIVE_DESKTOP_DATA_ROOT (or --data-root) is required for the native profile"
            )
        root = _normal(root_value)
        reject_program_files(root, label="Native desktop data root")

        def choose(key: str, *env_names: str, default: Path) -> Path:
            raw = values.get(key) or _env_path(*env_names)
            path = _normal(raw or default)
            reject_program_files(path, label=f"Native desktop {key} path")
            return path

        paths = cls(
            data_root=root,
            database=choose(
                "database",
                "AIVE_DESKTOP_DB_PATH",
                "DESKTOP_DB_PATH",
                default=root / "Config" / "engine.sqlite3",
            ),
            vector_root=choose(
                "vector_root",
                "AIVE_DESKTOP_VECTOR_ROOT",
                "DESKTOP_VECTOR_ROOT",
                default=root / "VectorStore",
            ),
            uploads=choose(
                "uploads",
                "AIVE_DESKTOP_UPLOADS_PATH",
                "UPLOAD_PATH",
                default=root / "Uploads",
            ),
            proxies=choose(
                "proxies",
                "AIVE_DESKTOP_PROXIES_PATH",
                "PROXY_STORAGE_PATH",
                default=root / "Proxies",
            ),
            temp=choose(
                "temp",
                "AIVE_DESKTOP_TEMP_PATH",
                "TEMP_PATH",
                default=root / "Temp",
            ),
            logs=choose(
                "logs",
                "AIVE_DESKTOP_LOGS_PATH",
                "LOG_PATH",
                default=root / "Logs",
            ),
            config=choose(
                "config",
                "AIVE_DESKTOP_CONFIG_PATH",
                "CONFIG_PATH",
                default=root / "Config",
            ),
            backups=choose(
                "backups",
                "AIVE_DESKTOP_BACKUPS_PATH",
                "BACKUP_PATH",
                default=root / "Backups",
            ),
            models=choose(
                "models",
                "AIVE_DESKTOP_MODELS_PATH",
                "MODEL_STORAGE_PATH",
                default=root / "Models",
            ),
            projects=choose(
                "projects",
                "AIVE_DESKTOP_PROJECTS_PATH",
                "PROJECTS_PATH",
                default=root / "Projects",
            ),
            exports=choose(
                "exports",
                "AIVE_DESKTOP_EXPORTS_PATH",
                "EXPORTS_PATH",
                default=root / "Exports",
            ),
            components=choose(
                "components",
                "AIVE_DESKTOP_COMPONENT_ROOT",
                "DESKTOP_COMPONENT_ROOT",
                default=root / "Components",
            ),
            ffmpeg_component=choose(
                "ffmpeg_component",
                "AIVE_FFMPEG_COMPONENT_ROOT",
                "FFMPEG_COMPONENT_ROOT",
                default=root / "Components" / "ffmpeg",
            ),
        )
        if paths.database.exists() and paths.database.is_dir():
            raise NativePathError(f"Native desktop database path is a directory: {paths.database}")
        return paths

    def ensure_directories(self) -> None:
        """Create only user-writable runtime directories."""
        for path in (
            self.data_root,
            self.vector_root,
            self.uploads,
            self.proxies,
            self.temp,
            self.logs,
            self.config,
            self.backups,
            self.models,
            self.projects,
            self.exports,
            self.components,
            self.ffmpeg_component,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.database.parent.mkdir(parents=True, exist_ok=True)

    def settings_environment(self) -> dict[str, str]:
        """Return the legacy settings values used by compatibility routes."""
        return {
            "APP_STORAGE_ROOT": str(self.data_root),
            "VIDEO_STORAGE_PATH": str(self.exports),
            "UPLOAD_PATH": str(self.uploads),
            "TEMP_PATH": str(self.temp),
            "LOG_PATH": str(self.logs),
            "CONFIG_PATH": str(self.config),
            "BACKUP_PATH": str(self.backups),
            "PROXY_STORAGE_PATH": str(self.proxies),
            "MODEL_STORAGE_PATH": str(self.models),
            "LOCAL_MODEL_STORAGE_PATH": str(self.models),
            "STAGING_UPLOAD_PATH": str(self.uploads / "staging" / "native-imports"),
            "IMPORT_MANIFEST_PATH": str(
                self.uploads / "staging" / "native-imports" / "manifests"
            ),
            "ORPHAN_UPLOAD_PATH": str(self.uploads / "orphaned-imports"),
            "DESKTOP_DB_PATH": str(self.database),
            "DESKTOP_VECTOR_ROOT": str(self.vector_root),
            "DESKTOP_COMPONENT_ROOT": str(self.components),
            "FFMPEG_COMPONENT_ROOT": str(self.ffmpeg_component),
        }

    def contract_storage_paths(self, *, shell_root: str = "native-shell") -> dict[str, object]:
        """Build the Phase 1 engine-control storagePaths object."""
        return {
            "layoutVersion": "desktop.storage-layout.v1",
            "shellInstallRoot": shell_root,
            "sharedComponentsRoot": str(self.components),
            "activationMetadataRoot": str(self.components / "Activation"),
            "downloadStagingRoot": str(self.components / "Downloads" / "Staging"),
            "userConfigRoot": str(self.config),
            "userCacheRoot": str(self.temp),
            "userLogsRoot": str(self.logs),
            "userStateRoot": str(self.config / "State"),
            "projectsRoot": str(self.projects),
            "exportsRoot": str(self.exports),
            "programFilesRuntimeWritable": False,
        }

    def capability_paths(self) -> dict[str, str]:
        return {
            "database": str(self.database),
            "vectorStore": str(self.vector_root),
            "uploads": str(self.uploads),
            "proxies": str(self.proxies),
            "temp": str(self.temp),
            "logs": str(self.logs),
            "config": str(self.config),
            "backups": str(self.backups),
            "models": str(self.models),
            "projects": str(self.projects),
            "exports": str(self.exports),
            "components": str(self.components),
            "ffmpegComponent": str(self.ffmpeg_component),
        }
