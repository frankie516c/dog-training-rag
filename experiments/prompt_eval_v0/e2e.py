"""End-to-end check of the winning prompt, with real retrieval.

Reported separately from the prompt-only results and never merged with them: this run adds
BGE-M3 retrieval and the full gate pipeline, so a difference here can come from retrieval
as well as from the prompt.

Production code is not modified. The prompt is swapped by an answerer that mirrors
`GroundedAnswerer.draft` but builds its messages from the experiment prompt set; validation
is still the production `validate_draft`.

    python -m experiments.prompt_eval_v0.e2e --version v1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from backend.app.answerability import classify_question_intent
from backend.app.chat_service import ChatService
from backend.app.config import Settings
from backend.app.data_validation import DataPaths
from backend.app.domain import ChatRequest, ContentLanguage, EvidenceCard
from backend.app.embeddings import BgeM3EmbeddingProvider
from backend.app.generation import OpenAICompatibleGenerationProvider
from backend.app.grounded import DraftResult, validate_draft
from backend.app.retrieval import EvidenceRetrieval
from backend.app.scope import route_query_scope
from experiments.prompt_eval_v0.prompts import build_messages

RESULTS_DIR = Path(__file__).parent / "results"

#: (question, why it is here, whether generation is expected to run)
E2E_QUESTIONS = (
    ("배변 실수를 발견했을 때 어떻게 해야 하나요?", "배변 guidance how_to", True),
    ("이동장을 무서워하는 강아지는 어떻게 적응시키나요?", "이동장 guidance how_to", True),
    ("혐오 자극 훈련 연구에서 확인된 결과를 설명해주세요.", "전자 목줄 research explanation", True),
    ("강아지가 왜 사람에게 점프하나요?", "점프 research explanation", True),
    ("켄넬 짖음 연구에서 실제로 관찰된 것은 무엇인가요?", "켄넬 짖음 research explanation", True),
    ("전자 목줄이 보상 훈련보다 효과적인가요?", "comparison: exact-claim 조립", False),
    ("산책할 때 리드줄을 계속 당겨요.", "절차 근거 부족: insufficient", False),
    ("강아지에게 손을 가르치고 싶어요.", "unsupported: retrieval 0", False),
    ("강아지가 초콜릿을 먹었어요.", "urgent: retrieval 0", False),
)


class PromptVersionAnswerer:
    """Same contract as GroundedAnswerer, with a selectable system instruction."""

    def __init__(self, *, provider: OpenAICompatibleGenerationProvider, version: str) -> None:
        self._provider = provider
        self._version = version
        self.calls = 0

    async def draft(
        self,
        *,
        message: str,
        response_language: ContentLanguage,
        cards: Sequence[EvidenceCard],
    ) -> DraftResult:
        messages = build_messages(
            version=self._version,
            message=message,
            response_language=response_language,
            cards=cards,
        )
        self.calls += 1
        try:
            raw = await self._provider.complete(messages)
        except Exception:
            return DraftResult.invalid()
        return validate_draft(raw, cards=cards, response_language=response_language)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Prompt Eval v0 end-to-end run.")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = Settings()
    base_url = (settings.generation_base_url or "").strip()
    model = (settings.generation_model or "").strip()
    if not base_url or not model:
        raise SystemExit("GENERATION_BASE_URL and GENERATION_MODEL must be set")

    provider = OpenAICompatibleGenerationProvider(base_url=base_url, model=model)
    answerer = PromptVersionAnswerer(provider=provider, version=args.version)
    retrieval = EvidenceRetrieval(
        paths=DataPaths(),
        qdrant_path=settings.qdrant_path,
        collection_name=settings.qdrant_collection,
        embedder=BgeM3EmbeddingProvider(
            model_id=settings.embedding_model_id,
            device=settings.embedding_device,
        ),
    )
    service = ChatService(retriever=retrieval, grounded=answerer)

    records = []
    try:
        for index, (question, purpose, expects_generation) in enumerate(E2E_QUESTIONS, 1):
            before = answerer.calls
            started = time.perf_counter()
            response = asyncio.run(service.answer(ChatRequest(message=question)))
            latency_ms = round((time.perf_counter() - started) * 1000)
            cited = [str(item.card_id) for item in response.citations]
            unique_cited = sorted(set(cited))
            record = {
                "prompt_version": args.version,
                "index": index,
                "message": question,
                "purpose": purpose,
                "expects_generation": expects_generation,
                "intent": classify_question_intent(question).value,
                "scope": (route_query_scope(question) or "unsupported"),
                "status": response.status.value,
                "provider_calls": answerer.calls - before,
                "generation_matched_expectation": (answerer.calls - before > 0)
                is expects_generation,
                "citation_card_ids": unique_cited,
                "limitations": len(response.limitations),
                "safety_level": (
                    response.safety_notice.level.value if response.safety_notice else None
                ),
                "answer": response.answer,
                "latency_ms": latency_ms,
            }
            records.append(record)
            print(
                f"  {index}. {record['intent']:<12}{record['status']:<22} "
                f"provider={record['provider_calls']} cites={len(unique_cited)} "
                f"{latency_ms:>6}ms  {question[:28]}"
            )
    finally:
        retrieval.close()

    out = args.out or RESULTS_DIR / f"e2e_{args.version}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
