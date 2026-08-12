from backend.app.config import Settings


def test_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOG_TRAINING_RAG_APP_NAME", "test-api")
    monkeypatch.setenv("DOG_TRAINING_RAG_ENVIRONMENT", "test")
    monkeypatch.setenv("DOG_TRAINING_RAG_QDRANT_PATH", "test-qdrant")
    monkeypatch.setenv("DOG_TRAINING_RAG_QDRANT_COLLECTION", "test-collection")
    monkeypatch.setenv("DOG_TRAINING_RAG_EMBEDDING_MODEL_ID", "test/model")
    monkeypatch.setenv("DOG_TRAINING_RAG_EMBEDDING_DEVICE", "cpu")

    settings = Settings(_env_file=None)

    assert settings.app_name == "test-api"
    assert settings.environment == "test"
    assert settings.log_level == "INFO"
    assert str(settings.qdrant_path) == "test-qdrant"
    assert settings.qdrant_collection == "test-collection"
    assert settings.embedding_model_id == "test/model"
    assert settings.embedding_device == "cpu"
