import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
import sys

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.native_imports import (
    append_native_import_chunk,
    cancel_native_import_session,
    create_native_import_session,
    get_native_import_received_bytes,
    list_native_import_orphans,
    load_native_import_session,
    quarantine_native_import,
    resolve_staged_path,
)


class NativeImportsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.settings = SimpleNamespace(
            UPLOAD_PATH=str(root / "uploads"),
            STAGING_UPLOAD_PATH=str(root / "uploads" / "staging" / "native-imports"),
            IMPORT_MANIFEST_PATH=str(root / "uploads" / "staging" / "native-imports" / "manifests"),
            ORPHAN_UPLOAD_PATH=str(root / "uploads" / "orphaned-imports"),
            MAX_VIDEO_SIZE_MB=10240,
            UPLOAD_REQUIRED_FREE_SPACE_MULTIPLIER=4.0,
            UPLOAD_MIN_FREE_SPACE_BYTES=8 * 1024 * 1024 * 1024,
            UPLOAD_ABANDONED_PART_MAX_AGE_HOURS=0,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_create_session_persists_manifest_and_relative_paths(self):
        with patch("services.native_imports.shutil.disk_usage", return_value=(100, 50, 40 * 1024 * 1024 * 1024)):
            session, free_bytes, required_bytes = create_native_import_session(
                settings=self.settings,
                project_id="project-1",
                original_filename="Lecture Week 1.mp4",
                file_size_bytes=2_730_000_000,
                mime_type="video/mp4",
            )

        self.assertEqual(free_bytes, 40 * 1024 * 1024 * 1024)
        self.assertEqual(required_bytes, 10_920_000_000)
        self.assertTrue(session.staging_relative_path.startswith("staging/native-imports/"))
        self.assertTrue(session.staging_part_relative_path.endswith(".part"))

        manifest_path = Path(self.settings.UPLOAD_PATH) / session.manifest_relative_path
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["project_id"], "project-1")
        self.assertEqual(payload["status"], "initialized")

    def test_create_session_rejects_insufficient_disk_space(self):
        with patch("services.native_imports.shutil.disk_usage", return_value=(100, 90, 1024)):
            with self.assertRaisesRegex(ValueError, "Insufficient disk space"):
                create_native_import_session(
                    settings=self.settings,
                    project_id="project-1",
                    original_filename="Lecture Week 1.mp4",
                    file_size_bytes=2_730_000_000,
                    mime_type="video/mp4",
                )

    def test_cancel_removes_partial_files(self):
        with patch("services.native_imports.shutil.disk_usage", return_value=(100, 50, 40 * 1024 * 1024 * 1024)):
            session, _, _ = create_native_import_session(
                settings=self.settings,
                project_id="project-1",
                original_filename="Lecture Week 1.mp4",
                file_size_bytes=1024,
                mime_type="video/mp4",
            )

        part_path = resolve_staged_path(self.settings, session, part=True)
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(b"partial")

        updated, removed_files = cancel_native_import_session(self.settings, session.token)
        self.assertEqual(updated.status, "cancelled")
        self.assertFalse(part_path.exists())
        self.assertEqual(len(removed_files), 1)

    def test_append_chunk_tracks_offset_and_promotes_complete_upload(self):
        with patch("services.native_imports.shutil.disk_usage", return_value=(100, 50, 40 * 1024 * 1024 * 1024)):
            session, _, _ = create_native_import_session(
                settings=self.settings,
                project_id="project-1",
                original_filename="Lecture Week 1.mp4",
                file_size_bytes=11,
                mime_type="video/mp4",
            )

        session, received, complete = append_native_import_chunk(
            self.settings,
            session,
            offset=0,
            chunk=b"hello ",
        )
        self.assertEqual(received, 6)
        self.assertFalse(complete)
        self.assertEqual(get_native_import_received_bytes(self.settings, session), 6)

        session, received, complete = append_native_import_chunk(
            self.settings,
            load_native_import_session(self.settings, session.token),
            offset=6,
            chunk=b"world",
        )
        self.assertEqual(received, 11)
        self.assertTrue(complete)
        self.assertEqual(session.status, "copied")

        staged_path = resolve_staged_path(self.settings, session, part=False)
        part_path = resolve_staged_path(self.settings, session, part=True)
        self.assertTrue(staged_path.exists())
        self.assertFalse(part_path.exists())
        self.assertEqual(staged_path.read_bytes(), b"hello world")

    def test_append_chunk_rejects_unexpected_offset(self):
        with patch("services.native_imports.shutil.disk_usage", return_value=(100, 50, 40 * 1024 * 1024 * 1024)):
            session, _, _ = create_native_import_session(
                settings=self.settings,
                project_id="project-1",
                original_filename="Lecture Week 1.mp4",
                file_size_bytes=11,
                mime_type="video/mp4",
            )

        append_native_import_chunk(self.settings, session, offset=0, chunk=b"hello ")
        with self.assertRaisesRegex(ValueError, "Unexpected chunk offset"):
            append_native_import_chunk(
                self.settings,
                load_native_import_session(self.settings, session.token),
                offset=0,
                chunk=b"world",
            )

    def test_quarantine_and_orphan_report_surface_stale_files(self):
        with patch("services.native_imports.shutil.disk_usage", return_value=(100, 50, 40 * 1024 * 1024 * 1024)):
            session, _, _ = create_native_import_session(
                settings=self.settings,
                project_id="project-1",
                original_filename="Lecture Week 1.mp4",
                file_size_bytes=1024,
                mime_type="video/mp4",
            )

        staged_path = resolve_staged_path(self.settings, session, part=False)
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(b"complete")
        quarantine_native_import(self.settings, load_native_import_session(self.settings, session.token), staged_path, "db_error")

        orphans, warnings = list_native_import_orphans(self.settings, "project-1")
        self.assertFalse(warnings)
        self.assertEqual(len(orphans), 1)
        self.assertIn("quarantined_after_finalize_failure", orphans[0]["reason"])


if __name__ == "__main__":
    unittest.main()
