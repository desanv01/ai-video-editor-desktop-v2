"""
Application configuration — loads from environment variables / .env file.
"""

from pydantic_settings import BaseSettings
from typing import List
import json


class Settings(BaseSettings):
    # ── API Keys ──
    OPENAI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""

    # ── Database ──
    DATABASE_URL: str = "postgresql+asyncpg://aive:aive_secret@db:5432/aive_db"

    # ── Qdrant ──
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "course_materials"

    # ── Redis ──
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Storage ──
    VIDEO_STORAGE_PATH: str = "/data/videos"
    UPLOAD_PATH: str = "/data/uploads"
    TEMP_PATH: str = "/data/temp"

    # ── ASR Configuration ──
    ASR_PROVIDER: str = "voxtral"              # "voxtral" (primary) or "whisper" (fallback)
    VOXTRAL_MODEL: str = "voxtral-mini-latest" # Voxtral transcription model (Mistral API)
    MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
    WHISPER_MODEL: str = "whisper-1"            # OpenAI Whisper (fallback)
    ASR_LANGUAGE: str = "en"                    # Force mostly-English lecture transcription by default
    ASR_CONTEXT_PROMPT: str = (
        "English software engineering lecture with occasional Malay phrases. "
        "Object design reuse patterns, design patterns, bridge pattern, template method, "
        "class diagram, inheritance, delegation, abstraction, implementation."
    )

    # ── LLM Configuration (per-agent) ──
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    AGENT2_MODEL: str = "deepseek-chat"         # Content Understanding — heavy reasoning
    AGENT3_MODEL: str = "deepseek-chat"         # Fluency Detection — lightweight (swap to qwen3-8b when available)
    AGENT5_MODEL: str = "deepseek-chat"         # Edit Planner — strong JSON + reasoning

    # AI Provider Mode Configuration
    AI_PROCESSING_MODE: str = "hybrid"          # "api", "local", or "hybrid"
    AI_PROVIDER_FALLBACK_ENABLED: bool = True
    AI_TRANSCRIPTION_MODE: str = "api"          # Current pipeline remains API-backed
    AI_TRANSCRIPTION_API_PROVIDER_ID: str = ""
    AI_TRANSCRIPTION_LOCAL_PROVIDER_ID: str = "whisper-cpp"
    AI_TRANSCRIPTION_HYBRID_FALLBACK_ORDER: str = "local,api"
    AI_TRANSCRIPTION_FALLBACK_ENABLED: bool | None = None
    AI_CHAT_MODE: str = "api"
    AI_EMBEDDING_MODE: str = "api"
    AI_VISION_MODE: str = "api"
    AI_LOCAL_RUNTIME_MODE: str = "local"
    APP_SETTINGS_SECRET_KEY: str = ""           # Fernet key for DB-persisted API keys
    LOCAL_MODEL_STORAGE_PATH: str = "/data/models"
    LOCAL_TRANSCRIPTION_MODEL_PATH: str = ""
    LOCAL_TRANSCRIPTION_MODEL_ID: str = "small"
    LOCAL_TRANSCRIPTION_MODELS_DIR: str = ""
    LOCAL_CHAT_MODEL_PATH: str = ""
    LOCAL_EMBEDDING_MODEL_PATH: str = ""
    LOCAL_VISION_MODEL_PATH: str = ""
    LOCAL_RUNTIME_PATH: str = ""
    WHISPER_CPP_BINARY_PATH: str = "whisper-cli"
    WHISPER_CPP_MODEL_PATH: str = ""
    WHISPER_CPP_MODEL_ID: str = "small"
    WHISPER_CPP_MODELS_DIR: str = ""
    WHISPER_CPP_THREADS: int = 0

    # ── Embedding Configuration ──
    EMBEDDING_MODEL: str = "text-embedding-3-small"  # OpenAI (swap to BGE-M3 endpoint when available)
    EMBEDDING_DIMENSIONS: int = 1536

    # ── Processing ──
    MAX_VIDEO_SIZE_MB: int = 500
    FRAME_SAMPLE_INTERVAL: float = 1.0
    SILENCE_THRESHOLD_DB: int = -40
    SILENCE_MIN_DURATION: float = 1.5
    MIN_EDIT_REDUCTION_PERCENT: float = 18.0
    MAX_AUTO_CUT_IMPORTANCE: float = 0.62
    CHUNK_SIZE_TOKENS: int = 300
    CHUNK_OVERLAP_TOKENS: int = 50

    # ── Context Biasing (domain-specific terms for ASR accuracy) ──
    DOMAIN_TERMS: str = "[]"                   # JSON array of terms, e.g. '["polymorphism","quicksort"]'

    @property
    def domain_terms_list(self) -> List[str]:
        return json.loads(self.DOMAIN_TERMS)

    # ── App ──
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    CORS_ORIGINS: str = '["http://localhost:3000","http://localhost:5173","tauri://localhost"]'

    @property
    def cors_origins_list(self) -> List[str]:
        return json.loads(self.CORS_ORIGINS)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
