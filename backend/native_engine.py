"""Native Desktop V2 core-engine entrypoint.

This source entrypoint is also the PyInstaller onedir entrypoint.  It never
starts Docker/Compose, never searches for a system FFmpeg in native mode and
does not enable development reload.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent
APP_ROOT = BACKEND_ROOT / "app"
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


def _self_test() -> int:
    print(
        json.dumps(
            {
                "component": "aive-engine",
                "version": "1.0.0",
                "profile": "desktop-native",
                "packaging": "onedir",
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


def _configure_environment(args: argparse.Namespace) -> object:
    if not args.data_root:
        raise SystemExit("--data-root or AIVE_DESKTOP_DATA_ROOT is required")
    if args.port < 0 or args.port > 65535:
        raise SystemExit("--port must be between 0 and 65535")
    if len(args.bearer_token) < 32:
        raise SystemExit("--bearer-token or AIVE_ENGINE_BEARER_TOKEN must be at least 32 characters")

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
        }
    )
    if args.allow_tool_fixture:
        os.environ["AIVE_NATIVE_TEST_TOOL_FIXTURE"] = "1"
    paths.ensure_directories()
    return paths


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
