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
