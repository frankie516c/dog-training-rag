from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.domain import (
    ChatCitation,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ContentLanguage,
    EvidenceLevel,
    SafetyNotice,
    SourceRegistryEntry,
)
from backend.app.generation import GenerationEvidence, GenerationProvider
from backend.app.retrieval import DEFAULT_TOP_K, SearchResult
from backend.app.safety import detect_safety_risk
from backend.app.scope import card_scope, route_query_scope

PROVISIONAL_SCOPE_MATCHED_MINIMUM = 0.40

# Candidate pool pulled from the index before scope filtering. It is deliberately larger
# than the CLI default so an on-topic card is not lost behind off-topic neighbours, and
# it is not derived from the current corpus size.
CANDIDATE_TOP_K = 20


class ChatServiceUnavailable(RuntimeError):
    """The retrieval-backed chat service cannot safely answer right now."""


class ChatRetriever(Protocol):
    def search(self, query: str, *, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]: ...

    def sources_by_id(self) -> dict[str, SourceRegistryEntry]: ...


class ChatService:
    def __init__(
        self,
        *,
        retriever: ChatRetriever,
        generator: GenerationProvider,
        scope_matched_minimum: float = PROVISIONAL_SCOPE_MATCHED_MINIMUM,
        candidate_top_k: int = CANDIDATE_TOP_K,
        request_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._scope_matched_minimum = scope_matched_minimum
        self._candidate_top_k = candidate_top_k
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

        selected = [
            result
            for result in search_results
            if card_scope(result.card) is scope and result.score >= self._scope_matched_minimum
        ]
        if not selected:
            return self._insufficient(request, _insufficient_answer(request.response_language))

        evidence = tuple(
            GenerationEvidence(
                claim=result.card.claim,
                topic=result.card.topic,
                limitations=tuple(result.card.limitations),
            )
            for result in selected
        )
        try:
            sources_by_id = self._retriever.sources_by_id()
            citations = _build_citations(selected, sources_by_id)
        except Exception as exc:
            raise ChatServiceUnavailable("citation construction failed") from exc

        try:
            answer = await self._generator.generate(
                message=request.message,
                response_language=request.response_language,
                evidence=evidence,
            )
        except Exception as exc:
            raise ChatServiceUnavailable("generation provider failed") from exc
        if not answer.strip():
            raise ChatServiceUnavailable("generation provider returned an empty answer")

        return ChatResponse(
            request_id=self._request_id_factory(),
            status=ChatStatus.ANSWERED,
            answer=answer,
            answer_language=request.response_language,
            citations=citations,
            limitations=_collect_limitations(selected),
        )

    def _insufficient(self, request: ChatRequest, answer: str) -> ChatResponse:
        return ChatResponse(
            request_id=self._request_id_factory(),
            status=ChatStatus.INSUFFICIENT_EVIDENCE,
            answer=answer,
            answer_language=request.response_language,
            citations=[],
        )


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
