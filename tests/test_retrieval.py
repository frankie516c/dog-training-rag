import hashlib
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import BaseModel
from qdrant_client import QdrantClient

from backend.app.config import Settings
from backend.app.data_validation import DataPaths
from backend.app.domain import (
    ContentLanguage,
    EvidenceCard,
    EvidenceLevel,
    Locator,
    ReuseAction,
    ReuseAssessment,
    ReuseStatus,
    ReviewDecision,
    ReviewStatus,
    SourceClass,
    SourceRef,
    SourceRegistryEntry,
)
from backend.app.embeddings import BGE_M3_DIMENSION, BGE_M3_MODEL_ID, BgeM3EmbeddingProvider
from backend.app.main import CHAT_NOT_READY_MESSAGE, create_app
from backend.app.retrieval import (
    EvidenceRetrieval,
    evidence_embedding_text,
    point_id_for_card,
)
from backend.app.retrieval import (
    main as retrieval_main,
)

CARD_IDS = [
    UUID("10000000-0000-4000-8000-000000000001"),
    UUID("10000000-0000-4000-8000-000000000002"),
    UUID("10000000-0000-4000-8000-000000000003"),
    UUID("10000000-0000-4000-8000-000000000004"),
]


class FakeEmbedder:
    model_id = "fake/deterministic"
    dimension = 3

    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls.append(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [float(value + 1) for value in digest[:3]]
        magnitude = math.sqrt(sum(value * value for value in raw))
        return [value / magnitude for value in raw]


def make_source(
    source_id: str,
    rag_status: ReuseStatus = ReuseStatus.PERMITTED,
) -> SourceRegistryEntry:
    return SourceRegistryEntry(
        source_id=source_id,
        source_class=SourceClass.OFFICIAL_GUIDANCE,
        title=f"Synthetic source {source_id}",
        publisher="Synthetic publisher",
        canonical_url=f"https://example.test/{source_id}",
        content_languages=[ContentLanguage.ENGLISH],
        last_verified_at=date(2026, 8, 12),
        reuse_assessments=[
            ReuseAssessment(
                action=ReuseAction.RAG_USE,
                status=rag_status,
                note="Synthetic rights review.",
            )
        ],
    )


def make_card(card_id: UUID, source_id: str, *, suffix: str = "") -> EvidenceCard:
    return EvidenceCard(
        card_id=card_id,
        claim=f"Synthetic reward-based training claim {suffix}".strip(),
        claim_language=ContentLanguage.ENGLISH,
        topic="synthetic training",
        tags=["welfare", "reward"],
        limitations=["Synthetic fixture only."],
        source_refs=[
            SourceRef(
                source_id=source_id,
                locator=Locator(
                    kind="html",
                    url=f"https://example.test/{source_id}#guidance",
                    section="Synthetic guidance",
                ),
                evidence_level=EvidenceLevel.DIRECT,
            )
        ],
    )


def make_decision(card: EvidenceCard, decision: ReviewStatus) -> ReviewDecision:
    return ReviewDecision.for_card(
        card=card,
        reviewer="human-reviewer@example.test",
        reviewed_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        decision=decision,
        note="Synthetic human review.",
    )


def write_jsonl(path: Path, values: list[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{value.model_dump_json()}\n" for value in values),
        encoding="utf-8",
    )


def write_bundle(
    root: Path,
    *,
    sources: list[SourceRegistryEntry],
    cards: list[EvidenceCard],
    decisions: list[ReviewDecision],
) -> DataPaths:
    paths = DataPaths(
        source_registry=root / "source_registry.jsonl",
        evidence_cards=root / "evidence_cards.jsonl",
        review_decisions=root / "review_decisions.jsonl",
    )
    write_jsonl(paths.source_registry, sources)
    write_jsonl(paths.evidence_cards, cards)
    write_jsonl(paths.review_decisions, decisions)
    return paths


def make_retrieval(
    tmp_path: Path, paths: DataPaths, embedder: FakeEmbedder
) -> tuple[EvidenceRetrieval, QdrantClient]:
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    retrieval = EvidenceRetrieval(
        paths=paths,
        qdrant_path=tmp_path / "unused",
        collection_name="test_evidence",
        embedder=embedder,
        client=client,
    )
    return retrieval, client


def test_embedding_text_uses_fixed_field_and_value_order() -> None:
    card = make_card(CARD_IDS[0], "allowed-source")
    card = card.model_copy(
        update={
            "tags": ["zeta", "Alpha"],
            "limitations": ["Second limitation.", "First limitation."],
        }
    )

    assert evidence_embedding_text(card) == (
        "claim: Synthetic reward-based training claim\n"
        "topic: synthetic training\n"
        "tags: Alpha | zeta\n"
        "limitations: First limitation. | Second limitation."
    )


def test_bge_provider_is_lazy_and_declares_production_contract() -> None:
    provider = BgeM3EmbeddingProvider()

    assert provider.model_id == BGE_M3_MODEL_ID
    assert provider.dimension == BGE_M3_DIMENSION == 1_024
    assert provider.embed_documents([]) == []
    assert provider._model is None


def test_point_uuid_is_deterministic_and_not_the_card_id() -> None:
    first = point_id_for_card(CARD_IDS[0])

    assert first == UUID("c6726b99-c29e-5578-9435-b184c3deb695")
    assert point_id_for_card(CARD_IDS[0]) == first
    assert first != CARD_IDS[0]


def test_rebuild_indexes_only_eligible_cards_with_minimal_payload(tmp_path: Path) -> None:
    allowed = make_source("allowed-source")
    blocked = make_source("blocked-source", ReuseStatus.PROHIBITED)
    eligible = make_card(CARD_IDS[0], allowed.source_id, suffix="eligible")
    pending = make_card(CARD_IDS[1], allowed.source_id, suffix="pending")
    rejected = make_card(CARD_IDS[2], allowed.source_id, suffix="rejected")
    reuse_blocked = make_card(CARD_IDS[3], blocked.source_id, suffix="blocked")
    paths = write_bundle(
        tmp_path / "data",
        sources=[allowed, blocked],
        cards=[eligible, pending, rejected, reuse_blocked],
        decisions=[
            make_decision(eligible, ReviewStatus.APPROVED),
            make_decision(rejected, ReviewStatus.REJECTED),
            make_decision(reuse_blocked, ReviewStatus.APPROVED),
        ],
    )
    embedder = FakeEmbedder()
    retrieval, client = make_retrieval(tmp_path, paths, embedder)
    try:
        result = retrieval.rebuild()
        points, _ = client.scroll(
            collection_name="test_evidence",
            limit=10,
            with_payload=True,
            with_vectors=False,
        )

        assert result.indexed == 1
        assert embedder.document_calls == [[evidence_embedding_text(eligible)]]
        assert len(points) == 1
        assert points[0].id == str(point_id_for_card(eligible.card_id))
        assert points[0].payload == {
            "card_id": str(eligible.card_id),
            "schema_version": eligible.schema_version,
            "content_hash": eligible.content_hash(),
        }
        serialized_payload = json.dumps(points[0].payload)
        assert "claim" not in serialized_payload
        assert "source_refs" not in serialized_payload
        assert "locator" not in serialized_payload
    finally:
        retrieval.close()


def test_rebuild_is_idempotent(tmp_path: Path) -> None:
    source = make_source("allowed-source")
    card = make_card(CARD_IDS[0], source.source_id)
    paths = write_bundle(
        tmp_path / "data",
        sources=[source],
        cards=[card],
        decisions=[make_decision(card, ReviewStatus.APPROVED)],
    )
    retrieval, client = make_retrieval(tmp_path, paths, FakeEmbedder())
    try:
        assert retrieval.rebuild().indexed == 1
        assert retrieval.rebuild().indexed == 1
        assert client.count("test_evidence", exact=True).count == 1
    finally:
        retrieval.close()


def test_search_applies_top_k_and_rejoins_validated_cards(tmp_path: Path) -> None:
    source = make_source("allowed-source")
    cards = [make_card(CARD_IDS[index], source.source_id, suffix=str(index)) for index in range(3)]
    paths = write_bundle(
        tmp_path / "data",
        sources=[source],
        cards=cards,
        decisions=[make_decision(card, ReviewStatus.APPROVED) for card in cards],
    )
    embedder = FakeEmbedder()
    retrieval, _ = make_retrieval(tmp_path, paths, embedder)
    try:
        retrieval.rebuild()
        results = retrieval.search("synthetic query", top_k=2)

        cards_by_id = {card.card_id: card for card in cards}
        assert len(results) == 2
        assert embedder.query_calls == ["synthetic query"]
        assert all(result.card is not None for result in results)
        assert all(result.card == cards_by_id[result.card_id] for result in results)
    finally:
        retrieval.close()


def test_zero_eligible_build_and_empty_search_do_not_embed(tmp_path: Path) -> None:
    paths = write_bundle(tmp_path / "data", sources=[], cards=[], decisions=[])
    embedder = FakeEmbedder()
    retrieval, client = make_retrieval(tmp_path, paths, embedder)
    try:
        assert retrieval.rebuild().indexed == 0
        assert client.count("test_evidence", exact=True).count == 0
        assert retrieval.search("anything") == []
        assert embedder.document_calls == []
        assert embedder.query_calls == []
    finally:
        retrieval.close()


def test_all_missing_data_files_are_an_empty_initial_state(tmp_path: Path) -> None:
    paths = DataPaths(
        source_registry=tmp_path / "missing-sources.jsonl",
        evidence_cards=tmp_path / "missing-cards.jsonl",
        review_decisions=tmp_path / "missing-decisions.jsonl",
    )
    retrieval, _ = make_retrieval(tmp_path, paths, FakeEmbedder())
    try:
        assert retrieval.rebuild().indexed == 0
        assert retrieval.search("anything") == []
    finally:
        retrieval.close()


def test_cli_build_and_search_report_zero_without_approved_data(tmp_path: Path, capsys) -> None:
    paths = write_bundle(tmp_path / "data", sources=[], cards=[], decisions=[])
    common_args = [
        "--source-registry",
        str(paths.source_registry),
        "--evidence-cards",
        str(paths.evidence_cards),
        "--review-decisions",
        str(paths.review_decisions),
        "--qdrant-path",
        str(tmp_path / "cli-qdrant"),
        "--collection",
        "cli_test_evidence",
    ]

    assert retrieval_main(["build", *common_args]) == 0
    assert "indexed=0" in capsys.readouterr().out
    assert retrieval_main(["search", *common_args, "synthetic query"]) == 0
    assert "results=0" in capsys.readouterr().out


def test_chat_endpoint_remains_structured_503() -> None:
    response = TestClient(create_app(Settings())).post("/chat", json={"message": "질문"})

    assert response.status_code == 503
    assert response.json() == {
        "code": "chat_not_ready",
        "message": CHAT_NOT_READY_MESSAGE,
    }
