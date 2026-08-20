"""Deterministic Phase 5 fake-engine protocol and lifecycle tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "desktop-v2" / "fake-engine" / "fake_engine.py"
TOKEN = "phase5-fixture-token-123456789012345678"


class Phase5FakeEngineTests(unittest.TestCase):
    def _start(self, mode: str) -> subprocess.Popen[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "AIVE_ENGINE_BEARER_TOKEN": TOKEN,
                "AIVE_ENGINE_PORT": "0",
                "AIVE_FAKE_ENGINE_MODE": mode,
            }
        )
        return subprocess.Popen(
            [sys.executable, str(FIXTURE)],
            cwd=str(REPO_ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def _read_line(self, process: subprocess.Popen[str]) -> str:
        assert process.stdout is not None
        line = process.stdout.readline()
        self.assertTrue(line, "fake engine did not emit its deterministic fixture line")
        return line.rstrip("\r\n")

    def test_ready_port_zero_auth_and_graceful_stop(self):
        process = self._start("ready")
        try:
            handshake_line = self._read_line(process)
            handshake = json.loads(handshake_line)
            self.assertEqual(handshake["type"], "aive-engine-startup")
            self.assertEqual(handshake["protocolVersion"], "desktop.engine-handshake.v1")
            self.assertEqual(handshake["host"], "127.0.0.1")
            self.assertGreater(handshake["port"], 0)
            self.assertGreater(handshake["pid"], 0)
            self.assertNotIn(TOKEN, handshake_line)

            base = f"http://127.0.0.1:{handshake['port']}"
            with httpx.Client(timeout=5) as client:
                self.assertEqual(client.get(base + "/readiness").status_code, 401)
                self.assertEqual(
                    client.get(base + "/readiness", headers={"Authorization": f"Bearer {TOKEN}"}).status_code,
                    200,
                )
                self.assertEqual(
                    client.get(base + "/readiness", headers={"Authorization": "Bearer wrong-token"}).status_code,
                    401,
                )
                self.assertEqual(
                    client.post(
                        base + "/engine-control/shutdown",
                        headers={"Authorization": f"Bearer {TOKEN}"},
                    ).status_code,
                    200,
                )
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()

    def test_handshake_failure_modes_are_deterministic(self):
        expected_markers = {
            "wrong-protocol": '"protocolVersion":"desktop.engine-handshake.v0"',
            "wrong-host": '"host":"0.0.0.0"',
            "malformed": '{"type":"aive-engine-startup"',
            "oversized": '"padding":',
        }
        for mode, marker in expected_markers.items():
            with self.subTest(mode=mode):
                process = self._start(mode)
                try:
                    line = self._read_line(process)
                    self.assertIn(marker, line)
                    self.assertNotIn(TOKEN, line)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                    if process.stdout is not None:
                        process.stdout.close()

    def test_timeout_and_crash_modes_do_not_publish_ready(self):
        timeout_process = self._start("timeout")
        try:
            time.sleep(0.25)
            self.assertIsNone(timeout_process.poll())
        finally:
            timeout_process.kill()
            timeout_process.wait(timeout=5)
            if timeout_process.stdout is not None:
                timeout_process.stdout.close()

        crash_process = self._start("crash")
        self.assertEqual(crash_process.wait(timeout=5), 17)
        if crash_process.stdout is not None:
            crash_process.stdout.close()


if __name__ == "__main__":
    unittest.main()
