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
import re
from typing import List, Optional
from openai import AsyncOpenAI
from config import settings
from services.tooling import ffmpeg_binary, ffprobe_binary
from providers.defaults import get_provider_registry
from providers.interfaces import (
    ProviderCapability,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderKind,
    ProviderMetadata,
    TranscriptionProvider,
    TranscriptionRequest,
    TranscriptionResponse,
)
from providers.processing_modes import ProcessingMode
from providers.whisper_cpp import (
    WhisperCppTranscriptionProvider,
    resolve_whisper_cpp_model_selection,
)

logger = logging.getLogger(__name__)

# Maximum audio duration per Voxtral API call (~25 min to stay safely under 32K tokens)
VOXTRAL_MAX_DURATION_SEC = 20 * 60
# Maximum file size for Whisper API
WHISPER_MAX_FILE_SIZE = 23 * 1024 * 1024
# Chunk duration for splitting long audio
CHUNK_DURATION_SEC = 10 * 60  # 20 minutes with 30s overlap
CHUNK_OVERLAP_SEC = 20
DEFAULT_ASR_CONTEXT_NOTE = (
    "English software engineering lecture with occasional Malay phrases. "
    "Preserve English technical terms such as object design, design pattern, "
    "bridge pattern, template method, class diagram, inheritance, delegation, "
    "abstraction, and implementation."
)

PROMPT_LEAK_MARKERS = (
    "transcribe exactly",
    "preserving the original language",
    "do not translate",
    "normalize the speech into a single language",
    "this meeting is being transcribed",
)

WORD_CLEAN_RE = re.compile(r"[^a-z0-9]+")


class ExistingAPITranscriptionProvider(TranscriptionProvider):
    """Provider adapter for the existing Voxtral/Whisper transcription pipelines."""

    def __init__(
        self,
        *,
        provider_id: str,
        label: str,
        provider_name: str,
        default_model: str,
        api_key: str,
        service: "TranscriptionService",
    ):
        self._provider_id = provider_id
        self._api_key = api_key
        self._service = service
        self._metadata = ProviderMetadata(
            provider_id=provider_id,
            kind=ProviderKind.TRANSCRIPTION,
            label=label,
            provider_name=provider_name,
            default_model=default_model,
            capabilities=(
                ProviderCapability("audio_transcription", "Speech-to-text transcription."),
                ProviderCapability("timestamps", "Word and segment timestamps when available."),
            ),
        )

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    async def health(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(
                status=ProviderHealthStatus.NOT_CONFIGURED,
                message=f"{self.metadata.label} API key is not configured.",
            )
        return await super().health()

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        duration = request.metadata.get("duration")
        if duration is None:
            duration = await self._service._get_audio_duration(request.audio_path)

        if self._provider_id == "voxtral":
            transcript = await self._service._transcribe_voxtral_pipeline(
                request.audio_path,
                float(duration),
                request.language,
                request.domain_terms,
            )
        elif self._provider_id == "whisper":
            transcript = await self._service._transcribe_whisper_pipeline(
                request.audio_path,
                float(duration),
                request.language,
            )
        else:
            raise RuntimeError(f"Unsupported transcription provider: {self._provider_id}")

        transcript = dict(transcript)
        transcript["provider"] = self.metadata.provider_id
        return TranscriptionResponse(
            transcript=transcript,
            provider_id=self.metadata.provider_id,
            model=self.metadata.default_model,
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
        self._registered_registry = None
        self._registry()

    def _registry(self):
        registry = get_provider_registry()
        if registry is not self._registered_registry:
            self._register_transcription_providers(registry)
            self._registered_registry = registry
        return registry

    def _register_transcription_providers(self, registry) -> None:
        default_provider = settings.ASR_PROVIDER.lower()
        registry.register(
            ExistingAPITranscriptionProvider(
                provider_id="voxtral",
                label="Voxtral Transcription",
                provider_name="mistral",
                default_model=settings.VOXTRAL_MODEL,
                api_key=settings.MISTRAL_API_KEY,
                service=self,
            ),
            set_default=default_provider == "voxtral",
            replace=True,
        )
        registry.register(
            ExistingAPITranscriptionProvider(
                provider_id="whisper",
                label="Whisper Transcription",
                provider_name="openai",
                default_model=settings.WHISPER_MODEL,
                api_key=settings.OPENAI_API_KEY,
                service=self,
            ),
            set_default=default_provider == "whisper",
            replace=True,
        )
        whisper_cpp_selection = resolve_whisper_cpp_model_selection(settings)
        registry.register(
            WhisperCppTranscriptionProvider(
                binary_path=whisper_cpp_selection.binary_path,
                model_path=whisper_cpp_selection.model_path,
                model_id=whisper_cpp_selection.model_id,
                work_dir=settings.TEMP_PATH,
            ),
            set_default=default_provider == "whisper-cpp",
            replace=True,
        )

    def _selected_transcription_provider_id(self) -> str:
        registry = self._registry()
        mode_config = registry.processing_mode_for(ProviderKind.TRANSCRIPTION)
        if mode_config.mode == ProcessingMode.LOCAL:
            return mode_config.local_provider_id or "whisper-cpp"

        return (
            mode_config.api_provider_id
            or registry.default_provider_id(ProviderKind.TRANSCRIPTION)
            or settings.ASR_PROVIDER.lower()
        )

    def _transcription_provider_route(self) -> list[str]:
        mode_config = self._registry().processing_mode_for(ProviderKind.TRANSCRIPTION)
        provider_ids: list[str] = []

        for mode in mode_config.mode_order():
            if mode == ProcessingMode.LOCAL:
                provider_ids.append(mode_config.local_provider_id or "whisper-cpp")
            elif mode == ProcessingMode.API:
                provider_ids.extend(
                    self._api_transcription_provider_ids(mode_config.api_provider_id)
                )

        if (
            mode_config.mode == ProcessingMode.LOCAL
            and mode_config.fallback_enabled
        ):
            provider_ids.extend(
                self._api_transcription_provider_ids(mode_config.api_provider_id)
            )

        return self._dedupe_provider_ids(provider_ids)

    def _api_transcription_provider_ids(
        self,
        preferred_provider_id: Optional[str],
    ) -> list[str]:
        primary = (
            preferred_provider_id
            or self._registry().default_provider_id(ProviderKind.TRANSCRIPTION)
            or settings.ASR_PROVIDER
            or "voxtral"
        ).strip().lower()
        if primary == "whisper-cpp":
            primary = settings.ASR_PROVIDER.lower() if settings.ASR_PROVIDER else "voxtral"
            if primary == "whisper-cpp":
                primary = "voxtral"

        provider_ids = [primary]
        provider_ids.extend(provider_id for provider_id in ("whisper", "voxtral") if provider_id != primary)
        return self._dedupe_provider_ids(provider_ids)

    @staticmethod
    def _dedupe_provider_ids(provider_ids: list[str]) -> list[str]:
        route: list[str] = []
        seen: set[str] = set()
        for provider_id in provider_ids:
            normalized = (provider_id or "").strip().lower()
            if normalized and normalized not in seen:
                route.append(normalized)
                seen.add(normalized)
        return route

    def _get_transcription_provider(self, provider_id: str) -> TranscriptionProvider:
        provider = self._registry().get(ProviderKind.TRANSCRIPTION, provider_id)
        if not isinstance(provider, TranscriptionProvider):
            raise TypeError(
                f"Provider {provider_id} does not implement TranscriptionProvider"
            )
        return provider

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
        mode_config = self._registry().processing_mode_for(ProviderKind.TRANSCRIPTION)
        provider_route = self._transcription_provider_route()
        if not provider_route:
            raise RuntimeError("No transcription providers are configured for the selected mode")

        terms = domain_terms or settings.domain_terms_list

        # Get audio duration to decide if chunking is needed
        duration = await self._get_audio_duration(audio_path)
        request = TranscriptionRequest(
            audio_path=audio_path,
            language=language,
            domain_terms=terms,
            metadata={
                "duration": duration,
                "threads": getattr(settings, "WHISPER_CPP_THREADS", 0),
            },
        )

        attempted_providers: list[str] = []
        failures: list[tuple[str, Exception]] = []

        for provider_id in provider_route:
            attempted_providers.append(provider_id)
            try:
                response = await self._get_transcription_provider(provider_id).transcribe(
                    request
                )
                result = dict(response.transcript)
                fallback_from = failures[-1][0] if failures else None
                result["provider"] = self._provider_result_label(
                    response.provider_id,
                    fallback_from,
                )
                result["transcription_mode"] = mode_config.mode.value
                result["transcription_route"] = {
                    "mode": mode_config.mode.value,
                    "fallback_enabled": mode_config.fallback_enabled,
                    "attempted_providers": attempted_providers,
                    "selected_provider": response.provider_id,
                    "fallback_from": fallback_from,
                }
                logger.info(
                    "%s transcription complete via %s: %.0fs, %s segments, %s speakers",
                    mode_config.mode.value.title(),
                    response.provider_id,
                    result.get("duration", 0),
                    len(result.get("segments", [])),
                    len(result.get("speakers", [])),
                )
                return result
            except Exception as e:
                failures.append((provider_id, e))
                if not mode_config.fallback_enabled:
                    raise

                if provider_id == provider_route[-1]:
                    break

                next_provider = provider_route[len(attempted_providers)]
                logger.warning(
                    "Transcription provider %s failed, falling back to %s: %s",
                    provider_id,
                    next_provider,
                    e,
                )

        failure_summary = "; ".join(
            f"{provider_id}: {error}" for provider_id, error in failures
        )
        raise RuntimeError(
            f"Transcription failed after trying {', '.join(attempted_providers)}: "
            f"{failure_summary}"
        )

    @staticmethod
    def _provider_result_label(provider_id: str, fallback_from: Optional[str]) -> str:
        if provider_id == "whisper" and fallback_from == "voxtral":
            return "whisper_fallback"
        return provider_id

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
        prompt_parts = [settings.ASR_CONTEXT_PROMPT or DEFAULT_ASR_CONTEXT_NOTE]
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
            return self._clean_transcription_result(self._parse_voxtral_response(response))
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
        }
        if language:
            kwargs["language"] = language

        prompt_parts = [settings.ASR_CONTEXT_PROMPT or DEFAULT_ASR_CONTEXT_NOTE]
        if settings.domain_terms_list:
            prompt_parts.append(", ".join(settings.domain_terms_list[:100]))
        kwargs["prompt"] = "\n".join(part for part in prompt_parts if part)

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

        return self._clean_transcription_result({
            "text": response.text,
            "language": getattr(response, "language", "en"),
            "duration": getattr(response, "duration", 0),
            "words": words,
            "segments": segments or self._segments_from_text(response.text, getattr(response, "duration", 0)),
            "speakers": [],
        })

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    #  HALLUCINATION / PROMPT LEAK CLEANUP
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def _clean_transcription_result(self, result: dict) -> dict:
        """
        Remove ASR prompt echoes/hallucinated instruction loops.

        Whisper's prompt field is context, not an instruction channel. Older
        runs used an instruction-style prompt, and during long silences the
        model echoed it into the transcript. This guard keeps future sidecar
        files and edit plans from treating that as lecture content.
        """
        segments = result.get("segments") or []
        words = result.get("words") or []

        cleaned_segments = []
        leak_seen = False
        for seg in segments:
            if leak_seen:
                continue

            original_text = (seg.get("text") or "").strip()
            cleaned_text, leaked = self._strip_prompt_leak(original_text)

            if cleaned_text and len(cleaned_text.split()) >= 3:
                cleaned = dict(seg)
                cleaned["text"] = cleaned_text
                if leaked:
                    original_len = max(len(original_text), 1)
                    keep_ratio = min(0.95, max(0.05, len(cleaned_text) / original_len))
                    start = float(cleaned.get("start", 0) or 0)
                    end = float(cleaned.get("end", start) or start)
                    cleaned["end"] = start + ((end - start) * keep_ratio)
                cleaned_segments.append(cleaned)

            if leaked:
                leak_seen = True

        cleaned_words = self._strip_prompt_words(words)

        if leak_seen:
            logger.warning("ASR prompt leakage detected and removed from transcript")

        if cleaned_segments:
            result["segments"] = cleaned_segments
            result["text"] = " ".join(s["text"] for s in cleaned_segments).strip()

            last_clean_end = max(float(s.get("end", 0) or 0) for s in cleaned_segments)
            if last_clean_end:
                result["duration"] = min(float(result.get("duration", 0) or last_clean_end), last_clean_end)
        else:
            cleaned_text, leaked = self._strip_prompt_leak(result.get("text", "") or "")
            result["text"] = cleaned_text
            if leaked:
                result["segments"] = self._segments_from_text(cleaned_text, result.get("duration", 0))

        result["words"] = cleaned_words
        return result

    @staticmethod
    def _strip_prompt_leak(text: str) -> tuple[str, bool]:
        lower = text.lower()
        marker_positions = [
            lower.find(marker)
            for marker in PROMPT_LEAK_MARKERS
            if lower.find(marker) >= 0
        ]
        if not marker_positions:
            return text.strip(), False

        first_marker = min(marker_positions)
        return text[:first_marker].strip(" ,.;:-"), True

    @staticmethod
    def _strip_prompt_words(words: List[dict]) -> List[dict]:
        if not words:
            return []

        normalized = [
            WORD_CLEAN_RE.sub("", (w.get("word") or w.get("text") or "").lower())
            for w in words
        ]

        cutoff = len(words)
        for i, token in enumerate(normalized):
            window = normalized[i:i + 12]
            if token == "transcribe" and "exactly" in window and "spoken" in window:
                cutoff = i
                break
            if token == "preserving" and "original" in window and "language" in window:
                cutoff = i
                break
            if token == "normalize" and "speech" in window and "language" in window:
                cutoff = i
                break

        return words[:cutoff]

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
    ffmpeg_binary(), "-i", audio_path,
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
            ffprobe_binary(), "-v", "quiet",
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
