#!/usr/bin/env python3
"""
Phase E Test Script — Edit Planner End-to-End Test
====================================================

Tests Agent 5 (Edit Planner) on a video that has been
processed through Phases B-D (transcribed + analyzed).

Usage:
    # Run edit planner on a fully-analyzed video:
    python scripts/test_edit_planner.py --video-id <UUID>

    # Run planner + show full plan:
    python scripts/test_edit_planner.py --video-id <UUID> --show-plan

    # Simulate teacher modification + revalidation:
    python scripts/test_edit_planner.py --video-id <UUID> --test-revalidation

Prerequisites:
    - Video must be transcribed (Phase B)
    - Segments must exist with analysis data (Phase D — Agents 2, 3, 4)
"""

import asyncio
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


async def main():
    parser = argparse.ArgumentParser(description="Test edit planner (Agent 5)")
    parser.add_argument("--video-id", type=str, required=True, help="UUID of the analyzed video")
    parser.add_argument("--show-plan", action="store_true", help="Print the full edit plan")
    parser.add_argument("--test-revalidation", action="store_true", help="Simulate teacher edit + revalidate")
    args = parser.parse_args()

    from db.database import async_session, init_db
    from db.models import Video, Segment, EditPlan, SegmentAction
    from sqlalchemy import select, func

    print("\n" + "=" * 60)
    print("  AI Video Editing Agent — Phase E Edit Planner Test")
    print("=" * 60 + "\n")

    await init_db()

    async with async_session() as db:
        # ── Verify prerequisites ──
        video = await db.get(Video, args.video_id)
        if not video:
            print(f"❌ Video not found: {args.video_id}")
            return 1

        seg_count = await db.execute(
            select(func.count()).select_from(Segment).where(Segment.video_id == args.video_id)
        )
        total_segs = seg_count.scalar() or 0

        print(f"📂 Video: {video.original_filename}")
        print(f"   Duration: {video.duration_seconds:.1f}s" if video.duration_seconds else "   Duration: unknown")
        print(f"   Segments: {total_segs}")

        if total_segs == 0:
            print("\n❌ No segments found. Run Phases B-D first (Agents 1-4).")
            return 1

        # Check segments have analysis data
        analyzed = await db.execute(
            select(func.count()).select_from(Segment)
            .where(Segment.video_id == args.video_id)
            .where(Segment.importance_score.isnot(None))
        )
        if (analyzed.scalar() or 0) == 0:
            print("\n❌ Segments have no analysis data. Run Agent 2 (content understanding) first.")
            return 1

        print(f"   Analysis: ✅ Ready")

        # ── Run Edit Planner ──
        print(f"\n{'=' * 50}")
        print(f"  Running Agent 5: Edit Planner")
        print(f"{'=' * 50}\n")

        from agents.edit_planner import run_edit_planner_agent

        start = time.time()
        try:
            result = await run_edit_planner_agent(args.video_id, db)
            await db.commit()
            elapsed = time.time() - start

            print(f"  ✅ Completed in {elapsed:.2f}s\n")

            # Print summary
            print(f"  📊 Summary:")
            print(f"     Segments total:      {result.get('segments_total', 0)}")
            print(f"     Keep:                {result.get('segments_keep', 0)}")
            print(f"     Cut:                 {result.get('segments_cut', 0)}")
            print(f"     Shorten:             {result.get('segments_shorten', 0)}")
            print(f"     Highlight:           {result.get('segments_highlight', 0)}")
            print(f"")
            print(f"     Original duration:   {result.get('original_duration', 0):.1f}s")
            print(f"     Estimated duration:  {result.get('estimated_duration', 0):.1f}s")
            print(f"     Time saved:          {result.get('time_saved_seconds', 0):.1f}s ({result.get('reduction_percent', 0)}%)")
            print(f"     Fillers removed:     {result.get('filler_words_removed', 0)}")
            print(f"     Silence removed:     {result.get('silence_removed_seconds', 0):.1f}s")

            # Chapters
            chapters = result.get("chapters", [])
            if chapters:
                print(f"\n  📑 Auto Chapters ({len(chapters)}):")
                for ch in chapters:
                    print(f"     {ch.get('timestamp_formatted', '??:??')} — {ch.get('label', 'N/A')}")

            # Warnings
            warnings = result.get("warnings", [])
            if warnings:
                print(f"\n  ⚠️  Warnings ({len(warnings)}):")
                for w in warnings:
                    print(f"     • {w}")

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ❌ Failed after {elapsed:.2f}s: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()
            return 1

        # ── Show full plan ──
        if args.show_plan:
            print(f"\n{'=' * 50}")
            print(f"  Full Edit Plan")
            print(f"{'=' * 50}\n")

            result_segs = await db.execute(
                select(Segment)
                .where(Segment.video_id == args.video_id)
                .order_by(Segment.segment_index)
            )
            segments = result_segs.scalars().all()

            action_colors = {
                "keep": "🟢",
                "cut": "🔴",
                "shorten": "🔵",
                "highlight": "🟡",
            }

            for seg in segments:
                action = seg.action.value if seg.action else "keep"
                icon = action_colors.get(action, "⚪")
                conf = f"{seg.action_confidence:.0%}" if seg.action_confidence else "N/A"

                print(f"  {icon} Seg {seg.segment_index:3d} [{seg.start_time:6.1f}s - {seg.end_time:6.1f}s] "
                      f"{action.upper():9s} ({conf}) | {seg.topic_label or 'N/A'}")
                if seg.action_reason:
                    print(f"       Reason: {seg.action_reason[:80]}")

        # ── Test revalidation ──
        if args.test_revalidation:
            print(f"\n{'=' * 50}")
            print(f"  Simulating Teacher Modification + Revalidation")
            print(f"{'=' * 50}\n")

            # Find a KEEP segment with high importance and simulate cutting it
            result_segs = await db.execute(
                select(Segment)
                .where(Segment.video_id == args.video_id)
                .where(Segment.action == SegmentAction.KEEP)
                .where(Segment.importance_score >= 0.6)
                .order_by(Segment.segment_index)
                .limit(1)
            )
            test_seg = result_segs.scalar_one_or_none()

            if test_seg:
                print(f"  Simulating: Teacher cuts segment {test_seg.segment_index} "
                      f"(\"{test_seg.topic_label}\", importance={test_seg.importance_score:.2f})")

                test_seg.teacher_action = SegmentAction.CUT
                test_seg.is_teacher_modified = True
                await db.flush()

                from agents.edit_planner import revalidate_edit_plan
                reval = await revalidate_edit_plan(args.video_id, db)

                warnings = reval.get("warnings", [])
                alerts = reval.get("consequence_alerts", [])

                print(f"\n  Revalidation results:")
                if warnings:
                    print(f"  ⚠️  Warnings ({len(warnings)}):")
                    for w in warnings:
                        print(f"      • {w}")
                if alerts:
                    print(f"  🚨 Consequence Alerts ({len(alerts)}):")
                    for a in alerts:
                        print(f"      • [{a['type']}] {a['message']}")
                if not warnings and not alerts:
                    print(f"  ✅ No issues detected")

                # Undo simulation
                test_seg.teacher_action = None
                test_seg.is_teacher_modified = False
                await db.flush()
                print(f"\n  (Simulation reverted)")
            else:
                print("  No suitable segment found for simulation")

        # ── Validation ──
        print(f"\n{'=' * 50}")
        print(f"  Validation")
        print(f"{'=' * 50}\n")

        plan_result = await db.execute(
            select(EditPlan).where(EditPlan.video_id == args.video_id)
        )
        plan = plan_result.scalar_one_or_none()

        checks = [
            ("Edit plan created", plan is not None),
            ("Plan has entries", plan and plan.plan_json and len(plan.plan_json) > 0),
            ("All segments have actions", all(
                s.action is not None
                for s in (await db.execute(
                    select(Segment).where(Segment.video_id == args.video_id)
                )).scalars().all()
            )),
            ("All segments have reasons", all(
                s.action_reason not in (None, "")
                for s in (await db.execute(
                    select(Segment).where(Segment.video_id == args.video_id)
                )).scalars().all()
            )),
            ("Estimated duration < original", plan and (plan.estimated_duration or 0) <= (plan.original_duration or 0)),
            ("At least 1 segment kept", plan and (plan.segments_keep or 0) > 0),
            ("Status is awaiting_review", video.status == "awaiting_review"),
            ("Chapters generated", len(result.get("chapters", [])) > 0),
        ]

        for name, ok in checks:
            print(f"  {'✅' if ok else '❌'} {name}")

        passed = sum(1 for _, ok in checks if ok)
        print(f"\n  Results: {passed}/{len(checks)} passed\n")

        return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
