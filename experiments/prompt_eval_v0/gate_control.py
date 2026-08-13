"""Gate regression check. Not scored, and never calls a model.

The four control questions must terminate before generation for four different reasons.
A counting provider proves the provider was never asked; if any of these regressed, the
prompt scores would be measuring a pipeline that no longer gates.

    python -m experiments.prompt_eval_v0.gate_control
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from backend.app.chat_service import ChatService
from backend.app.domain import ChatRequest, SourceRegistryEntry
from backend.app.grounded import GroundedAnswerer
from backend.app.retrieval import SearchResult
from backend.app.scope import card_scope, route_query_scope
from experiments.prompt_eval_v0.fixture import (
    GATE_QUESTIONS,
    approved_cards,
    source_registry,
)

RESULTS_DIR = Path(__file__).parent / "results"


class CountingProvider:
    """Fails loudly if the pipeline ever reaches generation for a control question."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return json.dumps({"answerable": True, "answer": "차단 실패", "used_card_ids": []})


class ScopeRetriever:
    """Returns every approved card whose scope matches the question, as retrieval would."""

    def __init__(self) -> None:
        self.search_calls: list[str] = []

    def search(self, query: str, *, top_k: int = 5) -> list[SearchResult]:
        self.search_calls.append(query)
        scope = route_query_scope(query)
        cards = [card for card in approved_cards() if card_scope(card) is scope]
        return [
            SearchResult(card_id=card.card_id, score=0.70 - index * 0.05, card=card)
            for index, card in enumerate(cards)
        ]

    def sources_by_id(self) -> dict[str, SourceRegistryEntry]:
        return source_registry()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    records = []
    for gate in GATE_QUESTIONS:
        retriever = ScopeRetriever()
        provider = CountingProvider()
        service = ChatService(
            retriever=retriever,
            grounded=GroundedAnswerer(provider=provider),
        )
        response = asyncio.run(service.answer(ChatRequest(message=gate.message)))
        record = {
            "question_id": gate.question_id,
            "message": gate.message,
            "expectation": gate.expectation,
            "status": response.status.value,
            "retrieval_calls": len(retriever.search_calls),
            "provider_calls": provider.calls,
            "citations": len(response.citations),
            "safety_level": response.safety_notice.level.value if response.safety_notice else None,
            "answer": response.answer,
        }
        records.append(record)
        print(
            f"  {gate.question_id}  status={record['status']:<22} "
            f"retrieval={record['retrieval_calls']} provider={record['provider_calls']} "
            f"citations={record['citations']} safety={record['safety_level']}"
        )

    regressions = [record for record in records if record["provider_calls"] != 0]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "gate_control.json"
    out.write_text(
        json.dumps({"records": records, "regressions": regressions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nprovider calls across all gates: {sum(r['provider_calls'] for r in records)}")
    print(f"wrote {out}")
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
