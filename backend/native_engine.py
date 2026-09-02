"""Native Desktop V2 core-engine entrypoint.

This source entrypoint is also the PyInstaller onedir entrypoint.  It never
starts Docker/Compose, never searches for a system FFmpeg in native mode and
does not enable development reload.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import importlib
import json
import os
import re
import signal
import sys
import time
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent
APP_ROOT = BACKEND_ROOT / "app"
STARTUP_HANDSHAKE_PROTOCOL = "desktop.engine-handshake.v2"
ENGINE_ID = "aive-engine"
ENGINE_VERSION = "2.0.0-rc.6"
SELF_TEST_DEADLINE_SECONDS = 15.0
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Video Editor native desktop core engine")
    parser.add_argument("--data-root", default=os.environ.get("AIVE_DESKTOP_DATA_ROOT"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AIVE_ENGINE_PORT", "0")))
    parser.add_argument(
        "--bearer-token",
        default=os.environ.get("AIVE_ENGINE_BEARER_TOKEN", ""),
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("AIVE_ENGINE_SESSION_ID", ""),
    )
    parser.add_argument(
        "--control-address",
        default=os.environ.get("AIVE_ENGINE_CONTROL_ADDRESS", ""),
        help="Supervisor-owned 127.0.0.1 host:port for the authenticated startup control message.",
    )
    parser.add_argument(
        "--control-nonce",
        default=os.environ.get("AIVE_ENGINE_CONTROL_NONCE", ""),
        help="Per-launch supervisor nonce authenticated by the startup HMAC.",
    )
    parser.add_argument(
        "--ffmpeg-component-root",
        default=os.environ.get("AIVE_FFMPEG_COMPONENT_ROOT"),
    )
    parser.add_argument(
        "--component-root",
        default=os.environ.get("AIVE_DESKTOP_COMPONENT_ROOT"),
    )
    parser.add_argument(
        "--allow-tool-fixture",
        action="store_true",
        help="Enable only deterministic test command fixtures; never use in production.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Validate the frozen/source entrypoint without starting the API.",
    )
    return parser


def _contract_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "contracts" / "desktop-v2" / "schemas"
    return BACKEND_ROOT.parent / "contracts" / "desktop-v2" / "schemas"


def _self_test() -> int:
    """Run bounded, offline checks that exercise the actual frozen imports.

    The build wrapper also enforces a subprocess timeout.  Keeping the checks
    offline and read-only makes this safe to run before activation on a clean
    machine without creating a user profile or touching project data.
    """

    started = time.monotonic()
    checks: list[str] = []
    for module_name in (
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "aiosqlite",
        "desktop_native.app",
        "desktop_native.runtime",
        "services.native_imports",
    ):
        importlib.import_module(module_name)
        checks.append(f"import:{module_name}")
        if time.monotonic() - started > SELF_TEST_DEADLINE_SECONDS:
            raise TimeoutError("native engine self-test exceeded its internal deadline")

    contract_root = _contract_root()
    for filename in (
        "engine-control.v1.schema.json",
        "engine-handshake.v2.schema.json",
        "health-readiness.v1.schema.json",
        "native-import-operation.v1.schema.json",
    ):
        payload = json.loads((contract_root / filename).read_text(encoding="utf-8"))
        if payload.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError(f"unsupported or missing JSON schema marker in {filename}")
        checks.append(f"contract:{filename}")

    frozen = bool(getattr(sys, "frozen", False))
    print(
        json.dumps(
            {
                "schemaVersion": "desktop.engine-self-test.v1",
                "component": ENGINE_ID,
                "version": ENGINE_VERSION,
                "profile": "desktop-native",
                "packaging": "onedir",
                "runtime": "frozen" if frozen else "source",
                "frozen": frozen,
                "status": "ok",
                "checks": checks,
                "durationMs": round((time.monotonic() - started) * 1000),
                "deadlineMs": round(SELF_TEST_DEADLINE_SECONDS * 1000),
            },
            sort_keys=True,
        )
    )
    return 0


def _handshake_message(
    *,
    session_id: str,
    nonce: str,
    pid: int,
    component_id: str,
    component_version: str,
    host: str,
    assigned_port: int,
) -> bytes:
    """Return the stable v2 HMAC input shared with the native supervisor."""

    return "\n".join(
        (
            STARTUP_HANDSHAKE_PROTOCOL,
            session_id,
            nonce,
            str(pid),
            component_id,
            component_version,
            host,
            str(assigned_port),
        )
    ).encode("utf-8")


def build_startup_handshake(
    *,
    session_id: str,
    bearer_token: str,
    assigned_port: int,
    pid: int | None = None,
    nonce: str,
) -> dict[str, object]:
    """Build an authenticated diagnostic describing the bound loopback API."""

    process_id = pid or os.getpid()
    host = "127.0.0.1"
    proof = hmac.new(
        bearer_token.encode("utf-8"),
        _handshake_message(
            session_id=session_id,
            nonce=nonce,
            pid=process_id,
            component_id=ENGINE_ID,
            component_version=ENGINE_VERSION,
            host=host,
            assigned_port=assigned_port,
        ),
        hashlib.sha256,
    ).hexdigest()
    return {
        "type": "aive-engine-startup",
        "protocolVersion": STARTUP_HANDSHAKE_PROTOCOL,
        "sessionId": session_id,
        "nonce": nonce,
        "pid": process_id,
        "componentId": ENGINE_ID,
        "componentVersion": ENGINE_VERSION,
        "host": host,
        "assignedPort": assigned_port,
        "hmacSha256": proof,
    }


def _configure_environment(args: argparse.Namespace) -> object:
    if not args.data_root:
        raise SystemExit("--data-root or AIVE_DESKTOP_DATA_ROOT is required")
    if args.port < 0 or args.port > 65535:
        raise SystemExit("--port must be between 0 and 65535")
    if len(args.bearer_token) < 32:
        raise SystemExit("--bearer-token or AIVE_ENGINE_BEARER_TOKEN must be at least 32 characters")
    if not args.session_id or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", args.session_id):
        raise SystemExit("--session-id or AIVE_ENGINE_SESSION_ID must be a valid supervisor session")
    if not args.control_nonce or not re.fullmatch(r"[A-Za-z0-9_-]{22,128}", args.control_nonce):
        raise SystemExit("--control-nonce or AIVE_ENGINE_CONTROL_NONCE must be a valid supervisor nonce")
    control_host, separator, control_port = args.control_address.rpartition(":")
    if separator != ":" or control_host != "127.0.0.1":
        raise SystemExit("--control-address must identify a supervisor-owned 127.0.0.1 port")
    try:
        parsed_control_port = int(control_port)
    except ValueError as exc:
        raise SystemExit("--control-address port must be an integer") from exc
    if parsed_control_port < 1 or parsed_control_port > 65535:
        raise SystemExit("--control-address port must be between 1 and 65535")

    # Import only the isolated path module before selecting the profile.
    from desktop_native.paths import NativeDesktopPaths

    if args.component_root:
        os.environ["AIVE_DESKTOP_COMPONENT_ROOT"] = str(args.component_root)
    if args.ffmpeg_component_root:
        os.environ["AIVE_FFMPEG_COMPONENT_ROOT"] = str(args.ffmpeg_component_root)
    os.environ["AIVE_DESKTOP_DATA_ROOT"] = str(args.data_root)
    paths = NativeDesktopPaths.from_environment()

    os.environ.update(paths.settings_environment())
    os.environ.update(
        {
            "RUNTIME_PROFILE": "desktop-native",
            "APP_ENV": "desktop-native",
            "APP_DEBUG": "false",
            "AIVE_ENGINE_BEARER_TOKEN": args.bearer_token,
            "AIVE_ENGINE_SESSION_ID": args.session_id or "native-session",
            "DESKTOP_BEARER_TOKEN": args.bearer_token,
            "DESKTOP_SESSION_ID": args.session_id or "native-session",
            "AIVE_ENGINE_PORT": str(args.port),
            "AIVE_ENGINE_CONTROL_ADDRESS": args.control_address,
            "AIVE_ENGINE_CONTROL_NONCE": args.control_nonce,
        }
    )
    if args.allow_tool_fixture:
        os.environ["AIVE_NATIVE_TEST_TOOL_FIXTURE"] = "1"
    paths.ensure_directories()
    return paths


async def _publish_control_handshake(args: argparse.Namespace, assigned_port: int) -> None:
    control_host, _, control_port = args.control_address.rpartition(":")
    message = build_startup_handshake(
        session_id=args.session_id,
        bearer_token=args.bearer_token,
        assigned_port=assigned_port,
        nonce=args.control_nonce,
    )
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(control_host, int(control_port)),
        timeout=5.0,
    )
    del reader
    try:
        encoded = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(encoded) > 16 * 1024:
            raise RuntimeError("startup control message exceeded the bounded payload limit")
        writer.write(encoded + b"\n")
        await asyncio.wait_for(writer.drain(), timeout=5.0)
    finally:
        writer.close()
        await writer.wait_closed()


async def _serve(args: argparse.Namespace) -> None:
    paths = _configure_environment(args)
    from config import settings
    from desktop_native.app import create_native_app
    from desktop_native.logging_setup import configure_logging
    from desktop_native.runtime import NativeDesktopRuntime

    configure_logging(str(paths.logs / "engine.log"))
    runtime = NativeDesktopRuntime.from_settings(requested_port=args.port)
    app = create_native_app(runtime)

    import uvicorn

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=args.port,
        reload=False,
        access_log=False,
        log_config=None,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    # The supervisor uses an authenticated in-process control route for a
    # graceful stop.  The callback is installed only after the server object
    # exists and is never serialized into engine-control payloads.
    app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
    loop = asyncio.get_running_loop()

    def request_shutdown(*_signal_args) -> None:  # type: ignore[no-untyped-def]
        server.should_exit = True

    signal_numbers = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        signal_numbers.append(signal.SIGBREAK)
    for signum in signal_numbers:
        try:
            loop.add_signal_handler(signum, request_shutdown)
        except (NotImplementedError, RuntimeError):
            signal.signal(signum, request_shutdown)

    # Explicit startup/main-loop/shutdown keeps reload impossible and lets us
    # publish the OS-assigned port for a future Phase 5 supervisor.
    if not config.loaded:
        config.load()
    server.lifespan = config.lifespan_class(config)
    await server.startup()
    if server.servers:
        sockets = server.servers[0].sockets
        if sockets:
            runtime.assigned_port = int(sockets[0].getsockname()[1])
    if not runtime.assigned_port:
        raise RuntimeError("native engine did not receive an OS-assigned loopback port")
    # Stdout/stderr are diagnostics only.  Startup identity and port
    # discovery travel over the supervisor-owned authenticated loopback
    # control channel so readiness never depends on stdout framing or lifetime.
    await _publish_control_handshake(args, runtime.assigned_port)
    try:
        await server.main_loop()
    finally:
        await server.shutdown()


def main() -> int:
    args = _parser().parse_args()
    if args.self_test:
        return _self_test()
    try:
        asyncio.run(_serve(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
