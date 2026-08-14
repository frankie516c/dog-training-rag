"""A minimal, deliberately narrow emergency gate for the training chat.

This service answers training questions from approved training evidence. A suspected
toxic ingestion is not a training question, so it must never be routed into training
retrieval and must never reach a generation provider.

The substance list is intentionally small and explicit. It is not a veterinary toxicology
knowledge base and must not grow into one: this gate only decides "stop and send the
person to a vet", never what happened or what to do about it.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain import ContentLanguage, SafetyLevel
from backend.app.text_match import compile_terms, normalize

_HIGH_RISK_SUBSTANCES = compile_terms(
    (
        "초콜릿",
        "초콜렛",
        "자일리톨",
        "포도",
        "건포도",
        "양파",
        "마늘",
        "마카다미아",
        "chocolate",
        "xylitol",
        "grape",
        "raisin",
        "onion",
        "garlic",
        "macadamia",
    )
)

# Ingestion, stated or suspected. Korean marks suspicion with a following modifier
# ("먹은 것 같아요", "삼킨 듯해요"), so the verb form is what has to be recognised — the
# adnominal 먹은 / 삼킨 are separate syllables from 먹었 / 삼키 and matched nothing before.
# A substance alone is still not enough: "초콜릿색 래브라도" carries no ingestion at all.
_INGESTION = compile_terms(
    (
        "먹었",
        "먹어",
        "먹고",
        "먹은",
        "삼켰",
        "삼키",
        "삼킨",
        "삼켜",
        "섭취",
        "주워 먹",
        "주워먹",
        "물어 삼",
        "ate",
        "eaten",
        "eat",
        "swallow",
        "ingest",
    )
)

_URGENT_MESSAGE_KO = (
    "이 질문은 훈련 상담 범위를 벗어납니다. 중독 가능성이 있으므로 지금 바로 "
    "가까운 동물병원 또는 야간·응급 동물병원에 연락해 수의사의 안내를 받으세요."
)
_URGENT_MESSAGE_EN = (
    "This question is outside training guidance. Possible poisoning is time critical, so "
    "contact your nearest veterinary clinic or an emergency veterinary hospital now."
)
# The first sentence is the action. What this service cannot do comes after it: a reader
# in this situation should not have to get past a scope disclaimer to find "call a vet".
_URGENT_ANSWER_KO = (
    "지금 바로 가까운 동물병원이나 야간·응급 동물병원에 연락해 주세요. "
    "중독 가능성이 있어 시간이 중요합니다.\n\n"
    "무엇을 얼마나 먹었는지, 언제 먹었는지 알고 계신 만큼 수의사에게 전달해 주세요.\n\n"
    "이 서비스는 훈련 근거로만 답변하기 때문에 섭취량 판단, 진단, 구토 유도를 비롯한 "
    "처치 방법은 안내하지 않습니다."
)
_URGENT_ANSWER_EN = (
    "Contact your nearest veterinary clinic or an emergency veterinary hospital right now. "
    "Possible poisoning is time critical.\n\n"
    "Tell the veterinarian what was eaten, how much, and when, as far as you know.\n\n"
    "This service answers from training evidence only, so it does not assess dose, "
    "diagnose, or advise on treatment including inducing vomiting."
)


@dataclass(frozen=True)
class SafetyFinding:
    """One triggered safety rule, carrying only what the response needs."""

    level: SafetyLevel

    def notice_message(self, language: ContentLanguage) -> str:
        if language is ContentLanguage.ENGLISH:
            return _URGENT_MESSAGE_EN
        return _URGENT_MESSAGE_KO

    def answer(self, language: ContentLanguage) -> str:
        if language is ContentLanguage.ENGLISH:
            return _URGENT_ANSWER_EN
        return _URGENT_ANSWER_KO


def detect_safety_risk(message: str) -> SafetyFinding | None:
    """Return an urgent finding when a known high-risk substance is paired with ingestion.

    Either signal alone is not enough. "강아지가 간식을 먹었어요" has ingestion but no
    high-risk substance and is not urgent.
    """

    text = normalize(message)
    if _HIGH_RISK_SUBSTANCES.search(text) and _INGESTION.search(text):
        return SafetyFinding(level=SafetyLevel.URGENT)
    return None
