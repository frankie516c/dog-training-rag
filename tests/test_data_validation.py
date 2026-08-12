import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from backend.app.data_validation import (
    DataPaths,
    DataValidationError,
    load_and_validate,
    main,
)
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

CARD_ID = UUID("dcb40d88-dbd3-45cd-a102-e10bf675ccd1")
MISSING = object()


def make_source(
    source_id: str = "example-guidance",
    *,
    rag_status: ReuseStatus | object = ReuseStatus.PERMITTED,
    conditions: str | None = None,
) -> SourceRegistryEntry:
    assessments = []
    if rag_status is not MISSING:
        assessments.append(
            ReuseAssessment(
                action=ReuseAction.RAG_USE,
                status=rag_status,
                conditions=conditions,
                note="Rights review note.",
            )
        )
    return SourceRegistryEntry(
        source_id=source_id,
        source_class=SourceClass.OFFICIAL_GUIDANCE,
        title=f"Guidance for {source_id}",
        publisher="Example publisher",
        canonical_url=f"https://example.org/{source_id}",
        content_languages=[ContentLanguage.ENGLISH],
        last_verified_at=date(2026, 8, 12),
        reuse_assessments=assessments,
    )


def make_source_ref(
    source_id: str = "example-guidance",
    *,
    evidence_level: EvidenceLevel = EvidenceLevel.DIRECT,
) -> SourceRef:
    return SourceRef(
        source_id=source_id,
        locator=Locator(
            kind="html",
            url=f"https://example.org/{source_id}",
            section="Recommendations",
        ),
        evidence_level=evidence_level,
    )


def make_card(
    card_id: UUID = CARD_ID,
    *,
    source_refs: list[SourceRef] | None = None,
) -> EvidenceCard:
    return EvidenceCard(
        card_id=card_id,
        claim="Reward-based handling can reduce avoidable fear.",
        claim_language=ContentLanguage.ENGLISH,
        topic="fear-aware handling",
        tags=["welfare"],
        source_refs=source_refs or [make_source_ref()],
    )


def make_decision(
    card: EvidenceCard,
    decision: ReviewStatus = ReviewStatus.APPROVED,
) -> ReviewDecision:
    return ReviewDecision.for_card(
        card=card,
        reviewer="human-reviewer@example.org",
        reviewed_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        decision=decision,
        note="Human semantic review completed.",
    )


def write_jsonl(path: Path, values: list[BaseModel | dict], *, blank_line: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        value.model_dump_json() if isinstance(value, BaseModel) else json.dumps(value)
        for value in values
    ]
    if blank_line:
        lines.insert(0, "")
        lines.append("   ")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_bundle(
    tmp_path: Path,
    *,
    sources: list[BaseModel | dict] | None = None,
    cards: list[BaseModel | dict] | None = None,
    decisions: list[BaseModel | dict] | None = None,
    blank_lines: bool = False,
) -> DataPaths:
    paths = DataPaths(
        source_registry=tmp_path / "source_registry.jsonl",
        evidence_cards=tmp_path / "evidence_cards.jsonl",
        review_decisions=tmp_path / "review_decisions.jsonl",
    )
    write_jsonl(paths.source_registry, sources or [], blank_line=blank_lines)
    write_jsonl(paths.evidence_cards, cards or [], blank_line=blank_lines)
    write_jsonl(paths.review_decisions, decisions or [], blank_line=blank_lines)
    return paths


def test_loads_valid_jsonl_and_ignores_blank_lines(tmp_path: Path) -> None:
    source = make_source()
    card = make_card()
    decision = make_decision(card)
    paths = write_bundle(
        tmp_path,
        sources=[source],
        cards=[card],
        decisions=[decision],
        blank_lines=True,
    )

    result = load_and_validate(paths)

    assert result.sources == (source,)
    assert result.cards == (card,)
    assert result.decisions == (decision,)
    assert result.rag_eligible_cards[0].card == card
    assert result.summary.rag_eligible == 1
    assert result.summary.invalid == 0


def test_invalid_json_reports_file_and_line(tmp_path: Path) -> None:
    paths = write_bundle(tmp_path)
    paths.evidence_cards.write_text("\n{not-json}\n", encoding="utf-8")

    with pytest.raises(DataValidationError) as exc_info:
        load_and_validate(paths)

    assert "evidence_cards.jsonl:2" in str(exc_info.value)
    assert "invalid JSON" in str(exc_info.value)


def test_schema_error_reports_file_and_line(tmp_path: Path) -> None:
    paths = write_bundle(tmp_path)
    paths.source_registry.write_text("\n{}\n", encoding="utf-8")

    with pytest.raises(DataValidationError) as exc_info:
        load_and_validate(paths)

    assert "source_registry.jsonl:2" in str(exc_info.value)
    assert "schema validation failed" in str(exc_info.value)


@pytest.mark.parametrize("duplicate_kind", ["source", "card"])
def test_duplicate_ids_are_rejected(tmp_path: Path, duplicate_kind: str) -> None:
    source = make_source()
    card = make_card()
    paths = write_bundle(
        tmp_path,
        sources=[source, source] if duplicate_kind == "source" else [source],
        cards=[card, card] if duplicate_kind == "card" else [card],
    )

    with pytest.raises(DataValidationError, match=f"duplicate {duplicate_kind}_id"):
        load_and_validate(paths)


def test_unknown_source_id_is_rejected(tmp_path: Path) -> None:
    card = make_card(source_refs=[make_source_ref("missing-source")])
    paths = write_bundle(tmp_path, sources=[make_source()], cards=[card])

    with pytest.raises(DataValidationError, match="unknown source_id"):
        load_and_validate(paths)


def test_unknown_decision_card_id_is_rejected(tmp_path: Path) -> None:
    card = make_card()
    decision = make_decision(card).model_copy(update={"card_id": uuid4()})
    paths = write_bundle(tmp_path, sources=[make_source()], cards=[card], decisions=[decision])

    with pytest.raises(DataValidationError, match="unknown card_id"):
        load_and_validate(paths)


def test_card_content_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    card = make_card()
    decision = make_decision(card).model_copy(update={"card_content_hash": f"sha256:{'0' * 64}"})
    paths = write_bundle(tmp_path, sources=[make_source()], cards=[card], decisions=[decision])

    with pytest.raises(DataValidationError, match="card_content_hash does not match"):
        load_and_validate(paths)


def test_hash_version_mismatch_is_rejected_with_location(tmp_path: Path) -> None:
    card = make_card()
    decision_payload = make_decision(card).model_dump(mode="json")
    decision_payload["content_hash_version"] = "evidence-card-content-v2"
    paths = write_bundle(
        tmp_path,
        sources=[make_source()],
        cards=[card],
        decisions=[decision_payload],
    )

    with pytest.raises(DataValidationError) as exc_info:
        load_and_validate(paths)

    assert "review_decisions.jsonl:1" in str(exc_info.value)
    assert "schema validation failed" in str(exc_info.value)


def test_unapproved_card_is_excluded(tmp_path: Path) -> None:
    paths = write_bundle(tmp_path, sources=[make_source()], cards=[make_card()])

    result = load_and_validate(paths)

    assert result.rag_eligible_cards == ()
    assert result.summary.pending_or_unreviewed == 1


def test_approved_card_is_included(tmp_path: Path) -> None:
    card = make_card()
    paths = write_bundle(
        tmp_path,
        sources=[make_source()],
        cards=[card],
        decisions=[make_decision(card)],
    )

    result = load_and_validate(paths)

    assert [item.card for item in result.rag_eligible_cards] == [card]
    assert result.summary.rag_eligible == 1


def test_rejected_card_is_excluded(tmp_path: Path) -> None:
    card = make_card()
    paths = write_bundle(
        tmp_path,
        sources=[make_source()],
        cards=[card],
        decisions=[make_decision(card, ReviewStatus.REJECTED)],
    )

    result = load_and_validate(paths)

    assert result.rag_eligible_cards == ()
    assert result.summary.rejected == 1


def test_conflicting_approval_and_rejection_is_data_error(tmp_path: Path) -> None:
    card = make_card()
    paths = write_bundle(
        tmp_path,
        sources=[make_source()],
        cards=[card],
        decisions=[
            make_decision(card, ReviewStatus.APPROVED),
            make_decision(card, ReviewStatus.REJECTED),
        ],
    )

    with pytest.raises(DataValidationError, match="conflicting approval and rejection"):
        load_and_validate(paths)


@pytest.mark.parametrize(
    "rag_status",
    [ReuseStatus.UNKNOWN, ReuseStatus.PROHIBITED, MISSING],
    ids=["unknown", "prohibited", "missing"],
)
def test_rag_use_unknown_prohibited_or_missing_is_blocked(
    tmp_path: Path, rag_status: ReuseStatus | object
) -> None:
    card = make_card()
    paths = write_bundle(
        tmp_path,
        sources=[make_source(rag_status=rag_status)],
        cards=[card],
        decisions=[make_decision(card)],
    )

    result = load_and_validate(paths)

    assert result.rag_eligible_cards == ()
    assert result.summary.reuse_blocked == 1


def test_every_direct_or_supporting_source_must_allow_rag_use(tmp_path: Path) -> None:
    card = make_card(
        source_refs=[
            make_source_ref("permitted-source", evidence_level=EvidenceLevel.DIRECT),
            make_source_ref("blocked-source", evidence_level=EvidenceLevel.SUPPORTING),
        ]
    )
    paths = write_bundle(
        tmp_path,
        sources=[
            make_source("permitted-source"),
            make_source("blocked-source", rag_status=ReuseStatus.PROHIBITED),
        ],
        cards=[card],
        decisions=[make_decision(card)],
    )

    result = load_and_validate(paths)

    assert result.rag_eligible_cards == ()
    assert result.summary.reuse_blocked == 1


def test_conditional_rag_use_preserves_conditions(tmp_path: Path) -> None:
    card = make_card()
    source = make_source(
        rag_status=ReuseStatus.PERMITTED_WITH_CONDITIONS,
        conditions="Attribute the publisher in downstream output.",
    )
    paths = write_bundle(tmp_path, sources=[source], cards=[card], decisions=[make_decision(card)])

    result = load_and_validate(paths)

    condition = result.rag_eligible_cards[0].rag_use_conditions[0]
    assert condition.source_id == source.source_id
    assert condition.conditions == "Attribute the publisher in downstream output."
    assert condition.note == "Rights review note."


def test_jsonl_round_trip_preserves_models(tmp_path: Path) -> None:
    source = make_source()
    card = make_card()
    decision = make_decision(card)
    paths = write_bundle(tmp_path, sources=[source], cards=[card], decisions=[decision])

    result = load_and_validate(paths)

    assert result.sources[0].model_dump_json() == source.model_dump_json()
    assert result.cards[0].model_dump_json() == card.model_dump_json()
    assert result.decisions[0].model_dump_json() == decision.model_dump_json()


def test_cli_accepts_path_overrides_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    card = make_card()
    paths = write_bundle(
        tmp_path,
        sources=[make_source()],
        cards=[card],
        decisions=[make_decision(card)],
    )

    exit_code = main(
        [
            "--source-registry",
            str(paths.source_registry),
            "--evidence-cards",
            str(paths.evidence_cards),
            "--review-decisions",
            str(paths.review_decisions),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    for expected in (
        "sources=1",
        "cards=1",
        "decisions=1",
        "rag_eligible=1",
        "pending_or_unreviewed=0",
        "rejected=0",
        "reuse_blocked=0",
        "invalid=0",
    ):
        assert expected in output
