# RC.6 Lecturer Install Guide

Complete the RC.6 verification in the setup guide before running the installer. This developer/test build is not Authenticode-signed. Windows may display **Unknown publisher** or Microsoft Defender SmartScreen may require **More info**. Proceed only when the handoff came from the expected evaluator channel and both included verifiers passed; otherwise stop.

## Install the shell

1. Copy the entire extracted handoff to a local folder. Do not run the installer from inside the ZIP.
2. Run `AI Video Editor Desktop V2 Setup.exe`.
3. Approve the Windows administrator prompt. The installer is per-machine and targets `%ProgramFiles%\AI Video Editor Desktop V2\Shell`.
4. Finish setup, then launch **AI Video Editor Desktop V2** from its Start menu or Desktop shortcut.

A new installation intentionally begins without the heavy engine and media components. The first launch opens Setup Center.

## Complete Setup Center

1. On **Welcome**, continue to **Check this PC** and resolve any blocking storage or WebView2 message.
2. At **Install Core**, use the bundled catalog when offered. If it is unavailable, choose **Browse** and select this handoff's `Catalog\offline-catalog.json`. Browse accepts the catalog JSON, not its `.sig` file or a component archive.
3. Install the native core and approve the scoped activation prompt if Windows asks.
4. At **Install Media Tools**, install FFmpeg `8.1.1` from the same verified catalog.
5. Wait for **Verify and Start**. Do not close the app or power off the PC while an activation step is publishing.
6. At **Optional AI Setup**, choose **Work locally**, **Connect a provider**, or **Decide later**. Local ingest and manual/provider-free operations do not require an API key.
7. Continue when Setup Center shows **Ready** and launch the editor.

Setup Center verifies catalog trust, expiry and compatibility, archive hashes, inventory, self-tests, activation, the authenticated loopback engine handshake, readiness, and capabilities. Engine stdout/stderr are diagnostics only and never the readiness authority.

## Confirm first launch

- The shell opens without a repository checkout, Docker, or a manually started backend.
- Setup Center shows both required components as installed and the native engine as ready.
- **Diagnostics** shows a successful readiness and capabilities probe. Technical output is bounded and redacted.
- Create a small test project and import a valid local MP4 before relying on provider-backed functions.

No clean-PC success is implied merely because the source build or operator smoke passed. Record the Windows version, installer filename/hash, verifier output, UAC result, shortcut targets, first-launch result, and any reboot requirement on the actual evaluation PC.

Next: see the use guide in `USE.md` in the assembled handoff.
