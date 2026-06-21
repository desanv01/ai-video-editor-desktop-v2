"""Optional Revideo composition bridge for semantic lecture renders."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from config import settings


class RevideoUnavailable(RuntimeError):
    """Raised when the Revideo runtime is not configured on this host."""


@dataclass(frozen=True)
class RevideoRenderResult:
    output_path: str
    plan_path: str
    renderer: str = "revideo"


async def render_semantic_plan_with_revideo(
    *,
    render_plan: dict[str, Any],
    source_video_path: str,
    output_path: str,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> RevideoRenderResult:
    """Render a semantic teaching timeline through the Node/Revideo bridge."""
    if not bool(getattr(settings, "REVIDEO_RENDERER_ENABLED", False)):
        raise RevideoUnavailable("Revideo renderer is disabled")

    command = str(getattr(settings, "REVIDEO_RENDERER_COMMAND", "node") or "node")
    executable = shutil.which(command) if os.path.basename(command) == command else command
    if not executable or not os.path.exists(executable):
        raise RevideoUnavailable(f"Revideo command is not available: {command}")

    workdir = str(getattr(settings, "REVIDEO_RENDERER_WORKDIR", "/revideo") or "/revideo")
    script = str(getattr(settings, "REVIDEO_RENDERER_SCRIPT", os.path.join(workdir, "render.mjs")) or "")
    if not os.path.exists(script):
        raise RevideoUnavailable(f"Revideo script is not available: {script}")
    if not os.path.exists(source_video_path):
        raise RevideoUnavailable(f"Source video for Revideo does not exist: {source_video_path}")

    os.makedirs(settings.TEMP_PATH, exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plan_path = os.path.join(settings.TEMP_PATH, f"revideo_plan_{uuid.uuid4()}.json")
    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump(render_plan, handle)

    env = os.environ.copy()
    env.update({
        "AIVE_RENDER_PLAN_PATH": plan_path,
        "AIVE_SOURCE_VIDEO_PATH": source_video_path,
        "AIVE_RENDER_OUTPUT": output_path,
        "AIVE_RENDER_WORKERS": str(getattr(settings, "REVIDEO_RENDERER_WORKERS", 1) or 1),
        "AIVE_REVIDEO_BASE_PORT": str(_base_port()),
        "DISABLE_TELEMETRY": "true",
    })

    if progress_callback:
        progress_callback(0.0, "Starting Revideo semantic compositor")

    proc = await asyncio.create_subprocess_exec(
        executable,
        script,
        cwd=workdir,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_task = asyncio.create_task(_read_stream(proc.stdout, progress_callback))
    stderr_chunks: list[str] = []
    stderr_task = asyncio.create_task(_collect_stderr(proc.stderr, stderr_chunks))
    timeout = float(getattr(settings, "REVIDEO_RENDERER_TIMEOUT_SECONDS", 1800) or 1800)

    try:
        while proc.returncode is None:
            if cancel_check:
                cancel_check()
            try:
                await asyncio.wait_for(proc.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                pass
            timeout -= 0.25
            if timeout <= 0:
                proc.kill()
                await proc.wait()
                raise TimeoutError("Revideo render timed out")
    except Exception:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    finally:
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    if proc.returncode != 0:
        stderr = "\n".join(stderr_chunks)[-4000:]
        raise RuntimeError(f"Revideo render failed: {stderr}")
    if not os.path.exists(output_path):
        raise RuntimeError(f"Revideo render finished without output: {output_path}")
    if progress_callback:
        progress_callback(1.0, "Revideo semantic composition complete")
    return RevideoRenderResult(output_path=output_path, plan_path=plan_path)


async def _read_stream(stream: asyncio.StreamReader | None, progress_callback: Callable[[float, str], None] | None) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode(errors="replace").strip()
        if not text or not progress_callback:
            continue
        match = re.search(r"Render progress, worker\s+\d+:\s+(\d+)%", text)
        if match:
            progress_callback(max(0.0, min(1.0, int(match.group(1)) / 100.0)), text)


async def _collect_stderr(stream: asyncio.StreamReader | None, chunks: list[str]) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        chunks.append(line.decode(errors="replace").strip())


def _base_port() -> int:
    base = int(getattr(settings, "REVIDEO_RENDERER_BASE_PORT", 9300) or 9300)
    return base + (uuid.uuid4().int % 500)
