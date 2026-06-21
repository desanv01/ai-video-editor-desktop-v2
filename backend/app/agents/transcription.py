"""
Agent 1 — Transcription & Alignment Agent
Goal: Turn raw lecture video into an accurate, time-aligned transcript with speaker labels.

Pipeline: video → extract audio (ffmpeg) → transcribe (Voxtral/Whisper) → store
Voxtral provides diarization (speaker labels) for free.
"""

import os
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Video, Transcript, VideoStatus
from services.ffmpeg import ffmpeg_service
from services.transcription import transcription_service
from config import settings


async def run_transcription_agent(video_id: str, db: AsyncSession) -> dict:
    """
    Execute the transcription pipeline for a video.

    Steps:
        1. Extract audio from video using ffmpeg (16kHz mono WAV)
        2. Transcribe audio using Voxtral (primary) or Whisper (fallback)
        3. Store transcript with word-level timestamps + speaker diarization

    Returns:
        {
            "status": "success",
            "transcript_id": "...",
            "word_count": N,
            "duration": N,
            "speakers": [...],
            "provider": "voxtral" | "whisper",
        }
    """
    video = await db.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")

    video.status = VideoStatus.TRANSCRIBING
    await db.flush()

    try:
        # ── Step 1: Extract audio ──
        audio_filename = f"{video.id}_audio.wav"
        audio_path = os.path.join(settings.TEMP_PATH, audio_filename)
        os.makedirs(settings.TEMP_PATH, exist_ok=True)

        await ffmpeg_service.extract_audio(
            video_path=video.file_path,
            output_path=audio_path,
            format="wav"
        )
        video.audio_path = audio_path

        # ── Step 2: Transcribe with Voxtral (primary) or Whisper (fallback) ──
        result = await transcription_service.transcribe(
            audio_path=audio_path,
            language=settings.ASR_LANGUAGE or None,
            domain_terms=settings.domain_terms_list if settings.domain_terms_list else None,
        )

        # ── Step 3: Store transcript ──
        transcript = Transcript(
            id=uuid.uuid4(),
            video_id=video.id,
            full_text=result["text"],
            language=result.get("language", "en"),
            word_count=len(result["text"].split()),
            words_json=result.get("words", []),
            segments_json=result.get("segments", []),
            speakers_json=result.get("speakers", []),
            asr_provider=result.get("provider", "unknown"),
        )
        db.add(transcript)

        video.duration_seconds = result.get("duration", video.duration_seconds)
        await db.flush()

        return {
            "status": "success",
            "transcript_id": str(transcript.id),
            "word_count": transcript.word_count,
            "duration": result.get("duration", 0),
            "language": result.get("language", "en"),
            "segment_count": len(result.get("segments", [])),
            "speakers": result.get("speakers", []),
            "provider": result.get("provider", "unknown"),
            "transcription_route": result.get("transcription_route"),
        }

    except Exception as e:
        video.status = VideoStatus.FAILED
        video.error_message = f"Transcription failed: {str(e)}"
        await db.flush()
        raise
