# Desktop V2 Phase 9 release-candidate handoff

## Release identity

This is the Desktop V2 installer ACL hotfix release candidate based on commit `2ccea79bae4bf527022c9b332348b91c675e1922` and produced on `codex/desktop-v2-installer-acl-hotfix`.

| Field | Frozen value |
| --- | --- |
| Product | AI Video Editor Desktop V2 |
| Version | `2.0.0-rc.2` |
| Channel | `beta` |
| Shell identity | `com.fyp.ai-video-editor.desktop-v2` |
| Shell contract | `desktop.shell-identity.v1` |
| Engine contract | `desktop.health-readiness.v1` |
| Component manifest | `desktop.component-manifest.v1` |
| Catalog contract | `desktop.setup-catalog.v1` |
| Minimum OS | Windows 10 64-bit |
| Architecture | Windows x86_64 |
| Runtime prerequisites | WebView2; no system Python, Node.js, Docker, or FFmpeg |
| Minimum free space | 2 GiB, plus project/media working space |

The distributable handoff is the folder `AI-Video-Editor-Desktop-V2-Handoff`. It contains the small shell installer, signed component archives, signed offline catalog, public trust root, smoke source, documentation, checksums, and read-only verifier. The handoff folder and its eventual ZIP are intentionally outside Git.

## Exact distributable artifacts

These are the final handoff artifact records. Hashes are SHA-256; sizes are bytes. The mutable values below are refreshed from the generated rc.2 handoff before distribution.

| Artifact | Size/hash source |
| --- | --- |
| Installer, engine archive, component manifests, catalog, and release manifest | `AI-Video-Editor-Desktop-V2-Handoff\SHA256SUMS.txt` and `release-manifest.json` |
| `SHA256SUMS.txt` | generated in handoff; verified by `VERIFY-HANDOFF.ps1` |

The distribution ZIP beside the folder is `AI-Video-Editor-Desktop-V2-Handoff.zip`; its final size and SHA-256 are recorded in the final hotfix report.

The signed frozen engine inventory records `bin/aive-engine.exe` as 23,990,956 bytes with SHA-256 `813e46ebc4b5a5ac34bee032d807cb35acaf391e8121fc262877dae86b6c7e5b`. The FFmpeg inventory records `bin/ffmpeg.exe` as 227,398,656 bytes with SHA-256 `09948d4cdd0650da6ff5a87577469f2a218dc2615ae379f8f734d24c49de0f73` and `bin/ffprobe.exe` as 227,193,344 bytes with SHA-256 `a6618e99bb58869ded3c6f37b53aa1a8d701c3591dbb7b5b317d47369c112be2`.

## Trust and signing status

The shell compiles the Ed25519 lecturer-release trust root:

- Key id: `aive-desktop-v2-lecturer-2026`
- Public-key SHA-256: `471e7b08109f8723400afea495f63d1d93753e4757386e31560a7cbee6bd2a2d`
- Algorithm: Ed25519
- Private seed: generated and preserved in a restricted release-secrets directory outside the repository; it is not in Git, the handoff, the ZIP, logs, or build outputs
- Signed objects: both component manifests and the offline catalog; detached signatures are checked against the embedded signature values

No Authenticode certificate was available. The NSIS installer was built with `--no-sign`, is explicitly marked unsigned, and may show a Windows SmartScreen/unknown-publisher warning. This RC does not claim commercial Windows code signing. Verify the handoff checksums and Ed25519 trust root before choosing “More info → Run anyway.”

## Portable offline artifact references

The signed manifests do not contain creator-machine paths or `file:///...` URLs. Each artifact uses:

```text
offline:Components/<filename>
```

Setup Center’s file-import command takes the selected catalog’s containing directory as the offline root. The component manager then:

1. validates the `offline:` scheme and requires a `Components/` child path;
2. rejects absolute paths, drive letters, empty segments, `.`/`..`, and traversal;
3. canonicalizes the imported root and candidate artifact;
4. requires the candidate to remain beneath that root and to be a regular non-reparse file; and
5. downloads only from that resolved local file before checking the signed size/hash and exact archive inventory.

The root is persisted only as machine-scoped import metadata so later Setup Center operations can use the same catalog without embedding an absolute path in the signed release metadata. Moving the handoff requires importing the catalog again from its new location.

## Install, update, repair, rollback, and uninstall flow

1. Run `AI Video Editor Desktop V2 Setup.exe` and approve elevation. The installer targets `C:\Program Files\AI Video Editor Desktop V2`, creates Start-menu and desktop shortcuts, and bundles no heavy engine, FFmpeg, models, databases, uploads, projects, API keys, or environment files.
2. Launch the shell, open Setup Center, and choose **Offline catalog / Import catalog**. Select `Catalog/offline-catalog.json` while `Catalog` and `Components` remain siblings.
3. Setup Center verifies the catalog trust root, imports both signed component manifests, resolves the dependency plan, calculates required disk space, downloads from the portable references, verifies hashes/signatures, stages, and activates under the machine-scoped component root.
4. The Phase 5 supervisor starts the activated frozen engine on a dynamic loopback port, authenticates readiness with a generated bearer token, and routes only authenticated loopback traffic.
5. A later signed catalog can add a newer component version. The manager retains the previous active version during atomic activation and exposes repair/rollback metadata. This RC includes one version per required component, so a lecturer can exercise repair/recovery but cannot demonstrate a version downgrade without a second signed release.
6. The default uninstall plan removes the shell and preserves user data. Explicit destructive cleanup remains a separate, confirmed action.

## Evidence and regression gates

| Gate | Result |
| --- | --- |
| Contract fixtures | PASS — 6 schemas and 11 fixtures |
| Frontend tests | PASS — contract, Phase 2, 5, 6, 7, and 8 suites |
| Frontend production build | PASS — TypeScript and Vite production build |
| Rust check/tests | PASS — `cargo check`; 42 Rust tests and doc-test target pass |
| Frozen engine | PASS — PyInstaller Windows x64 onedir build and self-test; dynamic port/authenticated readiness/shutdown smoke |
| FFmpeg component | PASS — real Windows `ffmpeg.exe` and `ffprobe.exe`, version, encode, probe, and decode smoke |
| Portable copied-handoff test | PASS — copied to a different temporary root; signed offline catalog import; real engine and FFmpeg install/verify/activate; engine lifecycle and FFmpeg export; 1 test in 325.40 seconds |
| Component tamper negative | PASS — verifier rejects checksum/signature/layout changes in isolated temporary copies |
    | NSIS | PASS — x64 installer built and exercised in the real Windows profile; ACL, path, shortcuts, launch, and uninstall preservation verified |
| Handoff verifier | PASS — exact layout, checksums, public-key fingerprint, Ed25519 signatures, portable references, no private key, no creator path in release metadata |
| Safety/secret/tracked-artifact audit | PASS — protected original folders untouched; release binaries/build caches/private seed excluded from Git |

The verifier is read-only and does not execute the installer or any component. Run it from the handoff root with PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\VERIFY-HANDOFF.ps1
```

## Known limitations

- Provider credentials, Docker configuration, models, user projects, uploads, databases, and API keys are intentionally absent. Provider-backed AI generation is not claimed as an offline acceptance path.
- The local engine exposes a truthful degraded vector-store contract when optional local-vector services are unavailable; SQLite/local readiness and FFmpeg processing remain usable.
- The installer is unsigned for Authenticode and SmartScreen may warn.
- Docker compose is not part of lecturer acceptance and may be configuration-blocked by an absent private `.env`; the protected original work folders and existing containers are not changed.
- The installer is tested against the real Windows profile for the shell/ACL/shortcut/launch/uninstall path. Component install/lifecycle and authenticated engine/FFmpeg smoke use both the copied handoff and redirected temporary roots; no provider secrets or Docker services are required.

## Final gate

**PASS — lecturer-ready release-candidate handoff.** The real frozen engine, real pinned FFmpeg component, signed portable offline catalog, thin unsigned NSIS installer, copied-tree install/lifecycle test, and read-only handoff verifier are present and passing. The final ZIP is created only after this verifier and the copied-tree test pass, and must itself be distributed with the handoff folder’s checksum list.
