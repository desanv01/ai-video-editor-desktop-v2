#!/usr/bin/env python3
"""Run a redirected-root RC.6 native product smoke and emit redacted evidence.

This runner never discovers global media tools: absolute engine, FFmpeg and
FFprobe paths are explicit inputs.  It creates a valid short MP4, imports it
through the durable native-operation API, performs a provider-free render as
a durable engine job, restarts the engine against the same root, and verifies
project/import/job/export persistence plus playable output.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


PROTOCOL = "desktop.engine-handshake.v2"
ENGINE_ID = "aive-engine"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True, help="Frozen engine executable or backend/native_engine.py")
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True, help="Dedicated redirected test root; it is never deleted")
    parser.add_argument("--evidence", type=Path, help="Defaults to <data-root>/Logs/rc6-native-product-e2e.json")
    return parser.parse_args()


def run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)


def api(base: str, token: str, method: str, path: str, body: object | None = None) -> object:
    encoded = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    request = urllib.request.Request(
        base + path,
        data=encoded,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {path} failed with {error.code}: {error.read().decode(errors='replace')}") from error


def handshake_message(value: dict[str, object]) -> bytes:
    return "\n".join(
        str(value[key])
        for key in (
            "protocolVersion", "sessionId", "nonce", "pid", "componentId",
            "componentVersion", "host", "assignedPort",
        )
    ).encode()


def launch_engine(engine: Path, root: Path, component_root: Path) -> tuple[subprocess.Popen[str], str, str, dict[str, object]]:
    token = secrets.token_urlsafe(32)
    session = secrets.token_urlsafe(12)
    nonce = secrets.token_urlsafe(24)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(30)
    address = f"127.0.0.1:{listener.getsockname()[1]}"
    command = ([sys.executable, str(engine)] if engine.suffix.lower() == ".py" else [str(engine)]) + [
        "--data-root", str(root), "--port", "0",
        "--ffmpeg-component-root", str(component_root),
    ]
    environment = os.environ.copy()
    environment.update({
        "AIVE_ENGINE_BEARER_TOKEN": token,
        "AIVE_ENGINE_SESSION_ID": session,
        "AIVE_ENGINE_CONTROL_ADDRESS": address,
        "AIVE_ENGINE_CONTROL_NONCE": nonce,
    })
    process = subprocess.Popen(
        command,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        connection, peer = listener.accept()
        if peer[0] != "127.0.0.1":
            raise RuntimeError("engine control peer was not loopback")
        with connection:
            raw = connection.makefile("rb").readline(16 * 1024 + 1)
        if len(raw) > 16 * 1024:
            raise RuntimeError("engine control message exceeded 16 KiB")
        handshake = json.loads(raw)
        expected = hmac.new(token.encode(), handshake_message(handshake), hashlib.sha256).hexdigest()
        source_mode = engine.suffix.lower() == ".py"
        checks = {
            "protocol": handshake.get("protocolVersion") == PROTOCOL,
            "session": handshake.get("sessionId") == session,
            "nonce": handshake.get("nonce") == nonce,
            # A Windows Python launcher may insert a child interpreter for a
            # source run. Frozen product evidence requires the direct owned PID.
            "pid": (
                isinstance(handshake.get("pid"), int) and handshake["pid"] > 0
                if source_mode
                else handshake.get("pid") == process.pid
            ),
            "component": handshake.get("componentId") == ENGINE_ID,
            "host": handshake.get("host") == "127.0.0.1",
            "port": isinstance(handshake.get("assignedPort"), int),
            "hmac": hmac.compare_digest(str(handshake.get("hmacSha256", "")), expected),
        }
        if not all(checks.values()):
            failed = ",".join(name for name, passed in checks.items() if not passed)
            raise RuntimeError(f"engine control message failed checks: {failed}")
        base = f"http://127.0.0.1:{handshake['assignedPort']}"
        api(base, token, "GET", "/readiness")
        return process, base, token, handshake
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        listener.close()


def stop_engine(process: subprocess.Popen[str], base: str, token: str) -> None:
    api(base, token, "POST", "/engine-control/shutdown")
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError("engine did not stop within the bounded shutdown deadline")
    if process.returncode != 0:
        output = process.stdout.read()[-2000:] if process.stdout else ""
        raise RuntimeError(f"engine stopped with {process.returncode}: {output}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    engine, ffmpeg, ffprobe = (path.resolve(strict=True) for path in (args.engine, args.ffmpeg, args.ffprobe))
    root = args.data_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / "Temp" / "rc6-e2e-source.mp4"
    output = root / "Exports" / "rc6-e2e-export.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    run([
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "testsrc2=size=320x180:rate=24", "-t", "2", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-an", str(source),
    ])
    source_probe = json.loads(run([str(ffprobe), "-v", "error", "-show_entries", "format=duration,size", "-of", "json", str(source)]).stdout)

    process, base, token, first_handshake = launch_engine(engine, root, ffmpeg.parent)
    project = api(base, token, "POST", "/api/v1/projects", {"title": "RC6 Redirected Root E2E"})
    project_id = str(project["id"])
    init = api(base, token, "POST", f"/api/v1/projects/{project_id}/imports/native/primary/init", {
        "original_filename": source.name, "file_size_bytes": source.stat().st_size, "mime_type": "video/mp4",
    })
    operation_id = str(init["operation_id"])
    api(base, token, "POST", f"/api/v1/projects/{project_id}/imports/native/primary/{operation_id}/progress", {"phase": "copying"})
    uploads = root / "Uploads"
    part = uploads / str(init["staging_part_relative_path"])
    staged = uploads / str(init["staging_relative_path"])
    part.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, part.open("wb") as writer:
        for chunk in iter(lambda: reader.read(8 * 1024 * 1024), b""):
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    os.replace(part, staged)
    api(base, token, "POST", f"/api/v1/projects/{project_id}/imports/native/primary/{operation_id}/progress", {"phase": "staged"})
    finalized = api(base, token, "POST", f"/api/v1/projects/{project_id}/imports/native/primary/{operation_id}/finalize", {
        "copied_file_size_bytes": source.stat().st_size,
    })
    imported_candidates = list((uploads / "projects" / project_id / "assets").glob("*.mp4"))
    if len(imported_candidates) != 1:
        raise RuntimeError(f"expected exactly one imported MP4, found {len(imported_candidates)}")
    imported = imported_candidates[0]

    job = api(base, token, "POST", "/api/v1/jobs", {"kind": "rc6-provider-free-render", "payload": {"projectId": project_id}})
    job_id = str(job["job_id"])
    api(base, token, "POST", f"/api/v1/jobs/{job_id}/status", {"status": "running", "payload": {"phase": "rendering"}})
    run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(imported), "-vf", "scale=320:180", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output)])
    output_probe = json.loads(run([str(ffprobe), "-v", "error", "-show_entries", "format=duration,size", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height", "-of", "json", str(output)]).stdout)
    api(base, token, "POST", f"/api/v1/jobs/{job_id}/events", {"eventType": "export.playable", "payload": {"relativePath": "Exports/rc6-e2e-export.mp4", "sha256": sha256(output)}})
    api(base, token, "POST", f"/api/v1/jobs/{job_id}/status", {"status": "completed", "result": {"relativePath": "Exports/rc6-e2e-export.mp4", "playable": True}})
    stop_engine(process, base, token)

    restarted, restart_base, restart_token, second_handshake = launch_engine(engine, root, ffmpeg.parent)
    persisted_project = api(restart_base, restart_token, "GET", f"/api/v1/projects/{project_id}")
    persisted_import = api(restart_base, restart_token, "GET", f"/api/v1/projects/{project_id}/imports/native/primary/{operation_id}")
    persisted_job = api(restart_base, restart_token, "GET", f"/api/v1/jobs/{job_id}")
    stop_engine(restarted, restart_base, restart_token)
    if persisted_import["phase"] != "completed" or persisted_job["status"] != "completed" or not output.is_file():
        raise RuntimeError("redirected-root restart persistence verification failed")

    evidence = {
        "schemaVersion": "desktop.rc6-native-product-e2e.v1",
        "status": "pass",
        "engine": {"componentId": first_handshake["componentId"], "componentVersion": first_handshake["componentVersion"], "handshakeProtocol": PROTOCOL, "restartedPidChanged": first_handshake["pid"] != second_handshake["pid"]},
        "source": {"relativePath": "Temp/rc6-e2e-source.mp4", "sha256": sha256(source), "probe": source_probe},
        "project": {"id": project_id, "persisted": str(persisted_project["id"]) == project_id, "videoId": finalized["id"]},
        "import": {"operationId": operation_id, "phase": persisted_import["phase"], "eventTypes": [event["eventType"] for event in persisted_import["events"]]},
        "render": {"jobId": job_id, "status": persisted_job["status"], "relativePath": "Exports/rc6-e2e-export.mp4", "sha256": sha256(output), "probe": output_probe},
        "security": {"stdoutUsedForHandshake": False, "secretsEmitted": False, "dataRoot": "<redirected-root>"},
    }
    evidence_path = (args.evidence or root / "Logs" / "rc6-native-product-e2e.json").resolve()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        raise SystemExit(f"rc6-native-product-e2e.py: error: {error}")
