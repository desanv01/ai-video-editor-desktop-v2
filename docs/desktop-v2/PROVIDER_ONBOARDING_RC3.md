# Desktop V2 rc.3 provider onboarding

Provider onboarding appears only after the required engine and FFmpeg components are active and the supervisor has authenticated readiness. The default is local/manual operation; no cloud provider is required to open a project or use the local engine.

The UI exposes fixed cards for **Mistral / Voxtral**, **OpenAI**, **DeepSeek**, and **Alibaba / Qwen**, plus only lecturer-owned password-field keys (`api_key`, `access_token`, `password`, `hf_token`, and `custom_endpoint_key`). `Save securely`, `Verify provider`, `Refresh status`, and `Clear` are distinct explicit operations. The Rust command validates provider/key identifiers, bounds values to 4096 bytes, and never returns a secret.

On Windows, values are stored under a namespaced generic Credential Manager target for the current user using `CredWriteW`/`CredReadW`/`CredDeleteW`. They are not stored in setup state, JSON configuration, operation logs, diagnostics, command-line arguments, or the catalog. Windows Credential Manager is the selected per-user protected store; DPAPI’s normal same-user/same-machine protection boundary is the documented recovery expectation. There is no plaintext fallback in the release shell.

`Save securely` verifies only Credential Manager write/read-back and truthfully leaves provider verification as `not-requested`. `Verify provider` makes a bounded request through the authenticated local engine to the provider-health endpoint. If the engine, provider configuration, or network check is unavailable it returns an explicit `not-verified` result; protected-storage read-back is never presented as proof of provider connectivity.

Verification evidence must include a redacted status response, successful secure save/read-back, an independent provider verification or explicit `not-verified` result, clear, and a search proving the secret value does not occur in state/log/diagnostic outputs. A real clean-PC test must be run under the lecturer account because Credential Manager and DPAPI are user/machine scoped.

References: [CredWrite](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credwritew), [CryptProtectData / DPAPI](https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata).
