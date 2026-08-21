"""Human-readable, structured error payloads shared by touched API routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizedError:
    code: str
    message: str
    remediation: str
    retryable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
            "retryable": self.retryable,
        }


def normalize_error(error: object, *, default_code: str = "UNKNOWN_ERROR") -> NormalizedError:
    text = str(error or "").strip()
    lower = text.lower()
    if "not configured" in lower or "api key" in lower:
        return NormalizedError(
            "PROVIDER_NOT_CONFIGURED",
            "The selected AI provider is not configured.",
            "Open Settings > AI providers, configure a local model or API provider, then retry. Manual editing remains available.",
            True,
        )
    if "not found" in lower or "missing" in lower:
        return NormalizedError(
            "SOURCE_MISSING",
            "A required source or generated file is missing.",
            "Reopen the project, repair the source path, or import the source again.",
            True,
        )
    if "disk" in lower or "space" in lower:
        return NormalizedError(
            "STORAGE_UNAVAILABLE",
            "There is not enough available storage for this operation.",
            "Free disk space or choose a different application storage location, then retry.",
            True,
        )
    if "cancel" in lower:
        return NormalizedError(
            "CANCELLED",
            "The operation was cancelled.",
            "Resume or retry when you are ready.",
            True,
        )
    if "timeout" in lower or "timed out" in lower or "connection" in lower:
        return NormalizedError(
            "BACKEND_UNAVAILABLE",
            "The local backend did not respond in time.",
            "Check that the backend or desktop engine is running, then retry. Your project data is kept.",
            True,
        )
    return NormalizedError(
        default_code,
        text[:500] if text else "The operation could not be completed.",
        "Review the diagnostics and retry the operation. Existing source files and review decisions are preserved.",
        True,
    )


def error_payload(error: object, *, default_code: str = "UNKNOWN_ERROR") -> dict[str, Any]:
    return normalize_error(error, default_code=default_code).as_dict()
