import sys
import unittest
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.progress import (
    PipelineStep,
    cleanup_progress,
    complete_step,
    fail_step,
    get_progress,
    init_progress,
    start_step,
)


class PipelineProgressTests(unittest.TestCase):
    def tearDown(self):
        cleanup_progress("video-progress-test")

    def test_parallel_steps_keep_independent_timers_and_failures(self):
        video_id = "video-progress-test"

        with patch("services.progress.logger"), patch(
            "services.progress.time.time",
            side_effect=[10.0, 20.0, 25.0, 40.0],
        ):
            init_progress(video_id)
            start_step(video_id, PipelineStep.ANALYZING_FLUENCY)
            start_step(video_id, PipelineStep.ANALYZING_VISUAL)
            complete_step(video_id, PipelineStep.ANALYZING_FLUENCY, {"segments_updated": 3})
            complete_step(
                video_id,
                PipelineStep.ANALYZING_VISUAL,
                {
                    "scenes_detected": 0,
                    "analysis_source": "structure_reference_skip",
                    "structure_reference_count": 1,
                    "vision_provider": "vision-unconfigured",
                    "skip_reason": "large structured camera source",
                },
            )

        progress = get_progress(video_id)

        self.assertEqual(
            progress["steps_timing"][PipelineStep.ANALYZING_FLUENCY]["elapsed_seconds"],
            15.0,
        )
        visual_timing = progress["steps_timing"][PipelineStep.ANALYZING_VISUAL]
        self.assertEqual(visual_timing["elapsed_seconds"], 20.0)
        self.assertEqual(visual_timing["summary"]["analysis_source"], "structure_reference_skip")
        self.assertEqual(visual_timing["summary"]["vision_provider"], "vision-unconfigured")
        self.assertEqual(
            progress["steps_timing"][PipelineStep.ANALYZING_FLUENCY]["summary"]["segments_updated"],
            3,
        )
        self.assertNotIn(PipelineStep.ANALYZING_VISUAL, progress["steps_failed"])
        self.assertNotIn(PipelineStep.ANALYZING_FLUENCY, progress["steps_failed"])

    def test_parallel_step_failure_still_reports_independent_failure(self):
        video_id = "video-progress-test"

        with patch("services.progress.logger"), patch(
            "services.progress.time.time",
            side_effect=[10.0, 20.0, 25.0, 40.0],
        ):
            init_progress(video_id)
            start_step(video_id, PipelineStep.ANALYZING_FLUENCY)
            start_step(video_id, PipelineStep.ANALYZING_VISUAL)
            complete_step(video_id, PipelineStep.ANALYZING_FLUENCY, {"segments_updated": 3})
            fail_step(video_id, PipelineStep.ANALYZING_VISUAL, "frame probe failed")

        progress = get_progress(video_id)

        self.assertIn(PipelineStep.ANALYZING_VISUAL, progress["steps_failed"])
        self.assertEqual(
            progress["steps_timing"][PipelineStep.ANALYZING_VISUAL]["elapsed_seconds"],
            20.0,
        )


if __name__ == "__main__":
    unittest.main()
