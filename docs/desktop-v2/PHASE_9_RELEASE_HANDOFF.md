# Desktop V2 Phase 9 release-candidate handoff

## Release identity

This is the lecturer release candidate built from Phase 8 commit `21298c927b745707b1bc02040a51f403743d4fa4` on `codex/desktop-v2-phase-9`.

| Field | Frozen value |
| --- | --- |
| Product | AI Video Editor Desktop V2 |
| Version | `2.0.0-rc.1` |
| Channel | `beta` |
| Shell identity | `com.aivideoeditor.desktop.v2` |
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

These are the final handoff artifact records. Hashes are SHA-256; sizes are bytes.

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `AI Video Editor Desktop V2 Setup.exe` | 3,705,595 | `6bb050897acc81c0e6a401e603338367fde88f6647b14ffa6eff4efa47835bd2` |
| `Components/aive-engine-2.0.0-rc.1.tar.gz` | 166,179,979 | `f06cc33dd86dea719fa857294741698ae69c1482bd833e38d537419546a1ebfd` |
| `Components/aive-engine-manifest.json` | 1,012,571 | `03b4b6cb4360de2cfcd542065b2f48fbc690d1a0f53628a725b564621347ef71` |
| `Components/aive-engine-manifest.sig` | 64 | `495cb1fc60bd60dcb038c688282354d17be5bbe14eb298e2ac1014254b1ddb45` |
| `Components/ffmpeg-8.1.1.tar.gz` | 172,880,769 | `ef40d7a419e7f9dbe611c83ad8ed2d0bd66958e6813f253c642bfc9398fb51c0` |
| `Components/ffmpeg-manifest.json` | 4,338 | `16057c2fdbe089087386a6c69289ed3214368e9e3c679c70b74fc70d13eec47c` |
| `Components/ffmpeg-manifest.sig` | 64 | `718f479636d192617e8a4b90c1a4b4f5b9e04698664146601881b4f5cf42c971` |
| `Catalog/offline-catalog.json` | 1,194,314 | `72117179a48b4c05e2e1eb1a352ff2a90891141780b8998e41a5570284b2c54d` |
| `Catalog/offline-catalog.sig` | 64 | `b2e157118611ced08213d53a5fab6e65ea9c76a79e57c401c06803e450f4c72b` |
| `Catalog/lecturer-release-public-key.json` | 333 | `eed23a901849f7c04304f74ceacb343bb35602307678a8b08c981e22aa237ccf` |
| `Catalog/production-catalog.template.json` | 1,194,224 | `2ffd52ff5d219d7734a4f60a69996c8c858657fe8d55eea2f7c5a19fe3467cf3` |
| `release-manifest.json` | 5,992 | `07a0d56bf4c7d3f2acf431711c8bb7628e5fdf11949cce0ddf46985516da8250` |
| `SHA256SUMS.txt` | generated in handoff | verified by `VERIFY-HANDOFF.ps1` |

The distribution ZIP beside the folder is `AI-Video-Editor-Desktop-V2-Handoff.zip`, 341,568,461 bytes, SHA-256 `b83e2b6d1a7fcbf8e4ab8aa7d804cd3467c4f0ec1975a7834b4e8061742becef`.

The signed frozen engine inventory records `bin/aive-engine.exe` as 23,990,955 bytes with SHA-256 `a3ac4ce90da8d2e65ac743ff7692aae5fe7eae85ad8a9a43640073cb7039a8cc`. The FFmpeg inventory records `bin/ffmpeg.exe` as 227,398,656 bytes with SHA-256 `09948d4cdd0650da6ff5a87577469f2a218dc2615ae379f8f734d24c49de0f73` and `bin/ffprobe.exe` as 227,193,344 bytes with SHA-256 `a6618e99bb58869ded3c6f37b53aa1a8d701c3591dbb7b5b317d47369c112be2`.

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
| NSIS | PASS — x64 installer built; no real-profile installation performed |
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
- The RC was not installed against the real Windows profile. Installer/elevation behavior is verified by NSIS output metadata and the mocked Setup Center/migration gates; component install/lifecycle is verified under redirected temporary roots.

## Final gate

**PASS — lecturer-ready release-candidate handoff.** The real frozen engine, real pinned FFmpeg component, signed portable offline catalog, thin unsigned NSIS installer, copied-tree install/lifecycle test, and read-only handoff verifier are present and passing. The final ZIP is created only after this verifier and the copied-tree test pass, and must itself be distributed with the handoff folder’s checksum list.
