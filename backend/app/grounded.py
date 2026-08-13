"""Grounded generation over retrieved evidence, with a hard validation boundary.

The model never speaks directly to the user. It returns a structured draft, the server
validates that draft against the exact cards that were retrieved, and only a draft that
survives every check becomes an answer. Anything else — a bad payload, an empty answer, a
card the model invented, a number that is not in the evidence, a timeout — is discarded
and the caller falls back to deterministic composition.

Citations and limitations are never read from the model. The server builds them from the
cards it selected, exactly as in checkpoint 5H.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from backend.app.domain import ContentLanguage, EvidenceCard

MAX_ANSWER_CHARS = 2_000

_WRAPPING_CODE_FENCE = re.compile(r"\A```[^\n`]*\n?(?P<body>.*?)\n?```\Z", re.DOTALL)
_DIGIT_RUN = re.compile(r"\d+")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")
_HANGUL = re.compile(r"[가-힣]")

SYSTEM_INSTRUCTION = (
    "You answer a dog-training question using only the supplied approved evidence.\n"
    "Rules:\n"
    "- Do not add facts, numbers, sample sizes, durations, or procedures that are not in "
    "the evidence.\n"
    "- Write training steps only when the evidence itself states a procedure. Otherwise "
    "describe what the evidence does and does not show.\n"
    "- Keep research findings and general training advice distinct. Never present a study "
    "result as a prescription.\n"
    "- Never turn a feasibility result into an efficacy claim.\n"
    "- Preserve the direction of every comparison and every negation exactly as written.\n"
    "- Do not produce medical advice, diagnosis, dosing, or treatment.\n"
    "- If the evidence cannot answer the question, set answerable to false.\n"
    "- Do not write citations, sources, URLs, or a limitations list. The server assembles "
    "those separately.\n"
    'Reply with one JSON object and nothing else: {"answerable": bool, "answer": string '
    'or null, "used_card_ids": [string]}. "used_card_ids" must contain only ids given in '
    "the evidence."
)


class DraftVerdict(StrEnum):
    """Why a provider round-trip ended the way it did."""

    #: The draft passed every check and may be shown.
    ACCEPTED = "accepted"
    #: The model reported that the evidence cannot answer the question.
    NOT_ANSWERABLE = "not_answerable"
    #: Anything else: bad payload, empty answer, invented card, invented number.
    INVALID = "invalid"


@dataclass(frozen=True)
class GroundedDraft:
    """A validated model draft. Only the server may construct one."""

    answer: str
    used_card_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class DraftResult:
    """The outcome of one provider round-trip.

    NOT_ANSWERABLE and INVALID are handled differently by the caller: the first ends the
    request with insufficient_evidence, the second falls back to deterministic composition.
    """

    verdict: DraftVerdict
    draft: GroundedDraft | None = None

    @classmethod
    def invalid(cls) -> DraftResult:
        return cls(verdict=DraftVerdict.INVALID)

    @classmethod
    def not_answerable(cls) -> DraftResult:
        return cls(verdict=DraftVerdict.NOT_ANSWERABLE)


class CompletionProvider(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


def build_grounded_messages(
    *,
    message: str,
    response_language: ContentLanguage,
    cards: Sequence[EvidenceCard],
) -> list[dict[str, str]]:
    """Build the prompt. Only approved card content crosses this boundary.

    No URL, locator, source registry entry, license text, local path, API key or Qdrant
    setting is included.
    """

    evidence = [
        {
            "card_id": str(card.card_id),
            "topic": card.topic,
            "tags": list(card.tags),
            "claim": card.claim,
            "limitations": list(card.limitations),
        }
        for card in cards
    ]
    user_message = "\n".join(
        (
            f"Question: {message}",
            f"Answer language: {response_language.value}",
            "Evidence:",
            json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        )
    )
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_message},
    ]


def _unwrap(content: str) -> str:
    text = content.strip()
    fence = _WRAPPING_CODE_FENCE.match(text)
    if fence is not None and "```" not in fence.group("body"):
        text = fence.group("body").strip()
    return text


def evidence_context(cards: Sequence[EvidenceCard]) -> str:
    parts: list[str] = []
    for card in cards:
        parts.extend((card.topic, card.claim, *card.tags, *card.limitations))
    return " ".join(parts)


def validate_draft(
    raw: str,
    *,
    cards: Sequence[EvidenceCard],
    response_language: ContentLanguage,
) -> DraftResult:
    """Turn raw provider output into a verdict. Nothing invalid is ever shown."""

    allowed = {card.card_id for card in cards}
    if not allowed:
        return DraftResult.invalid()

    try:
        payload = json.loads(_unwrap(raw))
    except ValueError:
        return DraftResult.invalid()
    if not isinstance(payload, dict):
        return DraftResult.invalid()

    answerable = payload.get("answerable")
    if answerable is False:
        return DraftResult.not_answerable()
    if answerable is not True:
        return DraftResult.invalid()

    answer = payload.get("answer")
    if not isinstance(answer, str):
        return DraftResult.invalid()
    answer = _unwrap(answer)
    if not answer or len(answer) > MAX_ANSWER_CHARS:
        return DraftResult.invalid()

    used_raw = payload.get("used_card_ids")
    if not isinstance(used_raw, list) or not used_raw:
        return DraftResult.invalid()
    used: list[UUID] = []
    for value in used_raw:
        if not isinstance(value, str):
            return DraftResult.invalid()
        try:
            card_id = UUID(value)
        except ValueError:
            return DraftResult.invalid()
        if card_id not in allowed:
            return DraftResult.invalid()
        if card_id not in used:
            used.append(card_id)
    if not used:
        return DraftResult.invalid()

    if not _language_matches(answer, response_language):
        return DraftResult.invalid()
    if not _stays_within_evidence(answer, cards):
        return DraftResult.invalid()
    return DraftResult(
        verdict=DraftVerdict.ACCEPTED,
        draft=GroundedDraft(answer=answer, used_card_ids=tuple(used)),
    )


def _language_matches(answer: str, response_language: ContentLanguage) -> bool:
    has_hangul = _HANGUL.search(answer) is not None
    if response_language is ContentLanguage.KOREAN:
        return has_hangul
    return not has_hangul


def _stays_within_evidence(answer: str, cards: Sequence[EvidenceCard]) -> bool:
    """Reject numbers and Latin terms that do not appear in the evidence.

    This catches invented sample sizes, durations and study names, which is where the 5G
    fidelity failures concentrated. It cannot detect an invented Hangul proper noun; that
    remains a known gap covered only by the system instruction.
    """

    context = evidence_context(cards)
    if any(number not in context for number in _DIGIT_RUN.findall(answer)):
        return False

    context_words = {word.casefold() for word in _LATIN_WORD.findall(context)}
    return all(word.casefold() in context_words for word in _LATIN_WORD.findall(answer))


class GroundedAnswerer:
    """Asks a provider for a draft and returns it only if it validates."""

    def __init__(self, *, provider: CompletionProvider) -> None:
        self._provider = provider

    async def draft(
        self,
        *,
        message: str,
        response_language: ContentLanguage,
        cards: Sequence[EvidenceCard],
    ) -> DraftResult:
        messages = build_grounded_messages(
            message=message,
            response_language=response_language,
            cards=cards,
        )
        try:
            raw = await self._provider.complete(messages)
        except Exception:
            # Provider unreachable, timed out or misbehaving: fall back deterministically.
            return DraftResult.invalid()
        return validate_draft(raw, cards=cards, response_language=response_language)
