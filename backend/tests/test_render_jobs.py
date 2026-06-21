import sys
import tempfile
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


from services.render_jobs import (  # noqa: E402
    RenderCancelled,
    cancel_render_job,
    claim_render_job,
    complete_render_job,
    configure_render_job_store,
    create_render_job,
    create_render_job_with_status,
    ensure_not_cancelled,
    get_active_render_job,
    get_latest_render_job,
    get_render_job,
    load_render_jobs_from_store,
    request_render_cancel,
    start_render_job,
    update_render_job,
)


class RenderJobTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp_dir.name) / "render_jobs.json"
        configure_render_job_store(self.store_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_render_job_tracks_progress_and_completion(self):
        video_id = "render-progress-test-complete"
        job = create_render_job(video_id, "youtube_1080p")

        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["progress_percent"], 0.0)
        self.assertEqual(job["preset_id"], "youtube_1080p")
        self.assertTrue(job["started_at"].endswith("+00:00"))

        running = start_render_job(job["job_id"], video_id)
        self.assertEqual(running["status"], "running")
        self.assertTrue(running["cancellable"])

        updated = update_render_job(
            job["job_id"],
            video_id,
            progress_percent=42.25,
            phase="rendering_clips",
            phase_label="Rendering timeline clips",
            message="Rendering range 2 of 5",
            details={"current_range": 2, "total_ranges": 5},
        )
        self.assertEqual(updated["progress_percent"], 42.2)
        self.assertEqual(updated["details"]["current_range"], 2)

        completed = complete_render_job(job["job_id"], video_id, {"output_path": "out.mp4"})
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress_percent"], 100.0)
        self.assertFalse(completed["cancellable"])
        self.assertIsNone(get_active_render_job(video_id))
        self.assertEqual(get_latest_render_job(video_id)["status"], "completed")

    def test_active_job_is_reused_and_can_only_be_claimed_once(self):
        video_id = "render-progress-test-idempotent"
        job, created = create_render_job_with_status(video_id, "youtube_1080p")
        duplicate, duplicate_created = create_render_job_with_status(video_id, "youtube_720p")

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate["job_id"], job["job_id"])
        self.assertEqual(duplicate["preset_id"], "youtube_1080p")
        self.assertIsNotNone(claim_render_job(job["job_id"], video_id))
        self.assertIsNone(claim_render_job(job["job_id"], video_id))

    def test_render_cancel_request_is_observed_by_checker(self):
        video_id = "render-progress-test-cancel"
        job = create_render_job(video_id, "mp4_1080p")
        start_render_job(job["job_id"], video_id)

        cancel_requested = request_render_cancel(video_id)
        self.assertEqual(cancel_requested["status"], "cancel_requested")
        self.assertTrue(cancel_requested["cancel_requested"])

        with self.assertRaises(RenderCancelled):
            ensure_not_cancelled(job["job_id"], video_id)

        cancelled = cancel_render_job(job["job_id"], video_id)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertFalse(cancelled["cancellable"])
        self.assertIsNone(get_active_render_job(video_id))

    def test_active_job_survives_store_reload_as_interrupted_failure(self):
        video_id = "render-progress-test-restart"
        job = create_render_job(video_id, "youtube_720p")
        start_render_job(job["job_id"], video_id)
        update_render_job(
            job["job_id"],
            video_id,
            progress_percent=58.0,
            phase="rendering_clips",
            phase_label="Rendering timeline clips",
            message="Rendering range 3 of 5",
        )

        self.assertTrue(self.store_path.exists())

        load_render_jobs_from_store()

        interrupted = get_render_job(job["job_id"])
        self.assertIsNotNone(interrupted)
        self.assertEqual(interrupted["status"], "failed")
        self.assertEqual(interrupted["phase"], "interrupted")
        self.assertEqual(interrupted["error"], "Render interrupted by backend restart")
        self.assertIn("backend restarted", interrupted["message"])
        self.assertFalse(interrupted["cancellable"])
        self.assertIsNone(get_active_render_job(video_id))
        self.assertEqual(get_latest_render_job(video_id)["job_id"], job["job_id"])


if __name__ == "__main__":
    unittest.main()
