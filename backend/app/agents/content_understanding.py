"""
Agent 2 — Content Understanding Agent (LLM + RAG)

Phase D: Full analysis agent.

Goal: Understand WHAT is being taught in each segment of the lecture.

For each transcript chunk (~60s):
  1. Retrieves relevant course materials from Qdrant via semantic search
  2. Labels the main topic
  3. Generates a brief summary
  4. Assigns importance score (0.0 - 1.0)
  5. Classifies type (core_content / example / filler / qa / transition / ...)
  6. Preserves speaker labels from diarization

Also generates auto chapter markers from topic transitions.
"""

import uuid
import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Video, Transcript, Segment, SegmentType, VideoStatus
from services.llm import llm_service
from rag.vector_store import rag_service
from config import settings

logger = logging.getLogger(__name__)

CONTENT_ANALYSIS_PROMPT = """You are an educational content analyst. Analyze transcript segments from a lecture video and determine their educational value.

For each segment, provide:
1. topic_label: The main topic discussed (short, 2-6 words)
2. summary: Brief summary of the content (1-2 sentences)
3. importance_score: Float from 0.0 to 1.0
   - 0.9-1.0 = Essential core concept that MUST be kept
   - 0.7-0.8 = Important explanation, worked example, or key insight
   - 0.5-0.6 = Supplementary info, context setting, or review
   - 0.3-0.4 = Tangential digression, administrative remark
   - 0.0-0.2 = Pure filler, silence, or completely irrelevant
4. segment_type: One of: core_content, example, filler, qa, transition, intro_outro, repetition, pause

Consider the course materials provided. Content that aligns with curriculum topics should score higher. Student Q&A segments that clarify important concepts should also score well.

If a segment contains a speaker transition (e.g. student asking a question), note this in the summary.

IMPORTANT: Return ONLY valid JSON. No markdown, no extra text.

{
  "segments": [
    {
      "segment_index": 0,
      "topic_label": "Bubble Sort Algorithm",
      "summary": "Instructor explains how bubble sort works by comparing adjacent elements and swapping them.",
      "importance_score": 0.85,
      "segment_type": "core_content"
    }
  ]
}"""


async def run_content_understanding_agent(video_id: str, db: AsyncSession) -> dict:
    """
    Analyze transcript segments for educational content and importance.

    Creates Segment records in the database — these are used by
    Agents 3 and 4 to attach their own analysis, and by Agent 5
    to build the final edit plan.

    Returns:
        {"status": "success", "segments_analyzed": N, "chapters": [...]}
    """
    video = await db.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")

    video.status = VideoStatus.ANALYZING
    await db.flush()

    result = await db.execute(
        select(Transcript).where(Transcript.video_id == video_id)
    )
    transcript = result.scalar_one_or_none()
    if not transcript or not transcript.segments_json:
        raise ValueError(f"No transcript found for video {video_id}")

    # ── Step 1: Chunk transcript into ~60s segments ──
    raw_segments = transcript.segments_json
    chunks = rag_service.chunk_transcript_segments(raw_segments, target_duration=60.0)

    if not chunks:
        return {"status": "success", "segments_analyzed": 0, "chapters": []}

    logger.info(f"Agent 2: Analyzing {len(chunks)} chunks for video {video_id}")

    # ── Step 2: Analyze each batch with RAG context ──
    all_analyzed = []
    batch_size = 5

    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start:batch_start + batch_size]

        # RAG: retrieve relevant course materials for this batch
        batch_query = " ".join([c["text"][:150] for c in batch])
        rag_results = await rag_service.search(
            query=batch_query[:500],
            top_k=4,
            source_type="course_material",
            score_threshold=0.3,
        )

        if rag_results:
            context_parts = []
            for r in rag_results:
                source_info = ""
                if r.get("metadata", {}).get("filename"):
                    source_info = f" (from {r['metadata']['filename']}"
                    if r["metadata"].get("page_num"):
                        source_info += f", page {r['metadata']['page_num']}"
                    source_info += ")"
                context_parts.append(f"{r['text']}{source_info}")
            context = "\n\n".join(context_parts)
        else:
            context = "No course materials available for context."

        # Build segment descriptions
        segment_descriptions = []
        for i, chunk in enumerate(batch):
            idx = batch_start + i
            meta = chunk.get("metadata", {})
            speakers = meta.get("speakers", "")
            speaker_info = f" [Speakers: {speakers}]" if speakers else ""
            segment_descriptions.append(
                f"Segment {idx} [{meta.get('start_time', 0):.1f}s - {meta.get('end_time', 0):.1f}s]{speaker_info}:\n{chunk['text']}"
            )

        segments_text = "\n\n".join(segment_descriptions)

        # Call LLM with per-agent model
        messages = [
            {"role": "system", "content": CONTENT_ANALYSIS_PROMPT},
            {"role": "user", "content": f"## Relevant Course Materials\n{context}\n\n## Transcript Segments to Analyze\n{segments_text}\n\nAnalyze each segment. Return JSON only."}
        ]

        try:
            response = await llm_service.chat_json(
                messages,
                model=settings.AGENT2_MODEL,
                temperature=0.1,
                max_tokens=4096,
            )
            analyzed = response.get("segments", [])
            all_analyzed.extend(analyzed)
            logger.info(f"  Batch {batch_start//batch_size + 1}: analyzed {len(analyzed)} segments")
        except Exception as e:
            logger.warning(f"  Batch {batch_start//batch_size + 1} failed: {e}")
            for i in range(len(batch)):
                all_analyzed.append({
                    "segment_index": batch_start + i,
                    "topic_label": "Unknown",
                    "summary": f"Analysis failed: {str(e)[:50]}",
                    "importance_score": 0.5,
                    "segment_type": "core_content",
                })

    # ── Step 3: Create Segment records in DB ──
    type_map = {
        "core_content": SegmentType.CORE_CONTENT,
        "example": SegmentType.EXAMPLE,
        "filler": SegmentType.FILLER,
        "pause": SegmentType.PAUSE,
        "repetition": SegmentType.REPETITION,
        "intro_outro": SegmentType.INTRO_OUTRO,
        "qa": SegmentType.QA,
        "transition": SegmentType.TRANSITION,
    }

    created_segments = []
    for i, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        analysis = next(
            (a for a in all_analyzed if a.get("segment_index") == i),
            {}
        )

        # Extract speaker from chunk metadata
        speaker_label = meta.get("speakers")

        segment = Segment(
            id=uuid.uuid4(),
            video_id=video.id,
            segment_index=i,
            start_time=meta.get("start_time", 0),
            end_time=meta.get("end_time", 0),
            duration=meta.get("duration", 0),
            text=chunk["text"],
            speaker=speaker_label,
            topic_label=analysis.get("topic_label", "Unknown"),
            summary=analysis.get("summary", ""),
            importance_score=min(1.0, max(0.0, float(analysis.get("importance_score", 0.5)))),
            segment_type=type_map.get(
                analysis.get("segment_type", "core_content"),
                SegmentType.CORE_CONTENT,
            ),
        )
        db.add(segment)
        created_segments.append(segment)

    await db.flush()

    # ── Step 4: Generate auto chapter markers ──
    chapters = _generate_chapters(created_segments)

    logger.info(
        f"Agent 2 complete: {len(created_segments)} segments, "
        f"{len(chapters)} chapters"
    )

    return {
        "status": "success",
        "segments_analyzed": len(created_segments),
        "chapters": chapters,
    }


def _generate_chapters(segments: List[Segment]) -> List[dict]:
    """
    Generate YouTube-style chapter markers from topic transitions.

    A new chapter starts when the topic_label changes significantly
    from the previous segment (and the segment has reasonable importance).
    """
    if not segments:
        return []

    chapters = []
    current_topic = None

    for seg in segments:
        topic = seg.topic_label or "Unknown"

        # New chapter if topic changed and importance is reasonable
        if topic != current_topic and (seg.importance_score or 0) >= 0.3:
            minutes = int(seg.start_time // 60)
            seconds = int(seg.start_time % 60)
            chapters.append({
                "timestamp": seg.start_time,
                "label": f"{minutes:02d}:{seconds:02d} — {topic}",
                "topic": topic,
                "segment_index": seg.segment_index,
            })
            current_topic = topic

    return chapters
