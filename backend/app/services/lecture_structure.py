"""Helpers for extracting slide/PDF structure cues from project teaching assets."""

from __future__ import annotations

import os
from typing import Any, Iterable

from services.text_extraction import text_extractor


STRUCTURE_REFERENCE_METADATA_KEY = "structure_reference"
SUPPORTED_STRUCTURE_EXTENSIONS = {".pdf", ".pptx", ".docx", ".txt", ".md", ".csv"}


async def extract_structure_reference_metadata(
    *,
    file_path: str,
    original_filename: str,
    structure_reference_role: str,
) -> dict[str, Any]:
    """Extract compact page/slide titles for later section segmentation."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_STRUCTURE_EXTENSIONS:
        return {
            "text_extraction_status": "unsupported",
            "text_extraction_error": f"Structure extraction is not supported for {ext or 'unknown files'}.",
        }

    extraction = await text_extractor.extract(file_path)
    metadata = extraction.get("metadata") or {}
    pages = extraction.get("pages") or []
    items = [
        item
        for page in pages
        if (item := _structure_item_from_page(page, structure_reference_role))
    ]

    return {
        "text_extraction_status": "complete",
        "structure_title": _first_non_empty(metadata.get("title"), _filename_title(original_filename)),
        STRUCTURE_REFERENCE_METADATA_KEY: {
            "title": _first_non_empty(metadata.get("title"), _filename_title(original_filename)),
            "reference_role": structure_reference_role,
            "document_format": metadata.get("file_type") or ext.lstrip("."),
            "page_count": metadata.get("page_count"),
            "word_count": metadata.get("word_count"),
            "items": items,
        },
    }


def build_structure_references_from_assets(assets: Iterable[Any] | None) -> list[dict[str, Any]]:
    """Return normalized teaching-material references from project asset metadata."""
    references: list[dict[str, Any]] = []
    for asset in assets or []:
        metadata = dict(getattr(asset, "metadata_json", None) or {})
        structure = metadata.get(STRUCTURE_REFERENCE_METADATA_KEY)
        if not isinstance(structure, dict):
            structure = _legacy_structure_reference(metadata)
        if not structure:
            continue

        items = structure.get("items") or []
        if not items:
            continue

        references.append({
            "asset_id": str(getattr(asset, "id", "") or ""),
            "source_filename": getattr(asset, "original_filename", None)
            or getattr(asset, "filename", None),
            "reference_role": structure.get("reference_role")
            or metadata.get("structure_reference_role")
            or getattr(getattr(asset, "role", None), "value", None),
            "document_format": structure.get("document_format") or metadata.get("document_format"),
            "title": structure.get("title") or metadata.get("structure_title"),
            "items": items,
        })
    return references


def _legacy_structure_reference(metadata: dict[str, Any]) -> dict[str, Any] | None:
    user_metadata = metadata.get("user_metadata") if isinstance(metadata.get("user_metadata"), dict) else {}
    candidate = metadata.get("slide_titles") or metadata.get("page_titles") or user_metadata.get("slide_titles")
    if not candidate:
        return None
    items = []
    for index, value in enumerate(candidate, 1):
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault("index", index)
        else:
            item = {"index": index, "title": str(value)}
        items.append(item)
    return {
        "title": metadata.get("structure_title"),
        "reference_role": metadata.get("structure_reference_role"),
        "document_format": metadata.get("document_format"),
        "items": items,
    }


def _structure_item_from_page(page: dict[str, Any], role: str) -> dict[str, Any] | None:
    text = str(page.get("text") or "").strip()
    if not text:
        return None
    index = page.get("page_num") or page.get("slide_num") or page.get("index")
    title = _title_from_text(text)
    return {
        "index": index,
        "title": title,
        "text": text[:1200],
        "reference_role": role,
    }


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        cleaned = " ".join(line.strip().split())
        if cleaned and not cleaned.lower().startswith("[speaker notes]"):
            return cleaned[:100]
    return ""


def _filename_title(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    return " ".join(part for part in stem.replace("_", " ").replace("-", " ").split())


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = " ".join(str(value or "").strip().split())
        if text:
            return text
    return ""
