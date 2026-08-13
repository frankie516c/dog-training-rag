import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.domain import ContentLanguage
from backend.app.generation import (
    GenerationError,
    OpenAICompatibleGenerationProvider,
    build_generation_messages,
    normalize_generated_answer,
)
from backend.app.main import CHAT_NOT_READY_MESSAGE, create_app

PROSE = "강아지가 뛰어오르는 행동의 기능은 개체마다 다를 수 있습니다."


def test_plain_prose_is_returned_unchanged() -> None:
    assert normalize_generated_answer(PROSE) == PROSE
    assert normalize_generated_answer(f"  {PROSE}  ") == PROSE


def test_fenced_json_answer_is_extracted() -> None:
    assert normalize_generated_answer(f'```json\n{{"answer": "{PROSE}"}}\n```') == PROSE


def test_bare_json_answer_is_extracted() -> None:
    assert normalize_generated_answer(f'{{"answer": "{PROSE}", "citations": []}}') == PROSE


def test_fenced_prose_without_json_is_unwrapped() -> None:
    assert normalize_generated_answer(f"```\n{PROSE}\n```") == PROSE


def test_prose_that_merely_mentions_json_or_a_fence_is_untouched() -> None:
    inline = '보호자에게 {"answer": "..."} 같은 형식을 보여줄 필요는 없습니다.'
    assert normalize_generated_answer(inline) == inline

    with_block = f"{PROSE}\n\n```\n예시\n```\n\n마지막 문장입니다."
    assert normalize_generated_answer(with_block) == with_block

    two_fences = "```\n첫 블록\n```\n\n```\n둘째 블록\n```"
    assert normalize_generated_answer(two_fences) == two_fences


def test_json_object_without_a_string_answer_is_left_alone() -> None:
    content = '{"result": "no answer field"}'
    assert normalize_generated_answer(content) == content

    invalid = '{"answer": 닫히지 않은 객체}'
    assert normalize_generated_answer(invalid) == invalid


def test_empty_output_and_empty_answer_normalize_to_nothing() -> None:
    assert normalize_generated_answer("") == ""
    assert normalize_generated_answer("   \n  ") == ""
    assert normalize_generated_answer('{"answer": "   "}') == ""
    assert normalize_generated_answer('```json\n{"answer": ""}\n```') == ""


def test_system_prompt_forbids_wrapped_output() -> None:
    messages = build_generation_messages(
        message="synthetic question",
        response_language=ContentLanguage.KOREAN,
        evidence=(),
    )
    system = messages[0]["content"]

    assert "plain prose only" in system
    assert "Markdown code fence" in system
    assert "response schema" in system
    assert "assembles citations and limitations separately" in system


class FakeAsyncClient:
    """Minimal stand-in for httpx.AsyncClient returning one canned completion."""

    content: Any = PROSE

    def __init__(self, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> "FakeAsyncClient":
        return self

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": type(self).content}}]}


def run_provider(monkeypatch: pytest.MonkeyPatch, content: Any) -> str:
    monkeypatch.setattr(FakeAsyncClient, "content", content)
    monkeypatch.setattr("backend.app.generation.httpx.AsyncClient", FakeAsyncClient)
    provider = OpenAICompatibleGenerationProvider(
        base_url="http://localhost:11434/v1",
        model="synthetic-model",
    )
    return asyncio.run(
        provider.generate(
            message="synthetic question",
            response_language=ContentLanguage.KOREAN,
            evidence=(),
        )
    )


def test_provider_normalizes_a_wrapped_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_provider(monkeypatch, f'```json\n{{"answer": "{PROSE}"}}\n```') == PROSE


def test_provider_rejects_an_empty_normalized_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(GenerationError):
        run_provider(monkeypatch, '```json\n{"answer": "  "}\n```')

    with pytest.raises(GenerationError):
        run_provider(monkeypatch, "   ")

    with pytest.raises(GenerationError):
        run_provider(monkeypatch, None)


def test_retrieval_initialization_failure_logs_the_cause_and_stays_not_ready(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def explode(**kwargs: object) -> None:
        raise RuntimeError("Storage folder is already accessed by another instance")

    monkeypatch.setattr("backend.app.main.EvidenceRetrieval", explode)
    settings = Settings(
        _env_file=None,
        generation_base_url="http://localhost:11434/v1",
        generation_model="synthetic-model",
        generation_api_key="sk-test-secret-value",
    )

    with caplog.at_level(logging.ERROR, logger="backend.app.main"):
        client = TestClient(create_app(settings))

    records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert records, "an initialization failure must be logged at ERROR"
    logged = "\n".join(record.getMessage() for record in records)
    assert "evidence retrieval" in logged
    assert "RuntimeError" in logged
    assert "single-process" in logged
    assert records[0].exc_info is not None
    assert "sk-test-secret-value" not in caplog.text

    response = client.post("/chat", json={"message": "강아지가 사람을 보면 자꾸 뛰어올라요."})

    assert response.status_code == 503
    assert response.json() == {"code": "chat_not_ready", "message": CHAT_NOT_READY_MESSAGE}
    for forbidden in ("sk-test-secret-value", "synthetic-model", "qdrant", "localhost:11434"):
        assert forbidden not in response.text


def test_chat_service_does_not_depend_on_the_generation_adapter() -> None:
    """ChatService talks to a GroundedAnswerer, never to an HTTP provider directly.

    main.py may construct the adapter when one is configured; the service itself must
    stay usable with no provider at all.
    """

    import inspect

    import backend.app.chat_service as chat_service

    source = Path(chat_service.__file__).read_text(encoding="utf-8")
    assert "from backend.app.generation import" not in source
    assert "import backend.app.generation" not in source
    assert not hasattr(chat_service, "GenerationProvider")
    assert not hasattr(chat_service, "GenerationEvidence")

    parameters = inspect.signature(chat_service.ChatService.__init__).parameters
    assert parameters["grounded"].default is None
