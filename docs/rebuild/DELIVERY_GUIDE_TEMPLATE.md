Aivora delivery guide — MAIN MUST FINALIZE BEFORE DELIVERY

Replace every bracketed field using verified release and installed evidence.
This template is not acceptance evidence. Do not ship it with placeholders.

Release: [MAIN: actual release version]
Installer: [MAIN: exact installer filename]
Supported system: Windows x64 [MAIN: verified Windows versions]
Observed hardware: [MAIN: CPU, RAM and storage from actual acceptance]
Free space: [MAIN: observed install, preparation and export needs; include margin]
Managed packs: [MAIN: actual engine, FFmpeg, documents and whisper-small versions,
archive filenames and manifest filename; their hashes are in DELIVERY.json]
Limitations: [MAIN: explicit live-provider, other-laptop, GPU and signing evidence
or limitations; do not infer any of these from local installed acceptance]

Prepare
Extract the whole delivery ZIP into a local folder. Keep offline-components and
its manifest together. Read NOTICE.txt. SHA256SUMS.txt lists the supplied files;
[MAIN: provide the verified method for checking them]. Keep your original videos,
slides and any existing project backups. source/ contains the reviewed source ZIP.

Install and prepare components
Run [MAIN: installer filename] and follow the setup prompts. [MAIN: describe the
actual observed installer trust/signature prompts without asserting signing].
Open Aivora and [MAIN: exact verified offline-component selection steps].
Wait for all required components to finish preparation and show ready. If a
component fails, retain the delivery files, read the displayed error and retry
through [MAIN: verified retry control]. Do not mark a failed component ready.

Use your project
Create or reopen a project, import your video and optional teaching materials,
and wait for processing to finish. [MAIN: verified provider configuration steps,
which features need online providers, and supported local transcription choice].
Use the six original stages in order; review and save your decisions:
1. Transcribe — inspect transcript and timing; correct text where needed.
2. Clean — review suggested cuts and keep/remove decisions.
3. Sections — review chapters and their order.
4. Layout — choose and review slide/camera arrangements.
5. Polish — review captions, annotations and other finishing options.
6. Export — review export settings, then render and save the result.
[MAIN: confirm stage labels and the actual actions above against installed UI].

Transcript downloads and export
Use transcript download controls in Transcribe or Export to save the original
transcript as plain TXT, timestamped TXT, JSON or segment CSV. These downloads retain original transcript
content; teacher edits and cuts are separate. Choose a destination and wait for
the save result. For the edited video, use Export, wait for rendering to complete,
then [MAIN: exact verified export save/open steps and resulting file formats].

Reopen, close and retry
Save your decisions using [MAIN: actual save behavior/control]. Reopen the same
project from [MAIN: verified project-list control] and check the saved state.
Close through [MAIN: verified app close behavior; explain any active-work prompt].
If processing or export is interrupted, reopen the project, read its recovery
state and use [MAIN: verified recovery/retry control]. Keep originals and prior
valid exports. [MAIN: state verified limits on resume versus restarting work].

Uninstall and retained data
Use Windows installed-app settings to uninstall [MAIN: exact app display name].
[MAIN: describe observed uninstall prompts and exact verified data-retention
behavior: projects, source media, exports, local credentials and managed packs].
[MAIN: identify any optional data-removal control and its consequences; do not
promise retention or deletion until verified. Recommend backing up wanted data].

Release evidence
DELIVERY.json and evidence/ contain supplied artifact identities, CI identity,
installed gate evidence and explicit qualification limitations. They do not
substitute for testing on another laptop, live providers, GPU or signing.
[MAIN: verified support/reporting instructions; avoid credentials in reports].
