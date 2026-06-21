"""
Agent 3 — Fluency & Filler Agent

Phase D: Full analysis agent.

Goal: Detect delivery quality issues — filler words, repetitions, pauses.

Two parallel sub-tasks:
  (a) Acoustic analysis: silence/pause detection via ffmpeg silencedetect
  (b) Linguistic analysis: filler word + repetition detection via LLM

The results are merged onto Segment records created by Agent 2.
Agent 5 uses both importance (Agent 2) and fluency (Agent 3) signals
to decide which segments to cut/keep.
"""

import os
import logging
import re
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Video, Transcript, Segment
from services.ffmpeg import ffmpeg_service
from services.llm import llm_service
from providers import ProviderKind
from config import settings

logger = logging.getLogger(__name__)

FALLBACK_FILLER_PHRASES = (
    # English fillers
    ("um",),
    ("uh",),
    ("erm",),
    ("er",),
    ("ah",),
    ("hmm",),
    ("mmm",),
    ("mm",),
    ("like",),
    ("basically",),
    ("actually",),
    ("right",),
    ("so",),
    ("well",),
    ("okay",),
    ("anyway",),
    ("literally",),
    ("honestly",),
    ("seriously",),
    ("obviously",),
    ("essentially",),
    ("technically",),
    ("literally",),
    # Multi-word fillers
    ("you", "know"),
    ("i", "mean"),
    ("sort", "of"),
    ("kind", "of"),
    ("okay", "so"),
    ("you", "see"),
    ("you", "know", "what", "i", "mean"),
    ("i", "guess"),
    ("i", "think"),
    ("i", "suppose"),
    ("the", "thing", "is"),
    ("as", "i", "was", "saying"),
    # Malay / Manglish fillers (lecturer context)
    ("sekejap",),
    ("kejap",),
    ("macam",),
    ("aa",),
    ("aaa",),
    ("eeee",),
    ("ee",),
    ("jadi",),
    ("ok",),
    ("yelah",),
    ("mcm",),
    ("tau",),
    ("kan",),
    ("boleh",),
    ("err",),
    # False start / self-correction markers
    ("actually", "let", "me", "restart"),
    ("let", "me", "rephrase"),
    ("sorry", "let", "me"),
    ("i", "mean", "let", "me"),
    ("wait", "no"),
    ("hold", "on"),
    ("let", "me", "start", "again"),
    ("let", "me", "try", "again"),
)

FILLER_DETECTION_PROMPT = """You are a speech fluency analyzer

1. FILLER WORDS: "um", "uh", "like", "you know", "so", "basically", "actually", "right", "okay so", "sort of", "kind of", "I mean", "erm", "ah"
   - Count each occurrence separately (e.g., "um...um...like" = 3 fillers)

2. VERBAL REPETITIONS: Speaker restarts a sentence or repeats the same phrase
   - e.g., "the algorithm the algorithm works by..."
   - e.g., "so what we... so what we need to do is..."

3. HESITATIONS: Incomplete thoughts, false starts, trailing off mid-sentence

4. FLUENCY SCORE: Overall delivery quality from 0.0 to 1.0
   - 1.0 = Perfectly fluent, professional delivery
   - 0.7-0.9 = Minor occasional fillers, still clear
   - 0.4-0.6 = Noticeable fillers/repetitions, somewhat distracting
   - 0.1-0.3 = Frequent disfluencies, hard to follow
   - 0.0 = Mostly unintelligible or pure filler

IMPORTANT: Return ONLY valid JSON. No markdown.

{
  "segments": [
    {
      "segment_index": 0,
      "filler_count": 3,
      "filler_words": ["um", "like", "you know"],
      "has_repetition": false,
      "repetition_details": null,
      "fluency_score": 0.7
    }
  ]
}"""


async def run_fluency_agent(video_id: str, db: AsyncSession) -> dict:
    """
    Detect filler words, pauses, and disfluencies in the lecture.

    Steps:
        1. Detect silence/pauses via ffmpeg (acoustic analysis)
        2. Load segments created by Agent 2
        3. Analyze transcript text for fillers via LLM (linguistic analysis)
        4. Merge acoustic + linguistic results into Segment records

    Returns:
        {"status": "success", "total_fillers": N, "total_pause_duration": N, "segments_updated": N}
    """
    video = await db.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")

    # ── Step 1: Acoustic pause detection ──
    pauses = []
    if video.audio_path and os.path.exists(video.audio_path):
        try:
            pauses = await ffmpeg_service.detect_silence(
                audio_path=video.audio_path,
                threshold_db=settings.SILENCE_THRESHOLD_DB,
                min_duration=settings.SILENCE_MIN_DURATION,
            )
            logger.info(f"Agent 3: Detected {len(pauses)} silence regions")
        except Exception as e:
            logger.warning(f"Agent 3: Silence detection failed (non-fatal): {e}")
    else:
        logger.warning(f"Agent 3: No audio file found at {video.audio_path}, skipping silence detection")

    # ── Step 2: Load segments (created by Agent 2) ──
    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    segments = list(result.scalars().all())

    if not segments:
        logger.warning(f"Agent 3: No segments found for video {video_id}")
        raise ValueError(
            "No Agent 2 segments were available for delivery analysis. "
            "Content analysis must commit segments before Agent 3 runs."
        )

    logger.info(f"Agent 3: Analyzing {len(segments)} segments for fluency")

    # ── Step 3: Linguistic filler detection via LLM ──
    total_fillers = 0
    total_pause_duration = sum(p.get("duration", 0) for p in pauses)
    batches_attempted = 0
    batches_failed = 0
    fallback_segments = 0

    batch_size = 8  # Slightly smaller batches = more reliable JSON from LLM
    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start:batch_start + batch_size]
        batches_attempted += 1

        segment_texts = []
        for seg in batch:
            text = seg.text or ""
            # Truncate very long segments to avoid token overflow
            if len(text) > 1500:
                text = text[:1500] + "..."
            segment_texts.append(
                f"Segment {seg.segment_index} [{seg.start_time:.1f}s - {seg.end_time:.1f}s]:\n{text}"
            )

        messages = [
            {"role": "system", "content": FILLER_DETECTION_PROMPT},
            {"role": "user", "content": "\n\n".join(segment_texts) + "\n\nReturn JSON only."}
        ]

        try:
            response = await llm_service.chat_json(
                messages,
                model=settings.AGENT3_MODEL,
                temperature=0.1,
                max_tokens=2048,
            )
            filler_results = response.get("segments", [])
            logger.info(f"  Batch {batch_start//batch_size + 1}: analyzed {len(filler_results)} segments")
        except Exception as e:
            batches_failed += 1
            logger.warning(f"  Batch {batch_start//batch_size + 1} failed: {e}")
            filler_results = []

        # ── Step 4: Merge results ──
        for seg in batch:
            # Match LLM results to segment
            filler_data = next(
                (f for f in filler_results if f.get("segment_index") == seg.segment_index),
                {}
            )
            if not filler_data:
                filler_data = _fallback_fluency_analysis(seg)
                fallback_segments += 1

            seg.filler_count = int(filler_data.get("filler_count", 0))
            seg.filler_words = filler_data.get("filler_words", [])
            seg.has_repetition = bool(filler_data.get("has_repetition", False))
            seg.fluency_score = min(1.0, max(0.0, float(filler_data.get("fluency_score", 1.0))))

            total_fillers += seg.filler_count

            # Calculate pause duration OVERLAPPING with this segment
            # (handles pauses that start before or end after the segment)
            seg_pause_total = 0.0
            for p in pauses:
                overlap_start = max(p["start"], seg.start_time)
                overlap_end = min(p["end"], seg.end_time)
                overlap = max(0, overlap_end - overlap_start)
                seg_pause_total += overlap

            seg.pause_duration_total = round(seg_pause_total, 2)

    await db.flush()

    logger.info(
        f"Agent 3 complete: {total_fillers} fillers, "
        f"{total_pause_duration:.1f}s total silence, "
        f"{len(pauses)} pause regions"
    )

    return {
        "status": "success",
        "total_fillers": total_fillers,
        "total_pause_duration": round(total_pause_duration, 2),
        "pauses_detected": len(pauses),
        "segments_updated": len(segments),
        "batches_attempted": batches_attempted,
        "batches_failed": batches_failed,
        "fallback_segments": fallback_segments,
        "chat_provider": llm_service.provider_id_for_kind(ProviderKind.CHAT),
        "model": settings.AGENT3_MODEL,
    }


def _fallback_fluency_analysis(seg: Segment) -> dict:
    tokens = _normalized_tokens(seg.text or "")
    filler_words: list[str] = []
    claimed_indexes: set[int] = set()

    for start_index, _token in enumerate(tokens):
        if start_index in claimed_indexes:
            continue
        # Prefer the longest phrase at a token position so "okay so" and
        # "you know what I mean" are not fragmented into single-word fillers.
        for phrase in sorted(FALLBACK_FILLER_PHRASES, key=len, reverse=True):
            end_index = start_index + len(phrase)
            if end_index > len(tokens):
                continue
            if tuple(tokens[start_index:end_index]) == phrase:
                filler_words.append(" ".join(phrase))
                claimed_indexes.update(range(start_index, end_index))
                break

    has_repetition = _has_repeated_phrase(tokens)
    penalty = min(0.65, (len(filler_words) * 0.08) + (0.15 if has_repetition else 0.0))
    return {
        "segment_index": seg.segment_index,
        "filler_count": len(filler_words),
        "filler_words": filler_words,
        "has_repetition": has_repetition,
        "repetition_details": "Repeated phrase detected by deterministic fallback" if has_repetition else None,
        "fluency_score": round(max(0.1, 1.0 - penalty), 2),
    }


def _normalized_tokens(text: str) -> list[str]:
    return [
        token
        for token in (re.sub(r"[^a-z0-9']+", "", raw.lower()) for raw in text.split())
        if token
    ]


def _has_repeated_phrase(tokens: list[str]) -> bool:
    if len(tokens) < 4:
        return False
    for size in range(1, min(5, len(tokens) // 2) + 1):
        for index in range(0, len(tokens) - (size * 2) + 1):
            if tokens[index:index + size] == tokens[index + size:index + (size * 2)]:
                return True
    return False
