"""Deterministic authenticated loopback-control fake-engine tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "desktop-v2" / "fake-engine" / "fake_engine.py"
TOKEN = "phase5-fixture-token-123456789012345678"
SESSION = "fixture-session-0001"
NONCE = "fixture-control-nonce-00000001"


class Phase5FakeEngineTests(unittest.TestCase):
    def _start(self, mode: str) -> tuple[subprocess.Popen[str], socket.socket]:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)
        host, port = listener.getsockname()
        environment = os.environ.copy()
        environment.update(
            {
                "AIVE_ENGINE_BEARER_TOKEN": TOKEN,
                "AIVE_ENGINE_SESSION_ID": SESSION,
                "AIVE_ENGINE_CONTROL_ADDRESS": f"{host}:{port}",
                "AIVE_ENGINE_CONTROL_NONCE": NONCE,
                "AIVE_ENGINE_PORT": "0",
                "AIVE_FAKE_ENGINE_MODE": mode,
            }
        )
        return (
            subprocess.Popen(
                [sys.executable, str(FIXTURE)],
                cwd=str(REPO_ROOT),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ),
            listener,
        )

    def _control_message(self, listener: socket.socket) -> bytes:
        connection, peer = listener.accept()
        self.assertEqual(peer[0], "127.0.0.1")
        with connection:
            chunks = bytearray()
            while not chunks.endswith(b"\n"):
                chunk = connection.recv(4096)
                if not chunk:
                    break
                chunks.extend(chunk)
            return bytes(chunks).rstrip(b"\r\n")

    def _stop(self, process: subprocess.Popen[str], listener: socket.socket) -> None:
        listener.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()

    def test_ready_port_zero_hmac_auth_and_graceful_stop(self):
        process, listener = self._start("ready")
        try:
            raw = self._control_message(listener)
            handshake = json.loads(raw)
            self.assertEqual(handshake["protocolVersion"], "desktop.engine-handshake.v2")
            self.assertEqual(handshake["sessionId"], SESSION)
            self.assertEqual(handshake["nonce"], NONCE)
            self.assertEqual(handshake["componentId"], "aive-engine")
            self.assertGreater(handshake["assignedPort"], 0)
            canonical = "\n".join(
                str(handshake[key])
                for key in (
                    "protocolVersion", "sessionId", "nonce", "pid", "componentId",
                    "componentVersion", "host", "assignedPort",
                )
            ).encode()
            expected = hmac.new(TOKEN.encode(), canonical, hashlib.sha256).hexdigest()
            self.assertTrue(hmac.compare_digest(handshake["hmacSha256"], expected))
            self.assertNotIn(TOKEN.encode(), raw)

            base = f"http://127.0.0.1:{handshake['assignedPort']}"
            with httpx.Client(timeout=5) as client:
                self.assertEqual(client.get(base + "/readiness").status_code, 401)
                headers = {"Authorization": f"Bearer {TOKEN}"}
                self.assertEqual(client.get(base + "/readiness", headers=headers).status_code, 200)
                self.assertEqual(client.post(base + "/engine-control/shutdown", headers=headers).status_code, 200)
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            self._stop(process, listener)

    def test_adversarial_control_messages_are_deterministic(self):
        modes = (
            "wrong-protocol", "wrong-host", "wrong-hmac", "wrong-pid", "wrong-session",
            "wrong-nonce", "wrong-component", "wrong-version", "malformed", "oversized",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                process, listener = self._start(mode)
                try:
                    raw = self._control_message(listener)
                    self.assertTrue(raw)
                    self.assertNotIn(TOKEN.encode(), raw)
                finally:
                    self._stop(process, listener)

    def test_stdout_close_is_nonfatal_before_control_success(self):
        process, listener = self._start("stdout-close-before-control")
        try:
            handshake = json.loads(self._control_message(listener))
            self.assertGreater(handshake["assignedPort"], 0)
            self.assertIsNone(process.poll())
        finally:
            self._stop(process, listener)

    def test_timeout_and_crash_do_not_publish_control_message(self):
        timeout_process, listener = self._start("timeout")
        try:
            with self.assertRaises(socket.timeout):
                self._control_message(listener)
            self.assertIsNone(timeout_process.poll())
        finally:
            self._stop(timeout_process, listener)

        crash_process, crash_listener = self._start("crash")
        try:
            self.assertEqual(crash_process.wait(timeout=5), 17)
        finally:
            self._stop(crash_process, crash_listener)


if __name__ == "__main__":
    unittest.main()
