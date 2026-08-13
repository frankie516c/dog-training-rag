"""The three system instructions under test.

v0 is the production instruction, imported unchanged so the baseline cannot drift. v1 and
v2 append rules to it; none of them alters the structured output contract, so the same
`backend.app.grounded.validate_draft` judges every version.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from backend.app.domain import ContentLanguage, EvidenceCard
from backend.app.grounded import SYSTEM_INSTRUCTION as V0_SYSTEM_INSTRUCTION

CONTRACT_REMINDER = (
    "Output must use only the JSON contract stated above, with no extra keys and no text "
    "outside the object."
)

# v1 — evidence direction preservation.
V1_ADDITIONS = "\n".join(
    (
        "Additional rules:",
        "- Never swap the subject of a claim with the thing it is compared against.",
        "- Never delete a negation and never flip a negative finding into a positive one.",
        '- Never turn "was not more effective" into "was more effective".',
        "- Report an observed association as an association. Do not state it as causation.",
        "- Do not convert a study result into a training procedure or a prescription.",
        "- Do not invent steps, durations or success rates more specific than the evidence allows.",
        "- Check these conditions before answering, but never output your checking or any "
        "chain-of-thought.",
        CONTRACT_REMINDER,
    )
)

# v2 — user-facing directness, on top of v1's preservation rules.
V2_ADDITIONS = "\n".join(
    (
        V1_ADDITIONS,
        "Answer shape:",
        "- Open with one sentence that answers the question directly.",
        "- Then use one to three sentences for what the evidence does and does not show.",
        "- Prefer everyday Korean over technical wording where an everyday word exists.",
        "- Wording may change, but meaning, subject, negation and comparison direction must not.",
        "- For a how-to question, guide only as far as practice-guidance evidence goes.",
        "- If the question needs procedural detail the evidence does not supply, set "
        "answerable to false.",
        "- Never write citations, sources or a limitations list; the server assembles them.",
        CONTRACT_REMINDER,
    )
)

PROMPT_VERSIONS: dict[str, str] = {
    "v0": V0_SYSTEM_INSTRUCTION,
    "v1": V0_SYSTEM_INSTRUCTION + "\n" + V1_ADDITIONS,
    "v2": V0_SYSTEM_INSTRUCTION + "\n" + V2_ADDITIONS,
}


def build_messages(
    *,
    version: str,
    message: str,
    response_language: ContentLanguage,
    cards: Sequence[EvidenceCard],
) -> list[dict[str, str]]:
    """Build the message list for one prompt version.

    The user turn is byte-identical across versions; only the system turn differs. Card
    content is the same set of fields the production builder sends.
    """

    if version not in PROMPT_VERSIONS:
        raise ValueError(f"unknown prompt version: {version}")

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
        {"role": "system", "content": PROMPT_VERSIONS[version]},
        {"role": "user", "content": user_message},
    ]
