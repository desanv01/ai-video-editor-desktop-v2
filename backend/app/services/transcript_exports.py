"""Export stored original-recording transcripts without ASR, edits, or rendering."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any


TRANSCRIPT_EXPORT_SCHEMA_VERSION = "aive.original-transcript.v1"
TRANSCRIPT_EXPORT_FORMATS = {
    "txt": ("original_transcript_txt", "original_transcript.txt", "text/plain", "Original transcript (TXT)"),
    "timestamped_txt": (
        "original_transcript_timestamped_txt", "original_transcript_timestamped.txt",
        "text/plain", "Original transcript with timestamps (TXT)",
    ),
    "json": ("original_transcript_json", "original_transcript.json", "application/json", "Original transcript (JSON)"),
    "csv": ("original_transcript_segments_csv", "original_transcript_segments.csv", "text/csv", "Original transcript segments (CSV)"),
}
TRANSCRIPT_CSV_FIELDS = ["segment_index", "start_seconds", "end_seconds", "speaker", "text", "timing_source"]


class TranscriptExportUnavailable(ValueError):
    """The stored transcript cannot supply the requested format yet."""


def _stored_items(transcript: Any, field: str) -> list[dict[str, Any]]:
    value = getattr(transcript, field, None)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def original_transcript_text(transcript: Any) -> tuple[str, str]:
    """Prefer the exact stored full text; support older records lacking full_text."""
    full_text = getattr(transcript, "full_text", None)
    if isinstance(full_text, str) and full_text.strip():
        return full_text, "stored_full_text"
    segments = _stored_items(transcript, "segments_json")
    text = "\n".join(str(item.get("text") or "") for item in segments if str(item.get("text") or "").strip())
    if text:
        return text, "stored_segments"
    words = _stored_items(transcript, "words_json")
    text = " ".join(str(item.get("word") or item.get("text") or "") for item in words
                    if str(item.get("word") or item.get("text") or "").strip())
    return text, "stored_words"


def _seconds(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def original_transcript_segments(transcript: Any) -> list[dict[str, Any]]:
    """Keep provider segment order and text; never derive timing from edit segments."""
    rows = []
    for index, segment in enumerate(_stored_items(transcript, "segments_json")):
        start = _seconds(segment.get("start", segment.get("start_time")))
        end = _seconds(segment.get("end", segment.get("end_time")))
        valid = start is not None and end is not None and end >= start
        rows.append({
            "segment_index": index,
            "start_seconds": start if valid else None,
            "end_seconds": end if valid else None,
            "speaker": segment.get("speaker"),
            "text": str(segment.get("text") or ""),
            "timing_source": "stored_transcript_segment" if valid else "unavailable",
        })
    return rows


def transcript_export_availability(transcript: Any) -> dict[str, dict[str, Any]]:
    text, _ = original_transcript_text(transcript)
    rows = original_transcript_segments(transcript)
    ready = bool(transcript is not None and text.strip())
    has_segments = any(row["text"].strip() for row in rows)
    has_timing = any(row["text"].strip() and row["timing_source"] != "unavailable" for row in rows)
    result = {}
    for format_name in TRANSCRIPT_EXPORT_FORMATS:
        available = ready
        reason = None if ready else "Original transcript is not available yet."
        if ready and format_name == "csv" and not has_segments:
            available, reason = False, "Stored transcript segments are not available."
        if ready and format_name == "timestamped_txt" and not has_timing:
            available, reason = False, "Stored transcript segment timestamps are not available."
        result[format_name] = {"available": available, "reason": reason}
    return result


def transcript_export_catalog(video_id: Any, transcript: Any) -> dict[str, dict[str, Any]]:
    availability = transcript_export_availability(transcript)
    return {
        kind: {
            **availability[format_name], "label": label, "format": format_name,
            "media_type": media_type, "timeline": "original_recording",
            "path": f"/api/v1/videos/{video_id}/transcript/export?format={format_name}",
        }
        for format_name, (kind, _suffix, media_type, label) in TRANSCRIPT_EXPORT_FORMATS.items()
    }


def transcript_download_filename(video: Any, format_name: str) -> str:
    suffix = TRANSCRIPT_EXPORT_FORMATS[format_name][1]
    # Source names are display metadata, never trusted paths or response headers.
    name = re.split(r"[/\\]", str(getattr(video, "original_filename", None) or "lecture"))[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", stem).strip(" .")[:120] or "lecture"
    return f"{stem}_{suffix}"


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_transcript_export(video: Any, transcript: Any, format_name: str) -> str:
    if format_name not in TRANSCRIPT_EXPORT_FORMATS:
        raise ValueError(f"Unsupported transcript export format: {format_name}")
    availability = transcript_export_availability(transcript)[format_name]
    if not availability["available"]:
        raise TranscriptExportUnavailable(availability["reason"])
    text, text_source = original_transcript_text(transcript)
    rows = original_transcript_segments(transcript)
    if format_name == "txt":
        return text
    if format_name == "timestamped_txt":
        blocks = ["Original recording transcript — timestamps refer to the uploaded recording."]
        for row in rows:
            if row["timing_source"] == "unavailable":
                timing = "[Timing unavailable]"
            else:
                timing = f"[{_timestamp(row['start_seconds'])} → {_timestamp(row['end_seconds'])}]"
            speaker = f" {row['speaker']}" if row["speaker"] else ""
            blocks.append(f"{timing}{speaker}\n{row['text']}")
        return "\n\n".join(blocks) + "\n"
    if format_name == "csv":
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=TRANSCRIPT_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
    payload = {
        "schema_version": TRANSCRIPT_EXPORT_SCHEMA_VERSION,
        "transcript_variant": "original", "timeline": "original_recording",
        "video": {
            "id": str(video.id), "original_filename": getattr(video, "original_filename", None),
            "duration_seconds": getattr(video, "duration_seconds", None),
        },
        "transcript_id": str(transcript.id),
        "created_at": getattr(transcript, "created_at", None),
        "language": getattr(transcript, "language", None),
        "asr_provider": getattr(transcript, "asr_provider", None),
        "word_count": getattr(transcript, "word_count", None),
        "full_text": getattr(transcript, "full_text", None),
        "text": text, "text_source": text_source,
        "words": getattr(transcript, "words_json", None) or [],
        "segments": getattr(transcript, "segments_json", None) or [],
        "speakers": getattr(transcript, "speakers_json", None) or [],
        "segment_rows": rows,
        "timing_note": "Timing is copied from the stored transcript; upstream timing provenance may be unavailable. No timing is estimated during export and no edit decisions are applied.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"


def write_transcript_artifacts(video: Any, transcript: Any, storage_path: str) -> dict[str, str | None]:
    """Materialize the same downloads for bundles and render artifact manifests."""
    paths = {}
    availability = transcript_export_availability(transcript)
    for format_name, (kind, suffix, _media_type, _label) in TRANSCRIPT_EXPORT_FORMATS.items():
        path = Path(storage_path) / f"{video.id}_{suffix}"
        if not availability[format_name]["available"]:
            path.unlink(missing_ok=True)  # Do not bundle a previous transcript's stale file.
            paths[kind] = None
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
                temporary_path = handle.name
                handle.write(format_transcript_export(video, transcript, format_name))
            os.replace(temporary_path, path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
        paths[kind] = str(path)
    return paths
