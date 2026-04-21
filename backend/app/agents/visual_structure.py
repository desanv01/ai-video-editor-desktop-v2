"""
Agent 4 — Visual Structure Agent (Computer Vision)

Phase D: Full analysis agent.

Goal: Detect slide changes, scene boundaries, and visual structure
of the lecture video using PySceneDetect.

Outputs:
  - Scene records with timestamps, thumbnails, scene type
  - Segment records updated with slide_change flags and slide indices

Scene detection strategy for lectures:
  1. Try AdaptiveDetector (best for gradual slide transitions)
  2. Fall back to ContentDetector (better for hard cuts)
  3. For very static videos, lower the threshold progressively
"""

import os
import uuid
import asyncio
import logging
from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Video, Scene, Segment
from services.ffmpeg import ffmpeg_service
from config import settings

logger = logging.getLogger(__name__)


async def run_visual_structure_agent(video_id: str, db: AsyncSession) -> dict:
    """
    Detect scene/slide changes in the video.

    Steps:
        1. Run PySceneDetect on the video file
        2. Extract a thumbnail for each scene boundary
        3. Store Scene records with metadata
        4. Cross-reference with Segments to mark slide changes

    Returns:
        {"status": "success", "scenes_detected": N, "scene_timestamps": [...]}
    """
    video = await db.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")

    if not os.path.exists(video.file_path):
        raise FileNotFoundError(f"Video file not found: {video.file_path}")

    logger.info(f"Agent 4: Starting scene detection for video {video_id}")

    # ── Step 1: Detect scenes ──
    # PySceneDetect is CPU-bound + synchronous — run in thread pool
    scene_list = await asyncio.to_thread(_detect_scenes, video.file_path)

    if not scene_list:
        logger.info(f"Agent 4: No scene changes detected (single-scene video)")
        return {"status": "success", "scenes_detected": 0, "scene_timestamps": []}

    logger.info(f"Agent 4: Detected {len(scene_list)} scene boundaries")

    # ── Step 2: Create Scene records + extract thumbnails ──
    # Store thumbnails in persistent storage (not temp)
    thumb_dir = os.path.join(settings.VIDEO_STORAGE_PATH, f"thumbnails_{video.id}")
    os.makedirs(thumb_dir, exist_ok=True)

    scenes_created = []
    for i, (scene_start, scene_end) in enumerate(scene_list):
        start_sec = scene_start.get_seconds()
        end_sec = scene_end.get_seconds()
        duration = end_sec - start_sec

        # Extract thumbnail at scene start (+0.5s to avoid transition artifacts)
        thumb_filename = f"scene_{i:04d}.jpg"
        thumb_path = os.path.join(thumb_dir, thumb_filename)

        try:
            await ffmpeg_service.extract_frame(
                video_path=video.file_path,
                timestamp=start_sec + 0.5,
                output_path=thumb_path,
            )
        except Exception as e:
            logger.warning(f"  Thumbnail extraction failed for scene {i}: {e}")
            thumb_path = None

        scene = Scene(
            id=uuid.uuid4(),
            video_id=video.id,
            timestamp=start_sec,
            scene_index=i,
            scene_type=_classify_scene_type(i, len(scene_list), duration),
            thumbnail_path=thumb_path,
            confidence=0.8,  # PySceneDetect doesn't provide confidence scores
        )
        db.add(scene)
        scenes_created.append(scene)

    logger.info(f"Agent 4: Created {len(scenes_created)} scene records with thumbnails")

    # ── Step 3: Cross-reference with segments ──
    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    segments = list(result.scalars().all())

    if segments:
        scene_times = [s.timestamp for s in scenes_created]
        segments_with_changes = 0

        for seg in segments:
            # Find scene changes within this segment's time range
            changes_in_segment = [
                t for t in scene_times
                if seg.start_time <= t <= seg.end_time
            ]

            if changes_in_segment:
                seg.has_slide_change = True
                segments_with_changes += 1

                # Find the closest scene for indexing
                closest_time = min(changes_in_segment, key=lambda t: t)
                closest_scene = next(
                    (s for s in scenes_created if s.timestamp == closest_time),
                    None,
                )
                if closest_scene:
                    seg.slide_index = closest_scene.scene_index
                    seg.scene_id = str(closest_scene.id)

        logger.info(f"Agent 4: Marked {segments_with_changes}/{len(segments)} segments with slide changes")

    await db.flush()

    return {
        "status": "success",
        "scenes_detected": len(scenes_created),
        "scene_timestamps": [round(s.timestamp, 2) for s in scenes_created],
    }


def _detect_scenes(video_path: str) -> List[Tuple]:
    """
    Run PySceneDetect (synchronous, CPU-bound).

    Strategy for lecture videos:
      1. AdaptiveDetector with moderate threshold (best for slides)
      2. If too few scenes: ContentDetector with lower threshold
      3. If still too few: ContentDetector with very low threshold

    Returns list of (start_timecode, end_timecode) tuples.
    """
    from scenedetect import detect, AdaptiveDetector, ContentDetector

    try:
        # Attempt 1: AdaptiveDetector (handles gradual transitions well)
        scene_list = detect(
            video_path,
            AdaptiveDetector(
                adaptive_threshold=3.0,
                min_scene_len=30,  # ~1 second at 30fps
            ),
        )
        logger.info(f"  AdaptiveDetector: {len(scene_list)} scenes")

        if len(scene_list) >= 2:
            return scene_list

        # Attempt 2: ContentDetector with standard threshold
        scene_list = detect(
            video_path,
            ContentDetector(
                threshold=25.0,
                min_scene_len=30,
            ),
        )
        logger.info(f"  ContentDetector (threshold=25): {len(scene_list)} scenes")

        if len(scene_list) >= 2:
            return scene_list

        # Attempt 3: ContentDetector with low threshold (very sensitive)
        scene_list = detect(
            video_path,
            ContentDetector(
                threshold=15.0,
                min_scene_len=15,  # ~0.5 second minimum
            ),
        )
        logger.info(f"  ContentDetector (threshold=15): {len(scene_list)} scenes")

        return scene_list

    except Exception as e:
        logger.error(f"  Scene detection failed: {e}")
        return []


def _classify_scene_type(
    scene_index: int,
    total_scenes: int,
    duration: float,
) -> str:
    """
    Basic heuristic scene classification.

    Without CLIP, we use simple rules:
      - First/last scene = likely intro/outro
      - Very short scenes (<5s) = transition
      - Everything else = slide (most common in lectures)

    CLIP-based classification would go here as an enhancement.
    """
    if scene_index == 0:
        return "intro"
    elif scene_index == total_scenes - 1:
        return "outro"
    elif duration < 5.0:
        return "transition"
    else:
        return "slide"
