"""Automatic screens over one answer.

These are screens, not verdicts. `evidence_context` membership catches invented numbers and
invented Latin terms, and the reversal patterns below catch the specific inversions two 4B
models produced in 5G/5G-1. Nothing here understands Korean, so direction preservation and
readability still require a human reading the claim beside the answer — see the comparison
table in the report.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from backend.app.domain import EvidenceCard
from backend.app.grounded import evidence_context

_DIGIT_RUN = re.compile(r"\d+")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")

# Inversions of the reviewed claims. A hit is a strong signal; a miss proves nothing.
_ECOLLAR_SUPERIOR = (
    r"(e-collar|전자\s*목줄)[^.]{0,40}(더\s*(효과|효율)[^.]{0,10}(적이었|적입니다|적이다|했다))"
)
_REWARD_NEGATIVE = r"보상\s*(기반|중심)\s*집단[^.]{0,30}(더\s*)?부정적"
_FEASIBILITY_AS_EFFICACY = (
    r"(당김|끌기)[^.]{0,20}(감소|개선)[^.]{0,20}(효능|효과)[^.]{0,10}(입증|확인|보였)"
)

REVERSAL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("e-collar 우위 긍정", _ECOLLAR_SUPERIOR),
    ("보상 집단이 부정적", _REWARD_NEGATIVE),
    ("feasibility를 효능으로", _FEASIBILITY_AS_EFFICACY),
    ("인과 단정", r"(때문에|덕분에|원인이다|유발한다|초래한다)"),
    ("성공률 생성", r"성공률\s*\d"),
)

# Procedure scaffolding that only practice guidance may support.
PROCEDURE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("단계 번호", r"(^|\n)\s*\d+\s*(단계|일차|주차|\)|\.)"),
    ("일수 계획", r"\d+\s*(일|주)\s*(차|간|안에|만에|계획|프로그램)"),
    ("횟수 처방", r"하루\s*\d+\s*(번|회)"),
)


@dataclass
class AutoChecks:
    """Machine-checkable properties of one answer."""

    used_card_ids_valid: bool
    numbers_outside_evidence: list[str] = field(default_factory=list)
    latin_outside_evidence: list[str] = field(default_factory=list)
    reversal_hits: list[str] = field(default_factory=list)
    procedure_hits: list[str] = field(default_factory=list)
    sentence_count: int = 0
    answer_chars: int = 0

    @property
    def fabricated_content(self) -> bool:
        """Anything the evidence cannot support that a machine can see."""

        return bool(
            self.numbers_outside_evidence
            or self.latin_outside_evidence
            or self.reversal_hits
            or self.procedure_hits
        )

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["fabricated_content"] = self.fabricated_content
        return payload


def run_auto_checks(
    answer: str,
    *,
    cards: Sequence[EvidenceCard],
    used_card_ids: Sequence[str],
    allow_procedure: bool,
) -> AutoChecks:
    context = evidence_context(cards)
    allowed_ids = {str(card.card_id) for card in cards}
    context_words = {word.casefold() for word in _LATIN_WORD.findall(context)}

    numbers = [number for number in _DIGIT_RUN.findall(answer) if number not in context]
    latin = [word for word in _LATIN_WORD.findall(answer) if word.casefold() not in context_words]
    reversals = [label for label, pattern in REVERSAL_PATTERNS if re.search(pattern, answer)]
    procedures = (
        []
        if allow_procedure
        else [label for label, pattern in PROCEDURE_PATTERNS if re.search(pattern, answer)]
    )

    return AutoChecks(
        used_card_ids_valid=bool(used_card_ids) and set(used_card_ids) <= allowed_ids,
        numbers_outside_evidence=numbers,
        latin_outside_evidence=latin,
        reversal_hits=reversals,
        procedure_hits=procedures,
        sentence_count=len([part for part in re.split(r"[.!?]\s*", answer) if part.strip()]),
        answer_chars=len(answer),
    )
