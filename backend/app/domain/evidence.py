import hashlib
import json
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.0"
CANONICAL_HASH_VERSION = "evidence-card-content-v1"

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SourceId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=120,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
PmcId = Annotated[str, StringConstraints(pattern=r"^PMC[1-9][0-9]*$")]
Doi = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^10\.[0-9]{4,9}/\S+$")]
ContentHash = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceClass(StrEnum):
    OFFICIAL_GUIDANCE = "official_guidance"
    POSITION_STATEMENT = "position_statement"
    PEER_REVIEWED_PRIMARY = "peer_reviewed_primary"
    PEER_REVIEWED_REVIEW = "peer_reviewed_review"
    DATASET_DEFINITION = "dataset_definition"


class ContentLanguage(StrEnum):
    KOREAN = "ko"
    ENGLISH = "en"


class EvidenceLevel(StrEnum):
    """How directly a source reference supports one card's claim."""

    DIRECT = "DIRECT"
    SUPPORTING = "SUPPORTING"
    CONTEXT_ONLY = "CONTEXT_ONLY"


class ReviewStatus(StrEnum):
    PENDING_SEMANTIC_REVIEW = "PENDING_SEMANTIC_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReuseAction(StrEnum):
    ACCESS = "access"
    AUTOMATED_COLLECTION = "automated_collection"
    LOCAL_STORAGE = "local_storage"
    TRANSFORMATION = "transformation"
    RAG_USE = "rag_use"
    QUOTATION = "quotation"
    REDISTRIBUTION = "redistribution"
    COMMERCIAL_USE = "commercial_use"


class ReuseStatus(StrEnum):
    PERMITTED = "permitted"
    PERMITTED_WITH_CONDITIONS = "permitted_with_conditions"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


class LocatorKind(StrEnum):
    HTML = "html"
    PDF = "pdf"
    PMC_ARTICLE = "pmc_article"
    DATASET_DEFINITION = "dataset_definition"


class ReuseAssessment(ContractModel):
    """A rights assessment for exactly one reuse action."""

    action: ReuseAction
    status: ReuseStatus
    conditions: NonEmptyText | None = None
    note: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        if self.status is ReuseStatus.PERMITTED_WITH_CONDITIONS:
            if self.conditions is None:
                raise ValueError("permitted_with_conditions requires conditions")
        elif self.conditions is not None:
            raise ValueError("conditions are only valid for permitted_with_conditions")
        return self


class SourceRegistryEntry(ContractModel):
    """Stable source identity and rights review, independent from evidence claims."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    source_id: SourceId
    source_class: SourceClass
    title: NonEmptyText
    publisher: NonEmptyText
    canonical_url: HttpUrl
    content_languages: Annotated[list[ContentLanguage], Field(min_length=1)]
    last_verified_at: date
    license_name: NonEmptyText | None = None
    license_url: HttpUrl | None = None
    reuse_assessments: list[ReuseAssessment] = Field(default_factory=list)

    @field_validator("content_languages")
    @classmethod
    def reject_duplicate_languages(cls, languages: list[ContentLanguage]) -> list[ContentLanguage]:
        if len(languages) != len(set(languages)):
            raise ValueError("content_languages must not contain duplicates")
        return languages

    @field_validator("reuse_assessments")
    @classmethod
    def reject_duplicate_reuse_actions(
        cls, assessments: list[ReuseAssessment]
    ) -> list[ReuseAssessment]:
        actions = [assessment.action for assessment in assessments]
        if len(actions) != len(set(actions)):
            raise ValueError("reuse_assessments must not repeat an action")
        return assessments


class Locator(ContractModel):
    """A typed, source-native location that a reviewer can revisit."""

    kind: LocatorKind
    url: HttpUrl
    section: NonEmptyText | None = None
    fragment: NonEmptyText | None = None
    page: Annotated[int, Field(ge=1)] | None = None
    pmcid: PmcId | None = None
    doi: Doi | None = None
    dataset_id: NonEmptyText | None = None
    item_id: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_kind_specific_parts(self) -> Self:
        populated = {
            name
            for name in ("section", "fragment", "page", "pmcid", "doi", "dataset_id", "item_id")
            if getattr(self, name) is not None
        }

        if self.kind is LocatorKind.HTML:
            if not ({"section", "fragment"} & populated):
                raise ValueError("HTML locator requires section or fragment")
            forbidden = populated & {"page", "pmcid", "doi", "dataset_id", "item_id"}
        elif self.kind is LocatorKind.PDF:
            if "page" not in populated:
                raise ValueError("PDF locator requires page")
            forbidden = populated & {"pmcid", "doi", "dataset_id", "item_id"}
        elif self.kind is LocatorKind.PMC_ARTICLE:
            missing = {"pmcid", "section"} - populated
            if missing:
                raise ValueError("PMC article locator requires pmcid and section")
            forbidden = populated & {"page", "dataset_id", "item_id"}
        else:
            if "dataset_id" not in populated or not ({"section", "item_id"} & populated):
                raise ValueError(
                    "dataset definition locator requires dataset_id and section or item_id"
                )
            forbidden = populated & {"page", "pmcid"}

        if forbidden:
            fields = ", ".join(sorted(forbidden))
            raise ValueError(f"{self.kind.value} locator does not accept: {fields}")
        return self


class SourceRef(ContractModel):
    """A card-specific link to a registered source and exact supporting location."""

    source_id: SourceId
    locator: Locator
    evidence_level: EvidenceLevel
    support_note: NonEmptyText | None = None


class EvidenceCard(ContractModel):
    """A concise claim with one topic and one or more traceable source references."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    card_id: UUID
    claim: NonEmptyText
    claim_language: ContentLanguage
    topic: NonEmptyText
    tags: list[NonEmptyText] = Field(default_factory=list)
    source_refs: Annotated[list[SourceRef], Field(min_length=1)]
    limitations: list[NonEmptyText] = Field(default_factory=list)
    review_status: Literal[ReviewStatus.PENDING_SEMANTIC_REVIEW] = (
        ReviewStatus.PENDING_SEMANTIC_REVIEW
    )

    @field_validator("tags")
    @classmethod
    def remove_duplicate_tags(cls, tags: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            key = tag.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(tag)
        return unique

    @model_validator(mode="after")
    def require_claim_support(self) -> Self:
        if not any(
            source_ref.evidence_level in {EvidenceLevel.DIRECT, EvidenceLevel.SUPPORTING}
            for source_ref in self.source_refs
        ):
            raise ValueError("at least one DIRECT or SUPPORTING source reference is required")
        return self

    def canonical_content_bytes(self) -> bytes:
        """Serialize approval-target content using the versioned canonical rule."""

        source_refs = [source_ref.model_dump(mode="json") for source_ref in self.source_refs]
        source_refs.sort(key=_canonical_json_bytes)

        payload = {
            "canonical_hash_version": CANONICAL_HASH_VERSION,
            "schema_version": self.schema_version,
            "claim": self.claim,
            "claim_language": self.claim_language.value,
            "topic": self.topic,
            "tags": sorted(self.tags, key=lambda tag: (tag.casefold(), tag)),
            "source_refs": source_refs,
            "limitations": sorted(
                self.limitations,
                key=lambda limitation: (limitation.casefold(), limitation),
            ),
        }
        return _canonical_json_bytes(payload)

    def content_hash(self) -> str:
        digest = hashlib.sha256(self.canonical_content_bytes()).hexdigest()
        return f"sha256:{digest}"


class ReviewDecision(ContractModel):
    """An immutable review result bound to the exact content of one card."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    card_id: UUID
    reviewer: NonEmptyText
    reviewed_at: AwareDatetime
    content_hash_version: Literal["evidence-card-content-v1"]
    card_content_hash: ContentHash
    decision: Literal[ReviewStatus.APPROVED, ReviewStatus.REJECTED]
    note: NonEmptyText

    @classmethod
    def for_card(
        cls,
        *,
        card: EvidenceCard,
        reviewer: str,
        reviewed_at: AwareDatetime,
        decision: Literal[ReviewStatus.APPROVED, ReviewStatus.REJECTED],
        note: str,
    ) -> Self:
        """Build a decision bound to a card's official canonical content hash."""

        return cls(
            card_id=card.card_id,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            content_hash_version=CANONICAL_HASH_VERSION,
            card_content_hash=card.content_hash(),
            decision=decision,
            note=note,
        )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
