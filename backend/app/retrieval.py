from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

from qdrant_client import QdrantClient, models

from backend.app.config import Settings
from backend.app.data_validation import (
    DEFAULT_EVIDENCE_CARDS_PATH,
    DEFAULT_REVIEW_DECISIONS_PATH,
    DEFAULT_SOURCE_REGISTRY_PATH,
    DataLoadResult,
    DataPaths,
    DataValidationError,
    ValidationSummary,
    load_and_validate,
)
from backend.app.domain import EvidenceCard
from backend.app.embeddings import BgeM3EmbeddingProvider, EmbeddingProvider

DEFAULT_TOP_K = 5
POINT_NAMESPACE = UUID("ab50ff46-c340-4d69-a36e-cd3537b30051")


class RetrievalError(RuntimeError):
    """The validated data and local index cannot be safely joined."""


@dataclass(frozen=True)
class BuildResult:
    indexed: int


@dataclass(frozen=True)
class SearchResult:
    card_id: UUID
    score: float
    card: EvidenceCard


def evidence_embedding_text(card: EvidenceCard) -> str:
    """Build deterministic dense input from approved card content fields only."""

    tags = sorted(card.tags, key=lambda value: (value.casefold(), value))
    limitations = sorted(card.limitations, key=lambda value: (value.casefold(), value))
    return "\n".join(
        (
            f"claim: {card.claim}",
            f"topic: {card.topic}",
            f"tags: {' | '.join(tags)}",
            f"limitations: {' | '.join(limitations)}",
        )
    )


def point_id_for_card(card_id: UUID) -> UUID:
    """Derive a stable Qdrant UUID without using the EvidenceCard UUID directly."""

    return uuid5(POINT_NAMESPACE, card_id.hex)


class EvidenceRetrieval:
    def __init__(
        self,
        *,
        paths: DataPaths,
        qdrant_path: Path,
        collection_name: str,
        embedder: EmbeddingProvider,
        client: QdrantClient | None = None,
    ) -> None:
        self.paths = paths
        self.collection_name = collection_name
        self.embedder = embedder
        self._client = client or QdrantClient(path=str(qdrant_path))

    def close(self) -> None:
        self._client.close()

    def rebuild(self) -> BuildResult:
        data = _load_retrieval_data(self.paths)
        eligible_cards = [item.card for item in data.rag_eligible_cards]

        if self._client.collection_exists(self.collection_name):
            self._client.delete_collection(self.collection_name)
        self._client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=self.embedder.dimension,
                distance=models.Distance.COSINE,
            ),
        )

        if not eligible_cards:
            return BuildResult(indexed=0)

        texts = [evidence_embedding_text(card) for card in eligible_cards]
        vectors = self.embedder.embed_documents(texts)
        if len(vectors) != len(eligible_cards):
            raise RetrievalError("embedder returned a different number of vectors than cards")
        for vector in vectors:
            if len(vector) != self.embedder.dimension:
                raise RetrievalError("embedder returned a vector with an unexpected dimension")

        points = [
            models.PointStruct(
                id=str(point_id_for_card(card.card_id)),
                vector=vector,
                payload={
                    "card_id": str(card.card_id),
                    "schema_version": card.schema_version,
                    "content_hash": card.content_hash(),
                },
            )
            for card, vector in zip(eligible_cards, vectors, strict=True)
        ]
        self._client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )
        return BuildResult(indexed=len(points))

    def search(self, query: str, *, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        data = _load_retrieval_data(self.paths)
        eligible_by_id = {item.card.card_id: item.card for item in data.rag_eligible_cards}
        if not eligible_by_id or not self._client.collection_exists(self.collection_name):
            return []

        query_vector = self.embedder.embed_query(query)
        if len(query_vector) != self.embedder.dimension:
            raise RetrievalError("embedder returned a query vector with an unexpected dimension")
        response = self._client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        results: list[SearchResult] = []
        for point in response.points:
            payload = point.payload or {}
            try:
                card_id = UUID(str(payload["card_id"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise RetrievalError("Qdrant point has an invalid card_id payload") from exc
            card = eligible_by_id.get(card_id)
            if card is None:
                raise RetrievalError(f"Qdrant point references ineligible card {card_id}")
            if payload.get("schema_version") != card.schema_version:
                raise RetrievalError(f"Qdrant point schema_version is stale for card {card_id}")
            if payload.get("content_hash") != card.content_hash():
                raise RetrievalError(f"Qdrant point content_hash is stale for card {card_id}")
            results.append(SearchResult(card_id=card_id, score=point.score, card=card))
        return results


def _load_retrieval_data(paths: DataPaths) -> DataLoadResult:
    configured_paths = (paths.source_registry, paths.evidence_cards, paths.review_decisions)
    if all(not path.exists() for path in configured_paths):
        return DataLoadResult(
            sources=(),
            cards=(),
            decisions=(),
            rag_eligible_cards=(),
            summary=ValidationSummary(
                sources=0,
                cards=0,
                decisions=0,
                rag_eligible=0,
                pending_or_unreviewed=0,
                rejected=0,
                reuse_blocked=0,
            ),
        )
    return load_and_validate(paths)


def _add_common_arguments(parser: argparse.ArgumentParser, settings: Settings) -> None:
    parser.add_argument("--source-registry", type=Path, default=DEFAULT_SOURCE_REGISTRY_PATH)
    parser.add_argument("--evidence-cards", type=Path, default=DEFAULT_EVIDENCE_CARDS_PATH)
    parser.add_argument("--review-decisions", type=Path, default=DEFAULT_REVIEW_DECISIONS_PATH)
    parser.add_argument("--qdrant-path", type=Path, default=settings.qdrant_path)
    parser.add_argument("--collection", default=settings.qdrant_collection)
    parser.add_argument("--model", default=settings.embedding_model_id)
    parser.add_argument("--device", default=settings.embedding_device)


def _build_parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query the local evidence index.")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Rebuild the complete eligible-card index.")
    _add_common_arguments(build, settings)
    search = commands.add_parser("search", help="Search eligible evidence cards.")
    _add_common_arguments(search, settings)
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    args = _build_parser(settings).parse_args(argv)
    paths = DataPaths(
        source_registry=args.source_registry,
        evidence_cards=args.evidence_cards,
        review_decisions=args.review_decisions,
    )
    retrieval = EvidenceRetrieval(
        paths=paths,
        qdrant_path=args.qdrant_path,
        collection_name=args.collection,
        embedder=BgeM3EmbeddingProvider(model_id=args.model, device=args.device),
    )
    try:
        if args.command == "build":
            result = retrieval.rebuild()
            print(f"indexed={result.indexed}")
        else:
            results = retrieval.search(args.query, top_k=args.top_k)
            print(f"results={len(results)}")
            for result in results:
                print(
                    json.dumps(
                        {
                            "card_id": str(result.card_id),
                            "score": result.score,
                            "card": result.card.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                    )
                )
    except (DataValidationError, RetrievalError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        retrieval.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
