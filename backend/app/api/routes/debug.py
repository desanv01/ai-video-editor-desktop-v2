"""
Debug/Test Routes — for Phase B/C testing of individual components.
These endpoints are only available when APP_DEBUG=true.
"""

import os
import uuid
import shutil
import time
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from config import settings
from services.ffmpeg import ffmpeg_service
from services.transcription import transcription_service
from services.text_extraction import text_extractor
from rag.vector_store import rag_service

router = APIRouter(prefix="/debug", tags=["Debug"])


@router.post("/transcribe")
async def debug_transcribe(
    file: UploadFile = File(...),
    provider: Optional[str] = Query(None, description="Force 'voxtral' or 'whisper'"),
    terms: Optional[str] = Query(None, description="Comma-separated domain terms"),
):
    """
    Phase B test endpoint: transcribe an audio/video file directly.

    Upload an audio/video file and get the transcription result without
    going through the full pipeline. Useful for testing/debugging.

    Returns the raw transcription output including:
    - Full text
    - Word-level timestamps
    - Segment-level timestamps
    - Speaker diarization (Voxtral only)
    - Processing time and cost estimate
    """
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    # Save uploaded file
    temp_id = uuid.uuid4()
    ext = os.path.splitext(file.filename)[1] or ".mp4"
    temp_path = os.path.join(settings.TEMP_PATH, f"debug_{temp_id}{ext}")
    os.makedirs(settings.TEMP_PATH, exist_ok=True)

    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        # Extract audio if input is video
        audio_ext = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
        if ext.lower() not in audio_ext:
            audio_path = os.path.join(settings.TEMP_PATH, f"debug_{temp_id}_audio.wav")
            await ffmpeg_service.extract_audio(temp_path, audio_path)
        else:
            audio_path = temp_path

        # Get metadata
        metadata = {}
        try:
            metadata = await ffmpeg_service.get_video_metadata(temp_path)
        except Exception:
            pass

        duration = await transcription_service._get_audio_duration(audio_path)

        # Override provider if specified
        original_provider = settings.ASR_PROVIDER
        if provider:
            settings.ASR_PROVIDER = provider

        # Parse domain terms
        domain_terms = None
        if terms:
            domain_terms = [t.strip() for t in terms.split(",")]

        # Transcribe
        start_time = time.time()
        result = await transcription_service.transcribe(
            audio_path=audio_path,
            domain_terms=domain_terms,
        )
        elapsed = time.time() - start_time

        # Restore provider
        if provider:
            settings.ASR_PROVIDER = original_provider

        # Cost estimate
        if result.get("provider", "").startswith("voxtral"):
            cost_per_min = 0.003
        else:
            cost_per_min = 0.006
        estimated_cost = (duration / 60) * cost_per_min

        return {
            "status": "success",
            "input": {
                "filename": file.filename,
                "file_size_mb": round(os.path.getsize(temp_path) / 1024 / 1024, 2),
                "duration_seconds": round(duration, 1),
                "duration_minutes": round(duration / 60, 1),
                "metadata": metadata,
            },
            "transcription": result,
            "performance": {
                "elapsed_seconds": round(elapsed, 2),
                "realtime_factor": round(duration / max(elapsed, 0.01), 1),
                "estimated_cost_usd": round(estimated_cost, 5),
            },
            "summary": {
                "provider": result.get("provider"),
                "language": result.get("language"),
                "word_count": len(result.get("text", "").split()),
                "segments_count": len(result.get("segments", [])),
                "words_with_timestamps": len(result.get("words", [])),
                "speakers_detected": len(result.get("speakers", [])),
                "speakers": result.get("speakers", []),
            },
        }

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
    finally:
        # Cleanup temp files
        for path in [temp_path, audio_path]:
            if path and os.path.exists(path) and path != temp_path:
                try:
                    os.remove(path)
                except OSError:
                    pass
        try:
            os.remove(temp_path)
        except OSError:
            pass


@router.post("/extract-audio")
async def debug_extract_audio(
    file: UploadFile = File(...),
):
    """
    Test audio extraction only.
    Returns metadata about the extracted audio.
    """
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    temp_id = uuid.uuid4()
    ext = os.path.splitext(file.filename)[1] or ".mp4"
    temp_path = os.path.join(settings.TEMP_PATH, f"debug_{temp_id}{ext}")
    audio_path = os.path.join(settings.TEMP_PATH, f"debug_{temp_id}_audio.wav")
    os.makedirs(settings.TEMP_PATH, exist_ok=True)

    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        # Get video metadata
        video_meta = await ffmpeg_service.get_video_metadata(temp_path)

        # Extract audio
        start = time.time()
        await ffmpeg_service.extract_audio(temp_path, audio_path)
        elapsed = time.time() - start

        audio_size = os.path.getsize(audio_path)
        duration = await transcription_service._get_audio_duration(audio_path)

        # Test silence detection
        silences = await ffmpeg_service.detect_silence(
            audio_path,
            threshold_db=settings.SILENCE_THRESHOLD_DB,
            min_duration=settings.SILENCE_MIN_DURATION,
        )

        return {
            "status": "success",
            "video_metadata": video_meta,
            "audio": {
                "path": audio_path,
                "size_mb": round(audio_size / 1024 / 1024, 2),
                "duration_seconds": round(duration, 1),
                "extraction_time_seconds": round(elapsed, 2),
            },
            "silence_detection": {
                "threshold_db": settings.SILENCE_THRESHOLD_DB,
                "min_duration_seconds": settings.SILENCE_MIN_DURATION,
                "silences_found": len(silences),
                "total_silence_seconds": round(sum(s.get("duration", 0) for s in silences), 1),
                "silences": silences[:20],  # First 20 only
            },
        }
    finally:
        for path in [temp_path, audio_path]:
            try:
                os.remove(path)
            except OSError:
                pass


@router.get("/config")
async def debug_config():
    """Show current ASR and LLM configuration (debug only)."""
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    return {
        "asr": {
            "provider": settings.ASR_PROVIDER,
            "voxtral_model": settings.VOXTRAL_MODEL,
            "whisper_model": settings.WHISPER_MODEL,
            "whisper_cpp_binary_path": settings.WHISPER_CPP_BINARY_PATH,
            "whisper_cpp_model_id": settings.WHISPER_CPP_MODEL_ID,
            "whisper_cpp_model_path_set": bool(settings.WHISPER_CPP_MODEL_PATH or settings.LOCAL_TRANSCRIPTION_MODEL_PATH),
            "mistral_api_key_set": bool(settings.MISTRAL_API_KEY) and settings.MISTRAL_API_KEY != "...",
            "openai_api_key_set": bool(settings.OPENAI_API_KEY) and settings.OPENAI_API_KEY != "sk-...",
        },
        "llm": {
            "deepseek_api_key_set": bool(settings.DEEPSEEK_API_KEY) and settings.DEEPSEEK_API_KEY != "sk-...",
            "agent2_model": settings.AGENT2_MODEL,
            "agent3_model": settings.AGENT3_MODEL,
            "agent5_model": settings.AGENT5_MODEL,
        },
        "embedding": {
            "model": settings.EMBEDDING_MODEL,
            "dimensions": settings.EMBEDDING_DIMENSIONS,
        },
        "domain_terms": settings.domain_terms_list,
        "processing": {
            "silence_threshold_db": settings.SILENCE_THRESHOLD_DB,
            "silence_min_duration": settings.SILENCE_MIN_DURATION,
            "max_video_size_mb": settings.MAX_VIDEO_SIZE_MB,
        },
    }


# ═══════════════════════════════════════════
#  RAG DEBUG ENDPOINTS (Phase C)
# ═══════════════════════════════════════════

@router.get("/rag/stats")
async def debug_rag_stats():
    """Get Qdrant collection statistics."""
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    await rag_service.ensure_collection()
    return await rag_service.get_collection_stats()


@router.post("/rag/search")
async def debug_rag_search(
    query: str = Query(..., description="Search query text"),
    top_k: int = Query(5, ge=1, le=20, description="Number of results"),
    source_type: Optional[str] = Query(None, description="'course_material' or 'transcript'"),
    score_threshold: float = Query(0.0, ge=0.0, le=1.0, description="Minimum similarity score"),
):
    """
    Phase C test: search the RAG knowledge base directly.

    Upload course materials first via POST /api/v1/materials/upload,
    then use this endpoint to verify search quality.
    """
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    start = time.time()
    results = await rag_service.search(
        query=query,
        top_k=top_k,
        source_type=source_type,
        score_threshold=score_threshold,
    )
    elapsed = time.time() - start

    return {
        "query": query,
        "top_k": top_k,
        "source_type": source_type,
        "score_threshold": score_threshold,
        "results_count": len(results),
        "search_time_seconds": round(elapsed, 3),
        "results": results,
    }


@router.post("/rag/extract-text")
async def debug_extract_text(
    file: UploadFile = File(...),
):
    """
    Test text extraction from a document without embedding.
    Shows what the text extractor produces for a given file.
    """
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    temp_id = uuid.uuid4()
    ext = os.path.splitext(file.filename)[1]
    temp_path = os.path.join(settings.TEMP_PATH, f"debug_extract_{temp_id}{ext}")
    os.makedirs(settings.TEMP_PATH, exist_ok=True)

    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        start = time.time()
        result = await text_extractor.extract(temp_path)
        elapsed = time.time() - start

        # Also show chunking preview
        pages = result.get("pages", [])
        chunks = rag_service._chunk_pages(pages, file.filename)

        return {
            "status": "success",
            "filename": file.filename,
            "extraction_time_seconds": round(elapsed, 3),
            "metadata": result.get("metadata", {}),
            "text_preview": result["text"][:1000] + ("..." if len(result["text"]) > 1000 else ""),
            "pages_count": len(pages),
            "pages_preview": [
                {
                    "page_num": p.get("page_num"),
                    "text_preview": p.get("text", "")[:200] + "...",
                    "word_count": len(p.get("text", "").split()),
                }
                for p in pages[:5]  # First 5 pages only
            ],
            "chunking_preview": {
                "total_chunks": len(chunks),
                "first_3_chunks": [
                    {
                        "text_preview": c["text"][:200] + "...",
                        "word_count": len(c["text"].split()),
                        "metadata": c.get("metadata", {}),
                    }
                    for c in chunks[:3]
                ],
            },
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@router.post("/rag/reset")
async def debug_rag_reset():
    """Reset the Qdrant collection (delete all data). USE WITH CAUTION."""
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    await rag_service.reset_collection()
    return {"status": "reset", "collection": rag_service.collection_name}


# ═══════════════════════════════════════════
#  AGENT DEBUG ENDPOINTS (Phase D)
# ═══════════════════════════════════════════

@router.post("/agents/run/{agent_name}")
async def debug_run_agent(
    agent_name: str,
    video_id: str = Query(..., description="UUID of the video to analyze"),
):
    """
    Run a single agent in isolation for testing.

    Agents: transcription, content_understanding, fluency, visual_structure, edit_planner

    Prerequisites:
      - transcription: video must be uploaded
      - content_understanding: video must be transcribed
      - fluency: segments must exist (Agent 2 must run first)
      - visual_structure: video must be uploaded
      - edit_planner: all analysis agents must have run
    """
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    from db.database import async_session

    agent_map = {
        "transcription": "agents.transcription:run_transcription_agent",
        "content_understanding": "agents.content_understanding:run_content_understanding_agent",
        "fluency": "agents.fluency:run_fluency_agent",
        "visual_structure": "agents.visual_structure:run_visual_structure_agent",
        "edit_planner": "agents.edit_planner:run_edit_planner_agent",
    }

    if agent_name not in agent_map:
        raise HTTPException(400, f"Unknown agent: {agent_name}. Available: {list(agent_map.keys())}")

    # Dynamic import
    module_path, func_name = agent_map[agent_name].split(":")
    import importlib
    module = importlib.import_module(module_path)
    agent_func = getattr(module, func_name)

    start = time.time()
    async with async_session() as db:
        try:
            result = await agent_func(video_id, db)
            await db.commit()
            elapsed = time.time() - start

            return {
                "status": "success",
                "agent": agent_name,
                "video_id": video_id,
                "elapsed_seconds": round(elapsed, 2),
                "result": result,
            }
        except Exception as e:
            import traceback
            await db.rollback()
            return {
                "status": "error",
                "agent": agent_name,
                "video_id": video_id,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }


@router.get("/agents/segments/{video_id}")
async def debug_view_segments(
    video_id: str,
    limit: int = Query(20, ge=1, le=100),
):
    """View segments for a video — useful after running Agents 2/3/4."""
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    from db.database import async_session
    from db.models import Segment
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(Segment)
            .where(Segment.video_id == video_id)
            .order_by(Segment.segment_index)
            .limit(limit)
        )
        segments = result.scalars().all()

        return {
            "video_id": video_id,
            "segments_count": len(segments),
            "segments": [
                {
                    "index": s.segment_index,
                    "time": f"{s.start_time:.1f}s - {s.end_time:.1f}s",
                    "duration": f"{s.duration:.1f}s" if s.duration else None,
                    "speaker": s.speaker,
                    "topic": s.topic_label,
                    "summary": s.summary,
                    "importance": s.importance_score,
                    "type": s.segment_type.value if s.segment_type else None,
                    "fillers": s.filler_count,
                    "filler_words": s.filler_words,
                    "fluency": s.fluency_score,
                    "pause_seconds": s.pause_duration_total,
                    "has_repetition": s.has_repetition,
                    "has_slide_change": s.has_slide_change,
                    "slide_index": s.slide_index,
                    "action": s.action.value if s.action else None,
                    "confidence": s.action_confidence,
                    "text_preview": (s.text or "")[:150],
                }
                for s in segments
            ],
        }


@router.get("/agents/scenes/{video_id}")
async def debug_view_scenes(video_id: str):
    """View detected scenes for a video — useful after running Agent 4."""
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    from db.database import async_session
    from db.models import Scene
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(Scene)
            .where(Scene.video_id == video_id)
            .order_by(Scene.scene_index)
        )
        scenes = result.scalars().all()

        return {
            "video_id": video_id,
            "scenes_count": len(scenes),
            "scenes": [
                {
                    "index": s.scene_index,
                    "timestamp": s.timestamp,
                    "type": s.scene_type,
                    "confidence": s.confidence,
                    "has_thumbnail": bool(s.thumbnail_path and os.path.exists(s.thumbnail_path)),
                }
                for s in scenes
            ],
        }


# ═══════════════════════════════════════════
#  RENDER DEBUG ENDPOINTS (Phase H)
# ═══════════════════════════════════════════

@router.post("/render/force-approve/{video_id}")
async def debug_force_approve(video_id: str):
    """Force-approve an edit plan for testing (skips teacher review)."""
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    from db.database import async_session
    from db.models import EditPlan
    from sqlalchemy import select
    from datetime import datetime

    async with async_session() as db:
        result = await db.execute(
            select(EditPlan).where(EditPlan.video_id == video_id)
        )
        plan = result.scalar_one_or_none()
        if not plan:
            raise HTTPException(404, "No edit plan found")

        plan.is_approved = True
        plan.approved_at = datetime.utcnow()
        plan.teacher_notes = "Debug: force-approved"
        await db.commit()

        return {"status": "approved", "plan_id": str(plan.id)}


@router.post("/render/run/{video_id}")
async def debug_render(video_id: str):
    """Force render a video (must have an approved edit plan)."""
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    from db.database import async_session
    from services.renderer import render_final_video

    start = time.time()
    async with async_session() as db:
        try:
            result = await render_final_video(video_id, db)
            await db.commit()
            elapsed = time.time() - start

            return {
                "status": "success",
                "elapsed_seconds": round(elapsed, 2),
                "result": result,
            }
        except Exception as e:
            import traceback
            await db.rollback()
            return {
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
            }


@router.get("/render/exports/{video_id}")
async def debug_view_exports(video_id: str):
    """List all rendered export files and their sizes."""
    if not settings.APP_DEBUG:
        raise HTTPException(403, "Debug endpoints are disabled in production")

    base = settings.VIDEO_STORAGE_PATH
    files = {}
    for suffix in ["_edited.mp4", "_subtitles.srt", "_subtitles.vtt", "_chapters.txt", "_edit_plan.json"]:
        path = os.path.join(base, f"{video_id}{suffix}")
        if os.path.exists(path):
            size = os.path.getsize(path)
            files[suffix.lstrip("_")] = {
                "path": path,
                "size_bytes": size,
                "size_human": f"{size / 1024 / 1024:.2f}MB" if size > 1024 * 1024 else f"{size / 1024:.1f}KB",
            }
        else:
            files[suffix.lstrip("_")] = {"path": path, "exists": False}

    return {"video_id": video_id, "exports": files}
