# Deterministic Phase 5 fake engine

`fake_engine.py` is a test-only loopback process. It binds `127.0.0.1` on
port `0`, sends the same bounded HMAC-authenticated v2 message to a
supervisor-owned loopback control listener as the native engine, treats
stdout/stderr as diagnostics only, requires the bearer token on
readiness/capability/shutdown requests, and supports deterministic failure
modes through `AIVE_FAKE_ENGINE_MODE`:

`ready`, `degraded`, `wrong-protocol`, `wrong-host`, `wrong-hmac`,
`wrong-pid`, `wrong-session`, `wrong-nonce`, `wrong-component`,
`wrong-version`, `stdout-close-before-control`, `malformed`, `oversized`,
`timeout`, and `crash`.

It is not a runtime component, is not packaged by the installer, and must not
be used as a production engine.
