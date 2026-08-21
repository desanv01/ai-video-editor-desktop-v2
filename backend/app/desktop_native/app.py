"""FastAPI application factory for the explicit native desktop profile."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .runtime import NativeDesktopRuntime
from services.job_adapter import native_job


def _bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def create_native_app(runtime: NativeDesktopRuntime) -> FastAPI:
    """Create the native app without importing the Docker app/lifespan."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.startup()
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(
        title="AI Video Editing Agent — Native Desktop",
        description="Docker-free Desktop V2 Phase 4 native core engine.",
        version="2.0.0-rc.1",
        lifespan=lifespan,
    )
    app.state.native_runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://localhost:1420", "http://127.0.0.1:1420"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def native_bearer_middleware(request: Request, call_next):
        # This is the only unauthenticated route.  Health/readiness and all
        # browser/API paths require the per-session token.
        if request.url.path != "/live":
            token = _bearer_token(request)
            if token is None or not __import__("hmac").compare_digest(token, runtime.bearer_token):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Native desktop bearer session required."},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)

    @app.get("/live", tags=["Health"])
    async def live() -> dict[str, Any]:
        return {"status": "alive", "profile": "desktop-native"}

    @app.get("/health", tags=["Health"])
    async def health() -> dict[str, Any]:
        return runtime.health_payload()

    @app.get("/readiness", tags=["Health"])
    async def readiness() -> dict[str, Any]:
        return runtime.health_payload()

    @app.get("/capabilities", tags=["Health"])
    async def capabilities() -> dict[str, Any]:
        return runtime.capabilities_payload()

    @app.get("/engine-control", tags=["Engine"])
    async def engine_control() -> dict[str, Any]:
        return runtime.engine_control_payload("ready")

    @app.post("/engine-control/shutdown", tags=["Engine"])
    async def engine_control_shutdown(request: Request) -> dict[str, str]:
        callback = getattr(request.app.state, "request_shutdown", None)
        if not callable(callback):
            raise HTTPException(status_code=503, detail="Native engine shutdown is not available yet.")
        callback()
        return {"status": "accepted"}

    @app.get("/", tags=["Health"])
    async def root() -> dict[str, str]:
        return {
            "service": "AI Video Editing Agent",
            "profile": "desktop-native",
            "version": "2.0.0-rc.1",
            "readiness": "/readiness",
        }

    @app.get("/api/v1/runtime/paths", tags=["Runtime"])
    async def runtime_paths() -> dict[str, Any]:
        return {"dataRoot": str(runtime.paths.data_root), "paths": runtime.paths.capability_paths()}

    @app.post("/api/v1/jobs", status_code=202, tags=["Jobs"])
    async def create_job(request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict) or not body.get("kind"):
            raise HTTPException(status_code=422, detail="Job body requires a non-empty kind.")
        assert runtime.jobs is not None
        return native_job(runtime.jobs.create_job(str(body["kind"]), body.get("payload") or {})) or {}

    @app.get("/api/v1/jobs", tags=["Jobs"])
    async def list_jobs(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        assert runtime.jobs is not None
        return [native_job(job) or job for job in runtime.jobs.list_jobs(status=status, limit=limit)]

    @app.get("/api/v1/jobs/{job_id}", tags=["Jobs"])
    async def get_job(job_id: str) -> dict[str, Any]:
        assert runtime.jobs is not None
        job = runtime.jobs.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Native job not found.")
        return native_job(job) or job

    @app.post("/api/v1/jobs/{job_id}/events", tags=["Jobs"])
    async def append_job_event(job_id: str, request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict) or not body.get("eventType"):
            raise HTTPException(status_code=422, detail="Event body requires eventType.")
        assert runtime.jobs is not None
        try:
            return runtime.jobs.append_event(job_id, str(body["eventType"]), body.get("payload") or {})
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v1/jobs/{job_id}/status", tags=["Jobs"])
    async def update_job(job_id: str, request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict) or not body.get("status"):
            raise HTTPException(status_code=422, detail="Status body requires status.")
        assert runtime.jobs is not None
        try:
            updated = runtime.jobs.update_job(
                job_id,
                str(body["status"]),
                result=body.get("result"),
                error=body.get("error"),
                event_payload=body.get("payload") or {},
            )
            return native_job(updated) or updated
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Existing project/settings/video routes are included after the native
    # profile is configured.  They reuse the portable ORM and local vector
    # adapter; Docker mode never imports this factory.
    from api.routes.models import router as model_router
    from api.routes.projects import router as project_router
    from api.routes.videos import router as video_router
    from api.routes.workflow import router as workflow_router

    app.include_router(video_router, prefix="/api/v1")
    app.include_router(project_router, prefix="/api/v1")
    app.include_router(model_router, prefix="/api/v1")
    app.include_router(workflow_router, prefix="/api/v1")

    app.mount("/media", StaticFiles(directory=str(runtime.paths.exports)), name="media")
    app.mount("/uploads", StaticFiles(directory=str(runtime.paths.uploads)), name="uploads")
    return app
