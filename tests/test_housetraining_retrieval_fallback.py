"""Checkpoint 5J-1 — one canonical retry, for one scope, one intent, and only when empty.

"응가를 아무 데나 해요" routes to housetraining and reads as a how_to, but the colloquial
wording scores its own card at 0.378 against a 0.40 minimum, so the user got nothing. The
retry asks the corpus in its own words. These tests hold its blast radius: it must fire
for that case and stay silent everywhere else, and it must not change the threshold, the
gates or which card ends up cited.
"""

import asyncio
import json

import pytest

from backend.app.chat_service import HOUSETRAINING_CANONICAL_QUERY, ChatService
from backend.app.data_validation import (
    DEFAULT_EVIDENCE_CARDS_PATH,
    DEFAULT_SOURCE_REGISTRY_PATH,
)
from backend.app.domain import ChatRequest, ChatStatus, EvidenceCard, SourceRegistryEntry
from backend.app.grounded import GroundedAnswerer
from backend.app.response_plans import plan_for
from backend.app.retrieval import SearchResult
from backend.app.scope import TrainingScope, card_scope

# Scores measured against the built index, rounded down. The colloquial question puts the
# housetraining card below the threshold; the canonical query puts it above.
COLLOQUIAL_SCORES = {
    TrainingScope.JUMPING_UP: 0.43,
    TrainingScope.LEASH_WALKING: 0.39,
    TrainingScope.KENNEL_BARKING: 0.39,
    TrainingScope.CRATE_ADAPTATION: 0.37,
    TrainingScope.HOUSETRAINING: 0.37,
    TrainingScope.AVERSIVE_OR_ECOLLAR: 0.33,
}
CANONICAL_SCORES = dict(COLLOQUIAL_SCORES) | {TrainingScope.HOUSETRAINING: 0.62}


def all_cards() -> list[EvidenceCard]:
    lines = DEFAULT_EVIDENCE_CARDS_PATH.read_text(encoding="utf-8").splitlines()
    return [EvidenceCard.model_validate_json(line) for line in lines if line.strip()]


def sources() -> dict[str, SourceRegistryEntry]:
    lines = DEFAULT_SOURCE_REGISTRY_PATH.read_text(encoding="utf-8").splitlines()
    entries = [
        SourceRegistryEntry.model_validate(json.loads(line)) for line in lines if line.strip()
    ]
    return {entry.source_id: entry for entry in entries}


class ScoringRetriever:
    """Returns every card, scored by the table for the query it is given.

    Modelling the whole corpus rather than one scope is the point: the fallback must be
    seen to pick the housetraining card out of a full result set, not to be handed it.
    """

    def __init__(self, first_query_scores: dict[TrainingScope, float] | None = None) -> None:
        self.queries: list[str] = []
        self._cards = all_cards()
        self._first_query_scores = first_query_scores or COLLOQUIAL_SCORES

    def search(self, query: str, *, top_k: int = 20) -> list[SearchResult]:
        self.queries.append(query)
        table = (
            CANONICAL_SCORES if query == HOUSETRAINING_CANONICAL_QUERY else self._first_query_scores
        )
        results = [
            SearchResult(card_id=card.card_id, score=table[card_scope(card)], card=card)
            for card in self._cards
        ]
        return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]

    def sources_by_id(self) -> dict[str, SourceRegistryEntry]:
        return sources()


class ExplodingProvider:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def complete(self, messages):  # noqa: ANN001, ANN201 - test double
        self.calls.append(messages)
        raise AssertionError("the production path must not call a generation provider")


def ask(message: str, *, first_query_scores: dict[TrainingScope, float] | None = None):
    retriever = ScoringRetriever(first_query_scores)
    provider = ExplodingProvider()
    service = ChatService(retriever=retriever, grounded=GroundedAnswerer(provider=provider))
    response = asyncio.run(service.answer(ChatRequest(message=message)))
    return response, retriever, provider


def test_colloquial_question_retries_once_and_answers_from_the_housetraining_card() -> None:
    response, retriever, provider = ask("응가를 아무 데나 해요")

    assert retriever.queries == ["응가를 아무 데나 해요", HOUSETRAINING_CANONICAL_QUERY]
    assert response.status is ChatStatus.ANSWERED
    assert len(response.citations) == 1

    card = next(card for card in all_cards() if card_scope(card) is TrainingScope.HOUSETRAINING)
    assert response.citations[0].card_id == card.card_id
    plan = plan_for(card, language=response.answer_language)
    assert plan is not None
    assert response.answer == plan.render()
    assert provider.calls == []


def test_without_the_retry_the_same_question_would_have_had_nothing() -> None:
    """Guards the premise: the first search really is below the threshold."""

    retriever = ScoringRetriever()
    results = retriever.search("응가를 아무 데나 해요")
    housetraining = [
        result for result in results if card_scope(result.card) is TrainingScope.HOUSETRAINING
    ]
    assert housetraining
    assert all(result.score < 0.40 for result in housetraining)


def test_explicit_phrasing_still_answers_without_needing_the_retry() -> None:
    response, retriever, provider = ask("응가를 아무 데나 해요. 어떻게 훈련하나요?")

    assert response.status is ChatStatus.ANSWERED
    assert len(response.citations) == 1
    assert provider.calls == []
    # Two queries here too: this phrasing scores the same in the stub table. What matters
    # is that the retry is what rescues it and that only one card is cited.
    assert retriever.queries[0] == "응가를 아무 데나 해요. 어떻게 훈련하나요?"


def test_a_question_that_already_retrieved_does_not_retry() -> None:
    """The card clears the threshold for this phrasing, so there is nothing to rescue."""

    response, retriever, provider = ask(
        "배변 실수를 나중에 발견했어요", first_query_scores=CANONICAL_SCORES
    )

    assert retriever.queries == ["배변 실수를 나중에 발견했어요"]
    assert response.status is ChatStatus.ANSWERED
    assert len(response.citations) == 1
    assert provider.calls == []


@pytest.mark.parametrize(
    "message",
    ["강아지가 똥을 먹어요", "응가 냄새가 심해요"],
)
def test_out_of_scope_questions_never_reach_retrieval_or_the_retry(message: str) -> None:
    response, retriever, provider = ask(message)

    assert retriever.queries == []
    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert provider.calls == []


def test_a_housetraining_explanation_does_not_get_the_how_to_retry() -> None:
    response, retriever, provider = ask("배변 성공까지 며칠 걸리나요?")

    assert retriever.queries == ["배변 성공까지 며칠 걸리나요?"]
    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert provider.calls == []


@pytest.mark.parametrize(
    "message",
    [
        "리드줄을 계속 당겨요",
        "사람만 보면 뛰어올라요",
        "켄넬 안에서 계속 짖어요",
        "이동장에 들어가는 걸 무서워해요",
        "혐오 자극 훈련 연구에서 확인된 결과를 설명해주세요.",
        "전자 목줄이 보상 훈련보다 더 효과적인가요?",
    ],
)
def test_other_scopes_search_exactly_once(message: str) -> None:
    """No other scope gained a retry, so their retrieval call count is unchanged."""

    _, retriever, provider = ask(message)

    assert retriever.queries == [message]
    assert provider.calls == []
