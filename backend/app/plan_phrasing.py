"""Let a local model phrase a reviewed plan, and check that it only did that.

Checkpoint 5K. Every earlier attempt to put a 4B-class model in this pipeline failed the
same way: asked to judge what the evidence supports *and* to write well, it did neither
reliably — v1.1 under-used the evidence, v1.2 granted a reversal it was asked for, v1.2.1
refused a question it could answer. The records are in experiments/prompt_eval_v0.

So the model is not asked to judge anything here. Safety, scope, intent, answerability and
citations are all decided before this module is reached. What arrives is one approved card
and the reviewed `ResponsePlan` written from it, and the only job is to say those same
sentences in warmer Korean. Anything the model adds is a defect by construction, which is
what makes the checks below possible: the ground truth is not "is this true about dogs" but
"is this in the plan".

Rejection is cheap. The caller falls back to the plan's own rendering, which is a complete,
reviewed answer — so a failed phrasing costs the reader nothing but plainer prose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from backend.app.domain import ContentLanguage, EvidenceCard
from backend.app.response_plans import ResponsePlan
from backend.app.text_match import compile_terms, normalize

_WRAPPING_CODE_FENCE = re.compile(r"\A```[^\n`]*\n?(?P<body>.*?)\n?```\Z", re.DOTALL)
_DIGITS = re.compile(r"\d+")
_LATIN = re.compile(r"[A-Za-z][A-Za-z\-]*")

SYSTEM_INSTRUCTION = (
    "당신은 반려견 훈련 상담 서비스의 문장 다듬기 도우미입니다.\n"
    "검수를 마친 안내 문장이 주어집니다. 그 내용을 따뜻하고 자연스러운 한국어 존댓말로 "
    "다시 표현하는 것이 유일한 역할입니다.\n"
    "규칙:\n"
    "- 주어진 안내에 없는 방법, 도구, 단계, 횟수, 기간, 원인, 효과를 덧붙이지 마세요.\n"
    "- 강화 방법의 구체적인 수단을 스스로 정하지 마세요. 안내가 '강화'라고만 했다면 "
    "그대로 '강화'라고 쓰세요.\n"
    "- 근거가 말하지 않은 위로나 안심을 덧붙이지 마세요.\n"
    "- '도움이 되지 않는다'를 '방해한다', '악화된다', '더 나빠진다'처럼 더 강한 표현으로 "
    "바꾸지 마세요.\n"
    "- 사용자가 말하지 않은 상황을 사실인 것처럼 단정하지 마세요.\n"
    "- 이름, 호칭, 감탄사, 느낌표를 만들지 마세요.\n"
    "- 영어 단어를 섞지 마세요.\n"
    "출력은 다음 JSON 객체 하나뿐입니다. 다른 텍스트나 코드 블록을 붙이지 마세요.\n"
    '{"answer": "다듬은 한국어 답변", "used_card_ids": ["주어진 card_id"]}'
)

# --------------------------------------------------------------------------------------
# What the model is allowed to have said
# --------------------------------------------------------------------------------------
#
# These are not a blocklist of bad words. Each one marks a claim the housetraining and
# crate cards do not make, so its presence means the sentence went past the plan.

#: A specific reinforcer. The card states *when* to reinforce, never with what. 5J-1
#: removed "칭찬이나 간식" from the plan for exactly this reason.
_UNAPPROVED_MEANS = compile_terms(
    ("칭찬", "간식", "먹이", "사료", "장난감", "클리커", "쓰다듬", "산책으로", "보상으로")
)

#: Reassurance the evidence does not support. The card says punishment does not help; it
#: says nothing about whether the reader should stop worrying.
_UNFOUNDED_REASSURANCE = compile_terms(
    (
        "걱정하지 마",
        "걱정 마",
        "걱정하지 않으셔도",
        "안심하",
        "괜찮아요",
        "괜찮습니다",
        "문제없",
        "금방",
        "곧 좋아",
        "쉽게 해결",
    )
)

#: "도움이 되지 않는다" escalated into active harm. The distinction is the card's, not a
#: matter of tone: not helping and making things worse are different claims.
_CAUSAL_ESCALATION = compile_terms(
    ("방해", "악화", "나빠", "역효과", "해롭", "해가 되", "손상", "망가", "부정적인 영향")
)

#: A schedule the cards explicitly decline to give.
_INVENTED_SCHEDULE = compile_terms(
    ("며칠", "일주일", "한 달", "주에", "하루에", "매일", "몇 번", "회 정도", "시간 안에")
)

#: Asserting to the reader that they found the mess after the fact. Allowed only when the
#: question actually said so; the plan's general "나중에 발견한 실수는" is not this.
_ASSERTED_DISCOVERY = compile_terms(("발견하셨", "발견하신", "발견했군", "발견하셨군"))

#: The question is about a mess found after the fact.
_DISCOVERY_CONTEXT = compile_terms(("나중에", "뒤늦게", "발견", "치우고", "지나서", "한참"))


class PhrasingVerdict(StrEnum):
    ACCEPTED = "accepted"
    #: The payload was unusable: not JSON, fenced, empty, or citing another card.
    INVALID = "invalid"
    #: Parsed fine, but says something the plan does not.
    OUT_OF_PLAN = "out_of_plan"


@dataclass(frozen=True)
class PhrasingResult:
    verdict: PhrasingVerdict
    answer: str | None = None
    #: Why it was rejected. Logged and asserted on; never shown to the reader.
    reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.verdict is PhrasingVerdict.ACCEPTED


def build_phrasing_messages(
    *,
    message: str,
    response_language: ContentLanguage,
    card: EvidenceCard,
    plan: ResponsePlan,
) -> list[dict[str, str]]:
    """Build the request. Only approved content crosses this boundary.

    No URL, locator, source registry entry, license text, local path, API key or Qdrant
    setting is included — the card's own identifiers and text, the plan, and the question.
    """

    payload = {
        "question": message,
        "answer_language": response_language.value,
        "card_id": str(card.card_id),
        "claim": card.claim,
        "limitations": list(card.limitations),
        "reviewed_plan": {
            "opening": plan.opening,
            "steps": [step.text for step in plan.steps],
            "closing": plan.closing,
        },
    }
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _evidence_text(card: EvidenceCard, plan: ResponsePlan) -> str:
    return " ".join(
        [
            card.claim,
            *card.limitations,
            plan.opening,
            *(step.text for step in plan.steps),
            plan.closing,
        ]
    )


def validate_phrasing(
    raw: str,
    *,
    message: str,
    card: EvidenceCard,
    plan: ResponsePlan,
) -> PhrasingResult:
    """Accept the rephrasing only if it stayed inside the plan.

    The model is never asked whether the question is answerable, so no ``answerable``
    field is read. If one is present it is ignored: that decision was already made.
    """

    if _WRAPPING_CODE_FENCE.match(raw.strip()):
        return PhrasingResult(PhrasingVerdict.INVALID, reason="response was wrapped in a fence")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return PhrasingResult(PhrasingVerdict.INVALID, reason="response was not JSON")
    if not isinstance(payload, dict):
        return PhrasingResult(PhrasingVerdict.INVALID, reason="response was not a JSON object")

    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return PhrasingResult(PhrasingVerdict.INVALID, reason="answer was empty")
    answer = answer.strip()

    raw_ids = payload.get("used_card_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return PhrasingResult(PhrasingVerdict.INVALID, reason="used_card_ids was missing")
    try:
        used = {UUID(str(item)) for item in raw_ids}
    except (ValueError, TypeError):
        return PhrasingResult(PhrasingVerdict.INVALID, reason="used_card_ids was not a UUID list")
    if not used <= {card.card_id}:
        return PhrasingResult(PhrasingVerdict.INVALID, reason="cited a card it was not given")

    evidence = _evidence_text(card, plan)
    normalized_answer = normalize(answer)
    normalized_evidence = normalize(evidence)

    stray_numbers = sorted({token for token in _DIGITS.findall(answer) if token not in evidence})
    if stray_numbers:
        return PhrasingResult(
            PhrasingVerdict.OUT_OF_PLAN, reason=f"numbers not in the plan: {stray_numbers}"
        )
    stray_latin = sorted(
        {
            token
            for token in _LATIN.findall(answer)
            if token.casefold() not in normalized_evidence.casefold()
        }
    )
    if stray_latin:
        return PhrasingResult(
            PhrasingVerdict.OUT_OF_PLAN, reason=f"latin words not in the plan: {stray_latin}"
        )

    for label, pattern in (
        ("a reinforcer the card does not name", _UNAPPROVED_MEANS),
        ("reassurance the evidence does not support", _UNFOUNDED_REASSURANCE),
        ("escalated 도움이 되지 않는다 into active harm", _CAUSAL_ESCALATION),
        ("a schedule the card declines to give", _INVENTED_SCHEDULE),
    ):
        hit = pattern.search(normalized_answer)
        # A marker the plan itself uses is not an addition. "점진적으로 늘려" contains no
        # schedule marker, but a future card might, and the plan is the authority.
        if hit and hit.group(0) not in normalized_evidence:
            return PhrasingResult(PhrasingVerdict.OUT_OF_PLAN, reason=f"{label}: {hit.group(0)}")

    # The plan may state the rule generally ("나중에 발견한 실수는"). Telling the reader
    # that *they* found it later is a claim about their situation, and only their own
    # question can establish it.
    asserted = _ASSERTED_DISCOVERY.search(normalized_answer)
    if asserted and not _DISCOVERY_CONTEXT.search(normalize(message)):
        return PhrasingResult(
            PhrasingVerdict.OUT_OF_PLAN,
            reason=f"assumed a situation the question did not state: {asserted.group(0)}",
        )

    if "!" in answer or "！" in answer:
        return PhrasingResult(PhrasingVerdict.OUT_OF_PLAN, reason="added an exclamation")

    return PhrasingResult(PhrasingVerdict.ACCEPTED, answer=answer)
