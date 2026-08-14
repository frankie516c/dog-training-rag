"""The declared shape of a run, so deletion is detectable.

Deriving the expected shape from the data cannot detect deletion: remove every ``v2``
record and the observed version set simply becomes smaller, and remove the highest run
number and ``max()`` follows it down. Both were reported as OK by earlier versions of
``integrity.py``. The expectation is therefore declared once, stored beside the records,
and hashed into the manifest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


class ExpectationError(RuntimeError):
    """The declared shape of a run is missing or unusable."""


@dataclass(frozen=True)
class RunExpectation:
    versions: tuple[str, ...]
    runs: int
    questions: int

    @property
    def total_records(self) -> int:
        return len(self.versions) * self.runs * self.questions

    def as_dict(self) -> dict:
        return asdict(self) | {"total_records": self.total_records}


def expectation_path(records_path: Path) -> Path:
    return records_path.with_name(records_path.stem + "_expectation.json")


def load_expectation(records_path: Path, *, path: Path | None = None) -> RunExpectation:
    """Load the declared shape, from ``path`` when given, otherwise from beside the records.

    The override exists so a checker can be pointed at an arbitrary run instead of one
    hardcoded records file; see ``verify_run.py``.
    """

    path = path or expectation_path(records_path)
    if not path.exists():
        raise ExpectationError(
            f"missing {path.name}; without a declared shape a deleted version or run "
            "cannot be detected"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        expectation = RunExpectation(
            versions=tuple(payload["versions"]),
            runs=int(payload["runs"]),
            questions=int(payload["questions"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExpectationError(f"{path.name} is malformed: {exc}") from exc
    if not expectation.versions or expectation.runs < 1 or expectation.questions < 1:
        raise ExpectationError(f"{path.name} declares an empty run")
    return expectation


def write_expectation(records_path: Path, expectation: RunExpectation) -> Path:
    path = expectation_path(records_path)
    path.write_text(
        json.dumps(expectation.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def check_against(expectation: RunExpectation, records: list[dict]) -> dict:
    """Compare observed records with the declared shape. Absence is a failure."""

    observed_versions = sorted({record["prompt_version"] for record in records})
    observed_runs = sorted({record["run_number"] for record in records})
    observed_questions = sorted({record["question_id"] for record in records})

    per_pair: dict[tuple[str, str], int] = {}
    for record in records:
        key = (record["prompt_version"], record["question_id"])
        per_pair[key] = per_pair.get(key, 0) + 1

    missing_pairs = [
        {
            "prompt_version": version,
            "question_id": question,
            "found": per_pair.get((version, question), 0),
        }
        for version in expectation.versions
        for question in observed_questions
        if per_pair.get((version, question), 0) != expectation.runs
    ]

    return {
        "declared": expectation.as_dict(),
        "observed_versions": observed_versions,
        "observed_run_numbers": observed_runs,
        "observed_questions": len(observed_questions),
        "observed_records": len(records),
        "missing_versions": sorted(set(expectation.versions) - set(observed_versions)),
        "unexpected_versions": sorted(set(observed_versions) - set(expectation.versions)),
        "missing_run_numbers": sorted(set(range(1, expectation.runs + 1)) - set(observed_runs)),
        "question_count_matches": len(observed_questions) == expectation.questions,
        "record_count_matches": len(records) == expectation.total_records,
        "incomplete_version_question_pairs": missing_pairs,
    }


def satisfied(result: dict) -> bool:
    return (
        not result["missing_versions"]
        and not result["unexpected_versions"]
        and not result["missing_run_numbers"]
        and result["question_count_matches"]
        and result["record_count_matches"]
        and not result["incomplete_version_question_pairs"]
    )
