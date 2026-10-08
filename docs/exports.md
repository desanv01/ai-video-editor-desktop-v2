# Transcripts and exports

## Original transcript

Download the stored source transcript before or after rendering as plain TXT, timestamped TXT, JSON, or segment CSV. These files retain source speech, source timestamps, and original stored segments; cuts and corrected editing text are separate decisions. A missing source transcript is reported as unavailable.

In the Windows app, use the transcript download controls and choose a save destination. The native bridge saves the authenticated resource through the main process. Browser development uses its download route.

## Final outputs

Review and approve the edit plan before rendering. The Export stage provides video, audio, captions, chapters, edit plans, quality reports, comparisons, and available supporting files. Open the final media and check playback, duration, captions, and expected layouts.

## Editing evidence

Editing evidence records proposed actions, saved overrides, timing, provider routes, quality metrics, and available artifacts. The evidence JSON, Markdown summary, and ZIP bundle are available through the existing `/evidence/export`, `/evidence/summary`, and `/evidence/bundle` endpoints.

The desktop source now names these artifacts `editing_evidence` and uses filenames such as `<video_id>_editing_evidence.json`. Existing generated evidence files from older builds may need to be regenerated through the available export/render flow. Original recordings, transcripts, edit plans, and database state are not rewritten by this naming change.

Quality metrics and estimates help inspect a result; they do not replace checking the output video. Keep private source media, transcripts, and provider details out of public bug reports.
