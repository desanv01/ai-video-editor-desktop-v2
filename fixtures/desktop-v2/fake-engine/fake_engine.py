"""Small deterministic Phase 5 supervisor fixture; never a production engine."""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import signal
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


TOKEN = os.environ.get("AIVE_ENGINE_BEARER_TOKEN", "")
MODE = os.environ.get("AIVE_FAKE_ENGINE_MODE", "ready")
PORT = int(os.environ.get("AIVE_ENGINE_PORT", "0"))
SESSION_ID = os.environ.get("AIVE_ENGINE_SESSION_ID", "fixture-session")
CONTROL_ADDRESS = os.environ.get("AIVE_ENGINE_CONTROL_ADDRESS", "")
CONTROL_NONCE = os.environ.get("AIVE_ENGINE_CONTROL_NONCE", "fixture-control-nonce-000000")
COMPONENT_VERSION = os.environ.get("AIVE_FAKE_ENGINE_COMPONENT_VERSION", "1.0.0")
PID = os.getpid()
PROTOCOL = "desktop.engine-handshake.v2"


def _canonical(handshake: dict[str, object]) -> bytes:
    return "\n".join(
        str(handshake[key])
        for key in (
            "protocolVersion",
            "sessionId",
            "nonce",
            "pid",
            "componentId",
            "componentVersion",
            "host",
            "assignedPort",
        )
    ).encode("utf-8")


def _send_control(payload: bytes) -> None:
    host, separator, port = CONTROL_ADDRESS.rpartition(":")
    if separator != ":" or host != "127.0.0.1":
        raise RuntimeError("fake engine requires a supervisor-owned loopback control address")
    with socket.create_connection((host, int(port)), timeout=5) as control:
        control.sendall(payload + b"\n")


def _payload(path: str) -> dict[str, object]:
    if path == "/capabilities":
        return {
            "schemaVersion": "desktop.capabilities.v1",
            "componentId": "aive-engine",
            "componentVersion": COMPONENT_VERSION,
            "generatedAt": "2026-08-20T00:00:00Z",
            "requested": ["api", "database", "ffmpeg"],
            "items": [
                {"id": "api", "state": "available", "source": "component"},
                {"id": "database", "state": "available", "source": "backend"},
                {"id": "ffmpeg", "state": "available", "source": "component"},
            ],
        }
    state = "degraded" if MODE == "degraded" else "ready"
    return {
        "schemaVersion": "desktop.health-readiness.v1",
        "generatedAt": "2026-08-20T00:00:00Z",
        "overallState": state,
        "process": {
            "alive": True,
            "pid": PID,
            "componentId": "aive-engine",
            "componentVersion": COMPONENT_VERSION,
        },
        "checks": {
            "api": {"state": "healthy", "required": True, "detail": "fixture", "remediationCodes": []},
            "database": {"state": "ready", "required": True, "detail": "fixture", "remediationCodes": []},
            "vectorStore": {"state": "ready", "required": False, "detail": "fixture", "remediationCodes": []},
            "ffmpeg": {"state": "ready", "required": True, "detail": "fixture", "remediationCodes": []},
            "nativeImport": {"state": "ready", "required": True, "detail": "fixture", "remediationCodes": []},
        },
        "capabilities": {"available": ["api", "database", "ffmpeg", "native-import"], "degraded": [], "unavailable": []},
        "remediationCodes": [],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _authorized(self) -> bool:
        return self.headers.get("Authorization", "") == f"Bearer {TOKEN}"

    def _write(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._write(401, {"detail": "fixture auth required"})
            return
        if self.path in {"/readiness", "/health"}:
            self._write(200, _payload("/readiness"))
        elif self.path == "/capabilities":
            self._write(200, _payload("/capabilities"))
        else:
            self._write(404, {"detail": "fixture route not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._write(401, {"detail": "fixture auth required"})
            return
        if self.path == "/engine-control/shutdown":
            self._write(200, {"status": "accepted"})
            self.server.shutdown()
            return
        self._write(404, {"detail": "fixture route not found"})


def main() -> int:
    if MODE == "crash":
        return 17
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    assigned = int(server.server_address[1])
    if MODE == "timeout":
        # Bind successfully but never publish a handshake.  The supervisor
        # must enforce its own startup deadline and owned-process cleanup.
        signal.signal(signal.SIGTERM, lambda *_args: server.server_close())
        server.serve_forever()
        return 0
    handshake: dict[str, object] = {
        "type": "aive-engine-startup",
        "protocolVersion": PROTOCOL,
        "sessionId": SESSION_ID,
        "nonce": CONTROL_NONCE,
        "componentId": "aive-engine",
        "componentVersion": COMPONENT_VERSION,
        "host": "127.0.0.1",
        "assignedPort": assigned,
        "pid": PID,
    }
    if MODE == "wrong-protocol":
        handshake["protocolVersion"] = "desktop.engine-handshake.v0"
    elif MODE == "wrong-host":
        handshake["host"] = "0.0.0.0"
    elif MODE == "wrong-pid":
        handshake["pid"] = PID + 1
    elif MODE == "wrong-session":
        handshake["sessionId"] = "wrong-session"
    elif MODE == "wrong-nonce":
        handshake["nonce"] = "wrong-control-nonce-00000000"
    elif MODE == "wrong-component":
        handshake["componentId"] = "other-engine"
    elif MODE == "wrong-version":
        handshake["componentVersion"] = "9.9.9"
    handshake["hmacSha256"] = hmac.new(TOKEN.encode(), _canonical(handshake), hashlib.sha256).hexdigest()
    if MODE == "wrong-hmac":
        handshake["hmacSha256"] = "0" * 64
    if MODE == "malformed":
        control_payload = b'{"type":"aive-engine-startup"'
    elif MODE == "oversized":
        control_payload = json.dumps({"type": "aive-engine-startup", "padding": "x" * 20_000}).encode()
    else:
        control_payload = json.dumps(handshake, separators=(",", ":")).encode()
    if MODE == "stdout-close-before-control":
        os.close(sys.stdout.fileno())
    _send_control(control_payload)
    signal.signal(signal.SIGTERM, lambda *_args: server.shutdown())
    server.serve_forever()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
