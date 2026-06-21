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

    def test_slide_changes_and_slide_titles_drive_section_boundaries(self):
        result = analyze_topic_sections(
            segments=[
                _segment(
                    0,
                    0.0,
                    20.0,
                    topic=None,
                    text="We start with course goals and learning outcomes",
                    slide_index=1,
                    slide_change=True,
                ),
                _segment(
                    1,
                    20.0,
                    38.0,
                    topic=None,
                    text="Assessment rubrics and course expectations",
                    slide_index=1,
                ),
                _segment(
                    2,
                    44.0,
                    70.0,
                    topic=None,
                    text="Now the learning rate updates parameters with a loss function",
                    slide_index=2,
                    slide_change=True,
                ),
                _segment(
                    3,
                    82.0,
                    108.0,
                    topic=None,
                    text="Deployment packages containers and releases the model",
                    slide_index=3,
                    slide_change=True,
                ),
            ],
            structure_references=[
                {
                    "asset_id": "deck-1",
                    "source_filename": "week-1.pptx",
                    "reference_role": "slide_sequence",
                    "document_format": "pptx",
                    "items": [
                        {"index": 1, "title": "Course Goals", "text": "Course goals learning outcomes"},
                        {"index": 2, "title": "Gradient Descent", "text": "Learning rate loss function parameters"},
                        {"index": 3, "title": "Model Deployment", "text": "Containers release production model"},
                    ],
                }
            ],
            duration_seconds=110.0,
        )

        self.assertEqual(result["summary"]["sections_total"], 3)
        self.assertEqual(result["summary"]["structure_reference_count"], 1)
        self.assertEqual(
            [section["label"] for section in result["sections"]],
            ["Course Goals", "Gradient Descent", "Model Deployment"],
        )
        self.assertTrue(result["sections"][1]["source_signals"]["slide_change"])
        self.assertTrue(result["sections"][1]["source_signals"]["structure_title_change"])
        self.assertEqual(result["sections"][1]["label_source"], "teaching_material")
        self.assertEqual(result["sections"][1]["structure_reference"]["source_filename"], "week-1.pptx")
        self.assertIn("00:44 Gradient Descent", result["youtube_format"])

    def test_pdf_page_titles_improve_labels_without_topic_labels(self):
        result = analyze_topic_sections(
            segments=[
                _segment(0, 0.0, 34.0, topic=None, text="generic transcript about setup"),
                _segment(
                    1,
                    40.0,
                    76.0,
                    topic=None,
                    text="Next we discuss optimization objectives and constraints",
                    pause=3.0,
                ),
            ],
            structure_references=[
                {
                    "asset_id": "notes-1",
                    "source_filename": "lecture-notes.pdf",
                    "reference_role": "pdf_notes",
                    "document_format": "pdf",
                    "items": [
                        {"index": 1, "title": "Course Setup", "text": "setup introduction"},
                        {
                            "index": 2,
                            "title": "Optimization Objectives",
                            "text": "optimization objectives constraints",
                        },
                    ],
                }
            ],
            duration_seconds=80.0,
        )

        self.assertEqual(result["summary"]["sections_total"], 2)
        self.assertEqual(result["sections"][1]["label"], "Optimization Objectives")
        self.assertEqual(result["sections"][1]["structure_reference"]["reference_role"], "pdf_notes")

    def test_project_type_profile_enforces_shorter_tutorial_sections(self):
        segments = [
            _segment(index, index * 120.0, (index + 1) * 120.0, topic="Live Coding", text="editor code demo")
            for index in range(5)
        ]

        lecture = analyze_topic_sections(
            segments=segments,
            timeline_words=[],
            duration_seconds=600.0,
            project_type="lecture",
        )
        tutorial = analyze_topic_sections(
            segments=segments,
            timeline_words=[],
            duration_seconds=600.0,
            project_type="tutorial",
        )

        self.assertEqual(lecture["summary"]["project_type"], "lecture")
        self.assertEqual(tutorial["summary"]["project_type"], "tutorial")
        self.assertEqual(lecture["summary"]["target_section_duration_seconds"], 600)
        self.assertEqual(tutorial["summary"]["target_section_duration_seconds"], 300)
        self.assertEqual(lecture["summary"]["sections_total"], 1)
        self.assertGreater(tutorial["summary"]["sections_total"], lecture["summary"]["sections_total"])
        self.assertTrue(tutorial["sections"][1]["source_signals"]["duration_target"])


def _segment(
    index,
    start,
    end,
    *,
    topic,
    text,
    pause=0.0,
    action="keep",
    slide_index=None,
    slide_change=False,
):
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
        slide_index=slide_index,
        has_slide_change=slide_change,
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
