import asyncio
from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.chat_service import ChatService
from backend.app.config import Settings
from backend.app.domain import (
    ChatRequest,
    ChatStatus,
    ContentLanguage,
    EvidenceCard,
    EvidenceLevel,
    Locator,
    SourceClass,
    SourceRef,
    SourceRegistryEntry,
)
from backend.app.generation import GenerationEvidence, build_generation_messages
from backend.app.main import CHAT_NOT_READY_MESSAGE, create_app
from backend.app.retrieval import DEFAULT_TOP_K, SearchResult

CARD_ID = UUID("40000000-0000-4000-8000-000000000001")
REQUEST_ID = UUID("50000000-0000-4000-8000-000000000001")


class FakeRetriever:
    def __init__(
        self,
        results: list[SearchResult],
        sources: dict[str, SourceRegistryEntry] | None = None,
    ) -> None:
        self.results = results
        self.sources = sources or {}
        self.search_calls: list[tuple[str, int]] = []

    def search(self, query: str, *, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]:
        self.search_calls.append((query, top_k))
        return self.results

    def sources_by_id(self) -> dict[str, SourceRegistryEntry]:
        return self.sources


class FakeGenerator:
    def __init__(self, answer: str = "Synthetic grounded answer.", *, fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        message: str,
        response_language: ContentLanguage,
        evidence: tuple[GenerationEvidence, ...],
    ) -> str:
        self.calls.append(
            {
                "message": message,
                "response_language": response_language,
                "evidence": evidence,
            }
        )
        if self.fail:
            raise RuntimeError("synthetic provider failure")
        return self.answer


def make_source(source_id: str, title: str) -> SourceRegistryEntry:
    return SourceRegistryEntry(
        source_id=source_id,
        source_class=SourceClass.OFFICIAL_GUIDANCE,
        title=title,
        publisher="Synthetic publisher",
        canonical_url=f"https://example.test/{source_id}",
        content_languages=[ContentLanguage.ENGLISH],
        last_verified_at=date(2026, 8, 12),
    )


def make_card() -> EvidenceCard:
    return EvidenceCard(
        card_id=CARD_ID,
        claim="Synthetic approved claim.",
        claim_language=ContentLanguage.ENGLISH,
        topic="synthetic topic",
        tags=["not-sent-to-generator"],
        limitations=["Keep the synthetic limitation."],
        source_refs=[
            SourceRef(
                source_id="direct-source",
                locator=Locator(
                    kind="html",
                    url="https://example.test/direct-source#guidance",
                    section="Synthetic guidance",
                ),
                evidence_level=EvidenceLevel.DIRECT,
            ),
            SourceRef(
                source_id="context-source",
                locator=Locator(
                    kind="html",
                    url="https://example.test/context-source#background",
                    section="Synthetic background",
                ),
                evidence_level=EvidenceLevel.CONTEXT_ONLY,
            ),
        ],
    )


def make_service(
    *,
    score: float | None,
    generator: FakeGenerator | None = None,
) -> tuple[ChatService, FakeRetriever, FakeGenerator]:
    card = make_card()
    results = [] if score is None else [SearchResult(card_id=card.card_id, score=score, card=card)]
    sources = {
        "direct-source": make_source("direct-source", "Deterministic direct source"),
        "context-source": make_source("context-source", "Context-only source"),
    }
    retriever = FakeRetriever(results, sources)
    resolved_generator = generator or FakeGenerator()
    service = ChatService(
        retriever=retriever,
        generator=resolved_generator,
        request_id_factory=lambda: REQUEST_ID,
    )
    return service, retriever, resolved_generator


def test_no_retrieval_results_returns_insufficient_evidence() -> None:
    service, retriever, generator = make_service(score=None)

    response = asyncio.run(service.answer(ChatRequest(message="synthetic question")))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert response.answer_language is ContentLanguage.KOREAN
    assert retriever.search_calls == [("synthetic question", 5)]
    assert generator.calls == []


def test_result_below_provisional_threshold_is_insufficient() -> None:
    service, _, generator = make_service(score=0.4499)

    response = asyncio.run(service.answer(ChatRequest(message="synthetic question")))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert generator.calls == []


def test_grounded_result_returns_answered_with_server_citation() -> None:
    service, _, generator = make_service(score=0.45)

    response = asyncio.run(
        service.answer(
            ChatRequest(message="synthetic question", response_language=ContentLanguage.ENGLISH)
        )
    )

    assert response.status is ChatStatus.ANSWERED
    assert response.request_id == REQUEST_ID
    assert response.answer == "Synthetic grounded answer."
    assert response.limitations == ["Keep the synthetic limitation."]
    assert len(response.citations) == 1
    citation = response.citations[0]
    assert citation.card_id == CARD_ID
    assert citation.source_id == "direct-source"
    assert citation.source_name == "Deterministic direct source"
    assert str(citation.canonical_url) == "https://example.test/direct-source"
    assert citation.locator.section == "Synthetic guidance"
    assert citation.evidence_level is EvidenceLevel.DIRECT
    assert all(item.evidence_level is not EvidenceLevel.CONTEXT_ONLY for item in response.citations)

    generation_call = generator.calls[0]
    assert generation_call["evidence"] == (
        GenerationEvidence(
            claim="Synthetic approved claim.",
            topic="synthetic topic",
            limitations=("Keep the synthetic limitation.",),
        ),
    )


def test_generation_prompt_contains_only_allowed_evidence_fields_and_guardrails() -> None:
    messages = build_generation_messages(
        message="synthetic question",
        response_language=ContentLanguage.KOREAN,
        evidence=(
            GenerationEvidence(
                claim="Synthetic claim.",
                topic="Synthetic topic.",
                limitations=("Synthetic limitation.",),
            ),
        ),
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert '"claim":"Synthetic claim."' in prompt
    assert '"topic":"Synthetic topic."' in prompt
    assert '"limitations":["Synthetic limitation."]' in prompt
    assert "punishment-based or fear-based" in prompt
    assert "Do not invent steps" in prompt
    for forbidden in ("locator", "canonical_url", "license", "source_id", "raw_text"):
        assert forbidden not in prompt


def test_unconfigured_provider_returns_structured_503() -> None:
    settings = Settings(
        _env_file=None,
        generation_base_url=None,
        generation_model=None,
    )
    response = TestClient(create_app(settings)).post("/chat", json={"message": "질문"})

    assert response.status_code == 503
    assert response.json() == {
        "code": "chat_not_ready",
        "message": CHAT_NOT_READY_MESSAGE,
    }


def test_provider_failure_returns_structured_503() -> None:
    service, _, _ = make_service(score=0.8, generator=FakeGenerator(fail=True))
    response = TestClient(create_app(Settings(_env_file=None), chat_service=service)).post(
        "/chat", json={"message": "질문"}
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "chat_not_ready",
        "message": CHAT_NOT_READY_MESSAGE,
    }


def test_chat_endpoint_returns_grounded_answer_from_injected_service() -> None:
    service, _, _ = make_service(score=0.8)
    response = TestClient(create_app(Settings(_env_file=None), chat_service=service)).post(
        "/chat",
        json={"message": "synthetic question", "response_language": "en"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["answer"] == "Synthetic grounded answer."
    assert body["citations"][0]["source_id"] == "direct-source"
    assert body["limitations"] == ["Keep the synthetic limitation."]


def test_default_cors_origin_allows_chat_preflight() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))

    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in response.headers["access-control-allow-methods"]
