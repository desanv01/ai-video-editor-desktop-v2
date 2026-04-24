"""
Text Extraction Service — extracts text from course materials for the RAG pipeline.

Supports:
  - PDF  → pymupdf (fast, handles scanned docs with OCR fallback)
  - PPTX → python-pptx (extracts text from slides + speaker notes)
  - DOCX → python-docx (extracts paragraphs + tables)
  - TXT / MD → direct read

Each extractor returns structured output with page/slide metadata
so we can trace which part of which document a RAG result came from.
"""

import os
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class TextExtractor:
    """Extracts text from various document formats."""

    async def extract(self, file_path: str) -> dict:
        """
        Extract text from a file based on its extension.

        Returns:
            {
                "text": "Full extracted text...",
                "pages": [
                    {"page_num": 1, "text": "Page 1 content..."},
                    ...
                ],
                "metadata": {
                    "file_type": "pdf",
                    "page_count": 10,
                    "word_count": 5000,
                    "title": "Lecture Notes" (if available),
                }
            }
        """
        ext = os.path.splitext(file_path)[1].lower()

        extractors = {
            ".pdf": self._extract_pdf,
            ".pptx": self._extract_pptx,
            ".docx": self._extract_docx,
            ".txt": self._extract_text,
            ".md": self._extract_text,
            ".csv": self._extract_text,
        }

        extractor = extractors.get(ext)
        if not extractor:
            raise ValueError(f"Unsupported file type: {ext}. Supported: {list(extractors.keys())}")

        result = extractor(file_path)
        result["metadata"]["file_type"] = ext.lstrip(".")
        result["metadata"]["word_count"] = len(result["text"].split())

        logger.info(
            f"Extracted {result['metadata']['word_count']} words from "
            f"{os.path.basename(file_path)} ({ext}), "
            f"{result['metadata'].get('page_count', 'N/A')} pages"
        )

        return result

    # ──────────────────────────────────────
    #  PDF Extraction (pymupdf / fitz)
    # ──────────────────────────────────────

    def _extract_pdf(self, file_path: str) -> dict:
        """Extract text from PDF using pymupdf."""
        import fitz  # pymupdf

        doc = fitz.open(file_path)
        pages = []
        all_text = []
        page_count = len(doc)
        title = ""

        try:
            metadata = doc.metadata
            title = metadata.get("title", "") if metadata else ""
        except Exception:
            pass

        for page_num in range(page_count):
            page = doc[page_num]
            text = page.get_text("text").strip()

            if text:
                pages.append({
                    "page_num": page_num + 1,
                    "text": text,
                })
                all_text.append(text)

        doc.close()

        return {
            "text": "\n\n".join(all_text),
            "pages": pages,
            "metadata": {
                "page_count": page_count,
                "pages_with_text": len(pages),
                "title": title,
            },
        }

    # ──────────────────────────────────────
    #  PPTX Extraction (python-pptx)
    # ──────────────────────────────────────

    def _extract_pptx(self, file_path: str) -> dict:
        """Extract text from PowerPoint slides + speaker notes."""
        from pptx import Presentation

        prs = Presentation(file_path)
        pages = []
        all_text = []

        for slide_num, slide in enumerate(prs.slides, 1):
            slide_texts = []

            # Extract text from shapes (text boxes, titles, etc.)
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        para_text = paragraph.text.strip()
                        if para_text:
                            slide_texts.append(para_text)

                # Extract text from tables
                if shape.has_table:
                    table = shape.table
                    for row in table.rows:
                        row_texts = []
                        for cell in row.cells:
                            cell_text = cell.text.strip()
                            if cell_text:
                                row_texts.append(cell_text)
                        if row_texts:
                            slide_texts.append(" | ".join(row_texts))

            # Extract speaker notes
            notes_text = ""
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    slide_texts.append(f"[Speaker Notes] {notes_text}")

            if slide_texts:
                combined = "\n".join(slide_texts)
                pages.append({
                    "page_num": slide_num,
                    "text": combined,
                    "has_notes": bool(notes_text),
                })
                all_text.append(f"--- Slide {slide_num} ---\n{combined}")

        # Try to get presentation title from first slide
        title = ""
        if prs.slides and prs.slides[0].shapes.title:
            title = prs.slides[0].shapes.title.text or ""

        return {
            "text": "\n\n".join(all_text),
            "pages": pages,
            "metadata": {
                "page_count": len(prs.slides),
                "slides_with_text": len(pages),
                "title": title,
            },
        }

    # ──────────────────────────────────────
    #  DOCX Extraction (python-docx)
    # ──────────────────────────────────────

    def _extract_docx(self, file_path: str) -> dict:
        """Extract text from Word document (paragraphs + tables)."""
        from docx import Document

        doc = Document(file_path)
        all_text = []

        # Extract paragraphs
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                all_text.append(text)

        # Extract tables
        for table in doc.tables:
            for row in table.rows:
                row_texts = []
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    if cell_text:
                        row_texts.append(cell_text)
                if row_texts:
                    all_text.append(" | ".join(row_texts))

        # Try to get title from core properties
        title = ""
        try:
            if doc.core_properties and doc.core_properties.title:
                title = doc.core_properties.title
        except Exception:
            pass

        full_text = "\n\n".join(all_text)

        return {
            "text": full_text,
            "pages": [{"page_num": 1, "text": full_text}],  # DOCX doesn't have page breaks easily
            "metadata": {
                "page_count": 1,
                "paragraph_count": len(doc.paragraphs),
                "table_count": len(doc.tables),
                "title": title,
            },
        }

    # ──────────────────────────────────────
    #  Plain Text / Markdown
    # ──────────────────────────────────────

    def _extract_text(self, file_path: str) -> dict:
        """Read plain text or markdown files."""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        return {
            "text": text,
            "pages": [{"page_num": 1, "text": text}],
            "metadata": {
                "page_count": 1,
                "title": os.path.splitext(os.path.basename(file_path))[0],
            },
        }


# Singleton
text_extractor = TextExtractor()
