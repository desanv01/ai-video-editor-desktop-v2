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
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from desktop_native.health import build_health_payload  # noqa: E402
from desktop_native.jobs import DurableJobStore  # noqa: E402
from desktop_native.paths import NativeDesktopPaths, NativePathError  # noqa: E402
from desktop_native.sqlite_storage import backup_database, restore_database  # noqa: E402
from desktop_native.tools import ToolProbe, discover_ffmpeg  # noqa: E402
from desktop_native.vector_store import VectorCapability  # noqa: E402


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

    def test_ffmpeg_probes_overlap_collect_all_results_and_preserve_failure(self):
        for failed_probe in (None, "encode"):
            with self.subTest(failed_probe=failed_probe):
                barrier = Barrier(4, timeout=5)
                lock = Lock()
                entered = set()
                completed = set()
                results = {}

                def run_probe(path, args, *, allow_fixture):
                    self.assertFalse(allow_fixture)
                    if tuple(args) == ("-version",):
                        name = "ffprobe" if path.stem == "ffprobe" else "ffmpeg"
                    else:
                        name = "encode" if "color=c=black:s=16x16:r=1" in args else "decode"
                        self.assertEqual(tuple(args[-3:]), ("-f", "null", "-"))
                    with lock:
                        self.assertNotIn(name, entered)
                        entered.add(name)
                    # A serial implementation cannot finish this barrier.
                    barrier.wait()
                    result = ToolProbe(
                        path=str(path), present=True,
                        version="7.0.0" if name in ("ffmpeg", "ffprobe") else None,
                        version_ok=name in ("ffmpeg", "ffprobe"),
                        return_code=1 if name == failed_probe else 0,
                        detail="mocked probe",
                    )
                    with lock:
                        results[name] = result
                        completed.add(name)
                    return result

                with patch("desktop_native.tools._candidate", side_effect=lambda root, name, **kwargs: root / f"{name}.exe"), patch(
                    "desktop_native.tools._run_probe", side_effect=run_probe,
                ) as probe:
                    actual = discover_ffmpeg(FIXTURE_ROOT)

                self.assertEqual(probe.call_count, 4)
                self.assertEqual(entered, {"ffmpeg", "ffprobe", "encode", "decode"})
                self.assertEqual(completed, entered)
                self.assertIs(actual.ffmpeg, results["ffmpeg"])
                self.assertIs(actual.ffprobe, results["ffprobe"])
                self.assertIs(actual.encode_self_test, results["encode"])
                self.assertIs(actual.decode_self_test, results["decode"])
                self.assertEqual(actual.ready, failed_probe is None)
                self.assertEqual(actual.remediation_codes, [] if failed_probe is None else ["FFMPEG_MISSING"])

    def test_health_payload_reports_unavailable_lancedb(self):
        payload = build_health_payload(
            api_ready=True,
            database_ready=True,
            database_detail="SQLite ready",
            vector_capability=VectorCapability(
                backend="lancedb",
                state="unavailable",
                detail="Failed native index; no fallback is allowed.",
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
        with store._session() as db:
            self.assertEqual(db.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 30000)

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

class NativeStartupProbeOverlapTests(unittest.IsolatedAsyncioTestCase):
    def _startup(self, *, database_error=None, block_database=False, probe_error=None):
        from desktop_native import runtime as module

        entered, release, finished, prefix = (asyncio.Event() for _ in range(4))
        cleanup = asyncio.Event()
        owned_probe_tasks = []
        paths = SimpleNamespace(
            database=Path("unused/native.sqlite3"),
            ffmpeg_component=Path("unused/components/ffmpeg"),
            temp=Path("unused/temp"), ensure_directories=Mock(),
        )
        settings = SimpleNamespace(FFMPEG_BINARY_PATH="before-ffmpeg", FFPROBE_BINARY_PATH="before-ffprobe")
        result = SimpleNamespace(ffmpeg_path="component-ffmpeg", ffprobe_path="component-ffprobe", ready=True)
        probe = Mock(return_value=result, side_effect=probe_error)
        job_store = SimpleNamespace(recover_inflight=Mock(return_value=0))
        rag = SimpleNamespace(capability=VectorCapability("lancedb", "available", "fixture"), ensure_collection=AsyncMock())
        models = SimpleNamespace(
            get_native_model_store=Mock(return_value=object()),
            verify_native_selection=Mock(return_value={"ready": True}),
            apply_native_selection=Mock(), shutdown_native_model_store=Mock(side_effect=cleanup.set),
        )

        async def init_database():
            await entered.wait()  # Fails to progress if probes remain behind DB initialization.
            if database_error is not None or block_database:
                prefix.set()
            if database_error is not None:
                raise database_error
            if block_database:
                await asyncio.Event().wait()

        def recover_imports(_settings):
            job_store.recover_inflight.assert_called_once_with()
            prefix.set()
            return 0

        async def to_thread(function, *args, **kwargs):
            if function is probe:
                owned_probe_tasks.append(asyncio.current_task())
                entered.set()
                await release.wait()
                try:
                    return function(*args, **kwargs)
                finally:
                    finished.set()
            return function(*args, **kwargs)

        self.enterContext(patch.multiple(module, settings=settings, init_db=init_database,
                                         discover_ffmpeg=probe, DurableJobStore=Mock(return_value=job_store)))
        self.enterContext(patch.object(module.asyncio, "to_thread", side_effect=to_thread))
        self.enterContext(patch.dict(sys.modules, {
            "services.native_imports": SimpleNamespace(recover_native_import_sessions=recover_imports),
            "rag.vector_store": SimpleNamespace(rag_service=rag),
            "desktop_native.model_manager": models,
        }))
        self.addCleanup(release.set)
        runtime = module.NativeDesktopRuntime(paths=paths, bearer_token="t" * 32, session_id="startup_overlap")
        task = asyncio.create_task(runtime.startup())
        return SimpleNamespace(runtime=runtime, task=task, release=release, entered=entered,
                               finished=finished, prefix=prefix, cleanup=cleanup,
                               probe=probe, result=result, settings=settings, rag=rag,
                               models=models, owned_probe_tasks=owned_probe_tasks)

    async def test_startup_probe_overlaps_recovery_without_early_publication(self):
        state = self._startup()
        try:
            await asyncio.wait_for(state.prefix.wait(), 2)
            self.assertFalse(state.task.done())
            self.assertFalse(state.runtime.api_ready)
            self.assertIsNone(state.runtime.ffmpeg_probe)
            self.assertEqual(state.settings.FFMPEG_BINARY_PATH, "before-ffmpeg")
            self.assertEqual(state.settings.FFPROBE_BINARY_PATH, "before-ffprobe")
            state.rag.ensure_collection.assert_not_awaited()
            state.models.get_native_model_store.assert_not_called()
        finally:
            state.release.set()
        await asyncio.wait_for(state.task, 2)
        state.probe.assert_called_once_with(state.runtime.paths.ffmpeg_component,
                                           temp_root=state.runtime.paths.temp, allow_fixture=False)
        self.assertEqual(len(state.owned_probe_tasks), 1)
        self.assertTrue(state.finished.is_set())
        self.assertIs(state.runtime.ffmpeg_probe, state.result)
        self.assertEqual(state.settings.FFMPEG_BINARY_PATH, "component-ffmpeg")
        self.assertTrue(state.runtime.api_ready)
        state.rag.ensure_collection.assert_awaited_once()

    async def test_startup_database_failure_drains_probe_and_preserves_primary_error(self):
        primary = RuntimeError("database failed")
        state = self._startup(database_error=primary, probe_error=ValueError("secondary probe failure"))
        try:
            await asyncio.wait_for(state.prefix.wait(), 2)
            await asyncio.sleep(0)
            self.assertFalse(state.task.done())
            self.assertFalse(state.runtime.api_ready)
            self.assertFalse(state.runtime.database_ready)
            self.assertEqual(state.settings.FFMPEG_BINARY_PATH, "before-ffmpeg")
        finally:
            state.release.set()
        with self.assertRaises(RuntimeError) as raised:
            await asyncio.wait_for(state.task, 2)
        self.assertIs(raised.exception, primary)
        self.assertTrue(state.finished.is_set())
        self.assertEqual(len(state.owned_probe_tasks), 1)
        self.assertTrue(state.owned_probe_tasks[0].done())
        state.probe.assert_called_once()
        state.rag.ensure_collection.assert_not_awaited()

    async def test_startup_cancellation_drains_pending_probe(self):
        state = self._startup(block_database=True)
        try:
            await asyncio.wait_for(state.prefix.wait(), 2)
            state.task.cancel()
            await asyncio.wait_for(state.cleanup.wait(), 2)
            self.assertFalse(state.task.done())
            self.assertFalse(state.runtime.api_ready)
            state.task.cancel()  # Repeated cancellation must not cancel the owned probe task.
            await asyncio.sleep(0)
            self.assertFalse(state.task.done())
            self.assertFalse(state.owned_probe_tasks[0].cancelled())
        finally:
            state.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(state.task, 2)
        self.assertTrue(state.finished.is_set())
        self.assertEqual(len(state.owned_probe_tasks), 1)
        self.assertFalse(state.owned_probe_tasks[0].cancelled())
        state.models.shutdown_native_model_store.assert_called_once_with()
        self.assertEqual(state.runtime.startup_error, "Native startup cancelled")
        state.rag.ensure_collection.assert_not_awaited()

