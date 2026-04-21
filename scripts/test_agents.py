#!/usr/bin/env python3
"""
Phase D Test Script — Analysis Agents End-to-End Test
======================================================

Tests Agents 2, 3, and 4 on an already-transcribed video.

Prerequisites:
  - Video must be uploaded and transcribed (Phase B complete)
  - Course materials should be ingested (Phase C) for best Agent 2 results

Usage:
    # Run all 3 analysis agents on a video:
    python scripts/test_agents.py --video-id <UUID>

    # Run a single agent:
    python scripts/test_agents.py --video-id <UUID> --agent content_understanding
    python scripts/test_agents.py --video-id <UUID> --agent fluency
    python scripts/test_agents.py --video-id <UUID> --agent visual_structure

    # Run all agents then view results:
    python scripts/test_agents.py --video-id <UUID> --all --show-segments

Environment:
    Requires all services running (docker-compose up).
    Requires DEEPSEEK_API_KEY for Agents 2, 3.
    Requires video to be transcribed first.
"""

import asyncio
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


async def main():
    parser = argparse.ArgumentParser(description="Test analysis agents")
    parser.add_argument("--video-id", type=str, required=True, help="UUID of the transcribed video")
    parser.add_argument("--agent", type=str, default=None,
                        help="Run single agent: content_understanding, fluency, visual_structure")
    parser.add_argument("--all", action="store_true", help="Run all 3 analysis agents in sequence")
    parser.add_argument("--show-segments", action="store_true", help="Print segments after analysis")
    parser.add_argument("--show-scenes", action="store_true", help="Print scenes after Agent 4")
    args = parser.parse_args()

    from db.database import async_session, init_db
    from db.models import Video, Transcript, Segment, Scene
    from sqlalchemy import select, func

    print("\n" + "=" * 60)
    print("  AI Video Editing Agent — Phase D Analysis Test")
    print("=" * 60 + "\n")

    await init_db()

    async with async_session() as db:
        # ── Verify video exists and is transcribed ──
        video = await db.get(Video, args.video_id)
        if not video:
            print(f"❌ Video not found: {args.video_id}")
            print("   Upload and transcribe a video first (Phases A+B)")
            return 1

        result = await db.execute(
            select(Transcript).where(Transcript.video_id == args.video_id)
        )
        transcript = result.scalar_one_or_none()

        print(f"📂 Video: {video.original_filename}")
        print(f"   Status: {video.status.value}")
        print(f"   Duration: {video.duration_seconds:.1f}s" if video.duration_seconds else "   Duration: unknown")
        print(f"   Transcript: {'✅ Yes' if transcript else '❌ No'}")
        if transcript:
            print(f"   Segments: {len(transcript.segments_json or [])} raw segments")
            print(f"   Provider: {transcript.asr_provider}")
            print(f"   Speakers: {len(transcript.speakers_json or [])} detected")

        if not transcript:
            print("\n❌ Video must be transcribed first. Run Phase B.")
            return 1

        # ── Determine which agents to run ──
        agents_to_run = []
        if args.all or args.agent is None:
            agents_to_run = ["content_understanding", "fluency", "visual_structure"]
        elif args.agent:
            agents_to_run = [args.agent]

        # ── Run agents ──
        for agent_name in agents_to_run:
            print(f"\n{'=' * 50}")
            print(f"  Running: Agent {agent_name}")
            print(f"{'=' * 50}\n")

            # Import agent function
            agent_funcs = {
                "content_understanding": ("agents.content_understanding", "run_content_understanding_agent"),
                "fluency": ("agents.fluency", "run_fluency_agent"),
                "visual_structure": ("agents.visual_structure", "run_visual_structure_agent"),
            }

            if agent_name not in agent_funcs:
                print(f"  ❌ Unknown agent: {agent_name}")
                continue

            module_name, func_name = agent_funcs[agent_name]
            import importlib
            module = importlib.import_module(module_name)
            agent_func = getattr(module, func_name)

            start = time.time()
            try:
                result = await agent_func(args.video_id, db)
                await db.commit()
                elapsed = time.time() - start

                print(f"  ✅ Completed in {elapsed:.2f}s")
                for k, v in result.items():
                    if k == "chapters" and isinstance(v, list):
                        print(f"  📑 {k}: {len(v)} chapters")
                        for ch in v[:5]:
                            print(f"      {ch.get('label', 'N/A')}")
                    elif k == "scene_timestamps" and isinstance(v, list):
                        print(f"  🎬 {k}: {v[:10]}{'...' if len(v) > 10 else ''}")
                    else:
                        print(f"  📊 {k}: {v}")

            except Exception as e:
                elapsed = time.time() - start
                print(f"  ❌ Failed after {elapsed:.2f}s: {e}")
                import traceback
                traceback.print_exc()
                await db.rollback()

        # ── Show segments if requested ──
        if args.show_segments:
            print(f"\n{'=' * 50}")
            print(f"  Segment Analysis Results")
            print(f"{'=' * 50}\n")

            result = await db.execute(
                select(Segment)
                .where(Segment.video_id == args.video_id)
                .order_by(Segment.segment_index)
            )
            segments = result.scalars().all()

            for seg in segments:
                importance_bar = "█" * int((seg.importance_score or 0) * 10)
                fluency_bar = "█" * int((seg.fluency_score or 0) * 10)

                print(f"  Segment {seg.segment_index} [{seg.start_time:.1f}s - {seg.end_time:.1f}s]")
                if seg.speaker:
                    print(f"    Speaker:    {seg.speaker}")
                print(f"    Topic:      {seg.topic_label or 'N/A'}")
                print(f"    Type:       {seg.segment_type.value if seg.segment_type else 'N/A'}")
                print(f"    Importance: {seg.importance_score:.2f} {importance_bar}")
                print(f"    Fluency:    {seg.fluency_score:.2f} {fluency_bar}" if seg.fluency_score else "    Fluency:    N/A")
                print(f"    Fillers:    {seg.filler_count or 0} {seg.filler_words or []}")
                print(f"    Pauses:     {seg.pause_duration_total or 0:.1f}s")
                print(f"    Slide:      {'Yes (#{seg.slide_index})' if seg.has_slide_change else 'No'}")
                print(f"    Summary:    {seg.summary[:100]}..." if seg.summary and len(seg.summary) > 100 else f"    Summary:    {seg.summary or 'N/A'}")
                print()

        # ── Show scenes if requested ──
        if args.show_scenes:
            print(f"\n{'=' * 50}")
            print(f"  Scene Detection Results")
            print(f"{'=' * 50}\n")

            result = await db.execute(
                select(Scene)
                .where(Scene.video_id == args.video_id)
                .order_by(Scene.scene_index)
            )
            scenes = result.scalars().all()

            for sc in scenes:
                has_thumb = "✅" if sc.thumbnail_path and os.path.exists(sc.thumbnail_path) else "❌"
                print(f"  Scene {sc.scene_index}: {sc.timestamp:.1f}s | Type: {sc.scene_type} | Thumb: {has_thumb}")

        # ── Validation summary ──
        print(f"\n{'=' * 50}")
        print(f"  Validation Summary")
        print(f"{'=' * 50}\n")

        seg_count = await db.execute(
            select(func.count()).select_from(Segment).where(Segment.video_id == args.video_id)
        )
        total_segs = seg_count.scalar() or 0

        scene_count = await db.execute(
            select(func.count()).select_from(Scene).where(Scene.video_id == args.video_id)
        )
        total_scenes = scene_count.scalar() or 0

        # Count segments with analysis data
        analyzed = await db.execute(
            select(func.count()).select_from(Segment)
            .where(Segment.video_id == args.video_id)
            .where(Segment.topic_label.isnot(None))
        )
        analyzed_count = analyzed.scalar() or 0

        fluency_done = await db.execute(
            select(func.count()).select_from(Segment)
            .where(Segment.video_id == args.video_id)
            .where(Segment.fluency_score.isnot(None))
        )
        fluency_count = fluency_done.scalar() or 0

        checks = [
            ("Segments created (Agent 2)", total_segs > 0),
            ("All segments have topics", analyzed_count == total_segs and total_segs > 0),
            ("All segments have fluency scores", fluency_count == total_segs and total_segs > 0),
            ("Scenes detected (Agent 4)", total_scenes > 0),
        ]

        for name, ok in checks:
            print(f"  {'✅' if ok else '❌'} {name}")

        passed = sum(1 for _, ok in checks if ok)
        print(f"\n  Results: {passed}/{len(checks)} passed")
        print(f"  Segments: {total_segs} | Scenes: {total_scenes}\n")

        return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
