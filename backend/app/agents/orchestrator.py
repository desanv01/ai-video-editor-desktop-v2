"""
LangGraph Orchestrator — the central pipeline that coordinates all 5 agents.

Phase F: Production-ready orchestration.

CRITICAL ORDERING:
  Agent 2 CREATES Segment records (content analysis).
  Agents 3 and 4 UPDATE those Segment records (fluency + visual data).
  Therefore: Agent 2 must finish BEFORE Agents 3 and 4 start.

Correct graph flow:
  transcribe → embed_transcript → content_understanding → [fluency ‖ visual_structure] → plan_edits → END
                                                            (parallel, separate DB sessions)

Key design decisions:
  - Each parallel agent gets its own DB session to avoid write conflicts
  - Progress is tracked per-step for the desktop app to poll
  - Each node catches exceptions and reports them without crashing the pipeline
  - The pipeline PAUSES after edit planning — teacher reviews in the desktop app
  - Rendering is triggered separately after teacher approval
"""

import asyncio
import traceback
import logging
from typing import TypedDict, Optional

from agents.transcription import run_transcription_agent
from agents.content_understanding import run_content_understanding_agent
from agents.fluency import run_fluency_agent
from agents.visual_structure import run_visual_structure_agent
from agents.edit_planner import run_edit_planner_agent
from services.renderer import render_final_video
from services.progress import (
    PipelineStep, init_progress, start_step, complete_step, fail_step,
)
from services.render_jobs import (
    RenderCancelled,
    cancel_render_job,
    complete_render_job,
    fail_render_job,
    start_render_job,
)
from rag.vector_store import rag_service
from db.models import Video, VideoStatus
from db.database import async_session

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════

async def run_processing_pipeline(video_id: str, db_session) -> dict:
    """
    Run the full processing pipeline (Phases 1-5).

    Flow:
      1. Transcribe (Agent 1)
      2. Embed transcript (RAG)
      3. Content understanding (Agent 2) — creates Segments
      4. Fluency + Visual (Agents 3 & 4) — parallel, updates Segments
      5. Edit planning (Agent 5) — creates EditPlan

    Stops at "awaiting_review". Teacher reviews in the desktop app.
    After approval, call run_render_pipeline() separately.

    Returns:
        Final pipeline state dict with results from each phase.
    """
    init_progress(video_id)

    try:
        # ── Phase 1: Transcription ──
        start_step(video_id, PipelineStep.TRANSCRIBING)
        result_transcribe = await _run_node(
            video_id, db_session,
            PipelineStep.TRANSCRIBING,
            run_transcription_agent,
        )
        if result_transcribe.get("status") == "failed":
            return result_transcribe

        # ── Phase 2: Embed transcript into Qdrant for RAG ──
        start_step(video_id, PipelineStep.EMBEDDING_TRANSCRIPT)
        result_embed = await _run_embed_transcript(video_id, db_session)

        # ── Phase 3.1: Content Understanding (Agent 2) — MUST run first ──
        # Creates Segment records that Agents 3 and 4 will update
        start_step(video_id, PipelineStep.ANALYZING_CONTENT)
        result_content = await _run_node(
            video_id, db_session,
            PipelineStep.ANALYZING_CONTENT,
            run_content_understanding_agent,
        )

        # ── Phase 3.2 + 3.3: Fluency + Visual — parallel with SEPARATE sessions ──
        # Both UPDATE the Segments created by Agent 2
        # They write to different columns, so separate sessions avoid conflicts
        start_step(video_id, PipelineStep.ANALYZING_FLUENCY)

        async def _run_fluency():
            async with async_session() as session:
                return await _run_node(
                    video_id, session,
                    PipelineStep.ANALYZING_FLUENCY,
                    run_fluency_agent,
                )

        async def _run_visual():
            async with async_session() as session:
                return await _run_node(
                    video_id, session,
                    PipelineStep.ANALYZING_VISUAL,
                    run_visual_structure_agent,
                )

        result_fluency, result_visual = await asyncio.gather(
            _run_fluency(),
            _run_visual(),
            return_exceptions=False,
        )

        # Refresh the main session to see changes from parallel sessions
        db_session.expire_all()

        # ── Phase 4: Edit Planning (Agent 5) ──
        start_step(video_id, PipelineStep.PLANNING_EDITS)
        result_plan = await _run_node(
            video_id, db_session,
            PipelineStep.PLANNING_EDITS,
            run_edit_planner_agent,
        )

        # ── Pipeline complete — awaiting teacher review ──
        start_step(video_id, PipelineStep.AWAITING_REVIEW)
        complete_step(video_id, PipelineStep.AWAITING_REVIEW)

        logger.info(f"Pipeline complete for {video_id} — awaiting teacher review")

        return {
            "status": "awaiting_review",
            "video_id": video_id,
            "transcription": result_transcribe,
            "embedding": result_embed,
            "content_analysis": result_content,
            "fluency_analysis": result_fluency,
            "visual_analysis": result_visual,
            "edit_plan": result_plan,
        }

    except Exception as e:
        error_msg = f"Pipeline failed: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        fail_step(video_id, "pipeline", str(e))

        # Mark video as failed
        try:
            video = await db_session.get(Video, video_id)
            if video:
                video.status = VideoStatus.FAILED
                video.error_message = error_msg
                await db_session.flush()
        except Exception:
            pass

        return {"status": "failed", "error": error_msg}


async def run_render_pipeline(video_id: str, db_session, render_job_id: str | None = None) -> dict:
    """
    Run the render phase (after teacher approval).

    Separate from the main pipeline because it's triggered
    by the teacher clicking "Approve" in the desktop app.
    """
    start_step(video_id, PipelineStep.RENDERING)
    start_render_job(render_job_id, video_id)

    try:
        result = await render_final_video(
            video_id=video_id,
            db=db_session,
            render_job_id=render_job_id,
        )
        complete_render_job(render_job_id, video_id, result)
        complete_step(video_id, PipelineStep.RENDERING, result)
        start_step(video_id, PipelineStep.COMPLETED)
        complete_step(video_id, PipelineStep.COMPLETED)

        logger.info(f"Render complete for {video_id}")
        return {"status": "completed", **result}

    except RenderCancelled as e:
        cancel_render_job(render_job_id, video_id, str(e))
        logger.info("Render cancelled for %s", video_id)

        try:
            video = await db_session.get(Video, video_id)
            if video:
                video.status = VideoStatus.AWAITING_REVIEW
                video.error_message = "Render cancelled by user"
                await db_session.flush()
        except Exception:
            pass

        return {"status": "cancelled", "error": str(e)}

    except Exception as e:
        error_msg = f"Render failed: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        fail_render_job(render_job_id, video_id, error_msg)
        fail_step(video_id, PipelineStep.RENDERING, str(e))

        try:
            video = await db_session.get(Video, video_id)
            if video:
                video.status = VideoStatus.FAILED
                video.error_message = error_msg
                await db_session.flush()
        except Exception:
            pass

        return {"status": "failed", "error": error_msg}


# ═══════════════════════════════════════════
#  INTERNAL NODE RUNNERS
# ═══════════════════════════════════════════

async def _run_node(
    video_id: str,
    db_session,
    step_name: str,
    agent_func,
) -> dict:
    """
    Run a single agent node with progress tracking and error handling.

    If the agent fails, logs the error and returns a failure dict
    instead of raising (so the pipeline can continue with partial results).
    """
    try:
        result = await agent_func(video_id=video_id, db=db_session)
        await db_session.flush()
        complete_step(video_id, step_name, result)
        return result

    except Exception as e:
        error_msg = f"{step_name} failed: {str(e)}"
        logger.error(f"Node {step_name} failed:\n{traceback.format_exc()}")
        fail_step(video_id, step_name, str(e))

        # Non-critical agents can fail without stopping the pipeline
        critical_steps = {PipelineStep.TRANSCRIBING}
        if step_name in critical_steps:
            # Transcription failure is fatal — can't proceed
            video = await db_session.get(Video, video_id)
            if video:
                video.status = VideoStatus.FAILED
                video.error_message = error_msg
                await db_session.flush()
            raise

        return {"status": "failed", "error": error_msg, "step": step_name}


async def _run_embed_transcript(video_id: str, db_session) -> dict:
    """Embed transcript chunks into Qdrant for RAG. Non-fatal if it fails."""
    try:
        from sqlalchemy import select
        from db.models import Transcript

        result = await db_session.execute(
            select(Transcript).where(Transcript.video_id == video_id)
        )
        transcript = result.scalar_one_or_none()

        if transcript and transcript.segments_json:
            chunk_count = await rag_service.ingest_transcript(
                source_id=str(video_id),
                segments=transcript.segments_json,
                target_duration=60.0,
            )
            result = {"status": "success", "chunks_embedded": chunk_count}
            complete_step(video_id, PipelineStep.EMBEDDING_TRANSCRIPT, result)
            return result
        else:
            complete_step(video_id, PipelineStep.EMBEDDING_TRANSCRIPT)
            return {"status": "skipped", "reason": "No transcript segments"}

    except Exception as e:
        logger.warning(f"Transcript embedding failed (non-fatal): {e}")
        complete_step(video_id, PipelineStep.EMBEDDING_TRANSCRIPT)
        return {"status": "skipped", "reason": str(e)}
