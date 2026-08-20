"""Native desktop runtime lifecycle and Phase 1 payload state."""

from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings
from db.database import async_session, dispose_db, engine, init_db

from .health import ENGINE_ID, ENGINE_VERSION, build_capabilities_payload, build_health_payload
from .jobs import DurableJobStore
from .paths import NativeDesktopPaths
from .tools import FFmpegProbeResult, discover_ffmpeg
from .vector_store import VectorCapability

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class NativeDesktopRuntime:
    paths: NativeDesktopPaths
    bearer_token: str
    session_id: str
    requested_port: int = 0
    assigned_port: int = 0
    requested_capabilities: list[str] = field(
        default_factory=lambda: ["api", "database", "vector-store", "ffmpeg"]
    )
    allow_tool_fixture: bool = False
    database_ready: bool = False
    database_detail: str = "SQLite database has not completed startup."
    api_ready: bool = False
    vector_capability: VectorCapability | None = None
    ffmpeg_probe: FFmpegProbeResult | None = None
    startup_error: str | None = None
    jobs: DurableJobStore | None = None
    started_at: str | None = None
    shutting_down: bool = False

    def __post_init__(self) -> None:
        if len(self.bearer_token) < 32:
            raise ValueError("Native desktop bearer token must be at least 32 characters")
        if not re.fullmatch(r"[A-Za-z0-9._~-]{32,256}", self.bearer_token):
            raise ValueError("Native desktop bearer token contains characters outside the Phase 1 contract")
        if not self.session_id:
            self.session_id = secrets.token_urlsafe(12)
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", self.session_id):
            raise ValueError("Native desktop session id contains characters outside the Phase 1 contract")
        self.paths.ensure_directories()
        self.jobs = DurableJobStore(self.paths.database)
        self.ffmpeg_probe = discover_ffmpeg(
            self.paths.ffmpeg_component,
            temp_root=self.paths.temp,
            allow_fixture=self.allow_tool_fixture,
        )
        if self.ffmpeg_probe.ffmpeg_path:
            settings.FFMPEG_BINARY_PATH = self.ffmpeg_probe.ffmpeg_path
        if self.ffmpeg_probe.ffprobe_path:
            settings.FFPROBE_BINARY_PATH = self.ffmpeg_probe.ffprobe_path

    @classmethod
    def from_settings(cls, *, requested_port: int = 0) -> "NativeDesktopRuntime":
        paths = NativeDesktopPaths.from_environment()
        token = settings.DESKTOP_BEARER_TOKEN or os.environ.get("AIVE_ENGINE_BEARER_TOKEN", "")
        session_id = settings.DESKTOP_SESSION_ID or os.environ.get("AIVE_ENGINE_SESSION_ID", "")
        return cls(
            paths=paths,
            bearer_token=token,
            session_id=session_id,
            requested_port=requested_port,
            allow_tool_fixture=os.environ.get("AIVE_NATIVE_TEST_TOOL_FIXTURE") == "1",
        )

    async def startup(self) -> None:
        logger.info("native engine startup preflight begins")
        try:
            await init_db()
            self.database_ready = True
            self.database_detail = (
                f"SQLite WAL database ready at {self.paths.database}; foreign keys and "
                "30-second busy timeout are enabled."
            )
            if self.jobs:
                recovered = self.jobs.recover_inflight()
                if recovered:
                    logger.info("recovered %s interrupted native jobs", recovered)

            # The existing RAG service is selected by the native profile at
            # import time.  Reusing its client keeps project/video APIs and
            # native vector capability reporting on the same store.
            from rag.vector_store import rag_service

            self.vector_capability = getattr(rag_service, "capability", None)
            try:
                await rag_service.ensure_collection()
            except Exception as exc:
                self.vector_capability = VectorCapability(
                    backend="embedded-vector-error",
                    state="degraded",
                    detail=f"Embedded vector collection could not be initialized: {exc}",
                    remediation_codes=("VECTOR_STORE_UNAVAILABLE",),
                )
                logger.warning("embedded vector store degraded: %s", exc)

            self.api_ready = True
            self.started_at = _now()
            logger.info(
                "native engine startup complete profile=desktop-native db=%s vector=%s ffmpeg=%s",
                self.paths.database,
                getattr(self.vector_capability, "backend", "unavailable"),
                bool(self.ffmpeg_probe and self.ffmpeg_probe.ready),
            )
        except Exception as exc:
            self.startup_error = f"Native startup failed: {exc}"
            self.database_detail = str(exc)
            logger.exception("native engine startup failed")
            raise

    async def shutdown(self) -> None:
        if self.shutting_down:
            return
        self.shutting_down = True
        self.api_ready = False
        logger.info("native engine graceful shutdown begins")
        await dispose_db()
        logger.info("native engine graceful shutdown complete")

    def health_payload(self) -> dict[str, Any]:
        return build_health_payload(
            api_ready=self.api_ready,
            database_ready=self.database_ready,
            database_detail=self.database_detail,
            vector_capability=self.vector_capability,
            ffmpeg_probe=self.ffmpeg_probe,
            startup_error=self.startup_error,
        )

    def capabilities_payload(self) -> dict[str, Any]:
        return build_capabilities_payload(
            requested=self.requested_capabilities,
            vector_capability=self.vector_capability,
            ffmpeg_probe=self.ffmpeg_probe,
            database_ready=self.database_ready,
        )

    def engine_control_payload(self, message_type: str = "ready") -> dict[str, Any]:
        assigned_port = self.assigned_port or self.requested_port or 1
        payload: dict[str, Any] = {
            "schemaVersion": "desktop.engine-control.v1",
            "messageType": message_type,
            "session": {
                "sessionId": self.session_id,
                "bearerToken": self.bearer_token,
            },
            "engine": {"id": ENGINE_ID, "version": ENGINE_VERSION},
            "process": {
                "componentId": ENGINE_ID,
                "componentVersion": ENGINE_VERSION,
                "pid": os.getpid(),
                "executablePath": os.path.abspath(os.sys.executable),
                "entrypoint": "backend/native_engine.py",
                "arguments": [],
                "startedAt": self.started_at or _now(),
            },
            "loopback": {
                "host": "127.0.0.1",
                "allocation": "dynamic",
                "requestedPort": 0,
                "assignedPort": assigned_port,
            },
            "storagePaths": self.paths.contract_storage_paths(),
            "installedComponents": [
                {
                    "id": ENGINE_ID,
                    "version": ENGINE_VERSION,
                    "path": str(self.paths.components),
                    "active": True,
                    "capabilities": ["api", "database", "vector-store", "ffmpeg"],
                }
            ],
            "requestedCapabilities": self.requested_capabilities,
            "logPath": str(self.paths.logs / "engine.log"),
            "startupDeadlineMs": 120000,
            "shutdownPolicy": {
                "mode": "graceful",
                "gracePeriodMs": 10000,
                "escalation": "terminate",
            },
        }
        if message_type == "ready":
            payload["readiness"] = {
                "schemaVersion": "desktop.health-readiness.v1",
                "endpoint": "/readiness",
                "overallState": self.health_payload()["overallState"],
            }
        return payload
