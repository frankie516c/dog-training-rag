from collections import Counter

import pytest

from backend.app.answerability import (
    CAPABILITIES,
    EvidenceKind,
    QuestionIntent,
    card_evidence_kind,
    card_supports_intent,
    classify_question_intent,
    usable_for_intent,
)
from backend.app.data_validation import DEFAULT_EVIDENCE_CARDS_PATH
from backend.app.domain import EvidenceCard


def load_approved_cards() -> list[EvidenceCard]:
    lines = DEFAULT_EVIDENCE_CARDS_PATH.read_text(encoding="utf-8").splitlines()
    return [EvidenceCard.model_validate_json(line) for line in lines if line.strip()]


def card_by_topic_fragment(fragment: str) -> EvidenceCard:
    matches = [card for card in load_approved_cards() if fragment in card.topic]
    assert len(matches) == 1, f"expected exactly one card matching {fragment!r}"
    return matches[0]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("리드줄 당김을 어떻게 고치나요?", QuestionIntent.HOW_TO),
        ("배변 훈련 방법을 알려주세요", QuestionIntent.HOW_TO),
        ("점프를 못하게 하려면 어떡하죠", QuestionIntent.HOW_TO),
        ("배변 실수를 나중에 발견했는데 혼내야 하나요?", QuestionIntent.HOW_TO),
        ("How do I stop leash pulling?", QuestionIntent.HOW_TO),
        ("전자 목줄이 보상 훈련보다 더 효과적인가요?", QuestionIntent.COMPARISON),
        ("e-collar와 보상 훈련의 차이가 뭔가요", QuestionIntent.COMPARISON),
        ("어느 쪽이 낫나요", QuestionIntent.COMPARISON),
        ("강아지가 왜 점프하나요?", QuestionIntent.EXPLANATION),
        ("짖는 원인이 뭔가요", QuestionIntent.EXPLANATION),
        # Explicit 왜 beats the recurrence adverb.
        ("강아지가 왜 계속 짖나요?", QuestionIntent.EXPLANATION),
        ("점프 행동의 기능을 설명해 주세요", QuestionIntent.EXPLANATION),
        # Implicit how_to: a described problem with no interrogative marker.
        ("산책할 때 리드줄을 계속 당겨요.", QuestionIntent.HOW_TO),
    ],
)
def test_question_intent_is_classified_deterministically(
    message: str, expected: QuestionIntent
) -> None:
    assert classify_question_intent(message) is expected
    assert classify_question_intent(message) is classify_question_intent(message)


def test_comparison_wins_over_the_training_word() -> None:
    """훈련 appears in the e-collar comparison; it must not read as a how_to request."""

    assert (
        classify_question_intent("전자 목줄이 보상 훈련보다 더 효과적인가요?")
        is QuestionIntent.COMPARISON
    )


@pytest.mark.parametrize(
    "message",
    [
        # The 더-less phrasings that leaked to generation before this rule existed.
        "전자 목줄이 보상 훈련보다 효과적인가요?",
        "전자 목줄이 보상 훈련보다 효율적인가요?",
        "전자 목줄이 보상 훈련보다 더 효과적인가요?",
        "전자 목줄이 보상 훈련보다 나은가요?",
        "전자 목줄이 보상 훈련보다 효과가 좋나요?",
        "전자 목줄이 보상 훈련에 비해 효과적인가요?",
    ],
)
def test_comparative_training_questions_are_comparison(message: str) -> None:
    assert classify_question_intent(message) is QuestionIntent.COMPARISON


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # A metric with nothing to compare against.
        ("효과적인 배변 훈련 방법을 알려주세요.", QuestionIntent.HOW_TO),
        ("보상 훈련은 어떻게 하나요?", QuestionIntent.HOW_TO),
        ("전자 목줄 연구 결과가 왜 그런가요?", QuestionIntent.EXPLANATION),
        ("산책할 때 리드줄을 계속 당겨요.", QuestionIntent.HOW_TO),
        ("강아지가 왜 계속 짖나요?", QuestionIntent.EXPLANATION),
        # 보다 as the verb "to see", with no metric.
        ("사람을 보다가 자꾸 뛰어올라요.", QuestionIntent.HOW_TO),
        ("강아지를 보다 보면 왜 그런지 궁금해요.", QuestionIntent.EXPLANATION),
    ],
)
def test_half_a_comparison_is_not_a_comparison(message: str, expected: QuestionIntent) -> None:
    assert classify_question_intent(message) is expected


def test_research_findings_cannot_authorize_a_procedure() -> None:
    assert QuestionIntent.HOW_TO not in CAPABILITIES[EvidenceKind.RESEARCH_FINDING]
    assert QuestionIntent.COMPARISON in CAPABILITIES[EvidenceKind.RESEARCH_FINDING]
    assert QuestionIntent.EXPLANATION in CAPABILITIES[EvidenceKind.RESEARCH_FINDING]


@pytest.mark.parametrize(
    ("topic_fragment", "expected"),
    [
        ("배변 훈련의 기초 관리 원칙", EvidenceKind.PRACTICE_GUIDANCE),
        ("crate 적응의 기초 원칙", EvidenceKind.PRACTICE_GUIDANCE),
        ("리드줄 보행 프로그램", EvidenceKind.RESEARCH_FINDING),
        ("사람에게 점프하는 행동의 기능", EvidenceKind.RESEARCH_FINDING),
        ("점프 행동의 기능 기반 강화 개입", EvidenceKind.RESEARCH_FINDING),
        ("kennel 환경의 짖음", EvidenceKind.RESEARCH_FINDING),
        ("e-collar 훈련 효율 비교", EvidenceKind.RESEARCH_FINDING),
        ("혐오 자극 기반 훈련과 복지 지표", EvidenceKind.RESEARCH_FINDING),
    ],
)
def test_approved_cards_are_classified_from_topic_and_tags(
    topic_fragment: str, expected: EvidenceKind
) -> None:
    assert card_evidence_kind(card_by_topic_fragment(topic_fragment)) is expected


def test_every_approved_card_has_a_kind_and_both_kinds_are_present() -> None:
    kinds = Counter(card_evidence_kind(card) for card in load_approved_cards())

    assert set(kinds) == set(EvidenceKind)
    assert kinds[EvidenceKind.PRACTICE_GUIDANCE] == 2


def test_leash_feasibility_card_cannot_serve_a_how_to_question() -> None:
    leash = card_by_topic_fragment("리드줄 보행 프로그램")

    assert card_supports_intent(leash, QuestionIntent.HOW_TO) is False
    assert card_supports_intent(leash, QuestionIntent.EXPLANATION) is True
    assert usable_for_intent([leash], QuestionIntent.HOW_TO) == []


def test_jumping_and_kennel_research_cannot_serve_a_how_to_question() -> None:
    for fragment in (
        "사람에게 점프하는 행동의 기능",
        "점프 행동의 기능 기반 강화 개입",
        "kennel 환경의 짖음",
    ):
        card = card_by_topic_fragment(fragment)
        assert card_supports_intent(card, QuestionIntent.HOW_TO) is False


def test_ecollar_cards_serve_a_comparison_question() -> None:
    cards = [
        card_by_topic_fragment("e-collar 훈련 효율 비교"),
        card_by_topic_fragment("혐오 자극 기반 훈련과 복지 지표"),
    ]

    assert usable_for_intent(cards, QuestionIntent.COMPARISON) == cards


def test_guidance_cards_serve_a_how_to_question() -> None:
    cards = [
        card_by_topic_fragment("배변 훈련의 기초 관리 원칙"),
        card_by_topic_fragment("crate 적응의 기초 원칙"),
    ]

    assert usable_for_intent(cards, QuestionIntent.HOW_TO) == cards


def test_unknown_card_defaults_to_research_finding() -> None:
    unknown = card_by_topic_fragment("kennel 환경의 짖음").model_copy(
        update={"topic": "완전히 새로운 주제", "tags": ["unclassified"]}
    )

    assert card_evidence_kind(unknown) is EvidenceKind.RESEARCH_FINDING
    assert card_supports_intent(unknown, QuestionIntent.HOW_TO) is False


def test_usable_for_intent_preserves_order() -> None:
    cards = load_approved_cards()

    usable = usable_for_intent(cards, QuestionIntent.EXPLANATION)

    assert usable == cards
