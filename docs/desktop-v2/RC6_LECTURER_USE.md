# RC.6 Lecturer Use Guide

## Create a project and import video

1. Launch **AI Video Editor Desktop V2** and wait for native readiness.
2. On the project dashboard, select **Create Project**, enter the project details, and open it.
3. Select **Import video** for the primary source and choose a valid local video such as MP4.
4. Keep the source file available until the native import card reaches **Completed**. The app copies to a `.part` file, flushes it, atomically stages it, and records durable phases and events before finalizing.

An interrupted import can be polled and resumed/retried after restart. Use **Cancel** only while the status card says the operation is cancellable. A cancelled or failed import does not make its partial file a valid project asset. Do not manually rename `.part` files.

## Work through the editor

The guided workflow advances from source validation through processing, transcript/review, edit decisions, and export. Follow the visible next action and resolve the first blocker shown. Local ingest, source checks, manual review, and provider-free media operations remain useful when no AI provider is configured.

Provider-backed transcription or generation requires a lecturer-owned credential:

1. Open **Settings** and choose the provider section.
2. Select one of the fixed supported providers; do not paste a provider identifier into a diagnostic field.
3. Save the key securely to Windows Credential Manager and select **Verify provider**.
4. Keep secrets out of screenshots, project notes, JSON evidence, and support messages.

If local transcription is offered, review its model download size, hash, storage location, and consent prompt before downloading. Models live in the user-data boundary, not Program Files or the component archive.

## Export

1. Review workflow warnings. Export is blocked while required source or processing prerequisites are unresolved.
2. In the **Export** step, select an available preset and caption behavior.
3. Confirm or change the export folder in **Settings > Export** if needed.
4. Start export and wait for completion before closing the app.
5. Open the resulting MP4 from `%USERPROFILE%\Documents\AI Video Editor\Exports` or the folder you selected, and verify video playback and expected duration.

JSON plans, quality reports, academic evidence, or section clips are supporting outputs; they do not replace checking the playable video.

## Close and resume

Close the app normally, reopen it, and confirm the project, completed import, workflow/job state, and export are still present. Projects and exports are user data and are outside the signed component activation directory. Default uninstall and component repair must not remove them.

For technical details, open **Diagnostics > Redacted recovery details**. It reports storage checks, installed components, handshake/readiness/capabilities times, and a bounded redacted native stdout/stderr tail. Provider tokens are not persisted in diagnostics.
