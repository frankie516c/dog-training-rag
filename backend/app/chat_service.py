from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.answerability import (
    QuestionIntent,
    card_supports_intent,
    classify_question_intent,
)
from backend.app.composition import EvidenceCompositionError, compose_evidence_answer
from backend.app.domain import (
    ChatCitation,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ContentLanguage,
    EvidenceCard,
    EvidenceLevel,
    SafetyNotice,
    SourceRegistryEntry,
)
from backend.app.grounded import DraftVerdict, GroundedAnswerer
from backend.app.response_plans import compose_planned_answer
from backend.app.retrieval import DEFAULT_TOP_K, SearchResult
from backend.app.safety import detect_safety_risk
from backend.app.scope import TrainingScope, card_scope, route_query_scope

PROVISIONAL_SCOPE_MATCHED_MINIMUM = 0.40

# Candidate pool pulled from the index before scope filtering. It is deliberately larger
# than the CLI default so an on-topic card is not lost behind off-topic neighbours, and
# it is not derived from the current corpus size.
CANDIDATE_TOP_K = 20

# Intents allowed to reach the generation provider.
#
# COMPARISON is excluded on purpose. The draft validator checks vocabulary, not meaning, so
# it cannot see a dropped negation ("나타나지 않았다" -> "나타났다") or a swapped comparison
# subject — both reuse the evidence's own words and numbers. That is exactly the failure two
# local 4B models produced in checkpoints 5G and 5G-1, and it is the failure with the worst
# consequence here: a reversed welfare conclusion carries a correct-looking citation.
# Until a semantic guard exists, a comparison answer is the reviewed claim itself.
GENERATED_INTENTS = frozenset({QuestionIntent.HOW_TO, QuestionIntent.EXPLANATION})

# Checkpoint 5J-1. One fixed Korean query, in the vocabulary the housetraining card is
# written in, used only to retry a housetraining how_to that retrieved nothing. It never
# reaches the user: scope, intent, citations and the answer all come from the original
# question. No other scope has a retry.
HOUSETRAINING_CANONICAL_QUERY = "강아지 배변 훈련 배변 실수"


class ChatServiceUnavailable(RuntimeError):
    """The retrieval-backed chat service cannot safely answer right now."""


class ChatRetriever(Protocol):
    def search(self, query: str, *, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]: ...

    def sources_by_id(self) -> dict[str, SourceRegistryEntry]: ...


class ChatService:
    """Answer from retrieved evidence, without writing a sentence of its own.

    One selection pipeline, three ways to answer from what it selects, tried in order:

    * a reviewed response plan, when one is bound to this exact card, hash and language
      (checkpoint 5J) — the only path that gives procedural guidance;
    * a generated draft, only if an answerer was passed in and the intent allows it. The
      application does not pass one; see `backend.app.main`. Comparison never uses it, for
      the reason recorded at GENERATED_INTENTS;
    * the reviewed claims themselves, composed verbatim (checkpoint 5H).

    None of them runs when the evidence cannot answer the kind of question that was asked.
    See docs/grounded-rag.md.
    """

    def __init__(
        self,
        *,
        retriever: ChatRetriever,
        grounded: GroundedAnswerer | None = None,
        scope_matched_minimum: float = PROVISIONAL_SCOPE_MATCHED_MINIMUM,
        candidate_top_k: int = CANDIDATE_TOP_K,
        composer: Callable[[Sequence[EvidenceCard]], str] = compose_evidence_answer,
        request_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._retriever = retriever
        self._grounded = grounded
        self._scope_matched_minimum = scope_matched_minimum
        self._candidate_top_k = candidate_top_k
        self._composer = composer
        self._request_id_factory = request_id_factory

    async def answer(self, request: ChatRequest) -> ChatResponse:
        safety = detect_safety_risk(request.message)
        if safety is not None:
            return ChatResponse(
                request_id=self._request_id_factory(),
                status=ChatStatus.INSUFFICIENT_EVIDENCE,
                answer=safety.answer(request.response_language),
                answer_language=request.response_language,
                citations=[],
                safety_notice=SafetyNotice(
                    level=safety.level,
                    message=safety.notice_message(request.response_language),
                ),
            )

        scope = route_query_scope(request.message)
        if scope is None:
            return self._insufficient(request, _unsupported_answer(request.response_language))

        try:
            search_results = self._retriever.search(request.message, top_k=self._candidate_top_k)
        except Exception as exc:
            raise ChatServiceUnavailable("evidence retrieval failed") from exc

        selected = self._eligible(search_results, scope=scope, request=request)
        intent = classify_question_intent(request.message)

        # Checkpoint 5J-1. "응가를 아무 데나 해요" routes to housetraining and reads as a
        # how_to, but the colloquial wording scores its own card below the threshold —
        # 0.378 against a 0.40 minimum — so the user gets nothing while the evidence sits
        # one place down the list. Rather than lower the bar for every question, the
        # question is asked again in the corpus's own words. The threshold, the index and
        # the cards are untouched, and every gate below runs on the result exactly as it
        # runs on the original.
        if (
            not selected
            and scope is TrainingScope.HOUSETRAINING
            and intent is QuestionIntent.HOW_TO
        ):
            try:
                retried = self._retriever.search(
                    HOUSETRAINING_CANONICAL_QUERY, top_k=self._candidate_top_k
                )
            except Exception as exc:
                raise ChatServiceUnavailable("evidence retrieval failed") from exc
            selected = self._eligible(
                _merge_by_card(search_results, retried), scope=scope, request=request
            )

        if not selected:
            return self._insufficient(request, _insufficient_answer(request.response_language))

        # Sharing a topic is not answering the question. A feasibility study cannot serve a
        # how_to request, so it is removed here — before generation and before the
        # deterministic fallback, so the fallback never shows a research summary as if it
        # were the requested procedure.
        usable = [result for result in selected if card_supports_intent(result.card, intent)]
        if not usable:
            return self._insufficient(request, _insufficient_answer(request.response_language))

        # A reviewed procedural answer, when one exists for this exact card and language.
        # Checked before generation and before composition: it is the only path that can
        # tell the reader what to do, and it is fixed text, so it cannot drift from the
        # evidence. No plan means no procedural answer — fall through, never improvise.
        if intent is QuestionIntent.HOW_TO:
            planned = compose_planned_answer(
                [result.card for result in usable], language=request.response_language
            )
            if planned is not None:
                answer, plan_cards = planned
                planned_ids = {card.card_id for card in plan_cards}
                cited = [item for item in usable if item.card.card_id in planned_ids]
                if cited:
                    return self._answered(request, answer, cited)

        if self._grounded is not None and intent in GENERATED_INTENTS:
            result = await self._grounded.draft(
                message=request.message,
                response_language=request.response_language,
                cards=[result.card for result in usable],
            )
            if result.verdict is DraftVerdict.NOT_ANSWERABLE:
                # The model looked at this evidence and said it cannot answer. Take that
                # at face value rather than showing a claim it just rejected.
                return self._insufficient(request, _insufficient_answer(request.response_language))
            if result.draft is not None:
                cited = [item for item in usable if item.card_id in result.draft.used_card_ids]
                if cited:
                    return self._answered(request, result.draft.answer, cited)

        try:
            answer = self._composer([result.card for result in usable])
        except EvidenceCompositionError:
            return self._insufficient(request, _insufficient_answer(request.response_language))
        return self._answered(request, answer, usable)

    def _eligible(
        self,
        results: Sequence[SearchResult],
        *,
        scope: TrainingScope,
        request: ChatRequest,
    ) -> list[SearchResult]:
        """Cards this request may use: right scope, right language, over the threshold.

        Nothing is translated, so a language mismatch removes the card from the answer,
        the citations and the limitations alike.
        """

        return [
            result
            for result in results
            if card_scope(result.card) is scope
            and result.card.claim_language is request.response_language
            and result.score >= self._scope_matched_minimum
        ]

    def _answered(
        self,
        request: ChatRequest,
        answer: str,
        results: list[SearchResult],
    ) -> ChatResponse:
        try:
            sources_by_id = self._retriever.sources_by_id()
            citations = _build_citations(results, sources_by_id)
        except Exception as exc:
            raise ChatServiceUnavailable("citation construction failed") from exc

        return ChatResponse(
            request_id=self._request_id_factory(),
            status=ChatStatus.ANSWERED,
            answer=answer,
            answer_language=request.response_language,
            citations=citations,
            limitations=_collect_limitations(results),
        )

    def _insufficient(self, request: ChatRequest, answer: str) -> ChatResponse:
        return ChatResponse(
            request_id=self._request_id_factory(),
            status=ChatStatus.INSUFFICIENT_EVIDENCE,
            answer=answer,
            answer_language=request.response_language,
            citations=[],
        )


def _merge_by_card(
    first: Sequence[SearchResult], second: Sequence[SearchResult]
) -> list[SearchResult]:
    """One entry per card, keeping the higher score, first list's order first."""

    best: dict[UUID, SearchResult] = {}
    for result in (*first, *second):
        current = best.get(result.card.card_id)
        if current is None or result.score > current.score:
            best[result.card.card_id] = result
    return sorted(best.values(), key=lambda result: result.score, reverse=True)


def _insufficient_answer(language: ContentLanguage) -> str:
    if language is ContentLanguage.ENGLISH:
        return "There is not enough validated evidence to answer this question."
    return "검증된 근거가 충분하지 않아 이 질문에 답변하기 어렵습니다."


def _unsupported_answer(language: ContentLanguage) -> str:
    if language is ContentLanguage.ENGLISH:
        return "This question is outside the training topics covered by validated evidence."
    return "현재 검증된 훈련 근거 범위에서는 이 질문에 답하기 어렵습니다."


def _collect_limitations(results: list[SearchResult]) -> list[str]:
    limitations: list[str] = []
    seen: set[str] = set()
    for result in results:
        for limitation in result.card.limitations:
            key = limitation.casefold()
            if key not in seen:
                seen.add(key)
                limitations.append(limitation)
    return limitations


def _build_citations(
    results: list[SearchResult],
    sources_by_id: dict[str, SourceRegistryEntry],
) -> list[ChatCitation]:
    citations: list[ChatCitation] = []
    seen: set[tuple[UUID, str]] = set()
    for result in results:
        source_refs = sorted(
            (
                source_ref
                for source_ref in result.card.source_refs
                if source_ref.evidence_level in {EvidenceLevel.DIRECT, EvidenceLevel.SUPPORTING}
            ),
            key=lambda source_ref: (
                source_ref.source_id,
                0 if source_ref.evidence_level is EvidenceLevel.DIRECT else 1,
                json.dumps(
                    source_ref.locator.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        for source_ref in source_refs:
            citation_key = (result.card_id, source_ref.source_id)
            if citation_key in seen:
                continue
            source = sources_by_id.get(source_ref.source_id)
            if source is None:
                raise ChatServiceUnavailable(
                    f"validated source registry is missing {source_ref.source_id!r}"
                )
            citations.append(
                ChatCitation(
                    card_id=result.card_id,
                    source_id=source.source_id,
                    source_name=source.title,
                    canonical_url=source.canonical_url,
                    locator=source_ref.locator,
                    evidence_level=source_ref.evidence_level,
                )
            )
            seen.add(citation_key)
    return citations
