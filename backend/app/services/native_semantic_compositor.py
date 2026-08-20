"""Fast native semantic lecture compositor.

This is the production path for full-length lecture exports.  It consumes the
same semantic render plan used by preview/Revideo, but renders with FFmpeg
filters instead of browser frame rendering.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
from typing import Any, Callable

from services.ffmpeg import FFmpegService
from services.tooling import ffmpeg_binary


ProgressCallback = Callable[[float, str], None]
CancelCheck = Callable[[], None]
_proxy_locks: dict[str, asyncio.Lock] = {}


async def prewarm_render_proxy(
    source_video_path: str,
    *,
    output_width: int = 1920,
    output_height: int = 1080,
    fps: int = 30,
) -> str:
    """Create the reusable editing proxy before the teacher starts export."""
    return await _ensure_render_proxy(
        source_video_path=source_video_path,
        output_width=output_width,
        output_height=output_height,
        fps=fps,
        progress_callback=None,
        cancel_check=None,
    )


async def render_semantic_plan_with_ffmpeg(
    *,
    render_plan: dict[str, Any],
    source_video_path: str,
    output_path: str,
    work_dir: str,
    output_width: int = 1920,
    output_height: int = 1080,
    fps: int = 30,
    video_bitrate: str | None = None,
    audio_bitrate: str | None = "256k",
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> str:
    """Render semantic scenes with bounded memory, then stream-copy assemble them.

    A single graph that splits a long source once per scene causes FFmpeg to
    buffer future branches while concat consumes the first branch.  Full
    lectures can therefore retain gigabytes of decoded frames.  Rendering one
    scene at a time keeps memory proportional to one scene while preserving the
    exact same semantic timeline.
    """
    scenes = _valid_scenes(render_plan)
    if not scenes:
        raise ValueError("Semantic render plan has no renderable scenes")
    if not os.path.isfile(source_video_path):
        raise FileNotFoundError(f"Source video not found: {source_video_path}")

    os.makedirs(work_dir, exist_ok=True)
    source_video_path = await _ensure_render_proxy(
        source_video_path=source_video_path,
        output_width=output_width,
        output_height=output_height,
        fps=fps,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    slide_paths = _render_slide_images(render_plan, scenes, work_dir, output_width, output_height)
    total_duration = sum(float(scene["duration_seconds"]) for scene in scenes)
    if progress_callback:
        progress_callback(0.0, f"Preparing {len(scenes)} bounded render scenes")
    await _render_bounded_scene_sequence(
        source_video_path=source_video_path,
        output_path=output_path,
        work_dir=work_dir,
        scenes=scenes,
        slide_paths=slide_paths,
        output_width=output_width,
        output_height=output_height,
        fps=fps,
        video_bitrate=video_bitrate,
        audio_bitrate=audio_bitrate,
        total_duration=total_duration,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        raise RuntimeError("Native semantic compositor did not produce an output file")
    if progress_callback:
        progress_callback(1.0, "Native FFmpeg semantic composition complete")
    return output_path


async def _render_bounded_scene_sequence(
    *,
    source_video_path: str,
    output_path: str,
    work_dir: str,
    scenes: list[dict[str, Any]],
    slide_paths: list[str],
    output_width: int,
    output_height: int,
    fps: int,
    video_bitrate: str | None,
    audio_bitrate: str | None,
    total_duration: float,
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> None:
    scene_dir = os.path.join(work_dir, "bounded_scenes")
    os.makedirs(scene_dir, exist_ok=True)
    scene_outputs: list[str] = []
    completed_duration = 0.0
    total = max(0.1, float(total_duration or 0.1))

    try:
        for index, (scene, slide_path) in enumerate(zip(scenes, slide_paths)):
            if cancel_check:
                cancel_check()
            scene_output = os.path.join(scene_dir, f"scene_{index:04d}.mp4")
            scene_outputs.append(scene_output)
            duration = float(scene["duration_seconds"])
            command = _build_bounded_scene_command(
                source_video_path=source_video_path,
                slide_path=slide_path,
                output_path=scene_output,
                scene=scene,
                output_width=output_width,
                output_height=output_height,
                fps=fps,
                video_bitrate=video_bitrate,
                audio_bitrate=audio_bitrate,
                previous_scene_path=scene_outputs[index - 1] if index > 0 else None,
                previous_scene_duration=(
                    float(scenes[index - 1]["duration_seconds"])
                    if index > 0
                    else None
                ),
            )

            def scene_progress(value: float, _message: str, *, scene_index: int = index) -> None:
                rendered = min(duration, max(0.0, value) * duration)
                aggregate = min(0.985, (completed_duration + rendered) / total)
                if progress_callback:
                    progress_callback(
                        aggregate,
                        f"Composing scene {scene_index + 1}/{len(scenes)} "
                        f"({completed_duration + rendered:.1f}s of {total:.1f}s)",
                    )

            await _run_ffmpeg_with_progress(
                command,
                total_duration=duration,
                progress_callback=scene_progress,
                cancel_check=cancel_check,
            )
            completed_duration += duration

        if progress_callback:
            progress_callback(0.99, "Assembling rendered scenes")
        concat_path = os.path.join(scene_dir, "concat.txt")
        assembled_video_path = os.path.join(scene_dir, "assembled_video.mp4")
        assembled_audio_path = os.path.join(scene_dir, "assembled_audio.m4a")
        with open(concat_path, "w", encoding="utf-8") as handle:
            for scene_output in scene_outputs:
                escaped = scene_output.replace("\\", "/").replace("'", "'\\''")
                handle.write(f"file '{escaped}'\n")
        concat_command = [
            ffmpeg_binary(), "-hide_banner", "-nostdin", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_path,
            "-map", "0:v:0", "-c", "copy", "-an",
            "-movflags", "+faststart", assembled_video_path,
        ]
        await FFmpegService._run_process(
            concat_command,
            error_prefix="Bounded semantic scene assembly failed",
            stderr_limit=2400,
            cancel_check=cancel_check,
        )
        if progress_callback:
            progress_callback(0.992, "Assembling cleaned lecture audio")
        audio_command = _build_bounded_audio_command(
            source_video_path=source_video_path,
            output_path=assembled_audio_path,
            scenes=scenes,
            audio_bitrate=audio_bitrate,
        )
        await _run_ffmpeg_with_progress(
            audio_command,
            total_duration=total,
            progress_callback=None,
            cancel_check=cancel_check,
        )
        if progress_callback:
            progress_callback(0.997, "Muxing final video and audio")
        mux_command = [
            ffmpeg_binary(), "-hide_banner", "-nostdin", "-y",
            "-i", assembled_video_path, "-i", assembled_audio_path,
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-shortest",
            "-movflags", "+faststart", output_path,
        ]
        await FFmpegService._run_process(
            mux_command,
            error_prefix="Final semantic video/audio mux failed",
            stderr_limit=2400,
            cancel_check=cancel_check,
        )
    finally:
        # Scene intermediates can be several gigabytes for long lectures. They
        # are never reusable, unlike the normalized editing proxy.
        shutil.rmtree(scene_dir, ignore_errors=True)


async def _ensure_render_proxy(
    *,
    source_video_path: str,
    output_width: int,
    output_height: int,
    fps: int,
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> str:
    """Normalize large camera sources once and reuse the editing proxy."""
    if os.path.getsize(source_video_path) < 512 * 1024 * 1024:
        return source_video_path
    stat = os.stat(source_video_path)
    identity = f"{os.path.abspath(source_video_path)}:{stat.st_size}:{stat.st_mtime_ns}:{output_width}x{output_height}:{fps}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    proxy_dir = os.path.join(os.path.dirname(source_video_path), ".aive-proxies")
    os.makedirs(proxy_dir, exist_ok=True)
    proxy_path = os.path.join(proxy_dir, f"{digest}.mp4")
    lock = _proxy_locks.setdefault(proxy_path, asyncio.Lock())
    async with lock:
        if os.path.isfile(proxy_path) and os.path.getsize(proxy_path) > 1024 * 1024:
            if progress_callback:
                progress_callback(0.0, "Using cached 1080p editing proxy")
            return proxy_path

        temp_path = f"{proxy_path}.partial.mp4"
        if progress_callback:
            progress_callback(0.0, "Waiting for reusable 1080p editing proxy")
        command = [
            ffmpeg_binary(), "-hide_banner", "-nostdin", "-y", "-i", source_video_path,
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", (
                f"scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
                f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={int(fps or 30)}"
            ),
            *FFmpegService._video_encoder_args("10M", "fast"),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", temp_path,
        ]
        try:
            await FFmpegService._run_process(
                command,
                error_prefix="Editing proxy generation failed",
                stderr_limit=1800,
                cancel_check=cancel_check,
            )
        except Exception:
            if FFmpegService._command_uses_hardware_encoder(command):
                await FFmpegService._run_process(
                    FFmpegService._cpu_fallback_command(command),
                    error_prefix="Editing proxy generation failed after hardware fallback",
                    stderr_limit=1800,
                    cancel_check=cancel_check,
                )
            else:
                raise
        os.replace(temp_path, proxy_path)
        return proxy_path


def _valid_scenes(render_plan: dict[str, Any]) -> list[dict[str, Any]]:
    scenes: list[dict[str, Any]] = []
    for item in render_plan.get("scenes") or []:
        if not isinstance(item, dict):
            continue
        duration = _float(item.get("duration_seconds"))
        if duration <= 0:
            duration = max(0.0, _float(item.get("end_time")) - _float(item.get("start_time")))
        if duration < 0.05:
            continue
        scene = dict(item)
        scene["duration_seconds"] = round(duration, 3)
        scene["source_start_time"] = round(max(0.0, _float(scene.get("source_start_time"))), 3)
        scenes.append(scene)
    return scenes


def _render_slide_images(
    render_plan: dict[str, Any],
    scenes: list[dict[str, Any]],
    work_dir: str,
    width: int,
    height: int,
) -> list[str]:
    slides = {
        str(slide.get("id") or ""): slide
        for slide in render_plan.get("slides") or []
        if isinstance(slide, dict)
    }
    paths: list[str] = []
    generated: dict[str, str] = {}
    for index, scene in enumerate(scenes):
        slide = slides.get(str(scene.get("slide_id") or "")) or {}
        exact_path = str(slide.get("image_path") or "")
        if exact_path and os.path.isfile(exact_path):
            paths.append(exact_path)
            continue
        slide_key = str(slide.get("id") or scene.get("slide_id") or f"scene-{index}")
        image_path = generated.get(slide_key) or os.path.join(work_dir, f"semantic_slide_{len(generated):04d}.png")
        if slide_key not in generated:
            _draw_slide_card(
                image_path=image_path,
                title=str(slide.get("title") or scene.get("topic_label") or "Lecture section"),
                body=str(slide.get("body") or scene.get("caption_text") or ""),
                bullets=[str(item) for item in (slide.get("bullets") or []) if str(item).strip()],
                source=str(slide.get("source_filename") or ""),
                width=width,
                height=height,
            )
            generated[slide_key] = image_path
        paths.append(image_path)
    return paths


def _draw_slide_card(
    *,
    image_path: str,
    title: str,
    body: str,
    bullets: list[str],
    source: str,
    width: int,
    height: int,
) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(0, 0, width, height), color=(0.965, 0.976, 0.992), fill=(0.965, 0.976, 0.992))
    page.draw_rect(fitz.Rect(0, 0, width, height * 0.055), color=(0.11, 0.16, 0.28), fill=(0.11, 0.16, 0.28))

    if source:
        page.insert_textbox(
            fitz.Rect(width * 0.06, height * 0.075, width * 0.84, height * 0.12),
            _clip_text(source, 68),
            fontsize=24,
            fontname="helv",
            color=(0.14, 0.38, 0.92),
        )

    page.insert_textbox(
        fitz.Rect(width * 0.06, height * 0.15, width * 0.88, height * 0.34),
        _wrap_text(_clip_text(title, 96), 26),
        fontsize=58,
        fontname="helv",
        color=(0.05, 0.09, 0.16),
    )

    if body:
        page.insert_textbox(
            fitz.Rect(width * 0.06, height * 0.37, width * 0.82, height * 0.57),
            _wrap_text(_clip_text(body, 260), 52),
            fontsize=31,
            fontname="helv",
            color=(0.19, 0.27, 0.38),
        )

    y = height * 0.62
    for bullet in (bullets or [])[:4]:
        page.draw_rect(
            fitz.Rect(width * 0.07, y - 14, width * 0.84, y + 54),
            color=(0.80, 0.84, 0.91),
            fill=(1, 1, 1),
        )
        page.insert_textbox(
            fitz.Rect(width * 0.09, y, width * 0.81, y + 48),
            _wrap_text(_clip_text(bullet, 120), 58),
            fontsize=26,
            fontname="helv",
            color=(0.10, 0.15, 0.24),
        )
        y += 82

    pixmap = page.get_pixmap(alpha=False)
    pixmap.save(image_path)
    doc.close()


def _build_bounded_scene_command(
    *,
    source_video_path: str,
    slide_path: str,
    output_path: str,
    scene: dict[str, Any],
    output_width: int,
    output_height: int,
    fps: int,
    video_bitrate: str | None,
    audio_bitrate: str | None,
    previous_scene_path: str | None = None,
    previous_scene_duration: float | None = None,
) -> list[str]:
    duration = float(scene["duration_seconds"])
    source_start = float(scene.get("source_start_time") or 0.0)
    layout = str(scene.get("layout") or "picture_in_picture")
    cmd = [
        ffmpeg_binary(), "-hide_banner", "-nostdin", "-y",
        "-ss", f"{source_start:.3f}", "-t", f"{duration:.3f}", "-i", source_video_path,
        "-loop", "1", "-t", f"{duration:.3f}", "-i", slide_path,
    ]
    transition = scene.get("transition") if isinstance(scene.get("transition"), dict) else {}
    transition_type = str(transition.get("type") or "cut").lower()
    transition_duration = min(
        max(0.0, _float(transition.get("duration_seconds"))),
        duration / 2,
        max(0.0, float(previous_scene_duration or 0.0)) / 2,
    )
    use_transition = bool(
        previous_scene_path
        and os.path.isfile(previous_scene_path)
        and transition_type not in {"", "cut", "none"}
        and transition_duration >= 0.05
    )
    if use_transition:
        cmd.extend([
            "-sseof", f"-{transition_duration:.3f}",
            "-i", str(previous_scene_path),
        ])
    filter_parts = _scene_filter_parts(
        image_input=1,
        camera_source="0:v",
        scene_index=0,
        duration=duration,
        layout=layout,
        camera_settings=scene.get("camera") if isinstance(scene.get("camera"), dict) else {},
        output_width=output_width,
        output_height=output_height,
        fps=fps,
        output_label="current" if use_transition else "v",
    )
    if use_transition:
        xfade_name = FFmpegService._xfade_transition_name(transition_type)
        filter_parts.extend([
            f"[2:v]trim=duration={transition_duration:.3f},setpts=PTS-STARTPTS,"
            f"fps={int(fps or 30)},format=yuv420p[previous]",
            f"[previous][current]xfade=transition={xfade_name}:"
            f"duration={transition_duration:.3f}:offset=0,format=yuv420p[v]",
        ])
    cmd.extend([
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[v]",
        "-an",
        *FFmpegService._video_encoder_args(video_bitrate, "veryfast"),
        "-threads", "4",
        "-filter_threads", "2",
        "-r",
        str(int(fps or 30)),
        "-pix_fmt",
        "yuv420p",
        "-t",
        f"{duration:.3f}",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:2",
        output_path,
    ])
    return cmd


def _build_bounded_audio_command(
    *,
    source_video_path: str,
    output_path: str,
    scenes: list[dict[str, Any]],
    audio_bitrate: str | None,
) -> list[str]:
    """Assemble all source ranges and encode AAC once to avoid per-scene priming."""
    command = [ffmpeg_binary(), "-hide_banner", "-nostdin", "-y"]
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, scene in enumerate(scenes):
        duration = float(scene["duration_seconds"])
        source_start = float(scene.get("source_start_time") or 0.0)
        command.extend([
            "-ss", f"{source_start:.3f}", "-t", f"{duration:.3f}", "-i", source_video_path,
        ])
        filters.append(
            f"[{index}:a:0]atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
            f"aresample=48000,aformat=channel_layouts=stereo[a{index}]"
        )
        concat_inputs.append(f"[a{index}]")
    filters.append(f"{''.join(concat_inputs)}concat=n={len(scenes)}:v=0:a=1[a]")
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[a]", "-vn",
        "-c:a", "aac", "-b:a", FFmpegService._normalize_audio_bitrate(audio_bitrate),
        "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
        "-progress", "pipe:2", output_path,
    ])
    return command


def _scene_filter_parts(
    *,
    image_input: int,
    camera_source: str,
    scene_index: int,
    duration: float,
    layout: str,
    camera_settings: dict[str, Any],
    output_width: int,
    output_height: int,
    fps: int,
    output_label: str,
) -> list[str]:
    bg = f"bg{scene_index}"
    cam = f"cam{scene_index}"
    parts: list[str] = []

    if layout == "full_camera_source":
        parts.append(
            f"[{camera_source}]scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={int(fps or 30)},format=yuv420p[{output_label}]"
        )
        return parts

    parts.append(
        f"[{image_input}:v]scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
        f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2:color=0xf8fafc,"
        f"trim=duration={duration:.3f},setpts=PTS-STARTPTS,fps={int(fps or 30)},format=yuv420p[{bg}]"
    )

    if layout == "full_screen_source":
        parts.append(f"[{bg}]null[{output_label}]")
        return parts

    if layout == "side_by_side":
        left_width = _even(output_width * 0.58)
        right_width = _even(output_width - left_width)
        parts.append(
            f"[{camera_source}]scale={right_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={right_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={int(fps or 30)},format=yuv420p[{cam}]"
        )
        parts.append(
            f"[{bg}]scale={left_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={left_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[left{scene_index}]"
        )
        parts.append(f"[left{scene_index}][{cam}]hstack=inputs=2[{output_label}]")
        return parts

    camera_shape = str(camera_settings.get("shape") or "rounded_rectangle")
    camera_width, camera_height = FFmpegService._pip_camera_dimensions(
        output_width,
        output_height,
        str(camera_settings.get("size") or "medium"),
        camera_shape,
    )
    margin_percent = min(12.0, max(0.0, _float(camera_settings.get("margin_percent") or 4.0)))
    margin = _even(min(output_width, output_height) * margin_percent / 100.0)
    corner = str(camera_settings.get("corner") or "top_right")
    overlay_x = margin if corner.endswith("left") else output_width - camera_width - margin
    overlay_y = margin if corner.startswith("top") else output_height - camera_height - margin
    camera_filter = FFmpegService._pip_camera_filter(camera_width, camera_height, camera_shape)
    parts.append(f"[{camera_source}]{camera_filter},fps={int(fps or 30)}[{cam}]")
    parts.append(
        f"[{bg}][{cam}]overlay={overlay_x}:{overlay_y}:format=auto,"
        f"format=yuv420p[{output_label}]"
    )
    return parts


async def _run_ffmpeg_with_progress(
    cmd: list[str],
    *,
    total_duration: float,
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_lines: list[str] = []
    total = max(0.1, float(total_duration or 0.1))
    stall_timeout = max(30.0, float(os.getenv("AIVE_FFMPEG_STALL_TIMEOUT_SECONDS", "180")))
    last_output_at = asyncio.get_running_loop().time()
    assert proc.stderr is not None
    while True:
        if cancel_check:
            try:
                cancel_check()
            except Exception:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
                raise
        try:
            line = await asyncio.wait_for(proc.stderr.readline(), timeout=1.0)
        except asyncio.TimeoutError:
            if asyncio.get_running_loop().time() - last_output_at < stall_timeout:
                continue
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"Native semantic composition stalled with no FFmpeg progress for {stall_timeout:.0f} seconds"
            )
        if not line:
            break
        last_output_at = asyncio.get_running_loop().time()
        text = line.decode(errors="ignore").strip()
        if text:
            stderr_lines.append(text)
        if text.startswith("out_time_ms="):
            value = _float(text.split("=", 1)[1]) / 1_000_000
            if progress_callback:
                progress_callback(min(0.995, value / total), f"Composed {value:.1f}s of {total:.1f}s")
        elif text.startswith("out_time_us="):
            value = _float(text.split("=", 1)[1]) / 1_000_000
            if progress_callback:
                progress_callback(min(0.995, value / total), f"Composed {value:.1f}s of {total:.1f}s")
        elif text.startswith("progress=end") and progress_callback:
            progress_callback(1.0, "Native FFmpeg semantic composition complete")
    stdout, stderr = await proc.communicate()
    if stdout:
        stderr_lines.append(stdout.decode(errors="ignore"))
    if stderr:
        stderr_lines.append(stderr.decode(errors="ignore"))
    if proc.returncode != 0:
        message = "\n".join(stderr_lines)[-1800:]
        if FFmpegService._command_uses_hardware_encoder(cmd):
            fallback_cmd = FFmpegService._cpu_fallback_command(cmd)
            await FFmpegService._run_process(
                fallback_cmd,
                error_prefix="Native semantic composition failed after hardware encoder fallback",
                stderr_limit=1800,
                cancel_check=cancel_check,
            )
            return
        raise RuntimeError(f"Native semantic composition failed: {message}")


def _wrap_text(text: str, width: int) -> str:
    words = re.split(r"\s+", str(text or "").strip())
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return "\n".join(lines)


def _clip_text(text: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _even(value: float) -> int:
    number = max(2, int(round(float(value))))
    return number if number % 2 == 0 else number - 1


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
