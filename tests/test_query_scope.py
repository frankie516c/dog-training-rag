import json
from collections import Counter
from pathlib import Path

import pytest

from backend.app.data_validation import DEFAULT_EVIDENCE_CARDS_PATH
from backend.app.domain import EvidenceCard, SafetyLevel
from backend.app.safety import detect_safety_risk
from backend.app.scope import TrainingScope, card_scope, route_query_scope

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "query_scope_eval.json"


def load_cases() -> list[dict[str, str]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return payload["cases"]


def load_approved_cards() -> list[EvidenceCard]:
    lines = DEFAULT_EVIDENCE_CARDS_PATH.read_text(encoding="utf-8").splitlines()
    return [EvidenceCard.model_validate_json(line) for line in lines if line.strip()]


CASES = load_cases()


@pytest.mark.parametrize(
    ("message", "expected"),
    [(case["message"], case["expected"]) for case in CASES],
    ids=[case["expected"] for case in CASES],
)
def test_fixture_cases_route_as_expected(message: str, expected: str) -> None:
    finding = detect_safety_risk(message)

    if expected == "safety_urgent":
        assert finding is not None
        assert finding.level is SafetyLevel.URGENT
        return

    assert finding is None
    scope = route_query_scope(message)
    if expected == "unsupported":
        assert scope is None
    else:
        assert scope is not None
        assert scope.value == expected


def test_every_supported_scope_is_reachable_from_the_fixture() -> None:
    routed = {
        route_query_scope(case["message"])
        for case in CASES
        if case["expected"] not in {"unsupported", "safety_urgent"}
    }

    assert routed == set(TrainingScope)


def test_kennel_barking_and_crate_adaptation_stay_separate() -> None:
    assert route_query_scope("강아지가 켄넬 안에서 계속 짖어요.") is TrainingScope.KENNEL_BARKING
    assert route_query_scope("이동장에 들어가는 것을 무서워해요.") is TrainingScope.CRATE_ADAPTATION
    assert route_query_scope("크레이트 안에서 밤새 짖어요.") is TrainingScope.KENNEL_BARKING
    assert route_query_scope("크레이트 적응 훈련을 하고 싶어요.") is TrainingScope.CRATE_ADAPTATION


def test_electronic_collar_beats_the_generic_leash_word() -> None:
    assert (
        route_query_scope("전자 목줄이 보상 훈련보다 더 효과적인가요?")
        is TrainingScope.AVERSIVE_OR_ECOLLAR
    )
    assert route_query_scope("Is an e-collar better?") is TrainingScope.AVERSIVE_OR_ECOLLAR
    assert route_query_scope("산책할 때 목줄을 계속 당겨요.") is TrainingScope.LEASH_WALKING


def test_generic_words_alone_do_not_decide_a_scope() -> None:
    assert route_query_scope("목줄을 새로 샀어요.") is None
    assert route_query_scope("강아지가 짖어요.") is None
    assert route_query_scope("훈련을 시작하려고 해요.") is None


@pytest.mark.parametrize(
    "message",
    [
        "강아지에게 손이나 악수를 가르치고 싶어요.",
        "앉아를 가르치는 순서를 알려주세요.",
        "엎드려와 기다려는 어떻게 가르치나요?",
        "리콜 연습은 어떻게 하나요?",
        "물어온 물건을 놓아 하도록 가르치고 싶어요.",
    ],
)
def test_procedures_without_approved_evidence_are_unsupported(message: str) -> None:
    assert route_query_scope(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "응가를 아무데나 해요ㅠㅠ",
        "집 안에 똥을 싸요",
        "오줌을 아무데나 싸요",
        "배변패드에 안 해요",
        "자꾸 소변 실수를 해요",
        "집 안에서 쉬를 해요",
        # 이모티콘, 반복 문장부호, 띄어쓰기 차이가 있어도 같은 판정이어야 한다.
        "응가를  아무 데나 해요!!!",
        "집안에 똥을 싸요ㅠㅠㅠ",
        "실내에서 쉬를 해요…",
    ],
)
def test_colloquial_housetraining_questions_are_routed(message: str) -> None:
    assert route_query_scope(message) is TrainingScope.HOUSETRAINING


@pytest.mark.parametrize(
    "message",
    [
        "강아지가 똥을 먹어요",
        "응가 냄새가 너무 심해요",
        "강아지가 쉬고 있어요",
        "초보자가 가르치기 쉬운 훈련은 뭐예요?",
        "대변 색깔이 이상해요",
    ],
)
def test_elimination_words_alone_are_not_housetraining(message: str) -> None:
    assert route_query_scope(message) is not TrainingScope.HOUSETRAINING


def test_high_risk_ingestion_is_urgent_and_plain_treats_are_not() -> None:
    assert detect_safety_risk("강아지가 초콜릿을 먹었어요.") is not None
    assert detect_safety_risk("개가 자일리톨을 삼켰어요.") is not None
    assert detect_safety_risk("My dog ate chocolate.") is not None
    assert detect_safety_risk("강아지가 간식을 먹었어요.") is None
    assert detect_safety_risk("강아지가 사료를 잘 먹어요.") is None
    assert detect_safety_risk("초콜릿색 래브라도를 키우고 있어요.") is None


def test_each_approved_card_maps_to_exactly_one_scope() -> None:
    cards = load_approved_cards()

    assert cards, "expected the reviewed evidence seed to be present"
    unmapped = [card.topic for card in cards if card_scope(card) is None]
    assert unmapped == []


def test_approved_cards_cover_every_supported_scope() -> None:
    counts = Counter(card_scope(card) for card in load_approved_cards())

    assert set(counts) == set(TrainingScope)
    assert None not in counts


def test_card_scope_uses_topic_and_tags_not_source_id() -> None:
    cards = load_approved_cards()
    by_scope: dict[TrainingScope | None, set[str]] = {}
    for card in cards:
        source_ids = {source_ref.source_id for source_ref in card.source_refs}
        by_scope.setdefault(card_scope(card), set()).update(source_ids)

    shared = by_scope[TrainingScope.HOUSETRAINING] & by_scope[TrainingScope.CRATE_ADAPTATION]
    assert shared, "housetraining and crate cards should share a source_id"
