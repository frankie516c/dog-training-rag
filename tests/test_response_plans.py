"""Checkpoint 5J — reviewed response plans, bound to the evidence they came from.

The plans exist to give real guidance without a model writing it. These tests hold two
lines: the guidance must actually appear for the scopes that have practice evidence, and
it must disappear the moment its binding no longer matches.
"""

import asyncio
import json
from uuid import uuid4

import pytest

from backend.app.chat_service import ChatService
from backend.app.data_validation import (
    DEFAULT_EVIDENCE_CARDS_PATH,
    DEFAULT_SOURCE_REGISTRY_PATH,
)
from backend.app.domain import (
    ChatRequest,
    ChatStatus,
    ContentLanguage,
    EvidenceCard,
    SourceRegistryEntry,
)
from backend.app.grounded import GroundedAnswerer
from backend.app.response_plans import PLANS, compose_planned_answer, plan_for
from backend.app.retrieval import SearchResult
from backend.app.scope import TrainingScope, card_scope

PLANNED_SCOPES = (TrainingScope.HOUSETRAINING, TrainingScope.CRATE_ADAPTATION)
RESEARCH_ONLY_SCOPES = (
    TrainingScope.LEASH_WALKING,
    TrainingScope.JUMPING_UP,
    TrainingScope.KENNEL_BARKING,
)


def approved_cards() -> list[EvidenceCard]:
    lines = DEFAULT_EVIDENCE_CARDS_PATH.read_text(encoding="utf-8").splitlines()
    return [EvidenceCard.model_validate_json(line) for line in lines if line.strip()]


def cards_in(scope: TrainingScope) -> list[EvidenceCard]:
    return [card for card in approved_cards() if card_scope(card) is scope]


def sources() -> dict[str, SourceRegistryEntry]:
    lines = DEFAULT_SOURCE_REGISTRY_PATH.read_text(encoding="utf-8").splitlines()
    entries = [
        SourceRegistryEntry.model_validate(json.loads(line)) for line in lines if line.strip()
    ]
    return {entry.source_id: entry for entry in entries}


class StubRetriever:
    def __init__(self, cards: list[EvidenceCard]) -> None:
        self._cards = cards

    def search(self, query: str, *, top_k: int = 20) -> list[SearchResult]:
        return [
            SearchResult(card_id=card.card_id, score=0.70 - index * 0.05, card=card)
            for index, card in enumerate(self._cards)
        ]

    def sources_by_id(self) -> dict[str, SourceRegistryEntry]:
        return sources()


class ExplodingProvider:
    """Any call is a test failure: production must not reach a provider."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    async def complete(self, messages):  # noqa: ANN001, ANN201 - test double
        self.calls.append(messages)
        raise AssertionError("the production path must not call a generation provider")


def answer_for(question: str, scope: TrainingScope, *, with_provider: bool = False):
    provider = ExplodingProvider()
    service = ChatService(
        retriever=StubRetriever(cards_in(scope)),
        grounded=GroundedAnswerer(provider=provider) if with_provider else None,
    )
    return asyncio.run(service.answer(ChatRequest(message=question))), provider


# --- binding -------------------------------------------------------------------------


def test_every_plan_binds_to_an_approved_card_and_its_current_hash() -> None:
    by_id = {card.card_id: card for card in approved_cards()}
    for plan in PLANS:
        card = by_id.get(plan.card_id)
        assert card is not None, f"plan references unknown card {plan.card_id}"
        assert plan.card_content_hash == card.content_hash()
        assert plan.language is card.claim_language


def test_an_edited_card_loses_its_plan() -> None:
    card = cards_in(TrainingScope.HOUSETRAINING)[0]
    assert plan_for(card, language=ContentLanguage.KOREAN) is not None

    edited = card.model_copy(update={"claim": card.claim + " 한 글자 추가."})
    assert edited.content_hash() != card.content_hash()
    assert plan_for(edited, language=ContentLanguage.KOREAN) is None


def test_an_unknown_card_has_no_plan() -> None:
    card = cards_in(TrainingScope.HOUSETRAINING)[0]
    other = card.model_copy(update={"card_id": uuid4()})
    assert plan_for(other, language=ContentLanguage.KOREAN) is None


def test_a_language_mismatch_has_no_plan() -> None:
    card = cards_in(TrainingScope.HOUSETRAINING)[0]
    assert plan_for(card, language=ContentLanguage.ENGLISH) is None


def test_research_only_scopes_have_no_plan() -> None:
    for scope in RESEARCH_ONLY_SCOPES:
        for card in cards_in(scope):
            assert plan_for(card, language=ContentLanguage.KOREAN) is None


def test_compose_returns_none_when_no_card_has_a_plan() -> None:
    assert (
        compose_planned_answer(
            cards_in(TrainingScope.LEASH_WALKING), language=ContentLanguage.KOREAN
        )
        is None
    )


# --- content -------------------------------------------------------------------------


def test_plans_invent_no_number() -> None:
    """No duration, count, or success rate the cards do not carry."""

    for plan in PLANS:
        rendered = plan.render()
        # Step numbering is the only digit allowed, and it lives at the line start.
        body = "\n".join(
            line.split(". ", 1)[1] if line[:1].isdigit() else line for line in rendered.splitlines()
        )
        assert not any(character.isdigit() for character in body), plan.card_id


def test_housetraining_plan_leads_with_not_punishing() -> None:
    plan = plan_for(cards_in(TrainingScope.HOUSETRAINING)[0], language=ContentLanguage.KOREAN)
    assert plan is not None
    assert "혼내지 마세요" in plan.steps[0].text
    assert "처벌은 배변 학습에 도움이 되지 않습니다" in plan.steps[0].text
    joined = " ".join(step.text for step in plan.steps)
    assert "일관되게" in joined
    assert "직후에 바로 강화" in joined
    assert "수의사" in plan.closing


def test_crate_plan_covers_the_four_reviewed_actions() -> None:
    plan = plan_for(cards_in(TrainingScope.CRATE_ADAPTATION)[0], language=ContentLanguage.KOREAN)
    assert plan is not None
    joined = " ".join(step.text for step in plan.steps)
    assert "자발적으로 드나들" in joined
    assert "긍정적인 경험" in joined
    assert "점진적으로" in joined
    assert "처벌 수단으로 사용하지 마세요" in joined


def test_every_step_quotes_its_source() -> None:
    """Checkpoint 5J-1. The hash proves the card is unchanged; it does not show that a
    step follows from it. This pairs each step with the sentence it was written from, so
    a reviewer — and this test — can check the derivation rather than take it on trust."""

    by_id = {card.card_id: card for card in approved_cards()}
    for plan in PLANS:
        card = by_id[plan.card_id]
        haystack = " ".join([card.claim, *card.limitations])
        for step in plan.steps:
            assert step.source in haystack, (plan.card_id, step.text, step.source)


def test_steps_add_no_example_the_card_does_not_carry() -> None:
    """Concrete examples were removed in 5J-1: the cards say "강화" and "긍정적 경험",
    not which treat or blanket to use."""

    for plan in PLANS:
        rendered = " ".join(step.text for step in plan.steps)
        for invented in ("간식", "담요", "칭찬", "장난감"):
            assert invented not in rendered, (plan.card_id, invented)


def test_rendered_plan_opens_with_empathy_then_numbered_steps() -> None:
    for plan in PLANS:
        rendered = plan.render()
        first_line = rendered.splitlines()[0]
        assert first_line == plan.opening
        assert not first_line.startswith("1.")
        assert "지금은 이렇게 해보세요." in rendered
        for index, step in enumerate(plan.steps, 1):
            assert f"{index}. {step.text}" in rendered


# --- pipeline ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "scope"),
    [
        ("배변 실수를 나중에 발견했어요", TrainingScope.HOUSETRAINING),
        ("응가를 아무 데나 해요", TrainingScope.HOUSETRAINING),
        ("이동장을 무서워해요", TrainingScope.CRATE_ADAPTATION),
    ],
)
def test_guidance_questions_get_the_planned_answer(question: str, scope: TrainingScope) -> None:
    response, provider = answer_for(question, scope, with_provider=True)

    assert response.status is ChatStatus.ANSWERED
    assert provider.calls == []
    plan = plan_for(cards_in(scope)[0], language=ContentLanguage.KOREAN)
    assert plan is not None
    assert response.answer == plan.render()
    assert response.citations
    assert response.limitations


def test_housetraining_answer_starts_by_not_punishing() -> None:
    response, _ = answer_for("배변 실수를 나중에 발견했어요", TrainingScope.HOUSETRAINING)
    assert response.status is ChatStatus.ANSWERED
    first_step = next(line for line in response.answer.splitlines() if line.startswith("1. "))
    assert "혼내지 마세요" in first_step


def test_leash_pulling_how_to_stays_insufficient() -> None:
    response, provider = answer_for(
        "리드줄을 자꾸 당겨요. 어떻게 훈련하나요?", TrainingScope.LEASH_WALKING, with_provider=True
    )
    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert provider.calls == []


def test_urgent_ingestion_short_circuits_before_retrieval() -> None:
    provider = ExplodingProvider()
    service = ChatService(
        retriever=StubRetriever(cards_in(TrainingScope.HOUSETRAINING)),
        grounded=GroundedAnswerer(provider=provider),
    )
    response = asyncio.run(
        service.answer(ChatRequest(message="강아지가 초콜릿을 먹었어요. 어떻게 해야 하나요?"))
    )
    assert response.safety_notice is not None
    assert response.safety_notice.level.value == "urgent"
    assert response.status is ChatStatus.INSUFFICIENT_EVIDENCE
    assert response.citations == []
    assert provider.calls == []


def test_answered_citations_match_the_cards_the_plan_used() -> None:
    for question, scope in (
        ("배변 실수를 나중에 발견했어요", TrainingScope.HOUSETRAINING),
        ("이동장을 무서워해요", TrainingScope.CRATE_ADAPTATION),
    ):
        response, _ = answer_for(question, scope)
        plan = plan_for(cards_in(scope)[0], language=ContentLanguage.KOREAN)
        assert plan is not None
        cited_ids = {citation.card_id for citation in response.citations}
        assert cited_ids == {plan.card_id}

        by_id = {card.card_id: card for card in approved_cards()}
        for citation in response.citations:
            card = by_id[citation.card_id]
            assert card.content_hash() == plan.card_content_hash
            assert set(response.limitations) <= set(card.limitations)


def test_the_application_does_not_wire_the_answerability_judging_path() -> None:
    """Checkpoint 5K reintroduces a provider, but only as a rephraser.

    The 5I-A path, where the model also decided whether the evidence could answer, stays
    unwired: three prompt experiments showed a 4B-class model cannot hold that judgement
    and the wording at once.
    """

    import inspect

    from backend.app import main

    source = inspect.getsource(main)
    assert "GroundedAnswerer" not in source
    assert "grounded=" not in source
    assert "phraser=_create_plan_phraser(settings)" in source


def test_no_provider_configured_still_answers_from_the_reviewed_plan() -> None:
    """An unconfigured provider costs prose, not correctness."""

    from backend.app.config import Settings
    from backend.app.main import _create_plan_phraser

    settings = Settings(generation_base_url=None, generation_model=None)
    assert _create_plan_phraser(settings) is None

    response, _ = answer_for("배변 실수를 나중에 발견했어요", TrainingScope.HOUSETRAINING)
    assert response.status is ChatStatus.ANSWERED
    plan = plan_for(cards_in(TrainingScope.HOUSETRAINING)[0], language=ContentLanguage.KOREAN)
    assert plan is not None
    assert response.answer == plan.render()
