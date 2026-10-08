"""Native model-store factory and captured binding/lease integration."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading

from .model_catalog import catalog as pinned_catalog, lookup
from .model_store import ModelStoreError, NativeModelStore, RUNNING

_lock = threading.RLock()
_store = None
_key = None
_stopped = False
_verification_error = None


def _binding_key(settings):
    if not getattr(settings, "is_native_desktop", False):
        raise ModelStoreError("Native model management requires the desktop-native profile")
    root = str(getattr(settings, "WHISPER_CPP_COMPONENT_ROOT", "") or "")
    values = (str(getattr(settings, "APP_STORAGE_ROOT", "") or ""), root,
              str(getattr(settings, "WHISPER_CPP_BINARY_PATH", "") or ""),
              str(getattr(settings, "WHISPER_CPP_MODEL_PATH", "") or ""),
              str(Path(root) / "probes" / "jfk.wav") if root else "")
    if not all(values):
        raise ModelStoreError("Prepare or repair the activated Whisper small component; protected bindings are missing")
    return values


def get_native_model_store(settings, *, restart=False):
    global _store, _key, _stopped, _verification_error
    key = _binding_key(settings)
    with _lock:
        if _store is not None and _key != key:
            # Profile changes cannot abandon work in the prior owned data root.
            _store.shutdown()
            _store = None
            _verification_error = None
        if _stopped and not restart:
            raise ModelStoreError("Native model manager is shut down; restart the native engine")
        if _store is None or (restart and _store._closed):
            _store = NativeModelStore(*key)
            _key = key
            _stopped = False
            _verification_error = None
        _store._binding()
        return _store


def shutdown_native_model_store():
    global _stopped
    with _lock:
        _stopped = True
        store = _store
    if store is not None:
        store.shutdown()


def verify_native_selection(settings):
    global _verification_error
    store = get_native_model_store(settings)
    requested = store.selection()["requested_model_id"]
    try:
        selection = store.verify_selection()
    except Exception as exc:
        if requested == "small":
            raise
        # A failed optional qualification must retain the desired journal and
        # protected small fallback, without turning a filename into readiness.
        selection = store.selection()
        with _lock:
            _verification_error = str(exc)
        return dict(selection, optional_state="verification_failed",
                    optional_error=f"Verify or remove {requested}: {exc}")
    with _lock:
        _verification_error = None
    return selection


def native_selection(settings):
    selection = get_native_model_store(settings).selection()
    alternate = str(getattr(settings, "LOCAL_TRANSCRIPTION_MODEL_PATH", "") or "")
    allowed = {str(getattr(settings, "WHISPER_CPP_MODEL_PATH", "") or ""), selection["file_path"]}
    if alternate and alternate not in allowed:
        raise ModelStoreError("Manual native model path rejected; activate an owned verified model instead")
    with _lock:
        error = _verification_error
    if selection["fallback"] and error:
        selection.update(optional_state="verification_failed", optional_error=error)
    return selection


def apply_native_selection(settings):
    selection = get_native_model_store(settings).selection()
    settings.LOCAL_TRANSCRIPTION_MODEL_ID = selection["model_id"]
    settings.LOCAL_TRANSCRIPTION_MODEL_PATH = selection["file_path"]
    return selection


def validate_captured_binding(store, model_id, model_path, binary_path):
    spec = lookup(model_id)
    with store._lock:
        if store._closed:
            raise ModelStoreError("Captured native model store is shut down")
        store._binding()
        expected = store.bundled_model if model_id == "small" else store._owned(store._paths(spec)[0])
        if str(expected) != model_path or str(store.runtime_binary) != binary_path:
            raise ModelStoreError("Explicit native runtime/model paths do not match the captured verified binding")
        if model_id != "small" and not store._valid_cached(model_id):
            raise ModelStoreError("Captured optional model requires verification before transcription")
    return {"model_id": model_id, "file_path": str(expected), "runtime_binary": str(store.runtime_binary)}


@contextmanager
def native_model_lease(store, model_id, model_path, binary_path):
    with store.usage_lease(model_id) as binding:
        validate_captured_binding(store, model_id, model_path, binary_path)
        yield binding


def native_catalog_snapshot(settings):
    """Metadata only: no hashing, runtime probe, or network acquisition."""
    from providers.whisper_cpp import WHISPER_CPP_MODEL_OPTIONS, _managed_whisper_files
    baseline = _managed_whisper_files(settings.WHISPER_CPP_COMPONENT_ROOT,
                                     settings.WHISPER_CPP_BINARY_PATH, settings.WHISPER_CPP_MODEL_PATH)
    if baseline[2]:
        raise ModelStoreError("; ".join(baseline[2]))
    store = get_native_model_store(settings)
    selection = native_selection(settings)
    options = {option.model_id: option for option in WHISPER_CPP_MODEL_OPTIONS}
    items = []
    with store._lock:
        busy = store._busy is not None
        for spec in pinned_catalog():
            option = options[spec.model_id]
            bundled = spec.model_id == "small"
            ready = bundled or store._valid_cached(spec.model_id)
            file = store.bundled_model if bundled else store._owned(store._paths(spec)[0])
            part = None if bundled else store._owned(store._paths(spec)[1])
            partial = part.stat().st_size if part is not None and part.exists() else 0
            exists = file.is_file()
            attestation = None if bundled else store._owned(store._paths(spec)[2])
            owned_files = exists or (part is not None and part.exists()) or (attestation is not None and attestation.exists())
            job = store.get_job(spec.model_id)
            running = bool(job and job["status"] in RUNNING and store._busy == spec.model_id)
            model_busy = store._busy == spec.model_id
            leased = bool(store._leases.get(spec.model_id, 0))
            verification = not bundled and exists and not ready
            state = job["status"] if job else "not_downloaded"
            if ready and not running:
                state = "downloaded"
            elif verification and not running and state == "completed":
                state = "interrupted"
            retained = spec.size_bytes if ready else (file.stat().st_size if exists else partial)
            message = job["message"] if job else ""
            error = job["error"] if job else None
            if verification and not running:
                message = "Existing model requires local verification and runtime probe"
            if selection["requested_model_id"] == spec.model_id and selection.get("optional_error"):
                error = selection["optional_error"]
            items.append(dict(model_id=spec.model_id, provider_id="whisper-cpp", tier=option.tier,
                              label=option.label, expected_filename=spec.filename, download_url=spec.url,
                              description=option.description, size=option.size_label, size_mb=option.size_mb,
                              size_bytes=spec.size_bytes, sha256=spec.sha256,
                              storage_required_bytes=spec.size_bytes + max(64 * 1024 * 1024, spec.size_bytes // 20),
                              speed=option.speed, quality=option.quality,
                              active=selection["model_id"] == spec.model_id, downloaded=ready, bundled=bundled,
                              managed=True, status=state, can_download=not bundled and not ready and not exists and not busy and not leased,
                              can_remove=not bundled and owned_files and not model_busy and not leased,
                              can_cancel=running, can_resume=not bundled and not exists and partial > 0 and not busy and not leased,
                              verification_required=verification, can_verify=verification and not busy and not leased,
                              download_bytes_downloaded=retained, download_total_bytes=spec.size_bytes,
                              download_progress_percent=(job["progress"] * 100 if running else retained / spec.size_bytes * 100),
                              download_message=message, download_error=error, file_path=str(file) if exists else None))
    message = "whisper.cpp runtime is ready."
    if selection["fallback"]:
        message += f" Using protected small; {selection['requested_model_id']} requires verification."
        if selection.get("optional_error"):
            message += " " + selection["optional_error"]
    return dict(provider_id="whisper-cpp", active_model_id=selection["model_id"], runtime_configured=True,
                runtime_status="ready", runtime_message=message, runtime_binary_path=baseline[0],
                models=items, native=True, optional_state=selection["optional_state"])
