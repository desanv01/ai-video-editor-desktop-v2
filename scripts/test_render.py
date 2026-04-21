#!/usr/bin/env python3
"""
Phase H Test Script — Renderer & Export End-to-End Test
========================================================

Tests the full render pipeline after teacher approval:
  Approve plan → Trim clips → Concat → SRT + VTT → Chapters → Plan export → Verify

Usage:
    # Render a video that has an edit plan (Phases B-E complete):
    python scripts/test_render.py --video-id <UUID>

    # Render + verify all export files:
    python scripts/test_render.py --video-id <UUID> --verify-exports

    # Just check quality report (no render):
    python scripts/test_render.py --video-id <UUID> --report-only

Prerequisites:
    - Video must be processed through Phases B-E (edit plan must exist)
    - All services running (docker-compose up)
"""

import asyncio
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


async def main():
    parser = argparse.ArgumentParser(description="Test renderer and exports")
    parser.add_argument("--video-id", type=str, required=True, help="UUID of the video with edit plan")
    parser.add_argument("--verify-exports", action="store_true", help="Verify all export files exist and are valid")
    parser.add_argument("--report-only", action="store_true", help="Only generate and show quality report")
    args = parser.parse_args()

    from db.database import async_session, init_db
    from db.models import Video, Segment, EditPlan, VideoStatus
    from sqlalchemy import select, func
    from config import settings

    print("\n" + "=" * 60)
    print("  AI Video Editing Agent — Phase H Render & Export Test")
    print("=" * 60 + "\n")

    await init_db()

    async with async_session() as db:
        # ── Verify prerequisites ──
        video = await db.get(Video, args.video_id)
        if not video:
            print(f"❌ Video not found: {args.video_id}")
            return 1

        plan_result = await db.execute(
            select(EditPlan).where(EditPlan.video_id == args.video_id)
        )
        plan = plan_result.scalar_one_or_none()

        print(f"📂 Video: {video.original_filename}")
        print(f"   Status: {video.status.value}")
        print(f"   Duration: {video.duration_seconds:.1f}s" if video.duration_seconds else "   Duration: unknown")
        print(f"   Plan: {'✅ Exists' if plan else '❌ Missing'}")
        if plan:
            print(f"   Approved: {'✅ Yes' if plan.is_approved else '❌ No'}")
            print(f"   Segments: keep={plan.segments_keep}, cut={plan.segments_cut}, highlight={plan.segments_highlight}")

        if not plan:
            print("\n❌ No edit plan found. Run Phases B-E first.")
            return 1

        # ── Report only mode ──
        if args.report_only:
            print(f"\n{'─' * 40}")
            print(f"  Quality Report")
            print(f"{'─' * 40}\n")

            from services.renderer import generate_quality_report
            report = await generate_quality_report(args.video_id, db)

            if "error" in report:
                print(f"  ❌ {report['error']}")
                return 1

            _print_report(report)
            return 0

        # ── Force-approve if needed ──
        if not plan.is_approved:
            print(f"\n  ℹ️  Auto-approving plan for test...")
            from datetime import datetime
            plan.is_approved = True
            plan.approved_at = datetime.utcnow()
            plan.teacher_notes = "Auto-approved for Phase H test"
            await db.commit()

        # ── Render ──
        print(f"\n{'─' * 40}")
        print(f"  Rendering Final Video")
        print(f"{'─' * 40}\n")

        from services.renderer import render_final_video

        start = time.time()
        try:
            result = await render_final_video(args.video_id, db)
            await db.commit()
            elapsed = time.time() - start

            print(f"  ✅ Render completed in {elapsed:.2f}s\n")

            for k, v in result.items():
                if "path" in k:
                    exists = os.path.exists(str(v)) if v else False
                    size = os.path.getsize(str(v)) / 1024 / 1024 if exists else 0
                    print(f"  📄 {k}: {'✅' if exists else '❌'} {v} ({size:.1f}MB)" if exists else f"  📄 {k}: ❌ {v}")
                else:
                    print(f"  📊 {k}: {v}")

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ❌ Render failed after {elapsed:.2f}s: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()
            return 1

        # ── Verify exports ──
        if args.verify_exports:
            print(f"\n{'─' * 40}")
            print(f"  Verifying Export Files")
            print(f"{'─' * 40}\n")

            base = settings.VIDEO_STORAGE_PATH
            vid = args.video_id

            export_files = {
                "Edited video (MP4)": video.processed_video_path,
                "Subtitles (SRT)": os.path.join(base, f"{vid}_subtitles.srt"),
                "Subtitles (VTT)": os.path.join(base, f"{vid}_subtitles.vtt"),
                "Chapters (TXT)": os.path.join(base, f"{vid}_chapters.txt"),
                "Edit plan (JSON)": os.path.join(base, f"{vid}_edit_plan.json"),
            }

            for name, path in export_files.items():
                if path and os.path.exists(path):
                    size = os.path.getsize(path)
                    print(f"  ✅ {name}: {path} ({_format_size(size)})")

                    # Validate content
                    if path.endswith(".srt"):
                        with open(path) as f:
                            content = f.read()
                            cue_count = content.count(" --> ")
                            print(f"      SRT cues: {cue_count}")
                            if cue_count == 0:
                                print(f"      ⚠️  SRT file has no cues!")

                    elif path.endswith(".vtt"):
                        with open(path) as f:
                            content = f.read()
                            if not content.startswith("WEBVTT"):
                                print(f"      ⚠️  VTT file missing WEBVTT header!")
                            cue_count = content.count(" --> ")
                            print(f"      VTT cues: {cue_count}")

                    elif path.endswith(".json"):
                        import json
                        with open(path) as f:
                            data = json.load(f)
                            seg_count = len(data.get("segments", []))
                            print(f"      Segments in export: {seg_count}")
                            print(f"      Export version: {data.get('export_version', 'unknown')}")

                    elif path.endswith("_chapters.txt"):
                        with open(path) as f:
                            lines = [l for l in f.readlines() if l.strip()]
                            print(f"      Chapters: {len(lines)}")

                    elif path.endswith(".mp4"):
                        from services.ffmpeg import ffmpeg_service
                        meta = await ffmpeg_service.get_video_metadata(path)
                        print(f"      Duration: {meta.get('duration', 0):.1f}s")
                        print(f"      Resolution: {meta.get('width', '?')}x{meta.get('height', '?')}")
                else:
                    print(f"  ❌ {name}: MISSING")

        # ── Quality report ──
        print(f"\n{'─' * 40}")
        print(f"  Quality Report")
        print(f"{'─' * 40}\n")

        from services.renderer import generate_quality_report
        report = await generate_quality_report(args.video_id, db)
        _print_report(report)

        # ── Validation ──
        print(f"\n{'─' * 40}")
        print(f"  Validation")
        print(f"{'─' * 40}\n")

        base = settings.VIDEO_STORAGE_PATH
        vid = args.video_id

        checks = [
            ("Video status is completed", video.status == VideoStatus.COMPLETED),
            ("Edited MP4 exists", video.processed_video_path and os.path.exists(video.processed_video_path)),
            ("SRT file exists", os.path.exists(os.path.join(base, f"{vid}_subtitles.srt"))),
            ("VTT file exists", os.path.exists(os.path.join(base, f"{vid}_subtitles.vtt"))),
            ("Chapters file exists", os.path.exists(os.path.join(base, f"{vid}_chapters.txt"))),
            ("Plan export exists", os.path.exists(os.path.join(base, f"{vid}_edit_plan.json"))),
            ("Output shorter than original",
             result.get("output_duration", 0) < (video.duration_seconds or float("inf"))),
            ("At least 1 segment included", result.get("segments_included", 0) > 0),
        ]

        for name, ok in checks:
            print(f"  {'✅' if ok else '❌'} {name}")

        passed = sum(1 for _, ok in checks if ok)
        total = len(checks)

        print(f"\n  {'=' * 40}")
        print(f"  Results: {passed}/{total} passed")
        if passed == total:
            print(f"  🎉 PHASE H RENDER TEST PASSED!")
        else:
            print(f"  ⚠️  {total - passed} checks failed")
        print(f"  {'=' * 40}\n")

        return 0 if passed == total else 1


def _print_report(report: dict):
    """Pretty-print the quality report."""
    print(f"  📊 Duration:")
    print(f"     Original:  {report.get('original_duration_seconds', 0):.1f}s")
    print(f"     Estimated: {report.get('estimated_duration_seconds', 0):.1f}s")
    if report.get("actual_output_duration_seconds"):
        print(f"     Actual:    {report['actual_output_duration_seconds']:.1f}s")
    print(f"     Saved:     {report.get('time_saved_seconds', 0):.1f}s ({report.get('reduction_percent', 0):.1f}%)")

    print(f"\n  📊 Segments:")
    print(f"     Total:     {report.get('total_segments', 0)}")
    print(f"     Keep:      {report.get('segments_keep', 0)}")
    print(f"     Cut:       {report.get('segments_cut', 0)}")
    print(f"     Highlight: {report.get('segments_highlight', 0)}")

    print(f"\n  📊 Quality:")
    print(f"     Avg importance: {report.get('average_importance_score', 0):.3f}")
    print(f"     Avg fluency:    {report.get('average_fluency_score', 0):.3f}")
    print(f"     Total fillers:  {report.get('total_filler_words', 0)}")
    print(f"     Total pauses:   {report.get('total_pause_seconds', 0):.1f}s")

    if report.get("teacher_modifications"):
        print(f"\n  👨‍🏫 Teacher:")
        print(f"     Modifications: {report['teacher_modifications']}")
        print(f"     Overrides:     {report.get('teacher_overrides', 0)}")

    topics = report.get("topic_distribution", {})
    if topics:
        print(f"\n  📑 Topics ({len(topics)}):")
        for topic, data in sorted(topics.items(), key=lambda x: x[1]["total_duration"], reverse=True)[:8]:
            print(f"     {topic}: {data['count']} segs, {data['total_duration']:.0f}s")


def _format_size(bytes_val: int) -> str:
    if bytes_val < 1024:
        return f"{bytes_val}B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f}KB"
    else:
        return f"{bytes_val / 1024 / 1024:.1f}MB"


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
