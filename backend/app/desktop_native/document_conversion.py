"""Isolated managed PPTX-to-PDF conversion and complete native slide extraction."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, TypeVar

from config import settings
from services.tooling import libreoffice_binary

logger = logging.getLogger(__name__)
CONVERSION_TIMEOUT_SECONDS = 180
PIPE_DIAGNOSTIC_BYTES = 64 * 1024
_deferred_cleanups: set[asyncio.Future] = set()
_OwnedFuture = TypeVar("_OwnedFuture", bound=asyncio.Future)


class ManagedDocumentError(RuntimeError):
    pass


@dataclass
class ConversionState:
    process: asyncio.subprocess.Process | None = None
    owner: asyncio.Task | None = None
    completion: asyncio.Future | None = None
    abort: asyncio.Event = field(default_factory=asyncio.Event)
    cleanup_complete: bool = False


def _track(task: _OwnedFuture) -> _OwnedFuture:
    # Keep owners alive after the requesting task is cancelled repeatedly.
    _deferred_cleanups.add(task)
    def completed(done):
        _deferred_cleanups.discard(done)
        if not done.cancelled():
            done.exception()
    task.add_done_callback(completed)
    return task


def _remove_owned(directory: Path, parent: Path, prefix: str) -> None:
    """Remove only this call's unique direct child, never its root or old output."""
    try:
        info = directory.lstat()
    except FileNotFoundError:
        return
    if (
        not directory.name.startswith(prefix)
        or directory.resolve(strict=True).parent != parent.resolve(strict=True)
        or stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise ManagedDocumentError("Unsafe managed conversion cleanup target rejected")
    shutil.rmtree(directory)


def _text_pages(path: Path, presentation_factory) -> tuple[dict[int, str], int, bool]:
    slide_texts: dict[int, str] = {}
    total_slides = 0
    try:
        prs = presentation_factory(str(path))
        total_slides = len(prs.slides)
        for slide_num, slide in enumerate(prs.slides):
            texts: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        para_text = paragraph.text.strip()
                        if para_text:
                            texts.append(para_text)
                if shape.has_table:
                    table = shape.table
                    for row in table.rows:
                        row_texts: list[str] = []
                        for cell in row.cells:
                            cell_text = cell.text.strip()
                            if cell_text:
                                row_texts.append(cell_text)
                        if row_texts:
                            texts.append(" | ".join(row_texts))
            try:
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        texts.append(f"[Speaker Notes] {notes}")
            except Exception:
                pass
            slide_texts[slide_num] = "\n".join(texts)
        return slide_texts, total_slides, True
    except Exception:
        logger.exception("Managed PPTX text extraction failed")
        return slide_texts, total_slides, False


async def _drain(reader: asyncio.StreamReader | None) -> bytes:
    retained = bytearray()
    if reader is not None:
        while True:
            chunk = await reader.read(16 * 1024)
            if not chunk:
                break
            retained.extend(chunk)
            if len(retained) > PIPE_DIAGNOSTIC_BYTES:
                del retained[:-PIPE_DIAGNOSTIC_BYTES]
    return bytes(retained)


async def _terminate_owned(proc: asyncio.subprocess.Process, completion: asyncio.Future) -> None:
    """Terminate only the still-live process/tree launched by this operation."""
    if proc.returncode is None:
        if os.name == "nt":
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill.exe", "/PID", str(proc.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                try:
                    await asyncio.wait_for(killer.wait(), timeout=5)
                except asyncio.TimeoutError:
                    killer.kill()
                    await asyncio.wait_for(killer.wait(), timeout=5)
                if proc.returncode is None and killer.returncode != 0:
                    proc.kill()
            except Exception:
                # The owned root handle remains available even if taskkill cannot start.
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        await asyncio.wait_for(asyncio.shield(completion), timeout=10)
    except asyncio.TimeoutError as exc:
        raise ManagedDocumentError("Managed document process cleanup did not complete; its isolated workspace was retained") from exc


def _profile_uri(profile: Path) -> str:
    """Use only a verified shorter Windows alias of this same owned profile."""
    original_uri = profile.as_uri()
    if os.name != "nt":
        return original_uri
    original = profile.resolve(strict=True)
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        short_path = kernel32.GetShortPathNameW
        short_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        short_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = short_path(str(original), buffer, len(buffer))
        if not length or length >= len(buffer):
            return original_uri
        alias_text = buffer.value
        if len(alias_text) != length or not alias_text:
            return original_uri
    except (OSError, AttributeError, ValueError):
        # Some filesystems have no short aliases; never enable them or redirect.
        return original_uri
    alias = Path(alias_text)
    if not alias.is_absolute():
        raise ManagedDocumentError("Managed document profile alias is not absolute")
    try:
        matches = alias.samefile(profile) and alias.resolve(strict=True) == original
    except (OSError, ValueError) as exc:
        raise ManagedDocumentError("Managed document profile alias identity could not be verified") from exc
    if not matches:
        raise ManagedDocumentError("Managed document profile alias does not identify the owned profile")
    if len(alias_text) >= len(str(original)):
        return original_uri
    return alias.as_uri()

async def _conversion_owner(binary: str, source: Path, work: Path, state: ConversionState) -> Path:
    # This task is shielded and retained for its entire spawn/termination lifetime.
    pdf_dir = work / "pdf"
    profile = work / "profile"
    pdf_dir.mkdir()
    profile.mkdir()
    command = [
        binary, f"-env:UserInstallation={_profile_uri(profile)}",
        "--headless", "--nologo", "--nodefault", "--nofirststartwizard", "--norestore",
        "--convert-to", "pdf:impress_pdf_Export", "--outdir", str(pdf_dir), str(source),
    ]
    options: dict[str, Any] = {"cwd": str(work)}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    abort_task = None
    try:
        state.process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options,
        )
        proc = state.process
        # return_exceptions waits for all three users, even if one pipe reader fails.
        state.completion = _track(asyncio.gather(
            proc.wait(), _drain(proc.stdout), _drain(proc.stderr), return_exceptions=True,
        ))
        abort_task = asyncio.create_task(state.abort.wait())
        done, _ = await asyncio.wait(
            (state.completion, abort_task), timeout=CONVERSION_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if state.abort.is_set():
            raise asyncio.CancelledError
        if state.completion not in done:
            raise ManagedDocumentError("Managed document conversion timed out")
        results = state.completion.result()
        if any(isinstance(value, BaseException) for value in results):
            raise ManagedDocumentError("Managed document process or diagnostic pipe failed")
        return_code, stdout, stderr = results
        if return_code != 0:
            logger.warning("Managed LibreOffice failed (rc=%s): %s", return_code, stderr.decode("utf-8", errors="replace"))
            raise ManagedDocumentError("Managed LibreOffice could not convert this presentation; repair the document component or retry a valid deck")
        if stdout:
            logger.debug("Managed LibreOffice output: %s", stdout.decode("utf-8", errors="replace"))
        pdf = pdf_dir / (source.stem + ".pdf")
        if not pdf.is_file() or pdf.stat().st_size == 0 or pdf.is_symlink():
            raise ManagedDocumentError("Managed LibreOffice produced no complete PDF for this deck")
        return pdf
    except BaseException:
        if state.process is not None and state.completion is not None:
            try:
                await _terminate_owned(state.process, state.completion)
            except Exception:
                logger.exception("Owned managed document process cleanup failed; workspace retained")
        raise
    finally:
        if abort_task is not None:
            abort_task.cancel()
            await asyncio.gather(abort_task, return_exceptions=True)
        state.cleanup_complete = state.process is None or (
            state.completion is not None
            and state.completion.done()
            and not state.completion.cancelled()
            and not any(isinstance(value, BaseException) for value in state.completion.result())
        )


async def _convert_to_pdf(binary: str, source: Path, work: Path, state: ConversionState) -> Path:
    state.owner = _track(asyncio.create_task(_conversion_owner(binary, source, work, state)))
    try:
        return await asyncio.shield(state.owner)
    except asyncio.CancelledError:
        state.abort.set()
        raise


def _render_pages(pdf: Path, generation: Path, dpi: int, finished: threading.Event) -> list[dict]:
    try:
        from services.pdf_slides import pdf_slide_service
        return asyncio.run(pdf_slide_service.extract_pdf_pages(
            str(pdf), str(generation), dpi=dpi, skip_existing=False,
        ))
    finally:
        finished.set()


async def _cleanup_paths(work: Path, temp_root: Path, generation: Path | None, output_root: Path, failed: bool) -> None:
    try:
        if generation is not None and failed:
            await asyncio.to_thread(_remove_owned, generation, output_root, "pptx-generation-")
        await asyncio.to_thread(_remove_owned, work, temp_root, "aive-document-")
    except Exception:
        logger.exception("Isolated managed document directory cleanup failed; retained owned output")


async def _await_render(future: Future) -> list[dict]:
    return await asyncio.shield(asyncio.wrap_future(future))


async def _cleanup_after_users(
    state: ConversionState, render_task: asyncio.Task | None, render_future: Future | None,
    finished: threading.Event, executor: ThreadPoolExecutor | None,
    work: Path, temp_root: Path, generation: Path | None, output_root: Path, failed: bool,
) -> None:
    if state.owner is not None:
        await asyncio.gather(asyncio.shield(state.owner), return_exceptions=True)
    if render_task is not None:
        await asyncio.gather(asyncio.shield(render_task), return_exceptions=True)
    if render_future is not None:
        # A cancelled asyncio task is not evidence that its executor work stopped.
        # The concurrent future also covers cancellation before the thread starts.
        while not render_future.done() or not finished.is_set():
            await asyncio.sleep(0.1)
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    if state.cleanup_complete:
        await _cleanup_paths(work, temp_root, generation, output_root, failed)
    else:
        logger.error("Managed process/pipe cleanup is incomplete; isolated workspace retained")


def _errors(texts: dict[int, str], count: int, message: str) -> list[dict]:
    return [{
        "page_index": index, "text": texts.get(index, ""), "image_path": None,
        "error": f"{message}. Prepare or repair the managed document components and retry.",
    } for index in range(max(1, count))]


async def extract_native_pptx_pages(pptx_path: str, output_dir: str, *, dpi: int, presentation_factory) -> list[dict]:
    if presentation_factory is None:
        raise ImportError("The managed document pack is missing Python-PPTX; repair the document component.")
    source = Path(pptx_path).resolve(strict=True)
    if not source.is_file():
        raise FileNotFoundError(f"PPTX file not found: {pptx_path}")
    texts, count, text_ok = await asyncio.to_thread(_text_pages, source, presentation_factory)
    if not text_ok or count == 0:
        return _errors(texts, count, "No complete slide text/count could be read from the presentation")
    try:
        binary = libreoffice_binary()
        temp_value = str(settings.TEMP_PATH or "").strip()
        if not temp_value or not Path(temp_value).is_absolute():
            raise ManagedDocumentError("Managed document conversion requires an absolute app-owned temporary root")
        temp_root = Path(temp_value).resolve()
        output_root = Path(output_dir).resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        output_root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="aive-document-", dir=temp_root)).resolve()
        if work.parent != temp_root:
            raise ManagedDocumentError("Managed document workspace escaped its temporary root")
    except Exception as exc:
        return _errors(texts, count, str(exc))

    state = ConversionState()
    generation: Path | None = None
    render_finished = threading.Event()
    render_task: asyncio.Task | None = None
    render_future: Future | None = None
    render_executor: ThreadPoolExecutor | None = None
    success = False
    try:
        pdf = await _convert_to_pdf(binary, source, work, state)
        generation = Path(tempfile.mkdtemp(prefix="pptx-generation-", dir=output_root)).resolve()
        if generation.parent != output_root:
            raise ManagedDocumentError("Managed slide output escaped its requested root")
        render_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aive-document")
        render_future = render_executor.submit(_render_pages, pdf, generation, dpi, render_finished)
        # Set completion even if queued executor work is cancelled before starting.
        render_future.add_done_callback(lambda done: render_finished.set())
        render_task = _track(asyncio.create_task(_await_render(render_future)))
        pages = await asyncio.shield(render_task)
        if len(pages) != count or [page.get("page_index") for page in pages] != list(range(count)):
            raise ManagedDocumentError("Converted PDF page count/order does not match the original presentation")
        for page in pages:
            image = Path(str(page.get("image_path") or ""))
            if page.get("error") or not image.is_file() or image.is_symlink() or image.stat().st_size == 0 or image.resolve().parent != generation:
                raise ManagedDocumentError("Managed slide rendering returned partial or missing page images")
        result = [{**page, "text": texts.get(page["page_index"], "")} for page in pages]
        success = True
        return result
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Managed PPTX rendering unavailable: %s", exc)
        return _errors(texts, count, str(exc))
    finally:
        # Cleanup itself has an owner so repeated caller cancellation cannot
        # interrupt deletion or cause deletion while another owner uses files.
        cleanup = _track(asyncio.create_task(_cleanup_after_users(
            state, render_task, render_future, render_finished, render_executor,
            work, temp_root, generation, output_root, not success,
        )))
        if (
            (state.owner is None or state.owner.done())
            and (render_future is None or (render_future.done() and render_finished.is_set()))
            and (render_task is None or render_task.done())
        ):
            await asyncio.shield(cleanup)
        # Otherwise the tracked cleanup owns the still-active users; cancellation
        # propagates immediately while their directories remain intact.
