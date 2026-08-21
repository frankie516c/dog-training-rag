from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    app_name: str = "dog-training-rag"
    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    qdrant_path: Path = Path("data/qdrant")
    qdrant_collection: str = "evidence_cards_v1"
    embedding_model_id: str = "BAAI/bge-m3"
    embedding_device: str | None = None
    # Provisional minimum cosine score for a candidate whose scope already matches the
    # routed question. Derived from a 7-question smoke test, not from a retrieval
    # evaluation; see docs/query-scope-gating.md before changing it.
    scope_matched_minimum_score: float = Field(default=0.40, ge=0.0, le=1.0)
    generation_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GENERATION_BASE_URL", "DOG_TRAINING_RAG_GENERATION_BASE_URL"
        ),
    )
    generation_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GENERATION_API_KEY", "DOG_TRAINING_RAG_GENERATION_API_KEY"),
    )
    generation_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GENERATION_MODEL", "DOG_TRAINING_RAG_GENERATION_MODEL"),
    )
    # Sent verbatim to the OpenAI-compatible endpoint. "none" keeps a reasoning model from
    # spending its budget on thinking tokens for what is a rephrasing task.
    generation_reasoning_effort: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GENERATION_REASONING_EFFORT", "DOG_TRAINING_RAG_GENERATION_REASONING_EFFORT"
        ),
    )
    # A 9B model split across CPU and GPU answers in ~13s here, so the default allows for
    # a slow first call rather than turning it into a fallback.
    generation_timeout_seconds: float = Field(
        default=60.0,
        gt=0.0,
        validation_alias=AliasChoices(
            "GENERATION_TIMEOUT_SECONDS", "DOG_TRAINING_RAG_GENERATION_TIMEOUT_SECONDS"
        ),
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DOG_TRAINING_RAG_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
