from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.domain import LocatorKind as PublicLocatorKind
from backend.app.domain.evidence import (
    CANONICAL_HASH_VERSION,
    ContentLanguage,
    EvidenceCard,
    EvidenceLevel,
    Locator,
    LocatorKind,
    ReuseAction,
    ReuseAssessment,
    ReuseStatus,
    ReviewDecision,
    ReviewStatus,
    SourceClass,
    SourceRef,
    SourceRegistryEntry,
)

CARD_ID = UUID("f17cfc7f-dc26-4a27-bb6c-44bff060aa16")
CONTENT_HASH = f"sha256:{'a' * 64}"


def make_locator(**overrides) -> Locator:
    values = {
        "kind": "html",
        "url": "https://example.org/guidance",
        "section": "Safe handling",
    }
    values.update(overrides)
    return Locator(**values)


def make_source_ref(**overrides) -> SourceRef:
    values = {
        "source_id": "example-guidance",
        "locator": make_locator(),
        "evidence_level": EvidenceLevel.DIRECT,
    }
    values.update(overrides)
    return SourceRef(**values)


def make_card(**overrides) -> EvidenceCard:
    values = {
        "card_id": CARD_ID,
        "claim": "Reward-based handling can reduce avoidable fear during routine care.",
        "claim_language": "en",
        "topic": "fear-aware handling",
        "source_refs": [make_source_ref()],
    }
    values.update(overrides)
    return EvidenceCard(**values)


@pytest.mark.parametrize(
    "locator",
    [
        {
            "kind": "html",
            "url": "https://example.org/guidance#handling",
            "fragment": "handling",
        },
        {
            "kind": "pdf",
            "url": "https://example.org/guidance.pdf",
            "page": 4,
            "section": "Recommendations",
        },
        {
            "kind": "pmc_article",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7387681/",
            "pmcid": "PMC7387681",
            "doi": "10.3389/fvets.2020.00508",
            "section": "Results",
        },
        {
            "kind": "dataset_definition",
            "url": "https://example.org/datasets/cbarq",
            "dataset_id": "cbarq-survey-2017",
            "item_id": "trainability",
            "doi": "10.24097/wolfram.41397.data",
        },
    ],
)
def test_each_locator_kind_can_be_created(locator) -> None:
    assert Locator(**locator).url.host is not None


def test_locator_kind_is_available_from_domain_package() -> None:
    assert PublicLocatorKind is LocatorKind


@pytest.mark.parametrize(
    "locator",
    [
        {"kind": "html", "url": "https://example.org/guidance"},
        {"kind": "pdf", "url": "https://example.org/guidance.pdf"},
        {
            "kind": "pmc_article",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7387681/",
            "section": "Results",
        },
        {
            "kind": "dataset_definition",
            "url": "https://example.org/datasets/cbarq",
            "dataset_id": "cbarq-survey-2017",
        },
    ],
)
def test_locator_rejects_missing_kind_specific_parts(locator) -> None:
    with pytest.raises(ValidationError):
        Locator(**locator)


@pytest.mark.parametrize("url", ["not-a-url", "ftp://example.org/file"])
def test_registry_rejects_invalid_url(url: str) -> None:
    with pytest.raises(ValidationError):
        SourceRegistryEntry(
            source_id="example-guidance",
            source_class=SourceClass.OFFICIAL_GUIDANCE,
            title="Example guidance",
            publisher="Example publisher",
            canonical_url=url,
            content_languages=[ContentLanguage.ENGLISH],
            last_verified_at=date(2026, 8, 12),
        )


def test_registry_keeps_reuse_assessments_separate_from_evidence_level() -> None:
    entry = SourceRegistryEntry(
        source_id="example-guidance",
        source_class=SourceClass.OFFICIAL_GUIDANCE,
        title="Example guidance",
        publisher="Example publisher",
        canonical_url="https://example.org/guidance",
        content_languages=[ContentLanguage.ENGLISH],
        last_verified_at=date(2026, 8, 12),
        reuse_assessments=[
            ReuseAssessment(
                action=ReuseAction.QUOTATION,
                status=ReuseStatus.PERMITTED_WITH_CONDITIONS,
                conditions="Attribute the publisher and link to the source.",
            )
        ],
    )

    assert entry.reuse_assessments[0].action is ReuseAction.QUOTATION
    assert "evidence_level" not in SourceRegistryEntry.model_fields


def test_registry_rejects_duplicate_reuse_action() -> None:
    duplicate_action = [
        ReuseAssessment(action=ReuseAction.ACCESS, status=ReuseStatus.PERMITTED),
        ReuseAssessment(action=ReuseAction.ACCESS, status=ReuseStatus.UNKNOWN),
    ]

    with pytest.raises(ValidationError):
        SourceRegistryEntry(
            source_id="example-guidance",
            source_class=SourceClass.OFFICIAL_GUIDANCE,
            title="Example guidance",
            publisher="Example publisher",
            canonical_url="https://example.org/guidance",
            content_languages=[ContentLanguage.ENGLISH],
            last_verified_at=date(2026, 8, 12),
            reuse_assessments=duplicate_action,
        )


def test_conditional_reuse_requires_non_empty_conditions() -> None:
    with pytest.raises(ValidationError):
        ReuseAssessment(
            action=ReuseAction.RAG_USE,
            status=ReuseStatus.PERMITTED_WITH_CONDITIONS,
        )

    with pytest.raises(ValidationError):
        ReuseAssessment(
            action=ReuseAction.RAG_USE,
            status=ReuseStatus.PERMITTED_WITH_CONDITIONS,
            conditions="   ",
        )


@pytest.mark.parametrize("content_languages", [[], ["en", "en"], ["fr"]])
def test_registry_rejects_invalid_content_languages(content_languages) -> None:
    with pytest.raises(ValidationError):
        SourceRegistryEntry(
            source_id="example-guidance",
            source_class=SourceClass.OFFICIAL_GUIDANCE,
            title="Example guidance",
            publisher="Example publisher",
            canonical_url="https://example.org/guidance",
            content_languages=content_languages,
            last_verified_at=date(2026, 8, 12),
        )


def test_korean_claim_can_reference_english_and_korean_sources() -> None:
    english_source = SourceRegistryEntry(
        source_id="english-guidance",
        source_class=SourceClass.POSITION_STATEMENT,
        title="English guidance",
        publisher="Example publisher",
        canonical_url="https://example.org/en",
        content_languages=[ContentLanguage.ENGLISH],
        last_verified_at=date(2026, 8, 12),
    )
    korean_source = SourceRegistryEntry(
        source_id="korean-guidance",
        source_class=SourceClass.OFFICIAL_GUIDANCE,
        title="한국어 지침",
        publisher="예시 발행자",
        canonical_url="https://example.org/ko",
        content_languages=[ContentLanguage.KOREAN],
        last_verified_at=date(2026, 8, 12),
    )
    card = make_card(
        claim="안전하고 긍정적인 훈련 원칙을 적용한다.",
        claim_language=ContentLanguage.KOREAN,
        source_refs=[
            make_source_ref(source_id=english_source.source_id),
            make_source_ref(
                source_id=korean_source.source_id,
                locator=make_locator(url="https://example.org/ko"),
                evidence_level=EvidenceLevel.SUPPORTING,
            ),
        ],
    )

    assert card.claim_language is ContentLanguage.KOREAN
    assert {source_ref.source_id for source_ref in card.source_refs} == {
        "english-guidance",
        "korean-guidance",
    }


@pytest.mark.parametrize("claim_language", ["", "fr"])
def test_card_rejects_unsupported_claim_language(claim_language: str) -> None:
    with pytest.raises(ValidationError):
        make_card(claim_language=claim_language)


def test_locator_rejects_invalid_url() -> None:
    with pytest.raises(ValidationError):
        make_locator(url="not-a-url")


@pytest.mark.parametrize("source_id", ["", "UPPER_CASE", "has spaces", "-leading"])
def test_source_reference_rejects_invalid_source_id(source_id: str) -> None:
    with pytest.raises(ValidationError):
        make_source_ref(source_id=source_id)


def test_new_card_is_pending_semantic_review() -> None:
    card = make_card()

    assert card.review_status is ReviewStatus.PENDING_SEMANTIC_REVIEW
    with pytest.raises(ValidationError):
        make_card(review_status=ReviewStatus.APPROVED)


def test_duplicate_tags_are_removed_case_insensitively_in_input_order() -> None:
    card = make_card(tags=["welfare", "Training", "welfare", "training"])

    assert card.tags == ["welfare", "Training"]


def test_card_rejects_context_only_sources() -> None:
    with pytest.raises(ValidationError):
        make_card(source_refs=[make_source_ref(evidence_level=EvidenceLevel.CONTEXT_ONLY)])


def test_card_accepts_direct_with_context_source() -> None:
    card = make_card(
        source_refs=[
            make_source_ref(evidence_level=EvidenceLevel.DIRECT),
            make_source_ref(
                source_id="context-source",
                evidence_level=EvidenceLevel.CONTEXT_ONLY,
            ),
        ]
    )

    assert len(card.source_refs) == 2


def test_card_accepts_supporting_only_source() -> None:
    card = make_card(source_refs=[make_source_ref(evidence_level=EvidenceLevel.SUPPORTING)])

    assert card.source_refs[0].evidence_level is EvidenceLevel.SUPPORTING


@pytest.mark.parametrize(
    "missing_field",
    [
        "reviewer",
        "reviewed_at",
        "content_hash_version",
        "card_content_hash",
        "decision",
        "note",
    ],
)
def test_review_decision_requires_review_metadata(missing_field: str) -> None:
    values = {
        "card_id": CARD_ID,
        "reviewer": "reviewer@example.org",
        "reviewed_at": datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        "content_hash_version": CANONICAL_HASH_VERSION,
        "card_content_hash": CONTENT_HASH,
        "decision": ReviewStatus.APPROVED,
        "note": "Claim and limitations match the cited source.",
    }
    del values[missing_field]

    with pytest.raises(ValidationError):
        ReviewDecision(**values)


@pytest.mark.parametrize("decision", [ReviewStatus.APPROVED, ReviewStatus.REJECTED])
def test_review_decision_json_round_trip(decision: ReviewStatus) -> None:
    review = ReviewDecision(
        card_id=CARD_ID,
        reviewer="reviewer@example.org",
        reviewed_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        content_hash_version=CANONICAL_HASH_VERSION,
        card_content_hash=CONTENT_HASH,
        decision=decision,
        note="Human semantic review completed.",
    )

    assert ReviewDecision.model_validate_json(review.model_dump_json()) == review


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reviewed_at", datetime(2026, 8, 12, 15, 0)),
        ("card_content_hash", "sha256:not-a-valid-hash"),
        ("note", "   "),
    ],
)
def test_review_decision_rejects_invalid_metadata(field: str, value) -> None:
    values = {
        "card_id": CARD_ID,
        "reviewer": "reviewer@example.org",
        "reviewed_at": datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        "content_hash_version": CANONICAL_HASH_VERSION,
        "card_content_hash": CONTENT_HASH,
        "decision": ReviewStatus.APPROVED,
        "note": "Human semantic review completed.",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        ReviewDecision(**values)


def test_review_decision_factory_uses_official_card_hash() -> None:
    card = make_card()

    review = ReviewDecision.for_card(
        card=card,
        reviewer="reviewer@example.org",
        reviewed_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        decision=ReviewStatus.APPROVED,
        note="Human semantic review completed.",
    )

    assert review.content_hash_version == CANONICAL_HASH_VERSION
    assert review.card_content_hash == card.content_hash()


def test_content_hash_ignores_unordered_input_order() -> None:
    direct = make_source_ref(source_id="direct-source", evidence_level=EvidenceLevel.DIRECT)
    context = make_source_ref(
        source_id="context-source",
        locator=make_locator(fragment="context", section=None),
        evidence_level=EvidenceLevel.CONTEXT_ONLY,
    )
    first = make_card(
        tags=["welfare", "training"],
        source_refs=[direct, context],
        limitations=["Not a diagnosis.", "Not an individual treatment plan."],
    )
    reordered = make_card(
        tags=["training", "welfare"],
        source_refs=[context, direct],
        limitations=["Not an individual treatment plan.", "Not a diagnosis."],
    )

    assert first.content_hash() == reordered.content_hash()
    assert first.canonical_content_bytes() == reordered.canonical_content_bytes()


def test_canonical_json_includes_null_source_and_locator_fields() -> None:
    canonical_json = make_card().canonical_content_bytes().decode("utf-8")

    assert '"support_note":null' in canonical_json
    assert '"page":null' in canonical_json
    assert '"pmcid":null' in canonical_json
    assert '"doi":null' in canonical_json
    assert '"dataset_id":null' in canonical_json
    assert '"item_id":null' in canonical_json
    assert '"fragment":null' in canonical_json


def test_explicit_none_and_omitted_optional_values_have_same_hash() -> None:
    omitted = make_card()
    explicit_none = make_card(
        source_refs=[
            make_source_ref(
                support_note=None,
                locator=make_locator(
                    fragment=None,
                    page=None,
                    pmcid=None,
                    doi=None,
                    dataset_id=None,
                    item_id=None,
                ),
            )
        ]
    )

    assert omitted.content_hash() == explicit_none.content_hash()
    assert omitted.canonical_content_bytes() == explicit_none.canonical_content_bytes()


def test_canonical_content_golden_vector() -> None:
    card = make_card()
    expected_json = (
        '{"canonical_hash_version":"evidence-card-content-v1",'
        '"claim":"Reward-based handling can reduce avoidable fear during routine care.",'
        '"claim_language":"en","limitations":[],"schema_version":"1.0",'
        '"source_refs":[{"evidence_level":"DIRECT","locator":{"dataset_id":null,'
        '"doi":null,"fragment":null,"item_id":null,"kind":"html","page":null,'
        '"pmcid":null,"section":"Safe handling","url":"https://example.org/guidance"},'
        '"source_id":"example-guidance","support_note":null}],"tags":[],'
        '"topic":"fear-aware handling"}'
    )
    expected_hash = "sha256:0e5415f9dd8e50285f811dfba5c887f87c8d24c3f061e89d3c91e57668a1e8a8"

    assert card.canonical_content_bytes() == expected_json.encode("utf-8")
    assert card.content_hash() == expected_hash


def test_content_hash_excludes_card_identity() -> None:
    original = make_card()
    same_content_with_new_id = make_card(card_id=UUID("5f896b26-e029-441d-8c30-6203e57b8586"))

    assert original.content_hash() == same_content_with_new_id.content_hash()


def test_content_hash_changes_with_approval_target_content() -> None:
    base = make_card()
    changed_cards = [
        make_card(claim="A different claim."),
        make_card(claim_language=ContentLanguage.KOREAN),
        make_card(topic="a different topic"),
        make_card(tags=["new-tag"]),
        make_card(
            source_refs=[
                make_source_ref(
                    locator=make_locator(section="A different section"),
                )
            ]
        ),
        make_card(source_refs=[make_source_ref(evidence_level=EvidenceLevel.SUPPORTING)]),
    ]

    assert all(card.content_hash() != base.content_hash() for card in changed_cards)


def test_evidence_card_json_round_trip_without_source_body() -> None:
    card = make_card(
        tags=["welfare", "training"],
        limitations=["This claim does not prescribe an individual treatment plan."],
    )

    restored = EvidenceCard.model_validate_json(card.model_dump_json())

    assert restored == card
    assert restored.content_hash() == card.content_hash()
    assert "quote" not in EvidenceCard.model_fields
    assert "source_body" not in EvidenceCard.model_fields


@pytest.mark.parametrize(
    ("field", "value"),
    [("claim", "   "), ("source_refs", []), ("topic", "")],
)
def test_card_rejects_empty_core_fields(field: str, value) -> None:
    with pytest.raises(ValidationError):
        make_card(**{field: value})


def test_invalid_enum_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_source_ref(evidence_level="CERTAIN")

    with pytest.raises(ValidationError):
        ReviewDecision(
            card_id=CARD_ID,
            reviewer="reviewer@example.org",
            reviewed_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
            content_hash_version=CANONICAL_HASH_VERSION,
            card_content_hash=CONTENT_HASH,
            decision=ReviewStatus.PENDING_SEMANTIC_REVIEW,
            note="Pending is not a review decision.",
        )
