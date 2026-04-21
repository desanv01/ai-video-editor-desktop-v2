#!/usr/bin/env python3
"""
Phase B Test Script — Transcription Pipeline End-to-End Test
=============================================================

Tests the full Agent 1 pipeline:
  1. Audio extraction (ffmpeg)
  2. Voxtral transcription (Mistral API) with fallback to Whisper (OpenAI API)
  3. Output validation (timestamps, segments, diarization)

Usage:
    # Test with a real video file:
    python scripts/test_transcription.py --file /path/to/lecture.mp4

    # Test with a URL (downloads first):
    python scripts/test_transcription.py --url https://example.com/lecture.mp4

    # Test Whisper fallback explicitly:
    python scripts/test_transcription.py --file /path/to/lecture.mp4 --provider whisper

    # Test with domain terms:
    python scripts/test_transcription.py --file /path/to/lecture.mp4 --terms "quicksort,polymorphism,recursion"

Environment:
    Requires MISTRAL_API_KEY and/or OPENAI_API_KEY in .env or environment.
    Requires ffmpeg installed.
"""

import asyncio
import argparse
import os
import sys
import time
import json
import subprocess

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


async def main():
    parser = argparse.ArgumentParser(description="Test transcription pipeline")
    parser.add_argument("--file", type=str, help="Path to video/audio file")
    parser.add_argument("--url", type=str, help="URL to download video from")
    parser.add_argument("--provider", type=str, default=None,
                        help="Force provider: 'voxtral' or 'whisper'")
    parser.add_argument("--terms", type=str, default=None,
                        help="Comma-separated domain terms for context biasing")
    parser.add_argument("--output", type=str, default=None,
                        help="Save transcript JSON to this path")
    args = parser.parse_args()

    # ── Resolve input file ──
    if args.url:
        print(f"\n📥 Downloading from URL: {args.url}")
        file_path = "/tmp/test_lecture.mp4"
        result = subprocess.run(
            ["curl", "-L", "-o", file_path, args.url],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"❌ Download failed: {result.stderr[:200]}")
            sys.exit(1)
        print(f"✅ Downloaded to {file_path}")
    elif args.file:
        file_path = args.file
    else:
        # Generate a tiny test audio with ffmpeg (10 seconds of silence + tone)
        print("\n⚠️  No input file specified. Generating a 10-second test tone...")
        file_path = "/tmp/test_tone.wav"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=10",
            "-ar", "16000", "-ac", "1",
            file_path,
        ], capture_output=True)
        print(f"✅ Generated test audio: {file_path}")
        print("   NOTE: Transcription of a pure tone will return empty text.")
        print("   For a real test, use: --file /path/to/lecture.mp4\n")

    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        sys.exit(1)

    file_size_mb = os.path.getsize(file_path) / 1024 / 1024
    print(f"\n📂 Input: {file_path} ({file_size_mb:.1f} MB)")

    # ── Override provider if specified ──
    from config import settings
    original_provider = settings.ASR_PROVIDER
    if args.provider:
        settings.ASR_PROVIDER = args.provider
        print(f"🔧 Provider override: {args.provider}")

    # ── Parse domain terms ──
    domain_terms = None
    if args.terms:
        domain_terms = [t.strip() for t in args.terms.split(",")]
        print(f"📝 Domain terms: {domain_terms}")

    # ── Step 1: Extract audio ──
    print("\n" + "=" * 60)
    print("  Step 1: Audio Extraction (ffmpeg)")
    print("=" * 60 + "\n")

    from services.ffmpeg import ffmpeg_service

    audio_path = "/tmp/test_audio.wav"
    start = time.time()
    try:
        # Check if input is already audio
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".wav", ".mp3", ".ogg", ".flac", ".m4a"):
            # Just resample for consistency
            audio_path = file_path
            if ext != ".wav":
                await ffmpeg_service.extract_audio(file_path, audio_path)
            print(f"  ✅ Audio file detected, using directly")
        else:
            await ffmpeg_service.extract_audio(file_path, audio_path)
            print(f"  ✅ Audio extracted: {audio_path}")
    except Exception as e:
        print(f"  ❌ Audio extraction failed: {e}")
        sys.exit(1)

    extract_time = time.time() - start
    audio_size_mb = os.path.getsize(audio_path) / 1024 / 1024
    print(f"  ⏱  Time: {extract_time:.1f}s")
    print(f"  📊 Audio size: {audio_size_mb:.1f} MB")

    # Get audio duration
    from services.transcription import TranscriptionService
    duration = await TranscriptionService._get_audio_duration(audio_path)
    print(f"  ⏱  Duration: {duration:.1f}s ({duration/60:.1f} min)")

    # ── Step 2: Transcribe ──
    print("\n" + "=" * 60)
    print(f"  Step 2: Transcription ({settings.ASR_PROVIDER.upper()})")
    print("=" * 60 + "\n")

    from services.transcription import transcription_service

    start = time.time()
    try:
        result = await transcription_service.transcribe(
            audio_path=audio_path,
            domain_terms=domain_terms,
        )
    except Exception as e:
        print(f"  ❌ Transcription failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    transcribe_time = time.time() - start

    # ── Step 3: Validate and display results ──
    print("\n" + "=" * 60)
    print("  Step 3: Results")
    print("=" * 60 + "\n")

    provider = result.get("provider", "unknown")
    text = result.get("text", "")
    words = result.get("words", [])
    segments = result.get("segments", [])
    speakers = result.get("speakers", [])
    language = result.get("language", "unknown")
    reported_duration = result.get("duration", 0)

    print(f"  Provider:      {provider}")
    print(f"  Language:      {language}")
    print(f"  Duration:      {reported_duration:.1f}s")
    print(f"  Transcribe:    {transcribe_time:.1f}s ({duration/max(transcribe_time, 0.1):.1f}x realtime)")
    print(f"  Word count:    {len(text.split())}")
    print(f"  Words (timed): {len(words)}")
    print(f"  Segments:      {len(segments)}")
    print(f"  Speakers:      {len(speakers)}")

    if speakers:
        print(f"\n  🎙️  Speakers detected:")
        for sp in speakers:
            print(f"      {sp['label']}: {sp['segments_count']} segments")

    # Show first 5 segments
    if segments:
        print(f"\n  📝 First 5 segments:")
        for seg in segments[:5]:
            speaker_label = f" [{seg.get('speaker', '')}]" if seg.get('speaker') else ""
            print(f"      [{seg['start']:.1f}s - {seg['end']:.1f}s]{speaker_label}")
            print(f"        {seg['text'][:100]}{'...' if len(seg['text']) > 100 else ''}")

    # Show first 10 words with timestamps
    if words:
        print(f"\n  📝 First 10 words with timestamps:")
        for w in words[:10]:
            speaker_label = f" [{w.get('speaker', '')}]" if w.get('speaker') else ""
            print(f"      {w['start']:.2f}s - {w['end']:.2f}s: \"{w['word']}\"{speaker_label}")

    # Show transcript preview
    if text:
        preview = text[:500] + ("..." if len(text) > 500 else "")
        print(f"\n  📝 Transcript preview:")
        print(f"      {preview}")

    # ── Validation checks ──
    print("\n" + "=" * 60)
    print("  Validation")
    print("=" * 60 + "\n")

    checks = []

    # Check 1: Text is non-empty
    checks.append(("Transcript text non-empty", len(text) > 0))

    # Check 2: Segments have timestamps
    if segments:
        has_times = all(s.get("start", -1) >= 0 and s.get("end", 0) > 0 for s in segments)
        checks.append(("Segments have timestamps", has_times))

        # Check 3: Segments are chronologically ordered
        is_ordered = all(
            segments[i]["start"] <= segments[i + 1]["start"]
            for i in range(len(segments) - 1)
        )
        checks.append(("Segments chronologically ordered", is_ordered))

        # Check 4: No large time gaps (>30s)
        max_gap = 0
        for i in range(len(segments) - 1):
            gap = segments[i + 1]["start"] - segments[i]["end"]
            max_gap = max(max_gap, gap)
        checks.append((f"Max segment gap < 30s (actual: {max_gap:.1f}s)", max_gap < 30))

    # Check 5: Words have timestamps
    if words:
        word_times = all(w.get("start", -1) >= 0 for w in words)
        checks.append(("Words have timestamps", word_times))

    # Check 6: Provider matches config
    expected = settings.ASR_PROVIDER
    checks.append((f"Provider matches config ({expected})",
                    provider == expected or provider == f"{expected}_fallback"))

    # Check 7: Diarization (Voxtral only)
    if provider == "voxtral":
        has_speakers = len(speakers) > 0
        checks.append(("Voxtral returned speaker labels", has_speakers))

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)

    for name, ok in checks:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")

    print(f"\n  Results: {passed}/{total} passed\n")

    # ── Save output ──
    output_path = args.output or "/tmp/transcription_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"  💾 Full result saved to: {output_path}")

    # ── Cost estimate ──
    if provider in ("voxtral", "voxtral_fallback"):
        cost = (duration / 60) * 0.003
        print(f"  💰 Estimated Voxtral cost: ${cost:.4f} ({duration/60:.1f} min × $0.003/min)")
    elif provider in ("whisper", "whisper_fallback"):
        cost = (duration / 60) * 0.006
        print(f"  💰 Estimated Whisper cost: ${cost:.4f} ({duration/60:.1f} min × $0.006/min)")

    print()

    # Restore original provider
    settings.ASR_PROVIDER = original_provider

    return 0 if passed == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
