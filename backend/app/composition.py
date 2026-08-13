"""Deterministic answer composition from reviewed EvidenceCard claims.

Checkpoint 5G and 5G-1 measured two local 4B models on the identical retrieval result
and prompt. Both changed the subject, the study condition or the stated purpose of the
evidence — `gemma3:4b` turned "punishing a mistake found later does not help" into "the
dog eliminating anywhere does not help", and `qwen3.5:4b` inverted which group showed the
negative welfare outcome and reversed a study's stated purpose. The failures were not the
same ones, so no prompt or output filter covers both.

This module removes that failure class instead of trying to detect it: the answer is the
human-reviewed claim text itself, byte for byte. Nothing here summarizes, translates,
corrects or reorders a sentence. If the claims cannot be composed, the caller returns
`insufficient_evidence` rather than inventing prose.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import EvidenceCard

CLAIM_SEPARATOR = "\n\n"


class EvidenceCompositionError(RuntimeError):
    """The selected cards cannot produce a reviewed answer."""


def compose_evidence_answer(cards: Sequence[EvidenceCard]) -> str:
    """Join the reviewed claims of the selected cards in citation order.

    The caller is responsible for selection: safety, scope, score, language and reuse
    eligibility are all decided before a card reaches this function. Composition only
    concatenates what it is given, de-duplicating repeated cards and repeated claim text
    so one claim is never shown twice.

    Raises EvidenceCompositionError when nothing composable remains.
    """

    claims: list[str] = []
    seen_card_ids = set()
    seen_claims = set()

    for card in cards:
        if card.card_id in seen_card_ids:
            continue
        seen_card_ids.add(card.card_id)

        claim = card.claim
        if not claim.strip():
            raise EvidenceCompositionError(f"card {card.card_id} has an empty claim")
        if claim in seen_claims:
            continue
        seen_claims.add(claim)
        claims.append(claim)

    if not claims:
        raise EvidenceCompositionError("no reviewed claim is available to compose")
    return CLAIM_SEPARATOR.join(claims)
