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
    SourceRegistryEntry,
)
from backend.app.generation import GenerationEvidence, GenerationProvider
from backend.app.retrieval import DEFAULT_TOP_K, SearchResult

PROVISIONAL_COSINE_THRESHOLD = 0.45


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
        threshold: float = PROVISIONAL_COSINE_THRESHOLD,
        request_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._threshold = threshold
        self._request_id_factory = request_id_factory

    async def answer(self, request: ChatRequest) -> ChatResponse:
        try:
            search_results = self._retriever.search(request.message, top_k=DEFAULT_TOP_K)
        except Exception as exc:
            raise ChatServiceUnavailable("evidence retrieval failed") from exc

        selected = [result for result in search_results if result.score >= self._threshold]
        if not selected:
            return ChatResponse(
                request_id=self._request_id_factory(),
                status=ChatStatus.INSUFFICIENT_EVIDENCE,
                answer=_insufficient_answer(request.response_language),
                answer_language=request.response_language,
                citations=[],
            )

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


def _insufficient_answer(language: ContentLanguage) -> str:
    if language is ContentLanguage.ENGLISH:
        return "There is not enough validated evidence to answer this question."
    return "검증된 근거가 충분하지 않아 이 질문에 답변하기 어렵습니다."


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
