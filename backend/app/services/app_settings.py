"""Persistent AI settings service.

This module keeps the desktop-managed settings separate from process
environment defaults. API keys are write-only: responses only expose whether a
key is configured and a masked display value.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from hashlib import sha256
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import AppAISettings
from models.schemas import (
    AICapabilitySettings,
    APIKeyStatus,
    AppSettingsResponse,
    AppSettingsUpdateRequest,
)
from providers.interfaces import ProviderKind
from providers.processing_modes import (
    DEFAULT_HYBRID_FALLBACK_ORDER,
    ProcessingMode,
    parse_processing_mode,
)

DEFAULT_SETTINGS_ID = "default"

API_KEY_ENV_VARS = {
    "mistral": "MISTRAL_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

API_KEY_SETTINGS_FIELDS = {
    "mistral": "MISTRAL_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _mask_secret(value: str, fallback_last_four: Optional[str] = None) -> Optional[str]:
    last_four = (value[-4:] if value else fallback_last_four) or ""
    return f"{'*' * 8}{last_four}" if last_four else None


def _validate_provider_kind(kind: str) -> ProviderKind:
    try:
        return ProviderKind(kind)
    except ValueError as exc:
        valid = ", ".join(item.value for item in ProviderKind)
        raise HTTPException(422, f"Unknown AI capability '{kind}'. Expected one of: {valid}") from exc


def _validate_mode(value: str, field_name: str) -> str:
    try:
        return parse_processing_mode(value, field_name=field_name).value
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _validate_mode_order(values: list[str], field_name: str) -> list[str]:
    return [_validate_mode(value, field_name) for value in values]


def _default_capabilities() -> dict[str, dict[str, Any]]:
    return {
        ProviderKind.TRANSCRIPTION.value: {
            "mode": settings.AI_TRANSCRIPTION_MODE,
            "api_provider_id": settings.ASR_PROVIDER.lower(),
            "local_provider_id": "whisper-cpp",
            "fallback_enabled": settings.AI_PROVIDER_FALLBACK_ENABLED,
            "hybrid_fallback_order": [
                mode.value for mode in DEFAULT_HYBRID_FALLBACK_ORDER[ProviderKind.TRANSCRIPTION]
            ],
        },
        ProviderKind.CHAT.value: {
            "mode": settings.AI_CHAT_MODE,
            "api_provider_id": "deepseek-chat",
            "local_provider_id": None,
            "fallback_enabled": settings.AI_PROVIDER_FALLBACK_ENABLED,
            "hybrid_fallback_order": [
                mode.value for mode in DEFAULT_HYBRID_FALLBACK_ORDER[ProviderKind.CHAT]
            ],
        },
        ProviderKind.EMBEDDING.value: {
            "mode": settings.AI_EMBEDDING_MODE,
            "api_provider_id": "openai-embeddings",
            "local_provider_id": None,
            "fallback_enabled": settings.AI_PROVIDER_FALLBACK_ENABLED,
            "hybrid_fallback_order": [
                mode.value for mode in DEFAULT_HYBRID_FALLBACK_ORDER[ProviderKind.EMBEDDING]
            ],
        },
        ProviderKind.VISION.value: {
            "mode": settings.AI_VISION_MODE,
            "api_provider_id": "vision-unconfigured",
            "local_provider_id": None,
            "fallback_enabled": settings.AI_PROVIDER_FALLBACK_ENABLED,
            "hybrid_fallback_order": [
                mode.value for mode in DEFAULT_HYBRID_FALLBACK_ORDER[ProviderKind.VISION]
            ],
        },
        ProviderKind.LOCAL_RUNTIME.value: {
            "mode": settings.AI_LOCAL_RUNTIME_MODE,
            "api_provider_id": None,
            "local_provider_id": "local-runtime-unconfigured",
            "fallback_enabled": settings.AI_PROVIDER_FALLBACK_ENABLED,
            "hybrid_fallback_order": [
                mode.value for mode in DEFAULT_HYBRID_FALLBACK_ORDER[ProviderKind.LOCAL_RUNTIME]
            ],
        },
    }


def _default_api_keys() -> dict[str, dict[str, Any]]:
    return {
        provider: {
            "source": "env",
            "env_var": env_var,
            "updated_at": None,
        }
        for provider, env_var in API_KEY_ENV_VARS.items()
    }


def _default_local_model_paths() -> dict[str, Optional[str]]:
    return {
        ProviderKind.TRANSCRIPTION.value: (
            settings.WHISPER_CPP_MODEL_PATH
            or settings.LOCAL_TRANSCRIPTION_MODEL_PATH
            or None
        ),
        ProviderKind.CHAT.value: settings.LOCAL_CHAT_MODEL_PATH or None,
        ProviderKind.EMBEDDING.value: settings.LOCAL_EMBEDDING_MODEL_PATH or None,
        ProviderKind.VISION.value: settings.LOCAL_VISION_MODEL_PATH or None,
        ProviderKind.LOCAL_RUNTIME.value: settings.LOCAL_RUNTIME_PATH or None,
    }


def _encrypt_secret(secret: str) -> str:
    if not settings.APP_SETTINGS_SECRET_KEY:
        raise HTTPException(
            422,
            "APP_SETTINGS_SECRET_KEY must be configured before storing API keys in the database.",
        )

    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise HTTPException(
            500,
            "cryptography is required to store encrypted API keys. Install backend requirements.",
        ) from exc

    try:
        fernet = Fernet(settings.APP_SETTINGS_SECRET_KEY.encode("utf-8"))
    except Exception as exc:
        raise HTTPException(500, "APP_SETTINGS_SECRET_KEY is not a valid Fernet key.") from exc

    return fernet.encrypt(secret.encode("utf-8")).decode("utf-8")


def _decrypt_secret(encrypted_secret: str) -> Optional[str]:
    if not encrypted_secret or not settings.APP_SETTINGS_SECRET_KEY:
        return None

    try:
        from cryptography.fernet import Fernet

        fernet = Fernet(settings.APP_SETTINGS_SECRET_KEY.encode("utf-8"))
        return fernet.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


async def get_or_create_ai_settings(db: AsyncSession) -> AppAISettings:
    record = await db.get(AppAISettings, DEFAULT_SETTINGS_ID)
    if record:
        return record

    record = AppAISettings(
        id=DEFAULT_SETTINGS_ID,
        preferred_processing_mode=settings.AI_PROCESSING_MODE,
        fallback_enabled=settings.AI_PROVIDER_FALLBACK_ENABLED,
        capabilities_json=_default_capabilities(),
        api_keys_json=_default_api_keys(),
        local_model_paths_json=_default_local_model_paths(),
        domain_terms_json=settings.domain_terms_list,
    )
    db.add(record)
    await db.flush()
    return record


def apply_settings_record(record: AppAISettings) -> None:
    """Overlay persisted settings onto the existing env-backed settings object."""
    settings.AI_PROCESSING_MODE = record.preferred_processing_mode
    settings.AI_PROVIDER_FALLBACK_ENABLED = bool(record.fallback_enabled)
    settings.DOMAIN_TERMS = json.dumps(record.domain_terms_json or [])

    capabilities = record.capabilities_json or {}
    mode_fields = {
        ProviderKind.TRANSCRIPTION.value: "AI_TRANSCRIPTION_MODE",
        ProviderKind.CHAT.value: "AI_CHAT_MODE",
        ProviderKind.EMBEDDING.value: "AI_EMBEDDING_MODE",
        ProviderKind.VISION.value: "AI_VISION_MODE",
        ProviderKind.LOCAL_RUNTIME.value: "AI_LOCAL_RUNTIME_MODE",
    }
    for kind, field_name in mode_fields.items():
        capability = capabilities.get(kind) or {}
        mode = capability.get("mode")
        if mode:
            setattr(settings, field_name, mode)

    transcription_provider = (capabilities.get(ProviderKind.TRANSCRIPTION.value) or {}).get("api_provider_id")
    if transcription_provider:
        settings.ASR_PROVIDER = transcription_provider

    local_paths = record.local_model_paths_json or {}
    settings.LOCAL_TRANSCRIPTION_MODEL_PATH = local_paths.get(ProviderKind.TRANSCRIPTION.value) or ""
    settings.WHISPER_CPP_MODEL_PATH = settings.LOCAL_TRANSCRIPTION_MODEL_PATH
    settings.LOCAL_CHAT_MODEL_PATH = local_paths.get(ProviderKind.CHAT.value) or ""
    settings.LOCAL_EMBEDDING_MODEL_PATH = local_paths.get(ProviderKind.EMBEDDING.value) or ""
    settings.LOCAL_VISION_MODEL_PATH = local_paths.get(ProviderKind.VISION.value) or ""
    settings.LOCAL_RUNTIME_PATH = local_paths.get(ProviderKind.LOCAL_RUNTIME.value) or ""

    for provider, entry in (record.api_keys_json or {}).items():
        settings_field = API_KEY_SETTINGS_FIELDS.get(provider)
        if not settings_field:
            continue

        if entry.get("source") == "encrypted_db":
            decrypted = _decrypt_secret(entry.get("encrypted_value", ""))
            if decrypted:
                setattr(settings, settings_field, decrypted)
        elif entry.get("source") == "env" and entry.get("env_var"):
            env_value = os.getenv(entry["env_var"])
            if env_value:
                setattr(settings, settings_field, env_value)


def reset_provider_registry_cache() -> None:
    try:
        from providers.defaults import reset_provider_registry

        reset_provider_registry()
    except Exception:
        pass


async def load_and_apply_persisted_ai_settings(db: AsyncSession) -> AppAISettings:
    record = await get_or_create_ai_settings(db)
    apply_settings_record(record)
    reset_provider_registry_cache()
    return record


def settings_response(record: AppAISettings) -> AppSettingsResponse:
    capabilities = {
        kind: AICapabilitySettings(**payload)
        for kind, payload in (record.capabilities_json or {}).items()
    }

    api_keys = {
        provider: _api_key_status(provider, payload)
        for provider, payload in (record.api_keys_json or {}).items()
    }

    return AppSettingsResponse(
        asr_provider=settings.ASR_PROVIDER,
        agent2_model=settings.AGENT2_MODEL,
        agent3_model=settings.AGENT3_MODEL,
        agent5_model=settings.AGENT5_MODEL,
        embedding_model=settings.EMBEDDING_MODEL,
        domain_terms=record.domain_terms_json or [],
        preferred_processing_mode=record.preferred_processing_mode,
        fallback_enabled=record.fallback_enabled,
        capabilities=capabilities,
        api_keys=api_keys,
        local_model_paths=record.local_model_paths_json or {},
    )


def _api_key_status(provider: str, entry: dict[str, Any]) -> APIKeyStatus:
    source = entry.get("source", "env")
    env_var = entry.get("env_var") or API_KEY_ENV_VARS.get(provider)
    env_value = os.getenv(env_var or "")

    if source == "encrypted_db":
        has_key = bool(entry.get("encrypted_value"))
        display_value = _mask_secret("", entry.get("last_four"))
    else:
        has_key = bool(env_value)
        display_value = _mask_secret(env_value)

    return APIKeyStatus(
        provider=provider,
        source=source,
        env_var=env_var,
        has_key=has_key,
        display_value=display_value,
        updated_at=entry.get("updated_at"),
    )


async def update_ai_settings(
    db: AsyncSession,
    request: AppSettingsUpdateRequest,
) -> AppSettingsResponse:
    record = await get_or_create_ai_settings(db)

    if request.preferred_processing_mode is not None:
        record.preferred_processing_mode = _validate_mode(
            request.preferred_processing_mode,
            "preferred_processing_mode",
        )

    if request.fallback_enabled is not None:
        record.fallback_enabled = request.fallback_enabled

    if request.capabilities:
        capabilities = dict(record.capabilities_json or _default_capabilities())
        for kind, update in request.capabilities.items():
            provider_kind = _validate_provider_kind(kind)
            existing = dict(capabilities.get(kind) or {})
            update_data = update.model_dump(exclude_unset=True)

            if "mode" in update_data and update_data["mode"] is not None:
                update_data["mode"] = _validate_mode(update_data["mode"], f"capabilities.{kind}.mode")

            if "hybrid_fallback_order" in update_data and update_data["hybrid_fallback_order"] is not None:
                update_data["hybrid_fallback_order"] = _validate_mode_order(
                    update_data["hybrid_fallback_order"],
                    f"capabilities.{kind}.hybrid_fallback_order",
                )

            existing.update(update_data)
            existing.setdefault("mode", ProcessingMode.HYBRID.value)
            existing.setdefault("fallback_enabled", record.fallback_enabled)
            existing.setdefault(
                "hybrid_fallback_order",
                [mode.value for mode in DEFAULT_HYBRID_FALLBACK_ORDER[provider_kind]],
            )
            capabilities[kind] = existing
        record.capabilities_json = capabilities

    if request.local_model_paths:
        local_paths = dict(record.local_model_paths_json or _default_local_model_paths())
        for kind, path in request.local_model_paths.items():
            _validate_provider_kind(kind)
            local_paths[kind] = path.strip() if isinstance(path, str) and path.strip() else None
        record.local_model_paths_json = local_paths

    if request.api_keys:
        api_keys = dict(record.api_keys_json or _default_api_keys())
        for provider, update in request.api_keys.items():
            if provider not in API_KEY_ENV_VARS:
                valid = ", ".join(sorted(API_KEY_ENV_VARS))
                raise HTTPException(422, f"Unknown API key provider '{provider}'. Expected one of: {valid}")

            existing = dict(api_keys.get(provider) or {})
            if update.clear:
                api_keys[provider] = {
                    "source": "env",
                    "env_var": update.env_var or API_KEY_ENV_VARS[provider],
                    "updated_at": _utc_now(),
                }
                continue

            if update.use_env or update.env_var:
                api_keys[provider] = {
                    "source": "env",
                    "env_var": update.env_var or API_KEY_ENV_VARS[provider],
                    "updated_at": _utc_now(),
                }
                continue

            if update.api_key is not None:
                api_key = update.api_key.strip()
                if not api_key:
                    api_keys[provider] = {
                        "source": "env",
                        "env_var": API_KEY_ENV_VARS[provider],
                        "updated_at": _utc_now(),
                    }
                else:
                    api_keys[provider] = {
                        "source": "encrypted_db",
                        "encrypted_value": _encrypt_secret(api_key),
                        "fingerprint": sha256(api_key.encode("utf-8")).hexdigest()[:12],
                        "last_four": api_key[-4:],
                        "updated_at": _utc_now(),
                    }
                continue

            api_keys[provider] = existing
        record.api_keys_json = api_keys

    if request.domain_terms is not None:
        record.domain_terms_json = request.domain_terms[:100]

    record.updated_at = datetime.utcnow()
    await db.flush()
    apply_settings_record(record)
    reset_provider_registry_cache()
    return settings_response(record)
