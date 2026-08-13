"""What a question is asking for, and whether the retrieved evidence can answer it.

Sharing a topic is not the same as answering a question. A leash-walking feasibility
study says a class could be run for older owners; it says nothing about how to stop a dog
pulling. A functional-analysis study explains why jumping is maintained; its own
limitation forbids turning it into an owner procedure. A kennel counterconditioning pilot
is not a home barking protocol.

So two typed contracts sit between retrieval and answering:

* `QuestionIntent`  — what the user asked for (rule-based, no model).
* `EvidenceKind`    — what a card is, derived from its topic and tags.

`CAPABILITIES` maps the second to the first. A card that cannot serve the intent is
dropped before generation *and* before the deterministic fallback, so a how_to question
with no procedural evidence returns insufficient_evidence rather than a research summary.

Neither contract is exposed in the API, and neither hardcodes a card_id.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from backend.app.domain import EvidenceCard
from backend.app.text_match import compile_terms, normalize


class QuestionIntent(StrEnum):
    """What the question asks the evidence to do. Internal only."""

    HOW_TO = "how_to"
    COMPARISON = "comparison"
    EXPLANATION = "explanation"


class EvidenceKind(StrEnum):
    """What a reviewed card is, for the purpose of answering."""

    #: Guidance that states principles or a process an owner can follow.
    PRACTICE_GUIDANCE = "practice_guidance"
    #: A study result. Describes what was observed, not what an owner should do.
    RESEARCH_FINDING = "research_finding"


_GUIDANCE_INTENTS = frozenset({QuestionIntent.HOW_TO, QuestionIntent.EXPLANATION})
# A finding can be explained and compared. It cannot authorize a procedure.
_FINDING_INTENTS = frozenset({QuestionIntent.COMPARISON, QuestionIntent.EXPLANATION})

CAPABILITIES: dict[EvidenceKind, frozenset[QuestionIntent]] = {
    EvidenceKind.PRACTICE_GUIDANCE: _GUIDANCE_INTENTS,
    EvidenceKind.RESEARCH_FINDING: _FINDING_INTENTS,
}


# --------------------------------------------------------------------------------------
# Question intent
# --------------------------------------------------------------------------------------
#
# Comparison is checked before how_to: "전자 목줄이 보상 훈련보다 더 효과적인가요?" contains
# 훈련 but is a comparison, not a request for steps.
#
# A behaviour complaint with no interrogative marker ("산책할 때 리드줄을 계속 당겨요") is an
# *implicit* how_to. Owners describe the problem and expect what to do about it; they rarely
# type "어떻게 고치나요". Reading those as explanation was measurably wrong: it let a
# leash-walking feasibility study be returned as the answer to a pulling complaint, which is
# the exact mismatch this contract exists to prevent. Explicit 왜/원인 questions are still
# explanation, so the honest "this evidence does not show that" answer stays reachable for
# anyone who actually asks for the finding.

_COMPARISON = compile_terms(
    (
        "더 효과",
        "더 효율",
        "보다 나",
        "보다 낫",
        "낫나요",
        "비교",
        "차이가",
        "어느 쪽",
        "어느게",
        "어느 게",
        "vs",
        "more effective",
        "better than",
        "compared",
    )
)

_HOW_TO = compile_terms(
    (
        "어떻게",
        "어떡",
        "방법",
        "고치",
        "교정",
        "가르치",
        "훈련시",
        "시켜야",
        "해야 하나요",
        "야 하나요",
        "멈추게",
        "못하게",
        "없애",
        "줄이려",
        "그만두게",
        "how to",
        "how do i",
        "what should i do",
    )
)

_EXPLANATION = compile_terms(
    ("왜", "이유", "원인", "무엇인가", "뭔가요", "뭐예요", "why", "what is", "what causes")
)

# Recurrence adverbs, "anywhere" complaints, fear reports and trigger phrases. Each marks a
# described problem rather than a question about a finding.
_PROBLEM_STATEMENT = compile_terms(
    (
        "계속",
        "자꾸",
        "자주",
        "맨날",
        "만날",
        "항상",
        "아무 데나",
        "아무데나",
        "아무 곳",
        "무서워",
        "두려워",
        "겁내",
        "만 보면",
        "만 오면",
    )
)


def classify_question_intent(message: str) -> QuestionIntent:
    """Classify a question deterministically. No model, no network.

    Order matters. Explicit markers win over the implicit reading, so a 왜/원인 question
    about a recurring behaviour stays an explanation.
    """

    text = normalize(message)
    if _COMPARISON.search(text):
        return QuestionIntent.COMPARISON
    if _HOW_TO.search(text):
        return QuestionIntent.HOW_TO
    if _EXPLANATION.search(text):
        return QuestionIntent.EXPLANATION
    if _PROBLEM_STATEMENT.search(text):
        return QuestionIntent.HOW_TO
    return QuestionIntent.EXPLANATION


# --------------------------------------------------------------------------------------
# Evidence kind
# --------------------------------------------------------------------------------------
#
# Positive markers identify guidance; everything else is treated as a research finding.
# The default is the fail-closed direction: an unrecognised card can never authorize a
# procedure. Adding a guidance card means adding its marker here on purpose.

_GUIDANCE_MARKERS = compile_terms(
    ("management", "gradual exposure", "기초 원칙", "관리 원칙", "커리큘럼", "교육 과정")
)


def card_evidence_kind(card: EvidenceCard) -> EvidenceKind:
    """Decide what a card is from its topic and tags only."""

    text = normalize(" ".join((card.topic, *card.tags)))
    if _GUIDANCE_MARKERS.search(text):
        return EvidenceKind.PRACTICE_GUIDANCE
    return EvidenceKind.RESEARCH_FINDING


def card_supports_intent(card: EvidenceCard, intent: QuestionIntent) -> bool:
    return intent in CAPABILITIES[card_evidence_kind(card)]


def usable_for_intent(
    cards: Iterable[EvidenceCard],
    intent: QuestionIntent,
) -> list[EvidenceCard]:
    """Keep only the cards that can answer this kind of question, in the given order."""

    return [card for card in cards if card_supports_intent(card, intent)]
