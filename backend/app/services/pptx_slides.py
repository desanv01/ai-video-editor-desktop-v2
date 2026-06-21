"""
PPTX Slide Extractor Service

Converts each slide of a PPTX file into a PNG image using LibreOffice
headless conversion and extracts per-slide text using python-pptx.

Typical use:
    from services.pptx_slides import pptx_slide_service

    pages = await pptx_slide_service.extract_pptx_pages(
        "/path/to/slides.pptx", "/output/dir"
    )
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import – python-pptx is only loaded when the service is used.
# ---------------------------------------------------------------------------

try:
    from pptx import Presentation
except ImportError:  # pragma: no cover
    Presentation = None


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class PPTXSlideService:
    """Service for extracting slide images and text from PPTX files.

    Uses LibreOffice headless for PNG rendering and python-pptx for text
    extraction.  All methods are async static methods so they can be called
    either through the module-level singleton ``pptx_slide_service`` or
    directly on the class.
    """

    @staticmethod
    async def extract_pptx_pages(
        pptx_path: str,
        output_dir: str,
        dpi: int = 200,
    ) -> list[dict]:
        """Convert each PPTX slide to a PNG and extract per-slide text.

        Images are named ``page_000.png``, ``page_001.png``, … inside
        *output_dir* (zero-padded to three digits).

        Args:
            pptx_path:  Absolute path to the PPTX file.
            output_dir: Directory to save slide images (created if missing).
            dpi:        Render resolution (default 200).  LibreOffice's
                        ``--convert-to png`` may not honour an explicit DPI
                        on all platforms; the value is logged for traceability.

        Returns:
            [
                {
                    "page_index": 0,
                    "text": "Slide text content...",
                    "image_path": "/abs/path/to/page_000.png",
                },
                ...
            ]

            Slides that could not be rendered still appear with
            ``image_path`` set to ``None`` and an ``"error"`` key.
        """
        # ------------------------------------------------------------------
        # Guards
        # ------------------------------------------------------------------
        if Presentation is None:
            raise ImportError(
                "python-pptx is required for PPTX processing. "
                "Install it with: pip install python-pptx"
            )

        if not os.path.isfile(pptx_path):
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")

        os.makedirs(output_dir, exist_ok=True)

        # ------------------------------------------------------------------
        # Step 1 – Extract text from every slide using python-pptx
        # ------------------------------------------------------------------
        slide_texts: dict[int, str] = {}
        total_slides = 0

        try:
            prs = Presentation(pptx_path)
            total_slides = len(prs.slides)

            for slide_num, slide in enumerate(prs.slides):
                texts: list[str] = []

                for shape in slide.shapes:
                    # Text frames (titles, text boxes, …)
                    if shape.has_text_frame:
                        for paragraph in shape.text_frame.paragraphs:
                            para_text = paragraph.text.strip()
                            if para_text:
                                texts.append(para_text)

                    # Tables
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

                # Speaker notes
                try:
                    if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                        notes = slide.notes_slide.notes_text_frame.text.strip()
                        if notes:
                            texts.append(f"[Speaker Notes] {notes}")
                except Exception:
                    pass

                slide_texts[slide_num] = "\n".join(texts)

        except Exception as exc:
            logger.error(
                "Failed to extract text from '%s': %s", pptx_path, exc,
            )
            # Continue – rendering may still succeed even if text fails.

        # ------------------------------------------------------------------
        # Step 2 – Render slides to PNG via LibreOffice headless
        # ------------------------------------------------------------------
        cmd = [
            "libreoffice",
            "--headless",
            "--convert-to", "png",
            "--outdir", output_dir,
            pptx_path,
        ]

        logger.info("Running LibreOffice: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                stderr_str = stderr.decode("utf-8", errors="replace").strip()
                logger.error(
                    "LibreOffice conversion failed (rc=%d): %s",
                    proc.returncode, stderr_str,
                )
            else:
                logger.info("LibreOffice conversion completed successfully.")
                if stdout:
                    logger.debug(
                        "LibreOffice stdout: %s",
                        stdout.decode("utf-8", errors="replace").strip(),
                    )

        except FileNotFoundError:
            logger.error(
                "LibreOffice not found. Install LibreOffice to render PPTX "
                "slides.  Text extraction will still be returned."
            )
        except Exception as exc:
            logger.error("LibreOffice execution error: %s", exc)

        # ------------------------------------------------------------------
        # Step 3 – Rename LibreOffice output (Slide1.png → page_000.png)
        # ------------------------------------------------------------------
        rename_map: dict[int, str] = {}  # slide_index (0-based) → final path

        for idx in range(total_slides):
            src_name = f"Slide{idx + 1}.png"
            src_path = os.path.join(output_dir, src_name)
            dst_name = f"page_{idx:03d}.png"
            dst_path = os.path.join(output_dir, dst_name)

            if os.path.isfile(src_path):
                try:
                    if os.path.isfile(dst_path):
                        os.remove(dst_path)
                    os.rename(src_path, dst_path)
                    rename_map[idx] = dst_path
                    logger.debug("Renamed %s → %s", src_name, dst_name)
                except OSError as exc:
                    logger.error(
                        "Failed to rename %s → %s: %s",
                        src_name, dst_name, exc,
                    )
            else:
                logger.warning(
                    "Expected LibreOffice output '%s' not found in '%s'.",
                    src_name, output_dir,
                )

        # Clean up any orphaned Slide*.png files from a previous partial run.
        for leftover in glob.glob(os.path.join(output_dir, "Slide*.png")):
            try:
                os.remove(leftover)
                logger.debug("Removed leftover file: %s", leftover)
            except OSError:
                pass

        # ------------------------------------------------------------------
        # Step 4 – Build results
        # ------------------------------------------------------------------
        results: list[dict] = []

        for idx in range(total_slides):
            text = slide_texts.get(idx, "")
            image_path = rename_map.get(idx)

            if image_path is None:
                results.append({
                    "page_index": idx,
                    "text": text,
                    "image_path": None,
                    "error": (
                        "Slide image not generated (LibreOffice may be "
                        "unavailable or conversion failed)"
                    ),
                })
            else:
                results.append({
                    "page_index": idx,
                    "text": text,
                    "image_path": image_path,
                })

        if total_slides == 0:
            results.append({
                "page_index": 0,
                "text": "",
                "image_path": None,
                "error": (
                    "No slides found in PPTX file or file could not be opened"
                ),
            })

        return results


# ---------------------------------------------------------------------------
# Singleton (follows the project convention — see services/pdf_slides.py)
# ---------------------------------------------------------------------------

pptx_slide_service = PPTXSlideService()
