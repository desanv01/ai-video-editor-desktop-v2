# Synthetic Test Media Fixtures

These fixtures provide a privacy-safe lecture project for Phase 10 evaluation and demos.
The committed files are lightweight source data. Generated audio/video files are written
to `fixtures/synthetic_media/generated/`, which is intentionally ignored by git.

## Generate Fixtures

From the repository root:

```powershell
python scripts/generate_synthetic_test_media.py --force
```

To generate only metadata, transcript sidecars, slide SVGs, and optional PPTX without
requiring FFmpeg:

```powershell
python scripts/generate_synthetic_test_media.py --metadata-only --force
```

## Generated Outputs

The full generator creates:

- `media/lecture_video.mp4`: combined lecture video with screen, camera picture-in-picture, and synthetic audio.
- `media/screen_recording.mp4`: synthetic screen capture source.
- `media/webcam_recording.mp4`: synthetic camera/webcam source.
- `media/separate_audio.wav`: audio master with tone, cue beeps, and short silence windows.
- `slides/synthetic_lecture_slides.pptx`: slide deck when `python-pptx` is available.
- `slides/slide_*.svg`: slide images suitable for visual inspection.
- `transcripts/synthetic_lecture_transcript.json`: word-level transcript.
- `transcripts/synthetic_lecture.srt` and `.vtt`: caption sidecars.
- `synthetic_lecture_manifest.json`: generated asset manifest with relative paths.

The source data models a short academic lecture with screen, camera, audio, slides,
layout cues, edit decisions, filler words, dead air, and chapter markers.
