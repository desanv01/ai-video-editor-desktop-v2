import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT_PATH = REPO_ROOT / "docs" / "phase-10-demo-script.md"


class DemoScriptDocumentTests(unittest.TestCase):
    def test_demo_script_covers_required_presentation_flow(self):
        content = DEMO_SCRIPT_PATH.read_text(encoding="utf-8")

        required_sections = [
            "# Phase 10 Demo Script And Presentation Narrative",
            "## Demo Thesis",
            "## Demo Scenario",
            "## Pre-Demo Setup",
            "## Presentation Opening",
            "## Live Demo Flow",
            "## Five Minute Fallback Demo",
            "## Slide Narrative",
            "## Examiner Q And A Anchors",
            "## Closing Statement",
        ]
        for section in required_sections:
            self.assertIn(section, content)

        workflow_terms = ["Transcribe", "Clean", "Sections", "Layout", "Polish", "Export"]
        for term in workflow_terms:
            self.assertIn(term, content)

    def test_demo_script_references_phase_10_evidence_artifacts(self):
        content = DEMO_SCRIPT_PATH.read_text(encoding="utf-8")

        required_references = [
            "fixtures/synthetic_media/source/synthetic_lecture_manifest.json",
            "scripts/generate_synthetic_test_media.py",
            "backend.tests.test_synthetic_media_fixtures",
            "/api/v1/videos/{video_id}/plan/export",
            "/api/v1/videos/{video_id}/report/export",
            "/api/v1/videos/{video_id}/mode-comparison/export",
            "/api/v1/videos/{video_id}/evidence/bundle",
            "API, Local, and Hybrid",
            "transcription accuracy proxy",
            "teacher override rate",
        ]
        for reference in required_references:
            self.assertIn(reference, content)


if __name__ == "__main__":
    unittest.main()
