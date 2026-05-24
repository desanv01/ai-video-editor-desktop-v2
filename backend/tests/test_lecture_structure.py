import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.lecture_structure import build_structure_references_from_assets  # noqa: E402


class LectureStructureTests(unittest.TestCase):
    def test_builds_structure_references_from_project_asset_metadata(self):
        asset = SimpleNamespace(
            id="asset-1",
            filename="stored.pdf",
            original_filename="lecture-notes.pdf",
            metadata_json={
                "structure_reference_role": "pdf_notes",
                "document_format": "pdf",
                "structure_reference": {
                    "title": "Week 1 Notes",
                    "reference_role": "pdf_notes",
                    "document_format": "pdf",
                    "items": [
                        {"index": 1, "title": "Course Setup", "text": "overview"},
                        {"index": 2, "title": "Optimization Objectives", "text": "constraints"},
                    ],
                },
            },
        )

        references = build_structure_references_from_assets([asset])

        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["asset_id"], "asset-1")
        self.assertEqual(references[0]["source_filename"], "lecture-notes.pdf")
        self.assertEqual(references[0]["reference_role"], "pdf_notes")
        self.assertEqual(references[0]["items"][1]["title"], "Optimization Objectives")

    def test_supports_legacy_user_supplied_slide_titles(self):
        asset = SimpleNamespace(
            id="asset-2",
            filename="deck.pptx",
            original_filename="deck.pptx",
            metadata_json={
                "structure_reference_role": "slide_sequence",
                "document_format": "pptx",
                "user_metadata": {"slide_titles": ["Intro", "Model Evaluation"]},
            },
        )

        references = build_structure_references_from_assets([asset])

        self.assertEqual(references[0]["items"][0]["index"], 1)
        self.assertEqual(references[0]["items"][1]["title"], "Model Evaluation")


if __name__ == "__main__":
    unittest.main()
