"""Regressions for the harness defects found by review of Prompt Eval v0.

Each test names the claim it protects. They are about the evaluation harness, not about
production RAG behaviour, which these changes do not touch.
"""

import csv
import json
from pathlib import Path

import pytest

from experiments.prompt_eval_v0.loading import ConfigResolutionError, load_run, sidecar_path
from experiments.prompt_eval_v0.provenance import (
    response_fingerprint,
    sanitize_endpoint,
)
from experiments.prompt_eval_v0.review import (
    BLIND_FIELDS,
    BLIND_SHUFFLE_SEED,
    build_blind_sheet,
    summarise,
    verify_auto_checks_reproduce,
    verify_not_answerable_contract,
)
from experiments.prompt_eval_v0.semantic_review import label_applies, unreviewed_records

RESULTS = Path("experiments/prompt_eval_v0/results")
RECORDS_PATH = RESULTS / "prompt_only.jsonl"
FROZEN_RECORDS_SHA = "979fd8841e4c478c2692706212cb2010b59e833d775557cf1943ea8027a22e3d"


def load_frozen_records() -> list[dict]:
    return load_run(RECORDS_PATH).records


def make_record(**overrides) -> dict:
    record = {
        "prompt_version": "v0",
        "question_id": "G1",
        "kind": "guidance_how_to",
        "run_number": 1,
        "message": "질문",
        "card_ids": ["c1"],
        "provider_result": "accepted",
        "answer": "답변",
        "raw_response": '{"answerable": true}',
        "used_card_ids": ["c1"],
        "latency_ms": 100,
        "answerable": True,
        "auto_checks": {
            "used_card_ids_valid": True,
            "numbers_outside_evidence": [],
            "latin_outside_evidence": [],
            "reversal_hits": [],
            "procedure_hits": [],
            "sentence_count": 1,
            "answer_chars": 2,
            "fabricated_content": False,
        },
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------------------
# Finding 11 — the frozen records must never change
# --------------------------------------------------------------------------------------


def test_frozen_records_hash_is_unchanged() -> None:
    import hashlib

    assert hashlib.sha256(RECORDS_PATH.read_bytes()).hexdigest() == FROZEN_RECORDS_SHA


# --------------------------------------------------------------------------------------
# Finding 3 — recomputation coverage must be reported honestly
# --------------------------------------------------------------------------------------


def test_coverage_counts_only_applicable_records() -> None:
    records = load_frozen_records()

    coverage = verify_auto_checks_reproduce(records)

    assert coverage["total_records"] == 126
    assert coverage["applicable_records"] == 75
    assert coverage["checked_records"] == 75
    assert coverage["skipped_records"] == 51
    assert coverage["checked_records"] + coverage["skipped_records"] == coverage["total_records"]
    assert coverage["mismatches"] == 0
    assert coverage["coverage_consistent"] is True
    assert coverage["checked_records"] != coverage["total_records"], (
        "reporting checked == total was the original overstatement"
    )


def test_applicable_record_without_stored_checks_fails_closed() -> None:
    coverage = verify_auto_checks_reproduce([make_record(auto_checks=None)])

    assert coverage["applicable_without_stored_checks"]
    assert coverage["checked_records"] == 0


def test_not_answerable_records_get_their_own_applicable_checks() -> None:
    records = load_frozen_records()

    contract = verify_not_answerable_contract(records)

    assert contract["applicable_records"] == 51
    assert contract["checked_records"] == 51
    assert contract["violations"] == 0


def test_not_answerable_contract_catches_a_violation() -> None:
    bad = make_record(provider_result="not_answerable", answer="있으면 안 되는 답변")

    assert verify_not_answerable_contract([bad])["violations"] == 1


# --------------------------------------------------------------------------------------
# Finding 4 — the blind sheet must actually be blind
# --------------------------------------------------------------------------------------


def test_blind_sheet_has_no_version_column() -> None:
    assert "prompt_version" not in BLIND_FIELDS
    assert "prompt_version_hidden" not in BLIND_FIELDS
    assert "run_number" not in BLIND_FIELDS

    sheet, _ = build_blind_sheet(load_frozen_records())
    serialised = json.dumps(sheet, ensure_ascii=False)
    for version in ("v0", "v1", "v2"):
        assert f'"{version}"' not in serialised


def test_blind_sheet_order_does_not_encode_the_version() -> None:
    records = load_frozen_records()
    sheet, key = build_blind_sheet(records)
    by_row = {row["row_id"]: row for row in key}

    positions = [by_row[row["row_id"]]["prompt_version"] for row in sheet]
    cycles = {
        index % 3: {positions[i] for i in range(index, len(positions), 3)} for index in range(3)
    }

    assert all(len(versions) > 1 for versions in cycles.values()), (
        "a fixed v0/v1/v2 rotation would let a scorer read the version off the row position"
    )


def test_blind_sheet_row_ids_are_opaque_and_seed_stable() -> None:
    records = load_frozen_records()

    sheet_a, key_a = build_blind_sheet(records, seed=BLIND_SHUFFLE_SEED)
    sheet_b, _ = build_blind_sheet(records, seed=BLIND_SHUFFLE_SEED)
    sheet_c, _ = build_blind_sheet(records, seed=BLIND_SHUFFLE_SEED + 1)

    assert [row["row_id"] for row in sheet_a] == [row["row_id"] for row in sheet_b]
    assert [row["row_id"] for row in sheet_a] != [row["row_id"] for row in sheet_c]
    assert all(row["row_id"].startswith("B") and len(row["row_id"]) == 11 for row in sheet_a)
    assert len({row["row_id"] for row in sheet_a}) == len(sheet_a)
    # The key file is the only way back to version and run.
    assert {"prompt_version", "run_number"} <= set(key_a[0])


def test_shipped_blind_sheet_file_carries_no_version() -> None:
    path = RESULTS / "blind_review_v2.csv"
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))

    assert rows
    assert "prompt_version" not in rows[0]
    assert "prompt_version_hidden" not in rows[0]


# --------------------------------------------------------------------------------------
# Finding 6 — semantic labels must be bound to the response they describe
# --------------------------------------------------------------------------------------


def test_labels_apply_to_the_frozen_records() -> None:
    records = load_frozen_records()

    assert unreviewed_records(records) == []
    labelled = [r for r in records if r["question_id"] == "O4" and r["prompt_version"] == "v2"]
    assert labelled and all(label_applies(record) for record in labelled)


def test_label_does_not_survive_a_changed_answer() -> None:
    record = next(
        r
        for r in load_frozen_records()
        if (r["question_id"], r["prompt_version"], r["run_number"]) == ("O4", "v2", 2)
    )
    assert label_applies(record)

    mutated = dict(record, answer=(record["answer"] or "") + "!")

    assert not label_applies(mutated)
    assert unreviewed_records([mutated]) == ["O4|v2|2"]


def test_fingerprint_changes_with_every_bound_field() -> None:
    base = make_record()
    baseline = response_fingerprint(base)

    for field, value in (
        ("prompt_version", "v1"),
        ("message", "다른 질문"),
        ("card_ids", ["c2"]),
        ("raw_response", "다른 원문"),
        ("answer", "다른 답변"),
        ("provider_result", "not_answerable"),
        ("used_card_ids", ["c2"]),
    ):
        assert response_fingerprint(dict(base, **{field: value})) != baseline, field


# --------------------------------------------------------------------------------------
# Finding 12 — provider errors are their own denominator
# --------------------------------------------------------------------------------------


def test_provider_error_is_not_counted_as_resistance_or_a_correct_refusal() -> None:
    overreach_error = make_record(
        question_id="O4",
        kind="overreach",
        provider_result="error",
        answer=None,
        auto_checks=None,
        would_fallback=True,
    )

    summary = summarise([overreach_error])

    assert summary["provider_errors"] == 1
    assert summary["responded_runs"] == 0
    assert summary["adversarial_resisted"] == "0/0"
    assert summary["adversarial_provider_errors"] == 1
    assert summary["answerable_correct"] == "0/0"
    assert summary["answerable_accuracy_excluding_errors"] is None
    assert summary["fallback"] == 1


def test_error_free_run_reports_error_denominator_explicitly() -> None:
    summary = summarise([r for r in load_frozen_records() if r["prompt_version"] == "v0"])

    assert summary["provider_errors"] == 0
    assert summary["responded_runs"] == summary["total_runs"]


# --------------------------------------------------------------------------------------
# Finding 1 / 2 — the config sidecar must be read, and must fail closed
# --------------------------------------------------------------------------------------


def test_legacy_inline_config_is_still_read() -> None:
    loaded = load_run(RECORDS_PATH)

    assert loaded.config_source == "legacy_inline"
    assert loaded.config["model"] == "gemma3:4b"
    assert len(loaded.records) == 126


def test_sidecar_config_is_preferred(tmp_path: Path) -> None:
    import hashlib

    records = tmp_path / "run.jsonl"
    records.write_text(json.dumps(make_record(), ensure_ascii=False) + "\n", encoding="utf-8")
    sidecar_path(records).write_text(
        json.dumps(
            {
                "model": "from-sidecar",
                "records_sha256": hashlib.sha256(records.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    loaded = load_run(records)

    assert loaded.config_source == "sidecar"
    assert loaded.config["model"] == "from-sidecar"


def test_missing_config_fails_closed_instead_of_reporting_an_empty_model(tmp_path: Path) -> None:
    records = tmp_path / "run.jsonl"
    records.write_text(json.dumps(make_record(), ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ConfigResolutionError):
        load_run(records)


def test_config_without_a_model_fails_closed(tmp_path: Path) -> None:
    records = tmp_path / "run.jsonl"
    records.write_text(json.dumps(make_record(), ensure_ascii=False) + "\n", encoding="utf-8")
    sidecar_path(records).write_text(json.dumps({"timeout_seconds": 30}), encoding="utf-8")

    with pytest.raises(ConfigResolutionError):
        load_run(records)


def test_sidecar_belonging_to_another_run_is_rejected(tmp_path: Path) -> None:
    records = tmp_path / "run.jsonl"
    records.write_text(json.dumps(make_record(), ensure_ascii=False) + "\n", encoding="utf-8")
    sidecar_path(records).write_text(
        json.dumps({"model": "m", "records_sha256": "0" * 64}), encoding="utf-8"
    )

    with pytest.raises(ConfigResolutionError):
        load_run(records)


# --------------------------------------------------------------------------------------
# Finding 9 — no raw base_url in artifacts
# --------------------------------------------------------------------------------------


def test_endpoint_sanitisation_drops_everything_that_can_carry_a_secret() -> None:
    result = sanitize_endpoint("https://user:tok@gw.example.com:8443/v1/deploy?api-key=abc#frag")

    assert result["sanitized_origin"] == "https://gw.example.com:8443"
    assert result["locality"] == "remote"
    assert result["had_userinfo"] is True
    assert result["had_query_or_fragment"] is True
    # Only the values can carry a secret; the boolean field names legitimately say "user".
    values = " ".join(str(value) for value in result.values())
    for leak in ("user:", "tok", "abc", "frag", "?"):
        assert leak not in values


def test_local_endpoint_is_labelled_local() -> None:
    result = sanitize_endpoint("http://localhost:11434/v1")

    assert result["locality"] == "local"
    assert result["sanitized_origin"] == "http://localhost:11434"


def test_run_config_records_no_raw_base_url() -> None:
    from experiments.prompt_eval_v0.runner import RunConfig

    config = RunConfig(
        model="m", base_url="https://user:tok@host/v1?key=s", timeout_seconds=30.0
    ).as_dict()

    assert "base_url" not in config
    endpoint_values = " ".join(str(value) for value in config["endpoint"].values())
    for leak in ("user:", "tok", "key=s"):
        assert leak not in endpoint_values
    assert "host" in config["endpoint"]["sanitized_origin"]


# --------------------------------------------------------------------------------------
# Second review round — fail-open and reintroduced defects
# --------------------------------------------------------------------------------------


def test_missing_fingerprint_file_fails_closed_instead_of_dropping_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing binding file must not silently take critical_failures from 3 to 0."""

    import experiments.prompt_eval_v0.semantic_review as sr

    sr.label_fingerprints.cache_clear()
    monkeypatch.setattr(sr, "FINGERPRINT_PATH", Path("does-not-exist.json"))
    try:
        with pytest.raises(sr.LabelBindingError):
            sr.label_fingerprints()
    finally:
        sr.label_fingerprints.cache_clear()


def test_labelled_coordinates_are_known_without_the_binding_file() -> None:
    """unreviewed_records must not depend on the file it is meant to police."""

    from experiments.prompt_eval_v0.semantic_review import labelled_coordinate_keys

    keys = labelled_coordinate_keys()

    assert "O4|v2|2" in keys
    assert "O4|v0|1" in keys
    assert len(keys) == 19


def test_manifest_and_summary_carry_no_raw_base_url() -> None:
    """Finding 2/3: the legacy inline config must be sanitised before it is re-exported."""

    for name in ("manifest.json", "prompt_only_summary.json"):
        text = (RESULTS / name).read_text(encoding="utf-8")
        assert '"base_url"' not in text, name
        assert "11434/v1" not in text, name


def test_legacy_config_is_sanitised_on_load() -> None:
    config = load_run(RECORDS_PATH).config

    assert "base_url" not in config
    assert config["endpoint"]["locality"] == "local"
    assert config["endpoint_recovered_from_legacy_base_url"] is True


def test_targeted_runner_uses_the_shared_provider_builder() -> None:
    """Finding 8 must not be reintroduced in the harness that will run v1.1."""

    import inspect

    from experiments.prompt_eval_v0 import targeted

    source = inspect.getsource(targeted)

    assert "build_provider(config, settings)" in source
    assert "OpenAICompatibleGenerationProvider(" not in source


def test_targeted_summary_excludes_errors_from_acceptance_rates() -> None:
    """Finding 12: a failed run must not read as 'v1.1 refused everything'."""

    from experiments.prompt_eval_v0.targeted import summarise

    rows = [
        {
            "prompt_version": "v1.1",
            "question_id": "T1",
            "group": "over_refusal",
            "run_number": run,
            "provider_result": "error",
            "answer": None,
            "auto_checks": None,
            "latency_ms": 5,
            "would_fallback": True,
        }
        for run in (1, 2, 3)
    ]

    summary = summarise(rows, "v1.1")

    assert summary["provider_errors"] == 3
    assert summary["responded_runs"] == 0
    assert summary["accepted_by_group"]["over_refusal"] == "0/0"
    assert summary["provider_errors_by_group"]["over_refusal"] == 3
    assert summary["accepted_by_question"]["T1"] == "0/0"


def test_sidecar_without_a_records_binding_is_rejected(tmp_path: Path) -> None:
    records = tmp_path / "run.jsonl"
    records.write_text(json.dumps(make_record(), ensure_ascii=False) + "\n", encoding="utf-8")
    sidecar_path(records).write_text(json.dumps({"model": "m"}), encoding="utf-8")

    with pytest.raises(ConfigResolutionError):
        load_run(records)


def test_manifest_keys_are_posix_and_missing_inputs_are_recorded() -> None:
    manifest = json.loads((RESULTS / "manifest.json").read_text(encoding="utf-8"))

    assert all("\\" not in key for key in manifest["input_sha256"])
    assert "missing_inputs" in manifest
    assert manifest["missing_inputs"] == []
    for required in (
        "data/processed/evidence_cards.jsonl",
        "experiments/prompt_eval_v0/results/semantic_label_fingerprints.json",
        "experiments/prompt_eval_v0/targeted.py",
    ):
        assert manifest["input_sha256"][required]


def test_frozen_run_matches_its_declared_shape() -> None:
    from experiments.prompt_eval_v0.expectation import check_against, load_expectation, satisfied

    records = load_frozen_records()
    expectation = load_expectation(RECORDS_PATH)
    result = check_against(expectation, records)

    assert expectation.versions == ("v0", "v1", "v2")
    assert expectation.runs == 3
    assert expectation.total_records == 126
    assert satisfied(result)


@pytest.mark.parametrize(
    ("label", "drop"),
    [
        ("highest run deleted", lambda r: r["run_number"] == 3),
        ("middle run deleted", lambda r: r["run_number"] == 2),
        ("whole version deleted", lambda r: r["prompt_version"] == "v2"),
        ("one question deleted", lambda r: r["question_id"] == "O4"),
        (
            "single record deleted",
            lambda r: (r["question_id"], r["prompt_version"], r["run_number"]) == ("G1", "v0", 1),
        ),
    ],
)
def test_deletion_is_actually_detected(label: str, drop) -> None:
    """The previous version of this test never deleted anything, so it could not fail.

    Every shape derived from the data itself was blind to at least one of these.
    """

    from experiments.prompt_eval_v0.expectation import check_against, load_expectation, satisfied

    records = [record for record in load_frozen_records() if not drop(record)]
    assert len(records) < 126, label

    result = check_against(load_expectation(RECORDS_PATH), records)

    assert not satisfied(result), label


def test_missing_expectation_file_fails_closed(tmp_path: Path) -> None:
    from experiments.prompt_eval_v0.expectation import ExpectationError, load_expectation

    with pytest.raises(ExpectationError):
        load_expectation(tmp_path / "nothing.jsonl")


def test_latency_excludes_provider_errors() -> None:
    """A 30s timeout is not a slow answer."""

    rows = [
        make_record(question_id="R1", kind="research_explanation", latency_ms=1000),
        make_record(
            question_id="R1",
            kind="research_explanation",
            run_number=2,
            provider_result="error",
            answer=None,
            auto_checks=None,
            latency_ms=30000,
        ),
    ]

    summary = summarise(rows)

    assert summary["provider_errors"] == 1
    assert summary["latency_ms"]["max"] == 1000, "the timeout must not enter the latency stats"


def test_aggregate_marks_labels_invalid_when_a_fingerprint_breaks() -> None:
    """The written artifact must not read as a clean safety record."""

    records = load_frozen_records()
    v2 = [r for r in records if r["prompt_version"] == "v2"]
    assert summarise(v2)["semantic_labels_valid"] is True
    assert summarise(v2)["critical_failures"] == 3

    mutated = [
        dict(r, answer=(r["answer"] or "") + "!")
        if (r["question_id"], r["run_number"]) == ("O4", 2)
        else r
        for r in v2
    ]
    broken = summarise(mutated)

    assert broken["semantic_labels_valid"] is False
    assert broken["critical_failures"] is None, "a count of 0 would read as 'no findings'"


def test_missing_answerable_field_is_a_contract_violation() -> None:
    record = make_record(provider_result="not_answerable", answer=None, auto_checks=None)
    record.pop("answerable", None)

    result = verify_not_answerable_contract([record])

    assert result["violations"] == 1
    assert "answerable field absent" in result["violation_detail"][0]["problems"]


def test_v1_1_states_the_output_contract_once() -> None:
    """v1.1 is the single-variable arm; a duplicated reminder would confound it."""

    from experiments.prompt_eval_v0.prompts import CONTRACT_REMINDER, PROMPT_VERSIONS

    assert PROMPT_VERSIONS["v1.1"].count(CONTRACT_REMINDER) == 1
    assert PROMPT_VERSIONS["v1"].count(CONTRACT_REMINDER) == 1
    # v1.1 must be v1's rules plus the answerability block, nothing else.
    assert "Scope of answerability:" in PROMPT_VERSIONS["v1.1"]
    assert "Scope of answerability:" not in PROMPT_VERSIONS["v1"]
    assert "Answer shape:" not in PROMPT_VERSIONS["v1.1"]


def test_generation_api_key_reaches_the_provider_but_not_the_artifacts() -> None:
    from backend.app.config import Settings
    from experiments.prompt_eval_v0.runner import RunConfig, build_provider

    settings = Settings(
        _env_file=None,
        generation_base_url="http://localhost:11434/v1",
        generation_model="m",
        generation_api_key="sk-fake-eval-secret",
    )
    config = RunConfig(model="m", base_url="http://localhost:11434/v1", timeout_seconds=30.0)

    provider = build_provider(config, settings)

    assert provider._api_key == "sk-fake-eval-secret"
    assert "sk-fake-eval-secret" not in json.dumps(config.as_dict())
