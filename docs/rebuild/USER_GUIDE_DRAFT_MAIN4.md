# Aivora for Windows — user guide

**DRAFT — private version 2.1.0-rebuild.2, Windows x64.** Final installed verification, source and notice coverage, and public delivery are pending. This guide describes the supplied workflow; it is not final release approval.

## Installation and first launch

1. Run the supplied installer and follow the assisted per-user installation prompts.
2. Launch Aivora. The first-launch screen is **Prepare your editing workspace**.
3. Choose **Prepare automatically**. Aivora discovers its packaged catalog and prepares the four required components: the editing engine, FFmpeg, LibreOffice, and Whisper small. Manual tool or catalog selection is not required by this workflow.
4. After preparation completes, use the project dashboard. An empty dashboard displays **No projects yet**; use the project form to create a project.

The corrected preparation engine has passed frozen checks. The combined installer and its final first-use flow still require verification. If preparation fails, use **Retry preparation** or **Open diagnostics** rather than deleting your data.

Allow extra disk space for the installer, component archives and extraction, caches, updates, recordings, exports, and optional models. A verified minimum hardware or disk requirement is not yet available. The private installer is unsigned.

## Offline and connected features

The required runtime and tool packs, including Whisper small, are bundled for offline component preparation. Cloud reasoning, embeddings, provider verification, and optional model downloads need the connectivity required by your selected service. Do not assume that every AI feature works fully offline.

## Provider credentials

Open **Settings** to configure the provider you intend to use. The observed provider slots are Mistral, OpenAI, DeepSeek, and Alibaba. Credentials are stored in a Windows-protected encrypted vault.

A configured key does not establish that the provider connection works. Verify your chosen provider through the available settings controls when connected. Do not copy a repository environment file or put keys into plaintext configuration files.

## Local Whisper models

From **Settings**, open **Local Models**, then **Manage local Whisper models**.

Whisper small is bundled and protected, at approximately 466 MiB. Optional medium and large-v3 downloads contain 1,533,763,059 and 3,095,033,483 bytes respectively; allow additional working space.

1. Choose the model you want to manage. **Download Whisper [model]** starts an optional acquisition.
2. Use **Cancel Whisper [model] download or verification** when needed. Cancelling an acquisition can retain partial data for **Resume Whisper [model]**.
3. Use **Verify Whisper [model]** when the retained model needs verification.
4. Select a verified model and choose **Save** to activate it. On returning to Settings, **Current model [id]** identifies the active model.
5. Use **Remove Whisper [model]** to remove an optional model. Bundled small must remain available.

Medium acquisition, verification, activation, and removal have supporting acceptance evidence. Final installed medium restart remains pending. Large-v3 partial download, cancellation, resume, and removal have been exercised; a complete large-v3 download and runtime probe have not been accepted. These results do not establish compatibility with every CPU.

## Projects, media, and materials

Create a project from the dashboard or open an existing project with **Open project [title]**. Add the media and supporting materials through the project workflow, then start processing.

PDF and PPTX extraction and indexing have supporting acceptance evidence. Multi-source offset and layout acceptance remains pending. Processing stops for teacher review; it does not automatically approve a render.

## Teacher review through six stages

Work through **Transcribe**, **Clean**, **Sections**, **Layout**, **Polish**, and **Export**. The original five-agent processing order is preserved.

Review the transcript and editing decisions. Keep or cut material deliberately and retain teacher notes. In **Sections**, review the generated chapters and clips, then use **Mark Sections Complete** when your review is complete. Continue to **Layout** to review the composition before moving to Polish and Export.

Teacher review and render approval are separate actions. Representative teacher decisions and notes have been preserved in accepted workflows.

## Polish

Use **From chapters** to prepare educational cards, review them, and choose **Save Educational Overlays** to persist the result. Review annotations, caption policy, and end-card controls before approving a render.

Local playback and the outer preview aspect ratio have acceptance evidence. The latest HTML slide content correction still needs installed visual review.

## Exports and reports

After teacher approval, render and use the native save controls for **Edited Video (MP4)**, **Subtitles (SRT)**, and **Edit Plan (JSON)**. Original transcript exports include plain TXT, timestamped TXT, JSON, and segment CSV. Quality, metrics, timeline, and evidence exports are also available in the workflow.

A representative 720p MP4 and a native 20-entry evidence bundle have been accepted. This does not guarantee synchronization or quality for every input.

Read report qualifications alongside their values: ASR accuracy is a proxy; processing time may be unavailable; estimated cost is not billing; and mode comparisons describe planned strategies rather than measured executions. Render cancellation has preserved prior valid outputs in frozen checks, while final installed interruption coverage remains pending.

## Storage and backups

Aivora user storage has been observed under `%LOCALAPPDATA%\AIVE\Desktop`, with Shell, Data, Components, Cache, State, and Logs folders. Data includes the project database, vector store, uploads, exports, and owned temporary files. Installed binaries are stored separately.

Close Aivora before backing up the whole user folder. Preserve that backup before maintenance. Avoid selective database edits, resets, or reseeding as recovery workarounds.

## Diagnostics and recovery

For preparation problems, use **Retry preparation** and **Open diagnostics**. For ordinary recovery, restart Aivora and reopen your project. Keep your recordings, teacher decisions, exports, and backup intact while investigating a failure.

Do not delete user data to force a fresh setup. Final installed interruption and recovery coverage is still being completed.

## Updates and uninstall

Existing assisted installer updates have preserved user data, the encrypted credential vault, and component activation state. Keep a closed-app backup before an update.

Uninstall retention has not yet been verified; do not assume an uninstall preserves your data. Live updater behavior has not been accepted. No final download links, asset hashes, or update promises are supplied in this draft.

## Limitations and status

Final first-use, HTML preview content, Windows scaling and accessibility, uninstall retention, source and notice coverage, guide verification, and public release remain pending. Clean-PC, other-laptop, GPU, live-updater, and all-model operation are not established.

The five-second readiness target remains open. Do not treat window appearance as full engine readiness. This private draft will need reconciliation with the final accepted installer and delivery evidence.
