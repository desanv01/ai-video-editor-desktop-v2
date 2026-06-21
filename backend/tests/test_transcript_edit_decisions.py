import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.transcript_edit_decisions import (  # noqa: E402
    build_synced_timeline_plan,
    create_transcript_cut_decision,
    list_active_transcript_cut_intervals,
    list_transcript_cut_decisions,
    normalize_plan_payload,
    remove_transcript_cut_decision,
    restore_word_from_transcript_cut,
    subtract_cut_intervals,
    update_transcript_cut_trim,
)


class TranscriptEditDecisionTests(unittest.TestCase):
    def test_normalizes_legacy_plan_json(self):
        payload = normalize_plan_payload([
            {"segment_id": "seg-1", "action": "keep"},
        ])

        self.assertEqual(payload["segments"][0]["segment_id"], "seg-1")
        self.assertEqual(payload["edit_decisions"], [])
        self.assertIn("schema_version", payload)

    def test_creates_cut_decision_from_word_range(self):
        plan = SimpleNamespace(
            plan_json=[{"segment_id": "seg-1", "action": "keep"}],
            original_duration=10.0,
            estimated_duration=10.0,
        )
        words = [
            _word(0, "Please", 0.0, 0.4, "seg-1", 0),
            _word(1, "remove", 0.4, 0.9, "seg-1", 0),
            _word(2, "this", 0.9, 1.2, "seg-1", 0),
            _word(3, "phrase", 1.2, 1.8, "seg-2", 1),
        ]

        decision = create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=1,
            word_end_index=3,
            teacher_note="manual cut",
        )

        self.assertEqual(decision["text"], "remove this phrase")
        self.assertEqual(decision["start_time"], 0.4)
        self.assertEqual(decision["end_time"], 1.8)
        self.assertEqual(decision["segment_ids"], ["seg-1", "seg-2"])
        self.assertEqual(decision["segment_indexes"], [0, 1])
        self.assertEqual(plan.estimated_duration, 8.6)
        self.assertEqual(len(list_transcript_cut_decisions(plan)), 1)

    def test_removes_cut_and_restores_base_estimated_duration(self):
        plan = SimpleNamespace(
            plan_json=[],
            original_duration=10.0,
            estimated_duration=10.0,
        )
        words = [
            _word(0, "one", 0.0, 0.5, "seg-1", 0),
            _word(1, "two", 0.5, 1.0, "seg-1", 0),
        ]
        decision = create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=0,
            word_end_index=1,
        )

        removed = remove_transcript_cut_decision(plan=plan, decision_id=decision["id"])

        self.assertTrue(removed)
        self.assertEqual(list_transcript_cut_decisions(plan), [])
        self.assertEqual(plan.estimated_duration, 10.0)

    def test_restores_single_word_by_splitting_cut_range(self):
        plan = SimpleNamespace(
            plan_json=[],
            original_duration=10.0,
            estimated_duration=10.0,
        )
        words = [
            _word(0, "remove", 0.0, 0.4, "seg-1", 0),
            _word(1, "only", 0.4, 0.8, "seg-1", 0),
            _word(2, "this", 0.8, 1.2, "seg-1", 0),
            _word(3, "phrase", 1.2, 1.6, "seg-1", 0),
        ]
        decision = create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=0,
            word_end_index=3,
        )

        cuts = restore_word_from_transcript_cut(
            plan=plan,
            timeline_words=words,
            decision_id=decision["id"],
            word_index=1,
        )

        self.assertEqual([(cut["word_start_index"], cut["word_end_index"]) for cut in cuts], [(0, 0), (2, 3)])
        self.assertEqual([cut["text"] for cut in cuts], ["remove", "this phrase"])
        self.assertEqual(plan.estimated_duration, 8.8)

    def test_merges_overlapping_cut_intervals(self):
        plan = SimpleNamespace(
            plan_json=[],
            original_duration=12.0,
            estimated_duration=12.0,
        )
        words = [
            _word(0, "one", 0.0, 0.5, "seg-1", 0),
            _word(1, "two", 0.5, 1.0, "seg-1", 0),
            _word(2, "three", 0.9, 1.4, "seg-1", 0),
            _word(3, "four", 1.4, 2.0, "seg-1", 0),
        ]

        create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=1,
            word_end_index=2,
        )
        create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=2,
            word_end_index=3,
        )

        intervals = list_active_transcript_cut_intervals(plan)

        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0]["start_time"], 0.5)
        self.assertEqual(intervals[0]["end_time"], 2.0)
        self.assertEqual(intervals[0]["duration"], 1.5)
        self.assertEqual(len(intervals[0]["decision_ids"]), 2)

    def test_includes_precise_dead_air_ranges_in_shared_timeline(self):
        plan = SimpleNamespace(
            plan_json={"clean_cuts": [{
                "id": "clean-dead-air-1-2",
                "kind": "clean_time_cut",
                "status": "active",
                "type": "dead_air",
                "start_time": 1.2,
                "end_time": 2.8,
                "duration": 1.6,
                "source": "auto_clean_dead_air",
            }]},
            original_duration=4.0,
            estimated_duration=4.0,
        )
        intervals = list_active_transcript_cut_intervals(plan)
        synced = build_synced_timeline_plan(
            plan=plan,
            segments=[_segment("seg-1", 0, 0.0, 4.0)],
            duration_seconds=4.0,
        )
        self.assertEqual([(item["start_time"], item["end_time"]) for item in intervals], [(1.2, 2.8)])
        self.assertEqual(
            [(item["source_start_time"], item["source_end_time"]) for item in synced["playable_ranges"]],
            [(0.0, 1.2), (2.8, 4.0)],
        )

    def test_updates_cut_trim_with_pre_and_post_roll(self):
        plan = SimpleNamespace(
            plan_json=[],
            original_duration=8.0,
            estimated_duration=8.0,
        )
        words = [
            _word(0, "trim", 2.0, 2.5, "seg-1", 0),
            _word(1, "this", 2.5, 3.0, "seg-1", 0),
        ]
        decision = create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=0,
            word_end_index=1,
        )

        updated = update_transcript_cut_trim(
            plan=plan,
            decision_id=decision["id"],
            pre_roll_seconds=0.25,
            post_roll_seconds=0.5,
        )
        intervals = list_active_transcript_cut_intervals(plan)

        self.assertEqual(updated["word_start_time"], 2.0)
        self.assertEqual(updated["word_end_time"], 3.0)
        self.assertEqual(updated["start_time"], 1.75)
        self.assertEqual(updated["end_time"], 3.5)
        self.assertEqual(updated["duration"], 1.75)
        self.assertEqual(updated["pre_roll_seconds"], 0.25)
        self.assertEqual(updated["post_roll_seconds"], 0.5)
        self.assertEqual(updated["trim_source"], "manual_trim")
        self.assertEqual(intervals[0]["start_time"], 1.75)
        self.assertEqual(intervals[0]["end_time"], 3.5)
        self.assertEqual(plan.estimated_duration, 6.2)

    def test_subtracts_cut_intervals_from_playable_range(self):
        playable = subtract_cut_intervals(
            0.0,
            5.0,
            [
                {"start_time": 1.0, "end_time": 2.0},
                {"start_time": 3.5, "end_time": 4.0},
            ],
        )

        self.assertEqual(
            playable,
            [
                {"start_time": 0.0, "end_time": 1.0, "duration": 1.0},
                {"start_time": 2.0, "end_time": 3.5, "duration": 1.5},
                {"start_time": 4.0, "end_time": 5.0, "duration": 1.0},
            ],
        )

    def test_drops_micro_playable_ranges_after_transcript_cuts(self):
        playable = subtract_cut_intervals(
            0.0,
            1.0,
            [
                {"start_time": 0.0, "end_time": 0.999995},
            ],
        )

        self.assertEqual(playable, [])

    def test_builds_synced_export_ranges_from_segment_actions_and_transcript_cuts(self):
        plan = SimpleNamespace(
            plan_json=[],
            original_duration=6.0,
            estimated_duration=6.0,
        )
        words = [
            _word(0, "keep", 0.0, 1.0, "seg-1", 0),
            _word(1, "cut", 1.0, 2.0, "seg-1", 0),
            _word(2, "keep", 2.0, 3.0, "seg-1", 0),
            _word(3, "cut", 4.0, 5.0, "seg-2", 1),
        ]
        create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=1,
            word_end_index=1,
        )
        create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=3,
            word_end_index=3,
        )
        segments = [
            _segment("seg-1", 0, 0.0, 3.0),
            _segment("seg-2", 1, 3.0, 6.0, action="cut"),
        ]

        synced = build_synced_timeline_plan(
            plan=plan,
            segments=segments,
            duration_seconds=6.0,
        )

        self.assertEqual(len(synced["cut_intervals"]), 2)
        self.assertEqual(len(synced["segment_overlays"]), 2)
        self.assertEqual(
            [(item["source_start_time"], item["source_end_time"]) for item in synced["playable_ranges"]],
            [(0.0, 1.0), (2.0, 3.0)],
        )
        self.assertEqual(synced["export_plan"]["transcript_cut_count"], 2)
        self.assertEqual(synced["export_plan"]["estimated_output_duration_seconds"], 2.0)

    def test_synced_export_plan_omits_micro_ranges(self):
        plan = SimpleNamespace(
            plan_json=[],
            original_duration=1.0,
            estimated_duration=1.0,
        )
        words = [
            _word(0, "almost", 0.0, 0.999995, "seg-1", 0),
        ]
        create_transcript_cut_decision(
            plan=plan,
            timeline_words=words,
            word_start_index=0,
            word_end_index=0,
        )
        segments = [_segment("seg-1", 0, 0.0, 1.0)]

        synced = build_synced_timeline_plan(
            plan=plan,
            segments=segments,
            duration_seconds=1.0,
        )

        self.assertEqual(synced["playable_ranges"], [])
        self.assertEqual(synced["export_plan"]["estimated_output_duration_seconds"], 0.0)


def _word(index, text, start, end, segment_id, segment_index):
    return {
        "word_index": index,
        "text": text,
        "start_time": start,
        "end_time": end,
        "segment_id": segment_id,
        "segment_index": segment_index,
    }


def _segment(segment_id, segment_index, start, end, action="keep"):
    return SimpleNamespace(
        id=segment_id,
        segment_index=segment_index,
        start_time=start,
        end_time=end,
        duration=end - start,
        action=action,
        teacher_action=None,
        is_teacher_modified=False,
    )


if __name__ == "__main__":
    unittest.main()
