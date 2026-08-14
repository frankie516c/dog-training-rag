"""The checker must fail on absence, for any run, not just the frozen v0 one.

Every deletion test copies the real run to a temporary directory and actually removes
records. A test that asserts on an untouched file cannot tell a working detector from one
that always returns OK.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from experiments.prompt_eval_v0.expectation import expectation_path
from experiments.prompt_eval_v0.loading import sidecar_path
from experiments.prompt_eval_v0.verify_run import VerificationError, main, verify

RESULTS = Path("experiments/prompt_eval_v0/results")
TARGETED = RESULTS / "targeted_v1_1.jsonl"
FROZEN_V0 = RESULTS / "prompt_only.jsonl"
FROZEN_V0_SHA = "979fd8841e4c478c2692706212cb2010b59e833d775557cf1943ea8027a22e3d"


def copy_run(tmp_path: Path, records_path: Path) -> Path:
    """Copy a run — records, expectation and config sidecar — into tmp_path."""

    target = tmp_path / records_path.name
    shutil.copy(records_path, target)
    for source, destination in (
        (expectation_path(records_path), expectation_path(target)),
        (sidecar_path(records_path), sidecar_path(target)),
    ):
        if source.exists():
            shutil.copy(source, destination)
    return target


def rewrite(records_path: Path, records: list[dict]) -> None:
    """Write records back and refresh the sidecar binding, so only the shape changed.

    Without this the sidecar sha would fail first and every deletion test would pass for
    the wrong reason.
    """

    records_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    sidecar = sidecar_path(records_path)
    if sidecar.exists():
        config = json.loads(sidecar.read_text(encoding="utf-8"))
        config["records_sha256"] = hashlib.sha256(records_path.read_bytes()).hexdigest()
        sidecar.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def read_records(records_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and "prompt_version" in line
    ]


def test_targeted_run_matches_its_declared_shape():
    result = verify(TARGETED)
    assert result["passed"], result
    assert result["declared_shape_check"]["declared"] == {
        "versions": ("v1", "v1.1"),
        "runs": 3,
        "questions": 9,
        "total_records": 54,
    }
    assert result["declared_shape_check"]["observed_records"] == 54


def test_cli_exits_zero_for_the_targeted_run():
    assert main(["--records", str(TARGETED)]) == 0


@pytest.mark.parametrize(
    ("label", "drop"),
    [
        ("whole version", lambda r: r["prompt_version"] == "v1.1"),
        ("whole question", lambda r: r["question_id"] == "T9"),
        ("highest run", lambda r: r["run_number"] == 3),
        ("middle run", lambda r: r["run_number"] == 2),
        (
            "single record",
            lambda r: (r["question_id"], r["prompt_version"], r["run_number"]) == ("T1", "v1", 1),
        ),
    ],
)
def test_deletion_is_detected(tmp_path, label, drop):
    records_path = copy_run(tmp_path, TARGETED)
    original = read_records(records_path)
    kept = [record for record in original if not drop(record)]
    assert len(kept) < len(original), f"{label} deleted nothing"
    rewrite(records_path, kept)

    result = verify(records_path)
    assert not result["passed"], f"{label} went undetected"
    assert main(["--records", str(records_path)]) == 1


def test_missing_expectation_file_is_a_failure(tmp_path):
    records_path = copy_run(tmp_path, TARGETED)
    expectation_path(records_path).unlink()
    with pytest.raises(VerificationError):
        verify(records_path)
    assert main(["--records", str(records_path)]) == 1


def test_explicit_expectation_path_is_used(tmp_path):
    records_path = copy_run(tmp_path, TARGETED)
    declared = tmp_path / "elsewhere.json"
    declared.write_text(
        json.dumps({"versions": ["v1", "v1.1"], "runs": 3, "questions": 9}), encoding="utf-8"
    )
    expectation_path(records_path).unlink()
    result = verify(records_path, expectation_file=declared)
    assert result["passed"]
    assert result["expectation_path"] == declared.as_posix()


def test_expectation_declaring_a_different_shape_fails(tmp_path):
    records_path = copy_run(tmp_path, TARGETED)
    declared = tmp_path / "other_shape.json"
    declared.write_text(
        json.dumps({"versions": ["v1", "v1.1"], "runs": 4, "questions": 9}), encoding="utf-8"
    )
    result = verify(records_path, expectation_file=declared)
    assert not result["passed"]


def test_records_edited_after_the_sidecar_was_written_fails(tmp_path):
    records_path = copy_run(tmp_path, TARGETED)
    records = read_records(records_path)
    records[0]["answer"] = (records[0].get("answer") or "") + " edited"
    # Deliberately not refreshing the sidecar: this is the tamper case.
    records_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    result = verify(records_path)
    assert not result["passed"]
    assert "different records file" in (result["config_binding_error"] or "")


def test_missing_config_sidecar_fails(tmp_path):
    records_path = copy_run(tmp_path, TARGETED)
    sidecar_path(records_path).unlink()
    result = verify(records_path)
    assert not result["passed"]
    assert result["config_binding_error"]


def test_duplicate_coordinates_fail(tmp_path):
    records_path = copy_run(tmp_path, TARGETED)
    records = read_records(records_path)
    rewrite(records_path, records + [records[0]])
    result = verify(records_path)
    assert not result["passed"]
    assert result["duplicate_keys"]


def test_malformed_line_fails(tmp_path):
    records_path = copy_run(tmp_path, TARGETED)
    with records_path.open("a", encoding="utf-8") as handle:
        handle.write('{"prompt_version": broken}\n')
    result = verify(records_path)
    assert not result["passed"]
    assert result["malformed_lines"]


def test_legacy_v0_layout_needs_the_explicit_flag():
    """The frozen v0 file has no sidecar; accepting it silently would hide a real gap."""

    assert verify(FROZEN_V0)["passed"] is False
    assert verify(FROZEN_V0, allow_legacy_config=True)["passed"] is True


def test_verifying_does_not_modify_the_frozen_v0_records():
    verify(FROZEN_V0, allow_legacy_config=True)
    assert hashlib.sha256(FROZEN_V0.read_bytes()).hexdigest() == FROZEN_V0_SHA
