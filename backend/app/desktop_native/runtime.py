"""Native desktop runtime lifecycle and Phase 1 payload state."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import settings
from db.database import dispose_db, init_db

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
        default_factory=lambda: ["api", "database", "vector-store", "ffmpeg", "native-import"]
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
    _rag_service: Any = field(default=None, init=False, repr=False)
    model_store: Any = field(default=None, init=False, repr=False)
    model_state: dict[str, Any] = field(default_factory=dict, init=False)
    _shutdown_complete: bool = field(default=False, init=False, repr=False)
    _shutdown_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

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
        self.jobs = None
        self.database_ready = False
        self.api_ready = False
        self.startup_error = None
        try:
            # Revision validation/upgrade must precede helpers that create tables.
            await init_db()
            self.database_ready = True
            self.database_detail = (
                f"SQLite WAL database ready at {self.paths.database}; synchronous FULL, "
                "foreign keys and 30-second busy timeout are enabled."
            )
            self.jobs = await asyncio.to_thread(DurableJobStore, self.paths.database)
            recovered = await asyncio.to_thread(self.jobs.recover_inflight)
            if recovered:
                logger.info("recovered %s interrupted native jobs", recovered)
            from services.native_imports import recover_native_import_sessions

            recovered_imports = await asyncio.to_thread(recover_native_import_sessions, settings)
            if recovered_imports:
                logger.info("recovered %s interrupted native import operations", recovered_imports)

            self.ffmpeg_probe = await asyncio.to_thread(
                discover_ffmpeg,
                self.paths.ffmpeg_component,
                temp_root=self.paths.temp,
                allow_fixture=self.allow_tool_fixture,
            )
            if self.ffmpeg_probe.ffmpeg_path:
                settings.FFMPEG_BINARY_PATH = self.ffmpeg_probe.ffmpeg_path
            if self.ffmpeg_probe.ffprobe_path:
                settings.FFPROBE_BINARY_PATH = self.ffmpeg_probe.ffprobe_path

            try:
                from rag.vector_store import rag_service

                self._rag_service = rag_service
                self.vector_capability = getattr(rag_service, "capability", None)
                if self.vector_capability is None:
                    raise RuntimeError("Native RAG service has no vector capability")
                await rag_service.ensure_collection()
            except Exception as exc:
                # Retain the actual mutable capability so later operation errors
                # and recovery remain visible to health/capabilities callers.
                if self.vector_capability is None:
                    self.vector_capability = VectorCapability(
                        backend="lancedb",
                        state="unavailable",
                        detail=f"Native vector collection could not be initialized: {exc}",
                        remediation_codes=("VECTOR_STORE_UNAVAILABLE",),
                    )
                elif self.vector_capability.state == "available":
                    # A pre-adapter configuration failure must not leave an old
                    # success visible; retain this same actual capability object.
                    self.vector_capability.state = "unavailable"
                    self.vector_capability.detail = f"Native vector initialization failed: {exc}"
                    self.vector_capability.remediation_codes = ("VECTOR_STORE_UNAVAILABLE",)
                logger.warning("native LanceDB vector store unavailable: %s", exc)

            from .model_manager import get_native_model_store, verify_native_selection, apply_native_selection
            try:
                self.model_store = await asyncio.to_thread(get_native_model_store, settings, restart=True)
                self.model_state = await asyncio.to_thread(verify_native_selection, settings)
                apply_native_selection(settings)
                if self.model_state.get("optional_error"):
                    logger.warning("native optional model verification: %s", self.model_state["optional_error"])
            except (RuntimeError, OSError, ValueError) as exc:
                self.model_state = {"ready": False, "optional_state": "missing", "error": str(exc)}
                logger.warning("native Whisper component requires repair: %s", exc)
            self.api_ready = True
            self.started_at = _now()
            logger.info(
                "native engine startup complete profile=desktop-native db=%s vector=%s ffmpeg=%s",
                self.paths.database,
                getattr(self.vector_capability, "backend", "unavailable"),
                bool(self.ffmpeg_probe and self.ffmpeg_probe.ready),
            )
        except asyncio.CancelledError:
            from .model_manager import shutdown_native_model_store
            cleanup = asyncio.create_task(asyncio.to_thread(shutdown_native_model_store))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            cleanup.result()
            self.jobs = None
            self.database_ready = False
            self.api_ready = False
            self.startup_error = "Native startup cancelled"
            self.database_detail = "Native startup did not complete."
            logger.info("native engine startup cancelled")
            raise
        except Exception as exc:
            self.jobs = None
            self.database_ready = False
            self.api_ready = False
            self.startup_error = f"Native startup failed: {exc}"
            self.database_detail = str(exc)
            logger.exception("native engine startup failed")
            raise

    async def shutdown(self) -> None:
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self.shutting_down = True
            self.api_ready = False
            self.database_ready = False
            self.jobs = None
            logger.info("native engine graceful shutdown begins")

            async def cleanup_owner():
                from .model_manager import shutdown_native_model_store
                try:
                    # Model workers must stop before engine resources are disposed.
                    await asyncio.to_thread(shutdown_native_model_store)
                finally:
                    try:
                        # Do not create RAG merely to close an unstarted runtime.
                        if self._rag_service is not None:
                            await self._rag_service.close()
                    finally:
                        await dispose_db()
                # A failed close remains retryable; only full success is idempotent.
                self._shutdown_complete = True
                logger.info("native engine graceful shutdown complete")

            owner = asyncio.create_task(cleanup_owner())
            caller_cancelled = False
            try:
                while not owner.done():
                    try:
                        await asyncio.shield(owner)
                    except asyncio.CancelledError:
                        caller_cancelled = True
                # Surface cleanup failures before propagating deferred cancellation.
                owner.result()
            except Exception:
                logger.exception("native engine graceful shutdown failed")
                raise
            if caller_cancelled:
                raise asyncio.CancelledError()

    def health_payload(self) -> dict[str, Any]:
        return build_health_payload(
            api_ready=self.api_ready,
            database_ready=self.database_ready,
            database_detail=self.database_detail,
            vector_capability=self.vector_capability,
            ffmpeg_probe=self.ffmpeg_probe,
            startup_error=self.startup_error,
            native_import_ready=self.database_ready and self.jobs is not None,
        )

    def capabilities_payload(self) -> dict[str, Any]:
        return build_capabilities_payload(
            requested=self.requested_capabilities,
            vector_capability=self.vector_capability,
            ffmpeg_probe=self.ffmpeg_probe,
            database_ready=self.database_ready,
            native_import_ready=self.database_ready and self.jobs is not None,
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
                    "capabilities": ["api", "database", "vector-store", "ffmpeg", "native-import"],
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
