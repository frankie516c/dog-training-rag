"""Checkpoint 5K — the model may reword the reviewed plan and nothing else.

Every rejection case below was produced by qwen3.5:9b on this exact plan during the
pre-implementation smoke calls. They are not hypothetical prompt-injection scenarios;
they are what the model does when asked to be warm.
"""

import asyncio
import json
from pathlib import Path

import pytest

from backend.app.domain import ContentLanguage, EvidenceCard
from backend.app.plan_phraser import PlanPhraser
from backend.app.plan_phrasing import (
    PhrasingVerdict,
    build_phrasing_messages,
    validate_phrasing,
)
from backend.app.response_plans import plan_for
from backend.app.scope import TrainingScope, card_scope

CARDS_PATH = Path("data/processed/evidence_cards.jsonl")
QUESTION = "배변 실수를 나중에 발견했어요"


def card_in(scope: TrainingScope) -> EvidenceCard:
    cards = [
        EvidenceCard.model_validate_json(line)
        for line in CARDS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return next(card for card in cards if card_scope(card) is scope)


@pytest.fixture
def housetraining():
    card = card_in(TrainingScope.HOUSETRAINING)
    plan = plan_for(card, language=ContentLanguage.KOREAN)
    assert plan is not None
    return card, plan


def payload(answer: str, card: EvidenceCard, **extra) -> str:
    return json.dumps(
        {"answer": answer, "used_card_ids": [str(card.card_id)], **extra}, ensure_ascii=False
    )


def check(answer: str, housetraining, message: str = QUESTION):
    card, plan = housetraining
    return validate_phrasing(payload(answer, card), message=message, card=card, plan=plan)


# --- what may cross the boundary -----------------------------------------------------


def test_the_request_carries_evidence_and_nothing_else(housetraining) -> None:
    card, plan = housetraining
    messages = build_phrasing_messages(
        message=QUESTION, response_language=ContentLanguage.KOREAN, card=card, plan=plan
    )
    sent = " ".join(part["content"] for part in messages)

    assert card.claim in sent
    assert plan.steps[0].text in sent
    for leaked in ("http", "pressbooks", "qdrant", "api_key", "Bearer", "C:\\", "locator"):
        assert leaked not in sent, leaked


def test_an_answerable_field_is_ignored_not_obeyed(housetraining) -> None:
    """Answerability was decided before this module. A model vote does not reopen it."""

    card, plan = housetraining
    raw = payload("나중에 발견한 실수는 혼내지 마세요.", card, answerable=False)
    result = validate_phrasing(raw, message=QUESTION, card=card, plan=plan)
    assert result.verdict is PhrasingVerdict.ACCEPTED


# --- the three errors this checkpoint was written for --------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "원하는 장소에서 배설한 직후에 바로 칭찬해 주세요.",
        "배설 직후에 간식으로 강화해 주세요.",
        "잘 했을 때 장난감을 주며 강화해 주세요.",
    ],
)
def test_a_reinforcer_the_card_does_not_name_is_rejected(answer: str, housetraining) -> None:
    """The card states when to reinforce. 5J-1 removed "칭찬이나 간식" for this reason."""

    result = check(answer, housetraining)
    assert result.verdict is PhrasingVerdict.OUT_OF_PLAN
    assert "reinforcer" in (result.reason or "")


@pytest.mark.parametrize(
    "answer",
    [
        "혼내지 않으셔도 되니 걱정하지 마세요.",
        "너무 걱정 마세요. 사후 처벌은 도움이 되지 않습니다.",
        "일관되게 관리하시면 금방 좋아집니다.",
        "안심하셔도 됩니다. 사후 처벌은 도움이 되지 않습니다.",
    ],
)
def test_reassurance_the_evidence_does_not_support_is_rejected(answer: str, housetraining) -> None:
    result = check(answer, housetraining)
    assert result.verdict is PhrasingVerdict.OUT_OF_PLAN
    assert "reassurance" in (result.reason or "")


@pytest.mark.parametrize(
    "answer",
    [
        "시간이 지난 뒤의 처벌은 배변 학습을 방해합니다.",
        "사후 처벌은 배변 습관을 악화시킵니다.",
        "나중에 혼내면 오히려 더 나빠집니다.",
        "지난 실수를 혼내면 역효과가 납니다.",
    ],
)
def test_escalating_does_not_help_into_active_harm_is_rejected(answer: str, housetraining) -> None:
    """The card says punishment does not help. Not helping and harming are not the same
    claim, and only one of them is in the evidence."""

    result = check(answer, housetraining)
    assert result.verdict is PhrasingVerdict.OUT_OF_PLAN
    assert "escalated" in (result.reason or "")


# --- the rest of the boundary --------------------------------------------------------


def test_the_approved_meaning_is_accepted(housetraining) -> None:
    """The allowed claim, stated warmly, in several shapes."""

    for answer in (
        "나중에 발견하신 실수는 혼내지 마세요. 시간이 지난 뒤의 처벌은 배변 학습에 "
        "도움이 되지 않습니다. 강아지의 나이에 맞춰 배변 관리를 일관되게 유지해 주시고, "
        "원하는 장소에서 배설한 직후에 바로 강화해 주세요.",
        "이미 시간이 지난 실수를 혼내는 것은 배변 학습에 도움이 되지 않습니다. "
        "대신 원하는 장소에서 배설한 직후에 바로 강화해 주세요.",
    ):
        result = check(answer, housetraining)
        assert result.verdict is PhrasingVerdict.ACCEPTED, result.reason
        assert result.answer == answer


def test_a_situation_the_question_did_not_state_is_rejected(housetraining) -> None:
    """ "발견하셨군요" is a claim about the reader, and only their question establishes it."""

    answer = "실수를 발견하셨군요. 혼내지 마시고 배변 관리를 일관되게 유지해 주세요."
    assert check(answer, housetraining, message=QUESTION).verdict is PhrasingVerdict.ACCEPTED
    result = check(answer, housetraining, message="응가를 아무 데나 해요")
    assert result.verdict is PhrasingVerdict.OUT_OF_PLAN
    assert "did not state" in (result.reason or "")


def test_a_schedule_the_card_declines_to_give_is_rejected(housetraining) -> None:
    for answer in (
        "보통 며칠이면 좋아집니다.",
        "하루에 세 번 정도 확인해 주세요.",
    ):
        assert check(answer, housetraining).verdict is PhrasingVerdict.OUT_OF_PLAN


def test_numbers_and_latin_outside_the_plan_are_rejected(housetraining) -> None:
    assert check("성공률은 80% 정도입니다.", housetraining).verdict is PhrasingVerdict.OUT_OF_PLAN
    assert (
        check("원하는 곳에서 correctly 했다면 강화해 주세요.", housetraining).verdict
        is PhrasingVerdict.OUT_OF_PLAN
    )


def test_an_exclamation_is_rejected(housetraining) -> None:
    assert (
        check("혼내지 마세요! 바로 강화해 주세요.", housetraining).verdict
        is PhrasingVerdict.OUT_OF_PLAN
    )


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"answer": "혼내지 마세요.", "used_card_ids": []}\n```',
        "설명: 답변입니다",
        '{"answer": "", "used_card_ids": ["6e73ad54-2c9f-48da-a261-076df3087707"]}',
        '{"answer": "혼내지 마세요."}',
        '{"answer": "혼내지 마세요.", "used_card_ids": ["not-a-uuid"]}',
        '{"answer": "혼내지 마세요.", "used_card_ids": ["11111111-1111-1111-1111-111111111111"]}',
    ],
)
def test_unusable_payloads_are_invalid(raw: str, housetraining) -> None:
    card, plan = housetraining
    result = validate_phrasing(raw, message=QUESTION, card=card, plan=plan)
    assert result.verdict is PhrasingVerdict.INVALID
    assert result.answer is None


# --- the phraser never raises --------------------------------------------------------


class BrokenProvider:
    async def complete(self, messages, *, options=None):  # noqa: ANN001, ANN201
        raise RuntimeError("synthetic provider failure")


class TalkativeProvider:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.options: dict | None = None

    async def complete(self, messages, *, options=None):  # noqa: ANN001, ANN201
        self.options = options
        return self.reply


def test_a_provider_failure_is_a_rejection_not_an_exception(housetraining) -> None:
    card, plan = housetraining
    phraser = PlanPhraser(provider=BrokenProvider())
    result = asyncio.run(
        phraser.phrase(
            message=QUESTION, response_language=ContentLanguage.KOREAN, card=card, plan=plan
        )
    )
    assert result.verdict is PhrasingVerdict.INVALID
    assert result.answer is None


def test_reasoning_effort_is_sent_when_configured(housetraining) -> None:
    card, plan = housetraining
    provider = TalkativeProvider(payload("혼내지 마세요.", card))
    phraser = PlanPhraser(provider=provider, reasoning_effort="none")
    asyncio.run(
        phraser.phrase(
            message=QUESTION, response_language=ContentLanguage.KOREAN, card=card, plan=plan
        )
    )
    assert provider.options is not None
    assert provider.options["reasoning_effort"] == "none"
    assert provider.options["temperature"] == 0.0
