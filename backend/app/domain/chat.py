from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

from backend.app.domain.evidence import (
    ContentLanguage,
    EvidenceLevel,
    Locator,
    NonEmptyText,
    SourceId,
)


class ChatContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]


class ChatStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SafetyLevel(StrEnum):
    CAUTION = "caution"
    URGENT = "urgent"


class ChatRequest(ChatContractModel):
    message: MessageText
    response_language: ContentLanguage = ContentLanguage.KOREAN


class ChatCitation(ChatContractModel):
    card_id: UUID
    source_id: SourceId
    source_name: NonEmptyText
    canonical_url: HttpUrl
    locator: Locator
    evidence_level: Literal[EvidenceLevel.DIRECT, EvidenceLevel.SUPPORTING]


class SafetyNotice(ChatContractModel):
    level: SafetyLevel
    message: NonEmptyText


class ChatResponse(ChatContractModel):
    request_id: UUID
    status: ChatStatus
    answer: NonEmptyText
    answer_language: ContentLanguage
    citations: list[ChatCitation]
    limitations: list[NonEmptyText] = Field(default_factory=list)
    safety_notice: SafetyNotice | None = None

    @model_validator(mode="after")
    def validate_status_and_citations(self) -> Self:
        if self.status is ChatStatus.ANSWERED and not self.citations:
            raise ValueError("answered responses require at least one citation")
        if self.status is ChatStatus.INSUFFICIENT_EVIDENCE and self.citations:
            raise ValueError("insufficient_evidence responses cannot include citations")

        citation_keys = [(citation.card_id, citation.source_id) for citation in self.citations]
        if len(citation_keys) != len(set(citation_keys)):
            raise ValueError("duplicate card_id and source_id citation")
        return self


class ChatErrorResponse(ChatContractModel):
    code: Literal["chat_not_ready"]
    message: NonEmptyText
