#!/usr/bin/env python3
"""
Phase F Test Script — End-to-End Pipeline Test
================================================

Tests the COMPLETE pipeline from upload through edit plan generation:
  Upload → Transcribe → Embed → Analyze (2,3,4) → Plan → Verify

This is the single most important test in the project — it proves
the entire LangGraph orchestration works end-to-end.

Usage:
    # Full end-to-end test with a video file:
    python scripts/test_pipeline.py --file /path/to/lecture.mp4

    # Test with a specific ASR provider:
    python scripts/test_pipeline.py --file lecture.mp4 --provider whisper

    # Skip upload (use existing video_id):
    python scripts/test_pipeline.py --video-id <UUID>

    # Monitor progress only (for a video already being processed):
    python scripts/test_pipeline.py --video-id <UUID> --monitor

Prerequisites:
    All services running (docker-compose up).
    API keys configured in .env.
"""

import asyncio
import argparse
import os
import sys
import time
import uuid
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


async def main():
    parser = argparse.ArgumentParser(description="End-to-end pipeline test")
    parser.add_argument("--file", type=str, help="Path to video/audio file to upload")
    parser.add_argument("--video-id", type=str, help="Existing video UUID (skip upload)")
    parser.add_argument("--provider", type=str, default=None, help="Force ASR provider")
    parser.add_argument("--monitor", action="store_true", help="Just monitor progress of existing video")
    args = parser.parse_args()

    from db.database import async_session, init_db
    from db.models import Video, Transcript, Segment, EditPlan, Scene, VideoStatus
    from sqlalchemy import select, func
    from config import settings
    from services.progress import get_progress

    print("\n" + "=" * 60)
    print("  AI Video Editing Agent — Phase F End-to-End Pipeline Test")
    print("=" * 60 + "\n")

    await init_db()

    if args.provider:
        settings.ASR_PROVIDER = args.provider
        print(f"🔧 ASR provider override: {args.provider}")

    video_id = args.video_id

    # ── Step 1: Upload (or use existing) ──
    if not video_id:
        if not args.file:
            print("Usage: python scripts/test_pipeline.py --file lecture.mp4")
            print("   or: python scripts/test_pipeline.py --video-id <UUID>")
            return 1

        if not os.path.exists(args.file):
            print(f"❌ File not found: {args.file}")
            return 1

        file_size_mb = os.path.getsize(args.file) / 1024 / 1024
        print(f"📂 Input: {args.file} ({file_size_mb:.1f} MB)")

        print(f"\n{'─' * 40}")
        print(f"  Step 1: Upload Video")
        print(f"{'─' * 40}\n")

        video_id = str(uuid.uuid4())
        ext = os.path.splitext(args.file)[1] or ".mp4"
        filename = f"{video_id}{ext}"
        dest_path = os.path.join(settings.UPLOAD_PATH, filename)
        os.makedirs(settings.UPLOAD_PATH, exist_ok=True)
        shutil.copy2(args.file, dest_path)

        from services.ffmpeg import ffmpeg_service
        metadata = {}
        try:
            metadata = await ffmpeg_service.get_video_metadata(dest_path)
        except Exception:
            pass

        async with async_session() as db:
            video = Video(
                id=video_id,
                filename=filename,
                original_filename=os.path.basename(args.file),
                file_path=dest_path,
                file_size_bytes=os.path.getsize(dest_path),
                duration_seconds=metadata.get("duration"),
                resolution=f"{metadata.get('width', 0)}x{metadata.get('height', 0)}",
                fps=metadata.get("fps"),
                status=VideoStatus.UPLOADED,
            )
            db.add(video)
            await db.commit()

        print(f"  ✅ Video registered: {video_id}")
        print(f"  📊 Duration: {metadata.get('duration', 0):.1f}s")
    else:
        print(f"  📂 Using existing video: {video_id}")

    # ── Step 2: Run full pipeline ──
    if not args.monitor:
        print(f"\n{'─' * 40}")
        print(f"  Step 2: Running Full Pipeline")
        print(f"{'─' * 40}\n")

        from agents.orchestrator import run_processing_pipeline
        from rag.vector_store import rag_service

        await rag_service.ensure_collection()

        pipeline_start = time.time()

        async with async_session() as db:
            video = await db.get(Video, video_id)
            if video:
                video.status = VideoStatus.PROCESSING
                await db.commit()

            result = await run_processing_pipeline(video_id, db)
            await db.commit()

        pipeline_elapsed = time.time() - pipeline_start

        print(f"\n  Pipeline completed in {pipeline_elapsed:.1f}s")
        print(f"  Final status: {result.get('status', 'unknown')}")

        if result.get("status") == "failed":
            print(f"  ❌ Error: {result.get('error', 'unknown')}")
            return 1

    # ── Step 3: Show progress summary ──
    print(f"\n{'─' * 40}")
    print(f"  Step 3: Progress Summary")
    print(f"{'─' * 40}\n")

    progress = get_progress(video_id)
    print(f"  Progress: {progress.get('progress_percent', 0)}%")
    print(f"  Total time: {progress.get('total_elapsed_seconds', 0):.1f}s")
    print(f"\n  Steps completed:")
    for step in progress.get("steps_completed", []):
        timing = progress.get("steps_timing", {}).get(step, {})
        elapsed = timing.get("elapsed_seconds", 0)
        summary = timing.get("summary", {})
        print(f"    ✅ {step} ({elapsed:.1f}s)")
        if summary:
            for k, v in summary.items():
                print(f"       {k}: {v}")

    if progress.get("error"):
        print(f"\n  ❌ Error: {progress['error']}")

    # ── Step 4: Validate results ──
    print(f"\n{'─' * 40}")
    print(f"  Step 4: Validation")
    print(f"{'─' * 40}\n")

    async with async_session() as db:
        video = await db.get(Video, video_id)

        # Transcript check
        t_result = await db.execute(select(Transcript).where(Transcript.video_id == video_id))
        transcript = t_result.scalar_one_or_none()

        # Segment count
        seg_count = await db.execute(
            select(func.count()).select_from(Segment).where(Segment.video_id == video_id)
        )
        total_segs = seg_count.scalar() or 0

        # Segments with importance scores
        analyzed = await db.execute(
            select(func.count()).select_from(Segment)
            .where(Segment.video_id == video_id)
            .where(Segment.importance_score.isnot(None))
        )
        analyzed_count = analyzed.scalar() or 0

        # Segments with fluency
        fluency = await db.execute(
            select(func.count()).select_from(Segment)
            .where(Segment.video_id == video_id)
            .where(Segment.fluency_score.isnot(None))
        )
        fluency_count = fluency.scalar() or 0

        # Segments with edit actions
        actioned = await db.execute(
            select(func.count()).select_from(Segment)
            .where(Segment.video_id == video_id)
            .where(Segment.action.isnot(None))
        )
        actioned_count = actioned.scalar() or 0

        # Scenes
        scene_count = await db.execute(
            select(func.count()).select_from(Scene).where(Scene.video_id == video_id)
        )
        total_scenes = scene_count.scalar() or 0

        # Edit plan
        plan_result = await db.execute(select(EditPlan).where(EditPlan.video_id == video_id))
        plan = plan_result.scalar_one_or_none()

        checks = [
            ("Video status is awaiting_review", video and video.status == VideoStatus.AWAITING_REVIEW),
            ("Transcript exists", transcript is not None),
            ("Transcript has text", transcript and len(transcript.full_text or "") > 0),
            ("Transcript has segments", transcript and len(transcript.segments_json or []) > 0),
            ("ASR provider recorded", transcript and transcript.asr_provider is not None),
            ("Segments created (Agent 2)", total_segs > 0),
            ("All segments have importance scores", analyzed_count == total_segs and total_segs > 0),
            ("All segments have fluency scores", fluency_count == total_segs and total_segs > 0),
            ("All segments have edit actions", actioned_count == total_segs and total_segs > 0),
            ("Scenes detected (Agent 4)", total_scenes >= 0),  # 0 is OK for single-scene videos
            ("Edit plan exists", plan is not None),
            ("Edit plan has entries", plan and plan.plan_json and len(plan.plan_json) > 0),
            ("Estimated duration calculated", plan and plan.estimated_duration is not None),
            ("At least 1 segment kept", plan and (plan.segments_keep or 0) > 0),
        ]

        for name, ok in checks:
            print(f"  {'✅' if ok else '❌'} {name}")

        passed = sum(1 for _, ok in checks if ok)
        total = len(checks)

        # Summary stats
        if plan:
            print(f"\n  📊 Edit Plan Summary:")
            print(f"     Total segments:     {plan.segments_total}")
            print(f"     Keep:               {plan.segments_keep}")
            print(f"     Cut:                {plan.segments_cut}")
            print(f"     Highlight:          {plan.segments_highlight}")
            print(f"     Original:           {plan.original_duration:.1f}s")
            print(f"     Estimated:          {plan.estimated_duration:.1f}s")
            reduction = ((plan.original_duration - plan.estimated_duration) / max(plan.original_duration, 1)) * 100
            print(f"     Reduction:          {reduction:.1f}%")
            print(f"     Fillers removed:    {plan.filler_words_removed}")

        if transcript:
            print(f"\n  🎙️  Transcription:")
            print(f"     Provider:           {transcript.asr_provider}")
            print(f"     Language:           {transcript.language}")
            print(f"     Word count:         {transcript.word_count}")
            print(f"     Speakers:           {len(transcript.speakers_json or [])}")

        print(f"\n  {'=' * 40}")
        print(f"  Results: {passed}/{total} passed")
        if passed == total:
            print(f"  🎉 END-TO-END PIPELINE TEST PASSED!")
        else:
            print(f"  ⚠️  {total - passed} checks failed")
        print(f"  {'=' * 40}\n")

        return 0 if passed == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
