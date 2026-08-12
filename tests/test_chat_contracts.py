from copy import deepcopy
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.domain import (
    ChatCitation,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ContentLanguage,
    EvidenceLevel,
    Locator,
    SafetyNotice,
)
from backend.app.main import CHAT_NOT_READY_MESSAGE, create_app

CARD_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUEST_ID = UUID("22222222-2222-4222-8222-222222222222")


def make_citation(**overrides: object) -> ChatCitation:
    values: dict[str, object] = {
        "card_id": CARD_ID,
        "source_id": "synthetic-source",
        "source_name": "Synthetic source",
        "canonical_url": "https://example.test/guidance",
        "locator": Locator(
            kind="html",
            url="https://example.test/guidance#training-principles",
            section="Training principles",
        ),
        "evidence_level": EvidenceLevel.DIRECT,
    }
    values.update(overrides)
    return ChatCitation.model_validate(values)


def make_response(**overrides: object) -> ChatResponse:
    values: dict[str, object] = {
        "request_id": REQUEST_ID,
        "status": ChatStatus.ANSWERED,
        "answer": "Use a synthetic training example.",
        "answer_language": ContentLanguage.ENGLISH,
        "citations": [make_citation()],
    }
    values.update(overrides)
    return ChatResponse.model_validate(values)


def test_valid_request_trims_message_and_defaults_to_korean() -> None:
    request = ChatRequest(message="  산책 연습은 어떻게 하나요?  ")

    assert request.message == "산책 연습은 어떻게 하나요?"
    assert request.response_language is ContentLanguage.KOREAN


@pytest.mark.parametrize("message", ["", "   ", "\t\n"])
def test_request_rejects_message_empty_after_trimming(message: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message=message)


def test_request_rejects_message_longer_than_1000_characters() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="가" * 1_001)


def test_answered_response_accepts_a_citation() -> None:
    response = make_response()

    assert response.status is ChatStatus.ANSWERED
    assert len(response.citations) == 1


def test_answered_response_rejects_empty_citations() -> None:
    with pytest.raises(ValidationError):
        make_response(citations=[])


def test_insufficient_evidence_accepts_empty_citations() -> None:
    response = make_response(
        status=ChatStatus.INSUFFICIENT_EVIDENCE,
        answer="There is not enough validated evidence.",
        citations=[],
    )

    assert response.citations == []


def test_insufficient_evidence_rejects_citations() -> None:
    with pytest.raises(ValidationError):
        make_response(status=ChatStatus.INSUFFICIENT_EVIDENCE)


def test_citation_rejects_context_only_evidence() -> None:
    with pytest.raises(ValidationError):
        make_citation(evidence_level=EvidenceLevel.CONTEXT_ONLY)


def test_response_rejects_duplicate_card_and_source_citations() -> None:
    citation = make_citation()

    with pytest.raises(ValidationError):
        make_response(citations=[citation, citation.model_copy(deep=True)])


def test_safety_notice_accepts_known_level_and_rejects_blank_message() -> None:
    response = make_response(
        safety_notice={"level": "caution", "message": "  Keep a safe distance.  "}
    )

    assert response.safety_notice == SafetyNotice(level="caution", message="Keep a safe distance.")
    with pytest.raises(ValidationError):
        make_response(safety_notice={"level": "urgent", "message": "   "})


def test_unknown_enum_and_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", response_language="fr")
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"message": "hello", "top_k": 5})
    with pytest.raises(ValidationError):
        make_response(status="unknown")


def test_nested_model_extra_field_is_rejected() -> None:
    citation = make_citation().model_dump(mode="json")
    locator = deepcopy(citation["locator"])
    locator["raw_text"] = "not allowed"
    citation["locator"] = locator

    with pytest.raises(ValidationError):
        ChatCitation.model_validate(citation)


def test_answer_and_safety_message_reject_whitespace_only_text() -> None:
    with pytest.raises(ValidationError):
        make_response(answer="   ")
    with pytest.raises(ValidationError):
        SafetyNotice(level="urgent", message="\n\t")


def test_chat_endpoint_returns_structured_503() -> None:
    client = TestClient(create_app(Settings()))

    response = client.post("/chat", json={"message": "산책 연습을 알려주세요."})

    assert response.status_code == 503
    assert response.json() == {
        "code": "chat_not_ready",
        "message": CHAT_NOT_READY_MESSAGE,
    }


def test_openapi_exposes_chat_request_success_and_503_schemas() -> None:
    client = TestClient(create_app(Settings()))
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/chat"]["post"]

    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    unavailable_schema = operation["responses"]["503"]["content"]["application/json"]["schema"]

    assert request_schema["$ref"].endswith("/ChatRequest")
    assert success_schema["$ref"].endswith("/ChatResponse")
    assert unavailable_schema["$ref"].endswith("/ChatErrorResponse")
