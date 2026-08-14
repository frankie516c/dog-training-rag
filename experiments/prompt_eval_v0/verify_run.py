"""Verify any prompt-eval run against its declared shape.

``integrity.py`` is bound to the frozen v0 records: its ``RECORDS_PATH`` is a module
constant and its context check is written against the 14-question v0 fixture, so it cannot
be pointed at another run. That left the 54-record targeted run with no shipped command
that would notice a deleted version, question, run or record — the report said "declared
shape satisfied" on the strength of an ad-hoc script.

This module is that command. It takes the records file and, optionally, the expectation
file explicitly, so it works for any run:

    python -m experiments.prompt_eval_v0.verify_run \
        --records experiments/prompt_eval_v0/results/targeted_v1_1.jsonl

Exit status is 0 only when every check passes. Absence is always a failure: a missing
expectation file, a missing version, a short run, one deleted record, a config sidecar
that was written for different records, or a records file whose bytes no longer match the
sha recorded in that sidecar.

It reads. It never writes to the run it is checking.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from experiments.prompt_eval_v0.expectation import (
    ExpectationError,
    check_against,
    expectation_path,
    load_expectation,
    satisfied,
)
from experiments.prompt_eval_v0.loading import ConfigResolutionError, load_run, sidecar_path
from experiments.prompt_eval_v0.provenance import sha256_file


class VerificationError(RuntimeError):
    """The run could not be verified at all, as opposed to failing a check."""


def read_records(records_path: Path) -> tuple[list[dict], list[int]]:
    """Return parsed records and the line numbers that would not parse.

    Done before ``load_run`` so a malformed line is reported by number instead of
    surfacing as an uncaught JSONDecodeError.
    """

    records: list[dict] = []
    malformed: list[int] = []
    for number, line in enumerate(records_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            malformed.append(number)
            continue
        if "prompt_version" in payload:
            records.append(payload)
    return records, malformed


def duplicate_keys(records: list[dict]) -> list[list]:
    seen: set[tuple] = set()
    duplicates: list[list] = []
    for record in records:
        key = (record["prompt_version"], record["question_id"], record["run_number"])
        if key in seen:
            duplicates.append(list(key))
        seen.add(key)
    return duplicates


def verify(
    records_path: Path,
    *,
    expectation_file: Path | None = None,
    allow_legacy_config: bool = False,
) -> dict:
    """Check one run. The returned dict always carries ``passed``."""

    if not records_path.exists():
        raise VerificationError(f"missing records file: {records_path}")

    records, malformed = read_records(records_path)
    declared_path = expectation_file or expectation_path(records_path)
    try:
        expectation = load_expectation(records_path, path=declared_path)
    except ExpectationError as exc:
        raise VerificationError(str(exc)) from exc

    # load_run is what binds the config sidecar to these exact bytes; it raises when the
    # binding is missing or stale, which is a verification failure, not an exception to
    # let through.
    binding_error: str | None = None
    config_source = None
    if not malformed:
        # Skipped when a line is malformed: load_run would raise an uncaught
        # JSONDecodeError on the same input and the line number would be lost.
        try:
            loaded = load_run(records_path)
            config_source = loaded.config_source
        except ConfigResolutionError as exc:
            binding_error = str(exc)

    shape = check_against(expectation, records)
    duplicates = duplicate_keys(records)
    sidecar = sidecar_path(records_path)
    legacy_config_used = config_source == "legacy_inline"

    result = {
        "records_path": records_path.as_posix(),
        "records_sha256": sha256_file(records_path),
        "expectation_path": declared_path.as_posix(),
        "config_sidecar": sidecar.as_posix() if sidecar.exists() else None,
        "config_source": config_source,
        "config_binding_error": binding_error,
        "malformed_lines": malformed,
        "duplicate_keys": duplicates,
        "declared_shape_check": shape,
        "matches_declared_shape": satisfied(shape),
        "legacy_config_used": legacy_config_used,
    }
    result["passed"] = (
        not malformed
        and not duplicates
        and binding_error is None
        and result["matches_declared_shape"]
        and (allow_legacy_config or not legacy_config_used)
    )
    return result


def failure_reasons(result: dict) -> list[str]:
    reasons = []
    if result["malformed_lines"]:
        reasons.append(f"malformed lines {result['malformed_lines']}")
    if result["duplicate_keys"]:
        reasons.append(f"duplicate keys {result['duplicate_keys']}")
    if result["config_binding_error"]:
        reasons.append(result["config_binding_error"])
    if not result["matches_declared_shape"]:
        shape = result["declared_shape_check"]
        if shape["missing_versions"]:
            reasons.append(f"missing versions {shape['missing_versions']}")
        if shape["unexpected_versions"]:
            reasons.append(f"unexpected versions {shape['unexpected_versions']}")
        if shape["missing_run_numbers"]:
            reasons.append(f"missing run numbers {shape['missing_run_numbers']}")
        if not shape["question_count_matches"]:
            reasons.append(
                f"question count {shape['observed_questions']} != {shape['declared']['questions']}"
            )
        if not shape["record_count_matches"]:
            reasons.append(
                f"record count {shape['observed_records']} != {shape['declared']['total_records']}"
            )
        if shape["incomplete_version_question_pairs"]:
            reasons.append(
                f"{len(shape['incomplete_version_question_pairs'])} incomplete "
                "version/question cells"
            )
    if result["legacy_config_used"]:
        reasons.append("config came from a legacy inline line, not a bound sidecar")
    return reasons


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--records", required=True, type=Path, help="records JSONL to verify")
    parser.add_argument(
        "--expectation",
        type=Path,
        default=None,
        help="declared-shape JSON; defaults to <records>_expectation.json",
    )
    parser.add_argument(
        "--allow-legacy-config",
        action="store_true",
        help="accept the frozen v0 layout, whose config is on line 1 instead of a sidecar",
    )
    args = parser.parse_args(argv)

    try:
        result = verify(
            args.records,
            expectation_file=args.expectation,
            allow_legacy_config=args.allow_legacy_config,
        )
    except VerificationError as exc:
        print(f"verify: FAILED — {exc}")
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["passed"]:
        declared = result["declared_shape_check"]["declared"]
        print(
            f"\nverify: OK — {declared['total_records']} records, "
            f"{len(declared['versions'])} versions x {declared['questions']} questions x "
            f"{declared['runs']} runs"
        )
        return 0
    for reason in failure_reasons(result):
        print(f"\nverify: FAILED — {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
