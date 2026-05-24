import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.clean_tools import analyze_clean_suggestions, apply_clean_suggestions  # noqa: E402
from services.transcript_edit_decisions import list_transcript_cut_decisions  # noqa: E402


class CleanToolsTests(unittest.TestCase):
    def test_conservative_profile_finds_obvious_fillers_dead_air_and_bad_takes(self):
        plan = _plan()
        segments = [
            _segment("seg-1", 0, 0.0, 5.0, pause=0.2, importance=0.8, fluency=0.9),
            _segment("seg-2", 1, 5.0, 10.0, pause=2.0, importance=0.7, fluency=0.8),
            _segment(
                "seg-3",
                2,
                10.0,
                14.0,
                pause=0.5,
                importance=0.1,
                fluency=0.2,
                filler_count=6,
                segment_type="filler",
            ),
        ]
        words = [
            _word(0, "Um", 0.0, 0.2, "seg-1", 0),
            _word(1, "today", 0.3, 0.7, "seg-1", 0),
            _word(2, "uh", 6.0, 6.2, "seg-2", 1),
            _word(3, "sorting", 6.3, 6.8, "seg-2", 1),
        ]

        result = analyze_clean_suggestions(
            segments=segments,
            timeline_words=words,
            plan=plan,
            profile_id="conservative",
        )

        self.assertEqual(result["summary"]["filler_word_count"], 2)
        self.assertEqual(result["summary"]["dead_air_count"], 1)
        self.assertEqual(result["summary"]["bad_take_count"], 1)
        self.assertEqual({item["type"] for item in result["suggestions"]}, {"filler_word", "dead_air", "bad_take"})

    def test_aggressive_profile_finds_multi_word_fillers(self):
        result = analyze_clean_suggestions(
            segments=[],
            timeline_words=[
                _word(0, "you", 1.0, 1.2, "seg-1", 0),
                _word(1, "know,", 1.2, 1.4, "seg-1", 0),
                _word(2, "merge", 1.5, 1.8, "seg-1", 0),
            ],
            plan=_plan(),
            profile_id="aggressive",
        )

        self.assertEqual(result["summary"]["filler_word_count"], 1)
        self.assertEqual(result["suggestions"][0]["word_start_index"], 0)
        self.assertEqual(result["suggestions"][0]["word_end_index"], 1)

    def test_apply_clean_creates_transcript_cuts_and_segment_overrides(self):
        plan = _plan(original_duration=12.0)
        segments = [
            _segment("seg-1", 0, 0.0, 4.0, pause=2.0, importance=0.7, fluency=0.8),
            _segment(
                "seg-2",
                1,
                4.0,
                8.0,
                pause=0.5,
                importance=0.1,
                fluency=0.2,
                filler_count=5,
                segment_type="filler",
            ),
        ]
        words = [
            _word(0, "um", 0.0, 0.2, "seg-1", 0),
            _word(1, "topic", 0.3, 0.7, "seg-1", 0),
        ]

        applied = apply_clean_suggestions(
            plan=plan,
            segments=segments,
            timeline_words=words,
            profile_id="conservative",
        )

        self.assertEqual(len(applied["created_transcript_cuts"]), 1)
        self.assertEqual(len(applied["updated_segments"]), 2)
        self.assertEqual(segments[0].teacher_action, "shorten")
        self.assertEqual(segments[1].teacher_action, "cut")
        self.assertEqual(list_transcript_cut_decisions(plan)[0]["source"], "auto_clean_filler_word")
        self.assertLess(plan.estimated_duration, 12.0)


def _plan(original_duration=20.0):
    return SimpleNamespace(
        plan_json=[],
        original_duration=original_duration,
        estimated_duration=original_duration,
        segments_total=0,
        segments_keep=0,
        segments_cut=0,
        segments_highlight=0,
        filler_words_removed=0,
        silence_removed_seconds=0.0,
    )


def _word(index, text, start, end, segment_id, segment_index):
    return {
        "word_index": index,
        "text": text,
        "start_time": start,
        "end_time": end,
        "segment_id": segment_id,
        "segment_index": segment_index,
    }


def _segment(
    segment_id,
    segment_index,
    start,
    end,
    *,
    pause,
    importance,
    fluency,
    filler_count=0,
    segment_type="core_content",
):
    return SimpleNamespace(
        id=segment_id,
        segment_index=segment_index,
        start_time=start,
        end_time=end,
        duration=end - start,
        text="sample lecture segment",
        segment_type=segment_type,
        importance_score=importance,
        fluency_score=fluency,
        filler_count=filler_count,
        pause_duration_total=pause,
        has_repetition=False,
        action="keep",
        teacher_action=None,
        teacher_note=None,
        is_teacher_modified=False,
    )


if __name__ == "__main__":
    unittest.main()
