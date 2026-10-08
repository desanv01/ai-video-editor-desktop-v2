# Contributing to Aivora

Read the [setup guide](docs/getting-started.md) and [runtime architecture](docs/architecture.md). Develop against the desktop repository's `main` branch using a focused `codex/` branch.

## Report bugs and ideas

[Open an issue](https://github.com/desanv01/ai-video-editor-desktop-v2/issues) with your version, workflow, expected result, actual result, and reproduction steps. Use synthetic or permission-cleared samples. Remove credentials, private recordings, transcripts, and personal information from logs and screenshots.

## Check a change

Use Node.js 24.14.1 and Python 3.12. Build before running tests that load the compiled Electron controller:

```powershell
npm ci --prefix desktop
npm run build --prefix desktop
npm test --prefix desktop

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt -r backend/requirements-rebuild-storage.txt
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
```

Run affected acceptance scripts from `scripts/rebuild/` when changing storage, credentials, managed components, exports, or process lifecycle. Consult [CI](.github/workflows/ci.yml) for its exact commands and managed FFmpeg requirements. Retained Tauri checks belong to `test:legacy-desktop-v2`, separate from the default Electron tests.

For documentation, verify links, assets, commands, and feature claims. For runtime changes, test the affected behavior. Preserve the six stages, manual overrides, approval, data ownership, and original transcript downloads.

## Pull requests

Describe the concrete problem, resulting behavior, checks performed, and material limitations. Build success does not establish installed workflow, clean-machine, provider, GPU, or signing results. Keep credentials, signing material, user databases, media, generated installers, and runtime archives out of Git.
