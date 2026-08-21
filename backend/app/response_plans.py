"""Curated procedural answers, bound to the exact reviewed evidence they came from.

Checkpoint 5H made answers safe by emitting reviewed claim text verbatim, which cannot
reverse a comparison or move a negation. It also made them unhelpful: asked "배변 실수를
나중에 발견했을 때 어떻게 해야 하나요", the service replied with a textbook sentence about
what does not help, and the human review of the prompt experiments scored that 2 out of 5.

Three attempts to fix it with a generation prompt failed in sequence — v1.1 answered
without using the evidence it had, v1.2 granted a reversal it was asked for, v1.2.1
preserved direction but refused the question. See experiments/prompt_eval_v0 for the
records. This module takes the other route: the guidance is written once, reviewed by a
human, and stored as fixed sentences. No model rewrites it at request time.

What keeps it honest is the binding. A plan names the card it was written from, that
card's content hash, and the language it is written in. If the card's reviewed text
changes by one character its hash changes, `plan_for` stops matching, and the caller falls
back to 5H composition. A plan can never drift away from its evidence unnoticed, because
nothing tries to re-derive it.

Only the two scopes with PRACTICE_GUIDANCE evidence have plans. Leash walking, jumping up
and kennel barking hold research findings only; a how-to there stays
`insufficient_evidence`, exactly as before.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from backend.app.domain import ContentLanguage, EvidenceCard

STEP_SEPARATOR = "\n"
BLOCK_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class PlanStep:
    """One action, and the sentence of the card it was written from.

    ``source`` is a substring of the bound card's claim or of one of its limitations. It
    is what a reviewer reads next to the step, and what
    `tests/test_response_plans.py::test_every_step_quotes_its_source` checks it against.
    The hash binding proves the card has not changed; it says nothing about whether the
    step follows from it. Only the review does that, and the pairing below is what was
    reviewed.
    """

    text: str
    source: str


@dataclass(frozen=True)
class ResponsePlan:
    """A reviewed, fixed answer for one card in one language.

    Nothing here adds a duration, a count, a success rate, a cause or a prescription the
    card does not carry.
    """

    card_id: UUID
    card_content_hash: str
    language: ContentLanguage
    #: One short sentence acknowledging the situation. No advice, no reassurance.
    opening: str
    #: The line that introduces the steps.
    lead_in: str
    #: Ordered actions. The first one carries the card's strongest instruction.
    steps: tuple[PlanStep, ...]
    #: What the evidence does not settle. Drawn from the card's limitations.
    closing: str

    def render(self) -> str:
        numbered = STEP_SEPARATOR.join(
            f"{index}. {step.text}" for index, step in enumerate(self.steps, 1)
        )
        return BLOCK_SEPARATOR.join((self.opening, f"{self.lead_in}\n{numbered}", self.closing))


HOUSETRAINING_KO = ResponsePlan(
    card_id=UUID("6e73ad54-2c9f-48da-a261-076df3087707"),
    card_content_hash="sha256:45293577813c90550c5b54f27283c72b7414990ecf10bad0dbfb3aa506201cad",
    language=ContentLanguage.KOREAN,
    opening="치우고 나서야 실수를 발견하면 속상하고 막막하실 수 있어요.",
    lead_in="지금은 이렇게 해보세요.",
    steps=(
        PlanStep(
            text="나중에 발견한 실수는 혼내지 마세요. 시간이 지난 뒤의 처벌은 배변 학습에 "
            "도움이 되지 않습니다.",
            source="사후에 발견한 실수를 처벌하는 방식은 학습에 도움이 되지 않는다",
        ),
        PlanStep(
            text="강아지의 나이에 맞춰 배변 관리를 일관되게 유지해 주세요.",
            source="배변 훈련의 기초를 나이에 맞춘 일관된 관리",
        ),
        PlanStep(
            text="원하는 장소에서 배설한 직후에 바로 강화해 주세요.",
            source="원하는 장소에서 배설한 직후의 강화",
        ),
    ),
    closing=(
        "얼마 만에 좋아지는지는 확인된 기간이 따로 없습니다. 실수가 계속 이어진다면 훈련 "
        "문제로만 보지 마시고 수의사에게 건강 상태를 먼저 확인해 주세요."
    ),
)

CRATE_ADAPTATION_KO = ResponsePlan(
    card_id=UUID("7f84be65-d3a0-43e1-94c7-2cc84b698808"),
    card_content_hash="sha256:b2ba0ab8389e30113af10ba697cb7d0f153071e4f8f05f6a67a857d9157f5878",
    language=ContentLanguage.KOREAN,
    opening="이동장 앞에서 굳어버리는 모습을 보면 마음이 쓰이시죠.",
    lead_in="지금은 이렇게 해보세요.",
    steps=(
        PlanStep(
            text="강아지가 자발적으로 드나들 수 있게 해 주세요.",
            source="개가 자발적으로 드나들며",
        ),
        PlanStep(
            text="이동장 안에서 긍정적인 경험을 쌓게 해 주세요.",
            source="긍정적 경험을 쌓고",
        ),
        PlanStep(
            text="머무는 시간을 점진적으로 늘려 주세요.",
            source="머무는 시간을 점진적으로 늘리는 과정",
        ),
        PlanStep(
            text="이동장을 처벌 수단으로 사용하지 마세요.",
            source="crate를 처벌 수단으로 사용하지 않도록",
        ),
    ),
    closing=(
        "적정 수용 시간이나 개별 진행 속도는 확인된 기준이 없습니다. 불안이나 울음이 "
        "심하다면 이동장 훈련만으로 해결하려 하지 마시고 수의사와 상의해 주세요."
    ),
)

PLANS: tuple[ResponsePlan, ...] = (HOUSETRAINING_KO, CRATE_ADAPTATION_KO)


def plan_for(card: EvidenceCard, *, language: ContentLanguage) -> ResponsePlan | None:
    """Return the reviewed plan for this exact card, or None.

    None on any mismatch — unknown card, edited card, other language. The caller treats
    None as "no procedural answer available" and falls back to claim composition, so a
    stale plan is never shown.
    """

    content_hash = card.content_hash()
    for plan in PLANS:
        if (
            plan.card_id == card.card_id
            and plan.card_content_hash == content_hash
            and plan.language is language
        ):
            return plan
    return None


def select_plan(
    cards: Sequence[EvidenceCard], *, language: ContentLanguage
) -> tuple[EvidenceCard, ResponsePlan] | None:
    """Return the first card that has a matching plan, with that plan.

    The caller cites exactly this card and nothing else. None is the fail-closed path:
    no plan means no procedural answer.
    """

    for card in cards:
        plan = plan_for(card, language=language)
        if plan is not None:
            return card, plan
    return None


def compose_planned_answer(
    cards: Sequence[EvidenceCard], *, language: ContentLanguage
) -> tuple[str, list[EvidenceCard]] | None:
    """Rendered plan and its card, or None. Kept for callers that only need the text."""

    selected = select_plan(cards, language=language)
    if selected is None:
        return None
    card, plan = selected
    return plan.render(), [card]
