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

_INGESTION = compile_terms(
    (
        "먹었",
        "먹어",
        "먹고",
        "삼켰",
        "삼키",
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
_URGENT_ANSWER_KO = (
    "훈련 근거로 답변할 수 있는 질문이 아닙니다. 즉시 가까운 동물병원 또는 응급 동물병원에 "
    "연락하세요. 이 서비스는 섭취량 판단, 진단, 처치 방법을 안내하지 않습니다."
)
_URGENT_ANSWER_EN = (
    "This is not a question that training evidence can answer. Contact your nearest "
    "veterinary clinic or an emergency veterinary hospital immediately. This service does "
    "not assess dose, diagnose, or advise on treatment."
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
