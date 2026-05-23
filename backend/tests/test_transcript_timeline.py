import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.transcript_timeline import (  # noqa: E402
    build_transcript_timeline,
    normalize_transcript_words,
)


class TranscriptTimelineTests(unittest.TestCase):
    def test_normalizes_provider_words_and_maps_transcript_segments(self):
        words = normalize_transcript_words(
            [
                {"word": "Hello", "start": 0.0, "end": 0.4, "speaker": "Teacher"},
                {"text": "class", "start_time": "0.45", "end_time": "0.9"},
            ],
            [{"text": "Hello class", "start": 0.0, "end": 1.0, "speaker": "Teacher"}],
            duration_seconds=5.0,
        )

        self.assertEqual([word["text"] for word in words], ["Hello", "class"])
        self.assertEqual(words[0]["speaker"], "Teacher")
        self.assertEqual(words[0]["transcript_segment_index"], 0)
        self.assertFalse(words[0]["is_estimated"])

    def test_estimates_word_timing_from_segments_when_words_are_missing(self):
        words = normalize_transcript_words(
            [],
            [
                {
                    "text": "Alpha beta gamma",
                    "start": 10.0,
                    "end": 13.0,
                    "speaker": "Teacher",
                }
            ],
        )

        self.assertEqual([word["text"] for word in words], ["Alpha", "beta", "gamma"])
        self.assertEqual(words[1]["start_time"], 11.0)
        self.assertEqual(words[1]["end_time"], 12.0)
        self.assertTrue(words[1]["is_estimated"])
        self.assertEqual(words[1]["source"], "transcript_segment_estimate")

    def test_builds_word_ranges_for_existing_review_segments(self):
        video_id = uuid.uuid4()
        transcript_id = uuid.uuid4()
        first_segment_id = uuid.uuid4()
        second_segment_id = uuid.uuid4()

        transcript = SimpleNamespace(
            id=transcript_id,
            full_text="Hello class Next topic",
            language="en",
            asr_provider="voxtral",
            words_json=[
                {"word": "Hello", "start": 0.0, "end": 0.5},
                {"word": "class", "start": 0.5, "end": 1.0},
                {"word": "Next", "start": 5.0, "end": 5.5},
                {"word": "topic", "start": 5.5, "end": 6.0},
            ],
            segments_json=[
                {"text": "Hello class", "start": 0.0, "end": 1.0},
                {"text": "Next topic", "start": 5.0, "end": 6.0},
            ],
        )
        review_segments = [
            SimpleNamespace(
                id=first_segment_id,
                segment_index=0,
                start_time=0.0,
                end_time=2.0,
                duration=2.0,
                text="Hello class",
                speaker=None,
            ),
            SimpleNamespace(
                id=second_segment_id,
                segment_index=1,
                start_time=4.0,
                end_time=7.0,
                duration=3.0,
                text="Next topic",
                speaker=None,
            ),
        ]

        timeline = build_transcript_timeline(
            video_id=video_id,
            transcript=transcript,
            review_segments=review_segments,
            duration_seconds=7.0,
        )

        self.assertEqual(timeline["video_id"], video_id)
        self.assertEqual(timeline["word_count"], 4)
        self.assertEqual(timeline["words"][0]["segment_id"], str(first_segment_id))
        self.assertEqual(timeline["words"][2]["segment_index"], 1)
        self.assertEqual(timeline["segments"][0]["word_start_index"], 0)
        self.assertEqual(timeline["segments"][0]["word_end_index"], 1)
        self.assertEqual(timeline["segments"][1]["word_count"], 2)


if __name__ == "__main__":
    unittest.main()
