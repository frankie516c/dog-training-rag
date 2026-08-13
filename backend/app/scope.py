"""Deterministic training-scope routing for questions and approved evidence cards.

This module holds no model, no network call and no LLM. It exists because a single
global cosine threshold could not separate on-topic from off-topic evidence: an
unrelated card frequently outscored the correct one. Scope agreement is therefore
checked before any dense score is trusted.

`TrainingScope` is internal. It is never accepted in a request, never returned in a
response and never written to the Qdrant payload.
"""

from __future__ import annotations

import re
from enum import StrEnum

from backend.app.domain import EvidenceCard
from backend.app.text_match import compile_terms as _pattern
from backend.app.text_match import normalize as _normalize


class TrainingScope(StrEnum):
    """The training question categories that current approved cards can support."""

    AVERSIVE_OR_ECOLLAR = "aversive_or_ecollar"
    JUMPING_UP = "jumping_up"
    KENNEL_BARKING = "kennel_barking"
    LEASH_WALKING = "leash_walking"
    HOUSETRAINING = "housetraining"
    CRATE_ADAPTATION = "crate_adaptation"


# --------------------------------------------------------------------------------------
# Card scope markers
#
# Markers are matched against a card's topic and tags only. `kennel` is deliberately
# absent: it appears both on the kennel-barking card and on the crate card, so treating
# it as decisive would map one card to two scopes and fail closed.
# --------------------------------------------------------------------------------------

_CARD_MARKERS: tuple[tuple[TrainingScope, re.Pattern[str]], ...] = (
    (
        TrainingScope.AVERSIVE_OR_ECOLLAR,
        _pattern(("aversive", "e-collar", "ecollar", "shock collar", "혐오 자극", "혐오 훈련")),
    ),
    (TrainingScope.JUMPING_UP, _pattern(("jumping up", "jumping-up", "점프", "뛰어오르"))),
    (TrainingScope.KENNEL_BARKING, _pattern(("bark", "짖음", "짖는"))),
    (
        TrainingScope.LEASH_WALKING,
        _pattern(("leash walking", "loose leash", "리드줄", "산책줄")),
    ),
    (TrainingScope.HOUSETRAINING, _pattern(("housetraining", "house training", "배변"))),
    (TrainingScope.CRATE_ADAPTATION, _pattern(("crate", "크레이트", "이동장"))),
)


def card_scope(card: EvidenceCard) -> TrainingScope | None:
    """Map one approved card to exactly one scope using its topic and tags.

    Returns None when no marker matches or when markers for more than one scope match.
    Ambiguity fails closed: an unmapped card is dropped from retrieval candidates rather
    than guessed into a scope.
    """

    text = _normalize(" ".join((card.topic, *card.tags)))
    matched = [scope for scope, pattern in _CARD_MARKERS if pattern.search(text)]
    if len(matched) != 1:
        return None
    return matched[0]


# --------------------------------------------------------------------------------------
# Query scope router
#
# Rules are evaluated in the order below and the first match wins. Order matters where
# vocabulary overlaps:
#   * aversive before leash, so "전자 목줄" is not read as a plain leash question
#   * barking before crate, so "켄넬 안에서 계속 짖어요" is kennel_barking while
#     "이동장에 들어가는 것을 무서워해요" is crate_adaptation
# A bare generic word never decides a scope on its own. Generic words such as 목줄,
# leash, 소변 only route when a second, behaviour-specific term is present too.
# --------------------------------------------------------------------------------------

_AVERSIVE = _pattern(
    (
        "전자 목줄",
        "전자목줄",
        "전기 목줄",
        "전기목줄",
        "충격 목줄",
        "충격목줄",
        "혐오 훈련",
        "혐오 자극",
        "혐오적 훈련",
        "e-collar",
        "ecollar",
        "e collar",
        "shock collar",
        "aversive",
    )
)

_BARK = _pattern(("짖", "bark"))
_KENNEL_CONTEXT = _pattern(
    ("켄넬", "캔넬", "견사", "보호소", "이동장", "크레이트", "kennel", "shelter", "crate")
)

_CRATE_CONTAINER = _pattern(("이동장", "크레이트", "켄넬", "캔넬", "crate", "kennel"))
_CRATE_ADAPTATION = _pattern(
    (
        "적응",
        "들어가",
        "들어오",
        "무서",
        "두려",
        "겁내",
        "겁먹",
        "싫어",
        "거부",
        "훈련",
        "adapt",
        "afraid",
        "fear",
        "scared",
        "anxious",
        "refuse",
        "go in",
        "gets in",
    )
)

_HOUSETRAINING = _pattern(
    ("배변", "대소변", "housetraining", "house training", "potty training", "toilet training")
)
# Colloquial 배설 표현을 포함한다. 이 단어들은 단독으로 범주를 정하지 않고 아래 장소·실수
# 표현과 함께 나올 때만 housetraining이 된다. `쉬`는 "쉬고 있어요", "가르치기 쉬운"과 겹치므로
# 조사가 붙은 형태만 인식한다.
_ELIMINATION = _pattern(
    ("소변", "오줌", "대변", "똥", "응가", "쉬야", "쉬를", "쉬해", "urinat", "defecat", "poop")
)
_ELIMINATION_CONTEXT = _pattern(
    (
        "실수",
        "아무 데",
        "아무데",
        "가리",
        "마킹",
        "훈련",
        "집 안",
        "집안",
        "실내",
        "바닥",
        "패드",
        "training",
        "accident",
        "indoors",
    )
)

_JUMP = _pattern(
    ("점프", "뛰어올라", "뛰어오르", "뛰어 올라", "jump up", "jumping up", "jumping on")
)
_JUMP_CONTACT = _pattern(("달려들", "올라타", "매달리"))
_JUMP_TARGET = _pattern(("앞발", "사람", "손님", "보호자", "방문객", "가슴", "어깨"))

_LEASH = _pattern(("리드줄", "산책줄", "loose leash", "leash walking", "leash pulling"))
_LEASH_GENERIC = _pattern(("목줄", "leash"))
_LEASH_PULL = _pattern(("당기", "당겨", "당김", "끌어", "끕니", "잡아당", "pull"))


def route_query_scope(message: str) -> TrainingScope | None:
    """Route a question to one supported scope, or None when it is out of scope.

    Questions about hand targeting, sit, down, stay, recall or release have no
    procedural evidence in the approved cards, so they intentionally return None
    instead of being guessed into a neighbouring scope.
    """

    text = _normalize(message)

    if _AVERSIVE.search(text):
        return TrainingScope.AVERSIVE_OR_ECOLLAR
    if _BARK.search(text) and _KENNEL_CONTEXT.search(text):
        return TrainingScope.KENNEL_BARKING
    if _CRATE_CONTAINER.search(text) and _CRATE_ADAPTATION.search(text):
        return TrainingScope.CRATE_ADAPTATION
    if _HOUSETRAINING.search(text) or (
        _ELIMINATION.search(text) and _ELIMINATION_CONTEXT.search(text)
    ):
        return TrainingScope.HOUSETRAINING
    if _JUMP.search(text) or (_JUMP_CONTACT.search(text) and _JUMP_TARGET.search(text)):
        return TrainingScope.JUMPING_UP
    if _LEASH.search(text) or (_LEASH_GENERIC.search(text) and _LEASH_PULL.search(text)):
        return TrainingScope.LEASH_WALKING
    return None
