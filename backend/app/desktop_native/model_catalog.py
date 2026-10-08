"""Immutable upstream identities for the supported native Whisper models."""
from dataclasses import dataclass
from types import MappingProxyType

REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"

@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    filename: str
    size_bytes: int
    sha256: str
    url: str

def _spec(model_id, size, digest):
    filename = f"ggml-{model_id}.bin"
    return ModelSpec(model_id, filename, size, digest,
                     f"https://huggingface.co/ggerganov/whisper.cpp/resolve/{REVISION}/{filename}")

MODELS = MappingProxyType({
    "small": _spec("small", 487601967, "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"),
    "medium": _spec("medium", 1533763059, "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"),
    "large-v3": _spec("large-v3", 3095033483, "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"),
})

def lookup(model_id: str) -> ModelSpec:
    if not isinstance(model_id, str) or model_id not in MODELS:
        raise ValueError(f"Unknown native model ID: {model_id!r}")
    return MODELS[model_id]

def catalog() -> tuple[ModelSpec, ...]:
    return tuple(MODELS.values())
