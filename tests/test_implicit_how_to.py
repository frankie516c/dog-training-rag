"""The five problem statements users actually typed, end to end against real cards.

Owners describe the behaviour and expect what to do about it. Reading those as explanation
let a leash-walking feasibility study answer a pulling complaint. These tests pin the
implicit how_to reading and, more importantly, pin what must NOT happen when the only
matching evidence is a research finding: no generation, no deterministic fallback, no
research summary presented as if it were the requested procedure.
"""

import asyncio
import json

import pytest

from backend.app.answerability import QuestionIntent, classify_question_intent
from backend.app.chat_service import ChatService
from backend.app.data_validation import (
    DEFAULT_EVIDENCE_CARDS_PATH,
    DEFAULT_SOURCE_REGISTRY_PATH,
)
from backend.app.domain import ChatRequest, ChatStatus, EvidenceCard, SourceRegistryEntry
from backend.app.grounded import GroundedAnswerer
from backend.app.retrieval import SearchResult
from backend.app.scope import TrainingScope, card_scope

# (question, scope whose approved cards it retrieves)
UI_STATEMENTS = [
    ("산책할 때 리드줄을 계속 당겨요", TrainingScope.LEASH_WALKING),
    ("사람만 보면 뛰어올라요", TrainingScope.JUMPING_UP),
    ("켄넬 안에서 계속 짖어요", TrainingScope.KENNEL_BARKING),
    ("이동장에 들어가는 걸 무서워해요", TrainingScope.CRATE_ADAPTATION),
    ("응가를 아무 데나 해요", TrainingScope.HOUSETRAINING),
]

# Scopes whose approved evidence is guidance, so an implicit how_to can be answered.
ANSWERABLE_SCOPES = {TrainingScope.HOUSETRAINING, TrainingScope.CRATE_ADAPTATION}


def load_cards() -> list[EvidenceCard]:
    lines = DEFAULT_EVIDENCE_CARDS_PATH.read_text(encoding="utf-8").splitlines()
    return [EvidenceCard.model_validate_json(line) for line in lines if line.strip()]


def load_sources() -> dict[str, SourceRegistryEntry]:
    lines = DEFAULT_SOURCE_REGISTRY_PATH.read_text(encoding="utf-8").splitlines()
    entries = [
        SourceRegistryEntry.model_validate(json.loads(line)) for line in lines if line.strip()
    ]
    return {entry.source_id: entry for entry in entries}


def cards_in(scope: TrainingScope) -> list[EvidenceCard]:
    return [card for card in load_cards() if card_scope(card) is scope]


class RecordingRetriever:
    def __init__(self, cards: list[EvidenceCard]) -> None:
        self.cards = cards
        self.search_calls: list[tuple[str, int]] = []

    def search(self, query: str, *, top_k: int = 5) -> list[SearchResult]:
        self.search_calls.append((query, top_k))
        return [
            SearchResult(card_id=card.card_id, score=0.70 - index * 0.05, card=card)
            for index, card in enumerate(self.cards)
        ]

    def sources_by_id(self) -> dict[str, SourceRegistryEntry]:
        return load_sources()


class RecordingProvider:
    """Records that generation was attempted, then fails so the answer comes from the
    deterministic composer. These tests are about which requests reach the provider at
    all, not about draft quality — that is covered in tests/test_grounded.py."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        raise RuntimeError("synthetic provider failure")


class RecordingComposer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cards) -> str:
        from backend.app.composition import compose_evidence_answer

        self.calls.append(tuple(str(card.card_id) for card in cards))
        return compose_evidence_answer(cards)


def run(question: str, scope: TrainingScope):
    cards = cards_in(scope)
    assert cards, f"expected approved cards for {scope.value}"
    retriever = RecordingRetriever(cards)
    provider = RecordingProvider()
    composer = RecordingComposer()
    service = ChatService(
        retriever=retriever,
        grounded=GroundedAnswerer(provider=provider),
        composer=composer,
    )
    response = asyncio.run(service.answer(ChatRequest(message=question)))
    return response, retriever, provider, composer


@pytest.mark.parametrize(("question", "scope"), UI_STATEMENTS, ids=[q for q, _ in UI_STATEMENTS])
def test_problem_statements_are_read_as_implicit_how_to(
    question: str, scope: TrainingScope
) -> None:
    assert classify_question_intent(question) is QuestionIntent.HOW_TO


@pytest.mark.parametrize(
    ("question", "scope"),
    [item for item in UI_STATEMENTS if item[1] in ANSWERABLE_SCOPES],
    ids=[q for q, s in UI_STATEMENTS if s in ANSWERABLE_SCOPES],
)
def test_guidance_backed_statements_are_answered(question: str, scope: TrainingScope) -> None:
    response, _, provider, composer = run(question, scope)

    assert response.status is ChatStatus.ANSWERED
    assert response.citations
    assert response.limitations
    assert len(provider.calls) == 1, "guidance-backed how_to should reach generation"
    # The stub provider fails, so this answer is the deterministic fallback.
    assert len(composer.calls) == 1
    assert response.answer in {card.claim for card in cards_in(scope)}


@pytest.mark.parametrize(
    ("question", "scope"),
    [item for item in UI_STATEMENTS if item[1] not in ANSWERABLE_SCOPES],
    ids=[q for q, s in UI_STATEMENTS if s not in ANSWERABLE_SCOPES],
)
def test_research_only_statements_are_insufficient(question: str, scope: TrainingScope) -> None:
    response, retriever, provider, composer = run(question, scope)

    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert response.limitations == []
    # Retrieval still runs; it is the answerability gate that stops the request.
    assert retriever.search_calls, "retrieval should still be attempted"
    assert provider.calls == [], "generation must not run"
    assert composer.calls == [], "deterministic fallback must not run either"


@pytest.mark.parametrize(
    ("question", "scope"),
    [item for item in UI_STATEMENTS if item[1] not in ANSWERABLE_SCOPES],
    ids=[q for q, s in UI_STATEMENTS if s not in ANSWERABLE_SCOPES],
)
def test_research_claim_text_never_appears_in_the_answer(
    question: str, scope: TrainingScope
) -> None:
    response, _, _, _ = run(question, scope)

    for card in cards_in(scope):
        assert card.claim not in response.answer


def test_leash_feasibility_is_no_longer_returned_for_a_pulling_complaint() -> None:
    """The exact P1 reproduction from the 5I-A review."""

    response, _, provider, composer = run(
        "산책할 때 리드줄을 계속 당겨요", TrainingScope.LEASH_WALKING
    )
    feasibility = cards_in(TrainingScope.LEASH_WALKING)[0]

    assert "feasibility" in feasibility.claim
    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert feasibility.claim not in response.answer
    assert provider.calls == []
    assert composer.calls == []


def test_explicit_explanation_questions_still_reach_research_evidence() -> None:
    """The finding is still available to anyone who asks about the finding."""

    question = "리드줄 보행 연구 결과가 왜 그런가요?"
    response, _, provider, _ = run(question, TrainingScope.LEASH_WALKING)

    assert classify_question_intent(question) is QuestionIntent.EXPLANATION
    assert response.status is ChatStatus.ANSWERED
    assert len(provider.calls) == 1
    assert response.answer == cards_in(TrainingScope.LEASH_WALKING)[0].claim
