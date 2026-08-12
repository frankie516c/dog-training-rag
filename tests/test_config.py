from backend.app.config import Settings


def test_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOG_TRAINING_RAG_APP_NAME", "test-api")
    monkeypatch.setenv("DOG_TRAINING_RAG_ENVIRONMENT", "test")
    monkeypatch.setenv("DOG_TRAINING_RAG_QDRANT_PATH", "test-qdrant")
    monkeypatch.setenv("DOG_TRAINING_RAG_QDRANT_COLLECTION", "test-collection")
    monkeypatch.setenv("DOG_TRAINING_RAG_EMBEDDING_MODEL_ID", "test/model")
    monkeypatch.setenv("DOG_TRAINING_RAG_EMBEDDING_DEVICE", "cpu")
    monkeypatch.setenv("GENERATION_BASE_URL", "https://generation.example.test/v1")
    monkeypatch.setenv("GENERATION_API_KEY", "test-secret")
    monkeypatch.setenv("GENERATION_MODEL", "test-generation-model")
    monkeypatch.setenv(
        "DOG_TRAINING_RAG_CORS_ORIGINS", '["http://localhost:3000","https://ui.example.test"]'
    )

    settings = Settings(_env_file=None)

    assert settings.app_name == "test-api"
    assert settings.environment == "test"
    assert settings.log_level == "INFO"
    assert str(settings.qdrant_path) == "test-qdrant"
    assert settings.qdrant_collection == "test-collection"
    assert settings.embedding_model_id == "test/model"
    assert settings.embedding_device == "cpu"
    assert settings.generation_base_url == "https://generation.example.test/v1"
    assert settings.generation_api_key is not None
    assert settings.generation_api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)
    assert settings.generation_model == "test-generation-model"
    assert settings.cors_origins == ["http://localhost:3000", "https://ui.example.test"]
