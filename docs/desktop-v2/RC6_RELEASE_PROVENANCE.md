# Desktop V2 RC.6 release provenance

RC.6 is `2.0.0-rc.6` on the beta channel. Its release directory and archive must be newly named with `rc6`; the provenance generator rejects RC.4/RC.5 paths and refuses to overwrite an existing manifest, SBOM, license/source record, or checksum catalog.

The Windows layout is fixed: the per-machine shell is under `%ProgramFiles%\AI Video Editor Desktop V2\Shell`, machine components and activation state are under `%ProgramData%\AI Video Editor`, disposable/user settings are under `%LocalAppData%\AI Video Editor`, and projects/exports/models are under `%USERPROFILE%\Documents\AI Video Editor`. The generated Tauri NSIS section owns one Desktop shortcut and one Start Menu shortcut. The hook creates no second shortcut or shortcut checkbox.

The default uninstall removes the shell, machine runtime, signed catalog cache, staging, and disposable per-user state. It preserves settings, uploads, models, databases, projects, exports, and Windows Credential Manager entries. Full wipe is a separate Rust command requiring the exact phrase `REMOVE ALL AI VIDEO EDITOR USER DATA`; it is limited to resolved allowlisted paths and the compiled product-owned Credential Manager target list. It never enumerates the credential vault. Locked Program Files remnants use non-recursive `/REBOOTOK` cleanup only after the install path exactly matches the canonical x64 shell path.

FFmpeg is pinned to 8.1.1. The reviewed Gyan asset URL, archive SHA-256, FFmpeg source commit, and GPL-3.0-only status are frozen in `contracts/desktop-v2/ffmpeg-8.1.1.provenance.json`. Production packaging requires the caller-supplied local archive, exact hash, reviewed metadata, real probes, component inventory, and a caller-supplied external Ed25519 seed. Test-fixture signatures remain test-only.

Release order:

1. Package the engine and FFmpeg 8.1.1 into a new RC.6 staging root with `package_native_engine.py` and `package_ffmpeg_component.py`.
2. Generate a fresh catalog with `generate_signed_catalog.py`, using the same external Ed25519 seed and key ID as the component manifests.
3. Build the NSIS/MSI shell into a fresh RC.6 output. Do not copy an RC.4/RC.5 installer or signed catalog forward.
4. Let `assemble_rc6_handoff.py` stage the installer, signed manifests, detached signatures, archives, catalog, public trust record, evidence, and read-only verifiers into a new timestamped direct child of the ignored `output` directory. It creates through a uniquely named partial directory, then renames only after verification and never overwrites a prior RC output.
5. Run `generate_rc6_release_provenance.py`; optionally pass the external seed path only for an existence/location check. The script deliberately never opens, hashes, prints, copies, or serializes the seed path.
6. Run `verify_handoff_signatures.py`, `Verify-RC6Release.ps1`, the SBOM/checksum checks, installer tests, and external clean-Windows validation.
7. Run `Sign-DesktopV2Release.ps1 -RequireSigning` only when an externally supplied OV/EV certificate and RFC3161 timestamp URL are available. Until its valid evidence exists, Authenticode is `not-claimed`; Ed25519 component/catalog signatures are not Authenticode.

No production signing seed was found in the standard external release-secret locations during this source pass. That is a release blocker for freshly signed production manifests/catalog, not permission to reuse a test key or old signed catalog. Large binaries, installer outputs, seeds, certificates, user data, Docker state, and project media remain outside Git.
