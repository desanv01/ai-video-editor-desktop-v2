# AI Provider Configuration

`PROVIDERS.csv` and `CONFIGURATION_KEYS.csv` enumerate active, optional, and placeholder provider paths. The registry supports hosted ASR/chat/embedding/vision adapters plus local whisper.cpp. Agent model defaults are configuration values, not guaranteed runtime providers: persisted application settings can override them.

ASR routing genuinely implements API, local, and hybrid behavior in `backend/app/services/transcription.py`, including long-audio chunking and provider-specific limits. General chat/embedding/vision mode abstraction is PARTIALLY_IMPLEMENTED: `LLMService` selects configured API/default providers, while local non-ASR adapters are placeholders. Automatic fallback is strongest in transcription and agent-level deterministic fallbacks, not a universal provider failover matrix.

API keys are accepted through settings and can be stored encrypted with Fernet only when `APP_SETTINGS_SECRET_KEY` is configured (`backend/app/services/app_settings.py:210-241`). UI masking is not equivalent to at-rest encryption. Timeouts/retries are service-specific; Qdrant ingest retries once, render jobs use watchdogs, and provider rate-limit accounting is not centrally persisted. No secret values are reproduced in this pack.
