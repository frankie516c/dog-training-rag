import copy
from uuid import UUID

import pytest

from backend.app.composition import (
    CLAIM_SEPARATOR,
    EvidenceCompositionError,
    compose_evidence_answer,
)
from backend.app.domain import ContentLanguage, EvidenceCard, EvidenceLevel, Locator, SourceRef

CARD_A = UUID("60000000-0000-4000-8000-00000000000a")
CARD_B = UUID("60000000-0000-4000-8000-00000000000b")

# Punctuation, digits and Latin terms that must survive composition untouched.
CLAIM_A = (
    "63마리를 세 집단으로 비교한 5일간의 제한된 recall·sit 연구에서는 "
    "e-collar 집단이 보상 중심 집단보다 더 효율적이거나 "
    "e-collar가 필요하다는 근거가 나타나지 않았다."
)
CLAIM_B = "총 11마리, 단일 시설, 통제군 부재 pilot 연구다 (2022)."


def make_card(
    card_id: UUID,
    claim: str,
    *,
    language: ContentLanguage = ContentLanguage.KOREAN,
) -> EvidenceCard:
    return EvidenceCard(
        card_id=card_id,
        claim=claim,
        claim_language=language,
        topic="synthetic topic",
        tags=["synthetic"],
        limitations=["Synthetic limitation."],
        source_refs=[
            SourceRef(
                source_id="direct-source",
                locator=Locator(
                    kind="html",
                    url="https://example.test/direct-source#guidance",
                    section="Synthetic guidance",
                ),
                evidence_level=EvidenceLevel.DIRECT,
            )
        ],
    )


def test_single_card_answer_is_the_claim_verbatim() -> None:
    answer = compose_evidence_answer([make_card(CARD_A, CLAIM_A)])

    assert answer == CLAIM_A


def test_multiple_cards_join_in_order_with_a_blank_line() -> None:
    cards = [make_card(CARD_A, CLAIM_A), make_card(CARD_B, CLAIM_B)]

    answer = compose_evidence_answer(cards)

    assert answer == CLAIM_A + CLAIM_SEPARATOR + CLAIM_B
    assert answer.index(CLAIM_A) < answer.index(CLAIM_B)


def test_reversed_card_order_reverses_the_answer_order() -> None:
    cards = [make_card(CARD_B, CLAIM_B), make_card(CARD_A, CLAIM_A)]

    assert compose_evidence_answer(cards) == CLAIM_B + CLAIM_SEPARATOR + CLAIM_A


def test_punctuation_numbers_and_latin_terms_are_preserved() -> None:
    answer = compose_evidence_answer([make_card(CARD_A, CLAIM_A)])

    for fragment in ("63마리", "5일간", "recall·sit", "e-collar", "나타나지 않았다."):
        assert fragment in answer


def test_duplicate_card_id_is_composed_once() -> None:
    cards = [make_card(CARD_A, CLAIM_A), make_card(CARD_A, CLAIM_A)]

    assert compose_evidence_answer(cards) == CLAIM_A


def test_duplicate_claim_text_from_different_cards_is_composed_once() -> None:
    cards = [make_card(CARD_A, CLAIM_A), make_card(CARD_B, CLAIM_A)]

    assert compose_evidence_answer(cards) == CLAIM_A


def test_empty_card_list_fails() -> None:
    with pytest.raises(EvidenceCompositionError):
        compose_evidence_answer([])


def test_blank_claim_fails() -> None:
    card = make_card(CARD_A, CLAIM_A)
    blank = card.model_copy(update={"claim": "   "})

    with pytest.raises(EvidenceCompositionError):
        compose_evidence_answer([blank])


def test_composition_does_not_mutate_the_source_cards() -> None:
    cards = [make_card(CARD_A, CLAIM_A), make_card(CARD_B, CLAIM_B)]
    before = copy.deepcopy([card.model_dump(mode="json") for card in cards])

    compose_evidence_answer(cards)

    assert [card.model_dump(mode="json") for card in cards] == before
