"""Focused Phase 4 native desktop tests."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import signal
import socket
import json
import hashlib
import hmac
import sqlite3
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from desktop_native.health import build_health_payload  # noqa: E402
from desktop_native.jobs import DurableJobStore  # noqa: E402
from desktop_native.paths import NativeDesktopPaths, NativePathError  # noqa: E402
from desktop_native.sqlite_storage import backup_database, restore_database  # noqa: E402
from desktop_native.tools import discover_ffmpeg  # noqa: E402
from desktop_native.vector_store import SQLiteVectorClient, VectorCapability  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "desktop-v2" / "native-tools"
TEST_ROOT = REPO_ROOT / "tmp_desktop_native_tests"


def _test_root(label: str) -> Path:
    root = TEST_ROOT / f"{label}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class NativeDesktopTests(unittest.TestCase):
    def test_native_paths_are_explicit_and_reject_program_files(self):
        tmp_path = _test_root("paths")
        paths = NativeDesktopPaths.from_environment(data_root=tmp_path / "user-data")
        self.assertEqual(paths.database, tmp_path / "user-data" / "Config" / "engine.sqlite3")
        self.assertTrue(
            paths.capability_paths()["ffmpegComponent"].endswith("Components\\ffmpeg")
            or paths.capability_paths()["ffmpegComponent"].endswith("Components/ffmpeg")
        )
        with self.assertRaises(NativePathError):
            NativeDesktopPaths.from_environment(
                data_root=tmp_path / "Program Files" / "AI Video Editor"
            )

    def test_durable_jobs_survive_store_reopen_and_recover(self):
        database = _test_root("jobs") / "engine.sqlite3"
        first = DurableJobStore(database)
        job = first.create_job("transcode", {"input": "fixture.mp4"})
        first.append_event(job["job_id"], "progress", {"percent": 10})
        reopened = DurableJobStore(database)
        self.assertEqual(reopened.get_job(job["job_id"])["status"], "queued")
        reopened.update_job(job["job_id"], "running")
        self.assertEqual(reopened.recover_inflight(), 1)
        recovered = DurableJobStore(database).get_job(job["job_id"])
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(
            DurableJobStore(database).list_events(job["job_id"])[-1]["eventType"],
            "recovered",
        )

    def test_sqlite_vector_persistence_and_filter(self):
        root = _test_root("vectors")

        async def exercise():
            client = SQLiteVectorClient(root / "vectors", dimensions=2)
            await client.create_collection(
                collection_name="course_materials",
                vectors_config=SimpleNamespace(size=2, distance="Cosine"),
            )
            await client.upsert(
                collection_name="course_materials",
                points=[
                    SimpleNamespace(
                        id="one",
                        vector=[1.0, 0.0],
                        payload={"source_id": "a", "text": "one"},
                    ),
                    SimpleNamespace(
                        id="two",
                        vector=[0.0, 1.0],
                        payload={"source_id": "b", "text": "two"},
                    ),
                ],
            )
            hits = await client.search(
                collection_name="course_materials",
                query_vector=[1.0, 0.0],
                query_filter=SimpleNamespace(
                    must=[SimpleNamespace(key="source_id", match=SimpleNamespace(value="a"))]
                ),
                limit=5,
            )
            self.assertEqual([hit.id for hit in hits], ["one"])
            reopened = SQLiteVectorClient(root / "vectors", dimensions=2)
            stats = await reopened.get_collection("course_materials")
            self.assertEqual(stats.points_count, 2)

        asyncio.run(exercise())

    def test_ffmpeg_discovery_success_and_failure_are_deterministic(self):
        root = _test_root("tools")
        success = discover_ffmpeg(FIXTURE_ROOT, temp_root=root, allow_fixture=True)
        self.assertTrue(success.ready)
        self.assertEqual(success.version, "7.0.0")
        self.assertTrue(success.ffmpeg_path and success.ffmpeg_path.endswith("ffmpeg.cmd"))

        failure = discover_ffmpeg(root / "missing-component", temp_root=root, allow_fixture=True)
        self.assertFalse(failure.ready)
        self.assertIn("FFMPEG_MISSING", failure.remediation_codes)
        self.assertIn("PATH", failure.ffmpeg.detail + failure.ffprobe.detail)

    def test_health_payload_reports_degraded_vector_fallback(self):
        payload = build_health_payload(
            api_ready=True,
            database_ready=True,
            database_detail="SQLite ready",
            vector_capability=VectorCapability(
                backend="sqlite-cosine-fallback",
                state="degraded",
                detail="Explicit fallback; not external Qdrant equivalent.",
                remediation_codes=("VECTOR_STORE_UNAVAILABLE",),
            ),
            ffmpeg_probe=None,
        )
        self.assertEqual(payload["overallState"], "degraded")
        self.assertEqual(payload["checks"]["vectorStore"]["state"], "degraded")
        self.assertIn("ffmpeg", payload["capabilities"]["unavailable"])

    def test_sqlite_pragmas_migrations_backup_and_concurrent_jobs(self):
        root = _test_root("storage")
        database = root / "engine.sqlite3"
        store = DurableJobStore(database)

        def create(index: int):
            return store.create_job("concurrent", {"index": index})["job_id"]

        with ThreadPoolExecutor(max_workers=8) as executor:
            job_ids = list(executor.map(create, range(24)))
        self.assertEqual(len(set(job_ids)), 24)

        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS desktop_schema_migrations "
                "(revision TEXT PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            for revision in (
                "001_initial",
                "002_app_ai_settings",
                "003_project_assets",
                "004_project_media_sources",
                "005_large_file_size_bigint",
            ):
                connection.execute(
                    "INSERT OR IGNORE INTO desktop_schema_migrations "
                    "(revision, description, applied_at) VALUES (?, ?, 'test')",
                    (revision, revision),
                )
            connection.commit()
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM desktop_schema_migrations").fetchone()[0],
                5,
            )
        finally:
            connection.close()

        backup = backup_database(database, root / "Backups" / "engine.sqlite3.bak")
        extra = store.create_job("only-after-backup", {})["job_id"]
        previous = restore_database(database, backup)
        self.assertIsNotNone(previous)
        self.assertIsNone(DurableJobStore(database).get_job(extra))

    def test_native_engine_smoke_auth_paths_project_job_and_shutdown(self):
        root = _test_root("engine")
        token = "phase4-native-smoke-token-123456789012345678"
        session_id = "native-smoke-session"
        control_nonce = "native-smoke-control-nonce-0001"
        port = _free_port()
        control = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        control.bind(("127.0.0.1", 0))
        control.listen(1)
        control.settimeout(30)
        control_host, control_port = control.getsockname()
        command = [
            sys.executable,
            str(REPO_ROOT / "backend" / "native_engine.py"),
            "--data-root",
            str(root / "data"),
            "--port",
            str(port),
            "--bearer-token",
            token,
            "--session-id",
            session_id,
            "--control-address",
            f"{control_host}:{control_port}",
            "--control-nonce",
            control_nonce,
            "--ffmpeg-component-root",
            str(FIXTURE_ROOT),
            "--allow-tool-fixture",
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags,
        )
        base = f"http://127.0.0.1:{port}"
        output = ""
        try:
            connection, _ = control.accept()
            with connection:
                raw_handshake = connection.makefile("rb").readline(16 * 1024)
            handshake = json.loads(raw_handshake)
            self.assertEqual(handshake["sessionId"], session_id)
            self.assertEqual(handshake["nonce"], control_nonce)
            self.assertEqual(handshake["assignedPort"], port)
            canonical = "\n".join(
                str(handshake[key])
                for key in (
                    "protocolVersion", "sessionId", "nonce", "pid", "componentId",
                    "componentVersion", "host", "assignedPort",
                )
            ).encode()
            self.assertTrue(
                hmac.compare_digest(
                    handshake["hmacSha256"],
                    hmac.new(token.encode(), canonical, hashlib.sha256).hexdigest(),
                )
            )
            deadline = time.time() + 30
            while time.time() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    self.fail(f"native engine exited early: {output}")
                try:
                    if httpx.get(base + "/live", timeout=0.5).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.1)
            else:
                self.fail("native engine did not become live")

            with httpx.Client(timeout=20) as client:
                self.assertEqual(client.get(base + "/health").status_code, 401)
                headers = {"Authorization": f"Bearer {token}"}
                health = client.get(base + "/health", headers=headers)
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json()["overallState"], "ready")
                paths = client.get(base + "/api/v1/runtime/paths", headers=headers).json()
                self.assertIn(str(root / "data"), paths["dataRoot"])
                project = client.post(
                    base + "/api/v1/projects",
                    headers=headers,
                    json={"title": "Native smoke project"},
                )
                self.assertEqual(project.status_code, 200, project.text)
                job = client.post(
                    base + "/api/v1/jobs",
                    headers=headers,
                    json={"kind": "smoke", "payload": {"project": project.json()["id"]}},
                )
                self.assertEqual(job.status_code, 202)
                jobs = client.get(base + "/api/v1/jobs", headers=headers).json()
                self.assertEqual(jobs[0]["status"], "queued")
        finally:
            if process.poll() is None:
                if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.send_signal(signal.SIGTERM)
                try:
                    output, _ = process.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    output, _ = process.communicate(timeout=5)
                    self.fail(f"native engine did not shut down gracefully: {output}")
                self.assertEqual(process.returncode, 0, output)
                self.assertIn("native engine graceful shutdown complete", output)
                self.assertNotIn('"type":"aive-engine-startup"', output)
                self.assertNotIn(token, output)
            control.close()
