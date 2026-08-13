"""The system instructions under test: v0, v1, v1.1 and v2.

v0 is the production instruction, imported unchanged so the baseline cannot drift. The
others append rules to it; none alters the structured output contract, so the same
`backend.app.grounded.validate_draft` judges every version.

v1.1 exists as the single-variable arm of a v1 vs v1.1 comparison, so it extends v1's rules
exactly once and states the output contract exactly once.
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
#
# The rules are kept separate from the trailing CONTRACT_REMINDER so a later version can
# extend them without repeating the reminder mid-prompt. v2 was built by nesting the whole
# v1 block and appending another reminder, which leaves the contract stated twice; v1.1
# must not inherit that, because it is the single-variable arm of the v1 vs v1.1 test.
V1_RULES = "\n".join(
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
    )
)

V1_ADDITIONS = V1_RULES + "\n" + CONTRACT_REMINDER

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

# v1.1 — v1's preservation rules, plus a narrower answerability scope.
#
# v1 refused questions its own evidence could answer: the housetraining card states that
# punishing a mistake found later does not help, yet every version returned
# answerable=false for "배변 실수를 발견했을 때 어떻게 해야 하나요?" nine times out of nine.
# These rules target only that over-refusal. Nothing about subject, negation or comparison
# direction changes.
V1_1_ADDITIONS = "\n".join(
    (
        V1_RULES,
        "Scope of answerability:",
        "- If the selected evidence directly answers any essential part of the question, "
        "set answerable to true.",
        "- Answer only as far as the evidence supports, even when no complete procedure exists.",
        "- When the evidence is practice guidance stating an actual behavioural principle, "
        "do not refuse merely because it gives no schedule, duration or success rate.",
        "- When the evidence is a research finding, you may describe what was observed and "
        "what was not established.",
        "- Never invent steps, counts, durations or success rates the evidence does not supply.",
        "- Do not refuse the whole question because one part of it cannot be answered. "
        "Answer the part the evidence covers and say what it does not cover.",
        CONTRACT_REMINDER,
    )
)

PROMPT_VERSIONS: dict[str, str] = {
    "v0": V0_SYSTEM_INSTRUCTION,
    "v1": V0_SYSTEM_INSTRUCTION + "\n" + V1_ADDITIONS,
    "v1.1": V0_SYSTEM_INSTRUCTION + "\n" + V1_1_ADDITIONS,
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
