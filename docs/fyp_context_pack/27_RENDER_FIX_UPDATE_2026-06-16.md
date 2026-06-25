# Render Fix Update 2026-06-16

This note records a post-audit localhost regression, its root cause, the code fix, and the verification evidence. It is intended to be easy to paste into a fresh Codex chat or into thesis/report working notes.

## Incident summary

- Date of reproduction: June 16, 2026
- Runtime: localhost stack on port 8000
- Project: `test23`
- Video: `Timeline 3.mp4`
- Video duration: about 29:54
- Structure-reference asset: one PDF with 36 pages
- Failure point: 12 percent during render/export
- Visible UI message: slideshow generation failed and appeared to implicate FFmpeg/NVENC

## What was actually happening

The failure was not primarily a GPU encoder failure. The real problem was inside FFmpeg slideshow construction for generated slide backgrounds.

The previous implementation of `FFmpegService.create_slideshow_clip` accepted every rasterized PDF page as its own FFmpeg input and built one scale/fps/trim chain per page before concatenating them into a slideshow. For `test23`, that meant:

- 36 simultaneous PNG inputs
- 36 separate scale filters
- 36 timing chains
- one large concat graph
- then NVENC encoding after the filter graph

With this deck size, FFmpeg exhausted filter-thread resources before the encoder even received frames. The actionable tail of the reproduced stderr was:

```text
Parsed_scale_63: Failed to configure output pad
Resource temporarily unavailable
Conversion failed
```

This explains why the first four videos rendered successfully but the fifth failed: the earlier decks stayed below the complexity threshold where the slideshow filter graph became unstable.

## Why the old error message was misleading

The renderer was truncating stderr from the start, so the stored/UI message mainly preserved the FFmpeg version banner instead of the useful ending. That made the issue look like a generic NVENC failure when the real cause was hidden in the tail.

The relevant error-reporting improvement is now in `backend/app/services/ffmpeg.py:24-28` via `_stderr_message`, and is used by the FFmpeg process wrapper around `backend/app/services/ffmpeg.py:64-112`.

## Fix applied

The fix was intentionally narrow and render-specific.

### 1. Replace many-input slideshow generation with FFconcat for multi-page decks

`FFmpegService.create_slideshow_clip` now:

- keeps the existing single-image behavior for one-page inputs
- creates a temporary `.ffconcat` manifest for multi-page inputs
- feeds the whole timed page sequence into FFmpeg as one concat-demuxed video stream
- applies one scale/pad/fps/format filter chain instead of dozens of parallel ones
- removes the temporary manifest after the run

Code evidence:

- `backend/app/services/ffmpeg.py:1621-1706`
- comment explaining the root cause and fix at `backend/app/services/ffmpeg.py:1650-1652`
- cleanup at `backend/app/services/ffmpeg.py:1704-1706`

### 2. Improve FFmpeg error preservation

`FFmpegService._stderr_message` now keeps the tail of stderr when truncation is needed, so future failures preserve the actionable diagnostic rather than only the version banner.

Code evidence:

- `backend/app/services/ffmpeg.py:24-28`
- wrapper usage in `_run_process` and `_run_process_with_encoder_fallback` at `backend/app/services/ffmpeg.py:31-50,64-112`

## Tests added

Two regression tests were added:

- `backend/tests/test_picture_in_picture_renderer.py:293-324`
  - `test_slideshow_multiple_images_use_single_concat_input`
  - verifies the new FFconcat-based slideshow path for a 36-image deck
- `backend/tests/test_picture_in_picture_renderer.py:327-334`
  - `test_ffmpeg_error_message_keeps_actionable_tail`
  - verifies that the useful tail of FFmpeg stderr is preserved

## Verification performed

### Code-level verification

- `.venv\Scripts\python.exe -m unittest backend.tests.test_picture_in_picture_renderer -v`
  - 38 tests passed
- `.venv\Scripts\python.exe -m unittest discover -s backend\tests -p test_*.py`
  - 193 tests passed

### Runtime reproduction and validation

- The old 36-input slideshow shape was reproduced against the real `test23` rasterized slide pages and failed with the `Parsed_scale_63` / `Resource temporarily unavailable` error.
- A replacement FFconcat-based probe using those same 36 slide pages succeeded with NVENC and produced a valid H.264/AAC 1920x1080 slideshow.
- The localhost backend was restarted with the fix and `test23` was re-approved for export.
- The live retry passed the previous 12 percent failure boundary and entered native semantic composition.

Runtime snapshot captured on June 16, 2026:

- render job status: `running`
- phase: `native_semantic_composition`
- progress: 23 percent
- message: composing scene 12/90
- error: `null`

This confirms the slideshow-generation regression itself was fixed in the real localhost workflow.

## Safe wording for report or handoff

Use wording like this:

> During post-audit localhost validation, a render regression was reproduced on a 29:54 lecture video linked to a 36-page PDF slide deck. The failure occurred during generated-slide slideshow creation, where the previous FFmpeg command constructed one parallel filter chain per slide page. This exhausted filter-graph resources before encoding began. The issue was fixed by changing multi-page slideshow generation to an FFconcat single-stream path and by improving FFmpeg error-tail preservation. After the fix, the same project advanced beyond the previous failure point and entered native semantic composition.

Avoid wording like this:

- "The GPU was broken."
- "NVENC was the root cause."
- "Agent 4 selected the wrong slides and caused the render failure."
- "The fix proves all long-form renders are now fully reliable."

## Thesis/report implication

This incident should be treated as:

- a rendering-pipeline implementation bug
- successfully reproduced on localhost
- fixed with a bounded, code-level change
- verified with both automated tests and live runtime evidence

It should not be presented as:

- a model-quality issue
- a semantic-planning issue
- a measured performance result
- proof that all long-duration exports are now universally stable
