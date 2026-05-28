"""
Initial project source synchronization helpers.

This is intentionally metadata-first. Waveform matching can later feed the same
metadata fields and confidence model without changing project asset storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from db.models import ProjectAsset, ProjectAssetSyncRole


SYNC_METADATA_KEY = "source_sync"
SYNCABLE_ROLES = {
    ProjectAssetSyncRole.PRIMARY_TIMELINE,
    ProjectAssetSyncRole.SCREEN_REFERENCE,
    ProjectAssetSyncRole.CAMERA_OVERLAY,
    ProjectAssetSyncRole.AUDIO_MASTER,
    ProjectAssetSyncRole.AUDIO_REFERENCE,
}

TIMESTAMP_KEYS = (
    "recording_started_at",
    "recording_start_time",
    "capture_started_at",
    "capture_start_time",
    "media_created_at",
    "creation_time",
)

TIME_OFFSET_KEYS = (
    "start_timecode_seconds",
    "media_start_time_seconds",
    "recording_start_seconds",
    "capture_start_seconds",
)


@dataclass(frozen=True)
class SyncAnchor:
    value_seconds: float
    key: str
    method: str


@dataclass(frozen=True)
class SyncRecommendation:
    asset_id: str
    recommended_offset_seconds: float
    confidence: float
    method: str
    reason: str
    metadata_anchor: dict[str, Any] | None = None
    needs_user_review: bool = True


def is_syncable_asset(asset: ProjectAsset) -> bool:
    sync_role = asset.sync_role
    if isinstance(sync_role, str):
        return sync_role in {role.value for role in SYNCABLE_ROLES}
    return sync_role in SYNCABLE_ROLES


def choose_reference_asset(assets: Iterable[ProjectAsset]) -> ProjectAsset | None:
    syncable_assets = [asset for asset in assets if is_syncable_asset(asset)]
    if not syncable_assets:
        return None

    role_priority = {
        ProjectAssetSyncRole.PRIMARY_TIMELINE: 0,
        ProjectAssetSyncRole.AUDIO_MASTER: 1,
        ProjectAssetSyncRole.SCREEN_REFERENCE: 2,
        ProjectAssetSyncRole.CAMERA_OVERLAY: 3,
        ProjectAssetSyncRole.AUDIO_REFERENCE: 4,
    }

    return sorted(
        syncable_assets,
        key=lambda asset: (
            0 if asset.is_primary else 1,
            role_priority.get(_sync_role_enum(asset.sync_role), 99),
            asset.created_at or datetime.min,
        ),
    )[0]


def extract_user_sync_offset(metadata: dict[str, Any] | None) -> float | None:
    candidates = _metadata_candidates(metadata)
    for candidate in candidates:
        for key in ("sync_offset_seconds", "initial_sync_offset_seconds", "manual_sync_offset_seconds"):
            value = candidate.get(key)
            parsed = _parse_float(value)
            if parsed is not None:
                return parsed
    return None


def recommend_sync_offsets(assets: Iterable[ProjectAsset]) -> tuple[ProjectAsset | None, list[SyncRecommendation]]:
    syncable_assets = [asset for asset in assets if is_syncable_asset(asset)]
    reference = choose_reference_asset(syncable_assets)
    if reference is None:
        return None, []

    reference_anchor = extract_sync_anchor(reference.metadata_json)
    recommendations = []
    for asset in syncable_assets:
        recommendation = _recommend_asset_offset(asset, reference, reference_anchor)
        recommendations.append(recommendation)

    return reference, recommendations


def build_sync_metadata(
    recommendation: SyncRecommendation,
    *,
    applied_by: str,
    user_adjusted: bool = False,
    note: str | None = None,
) -> dict[str, Any]:
    metadata = {
        "method": recommendation.method,
        "confidence": recommendation.confidence,
        "recommended_offset_seconds": recommendation.recommended_offset_seconds,
        "applied_offset_seconds": recommendation.recommended_offset_seconds,
        "needs_user_review": recommendation.needs_user_review,
        "user_adjusted": user_adjusted,
        "applied_by": applied_by,
        "waveform_sync_ready": True,
        "reason": recommendation.reason,
    }
    if recommendation.metadata_anchor:
        metadata["metadata_anchor"] = recommendation.metadata_anchor
    if note:
        metadata["note"] = note
    return metadata


def merge_sync_metadata(asset: ProjectAsset, sync_metadata: dict[str, Any]) -> None:
    metadata_json = dict(asset.metadata_json or {})
    metadata_json[SYNC_METADATA_KEY] = sync_metadata
    asset.metadata_json = metadata_json


def extract_sync_anchor(metadata: dict[str, Any] | None) -> SyncAnchor | None:
    for candidate in _metadata_candidates(metadata):
        for key in TIMESTAMP_KEYS:
            parsed = _parse_timestamp_seconds(candidate.get(key))
            if parsed is not None:
                return SyncAnchor(parsed, key, "metadata_timestamp")

        for key in TIME_OFFSET_KEYS:
            parsed = _parse_float(candidate.get(key))
            if parsed is not None:
                return SyncAnchor(parsed, key, "metadata_time_offset")

    return None


def _recommend_asset_offset(
    asset: ProjectAsset,
    reference: ProjectAsset,
    reference_anchor: SyncAnchor | None,
) -> SyncRecommendation:
    asset_id = str(asset.id)
    if asset.id == reference.id:
        return SyncRecommendation(
            asset_id=asset_id,
            recommended_offset_seconds=0.0,
            confidence=1.0,
            method="reference_asset",
            reason="Reference source anchors the project timeline.",
            metadata_anchor=_anchor_payload(reference_anchor),
            needs_user_review=False,
        )

    asset_anchor = extract_sync_anchor(asset.metadata_json)
    if reference_anchor and asset_anchor and reference_anchor.method == asset_anchor.method:
        offset = round(asset_anchor.value_seconds - reference_anchor.value_seconds, 3)
        return SyncRecommendation(
            asset_id=asset_id,
            recommended_offset_seconds=offset,
            confidence=0.75,
            method=asset_anchor.method,
            reason=f"Estimated from {asset_anchor.key} relative to reference {reference_anchor.key}.",
            metadata_anchor={
                "asset": _anchor_payload(asset_anchor),
                "reference": _anchor_payload(reference_anchor),
            },
            needs_user_review=True,
        )

    stored_sync = (asset.metadata_json or {}).get(SYNC_METADATA_KEY)
    if isinstance(stored_sync, dict):
        stored_offset = _parse_float(stored_sync.get("recommended_offset_seconds"))
        if stored_offset is not None:
            return SyncRecommendation(
                asset_id=asset_id,
                recommended_offset_seconds=stored_offset,
                confidence=float(stored_sync.get("confidence") or 0.4),
                method=str(stored_sync.get("method") or "stored_sync_metadata"),
                reason="Using previously stored source sync metadata.",
                metadata_anchor=stored_sync.get("metadata_anchor") if isinstance(stored_sync.get("metadata_anchor"), dict) else None,
                needs_user_review=bool(stored_sync.get("needs_user_review", True)),
            )

    return SyncRecommendation(
        asset_id=asset_id,
        recommended_offset_seconds=0.0,
        confidence=0.2,
        method="default_zero_offset",
        reason="No comparable start-time metadata found; keep at zero until manual or waveform sync is available.",
        needs_user_review=True,
    )


def _metadata_candidates(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        return []

    candidates = [metadata]
    for key in ("user_metadata", "ffprobe_tags", "format_tags", "source_sync"):
        nested = metadata.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    return candidates


def _sync_role_enum(value: ProjectAssetSyncRole | str) -> ProjectAssetSyncRole | None:
    if isinstance(value, ProjectAssetSyncRole):
        return value
    try:
        return ProjectAssetSyncRole(value)
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp_seconds(value: Any) -> float | None:
    numeric = _parse_float(value)
    if numeric is not None:
        return numeric

    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _anchor_payload(anchor: SyncAnchor | None) -> dict[str, Any] | None:
    if anchor is None:
        return None
    return {
        "key": anchor.key,
        "method": anchor.method,
        "value_seconds": anchor.value_seconds,
    }
