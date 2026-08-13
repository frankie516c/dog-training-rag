import asyncio
import json
import re
from uuid import UUID

import pytest

from backend.app.domain import ContentLanguage, EvidenceCard, EvidenceLevel, Locator, SourceRef
from backend.app.grounded import (
    DraftVerdict,
    GroundedAnswerer,
    build_grounded_messages,
    evidence_context,
    validate_draft,
)

CARD_A = UUID("70000000-0000-4000-8000-00000000000a")
CARD_B = UUID("70000000-0000-4000-8000-00000000000b")
UNRETRIEVED = UUID("70000000-0000-4000-8000-0000000000ff")

CLAIM_A = "63마리를 세 집단으로 비교한 5일간의 연구에서 e-collar 집단의 우위는 나타나지 않았다."
CLAIM_B = "혐오 자극 사용 비율이 높은 집단은 보상 기반 집단보다 더 부정적인 결과를 보였다."


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
        topic="e-collar 훈련 효율 비교",
        tags=["e-collar", "positive reinforcement"],
        limitations=["집단별 21마리라는 제한된 조건이다."],
        source_refs=[
            SourceRef(
                source_id="direct-source",
                locator=Locator(
                    kind="html",
                    url="https://example.test/direct-source#guidance",
                    section="Results",
                ),
                evidence_level=EvidenceLevel.DIRECT,
            )
        ],
    )


CARDS = [make_card(CARD_A, CLAIM_A), make_card(CARD_B, CLAIM_B)]


def payload(**overrides: object) -> str:
    body = {
        "answerable": True,
        "answer": "제한된 연구에서 e-collar 집단의 우위는 나타나지 않았습니다.",
        "used_card_ids": [str(CARD_A)],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def validate(raw: str, cards: list[EvidenceCard] | None = None):
    return validate_draft(
        raw,
        cards=CARDS if cards is None else cards,
        response_language=ContentLanguage.KOREAN,
    )


class FakeProvider:
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


# --------------------------------------------------------------------------------------
# Prompt boundary
# --------------------------------------------------------------------------------------


def test_prompt_carries_only_approved_card_content() -> None:
    messages = build_grounded_messages(
        message="전자 목줄이 보상 훈련보다 더 효과적인가요?",
        response_language=ContentLanguage.KOREAN,
        cards=CARDS,
    )
    prompt = "\n".join(item["content"] for item in messages)

    assert CLAIM_A in prompt
    assert CLAIM_B in prompt
    assert str(CARD_A) in prompt
    assert "집단별 21마리라는 제한된 조건이다." in prompt
    assert "e-collar 훈련 효율 비교" in prompt

    for forbidden in (
        "https://example.test",
        "direct-source",
        "Results",
        "qdrant",
        "Bearer",
        "C:\\",
        "locator",
    ):
        assert forbidden not in prompt


def test_prompt_states_the_grounding_rules() -> None:
    system = build_grounded_messages(
        message="질문",
        response_language=ContentLanguage.KOREAN,
        cards=CARDS,
    )[0]["content"]

    for rule in (
        "Do not add facts",
        "only when the evidence itself states a procedure",
        "feasibility result into an efficacy claim",
        "direction of every comparison",
        "medical advice",
        "answerable to false",
        "server assembles",
    ):
        assert rule in system


def test_only_retrieved_claims_reach_the_provider() -> None:
    provider = FakeProvider(payload())
    answerer = GroundedAnswerer(provider=provider)
    other = make_card(UNRETRIEVED, "검색되지 않은 카드의 주장이다.")

    asyncio.run(
        answerer.draft(
            message="전자 목줄이 보상 훈련보다 더 효과적인가요?",
            response_language=ContentLanguage.KOREAN,
            cards=CARDS,
        )
    )

    prompt = "\n".join(item["content"] for item in provider.calls[0])
    assert other.claim not in prompt
    assert str(UNRETRIEVED) not in prompt


# --------------------------------------------------------------------------------------
# Draft validation
# --------------------------------------------------------------------------------------


def assert_invalid(raw: str) -> None:
    result = validate(raw)
    assert result.verdict is DraftVerdict.INVALID
    assert result.draft is None


def test_valid_draft_is_accepted() -> None:
    result = validate(payload())

    assert result.verdict is DraftVerdict.ACCEPTED
    assert result.draft is not None
    assert result.draft.used_card_ids == (CARD_A,)
    assert result.draft.answer.startswith("제한된 연구에서")


def test_fenced_json_is_accepted() -> None:
    assert validate(f"```json\n{payload()}\n```").verdict is DraftVerdict.ACCEPTED


def test_unretrieved_card_id_is_rejected() -> None:
    assert_invalid(payload(used_card_ids=[str(UNRETRIEVED)]))
    assert_invalid(payload(used_card_ids=[str(CARD_A), str(UNRETRIEVED)]))


def test_answerable_false_is_its_own_verdict() -> None:
    result = validate(payload(answerable=False, answer=None, used_card_ids=[]))

    assert result.verdict is DraftVerdict.NOT_ANSWERABLE
    assert result.draft is None


def test_missing_or_non_boolean_answerable_is_invalid() -> None:
    assert_invalid(json.dumps({"answer": "무언가", "used_card_ids": [str(CARD_A)]}))
    assert_invalid(payload(answerable="true"))


def test_malformed_json_is_rejected() -> None:
    assert_invalid("이건 JSON이 아닙니다")
    assert_invalid('{"answerable": true, "answer": ')
    assert_invalid("[]")


def test_empty_or_missing_answer_is_rejected() -> None:
    assert_invalid(payload(answer=""))
    assert_invalid(payload(answer="   "))
    assert_invalid(payload(answer=None))
    assert_invalid(payload(answer=123))


def test_missing_or_empty_used_card_ids_is_rejected() -> None:
    assert_invalid(payload(used_card_ids=[]))
    assert_invalid(payload(used_card_ids="not-a-list"))
    assert_invalid(payload(used_card_ids=[42]))
    assert_invalid(payload(used_card_ids=["not-a-uuid"]))


def test_language_mismatch_is_rejected() -> None:
    english = validate_draft(
        payload(answer="No advantage was shown for the e-collar group."),
        cards=CARDS,
        response_language=ContentLanguage.KOREAN,
    )
    assert english.verdict is DraftVerdict.INVALID

    korean_for_english_request = validate_draft(
        payload(),
        cards=CARDS,
        response_language=ContentLanguage.ENGLISH,
    )
    assert korean_for_english_request.verdict is DraftVerdict.INVALID


def test_numbers_absent_from_the_evidence_are_rejected() -> None:
    assert_invalid(payload(answer="이 연구는 500마리를 대상으로 했습니다."))
    # 63 and 21 are both present in the supplied claim and limitation.
    accepted = validate(payload(answer="63마리 중 21마리가 각 집단에 배정됐습니다."))
    assert accepted.verdict is DraftVerdict.ACCEPTED


def test_latin_terms_absent_from_the_evidence_are_rejected() -> None:
    assert_invalid(payload(answer="Pavlov 방식의 e-collar 훈련입니다."))
    assert validate(payload(answer="e-collar 집단의 우위는 없었습니다.")).verdict is (
        DraftVerdict.ACCEPTED
    )


def test_oversized_answer_is_rejected() -> None:
    assert_invalid(payload(answer="가" * 2_001))


# --------------------------------------------------------------------------------------
# KNOWN LIMITATION — polarity and comparison direction are NOT validated.
#
# `_stays_within_evidence` checks that every number and Latin word in the answer occurs in
# the evidence. Reversing a conclusion changes neither: dropping a negation ("나타나지
# 않았다" -> "나타났다") or swapping which group is the subject of a comparison reuses the
# same vocabulary. Both reversals below are the failure mode two real 4B models produced in
# checkpoints 5G and 5G-1.
#
# These tests assert the CURRENT behaviour so the gap is visible and any future guard has a
# failing test to flip. They are not an endorsement of it.
# --------------------------------------------------------------------------------------

REVERSED_NEGATION = "63마리를 세 집단으로 비교한 5일간의 연구에서 e-collar 집단의 우위는 나타났다."
REVERSED_COMPARISON = (
    "보상 기반 집단은 혐오 자극 사용 비율이 높은 집단보다 더 부정적인 결과를 보였다."
)


@pytest.mark.parametrize(
    "reversed_answer",
    [REVERSED_NEGATION, REVERSED_COMPARISON],
    ids=["negation-dropped", "comparison-direction-swapped"],
)
def test_known_limitation_polarity_reversal_is_not_detected(reversed_answer: str) -> None:
    result = validate(payload(answer=reversed_answer))

    assert result.verdict is DraftVerdict.ACCEPTED
    assert result.draft is not None
    assert result.draft.answer == reversed_answer


def test_known_limitation_reversal_uses_only_evidence_vocabulary() -> None:
    """Why the current checks cannot see it: the vocabulary is entirely in-context."""

    context = evidence_context(CARDS)

    for reversed_answer in (REVERSED_NEGATION, REVERSED_COMPARISON):
        assert all(number in context for number in re.findall(r"\d+", reversed_answer))
        latin = re.findall(r"[A-Za-z][A-Za-z\-']+", reversed_answer)
        context_words = {word.casefold() for word in re.findall(r"[A-Za-z][A-Za-z\-']+", context)}
        assert all(word.casefold() in context_words for word in latin)


def test_model_supplied_citation_fields_are_ignored() -> None:
    result = validate(
        payload(
            citations=[{"source_id": "made-up-source", "url": "https://evil.test"}],
            limitations=["모델이 지어낸 한계"],
            sources=["https://evil.test"],
        )
    )

    assert result.draft is not None
    assert result.draft.answer == "제한된 연구에서 e-collar 집단의 우위는 나타나지 않았습니다."
    assert not hasattr(result.draft, "citations")
    assert not hasattr(result.draft, "limitations")


def test_no_cards_means_no_draft() -> None:
    result = validate_draft(payload(), cards=[], response_language=ContentLanguage.KOREAN)

    assert result.verdict is DraftVerdict.INVALID


# --------------------------------------------------------------------------------------
# Answerer behaviour
# --------------------------------------------------------------------------------------


def run_answerer(provider: FakeProvider):
    return asyncio.run(
        GroundedAnswerer(provider=provider).draft(
            message="질문",
            response_language=ContentLanguage.KOREAN,
            cards=CARDS,
        )
    )


def test_provider_error_yields_an_invalid_verdict() -> None:
    result = run_answerer(FakeProvider(error=TimeoutError("provider timeout")))

    assert result.verdict is DraftVerdict.INVALID
    assert result.draft is None


def test_invalid_provider_output_yields_an_invalid_verdict() -> None:
    result = run_answerer(FakeProvider("완전히 자유로운 산문 답변입니다."))

    assert result.verdict is DraftVerdict.INVALID


def test_answerer_passes_through_not_answerable() -> None:
    raw = json.dumps({"answerable": False, "answer": None, "used_card_ids": []})

    assert run_answerer(FakeProvider(raw)).verdict is DraftVerdict.NOT_ANSWERABLE
