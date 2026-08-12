from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ValidationError

from backend.app.domain import (
    EvidenceCard,
    EvidenceLevel,
    ReuseAction,
    ReuseStatus,
    ReviewDecision,
    ReviewStatus,
    SourceRegistryEntry,
)
from backend.app.domain.evidence import CANONICAL_HASH_VERSION

DEFAULT_SOURCE_REGISTRY_PATH = Path("data/sources/source_registry.jsonl")
DEFAULT_EVIDENCE_CARDS_PATH = Path("data/processed/evidence_cards.jsonl")
DEFAULT_REVIEW_DECISIONS_PATH = Path("data/reviews/review_decisions.jsonl")


class DataValidationError(ValueError):
    """Invalid JSONL data with optional source location."""

    def __init__(self, message: str, *, path: Path | None = None, line: int | None = None):
        self.path = path
        self.line = line
        location = str(path) if path is not None else "data"
        if line is not None:
            location = f"{location}:{line}"
        super().__init__(f"{location}: {message}")


@dataclass(frozen=True)
class DataPaths:
    source_registry: Path = DEFAULT_SOURCE_REGISTRY_PATH
    evidence_cards: Path = DEFAULT_EVIDENCE_CARDS_PATH
    review_decisions: Path = DEFAULT_REVIEW_DECISIONS_PATH


@dataclass(frozen=True)
class RagUseCondition:
    source_id: str
    conditions: str
    note: str | None


@dataclass(frozen=True)
class RagEligibleCard:
    card: EvidenceCard
    rag_use_conditions: tuple[RagUseCondition, ...]


@dataclass(frozen=True)
class ValidationSummary:
    sources: int
    cards: int
    decisions: int
    rag_eligible: int
    pending_or_unreviewed: int
    rejected: int
    reuse_blocked: int
    invalid: int = 0


@dataclass(frozen=True)
class DataLoadResult:
    sources: tuple[SourceRegistryEntry, ...]
    cards: tuple[EvidenceCard, ...]
    decisions: tuple[ReviewDecision, ...]
    rag_eligible_cards: tuple[RagEligibleCard, ...]
    summary: ValidationSummary


@dataclass(frozen=True)
class _LocatedRecord:
    value: BaseModel
    path: Path
    line: int


def load_and_validate(paths: DataPaths = DataPaths()) -> DataLoadResult:
    source_records = _load_jsonl(paths.source_registry, SourceRegistryEntry)
    card_records = _load_jsonl(paths.evidence_cards, EvidenceCard)
    decision_records = _load_jsonl(paths.review_decisions, ReviewDecision)

    sources_by_id = _index_unique(source_records, "source_id")
    cards_by_id = _index_unique(card_records, "card_id")

    for record in card_records:
        card = _as_card(record)
        for source_ref in card.source_refs:
            if source_ref.source_id not in sources_by_id:
                raise DataValidationError(
                    f"card {card.card_id} references unknown source_id {source_ref.source_id!r}",
                    path=record.path,
                    line=record.line,
                )

    decisions_by_card: dict[UUID, list[_LocatedRecord]] = defaultdict(list)
    for record in decision_records:
        decision = _as_decision(record)
        card_record = cards_by_id.get(decision.card_id)
        if card_record is None:
            raise DataValidationError(
                f"decision references unknown card_id {decision.card_id}",
                path=record.path,
                line=record.line,
            )
        card = _as_card(card_record)
        if decision.content_hash_version != CANONICAL_HASH_VERSION:
            raise DataValidationError(
                f"unsupported content hash version {decision.content_hash_version!r}",
                path=record.path,
                line=record.line,
            )
        expected_hash = card.content_hash()
        if decision.card_content_hash != expected_hash:
            raise DataValidationError(
                f"card_content_hash does not match current card {card.card_id}",
                path=record.path,
                line=record.line,
            )
        decisions_by_card[decision.card_id].append(record)

    eligible: list[RagEligibleCard] = []
    exclusions: Counter[str] = Counter()
    for card_record in card_records:
        card = _as_card(card_record)
        current_decisions = decisions_by_card.get(card.card_id, [])
        decision_values = {_as_decision(record).decision for record in current_decisions}
        if ReviewStatus.APPROVED in decision_values and ReviewStatus.REJECTED in decision_values:
            conflict = current_decisions[-1]
            raise DataValidationError(
                f"card {card.card_id} has conflicting approval and rejection decisions",
                path=conflict.path,
                line=conflict.line,
            )
        if ReviewStatus.REJECTED in decision_values:
            exclusions["rejected"] += 1
            continue
        if ReviewStatus.APPROVED not in decision_values:
            exclusions["pending_or_unreviewed"] += 1
            continue

        conditions = _rag_use_conditions(card, sources_by_id)
        if conditions is None:
            exclusions["reuse_blocked"] += 1
            continue
        eligible.append(RagEligibleCard(card=card, rag_use_conditions=conditions))

    summary = ValidationSummary(
        sources=len(source_records),
        cards=len(card_records),
        decisions=len(decision_records),
        rag_eligible=len(eligible),
        pending_or_unreviewed=exclusions["pending_or_unreviewed"],
        rejected=exclusions["rejected"],
        reuse_blocked=exclusions["reuse_blocked"],
    )
    return DataLoadResult(
        sources=tuple(_as_source(record) for record in source_records),
        cards=tuple(_as_card(record) for record in card_records),
        decisions=tuple(_as_decision(record) for record in decision_records),
        rag_eligible_cards=tuple(eligible),
        summary=summary,
    )


def _load_jsonl[ModelT: BaseModel](path: Path, model_type: type[ModelT]) -> list[_LocatedRecord]:
    records: list[_LocatedRecord] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if not raw_line.strip():
                    continue
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise DataValidationError(
                        f"invalid JSON: {exc.msg}", path=path, line=line_number
                    ) from exc
                try:
                    value = model_type.model_validate(payload)
                except ValidationError as exc:
                    raise DataValidationError(
                        f"schema validation failed: {exc}", path=path, line=line_number
                    ) from exc
                records.append(_LocatedRecord(value=value, path=path, line=line_number))
    except DataValidationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise DataValidationError(str(exc), path=path) from exc
    return records


def _index_unique(
    records: list[_LocatedRecord], attribute: str
) -> dict[str | UUID, _LocatedRecord]:
    indexed: dict[str | UUID, _LocatedRecord] = {}
    for record in records:
        identifier = getattr(record.value, attribute)
        if identifier in indexed:
            raise DataValidationError(
                f"duplicate {attribute} {identifier!s}", path=record.path, line=record.line
            )
        indexed[identifier] = record
    return indexed


def _rag_use_conditions(
    card: EvidenceCard, sources_by_id: dict[str | UUID, _LocatedRecord]
) -> tuple[RagUseCondition, ...] | None:
    relevant_source_ids = sorted(
        {
            source_ref.source_id
            for source_ref in card.source_refs
            if source_ref.evidence_level in {EvidenceLevel.DIRECT, EvidenceLevel.SUPPORTING}
        }
    )
    conditions: list[RagUseCondition] = []
    for source_id in relevant_source_ids:
        source = _as_source(sources_by_id[source_id])
        assessment = next(
            (
                candidate
                for candidate in source.reuse_assessments
                if candidate.action is ReuseAction.RAG_USE
            ),
            None,
        )
        if assessment is None or assessment.status in {
            ReuseStatus.PROHIBITED,
            ReuseStatus.UNKNOWN,
        }:
            return None
        if assessment.status is ReuseStatus.PERMITTED_WITH_CONDITIONS:
            if assessment.conditions is None:  # defensive; the domain model already rejects this
                return None
            conditions.append(
                RagUseCondition(
                    source_id=source_id,
                    conditions=assessment.conditions,
                    note=assessment.note,
                )
            )
    return tuple(conditions)


def _as_source(record: _LocatedRecord) -> SourceRegistryEntry:
    if not isinstance(record.value, SourceRegistryEntry):
        raise TypeError("expected SourceRegistryEntry")
    return record.value


def _as_card(record: _LocatedRecord) -> EvidenceCard:
    if not isinstance(record.value, EvidenceCard):
        raise TypeError("expected EvidenceCard")
    return record.value


def _as_decision(record: _LocatedRecord) -> ReviewDecision:
    if not isinstance(record.value, ReviewDecision):
        raise TypeError("expected ReviewDecision")
    return record.value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate EvidenceCard JSONL data for RAG use.")
    parser.add_argument("--source-registry", type=Path, default=DEFAULT_SOURCE_REGISTRY_PATH)
    parser.add_argument("--evidence-cards", type=Path, default=DEFAULT_EVIDENCE_CARDS_PATH)
    parser.add_argument("--review-decisions", type=Path, default=DEFAULT_REVIEW_DECISIONS_PATH)
    return parser


def _print_summary(summary: ValidationSummary) -> None:
    for field in (
        "sources",
        "cards",
        "decisions",
        "rag_eligible",
        "pending_or_unreviewed",
        "rejected",
        "reuse_blocked",
        "invalid",
    ):
        print(f"{field}={getattr(summary, field)}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = DataPaths(
        source_registry=args.source_registry,
        evidence_cards=args.evidence_cards,
        review_decisions=args.review_decisions,
    )
    try:
        result = load_and_validate(paths)
    except DataValidationError as exc:
        print(str(exc), file=sys.stderr)
        _print_summary(
            ValidationSummary(
                sources=0,
                cards=0,
                decisions=0,
                rag_eligible=0,
                pending_or_unreviewed=0,
                rejected=0,
                reuse_blocked=0,
                invalid=1,
            )
        )
        return 1
    _print_summary(result.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
