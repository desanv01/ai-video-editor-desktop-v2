# Deterministic Phase 5 fake engine

`fake_engine.py` is a test-only loopback process. It binds `127.0.0.1` on
port `0`, emits the same bounded token-free startup handshake as the native
engine, requires the bearer token on readiness/capability/shutdown requests,
and supports deterministic failure modes through `AIVE_FAKE_ENGINE_MODE`:

`ready`, `degraded`, `wrong-protocol`, `wrong-host`, `malformed`,
`oversized`, `timeout`, and `crash`.

It is not a runtime component, is not packaged by the installer, and must not
be used as a production engine.
