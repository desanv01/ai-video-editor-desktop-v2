"""Phase 1 health/readiness and capabilities payload builders."""

from __future__ import annotations

from datetime import datetime, timezone
from os import getpid
from typing import Any

from .tools import FFmpegProbeResult
from .vector_store import VectorCapability


ENGINE_ID = "aive-engine"
ENGINE_VERSION = "2.0.0-rc.6"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check(
    state: str,
    *,
    required: bool,
    detail: str,
    remediation_codes: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "state": state,
        "required": required,
        "detail": detail,
        "remediationCodes": list(dict.fromkeys(remediation_codes)),
    }


def _semver(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.split(".")
    if len(parts) < 3 or not all(part.isdigit() for part in parts[:3]):
        return None
    return ".".join(parts[:3])


def build_health_payload(
    *,
    api_ready: bool,
    database_ready: bool,
    database_detail: str,
    vector_capability: VectorCapability | None,
    ffmpeg_probe: FFmpegProbeResult | None,
    startup_error: str | None = None,
    component_id: str = ENGINE_ID,
    component_version: str = ENGINE_VERSION,
    native_import_ready: bool = True,
) -> dict[str, Any]:
    api_check = _check(
        "healthy" if api_ready else "not-ready",
        required=True,
        detail="Authenticated loopback API is serving." if api_ready else "API startup is still in progress.",
        remediation_codes=[] if api_ready else ["API_UNHEALTHY"],
    )
    database_check = _check(
        "ready" if database_ready else "fatal",
        required=True,
        detail=database_detail,
        remediation_codes=[] if database_ready else ["DATABASE_UNAVAILABLE"],
    )

    if vector_capability is None:
        vector_check = _check(
            "not-ready",
            required=False,
            detail="Embedded vector store has not completed startup.",
            remediation_codes=["VECTOR_STORE_UNAVAILABLE"],
        )
    else:
        vector_state = "ready" if vector_capability.state == "available" else "degraded"
        vector_check = _check(
            vector_state,
            required=False,
            detail=vector_capability.detail,
            remediation_codes=list(vector_capability.remediation_codes),
        )

    if ffmpeg_probe is None:
        ffmpeg_check = _check(
            "not-ready",
            required=True,
            detail="FFmpeg component probe has not completed.",
            remediation_codes=["FFMPEG_MISSING"],
        )
    else:
        ffmpeg_check = _check(
            "ready" if ffmpeg_probe.ready else "not-ready",
            required=True,
            detail=(
                f"Activated FFmpeg component is ready ({ffmpeg_probe.version or 'unknown version'})."
                if ffmpeg_probe.ready
                else "Activated FFmpeg component failed version or encode/decode self-tests."
            ),
            remediation_codes=ffmpeg_probe.remediation_codes,
        )

    checks = {
        "api": api_check,
        "database": database_check,
        "vectorStore": vector_check,
        "ffmpeg": ffmpeg_check,
        "aiModel": _check(
            "not-configured",
            required=False,
            detail="No local AI model was requested by the Phase 4 engine profile.",
            remediation_codes=[],
        ),
        "nativeImport": _check(
            "ready" if native_import_ready else "not-ready",
            required=True,
            detail=(
                "Durable native import manifests and staging storage are ready."
                if native_import_ready
                else "Native import staging storage is not writable."
            ),
            remediation_codes=[] if native_import_ready else ["STORAGE_NOT_WRITABLE"],
        ),
    }

    available: list[str] = []
    degraded: list[str] = []
    unavailable: list[str] = []
    for capability_id, check in (
        ("api", api_check),
        ("database", database_check),
        ("vector-store", vector_check),
        ("ffmpeg", ffmpeg_check),
        ("native-import", checks["nativeImport"]),
    ):
        if check["state"] in {"healthy", "ready"}:
            available.append(capability_id)
        elif check["state"] == "degraded":
            degraded.append(capability_id)
        else:
            unavailable.append(capability_id)

    remediation = []
    for check in checks.values():
        remediation.extend(check["remediationCodes"])
    remediation = list(dict.fromkeys(remediation))

    if startup_error:
        overall = "fatal"
        fatal_error = {
            "code": "NATIVE_STARTUP_FAILED",
            "message": startup_error,
            "retryable": True,
        }
        remediation.append("RESTART_REQUIRED")
    elif not database_ready:
        overall = "fatal"
        fatal_error = {
            "code": "DATABASE_UNAVAILABLE",
            "message": database_detail,
            "retryable": True,
        }
    elif not api_ready:
        overall = "starting"
        fatal_error = None
    elif degraded or unavailable:
        overall = "degraded"
        fatal_error = None
    else:
        overall = "ready"
        fatal_error = None

    payload: dict[str, Any] = {
        "schemaVersion": "desktop.health-readiness.v1",
        "generatedAt": _now(),
        "overallState": overall,
        "process": {
            "alive": True,
            "pid": getpid(),
            "componentId": component_id,
            "componentVersion": component_version,
        },
        "checks": checks,
        "capabilities": {
            "available": available,
            "degraded": degraded,
            "unavailable": unavailable,
        },
        "remediationCodes": list(dict.fromkeys(remediation)),
    }
    if fatal_error:
        payload["fatalError"] = fatal_error
    return payload


def build_capabilities_payload(
    *,
    requested: list[str],
    vector_capability: VectorCapability | None,
    ffmpeg_probe: FFmpegProbeResult | None,
    database_ready: bool,
    component_id: str = ENGINE_ID,
    component_version: str = ENGINE_VERSION,
    native_import_ready: bool = True,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = [
        {
            "id": "api",
            "state": "available",
            "source": "component",
            "version": component_version,
            "detail": "Native loopback API with mandatory bearer-session middleware.",
        },
        {
            "id": "database",
            "state": "available" if database_ready else "unavailable",
            "source": "backend",
            "detail": "SQLite WAL database with native schema migrations."
            if database_ready
            else "SQLite database initialization failed.",
            **({} if database_ready else {"remediationCodes": ["DATABASE_UNAVAILABLE"]}),
        },
        {
            "id": "native-import",
            "state": "available" if native_import_ready else "unavailable",
            "source": "backend",
            "version": component_version,
            "detail": "Durable accepted operations with persisted phases, events, cancellation and restart recovery."
            if native_import_ready
            else "Native import staging storage is unavailable.",
            **(
                {}
                if native_import_ready
                else {"remediationCodes": ["STORAGE_NOT_WRITABLE"]}
            ),
        },
    ]
    if vector_capability:
        items.append(
            {
                "id": "vector-store",
                "state": vector_capability.state,
                "source": "backend",
                "detail": vector_capability.detail,
                "remediationCodes": list(vector_capability.remediation_codes),
            }
        )
    else:
        items.append(
            {
                "id": "vector-store",
                "state": "unavailable",
                "source": "backend",
                "detail": "Embedded vector store was not initialized.",
                "remediationCodes": ["VECTOR_STORE_UNAVAILABLE"],
            }
        )
    if ffmpeg_probe:
        ffmpeg_state = "available" if ffmpeg_probe.ready else "unavailable"
        item: dict[str, Any] = {
            "id": "ffmpeg",
            "state": ffmpeg_state,
            "source": "component",
            "detail": "FFmpeg and FFprobe are discovered from the activated component root.",
            "remediationCodes": list(ffmpeg_probe.remediation_codes),
        }
        version = _semver(ffmpeg_probe.version)
        if version:
            item["version"] = version
        items.append(item)
    else:
        items.append(
            {
                "id": "ffmpeg",
                "state": "unavailable",
                "source": "component",
                "detail": "FFmpeg component probe has not completed.",
                "remediationCodes": ["FFMPEG_MISSING"],
            }
        )
    return {
        "schemaVersion": "desktop.capabilities.v1",
        "componentId": component_id,
        "componentVersion": component_version,
        "generatedAt": _now(),
        "requested": list(dict.fromkeys(requested)),
        "items": items,
    }
