# Get started with Aivora

## Windows handoff

Use a Windows x64 handoff from [Releases](https://github.com/desanv01/ai-video-editor-desktop-v2/releases) or a complete developer delivery. Read its qualification, source identity, signing status, and hashes. Current source is `2.1.0-rebuild.2`; packaging success alone does not establish installed workflow acceptance.

1. Extract the complete handoff and keep its installer, component manifest, `offline-components/`, notices, and guide together.
2. Run the supplied installer. The current Electron installer is assisted and per-user; it allows choosing the installation directory.
3. Open **Aivora**. Use the setup screen to select the supplied offline component folder when needed.
4. Allow the engine, FFmpeg, document tools, and supported transcription runtime/model to complete verification and preparation. Read errors and retry through setup if preparation fails.
5. Configure provider credentials in Settings for the hosted features you choose. Then create a project, import sources, process, review, and export.

Required pack details are declared in [`contracts/rebuild/components.json`](../contracts/rebuild/components.json). Use archives matching that manifest, including size and SHA-256. An installer downloaded from CI is an engineering artifact; CI does not bundle all runtime archives.

## Providers and local processing

The Electron main process uses Windows-backed `safeStorage` for provider credentials and forwards configured keys to the authenticated private engine session. The renderer receives redacted status. Hosted processing can send selected source content to providers and requires their credentials and connectivity.

Local transcription requires both a compatible whisper.cpp runtime and model, plus a successful joint probe. Local storage and manual editing do not make the full AI pipeline offline. Review the capability status displayed by setup and Settings.

## Data and backups

Current Electron storage is rooted at `%LOCALAPPDATA%\AIVE\Desktop`. The retained AIVE directory, application ID, protocol, and component IDs are stable compatibility names beneath the Aivora branding. The shell uses its `Shell` subdirectory; the runtime creates managed component, data, and log paths below the same root.

The Electron installer sets `deleteAppDataOnUninstall: false`. Back up important projects and exports before upgrades or uninstall; installed retention/recovery behavior still needs release-specific verification. A source clone does not include your user database, media, managed archives, or credentials. Use consistent SQLite backups rather than copying only a live database file.

## Source development

Use Node.js **24.14.1** and npm. Backend development uses Python **3.12** and the packages in `backend/requirements.txt` and `backend/requirements-rebuild-storage.txt`.

```powershell
git clone https://github.com/desanv01/ai-video-editor-desktop-v2.git
Set-Location ai-video-editor-desktop-v2
npm ci --prefix desktop
npm run build --prefix desktop
npm run dev:electron --prefix desktop
```

To make the assisted Windows installer:

```powershell
npm run package:win --prefix desktop
```

This builds the shell; it does not manufacture component archives or release acceptance. Use the managed pack tooling in `scripts/rebuild/` to prepare a matching handoff.

For browser iteration, run `npm run dev --prefix desktop` and open the Vite URL, normally `http://localhost:1420`. Browser mode needs a separately configured API. It does not start the private Electron engine. Rust, WebView2, and the Tauri CLI are relevant only to the retained Tauri runtime.

[Contribution checks](../CONTRIBUTING.md) · [Architecture](architecture.md)
