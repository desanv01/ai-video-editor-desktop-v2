"""Small deterministic Phase 5 supervisor fixture; never a production engine."""

from __future__ import annotations

import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


TOKEN = os.environ.get("AIVE_ENGINE_BEARER_TOKEN", "")
MODE = os.environ.get("AIVE_FAKE_ENGINE_MODE", "ready")
PORT = int(os.environ.get("AIVE_ENGINE_PORT", "0"))
PID = os.getpid()


def _payload(path: str) -> dict[str, object]:
    if path == "/capabilities":
        return {
            "schemaVersion": "desktop.capabilities.v1",
            "componentId": "aive-engine",
            "componentVersion": "1.0.0",
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
            "componentVersion": "1.0.0",
        },
        "checks": {
            "api": {"state": "healthy", "required": True, "detail": "fixture", "remediationCodes": []},
            "database": {"state": "ready", "required": True, "detail": "fixture", "remediationCodes": []},
            "vectorStore": {"state": "ready", "required": False, "detail": "fixture", "remediationCodes": []},
            "ffmpeg": {"state": "ready", "required": True, "detail": "fixture", "remediationCodes": []},
        },
        "capabilities": {"available": ["api", "database", "ffmpeg"], "degraded": [], "unavailable": []},
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
        "protocolVersion": "desktop.engine-handshake.v1",
        "host": "127.0.0.1",
        "port": assigned,
        "pid": PID,
    }
    if MODE == "wrong-protocol":
        handshake["protocolVersion"] = "desktop.engine-handshake.v0"
        sys.stdout.write(json.dumps(handshake, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    elif MODE == "wrong-host":
        handshake["host"] = "0.0.0.0"
        sys.stdout.write(json.dumps(handshake, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    elif MODE == "malformed":
        sys.stdout.write('{"type":"aive-engine-startup"\n')
        sys.stdout.flush()
    elif MODE == "oversized":
        sys.stdout.write(json.dumps({"type": "aive-engine-startup", "padding": "x" * 20_000}) + "\n")
        sys.stdout.flush()
    else:
        sys.stdout.write(json.dumps(handshake, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    signal.signal(signal.SIGTERM, lambda *_args: server.shutdown())
    server.serve_forever()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
