import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.topic_segmentation import analyze_topic_sections  # noqa: E402


class TopicSegmentationTests(unittest.TestCase):
    def test_generates_sections_from_topics_pauses_and_transcript_shift(self):
        result = analyze_topic_sections(
            segments=[
                _segment(
                    0,
                    0.0,
                    22.0,
                    topic="Course Setup",
                    text="Welcome to the course goals syllabus and assessment overview",
                ),
                _segment(
                    1,
                    22.0,
                    48.0,
                    topic="Course Setup",
                    text="We review course goals learning outcomes and assessment rubrics",
                    pause=4.2,
                ),
                _segment(
                    2,
                    52.0,
                    78.0,
                    topic="Gradient Descent",
                    text="Gradient descent updates parameters using a learning rate and loss function",
                ),
                _segment(
                    3,
                    78.0,
                    86.0,
                    topic="Gradient Descent",
                    text="The loss function gets smaller after each gradient update",
                ),
                _segment(
                    4,
                    86.0,
                    118.0,
                    topic=None,
                    text="Now deployment pipelines package containers and release models to production",
                ),
            ],
            timeline_words=[],
            duration_seconds=120.0,
        )

        self.assertEqual(result["summary"]["sections_total"], 3)
        self.assertEqual([chapter["label"] for chapter in result["chapters"][:2]], ["Course Setup", "Gradient Descent"])
        self.assertIn("Deployment", result["sections"][2]["label"])
        self.assertTrue(result["sections"][1]["source_signals"]["long_pause"])
        self.assertTrue(result["sections"][2]["source_signals"]["content_shift"])
        self.assertIn("transcript vocabulary shifted", result["sections"][2]["boundary_reason"])
        self.assertIn("00:52 Gradient Descent", result["youtube_format"])

    def test_uses_word_timeline_content_and_skips_cut_segments(self):
        result = analyze_topic_sections(
            segments=[
                _segment(0, 0.0, 35.0, topic=None, text="generic transcript", pause=5.0),
                _segment(1, 38.0, 70.0, topic=None, text="generic transcript", action="cut"),
                _segment(2, 72.0, 105.0, topic=None, text="generic transcript"),
            ],
            timeline_words=[
                _word(0, "matrix", 0.0, 0.3, 0),
                _word(1, "multiplication", 0.3, 0.7, 0),
                _word(2, "eigenvectors", 0.7, 1.2, 0),
                _word(3, "docker", 72.0, 72.4, 2),
                _word(4, "containers", 72.4, 73.0, 2),
                _word(5, "deployment", 73.0, 73.5, 2),
            ],
            duration_seconds=110.0,
        )

        self.assertEqual(result["summary"]["sections_total"], 2)
        self.assertEqual(result["sections"][0]["segment_indexes"], [0])
        self.assertEqual(result["sections"][1]["segment_indexes"], [2])
        self.assertIn("Matrix", result["sections"][0]["label"])
        self.assertIn("Docker", result["sections"][1]["label"])


def _segment(index, start, end, *, topic, text, pause=0.0, action="keep"):
    return SimpleNamespace(
        id=f"seg-{index}",
        segment_index=index,
        start_time=start,
        end_time=end,
        duration=end - start,
        text=text,
        topic_label=topic,
        summary=None,
        pause_duration_total=pause,
        action=action,
        teacher_action=None,
        is_teacher_modified=False,
    )


def _word(index, text, start, end, segment_index):
    return {
        "word_index": index,
        "text": text,
        "start_time": start,
        "end_time": end,
        "segment_index": segment_index,
    }


if __name__ == "__main__":
    unittest.main()
