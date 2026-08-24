# Desktop V2 rc.3 Windows validation evidence

The repository automation distinguishes proof that can run in CI/local development from proof that requires a genuine clean Windows 10/11 machine. `Invoke-CleanWindowsValidation.ps1` records OS/build/architecture, installer hash, WebView2 detection, and the media/engine smoke result. It does not overwrite the rc.2 handoff and does not silently install missing prerequisites.

CI/local proof includes Rust tests, TypeScript build/tests, signed-catalog fixture intake, component corruption/hash/signature/traversal/interruption/lock/rollback tests, migration safety, WebView2 policy checks, SBOM generation, and static installer/ACL checks.

External clean-PC proof must be run under a fresh Windows 10/11 x64 user profile with the actual installer and new rc.3 handoff. Record installer exit code, per-machine ACLs, first launch, bundled catalog selection, required engine + FFmpeg activation/readiness, project/source import, FFmpeg probe/encode/decode/export using `SMOKE\synthetic-source.mp4`, restart readiness, repair, and uninstall-plan preservation. Credential Manager provider tests must be run under the lecturer account because the store is user/machine scoped.

The clean-PC evidence bundle must clearly label `validationClass` as `local-or-ci-host` or `external-clean-pc`. A local smoke result cannot be presented as clean-PC installation proof.
