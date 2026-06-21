"""Semantic teaching render plan for preview and Revideo composition.

This service builds the missing middle layer between analysis and rendering:
transcript/segments + teaching structure references -> one deterministic visual
timeline.  The plan is intentionally JSON-first so it can feed Revideo, a
browser preview, or a fallback FFmpeg compositor without changing the AI/editor
contracts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from config import settings
from db.models import EditPlan, ProjectAsset, Segment, SegmentAction, Transcript, Video
from services.decision_values import normalize_confidence, normalize_slide_relation
from services.edit_plan_payload import normalize_plan_payload
from services.layout_model import LayoutMode, normalize_layout_cues
from services.lecture_structure import build_structure_references_from_assets
from services.transcript_edit_decisions import build_synced_timeline_plan


SEMANTIC_RENDER_PLAN_VERSION = "aive.render-plan.v2"
SEMANTIC_CHUNK_SECONDS = 20.0
MIN_SLIDE_MATCH_SCORE = 0.1


@dataclass(frozen=True)
class SlideCard:
    id: str
    title: str
    body: str
    bullets: list[str]
    source_filename: str | None = None
    source_asset_id: str | None = None
    reference_index: int | None = None
    image_path: str | None = None
    keywords: set[str] | None = None


def build_semantic_render_plan(
    *,
    video: Video,
    plan: EditPlan,
    segments: Iterable[Segment],
    transcript: Transcript | None = None,
    assets: Iterable[ProjectAsset] | None = None,
) -> dict[str, Any]:
    """Build the source-of-truth timeline consumed by preview and Revideo.

    The output times are based on the synced edit timeline, while semantic
    matching uses the original source-time text.  This keeps transcript cuts
    compatible with the current editor while still allowing a teaching-style
    slide timeline.
    """
    segment_list = list(segments or [])
    asset_list = list(assets or [])
    payload = normalize_plan_payload(plan.plan_json)
    duration = _duration(video, plan, segment_list)
    sync_plan = build_synced_timeline_plan(
        plan=plan,
        segments=segment_list,
        duration_seconds=duration,
    )
    cards = _slide_cards_from_assets(asset_list)
    if not cards:
        cards = _fallback_slide_cards_from_segments(segment_list, duration)
    cards = _attach_extracted_slide_paths(cards, video)

    cues = normalize_layout_cues(payload.get("layout_cues", []), duration_seconds=duration)
    slide_cues = _build_slide_cues(payload, segment_list, transcript, cards, duration)
    playable_ranges = [
        item
        for item in sync_plan.get("playable_ranges", [])
        if _range_duration(item) >= 0.05
    ]
    segment_by_id = {str(segment.id): segment for segment in segment_list}
    scenes: list[dict[str, Any]] = []
    previous_card_id = ""
    previous_topic = ""

    scene_index = 0
    for playable_range in playable_ranges:
        segment = segment_by_id.get(str(playable_range.get("segment_id")))
        if not segment:
            continue
        source_start = float(playable_range.get("source_start_time") or segment.start_time or 0.0)
        source_end = float(playable_range.get("source_end_time") or segment.end_time or source_start)
        output_start = float(playable_range.get("output_start_time") or 0.0)
        output_end = float(playable_range.get("output_end_time") or output_start)
        if output_end <= output_start:
            output_end = output_start + max(0.05, source_end - source_start)

        boundaries = _scene_boundaries(source_start, source_end, slide_cues, cues)
        for part_start, part_end in zip(boundaries, boundaries[1:]):
            if part_end - part_start < 0.05:
                continue
            scene_index += 1
            ratio_start = (part_start - source_start) / max(0.001, source_end - source_start)
            ratio_end = (part_end - source_start) / max(0.001, source_end - source_start)
            part_output_start = output_start + ((output_end - output_start) * ratio_start)
            part_output_end = output_start + ((output_end - output_start) * ratio_end)
            text = _text_for_source_range(segment, transcript, part_start, part_end)
            slide_cue = _slide_cue_at(slide_cues, part_start)
            card = _card_for_slide_cue(cards, slide_cue)
            card_id = card.id if card else ""
            layout_cue = _layout_cue_at(cues, part_start)
            layout = _scene_layout(
                segment,
                part_start,
                card,
                layout_cue,
                previous_card_id,
                previous_topic,
                has_structure=bool(cards),
            )
            transition = _scene_transition(
                cues,
                part_start,
                previous_card_id,
                card_id,
                has_previous=bool(scenes),
            )
            scene = {
            "id": f"scene-{scene_index:04d}",
            "source_segment_id": str(segment.id),
            "source_start_time": round(part_start, 3),
            "source_end_time": round(part_end, 3),
            "start_time": round(part_output_start, 3),
            "end_time": round(part_output_end, 3),
            "duration_seconds": round(max(0.05, part_output_end - part_output_start), 3),
            "layout": layout,
            "layout_cue_id": layout_cue.get("id") if layout_cue else None,
            "layout_source": (
                _layout_source(layout_cue, segment)
                if card is not None or _layout_cue_class(layout_cue) == "teacher"
                else "semantic_lecturer_only"
            ),
            "slide_cue_id": slide_cue.get("id") if slide_cue else None,
            "slide_id": card_id or None,
            "slide_title": card.title if card else "",
            "caption_text": _caption_text(text),
            "topic_label": segment.topic_label or (card.title if card else "Lecture"),
            "importance_score": segment.importance_score,
            "action": _segment_action(segment),
            "transition": transition,
            "camera": _camera_for_layout(layout, layout_cue, card=card),
            "semantic_match": {
                "score": round(float((slide_cue or {}).get("confidence") or (_match_score(card, text, segment) if card else 0.0)), 3),
                "strategy": str((slide_cue or {}).get("strategy") or "token_overlap_with_segment_topic"),
                "source": card.source_filename if card else "lecturer_only_no_relevant_slide",
            },
        }
            scenes.append(scene)
            previous_card_id = card_id
            previous_topic = str(segment.topic_label or "")

    if not scenes:
        scenes.append({
            "id": "scene-0001",
            "source_segment_id": None,
            "source_start_time": 0.0,
            "source_end_time": round(duration, 3),
            "start_time": 0.0,
            "end_time": round(duration, 3),
            "duration_seconds": round(duration, 3),
            "layout": LayoutMode.FULL_CAMERA_SOURCE.value,
            "layout_source": "semantic_lecturer_only",
            "slide_id": None,
            "slide_title": "",
            "caption_text": "",
            "topic_label": "Lecture",
            "importance_score": None,
            "action": "keep",
            "transition": {"type": "fade", "duration_seconds": 0.35},
            "camera": _camera_for_layout(LayoutMode.FULL_CAMERA_SOURCE.value),
            "semantic_match": {"score": 0.0, "strategy": "explicit_lecturer_only", "source": "lecturer_only_no_relevant_slide"},
        })

    slide_payloads = [_slide_card_payload(card, video_id=str(video.id)) for card in cards]
    clean_cuts = list(sync_plan.get("cut_intervals") or [])
    captions = _caption_events(scenes)
    transitions = [
        {"scene_id": scene["id"], "start_time": scene["start_time"], **scene["transition"]}
        for scene in scenes
    ]
    plan_identity = {
        "slide_cues": slide_cues,
        "layout_cues": cues,
        "clean_cuts": clean_cuts,
        "captions": captions,
        "transitions": transitions,
        "source_map": sync_plan.get("playable_ranges", []),
    }
    plan_hash = hashlib.sha256(
        json.dumps(plan_identity, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": SEMANTIC_RENDER_PLAN_VERSION,
        "renderer": {
            "preferred": "ffmpeg_native_semantic",
            "experimental": "revideo",
            "fallback": "legacy_ffmpeg_clips",
            "composition": "AiveLectureComposition",
        },
        "video": {
            "id": str(video.id),
            "project_id": str(video.project_id) if video.project_id else None,
            "filename": video.original_filename,
            "duration_seconds": duration,
            "source_url": f"/api/v1/videos/{video.id}/stream",
        },
        "timeline": {
            "duration_seconds": round(max(scene["end_time"] for scene in scenes), 3),
            "scene_count": len(scenes),
            "slide_count": len(slide_payloads),
            "source_duration_seconds": duration,
        },
        "plan_hash": plan_hash,
        "slide_cues": slide_cues,
        "layout_cues": cues,
        "clean_cuts": clean_cuts,
        "source_map": sync_plan.get("playable_ranges", []),
        "transitions": transitions,
        "sources": _source_manifest(video, asset_list, cards),
        "slides": slide_payloads,
        "scenes": scenes,
        "captions": captions,
        "metadata": {
            "created_by": "semantic_render_plan",
            "source": "transcript_segments_and_structure_references",
            "playable_range_count": len(playable_ranges),
            "layout_cue_count": len(cues),
            "slide_cue_count": len(slide_cues),
            "plan_hash": plan_hash,
            "structure_reference_count": sum(1 for card in cards if card.source_asset_id),
        },
    }


def with_semantic_render_plan(plan_payload: Any, render_plan: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_plan_payload(plan_payload)
    payload["render_plan"] = render_plan
    metadata = dict(payload.get("metadata") or {})
    metadata["render_plan_schema_version"] = render_plan.get("schema_version")
    metadata["render_plan_scene_count"] = render_plan.get("timeline", {}).get("scene_count", 0)
    metadata["render_plan_hash"] = render_plan.get("plan_hash")
    payload["metadata"] = metadata
    return payload


def _slide_cards_from_assets(assets: list[ProjectAsset]) -> list[SlideCard]:
    references = build_structure_references_from_assets(assets)
    cards: list[SlideCard] = []
    for reference_index, reference in enumerate(references, start=1):
        for item_index, item in enumerate(reference.get("items") or [], start=1):
            text = _clean_text(item.get("text") or item.get("title") or "")
            if not text:
                continue
            title = _first_sentence(item.get("title") or text, max_chars=72)
            body = _body_text(text, title)
            bullets = _bullets_from_text(text)
            cards.append(SlideCard(
                id=f"slide-{reference_index:02d}-{item_index:03d}",
                title=title or f"Teaching Point {item_index}",
                body=body,
                bullets=bullets,
                source_filename=reference.get("source_filename"),
                source_asset_id=reference.get("asset_id"),
                reference_index=_int_or_none(item.get("index")) or item_index,
                image_path=str(item.get("image_path") or "") or None,
                keywords=_keywords(f"{title} {text}"),
            ))
    return cards


def _fallback_slide_cards_from_segments(segments: list[Segment], duration: float) -> list[SlideCard]:
    grouped: dict[str, list[Segment]] = {}
    for segment in segments:
        key = segment.topic_label or "Lecture Overview"
        grouped.setdefault(key, []).append(segment)

    cards = []
    for index, (topic, topic_segments) in enumerate(grouped.items(), start=1):
        text = " ".join(str(segment.summary or segment.text or "") for segment in topic_segments)
        cards.append(SlideCard(
            id=f"generated-slide-{index:03d}",
            title=_first_sentence(topic, max_chars=72) or f"Lecture Section {index}",
            body=_body_text(text, topic),
            bullets=_bullets_from_text(text),
            source_filename=None,
            source_asset_id=None,
            reference_index=index,
            keywords=_keywords(f"{topic} {text}"),
        ))
    if cards:
        return cards
    return [SlideCard(
        id="generated-slide-001",
        title="Lecture Overview",
        body=f"Generated teaching structure for a {round(duration, 1)} second lecture.",
        bullets=["Review the lecture flow", "Confirm the teaching points", "Export the final lesson"],
        keywords={"lecture", "overview"},
    )]


def _best_slide_card(cards: list[SlideCard], text: str, segment: Segment, previous_card_id: str) -> SlideCard:
    scored = [(_match_score(card, text, segment), card) for card in cards]
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best = scored[0]
    if best_score <= 0.02 and previous_card_id:
        previous = next((card for card in cards if card.id == previous_card_id), None)
        if previous:
            return previous
    return best


def _attach_extracted_slide_paths(cards: list[SlideCard], video: Video) -> list[SlideCard]:
    """Attach exact PDF/PPTX page images extracted by Agent 4 when available."""
    slide_dir = os.path.join(settings.VIDEO_STORAGE_PATH, f"slides_{video.id}")
    attached: list[SlideCard] = []
    for card in cards:
        image_path = card.image_path
        page_index = max(0, int(card.reference_index or 1) - 1)
        candidate = os.path.join(slide_dir, f"page_{page_index:03d}.png")
        if not image_path and os.path.isfile(candidate):
            image_path = candidate
        attached.append(SlideCard(
            id=card.id,
            title=card.title,
            body=card.body,
            bullets=card.bullets,
            source_filename=card.source_filename,
            source_asset_id=card.source_asset_id,
            reference_index=card.reference_index,
            image_path=image_path,
            keywords=card.keywords,
        ))
    return attached


def _build_slide_cues(
    payload: dict[str, Any],
    segments: list[Segment],
    transcript: Transcript | None,
    cards: list[SlideCard],
    duration: float,
) -> list[dict[str, Any]]:
    """Return time-ranged slide choices without forcing irrelevant pages."""
    stored = payload.get("slide_cues")
    if isinstance(stored, list) and stored:
        normalized = _normalize_slide_cues(stored, cards, duration)
        if normalized:
            return _cover_slide_cue_gaps(normalized, duration)

    timeline = _stored_visual_timeline(payload)
    if timeline:
        normalized = _normalize_slide_cues(timeline, cards, duration)
        if normalized:
            return _cover_slide_cue_gaps(normalized, duration)

    cues: list[dict[str, Any]] = []
    for segment in segments:
        start = float(segment.start_time or 0.0)
        end = float(segment.end_time or start)
        if end <= start:
            continue
        chunk_count = max(1, int((end - start + SEMANTIC_CHUNK_SECONDS - 0.001) // SEMANTIC_CHUNK_SECONDS))
        chunk_duration = (end - start) / chunk_count
        for chunk_index in range(chunk_count):
            chunk_start = start + (chunk_duration * chunk_index)
            chunk_end = end if chunk_index == chunk_count - 1 else start + (chunk_duration * (chunk_index + 1))
            text = _text_for_source_range(segment, transcript, chunk_start, chunk_end)
            scored = sorted(
                ((_match_score(card, text, segment), card) for card in cards),
                key=lambda item: item[0],
                reverse=True,
            )
            score, card = scored[0] if scored else (0.0, None)
            relevant = bool(card and score >= MIN_SLIDE_MATCH_SCORE)
            cues.append({
                "id": f"slide-cue-{len(cues) + 1:04d}",
                "start_time": round(chunk_start, 3),
                "end_time": round(chunk_end, 3),
                "slide_id": card.id if relevant else None,
                "slide_index": (card.reference_index - 1) if relevant and card.reference_index else None,
                "confidence": round(score, 3),
                "strategy": "semantic_chunk_token_match",
                "reason": "Matched transcript chunk to complete slide text" if relevant else "No relevant teaching page; keep lecturer visible",
                "source_segment_id": str(segment.id),
            })
    return _cover_slide_cue_gaps(cues, duration)


def _stored_visual_timeline(payload: dict[str, Any]) -> list[dict[str, Any]]:
    visual = payload.get("visual_analysis")
    if isinstance(visual, dict) and isinstance(visual.get("slide_timeline"), list):
        return list(visual["slide_timeline"])
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("slide_timeline"), list):
        return list(metadata["slide_timeline"])
    return []


def _normalize_slide_cues(raw: list[dict[str, Any]], cards: list[SlideCard], duration: float) -> list[dict[str, Any]]:
    items = [dict(item) for item in raw if isinstance(item, dict)]
    items.sort(key=lambda item: _float_value(item.get("start_time", item.get("time_seconds", 0.0))))
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        start = max(0.0, _float_value(item.get("start_time", item.get("time_seconds", 0.0))))
        next_start = (
            max(start, _float_value(items[index + 1].get("start_time", items[index + 1].get("time_seconds", duration))))
            if index + 1 < len(items)
            else duration
        )
        end = max(start, min(duration, _float_value(item.get("end_time", next_start))))
        slide_id = item.get("slide_id")
        slide_index = _int_or_none(item.get("slide_index"))
        if not slide_id and slide_index is not None:
            card = next((candidate for candidate in cards if (candidate.reference_index or 1) - 1 == slide_index), None)
            slide_id = card.id if card else None
        confidence = normalize_confidence(item.get("confidence"), 0.75)
        cue_source = str(item.get("source") or item.get("strategy") or "").lower()
        is_teacher_choice = cue_source.startswith("teacher") or cue_source.startswith("manual")
        relation = normalize_slide_relation(
            item.get("slide_relation"),
            slide_index=slide_index,
            relevance=item.get("slide_relevance"),
        )
        review_required = bool(item.get("review_required", False)) or relation == "uncertain"
        if relation != "related" and not is_teacher_choice:
            slide_id = None
            slide_index = None
            item["reason"] = (
                "Slide relation is uncertain; keep lecturer visible pending review"
                if relation == "uncertain"
                else "Speech is unrelated to the teaching slides; keep lecturer visible"
            )
        normalized.append({
            **item,
            "id": str(item.get("id") or f"slide-cue-{index + 1:04d}"),
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "slide_id": slide_id,
            "slide_index": slide_index,
            "confidence": confidence,
            "slide_relation": relation,
            "review_required": review_required,
            "planning_status": str(item.get("planning_status") or ("needs_review" if review_required else "verified")),
            "strategy": str(item.get("strategy") or "agent4_semantic_timeline"),
        })
    return [item for item in normalized if item["end_time"] - item["start_time"] >= 0.05]


def _cover_slide_cue_gaps(cues: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    """Cover the source timeline explicitly so uncovered time never inherits a stale slide."""
    ordered = sorted((dict(cue) for cue in cues), key=lambda cue: _float_value(cue.get("start_time")))
    covered: list[dict[str, Any]] = []
    cursor = 0.0
    gap_index = 0
    for cue in ordered:
        start = max(cursor, _float_value(cue.get("start_time")))
        end = min(duration, max(start, _float_value(cue.get("end_time"))))
        if start - cursor >= 0.05:
            gap_index += 1
            covered.append(_lecturer_only_gap(cursor, start, gap_index))
        if end - start >= 0.05:
            cue["start_time"] = round(start, 3)
            cue["end_time"] = round(end, 3)
            covered.append(cue)
            cursor = end
    if duration - cursor >= 0.05:
        covered.append(_lecturer_only_gap(cursor, duration, gap_index + 1))
    return covered


def _lecturer_only_gap(start: float, end: float, index: int) -> dict[str, Any]:
    return {
        "id": f"semantic-lecturer-only-{index:04d}",
        "start_time": round(start, 3),
        "end_time": round(end, 3),
        "slide_id": None,
        "slide_index": None,
        "confidence": 1.0,
        "slide_relation": "unrelated",
        "review_required": False,
        "planning_status": "verified",
        "cue_type": "lecturer_only",
        "strategy": "explicit_timeline_coverage",
        "source": "semantic_relevance_gate",
        "reason": "No relevant slide cue covers this range",
    }


def _scene_boundaries(
    start: float,
    end: float,
    slide_cues: list[dict[str, Any]],
    layout_cues: list[dict[str, Any]],
) -> list[float]:
    boundaries = {round(start, 6), round(end, 6)}
    for cue in [*slide_cues, *layout_cues]:
        cue_start = _float_value(cue.get("start_time", cue.get("timing", {}).get("start_time", 0.0)))
        cue_end = cue.get("end_time", cue.get("timing", {}).get("end_time"))
        if start < cue_start < end:
            boundaries.add(round(cue_start, 6))
        if cue_end is not None and start < _float_value(cue_end) < end:
            boundaries.add(round(_float_value(cue_end), 6))
    return sorted(boundaries)


def _slide_cue_at(cues: list[dict[str, Any]], time_seconds: float) -> dict[str, Any] | None:
    for cue in cues:
        if time_seconds >= _float_value(cue.get("start_time")) and time_seconds < _float_value(cue.get("end_time")):
            return cue
    return None


def _card_for_slide_cue(cards: list[SlideCard], cue: dict[str, Any] | None) -> SlideCard | None:
    if not cue or not cue.get("slide_id"):
        return None
    return next((card for card in cards if card.id == str(cue.get("slide_id"))), None)


def _text_for_source_range(segment: Segment, transcript: Transcript | None, start: float, end: float) -> str:
    words = getattr(transcript, "words_json", None) if transcript else None
    if isinstance(words, list):
        parts = []
        for word in words:
            if not isinstance(word, dict):
                continue
            word_start = _float_value(word.get("start_time", word.get("start", 0.0)))
            word_end = _float_value(word.get("end_time", word.get("end", word_start)))
            if word_end >= start and word_start < end:
                parts.append(str(word.get("text", word.get("word", ""))))
        if parts:
            return " ".join(parts)
    full_text = _segment_text(segment, transcript)
    words_text = full_text.split()
    segment_duration = max(0.001, float(segment.end_time or end) - float(segment.start_time or start))
    first = int(len(words_text) * max(0.0, start - float(segment.start_time or 0.0)) / segment_duration)
    last = int(len(words_text) * max(0.0, end - float(segment.start_time or 0.0)) / segment_duration)
    return " ".join(words_text[first:max(first + 1, last)]) or full_text


def _segment_layout_mode(segment: Segment) -> str | None:
    raw = str(getattr(segment, "layout_mode", "") or "").lower()
    aliases = {
        "pip_slide": LayoutMode.PICTURE_IN_PICTURE.value,
        "picture_in_picture": LayoutMode.PICTURE_IN_PICTURE.value,
        "half_half": LayoutMode.SIDE_BY_SIDE.value,
        "side_by_side": LayoutMode.SIDE_BY_SIDE.value,
        "full_slide": LayoutMode.FULL_SCREEN_SOURCE.value,
        "full_screen_source": LayoutMode.FULL_SCREEN_SOURCE.value,
        "full_face": LayoutMode.FULL_CAMERA_SOURCE.value,
        "full_camera_source": LayoutMode.FULL_CAMERA_SOURCE.value,
    }
    return aliases.get(raw)


def _layout_source(cue: dict[str, Any] | None, segment: Segment) -> str:
    if cue:
        return str(cue.get("source") or "layout_cue")
    return "agent5_segment" if _segment_layout_mode(segment) else "project_default"


def _layout_cue_class(cue: dict[str, Any] | None) -> str:
    if not cue:
        return "none"
    source = str(cue.get("source") or "").lower()
    cue_id = str(cue.get("id") or "").lower()
    reason = str(cue.get("reason") or "").lower()
    if source.startswith("teacher") or "manual" in source or "teacher" in cue_id:
        return "teacher"
    if cue_id.startswith("layout-default") or reason.startswith("default full-screen"):
        return "default"
    return "ai"


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _match_score(card: SlideCard | None, text: str, segment: Segment) -> float:
    if card is None:
        return 0.0
    segment_terms = _keywords(f"{segment.topic_label or ''} {segment.summary or ''} {text}")
    if not segment_terms:
        return 0.0
    card_terms = card.keywords or _keywords(f"{card.title} {card.body} {' '.join(card.bullets)}")
    if not card_terms:
        return 0.0
    overlap = len(segment_terms & card_terms)
    topic_bonus = 0.12 if segment.topic_label and _normalize(segment.topic_label) in _normalize(card.title) else 0.0
    return min(1.0, (overlap / max(6, len(segment_terms))) + topic_bonus)


def _scene_layout(
    segment: Segment,
    source_start: float,
    card: SlideCard | None,
    cue: dict[str, Any] | None,
    previous_card_id: str,
    previous_topic: str,
    *,
    has_structure: bool,
) -> str:
    cue_layout = str(cue.get("layout") or "") if cue else ""
    cue_class = _layout_cue_class(cue)
    if cue_class == "teacher" and cue_layout in {mode.value for mode in LayoutMode}:
        return cue_layout
    if card is None or not has_structure:
        return LayoutMode.FULL_CAMERA_SOURCE.value
    if cue_class == "ai" and cue_layout in {mode.value for mode in LayoutMode}:
        return cue_layout
    segment_layout = _segment_layout_mode(segment)
    if segment_layout:
        return segment_layout
    if cue_layout in {mode.value for mode in LayoutMode}:
        return cue_layout
    if source_start <= 20:
        return LayoutMode.SIDE_BY_SIDE.value
    if previous_card_id and previous_card_id != card.id:
        return LayoutMode.SIDE_BY_SIDE.value
    if previous_topic and segment.topic_label and previous_topic != segment.topic_label:
        return LayoutMode.SIDE_BY_SIDE.value
    if _segment_action(segment) == SegmentAction.HIGHLIGHT.value:
        return LayoutMode.FULL_SCREEN_SOURCE.value
    return LayoutMode.PICTURE_IN_PICTURE.value


def _scene_transition(
    cues: list[dict[str, Any]],
    source_start: float,
    previous_card_id: str,
    card_id: str,
    *,
    has_previous: bool,
) -> dict[str, Any]:
    cue = _layout_cue_at(cues, source_start)
    timing = cue.get("timing") if isinstance(cue, dict) else {}
    cue_start = _float_value((cue or {}).get("start_time", (timing or {}).get("start_time")))
    visual_boundary = has_previous and (
        previous_card_id != card_id
        or abs(cue_start - source_start) <= 0.01
    )
    transition_type = str((timing or {}).get("transition_in") or "cut") if visual_boundary else "cut"
    return {
        "type": transition_type,
        "duration_seconds": (
            float((timing or {}).get("transition_duration_seconds") or 0.35)
            if visual_boundary
            else 0.0
        ),
    }


def _layout_cue_at(cues: list[dict[str, Any]], time_seconds: float) -> dict[str, Any] | None:
    for cue in cues:
        start = float(cue.get("start_time") or cue.get("timing", {}).get("start_time") or 0.0)
        end_raw = cue.get("end_time", cue.get("timing", {}).get("end_time"))
        end = float(end_raw) if end_raw is not None else None
        if time_seconds >= start and (end is None or time_seconds < end):
            return cue
    return cues[0] if cues else None


def _camera_for_layout(
    layout: str,
    cue: dict[str, Any] | None = None,
    *,
    card: SlideCard | None = None,
) -> dict[str, Any]:
    enabled = layout in {
        LayoutMode.PICTURE_IN_PICTURE.value,
        LayoutMode.SIDE_BY_SIDE.value,
        LayoutMode.FULL_CAMERA_SOURCE.value,
    }
    camera = dict((cue or {}).get("camera") or {})
    return {
        "enabled": enabled,
        "shape": camera.get("shape") or ("circle" if layout == LayoutMode.PICTURE_IN_PICTURE.value else "rounded_rectangle"),
        "corner": camera.get("corner") or ("bottom_right" if card is not None else "top_right"),
        "size": camera.get("size") or ("medium" if layout == LayoutMode.PICTURE_IN_PICTURE.value else "large"),
        "margin_percent": camera.get("margin_percent", 4),
        "safe_area_strategy": "teacher_override" if camera.get("corner") else "avoid_slide_title_band",
    }


def _default_layout_for_assets(assets: list[ProjectAsset], cards: list[SlideCard]) -> str:
    has_structure = any(card.source_asset_id for card in cards)
    has_camera = any(_enum_value(asset.role) == "camera" or _enum_value(asset.sync_role) == "camera_overlay" for asset in assets)
    has_primary = any(_enum_value(asset.role) == "primary" for asset in assets)
    if has_structure and (has_camera or has_primary):
        return LayoutMode.PICTURE_IN_PICTURE.value
    if has_camera:
        return LayoutMode.FULL_CAMERA_SOURCE.value
    return LayoutMode.FULL_SCREEN_SOURCE.value


def _source_manifest(video: Video, assets: list[ProjectAsset], cards: list[SlideCard]) -> dict[str, Any]:
    return {
        "primary_video": {
            "video_id": str(video.id),
            "filename": video.original_filename,
            "url": f"/api/v1/videos/{video.id}/stream",
        },
        "project_assets": [
            {
                "id": str(asset.id),
                "filename": asset.original_filename,
                "role": _enum_value(asset.role),
                "kind": _enum_value(asset.kind),
                "sync_role": _enum_value(asset.sync_role),
                "duration_seconds": asset.duration_seconds,
            }
            for asset in assets
        ],
        "slide_sources": sorted({
            str(card.source_filename)
            for card in cards
            if card.source_filename
        }),
    }


def _caption_events(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"caption-{scene['id']}",
            "start_time": scene["start_time"],
            "end_time": scene["end_time"],
            "text": scene["caption_text"],
        }
        for scene in scenes
        if scene.get("caption_text")
    ]


def _slide_card_payload(card: SlideCard, *, video_id: str) -> dict[str, Any]:
    return {
        "id": card.id,
        "title": card.title,
        "body": card.body,
        "bullets": card.bullets,
        "source_filename": card.source_filename,
        "source_asset_id": card.source_asset_id,
        "reference_index": card.reference_index,
        "image_path": card.image_path,
        "image_url": f"/api/v1/videos/{video_id}/render-plan/slides/{card.id}" if card.image_path else None,
    }


def _duration(video: Video, plan: EditPlan, segments: list[Segment]) -> float:
    candidates = [
        video.duration_seconds,
        plan.original_duration,
        max((segment.end_time for segment in segments), default=0.0),
    ]
    return max(float(value or 0.0) for value in candidates) or 0.1


def _range_duration(playable_range: dict[str, Any]) -> float:
    if playable_range.get("duration") is not None:
        return float(playable_range.get("duration") or 0.0)
    return float(playable_range.get("output_end_time") or 0.0) - float(playable_range.get("output_start_time") or 0.0)


def _segment_text(segment: Segment, transcript: Transcript | None) -> str:
    if segment.text:
        return str(segment.text)
    if transcript and isinstance(transcript.segments_json, list):
        parts = []
        for item in transcript.segments_json:
            if not isinstance(item, dict):
                continue
            start = float(item.get("start") or 0.0)
            end = float(item.get("end") or start)
            if end >= segment.start_time and start <= segment.end_time:
                parts.append(str(item.get("text") or ""))
        return " ".join(parts)
    return str(segment.summary or segment.topic_label or "")


def _segment_action(segment: Segment) -> str:
    action = segment.teacher_action or segment.action or SegmentAction.KEEP
    return action.value if hasattr(action, "value") else str(action)


def _caption_text(text: str) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= 160:
        return cleaned
    return cleaned[:157].rstrip() + "..."


def _body_text(text: str, title: str) -> str:
    cleaned = _clean_text(text)
    title_norm = _normalize(title)
    if title_norm and _normalize(cleaned).startswith(title_norm):
        cleaned = cleaned[len(title):].strip(" :-\n\t")
    sentences = _sentences(cleaned)
    return " ".join(sentences[:2])[:260]


def _bullets_from_text(text: str) -> list[str]:
    bullets: list[str] = []
    for sentence in _sentences(text):
        item = sentence.strip(" -\t\n")
        if len(item) < 8:
            continue
        bullets.append(item[:120])
        if len(bullets) >= 4:
            break
    return bullets or [_first_sentence(text, max_chars=120)]


def _first_sentence(text: Any, *, max_chars: int) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    first = _sentences(cleaned)[0] if _sentences(cleaned) else cleaned
    return first[:max_chars].rstrip(" ,;:")


def _sentences(text: Any) -> list[str]:
    cleaned = _clean_text(text)
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", cleaned) if part.strip()]


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9]{3,}", _normalize(text))
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "are", "you",
        "your", "will", "have", "has", "about", "into", "then", "also",
        "today", "class", "lecture", "session", "students", "maybe",
    }
    return {word for word in words if word not in stop}


def _clean_text(text: Any) -> str:
    return " ".join(str(text or "").replace("\x00", " ").split())


def _normalize(text: Any) -> str:
    return _clean_text(text).lower()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _enum_value(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else value or "").lower()
