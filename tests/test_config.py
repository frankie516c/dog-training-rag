from backend.app.config import Settings


def test_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOG_TRAINING_RAG_APP_NAME", "test-api")
    monkeypatch.setenv("DOG_TRAINING_RAG_ENVIRONMENT", "test")

    settings = Settings(_env_file=None)

    assert settings.app_name == "test-api"
    assert settings.environment == "test"
    assert settings.log_level == "INFO"
