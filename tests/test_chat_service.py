import asyncio
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.chat_service import CANDIDATE_TOP_K, ChatService
from backend.app.composition import CLAIM_SEPARATOR
from backend.app.config import Settings
from backend.app.domain import (
    ChatRequest,
    ChatStatus,
    ContentLanguage,
    EvidenceCard,
    EvidenceLevel,
    Locator,
    SafetyLevel,
    SourceClass,
    SourceRef,
    SourceRegistryEntry,
)
from backend.app.grounded import GroundedAnswerer
from backend.app.main import create_app
from backend.app.retrieval import DEFAULT_TOP_K, SearchResult

CARD_ID = UUID("40000000-0000-4000-8000-000000000001")
OTHER_CARD_ID = UUID("40000000-0000-4000-8000-000000000002")
HOUSETRAINING_CARD_ID = UUID("40000000-0000-4000-8000-000000000003")
SECOND_JUMPING_CARD_ID = UUID("40000000-0000-4000-8000-000000000004")
REQUEST_ID = UUID("50000000-0000-4000-8000-000000000001")

# An explicit 왜 question: explanation intent, so research-finding cards remain usable.
SUPPORTED_QUESTION = "강아지가 왜 사람에게 뛰어오르나요?"
COLLOQUIAL_HOUSETRAINING_QUESTION = "응가를 아무데나 해요ㅠㅠ"
UNSUPPORTED_QUESTION = "강아지에게 손이나 악수를 가르치고 싶어요."
SAFETY_QUESTION = "강아지가 초콜릿을 먹었어요."
ECOLLAR_QUESTION = "전자 목줄이 보상 훈련보다 더 효과적인가요?"
# Same scope and same cards, but an explanation intent, which may use generation.
ECOLLAR_EXPLANATION_QUESTION = "전자 목줄 연구 결과가 왜 그런가요?"
# Comparison over a scope whose only approved evidence is guidance, which cannot compare.
GUIDANCE_COMPARISON_QUESTION = "배변 패드가 배변 훈련보다 더 효과적인가요?"
LEASH_HOW_TO_QUESTION = "산책할 때 리드줄 당김을 어떻게 고치나요?"
UNSUPPORTED_ANSWER = "현재 검증된 훈련 근거 범위에서는 이 질문에 답하기 어렵습니다."

ECOLLAR_CLAIM = "제한된 연구에서 e-collar 집단의 우위는 나타나지 않았다."
AVERSIVE_CLAIM = "혐오 자극 비율이 높은 집단은 보상 기반 집단보다 부정적인 결과를 보였다."
GENERATED_ANSWER = "제한된 연구에서 e-collar 집단이 더 낫다는 근거는 나타나지 않았습니다."

JUMPING_CLAIM = "점프를 하나의 공통 원인으로 단정하기 어려웠다."
SECOND_JUMPING_CLAIM = "4마리 중 3마리는 점프가 감소했지만 1마리는 반응하지 않았다."
LEASH_CLAIM = "3주간의 보상 기반 리드줄 보행 수업을 운영할 수 있었다."
HOUSETRAINING_CLAIM = "사후에 발견한 실수를 처벌하는 방식은 학습에 도움이 되지 않는다."


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


class SpyComposer:
    """Wraps the real composer so tests can assert it was never reached."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, ...]] = []

    def __call__(self, cards: Sequence[EvidenceCard]) -> str:
        from backend.app.composition import compose_evidence_answer

        self.calls.append(tuple(card.card_id for card in cards))
        return compose_evidence_answer(cards)


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


def make_card(
    *,
    card_id: UUID = CARD_ID,
    claim: str = JUMPING_CLAIM,
    claim_language: ContentLanguage = ContentLanguage.KOREAN,
    topic: str = "synthetic jumping up topic",
    tags: list[str] | None = None,
    limitations: list[str] | None = None,
) -> EvidenceCard:
    """Build a synthetic card whose topic/tags map to one internal scope."""

    return EvidenceCard(
        card_id=card_id,
        claim=claim,
        claim_language=claim_language,
        topic=topic,
        tags=tags if tags is not None else ["jumping up"],
        limitations=limitations if limitations is not None else ["Keep the synthetic limitation."],
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


def make_second_jumping_card() -> EvidenceCard:
    return make_card(
        card_id=SECOND_JUMPING_CARD_ID,
        claim=SECOND_JUMPING_CLAIM,
        topic="synthetic jumping up intervention",
        limitations=["Keep the second synthetic limitation."],
    )


def make_off_scope_card() -> EvidenceCard:
    return make_card(
        card_id=OTHER_CARD_ID,
        claim=LEASH_CLAIM,
        topic="synthetic loose leash topic",
        tags=["leash walking"],
    )


def make_housetraining_card() -> EvidenceCard:
    """Mirrors the approved housetraining card: guidance, so it can serve how_to."""

    return make_card(
        card_id=HOUSETRAINING_CARD_ID,
        claim=HOUSETRAINING_CLAIM,
        topic="synthetic housetraining topic",
        tags=["housetraining", "management"],
    )


def make_service_from_results(
    results: list[SearchResult],
    *,
    grounded: GroundedAnswerer | None = None,
) -> tuple[ChatService, FakeRetriever, SpyComposer]:
    sources = {
        "direct-source": make_source("direct-source", "Deterministic direct source"),
        "context-source": make_source("context-source", "Context-only source"),
    }
    retriever = FakeRetriever(results, sources)
    composer = SpyComposer()
    service = ChatService(
        retriever=retriever,
        grounded=grounded,
        composer=composer,
        request_id_factory=lambda: REQUEST_ID,
    )
    return service, retriever, composer


def make_service(*, score: float | None) -> tuple[ChatService, FakeRetriever, SpyComposer]:
    card = make_card()
    results = [] if score is None else [SearchResult(card_id=card.card_id, score=score, card=card)]
    return make_service_from_results(results)


def test_no_retrieval_results_returns_insufficient_evidence() -> None:
    service, retriever, composer = make_service(score=None)

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert response.answer_language is ContentLanguage.KOREAN
    assert retriever.search_calls == [(SUPPORTED_QUESTION, CANDIDATE_TOP_K)]
    assert composer.calls == []


def test_scope_matched_result_below_minimum_is_insufficient() -> None:
    service, _, composer = make_service(score=0.3999)

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert composer.calls == []


def test_scope_matched_result_at_minimum_is_answered_without_a_generation_provider() -> None:
    service, _, composer = make_service(score=0.40)

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == JUMPING_CLAIM
    assert [citation.card_id for citation in response.citations] == [CARD_ID]
    assert composer.calls == [(CARD_ID,)]


def test_answer_is_the_reviewed_claim_verbatim() -> None:
    service, _, _ = make_service(score=0.8)

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.answer == JUMPING_CLAIM
    assert response.answer == make_card().claim


def test_multiple_cards_compose_in_citation_order() -> None:
    first = make_card()
    second = make_second_jumping_card()
    service, _, _ = make_service_from_results(
        [
            SearchResult(card_id=first.card_id, score=0.81, card=first),
            SearchResult(card_id=second.card_id, score=0.55, card=second),
        ]
    )

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.answer == JUMPING_CLAIM + CLAIM_SEPARATOR + SECOND_JUMPING_CLAIM
    citation_order = [citation.card_id for citation in response.citations]
    assert citation_order == [CARD_ID, SECOND_JUMPING_CARD_ID]
    assert response.answer.index(JUMPING_CLAIM) < response.answer.index(SECOND_JUMPING_CLAIM)
    assert response.limitations == [
        "Keep the synthetic limitation.",
        "Keep the second synthetic limitation.",
    ]


def test_off_scope_card_is_dropped_even_with_a_higher_score() -> None:
    off_scope = make_off_scope_card()
    service, retriever, composer = make_service_from_results(
        [SearchResult(card_id=off_scope.card_id, score=0.92, card=off_scope)]
    )

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert retriever.search_calls == [(SUPPORTED_QUESTION, CANDIDATE_TOP_K)]
    assert composer.calls == []


def test_off_scope_card_reaches_neither_answer_nor_citations() -> None:
    in_scope = make_card()
    off_scope = make_off_scope_card()
    service, _, composer = make_service_from_results(
        [
            SearchResult(card_id=off_scope.card_id, score=0.92, card=off_scope),
            SearchResult(card_id=in_scope.card_id, score=0.51, card=in_scope),
        ]
    )

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == JUMPING_CLAIM
    assert LEASH_CLAIM not in response.answer
    assert {citation.card_id for citation in response.citations} == {CARD_ID}
    assert composer.calls == [(CARD_ID,)]


def test_unmapped_card_is_dropped() -> None:
    unmapped = make_card(topic="synthetic topic", tags=["not-a-scope-marker"])
    service, _, composer = make_service_from_results(
        [SearchResult(card_id=unmapped.card_id, score=0.99, card=unmapped)]
    )

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert composer.calls == []


def test_colloquial_housetraining_question_reaches_retrieval_and_composition() -> None:
    housetraining = make_housetraining_card()
    leash = make_off_scope_card()
    jumping = make_card()
    service, retriever, composer = make_service_from_results(
        [
            SearchResult(card_id=leash.card_id, score=0.95, card=leash),
            SearchResult(card_id=jumping.card_id, score=0.93, card=jumping),
            SearchResult(card_id=housetraining.card_id, score=0.44, card=housetraining),
        ]
    )

    response = asyncio.run(service.answer(ChatRequest(message=COLLOQUIAL_HOUSETRAINING_QUESTION)))

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == HOUSETRAINING_CLAIM
    assert retriever.search_calls == [(COLLOQUIAL_HOUSETRAINING_QUESTION, CANDIDATE_TOP_K)]
    assert {citation.card_id for citation in response.citations} == {HOUSETRAINING_CARD_ID}
    assert composer.calls == [(HOUSETRAINING_CARD_ID,)]


def test_english_request_without_an_english_claim_is_insufficient() -> None:
    service, _, composer = make_service(score=0.9)

    response = asyncio.run(
        service.answer(
            ChatRequest(message=SUPPORTED_QUESTION, response_language=ContentLanguage.ENGLISH)
        )
    )

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert response.answer_language is ContentLanguage.ENGLISH
    assert composer.calls == []


def test_english_request_uses_only_english_claims() -> None:
    korean = make_card()
    english = make_card(
        card_id=SECOND_JUMPING_CARD_ID,
        claim="Jumping up is maintained by different reinforcers in different dogs.",
        claim_language=ContentLanguage.ENGLISH,
        topic="synthetic jumping up intervention",
    )
    service, _, _ = make_service_from_results(
        [
            SearchResult(card_id=korean.card_id, score=0.95, card=korean),
            SearchResult(card_id=english.card_id, score=0.42, card=english),
        ]
    )

    response = asyncio.run(
        service.answer(
            ChatRequest(message=SUPPORTED_QUESTION, response_language=ContentLanguage.ENGLISH)
        )
    )

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == english.claim
    assert JUMPING_CLAIM not in response.answer
    assert [citation.card_id for citation in response.citations] == [SECOND_JUMPING_CARD_ID]
    assert response.answer_language is ContentLanguage.ENGLISH


def test_unsupported_question_skips_retrieval_and_composition() -> None:
    service, retriever, composer = make_service(score=0.99)

    response = asyncio.run(service.answer(ChatRequest(message=UNSUPPORTED_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.answer == UNSUPPORTED_ANSWER
    assert response.citations == []
    assert response.safety_notice is None
    assert retriever.search_calls == []
    assert composer.calls == []


def test_safety_question_skips_retrieval_and_composition() -> None:
    service, retriever, composer = make_service(score=0.99)

    response = asyncio.run(service.answer(ChatRequest(message=SAFETY_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert response.safety_notice is not None
    assert response.safety_notice.level is SafetyLevel.URGENT
    assert "동물병원" in response.safety_notice.message
    assert retriever.search_calls == []
    assert composer.calls == []


def test_server_side_citation_fields_are_unchanged() -> None:
    service, _, _ = make_service(score=0.8)

    response = asyncio.run(service.answer(ChatRequest(message=SUPPORTED_QUESTION)))

    assert response.request_id == REQUEST_ID
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


def test_chat_endpoint_returns_composed_answer_from_injected_service() -> None:
    service, _, _ = make_service(score=0.8)
    response = TestClient(create_app(Settings(_env_file=None), chat_service=service)).post(
        "/chat",
        json={"message": SUPPORTED_QUESTION},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["answer"] == JUMPING_CLAIM
    assert body["citations"][0]["source_id"] == "direct-source"
    assert body["limitations"] == ["Keep the synthetic limitation."]


def test_chat_endpoint_returns_safety_notice_without_citations() -> None:
    service, _, _ = make_service(score=0.8)
    response = TestClient(create_app(Settings(_env_file=None), chat_service=service)).post(
        "/chat",
        json={"message": SAFETY_QUESTION},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert body["safety_notice"]["level"] == "urgent"


def test_chat_is_ready_without_any_generation_configuration(tmp_path: Path) -> None:
    """No Ollama, no GENERATION_* variables: /chat still serves a normal 200."""

    settings = Settings(
        _env_file=None,
        generation_base_url=None,
        generation_api_key=None,
        generation_model=None,
        qdrant_path=tmp_path / "qdrant",
    )
    client = TestClient(create_app(settings))

    response = client.post("/chat", json={"message": SUPPORTED_QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []


class FakeProvider:
    """Records prompts and returns a canned completion (or raises)."""

    def __init__(self, response: str | None = None, *, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    @property
    def last_prompt(self) -> str:
        return "\n".join(item["content"] for item in self.calls[-1])


def grounded_payload(answer: str, card_ids: list[UUID]) -> str:
    return json.dumps(
        {
            "answerable": True,
            "answer": answer,
            "used_card_ids": [str(card_id) for card_id in card_ids],
        },
        ensure_ascii=False,
    )


def make_ecollar_service(
    provider: FakeProvider | None,
) -> tuple[ChatService, FakeRetriever, SpyComposer]:
    first = make_card(
        card_id=CARD_ID,
        claim=ECOLLAR_CLAIM,
        topic="e-collar 훈련 효율 비교",
        tags=["e-collar", "positive reinforcement"],
    )
    second = make_card(
        card_id=SECOND_JUMPING_CARD_ID,
        claim=AVERSIVE_CLAIM,
        topic="혐오 자극 기반 훈련과 복지 지표",
        tags=["aversive training", "welfare"],
        limitations=["Keep the second synthetic limitation."],
    )
    grounded = GroundedAnswerer(provider=provider) if provider is not None else None
    return make_service_from_results(
        [
            SearchResult(card_id=first.card_id, score=0.72, card=first),
            SearchResult(card_id=second.card_id, score=0.51, card=second),
        ],
        grounded=grounded,
    )


def test_ecollar_explanation_enters_the_generated_path() -> None:
    provider = FakeProvider(grounded_payload(GENERATED_ANSWER, [CARD_ID]))
    service, _, composer = make_ecollar_service(provider)

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == GENERATED_ANSWER
    assert len(provider.calls) == 1
    assert composer.calls == []
    assert ECOLLAR_CLAIM in provider.last_prompt
    assert AVERSIVE_CLAIM in provider.last_prompt


# --------------------------------------------------------------------------------------
# Comparison never reaches the provider (checkpoint 5I-A mitigation)
# --------------------------------------------------------------------------------------


def test_ecollar_comparison_is_composed_without_calling_the_provider() -> None:
    provider = FakeProvider(grounded_payload(GENERATED_ANSWER, [CARD_ID]))
    service, retriever, composer = make_ecollar_service(provider)

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_QUESTION)))

    assert retriever.search_calls == [(ECOLLAR_QUESTION, CANDIDATE_TOP_K)]
    assert provider.calls == [], "comparison must not reach generation"
    assert composer.calls == [(CARD_ID, SECOND_JUMPING_CARD_ID)]
    assert response.status is ChatStatus.ANSWERED
    assert response.answer == ECOLLAR_CLAIM + CLAIM_SEPARATOR + AVERSIVE_CLAIM
    assert [citation.card_id for citation in response.citations] == [
        CARD_ID,
        SECOND_JUMPING_CARD_ID,
    ]
    assert response.limitations == [
        "Keep the synthetic limitation.",
        "Keep the second synthetic limitation.",
    ]


def test_comparison_answer_uses_only_the_two_selected_claims() -> None:
    provider = FakeProvider(grounded_payload(GENERATED_ANSWER, [CARD_ID]))
    service, _, _ = make_ecollar_service(provider)

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_QUESTION)))

    assert response.answer.split(CLAIM_SEPARATOR) == [ECOLLAR_CLAIM, AVERSIVE_CLAIM]
    assert GENERATED_ANSWER not in response.answer


def test_comparison_bypasses_the_validator_that_cannot_see_polarity_reversal() -> None:
    """Integration guard for the documented validator limitation.

    tests/test_grounded.py pins that a reversed conclusion passes validate_draft(). This
    asserts the service never gives that validator the chance on a comparison question.
    """

    reversed_answer = "e-collar 집단이 보상 중심 집단보다 더 효율적이었다."
    provider = FakeProvider(grounded_payload(reversed_answer, [CARD_ID]))
    service, _, _ = make_ecollar_service(provider)

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_QUESTION)))

    assert provider.calls == []
    assert reversed_answer not in response.answer
    assert response.answer == ECOLLAR_CLAIM + CLAIM_SEPARATOR + AVERSIVE_CLAIM


def test_comparison_without_answerable_evidence_is_insufficient() -> None:
    """Guidance cards cannot compare, so nothing is generated and nothing is composed."""

    guidance = make_housetraining_card()
    provider = FakeProvider(grounded_payload(GENERATED_ANSWER, [HOUSETRAINING_CARD_ID]))
    service, retriever, composer = make_service_from_results(
        [SearchResult(card_id=guidance.card_id, score=0.81, card=guidance)],
        grounded=GroundedAnswerer(provider=provider),
    )

    response = asyncio.run(service.answer(ChatRequest(message=GUIDANCE_COMPARISON_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert response.limitations == []
    assert HOUSETRAINING_CLAIM not in response.answer
    assert retriever.search_calls == [(GUIDANCE_COMPARISON_QUESTION, CANDIDATE_TOP_K)]
    assert provider.calls == []
    assert composer.calls == []


def test_comparison_without_a_provider_behaves_identically() -> None:
    service, _, composer = make_ecollar_service(None)

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_QUESTION)))

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == ECOLLAR_CLAIM + CLAIM_SEPARATOR + AVERSIVE_CLAIM
    assert composer.calls == [(CARD_ID, SECOND_JUMPING_CARD_ID)]


def test_generated_citations_follow_used_card_ids_only() -> None:
    provider = FakeProvider(grounded_payload(GENERATED_ANSWER, [CARD_ID]))
    service, _, _ = make_ecollar_service(provider)

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert [citation.card_id for citation in response.citations] == [CARD_ID]
    assert response.limitations == ["Keep the synthetic limitation."]


def test_model_supplied_citation_and_limitation_fields_are_ignored() -> None:
    raw = json.dumps(
        {
            "answerable": True,
            "answer": GENERATED_ANSWER,
            "used_card_ids": [str(CARD_ID)],
            "citations": [{"source_id": "made-up", "canonical_url": "https://evil.test"}],
            "limitations": ["모델이 지어낸 한계"],
        },
        ensure_ascii=False,
    )
    service, _, _ = make_ecollar_service(FakeProvider(raw))

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert [citation.source_id for citation in response.citations] == ["direct-source"]
    assert response.limitations == ["Keep the synthetic limitation."]
    assert "모델이 지어낸 한계" not in response.limitations


def test_unretrieved_card_id_falls_back_to_composition() -> None:
    unknown = UUID("40000000-0000-4000-8000-0000000000ff")
    service, _, composer = make_ecollar_service(
        FakeProvider(grounded_payload(GENERATED_ANSWER, [unknown]))
    )

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == ECOLLAR_CLAIM + CLAIM_SEPARATOR + AVERSIVE_CLAIM
    assert composer.calls == [(CARD_ID, SECOND_JUMPING_CARD_ID)]


def test_answerable_false_returns_insufficient_evidence() -> None:
    """The model rejected this evidence; do not fall back to the claim it rejected."""

    raw = json.dumps({"answerable": False, "answer": None, "used_card_ids": []})
    service, _, composer = make_ecollar_service(FakeProvider(raw))

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert ECOLLAR_CLAIM not in response.answer
    assert composer.calls == []


def test_malformed_json_falls_back_to_composition() -> None:
    service, _, composer = make_ecollar_service(FakeProvider("자유로운 산문 답변입니다."))

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert response.answer == ECOLLAR_CLAIM + CLAIM_SEPARATOR + AVERSIVE_CLAIM
    assert len(composer.calls) == 1


def test_empty_answer_falls_back_to_composition() -> None:
    service, _, composer = make_ecollar_service(FakeProvider(grounded_payload("   ", [CARD_ID])))

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert response.answer == ECOLLAR_CLAIM + CLAIM_SEPARATOR + AVERSIVE_CLAIM
    assert len(composer.calls) == 1


def test_provider_timeout_falls_back_to_composition() -> None:
    provider = FakeProvider(error=TimeoutError("provider timed out"))
    service, _, composer = make_ecollar_service(provider)

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == ECOLLAR_CLAIM + CLAIM_SEPARATOR + AVERSIVE_CLAIM
    assert len(provider.calls) == 1
    assert len(composer.calls) == 1


def test_unconfigured_provider_uses_composition_without_error() -> None:
    service, _, composer = make_ecollar_service(None)

    response = asyncio.run(service.answer(ChatRequest(message=ECOLLAR_EXPLANATION_QUESTION)))

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == ECOLLAR_CLAIM + CLAIM_SEPARATOR + AVERSIVE_CLAIM
    assert len(composer.calls) == 1


def test_leash_how_to_without_procedural_evidence_never_reaches_generation() -> None:
    leash = make_card(
        card_id=OTHER_CARD_ID,
        claim=LEASH_CLAIM,
        topic="리드줄 보행 프로그램의 실행 가능성",
        tags=["leash walking", "feasibility"],
    )
    provider = FakeProvider(grounded_payload("절대 나오면 안 되는 답변", [OTHER_CARD_ID]))
    service, retriever, composer = make_service_from_results(
        [SearchResult(card_id=leash.card_id, score=0.88, card=leash)],
        grounded=GroundedAnswerer(provider=provider),
    )

    response = asyncio.run(service.answer(ChatRequest(message=LEASH_HOW_TO_QUESTION)))

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert LEASH_CLAIM not in response.answer
    assert retriever.search_calls == [(LEASH_HOW_TO_QUESTION, CANDIDATE_TOP_K)]
    assert provider.calls == []
    assert composer.calls == []


def test_safety_and_unsupported_never_reach_the_provider() -> None:
    for message in (SAFETY_QUESTION, UNSUPPORTED_QUESTION):
        provider = FakeProvider(grounded_payload("나오면 안 되는 답변", [CARD_ID]))
        service, retriever, composer = make_ecollar_service(provider)

        response = asyncio.run(service.answer(ChatRequest(message=message)))

        assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
        assert retriever.search_calls == []
        assert provider.calls == []
        assert composer.calls == []


def test_default_cors_origin_allows_chat_preflight(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, qdrant_path=tmp_path / "qdrant")
    client = TestClient(create_app(settings))

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
