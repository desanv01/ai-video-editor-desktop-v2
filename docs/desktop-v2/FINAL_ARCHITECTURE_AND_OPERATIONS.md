# Desktop V2 final architecture and operations

## Runtime topology

```text
Windows lecturer machine
  ├─ Program Files\AI Video Editor Desktop V2
  │    └─ thin Tauri/NSIS shell, Setup Center, migration hooks
  ├─ ProgramData\AI Video Editor\
  │    ├─ Catalog\ and persisted offline-root import record
  │    ├─ Components\<component-id>\<version>\
  │    ├─ Downloads\Staging\
  │    └─ Activation\Journal\ and active-version pointers
  └─ user data and projects remain outside the installer/component perimeter
```

The shell is a stable per-machine identity (`com.aivideoeditor.desktop.v2`) and does not carry heavy runtime resources. The component manager owns signed archive intake, bounded download/extraction, exact inventory/hash verification, self-test, staging, atomic activation, repair, rollback metadata, and data-preserving uninstall behavior. The supervisor resolves only an activated verified engine, uses a dynamic loopback port and generated bearer token, requires the engine handshake/readiness contract, and supports graceful shutdown/restart.

## Release identity and compatibility

The frozen RC is version `2.0.0-rc.1` on the `beta` channel, built from Phase 8 commit `21298c927b745707b1bc02040a51f403743d4fa4`. It targets Windows 10/11 x86_64 with WebView2 and at least 2 GiB free space. No system Python, Node.js, Docker, or FFmpeg is required by the lecturer release. The required signed components are:

- `aive-engine` version `2.0.0-rc.1`, PyInstaller Windows x64 onedir;
- `ffmpeg` version `8.1.1`, containing the real Gyan.dev Windows x64 `ffmpeg.exe` and `ffprobe.exe`.

## Trust model

The shell contains the only accepted lecturer-release trust root: Ed25519 key `aive-desktop-v2-lecturer-2026`, public-key SHA-256 `471e7b08109f8723400afea495f63d1d93753e4757386e31560a7cbee6bd2a2d`. Catalog-supplied keys are not trusted. A catalog signature is checked first; each embedded component manifest is then checked by the component manager; the artifact size, SHA-256, exact archive inventory, executable self-test, and activation metadata are checked before use.

The private seed is an operational release secret, restricted outside the repository. Preserve it beside its protected release-secrets directory according to the private-key preservation guidance; do not place it in source, logs, handoff folders, ZIPs, CI artifacts, or shell history. Rotate the trust root only through a new reviewed shell release and a separately documented key-preservation event.

The Windows installer is Authenticode-unsigned because no commercial certificate was available. The handoff states this plainly and expects SmartScreen’s unknown-publisher warning. Ed25519 component/catalog signatures are real and independently verifiable with the public key included in `Catalog/lecturer-release-public-key.json`.

## Portable offline catalog operations

The handoff catalog is signed with portable references such as `offline:Components/ffmpeg-8.1.1.tar.gz`; no signed object is bound to the build machine’s absolute path. Setup Center’s native file picker passes the selected catalog path to the shell. The shell canonicalizes the catalog file and uses its parent directory as the imported root. The manager persists only a machine-scoped record of that imported root for subsequent operations, then enforces:

- `offline:` scheme;
- `Components/` prefix;
- safe relative path segments with no drive letters or traversal;
- canonical candidate under the canonical imported root;
- regular, non-reparse local artifact;
- signed artifact size/hash and exact manifest inventory.

This is why a lecturer may copy the entire handoff folder to a different drive or machine. `Catalog` and `Components` must remain siblings; after moving the folder, import the catalog again from its new location.

## Operational flows

### First install

Run the small NSIS installer with UAC approval. It installs the shell in Program Files, creates Start-menu and desktop shortcuts, and leaves heavy resources out of the base state. The initial shell is intentionally a zero-component state. Setup Center then imports the offline catalog, shows both required components, computes disk requirements, and installs them through the real component manager.

### Start and readiness

After activation, the Phase 5 supervisor launches the frozen engine only from the verified active component path. It supplies redirected data/component roots, selects a dynamic loopback port, and keeps the bearer token out of command-line arguments/logs. `/live` is unauthenticated liveness; `/readiness` and engine-control operations require the generated token. Startup is accepted only after the authenticated handshake and readiness contract match the frozen release identity.

### Updates and rollback

A future signed catalog may provide a newer version. The manager downloads into staging, verifies before activation, retains the current active version, writes journal checkpoints, and can repair or roll back after a failed activation. A rollback needs a previous signed version; the RC handoff contains one version only and therefore documents this limitation.

### Repair and recovery

Repair reuses the catalog/manifest trust checks and rebuilds a verified staged copy. Interrupted downloads and activation journals are machine-readable and resumable/cleanable. A corrupt active version is reported as a structured repair condition; the shell does not silently fall back to an unverified binary.

### Uninstall and migration

The default uninstall plan removes the shell while preserving user projects, exports, databases, uploads, and other valuable data. Migration scans and cleanup plans are explicit, transactional, and redact secret-like values. Destructive full wipe requires a separate confirmation path.

## Real release evidence

The final handoff contains exact checksums in `SHA256SUMS.txt`. The most material files are:

| File | Size | SHA-256 |
| --- | ---: | --- |
| `AI Video Editor Desktop V2 Setup.exe` | 3,705,595 | `6bb050897acc81c0e6a401e603338367fde88f6647b14ffa6eff4efa47835bd2` |
| `Components/aive-engine-2.0.0-rc.1.tar.gz` | 166,179,979 | `f06cc33dd86dea719fa857294741698ae69c1482bd833e38d537419546a1ebfd` |
| `Components/ffmpeg-8.1.1.tar.gz` | 172,880,769 | `ef40d7a419e7f9dbe611c83ad8ed2d0bd66958e6813f253c642bfc9398fb51c0` |
| `Catalog/offline-catalog.json` | 1,194,314 | `72117179a48b4c05e2e1eb1a352ff2a90891141780b8998e41a5570284b2c54d` |

The distribution ZIP is `AI-Video-Editor-Desktop-V2-Handoff.zip`, 341,568,461 bytes, SHA-256 `b83e2b6d1a7fcbf8e4ab8aa7d804cd3467c4f0ec1975a7834b4e8061742becef`.

The FFmpeg archive is pinned to Gyan.dev FFmpeg 8.1.1 full build, source commit `FFmpeg/FFmpeg@239f2c733d`, GPL-3.0-only, with source page and notices recorded in `LICENSES-AND-SOURCES.md`. The local installed Windows build was provenance-checked; system PATH FFmpeg was not used.

The copied-handoff test uses only temporary redirected roots and proves catalog signature verification, portable artifact resolution, real archive download/extraction, exact verification, activation of both components, frozen engine self-test, FFmpeg version/encode/probe/decode, authenticated readiness, and graceful shutdown. It does not install the RC into the real Windows profile or alter existing Docker containers.

## Verification and distribution procedure

1. Keep the handoff folder complete and preserve the relative layout.
2. Run the read-only `VERIFY-HANDOFF.ps1`. It fails on missing or extra critical files, checksum mismatch, public-key fingerprint mismatch, invalid Ed25519 signatures, non-portable/escaping artifact references, creator-machine paths in release metadata, and private-key material. It never executes the installer or components.
3. Confirm the copied-tree integration test and regression gates are recorded in `PHASE_9_RELEASE_HANDOFF.md`.
4. Only after those checks pass, create the ZIP beside the handoff folder. Do not add the private seed, build caches, `target`, `dist`, `node_modules`, models, databases, media beyond the tiny synthetic smoke source, environment files, or user data.
5. Distribute the folder and ZIP together with the SHA-256 list. A recipient should verify the folder after extraction and before running Setup.

## Final gate and limitations

Final gate: **PASS** for the lecturer-ready release-candidate handoff. The actual Windows installer is unsigned, so SmartScreen’s warning remains an expected limitation. Provider-backed AI features, Docker-backed services, and a second signed component version for downgrade testing are outside the offline RC scope. The local SQLite/vector readiness contract may truthfully report degraded vector capability while remaining usable for the documented smoke workflow.
