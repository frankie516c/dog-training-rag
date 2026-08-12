from functools import lru_cache
from pathlib import Path
from typing import Literal

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DOG_TRAINING_RAG_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
