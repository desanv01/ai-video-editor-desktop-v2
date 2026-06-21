"""
PDF Slide Extractor Service

Converts each page of a PDF file into a high-resolution PNG image and
extracts per-page text using PyMuPDF (fitz) for rendering and Pillow for
image processing.

Typical use:
    from services.pdf_slides import pdf_slide_service

    pages = await pdf_slide_service.extract_pdf_pages("/path/to/slides.pdf", "/output/dir")
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports – PyMuPDF and Pillow are only loaded when the service is used.
# This keeps the module importable even when the optional dependencies are
# missing, and callers get a clear error message at runtime.
# ---------------------------------------------------------------------------

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 200 DPI is a good default: for a typical 16:9 slide (10″ × 5.625″) it
# yields ~2000 × 1125 px, close to the 1920 × 1080 target.
DEFAULT_DPI: int = 200

# Minimum DPI we allow – anything lower risks unreadable text.
MIN_DPI: int = 72


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_fitz() -> None:
    """Raise a clear error if PyMuPDF is not installed."""
    if fitz is None:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF processing. "
            "Install it with: pip install PyMuPDF"
        )


def _require_pillow() -> None:
    """Raise a clear error if Pillow is not installed."""
    if Image is None:
        raise ImportError(
            "Pillow is required for image processing. "
            "Install it with: pip install Pillow"
        )


def _sanitise_dpi(dpi: int) -> int:
    """Clamp the DPI to a sensible range."""
    if dpi < MIN_DPI:
        logger.warning("DPI %d is below minimum; clamping to %d.", dpi, MIN_DPI)
        return MIN_DPI
    return dpi


def _count_words(text: Optional[str]) -> int:
    """Return a whitespace-based word count, handling None / empty strings."""
    if not text:
        return 0
    return len(text.split())


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class PdfSlideService:
    """Service for extracting slide images and text from PDF files.

    All methods are async static methods so they can be called either through
    the module-level singleton ``pdf_slide_service`` or directly on the class.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    async def get_pdf_page_count(pdf_path: str) -> int:
        """Get the total number of pages in a PDF file.

        Args:
            pdf_path: Absolute path to the PDF file.

        Returns:
            Number of pages (>= 0).

        Raises:
            FileNotFoundError: If *pdf_path* does not exist.
            RuntimeError: If the PDF cannot be opened (corrupted, encrypted, etc.).
            ImportError: If PyMuPDF is not installed.
        """
        _require_fitz()

        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            doc = fitz.open(pdf_path)
            try:
                if doc.is_encrypted:
                    # Attempt to authenticate with an empty password;
                    # many "encrypted" PDFs use a blank owner password.
                    if not doc.authenticate(""):
                        logger.warning(
                            "PDF '%s' is encrypted and could not be authenticated. "
                            "Page count may be inaccurate.",
                            pdf_path,
                        )
                return len(doc)
            finally:
                doc.close()
        except Exception as exc:
            logger.error("Failed to open PDF '%s': %s", pdf_path, exc)
            raise RuntimeError(f"Failed to open PDF: {exc}") from exc

    @staticmethod
    async def extract_pdf_page(
        pdf_path: str,
        page_index: int,
        output_path: str,
        dpi: int = DEFAULT_DPI,
    ) -> Dict:
        """Extract a single PDF page as a high-resolution PNG with text.

        Args:
            pdf_path:   Absolute path to the PDF file.
            page_index: 0-based page number to extract.
            output_path:Where to save the PNG image (parent dirs created as needed).
            dpi:        Render resolution (default 200).

        Returns:
            {
                "page_index": 0,
                "image_path": "/abs/path/to/output.png",
                "width":      2000,
                "height":     1125,
                "text":       "Full page text...",
                "word_count": 150,
            }

        Raises:
            FileNotFoundError: If *pdf_path* does not exist.
            ValueError:        If *page_index* is out of range.
            RuntimeError:      If rendering fails.
            ImportError:       If PyMuPDF or Pillow is missing.
        """
        _require_fitz()
        _require_pillow()
        dpi = _sanitise_dpi(dpi)

        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            doc = fitz.open(pdf_path)
            try:
                if page_index < 0 or page_index >= len(doc):
                    raise ValueError(
                        f"Page index {page_index} is out of range "
                        f"(0–{len(doc) - 1})"
                    )

                page = doc.load_page(page_index)

                # Render page to a pixmap at the requested DPI ------------------
                pix = page.get_pixmap(dpi=dpi)

                # Convert raw samples → Pillow Image → PNG on disk --------------
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                out_dir = os.path.dirname(output_path)
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                img.save(output_path, "PNG")

                # Extract text --------------------------------------------------
                text = page.get_text()

                logger.debug(
                    "Extracted page %d → %s (%d×%d, %d words)",
                    page_index, output_path, pix.width, pix.height,
                    _count_words(text),
                )

                return {
                    "page_index": page_index,
                    "image_path": output_path,
                    "width": pix.width,
                    "height": pix.height,
                    "text": text,
                    "word_count": _count_words(text),
                }

            finally:
                doc.close()
        except (ValueError, FileNotFoundError):
            raise
        except Exception as exc:
            logger.error(
                "Failed to extract page %d from '%s': %s",
                page_index, pdf_path, exc,
            )
            raise RuntimeError(
                f"Failed to extract page {page_index}: {exc}"
            ) from exc

    @staticmethod
    async def extract_pdf_pages(
        pdf_path: str,
        output_dir: str,
        dpi: int = DEFAULT_DPI,
        skip_existing: bool = True,
    ) -> List[Dict]:
        """Convert each PDF page to a high-res PNG and extract per-page text.

        Images are named ``page_000.png``, ``page_001.png``, … inside
        *output_dir* (zero-padded to three digits).

        Args:
            pdf_path:      Absolute path to the PDF file.
            output_dir:    Directory to save page images (created if missing).
            dpi:           Render resolution (default 200).
            skip_existing: If True (default), pages whose PNG already exists
                           on disk are not re-rendered.

        Returns:
            [
                {
                    "page_index": 0,
                    "image_path": "/abs/path/to/page_000.png",
                    "width":      2000,
                    "height":     1125,
                    "text":       "Full page text...",
                    "word_count": 150,
                },
                ...
            ]

            Pages that could not be processed are still included but carry
            ``"error"`` and ``None`` for the data fields.
        """
        _require_fitz()
        _require_pillow()
        dpi = _sanitise_dpi(dpi)

        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        os.makedirs(output_dir, exist_ok=True)

        results: List[Dict] = []

        try:
            doc = fitz.open(pdf_path)
            try:
                total = len(doc)

                if doc.is_encrypted:
                    if not doc.authenticate(""):
                        logger.warning(
                            "PDF '%s' is encrypted and could not be authenticated. "
                            "Extraction may fail.",
                            pdf_path,
                        )
                    else:
                        logger.info("PDF '%s' authenticated successfully.", pdf_path)

                for idx in range(total):
                    filename = f"page_{idx:03d}.png"
                    out_path = os.path.join(output_dir, filename)

                    # ---- cache hit -------------------------------------------------
                    if skip_existing and os.path.isfile(out_path):
                        logger.debug(
                            "Page %d/%d already exists at %s, using cached image.",
                            idx + 1, total, out_path,
                        )
                        try:
                            page = doc.load_page(idx)
                            text = page.get_text()
                        except Exception:
                            text = ""
                        results.append({
                            "page_index": idx,
                            "image_path": out_path,
                            "width": None,
                            "height": None,
                            "text": text,
                            "word_count": _count_words(text),
                            "cached": True,
                        })
                        continue

                    # ---- render ----------------------------------------------------
                    try:
                        page = doc.load_page(idx)
                        pix = page.get_pixmap(dpi=dpi)

                        img = Image.frombytes(
                            "RGB", [pix.width, pix.height], pix.samples
                        )
                        img.save(out_path, "PNG")

                        text = page.get_text()

                        results.append({
                            "page_index": idx,
                            "image_path": out_path,
                            "width": pix.width,
                            "height": pix.height,
                            "text": text,
                            "word_count": _count_words(text),
                            "cached": False,
                        })

                        logger.info(
                            "Extracted page %d/%d → %s (%d×%d, %d words)",
                            idx + 1, total, out_path,
                            pix.width, pix.height, _count_words(text),
                        )

                    except Exception as exc:
                        logger.error(
                            "Failed to process page %d of '%s': %s",
                            idx, pdf_path, exc,
                        )
                        results.append({
                            "page_index": idx,
                            "image_path": None,
                            "width": None,
                            "height": None,
                            "text": None,
                            "word_count": 0,
                            "error": str(exc),
                        })

            finally:
                doc.close()
        except Exception as exc:
            logger.error("Failed to process PDF '%s': %s", pdf_path, exc)
            raise RuntimeError(f"Failed to process PDF: {exc}") from exc

        return results


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

async def get_pdf_page_count(pdf_path: str) -> int:
    """Module-level shortcut for :meth:`PdfSlideService.get_pdf_page_count`."""
    return await PdfSlideService.get_pdf_page_count(pdf_path)


async def extract_pdf_page(
    pdf_path: str,
    page_index: int,
    output_path: str,
    dpi: int = DEFAULT_DPI,
) -> Dict:
    """Module-level shortcut for :meth:`PdfSlideService.extract_pdf_page`."""
    return await PdfSlideService.extract_pdf_page(
        pdf_path, page_index, output_path, dpi=dpi
    )


async def extract_pdf_pages(
    pdf_path: str,
    output_dir: str,
    dpi: int = DEFAULT_DPI,
    skip_existing: bool = True,
) -> List[Dict]:
    """Module-level shortcut for :meth:`PdfSlideService.extract_pdf_pages`."""
    return await PdfSlideService.extract_pdf_pages(
        pdf_path, output_dir, dpi=dpi, skip_existing=skip_existing
    )


# ---------------------------------------------------------------------------
# Singleton (follows the project convention — see services/ffmpeg.py)
# ---------------------------------------------------------------------------

pdf_slide_service = PdfSlideService()
