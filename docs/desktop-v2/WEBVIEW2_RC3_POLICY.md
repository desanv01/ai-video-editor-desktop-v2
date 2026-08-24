# Desktop V2 rc.3 WebView2 policy

The shell detects Microsoft WebView2 before it creates a Tauri window. A missing runtime is a release-visible prerequisite failure; the shell never downloads or bootstraps WebView2 silently.

The supported distribution choices are:

- Evergreen Runtime, installed by the official Microsoft Bootstrapper when the machine is online.
- Evergreen Standalone Installer, supplied and checksum-verified by the release owner for offline lecturer machines.
- Fixed Runtime only when the release owner supplies a provenance record, SHA-256, and the Windows 10 ACL plan. Fixed Runtime is materially larger (over 250 MB) and is not the default.

The detector checks the per-user and per-machine EdgeUpdate client key in both 32-bit and 64-bit views. Because some valid Evergreen installs do not publish those client keys, it then performs a bounded fallback over the exact Microsoft `EdgeWebView\Application` roots under `ProgramFiles(x86)`, `ProgramFiles`, and `LOCALAPPDATA`. A fallback candidate must be a regular `msedgewebview2.exe`, stay beneath the selected root, be within the size bound, expose a valid four-part Windows PE product/file version, and match its version directory. It also recognizes a fixed runtime only through the explicit `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` path after the same executable/version checks. No network request is made by detection.

`scripts/desktop-v2/Detect-WebView2.ps1` is the release procedure. Detection-only mode returns exit code 0 when available and 20 when missing. Explicit installation requires an externally supplied artifact, its SHA-256, and an online/offline policy choice. Provenance/checksum failures return 21 or 24; an online-only bootstrapper is rejected in offline mode with 23; installer failures return 22. Exit code 0 or 3010 is accepted from the Microsoft installer, followed by a second detection.

Release evidence must record the Microsoft download URL, retrieval date, artifact kind, exact file size, SHA-256, installer exit code, and post-install detected version. A placeholder or fabricated checksum is not release evidence.

References: [Microsoft WebView2 distribution](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution).
