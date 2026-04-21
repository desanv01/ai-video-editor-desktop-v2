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
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Video, Transcript, Segment
from services.ffmpeg import ffmpeg_service
from services.llm import llm_service
from config import settings

logger = logging.getLogger(__name__)

FILLER_DETECTION_PROMPT = """You are a speech fluency analyzer for educational video editing. Analyze the transcript and identify delivery issues.

For each segment, detect:

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
        return {"status": "success", "total_fillers": 0, "total_pause_duration": 0, "segments_updated": 0}

    logger.info(f"Agent 3: Analyzing {len(segments)} segments for fluency")

    # ── Step 3: Linguistic filler detection via LLM ──
    total_fillers = 0
    total_pause_duration = sum(p.get("duration", 0) for p in pauses)

    batch_size = 8  # Slightly smaller batches = more reliable JSON from LLM
    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start:batch_start + batch_size]

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
            logger.warning(f"  Batch {batch_start//batch_size + 1} failed: {e}")
            filler_results = []

        # ── Step 4: Merge results ──
        for seg in batch:
            # Match LLM results to segment
            filler_data = next(
                (f for f in filler_results if f.get("segment_index") == seg.segment_index),
                {}
            )

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
    }
