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
import stat
import sys
import time
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent
APP_ROOT = BACKEND_ROOT / "app"
STARTUP_HANDSHAKE_PROTOCOL = "desktop.engine-handshake.v2"
ENGINE_ID = "aive-engine"
ENGINE_VERSION = "2.1.0-rebuild.2"
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
    parser.add_argument("--whisper-component-root", default=os.environ.get("AIVE_WHISPER_COMPONENT_ROOT"))
    parser.add_argument("--whisper-binary-path", default=os.environ.get("AIVE_WHISPER_BINARY_PATH"))
    parser.add_argument("--whisper-model-path", default=os.environ.get("AIVE_WHISPER_MODEL_PATH"))
    parser.add_argument(
        "--documents-component-root",
        default=os.environ.get("AIVE_DOCUMENTS_COMPONENT_ROOT"),
    )
    parser.add_argument(
        "--libreoffice-binary-path",
        default=os.environ.get("AIVE_LIBREOFFICE_BINARY_PATH"),
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
    """Exercise native imports offline within an owned temporary profile."""
    from tempfile import TemporaryDirectory

    # This path module does not import settings or any runtime services.
    from desktop_native.paths import NativeDesktopPaths

    started = time.monotonic()
    with TemporaryDirectory(prefix="aive-engine-self-test-") as temporary_root:
        root = Path(temporary_root).resolve()
        overrides = {
            "data_root": root,
            "database": root / "Config" / "engine.sqlite3",
            "vector_root": root / "VectorStore",
            "uploads": root / "Uploads",
            "proxies": root / "Proxies",
            "temp": root / "Temp",
            "logs": root / "Logs",
            "config": root / "Config",
            "backups": root / "Backups",
            "models": root / "Models",
            "projects": root / "Projects",
            "exports": root / "Exports",
            "components": root / "Components",
            "ffmpeg_component": root / "Components" / "ffmpeg",
        }
        paths = NativeDesktopPaths.from_environment(data_root=root, overrides=overrides)
        environment = paths.settings_environment()
        # Override the AIVE aliases too: later path resolution must not inherit
        # an activated component or storage directory from the caller.
        for name, key in {
            "AIVE_DESKTOP_DATA_ROOT": "data_root",
            "DESKTOP_DATA_ROOT": "data_root",
            "AIVE_DESKTOP_DB_PATH": "database",
            "AIVE_DESKTOP_VECTOR_ROOT": "vector_root",
            "AIVE_DESKTOP_UPLOADS_PATH": "uploads",
            "AIVE_DESKTOP_PROXIES_PATH": "proxies",
            "AIVE_DESKTOP_TEMP_PATH": "temp",
            "AIVE_DESKTOP_LOGS_PATH": "logs",
            "AIVE_DESKTOP_CONFIG_PATH": "config",
            "AIVE_DESKTOP_BACKUPS_PATH": "backups",
            "AIVE_DESKTOP_MODELS_PATH": "models",
            "AIVE_DESKTOP_PROJECTS_PATH": "projects",
            "PROJECTS_PATH": "projects",
            "AIVE_DESKTOP_EXPORTS_PATH": "exports",
            "EXPORTS_PATH": "exports",
            "AIVE_DESKTOP_COMPONENT_ROOT": "components",
            "AIVE_FFMPEG_COMPONENT_ROOT": "ffmpeg_component",
        }.items():
            environment[name] = str(overrides[key])
        environment.update({
            "RUNTIME_PROFILE": "desktop-native",
            "APP_ENV": "desktop-native",
            "APP_DEBUG": "false",
            "DATABASE_URL": f"sqlite+aiosqlite:///{paths.database.as_posix()}",
            "DESKTOP_ENGINE_COMPONENT_ROOT": str(paths.components / "engine"),
            "FFMPEG_BINARY_PATH": str(paths.ffmpeg_component / "bin" / "ffmpeg.exe"),
            "FFPROBE_BINARY_PATH": str(paths.ffmpeg_component / "bin" / "ffprobe.exe"),
            "LOCAL_RUNTIME_PATH": str(paths.components / "local-runtime"),
            "LOCAL_CHAT_MODEL_PATH": str(paths.models / "chat"),
            "LOCAL_EMBEDDING_MODEL_PATH": str(paths.models / "embedding"),
            "LOCAL_VISION_MODEL_PATH": str(paths.models / "vision"),
            "REVIDEO_RENDERER_WORKDIR": str(paths.temp / "revideo"),
        })
        for name in ("AIVE_DOCUMENTS_COMPONENT_ROOT", "LIBREOFFICE_COMPONENT_ROOT"):
            environment[name] = str(paths.components / "documents")
        for name in ("AIVE_LIBREOFFICE_BINARY_PATH", "LIBREOFFICE_BINARY_PATH"):
            environment[name] = str(paths.components / "documents" / "program" / "soffice.com")
        for name in ("AIVE_WHISPER_COMPONENT_ROOT", "WHISPER_CPP_COMPONENT_ROOT"):
            environment[name] = str(paths.components / "whisper")
        for name in ("AIVE_WHISPER_BINARY_PATH", "WHISPER_CPP_BINARY_PATH"):
            environment[name] = str(paths.components / "whisper" / "bin" / "whisper-cli.exe")
        for name in ("AIVE_WHISPER_MODEL_PATH", "WHISPER_CPP_MODEL_PATH", "LOCAL_TRANSCRIPTION_MODEL_PATH"):
            environment[name] = str(paths.models / "ggml-small.bin")
        for name in ("WHISPER_CPP_MODELS_DIR", "LOCAL_TRANSCRIPTION_MODELS_DIR"):
            environment[name] = str(paths.models)
        previous_environment = {name: os.environ.get(name) for name in environment}
        try:
            os.environ.update(environment)
            paths.ensure_directories()
            return _self_test_checks(started)
        finally:
            for name, previous_value in previous_environment.items():
                if previous_value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous_value


def _self_test_checks(started: float) -> int:
    """Run the existing bounded checks after selecting the isolated profile."""
    checks: list[str] = []
    for module_name in (
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "aiosqlite",
        "lancedb",
        "pyarrow",
        "desktop_native.index_journal",
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


def _document_bindings(args: argparse.Namespace) -> tuple[str, str]:
    """Validate activated document paths without importing runtime settings."""
    root_value = str(args.documents_component_root or "").strip()
    binary_value = str(args.libreoffice_binary_path or "").strip()
    if bool(root_value) != bool(binary_value):
        raise SystemExit("Managed documents require both an activated component root and LibreOffice binary path")
    if not root_value:
        return "", ""
    root = Path(root_value)
    binary = Path(binary_value)
    if not root.is_absolute() or not binary.is_absolute():
        raise SystemExit("Managed document component and binary paths must be absolute")
    root = Path(os.path.abspath(root))
    binary = Path(os.path.abspath(binary))
    try:
        binary.relative_to(root)
        for target in (root, binary):
            for part in reversed((target, *target.parents)):
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise SystemExit("Managed document paths cannot contain symlinks or reparse points")
        actual_root = root.resolve(strict=True)
        actual_binary = binary.resolve(strict=True)
        relative_binary = actual_binary.relative_to(actual_root)
        if not actual_root.is_dir() or not stat.S_ISREG(actual_binary.stat().st_mode):
            raise SystemExit("Managed LibreOffice must be a regular file within its activated installation")
        if relative_binary.as_posix().lower() != "program/soffice.com":
            raise SystemExit("Managed LibreOffice must use the activated program/soffice.com CLI")
    except (OSError, ValueError) as exc:
        raise SystemExit("Managed LibreOffice installation is missing or outside its activated root") from exc
    return str(actual_root), str(actual_binary)


def _whisper_bindings(args: argparse.Namespace) -> tuple[str, str, str]:
    values = tuple(str(getattr(args, name, "") or "").strip() for name in (
        "whisper_component_root", "whisper_binary_path", "whisper_model_path",
    ))
    if not any(values):
        return "", "", ""
    if not all(values):
        raise SystemExit("Managed Whisper requires an activated root, binary and model together")
    paths = tuple(Path(value) for value in values)
    if not all(path.is_absolute() for path in paths):
        raise SystemExit("Managed Whisper root, binary and model must be absolute paths")
    root, binary, model = tuple(Path(os.path.abspath(path)) for path in paths)
    try:
        for target in (root, binary, model):
            target.relative_to(root)
            for part in reversed((target, *target.parents)):
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise SystemExit("Managed Whisper paths cannot contain symlinks or reparse points")
        actual_root = root.resolve(strict=True)
        if not actual_root.is_dir():
            raise SystemExit("Managed Whisper component root must be a directory")
        actual_files = []
        for target, expected in ((binary, "bin/whisper-cli.exe"), (model, "models/ggml-small.bin")):
            actual = target.resolve(strict=True)
            if actual.relative_to(actual_root).as_posix().lower() != expected or not stat.S_ISREG(actual.stat().st_mode):
                raise SystemExit("Managed Whisper requires its confined bin/whisper-cli.exe and models/ggml-small.bin")
            actual_files.append(str(actual))
    except (OSError, ValueError) as exc:
        raise SystemExit("Managed Whisper files are missing or outside the activated component; repair the Whisper small component") from exc
    return str(actual_root), *actual_files


def _configure_environment(args: argparse.Namespace) -> object:
    # Native credentials arrive only through the authenticated controller bridge.
    for name in ("MISTRAL_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ALIBABA_API_KEY"):
        os.environ.pop(name, None)
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

    documents_root, libreoffice_binary = _document_bindings(args)
    whisper_root, whisper_binary, whisper_model = _whisper_bindings(args)

    # Import only the isolated path module before selecting the profile.
    from desktop_native.paths import NativeDesktopPaths

    if args.component_root:
        os.environ["AIVE_DESKTOP_COMPONENT_ROOT"] = str(args.component_root)
    if args.ffmpeg_component_root:
        os.environ["AIVE_FFMPEG_COMPONENT_ROOT"] = str(args.ffmpeg_component_root)
    os.environ["AIVE_DESKTOP_DATA_ROOT"] = str(args.data_root)
    paths = NativeDesktopPaths.from_environment()

    os.environ.update(paths.settings_environment())
    # Empty explicit bindings also override inherited/manual settings and dotenv
    # values before any config import; native documents never fall back globally.
    os.environ["LIBREOFFICE_COMPONENT_ROOT"] = documents_root
    os.environ["LIBREOFFICE_BINARY_PATH"] = libreoffice_binary
    os.environ.update({
        "WHISPER_CPP_COMPONENT_ROOT": whisper_root,
        "WHISPER_CPP_BINARY_PATH": whisper_binary,
        "WHISPER_CPP_MODEL_PATH": whisper_model,
        "LOCAL_TRANSCRIPTION_MODEL_PATH": whisper_model,
        "WHISPER_CPP_MODEL_ID": "small",
        "LOCAL_TRANSCRIPTION_MODEL_ID": "small",
        "WHISPER_CPP_MODELS_DIR": "",
        "LOCAL_TRANSCRIPTION_MODELS_DIR": "",
    })
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
