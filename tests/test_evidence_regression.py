"""Critical fidelity regressions observed in checkpoints 5G and 5G-1.

Every phrase below was produced by a local 4B model that had been given the correct
retrieval result, and every one of them contradicts the reviewed card. None of them exist
in any approved claim, so deterministic composition must never emit them. These are
guards against the answer path regressing back to free generation.
"""

import json
import re

import pytest

from backend.app.composition import compose_evidence_answer
from backend.app.data_validation import DEFAULT_EVIDENCE_CARDS_PATH
from backend.app.domain import EvidenceCard
from backend.app.scope import TrainingScope, card_scope

# (label, pattern) — each was an observed model output, not a card sentence.
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    # gemma3:4b turned "punishing a mistake found later" into the act of eliminating.
    ("배변 행위 자체를 부정", r"응가를\s*아무데나\s*하는\s*것은\s*도움이\s*되지\s*않"),
    # gemma3:4b shrank the 63-dog study to 21 dogs total.
    ("전체 연구를 21마리로 축소", r"연구에는?\s*21\s*마리|21\s*마리만"),
    # gemma3:4b turned "최대 150분" into an average.
    ("최대 150분을 평균으로 변경", r"평균\s*150\s*분"),
    # qwen3.5:4b made the aversive group the comparator instead of the affected group.
    ("혐오 자극 비교 방향 반전", r"혐오\s*자극을?\s*사용하는\s*집단과\s*비교"),
    # qwen3.5:4b reversed the leash study's stated purpose.
    ("리드줄 연구 목적 반전", r"목적은\s*리드줄\s*당김\s*감소\s*효능"),
    # gemma3:4b made the kennel run itself the barker.
    ("견사가 짖는다", r"견사가\s*짖"),
]


def load_approved_cards() -> list[EvidenceCard]:
    lines = DEFAULT_EVIDENCE_CARDS_PATH.read_text(encoding="utf-8").splitlines()
    return [EvidenceCard.model_validate_json(line) for line in lines if line.strip()]


def cards_by_scope() -> dict[TrainingScope, list[EvidenceCard]]:
    grouped: dict[TrainingScope, list[EvidenceCard]] = {}
    for card in load_approved_cards():
        scope = card_scope(card)
        assert scope is not None, f"card {card.card_id} no longer maps to a scope"
        grouped.setdefault(scope, []).append(card)
    return grouped


@pytest.mark.parametrize(
    ("label", "pattern"), FORBIDDEN_PATTERNS, ids=[p[0] for p in FORBIDDEN_PATTERNS]
)
def test_forbidden_phrase_is_absent_from_the_approved_claims(label: str, pattern: str) -> None:
    """The premise of the guard: no reviewed claim contains the phrase either."""

    corpus = "\n".join(card.claim for card in load_approved_cards())

    assert re.search(pattern, corpus) is None


@pytest.mark.parametrize(
    ("label", "pattern"), FORBIDDEN_PATTERNS, ids=[p[0] for p in FORBIDDEN_PATTERNS]
)
def test_forbidden_phrase_is_absent_from_every_composed_answer(label: str, pattern: str) -> None:
    for cards in cards_by_scope().values():
        answer = compose_evidence_answer(cards)
        assert re.search(pattern, answer) is None, f"{label} appeared in a composed answer"


def test_every_composed_sentence_comes_from_an_approved_claim() -> None:
    """The strongest invariant: composition adds no text of its own."""

    approved = {card.claim for card in load_approved_cards()}

    for cards in cards_by_scope().values():
        answer = compose_evidence_answer(cards)
        for part in answer.split("\n\n"):
            assert part in approved


def test_composed_answers_carry_no_prefix_or_recommendation() -> None:
    banned_openers = ("답변", "안녕", "결론", "요약", "추천", "다음과 같이", "제공된 증거")

    for cards in cards_by_scope().values():
        answer = compose_evidence_answer(cards)
        assert not answer.startswith(banned_openers)
        assert "```" not in answer
        assert not answer.strip().startswith("{")


def test_approved_claims_are_still_the_reviewed_jsonl_text() -> None:
    """Composition reads the same bytes the review decisions were bound to."""

    raw_claims = []
    for line in DEFAULT_EVIDENCE_CARDS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw_claims.append(json.loads(line)["claim"])

    assert [card.claim for card in load_approved_cards()] == raw_claims
