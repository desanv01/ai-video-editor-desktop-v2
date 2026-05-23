import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.transcript_edit_decisions import (  # noqa: E402
    create_transcript_cut_decision,
    list_transcript_cut_decisions,
    normalize_plan_payload,
    remove_transcript_cut_decision,
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


def _word(index, text, start, end, segment_id, segment_index):
    return {
        "word_index": index,
        "text": text,
        "start_time": start,
        "end_time": end,
        "segment_id": segment_id,
        "segment_index": segment_index,
    }


if __name__ == "__main__":
    unittest.main()
