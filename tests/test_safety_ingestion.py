"""The emergency gate has to fire on how people actually type it.

A suspected ingestion is reported in Korean with the verb in its adnominal form and the
doubt in a following modifier — "먹은 것 같아요", "삼킨 듯해요". Those forms matched nothing
before, so the most common phrasing of the one case this gate exists for fell through to
training retrieval.
"""

import pytest

from backend.app.domain import ContentLanguage, SafetyLevel
from backend.app.safety import detect_safety_risk

SUSPECTED_INGESTION = [
    "우리 애가 초콜릿 먹은거 같아ㅠㅠ",
    "초콜렛을 먹은 것 같아요",
    "초콜릿을 먹었을 수도 있어요",
    "자일리톨 껌을 삼킨 것 같아요",
    "포도를 주워 먹은 듯해요",
]

NOT_INGESTION = [
    "초콜릿색 래브라도예요",
    "초콜릿 냄새가 나요",
    "간식을 먹었어요",
    "포도 모양 장난감이에요",
]


@pytest.mark.parametrize("message", SUSPECTED_INGESTION)
def test_suspected_ingestion_of_a_high_risk_substance_is_urgent(message: str) -> None:
    finding = detect_safety_risk(message)
    assert finding is not None, message
    assert finding.level is SafetyLevel.URGENT


@pytest.mark.parametrize("message", NOT_INGESTION)
def test_a_substance_without_ingestion_is_not_urgent(message: str) -> None:
    """Both signals are required. A colour, a smell, or a toy is not an ingestion."""

    assert detect_safety_risk(message) is None, message


def test_ingestion_without_a_high_risk_substance_is_not_urgent() -> None:
    assert detect_safety_risk("간식을 먹었어요") is None
    assert detect_safety_risk("사료를 삼킨 것 같아요") is None


def test_the_urgent_answer_leads_with_the_action() -> None:
    finding = detect_safety_risk("초콜릿을 먹은 것 같아요")
    assert finding is not None
    answer = finding.answer(ContentLanguage.KOREAN)

    first = answer.split("\n", 1)[0]
    assert "동물병원" in first
    assert "지금 바로" in first
    # The scope disclaimer may appear, but never ahead of the instruction to call a vet.
    assert "훈련 근거" not in first
    assert answer.index("동물병원") < answer.index("훈련 근거")


def test_the_urgent_answer_advises_no_treatment() -> None:
    """It may say what it will not do; it must not do it."""

    for language in (ContentLanguage.KOREAN, ContentLanguage.ENGLISH):
        answer = detect_safety_risk("초콜릿을 먹은 것 같아요").answer(language)
        for prescription in ("g/kg", "mg", "소금물", "과산화수소", "hydrogen peroxide"):
            assert prescription not in answer
