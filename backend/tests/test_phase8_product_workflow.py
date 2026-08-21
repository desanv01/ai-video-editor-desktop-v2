import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.error_normalization import normalize_error
from services.job_adapter import native_job, pipeline_job, render_job
from services.product_workflow import (
    WorkflowState,
    map_legacy_status,
    transition_allowed,
    validate_transition,
)
from services.readiness import build_project_readiness


class Phase8ProductWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        self.settings = SimpleNamespace(
            APP_STORAGE_ROOT=str(self.root),
            UPLOAD_PATH=str(self.root),
            MAX_VIDEO_SIZE_MB=10240,
            UPLOAD_MIN_FREE_SPACE_BYTES=0,
            MISTRAL_API_KEY="",
            OPENAI_API_KEY="",
            DEEPSEEK_API_KEY="",
            ASR_PROVIDER="voxtral",
            VOXTRAL_MODEL="voxtral-mini-latest",
            WHISPER_MODEL="whisper-1",
            AGENT5_MODEL="deepseek-chat",
            EMBEDDING_MODEL="text-embedding-3-small",
            WHISPER_CPP_MODEL_PATH="",
            LOCAL_TRANSCRIPTION_MODEL_PATH="",
            WHISPER_CPP_BINARY_PATH="",
            FFMPEG_BINARY_PATH="",
            FFPROBE_BINARY_PATH="",
            is_native_desktop=False,
        )

    def test_legacy_mapping_and_transition_guard(self):
        self.assertEqual(
            map_legacy_status(video_status="uploaded"),
            WorkflowState.READY_FOR_ANALYSIS,
        )
        self.assertEqual(
            map_legacy_status(video_status="completed", has_edit_plan=True, has_render_output=False),
            WorkflowState.EXPORT_READY,
        )
        self.assertEqual(
            map_legacy_status(project_status="draft", has_source=False),
            WorkflowState.SOURCE_REQUIRED,
        )
        self.assertTrue(transition_allowed("source_required", "validating"))
        self.assertFalse(transition_allowed("source_required", "completed"))
        with self.assertRaises(ValueError):
            validate_transition("source_required", "completed")

    def test_job_adapter_has_stable_shape_for_pipeline_native_and_render(self):
        queued = pipeline_job("video-1", legacy_status="uploaded")
        self.assertEqual(queued["job_id"], "analysis:video-1")
        self.assertEqual(queued["type"], "analysis")
        self.assertEqual(queued["state"], "queued")
        self.assertIn("cancellable", queued)
        self.assertTrue(queued["retryable"])

        native = native_job({
            "job_id": "native-1",
            "kind": "analysis",
            "status": "running",
            "payload": {"progress": 38, "stage": "transcribing"},
        })
        self.assertEqual(native["progress_percent"], 38.0)
        self.assertEqual(native["stage"], "transcribing")
        self.assertEqual(native["state"], "running")

        failed = render_job({
            "job_id": "render-1",
            "status": "failed",
            "error": "Provider API key not configured",
        })
        self.assertEqual(failed["type"], "export")
        self.assertEqual(failed["error_code"], "PROVIDER_NOT_CONFIGURED")
        self.assertTrue(failed["retryable"])
        self.assertTrue(failed["remediation"])

    def test_readiness_reports_source_blocker_then_ready_manual_mode(self):
        project_id = uuid4()
        project = SimpleNamespace(id=project_id, status="draft")
        video = SimpleNamespace(
            id=uuid4(),
            status="uploaded",
            file_path=None,
            original_filename=None,
            file_size_bytes=None,
            duration_seconds=None,
            resolution=None,
            fps=None,
            edit_plan=None,
            processed_video_path=None,
        )
        missing = build_project_readiness(project, video=video, assets=[], settings=self.settings)
        self.assertFalse(missing["ready"])
        self.assertEqual(missing["workflow_state"], "source_required")
        self.assertEqual(missing["blockers"][0]["code"], "SOURCE_REQUIRED")
        self.assertTrue(missing["manual_operations_available"])

        source = Path(__file__).resolve()
        asset = SimpleNamespace(
            id=uuid4(),
            is_primary=True,
            role="primary",
            file_path=str(source),
            original_filename="lecture.mp4",
            file_size_bytes=source.stat().st_size,
            duration_seconds=12.5,
            metadata_json={"resolution": "1280x720", "fps": 30},
        )
        ready = build_project_readiness(project, video=video, assets=[asset], settings=self.settings)
        self.assertTrue(ready["ready"])
        self.assertTrue(ready["source"]["valid"])
        self.assertEqual(ready["source"]["extension"], ".mp4")
        self.assertEqual(ready["workflow_state"], "ready_for_analysis")
        self.assertIn("Start analysis", " ".join(ready["required_actions"]))

    def test_error_normalization_is_human_and_retryable(self):
        error = normalize_error("The backend connection timed out")
        self.assertEqual(error.code, "BACKEND_UNAVAILABLE")
        self.assertTrue(error.retryable)
        self.assertNotIn("Traceback", error.message)


if __name__ == "__main__":
    unittest.main()
