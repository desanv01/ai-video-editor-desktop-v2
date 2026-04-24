"""
Transcription Service — Voxtral (primary) + Whisper (fallback).

Phase B: Core transcription pipeline.

Voxtral via Mistral API (official SDK):
  - Model: voxtral-mini-latest
  - Endpoint: /v1/audio/transcriptions
  - Features: diarization, context biasing, word/segment timestamps
  - Limit: ~30 minutes per request (32K token context)
  - Pricing: $0.003/minute
  - IMPORTANT: timestamp_granularities is NOT compatible with language param

Whisper via OpenAI API:
  - Model: whisper-1
  - Limit: 25MB per file
  - No diarization

Audio longer than 25 minutes is automatically split into overlapping chunks,
transcribed separately, and merged with corrected timestamps.
"""

import os
import asyncio
import json
import logging
from typing import List, Optional
from openai import AsyncOpenAI
from config import settings

logger = logging.getLogger(__name__)

# Maximum audio duration per Voxtral API call (~25 min to stay safely under 32K tokens)
VOXTRAL_MAX_DURATION_SEC = 20 * 60
# Maximum file size for Whisper API
WHISPER_MAX_FILE_SIZE = 23 * 1024 * 1024
# Chunk duration for splitting long audio
CHUNK_DURATION_SEC = 10 * 60  # 20 minutes with 30s overlap
CHUNK_OVERLAP_SEC = 20
MIXED_LANGUAGE_TRANSCRIPTION_PROMPT = (
    "This lecture may contain mixed English and Bahasa Melayu/Malay. "
    "Transcribe exactly what is spoken, preserving the original language for each phrase. "
    "Do not translate, summarize, or normalize the speech into a single language."
)


class TranscriptionService:
    """Unified ASR service: Voxtral primary, Whisper fallback."""

    def __init__(self):
        # Mistral client (OpenAI-compatible endpoint)
        self._mistral = AsyncOpenAI(
            api_key=settings.MISTRAL_API_KEY,
            base_url=settings.MISTRAL_BASE_URL,
        )
        # OpenAI client (Whisper fallback + embeddings)
        self._openai = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
        )

    # ═══════════════════════════════════════════
    #  PUBLIC API
    # ═══════════════════════════════════════════

    async def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        domain_terms: Optional[List[str]] = None,
    ) -> dict:
        """
        Transcribe an audio file.

        Automatically:
          - Picks provider based on config (ASR_PROVIDER)
          - Splits long audio into chunks if needed
          - Falls back to Whisper if Voxtral fails

        Returns unified format:
        {
            "text": "Full transcript...",
            "language": "en",
            "duration": 1234.5,
            "words": [{"word": "Hello", "start": 0.0, "end": 0.5, "speaker": "S1"}, ...],
            "segments": [{"text": "...", "start": 0.0, "end": 30.0, "speaker": "S1"}, ...],
            "speakers": [{"label": "Speaker 1", "segments_count": 15}, ...],
            "provider": "voxtral" | "whisper" | "whisper_fallback",
        }
        """
        provider = settings.ASR_PROVIDER.lower()
        terms = domain_terms or settings.domain_terms_list

        # Get audio duration to decide if chunking is needed
        duration = await self._get_audio_duration(audio_path)

        if provider == "voxtral":
            try:
                result = await self._transcribe_voxtral_pipeline(
                    audio_path, duration, language, terms
                )
                result["provider"] = "voxtral"
                logger.info(
                    f"Voxtral transcription complete: {result.get('duration', 0):.0f}s, "
                    f"{len(result.get('segments', []))} segments, "
                    f"{len(result.get('speakers', []))} speakers"
                )
                return result
            except Exception as e:
                logger.warning(f"Voxtral failed, falling back to Whisper: {e}")
                result = await self._transcribe_whisper_pipeline(
                    audio_path, duration, language
                )
                result["provider"] = "whisper_fallback"
                return result
        else:
            result = await self._transcribe_whisper_pipeline(
                audio_path, duration, language
            )
            result["provider"] = "whisper"
            return result

    # ═══════════════════════════════════════════
    #  VOXTRAL (Mistral API)
    # ═══════════════════════════════════════════

    async def _transcribe_voxtral_pipeline(
        self,
        audio_path: str,
        duration: float,
        language: Optional[str],
        domain_terms: Optional[List[str]],
    ) -> dict:
        """Route to single-call or chunked transcription based on duration."""
        if duration <= VOXTRAL_MAX_DURATION_SEC:
            return await self._voxtral_single(audio_path, language, domain_terms)
        else:
            logger.info(f"Audio is {duration:.0f}s — splitting into chunks for Voxtral")
            return await self._transcribe_chunked(
                audio_path, duration,
                chunk_fn=lambda path, lang=language, terms=domain_terms: (
                    self._voxtral_single(path, lang, terms)
                ),
            )

    async def _voxtral_single(
        self,
        audio_path: str,
        language: Optional[str],
        domain_terms: Optional[List[str]],
    ) -> dict:
        """
        Single Voxtral API call for audio <= 25 min.

        Uses the OpenAI-compatible /v1/audio/transcriptions endpoint.
        NOTE: timestamp_granularities and language are mutually exclusive
              in the current Mistral API — we prioritize timestamps.
        """
        kwargs = {
            "model": "voxtral-mini-latest",
            "file": open(audio_path, "rb"),
            "response_format": "verbose_json",
            "timestamp_granularities": ["word", "segment"],
        }

        # Context biasing for domain-specific terms (Voxtral feature)
        # Passed as part of the prompt field
        prompt_parts = [MIXED_LANGUAGE_TRANSCRIPTION_PROMPT]
        if domain_terms:
            bias_text = ", ".join(domain_terms[:100])
            prompt_parts.append(f"Domain terms: {bias_text}")
        kwargs["prompt"] = "\n".join(prompt_parts)

        # NOTE: Cannot use language + timestamp_granularities together.
        # If user explicitly wants language forced (no timestamps), uncomment:
        # if language:
        #     del kwargs["timestamp_granularities"]
        #     kwargs["language"] = language

        try:
            response = await self._mistral.audio.transcriptions.create(**kwargs)
            return self._parse_voxtral_response(response)
        finally:
            # Close file handle
            kwargs["file"].close()

    def _parse_voxtral_response(self, response) -> dict:
        """Parse Voxtral/Mistral transcription response into unified format."""
        text = getattr(response, "text", "") or ""

        # Parse words
        words = []
        raw_words = getattr(response, "words", None) or []
        for w in raw_words:
            words.append({
                "word": getattr(w, "word", getattr(w, "text", "")),
                "start": getattr(w, "start", 0),
                "end": getattr(w, "end", 0),
                "speaker": getattr(w, "speaker", None),
            })

        # Parse segments with speaker labels (diarization)
        segments = []
        speaker_counts = {}
        raw_segments = getattr(response, "segments", None) or []
        for seg in raw_segments:
            speaker = getattr(seg, "speaker", None)
            seg_text = getattr(seg, "text", "")
            if isinstance(seg_text, str):
                seg_text = seg_text.strip()

            segments.append({
                "text": seg_text,
                "start": getattr(seg, "start", 0),
                "end": getattr(seg, "end", 0),
                "speaker": speaker,
            })
            if speaker:
                speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1

        # Build speaker summary
        speakers = [
            {"label": label, "segments_count": count}
            for label, count in sorted(speaker_counts.items())
        ]

        return {
            "text": text,
            "language": getattr(response, "language", "en") or "en",
            "duration": getattr(response, "duration", 0) or 0,
            "words": words,
            "segments": segments,
            "speakers": speakers,
        }

    # ═══════════════════════════════════════════
    #  WHISPER (OpenAI API) — Fallback
    # ═══════════════════════════════════════════

    async def _transcribe_whisper_pipeline(
        self,
        audio_path: str,
        duration: float,
        language: Optional[str],
    ) -> dict:
        """Route to single or chunked Whisper transcription."""
        file_size = os.path.getsize(audio_path)

        if file_size <= WHISPER_MAX_FILE_SIZE and duration <= VOXTRAL_MAX_DURATION_SEC:
            return await self._whisper_single(audio_path, language)
        else:
            logger.info(f"Audio is {duration:.0f}s / {file_size/1024/1024:.1f}MB — chunking for Whisper")
            return await self._transcribe_chunked(
                audio_path, duration,
                chunk_fn=lambda path, lang=language: self._whisper_single(path, lang),
            )

    async def _whisper_single(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> dict:
        """Single Whisper API call (file <= 25MB)."""
        kwargs = {
            "model": settings.WHISPER_MODEL,
            "file": open(audio_path, "rb"),
            "response_format": "verbose_json",
            "timestamp_granularities": ["word", "segment"],
            "prompt": MIXED_LANGUAGE_TRANSCRIPTION_PROMPT,
        }
        if language:
            kwargs["language"] = language

        try:
            response = await self._openai.audio.transcriptions.create(**kwargs)
        finally:
            kwargs["file"].close()

        words = []
        if hasattr(response, "words") and response.words:
            words = [
                {"word": w.word, "start": w.start, "end": w.end, "speaker": None}
                for w in response.words
            ]

        segments = []
        if hasattr(response, "segments") and response.segments:
            segments = [
                {
                    "text": s.text.strip(),
                    "start": s.start,
                    "end": s.end,
                    "speaker": None,
                }
                for s in response.segments
            ]

        return {
            "text": response.text,
            "language": getattr(response, "language", "en"),
            "duration": getattr(response, "duration", 0),
            "words": words,
            "segments": segments or self._segments_from_text(response.text, getattr(response, "duration", 0)),
            "speakers": [],
        }

    # ═══════════════════════════════════════════
    #  AUDIO CHUNKING (shared by both providers)
    # ═══════════════════════════════════════════

    async def _transcribe_chunked(
        self,
        audio_path: str,
        total_duration: float,
        chunk_fn,
    ) -> dict:
        """
        Split audio into overlapping chunks, transcribe each, and merge.

        Uses 20-min chunks with 30s overlap. The overlap ensures no words
        are lost at chunk boundaries. Duplicate segments in the overlap
        region are de-duplicated during merge.
        """
        chunk_dir = os.path.join(settings.TEMP_PATH, f"chunks_{os.getpid()}")
        os.makedirs(chunk_dir, exist_ok=True)

        try:
            # Split audio into chunks
            chunks = await self._split_audio(
                audio_path, chunk_dir, total_duration,
                chunk_duration=CHUNK_DURATION_SEC,
                overlap=CHUNK_OVERLAP_SEC,
            )

            # Transcribe each chunk
            all_words = []
            all_segments = []
            all_text = []
            all_speakers = {}

            for chunk in chunks:
                logger.info(f"Transcribing chunk {chunk['index']+1}/{len(chunks)} "
                            f"(offset={chunk['offset']:.0f}s)")

                result = await chunk_fn(chunk["path"])
                offset = chunk["offset"]

                all_text.append(result.get("text", ""))

                # Offset timestamps and collect
                for w in result.get("words", []):
                    w["start"] += offset
                    w["end"] += offset
                    all_words.append(w)

                for s in result.get("segments", []):
                    s["start"] += offset
                    s["end"] += offset
                    all_segments.append(s)

                for sp in result.get("speakers", []):
                    label = sp["label"]
                    all_speakers[label] = all_speakers.get(label, 0) + sp["segments_count"]

            # De-duplicate overlapping segments
            all_segments = self._deduplicate_segments(all_segments)
            all_words = self._deduplicate_words(all_words)

            speakers = [
                {"label": label, "segments_count": count}
                for label, count in sorted(all_speakers.items())
            ]

            return {
                "text": " ".join(all_text),
                "language": "mixed",  # Chunked mode does not reliably detect one language.
                "duration": total_duration,
                "words": all_words,
                "segments": all_segments,
                "speakers": speakers,
            }

        finally:
            # Cleanup chunk files
            for chunk in chunks if 'chunks' in dir() else []:
                try:
                    os.remove(chunk["path"])
                except OSError:
                    pass
            try:
                os.rmdir(chunk_dir)
            except OSError:
                pass

    async def _split_audio(
        self,
        audio_path: str,
        output_dir: str,
        total_duration: float,
        chunk_duration: float = CHUNK_DURATION_SEC,
        overlap: float = CHUNK_OVERLAP_SEC,
    ) -> List[dict]:
        """Split audio into overlapping WAV chunks using ffmpeg."""
        chunks = []
        offset = 0.0
        idx = 0
        step = chunk_duration - overlap

        while offset < total_duration:
            chunk_path = os.path.join(output_dir, f"chunk_{idx:04d}.mp3")
            actual_duration = min(chunk_duration, total_duration - offset)

            cmd = [
    "ffmpeg", "-i", audio_path,
    "-ss", str(offset),
    "-t", str(actual_duration),
    "-acodec", "libmp3lame",
    "-ar", "16000",
    "-ac", "1",
    "-b:a", "64k",
    "-y", chunk_path,
]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"ffmpeg chunk split failed: {stderr.decode()[:200]}")
                raise RuntimeError(f"Failed to split audio at offset {offset}")

            chunks.append({
                "path": chunk_path,
                "offset": offset,
                "duration": actual_duration,
                "index": idx,
            })

            offset += step
            idx += 1

        logger.info(f"Split audio into {len(chunks)} chunks "
                     f"({chunk_duration}s each, {overlap}s overlap)")
        return chunks

    @staticmethod
    def _deduplicate_segments(segments: List[dict]) -> List[dict]:
        """
        Remove duplicate segments from the overlap regions.
        Two segments are considered duplicates if they overlap in time
        by more than 50% and have similar text.
        """
        if not segments:
            return segments

        # Sort by start time
        segments.sort(key=lambda s: s["start"])

        deduped = [segments[0]]
        for seg in segments[1:]:
            prev = deduped[-1]
            # Check for significant time overlap
            overlap_start = max(prev["start"], seg["start"])
            overlap_end = min(prev["end"], seg["end"])
            overlap_duration = max(0, overlap_end - overlap_start)

            seg_duration = seg["end"] - seg["start"]
            if seg_duration > 0 and overlap_duration / seg_duration > 0.5:
                # Skip duplicate — keep the earlier one
                continue
            deduped.append(seg)

        return deduped

    @staticmethod
    def _deduplicate_words(words: List[dict]) -> List[dict]:
        """Remove duplicate words from overlap regions."""
        if not words:
            return words

        words.sort(key=lambda w: w["start"])

        deduped = [words[0]]
        for w in words[1:]:
            prev = deduped[-1]
            # Skip if same word at nearly the same time (within 0.1s)
            if (w["word"] == prev["word"]
                    and abs(w["start"] - prev["start"]) < 0.1):
                continue
            deduped.append(w)

        return deduped

    @staticmethod
    def _segments_from_text(text: str, duration: float) -> List[dict]:
        """Fallback for ASR responses that include text but omit segment timestamps."""
        clean_text = (text or "").strip()
        if not clean_text:
            return []
        return [{
            "text": clean_text,
            "start": 0.0,
            "end": float(duration or 0.0),
            "speaker": None,
        }]

    # ═══════════════════════════════════════════
    #  UTILITIES
    # ═══════════════════════════════════════════

    @staticmethod
    async def _get_audio_duration(audio_path: str) -> float:
        """Get audio duration in seconds using ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            audio_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()

        try:
            return float(stdout.decode().strip())
        except (ValueError, AttributeError):
            logger.warning(f"Could not determine duration for {audio_path}, defaulting to 0")
            return 0.0


# Singleton
transcription_service = TranscriptionService()
