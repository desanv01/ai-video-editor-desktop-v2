"""
AI-Agent Assisted Video Editing Framework
Main FastAPI application entry point.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from db.database import init_db
from rag.vector_store import rag_service
from api.routes.videos import router as video_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # ── Startup ──
    print("🚀 Starting AI Video Editing Agent...")
    await init_db()
    print("✅ Database tables created")

    await rag_service.ensure_collection()
    print("✅ Qdrant collection ready")

    # Ensure storage directories exist
    import os
    for path in [settings.VIDEO_STORAGE_PATH, settings.UPLOAD_PATH, settings.TEMP_PATH]:
        os.makedirs(path, exist_ok=True)
    print("✅ Storage directories ready")

    print("🎬 AI Video Editing Agent is running!")

    yield

    # ── Shutdown ──
    print("👋 Shutting down...")


app = FastAPI(
    title="AI Video Editing Agent",
    description=(
        "AI-Agent Assisted Video Editing Framework for "
        "Automated Generation of Educational Content. "
        "Uses 5 specialized agents: Transcription, Content Understanding, "
        "Fluency Analysis, Visual Structure, and Edit Planning."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──
app.include_router(video_router, prefix="/api/v1")

# ── Debug routes (only when APP_DEBUG=true) ──
if settings.APP_DEBUG:
    from api.routes.debug import router as debug_router
    app.include_router(debug_router, prefix="/api/v1")

# ── Static files (for serving rendered videos) ──
import os
if os.path.exists(settings.VIDEO_STORAGE_PATH):
    app.mount(
        "/media",
        StaticFiles(directory=settings.VIDEO_STORAGE_PATH),
        name="media",
    )

# ── Static files (for serving original uploaded videos) ──
if os.path.exists(settings.UPLOAD_PATH):
    app.mount(
        "/uploads",
        StaticFiles(directory=settings.UPLOAD_PATH),
        name="uploads",
    )


@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "AI Video Editing Agent",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy"}
