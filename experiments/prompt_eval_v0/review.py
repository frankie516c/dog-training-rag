"""Merge automatic screens with the AI-assisted semantic review and emit the review sheets.

Outputs:
  results/aggregate.json                 per-version numbers, with explicit denominators
  results/semantic_review.json           the AI-assisted judgements, kept separate
  results/blind_review_v2.csv            one shuffled row per response, for a person
  results/blind_review_v2_key.csv        row_id -> version/run, kept out of the sheet
  results/blind_review_v2_manifest.json  hashes of both

The superseded results/blind_review.csv leaked prompt_version through row order. It is no
longer written; REPORT.md marks it invalid as blind evidence.

    python -m experiments.prompt_eval_v0.review
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from experiments.prompt_eval_v0.checks import run_auto_checks
from experiments.prompt_eval_v0.fixture import QUESTIONS, QuestionKind, cards_for
from experiments.prompt_eval_v0.provenance import response_fingerprint, sha256_file
from experiments.prompt_eval_v0.semantic_review import (
    CONCERN_JUDGEMENTS,
    CRITICAL_JUDGEMENTS,
    KNOWN_FALSE_POSITIVES,
    critical_for,
    expected_answerable,
    label_fingerprints,
    resisted_while_answering,
    unreviewed_records,
)

RESULTS_DIR = Path(__file__).parent / "results"
RECORDS_PATH = RESULTS_DIR / "prompt_only.jsonl"
VERSIONS = ("v0", "v1", "v2")

#: The sheet a person scores. No prompt version, no run number, no recoverable ordering.
#:
#: The first version sorted by (question_id, run_number, prompt_version), which emitted
#: v0/v1/v2 in a fixed three-row cycle — hiding the version column leaked nothing because
#: the row position gave it away. Rows are now shuffled with a fixed seed and given opaque
#: ids; the mapping back to version and run lives in a separate key file.
BLIND_FIELDS = (
    "row_id",
    "question",
    "evidence_claims",
    "model_answer",
    "used_card_ids",
    "auto_provider_result",
    "auto_flags",
    # Columns for a person to fill in.
    "human_direction_preserved",
    "human_beyond_evidence",
    "human_directness",
    "human_readability",
    "human_note",
)

KEY_FIELDS = ("row_id", "question_id", "prompt_version", "run_number", "kind")

BLIND_SHUFFLE_SEED = 20260813


def load_records() -> list[dict]:
    records = []
    for line in RECORDS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if "prompt_version" in payload:
            records.append(payload)
    return records


def verify_auto_checks_reproduce(records: list[dict]) -> dict:
    """Recompute the stored screens with the current code, reporting real coverage.

    `auto_checks` only exists on accepted drafts, so a `not_answerable` record is not
    applicable to this check. The first version of this function skipped those records
    while reporting `checked = len(records)`, which overstated coverage. Every count is now
    explicit, and an applicable record missing its stored checks fails closed.
    """

    applicable = [record for record in records if record["provider_result"] == "accepted"]
    mismatched = []
    missing_checks = []
    checked = 0

    for record in applicable:
        stored = record.get("auto_checks")
        if not stored or record.get("answer") is None:
            missing_checks.append(
                [record["prompt_version"], record["question_id"], record["run_number"]]
            )
            continue
        question = next(q for q in QUESTIONS if q.question_id == record["question_id"])
        fresh = run_auto_checks(
            record["answer"],
            cards=cards_for(question.scope),
            used_card_ids=record["used_card_ids"],
            allow_procedure=question.kind is QuestionKind.GUIDANCE_HOW_TO,
        ).as_dict()
        checked += 1
        if fresh != stored:
            mismatched.append(
                {
                    "key": [record["prompt_version"], record["question_id"], record["run_number"]],
                    "stored": stored,
                    "recomputed": fresh,
                }
            )

    skipped = len(records) - len(applicable)
    return {
        "total_records": len(records),
        "applicable_records": len(applicable),
        "checked_records": checked,
        "skipped_records": skipped,
        "skipped_reason": "not_answerable/error records carry no auto_checks by design",
        "mismatches": len(mismatched),
        "mismatch_detail": mismatched,
        # Fail closed: an accepted record without stored checks is a data defect.
        "applicable_without_stored_checks": missing_checks,
        "coverage_consistent": checked + len(missing_checks) + skipped == len(records),
    }


def verify_not_answerable_contract(records: list[dict]) -> dict:
    """Checks that DO apply to a refusal, instead of forcing number/latin screens on it."""

    rows = [record for record in records if record["provider_result"] == "not_answerable"]
    violations = []
    for record in rows:
        problems = []
        if record.get("answer") is not None:
            problems.append("answer is not null")
        if record.get("used_card_ids"):
            problems.append("used_card_ids not empty")
        if record.get("auto_checks") is not None:
            problems.append("auto_checks unexpectedly present")
        # A missing key is a data defect, not compliance.
        if "answerable" not in record:
            problems.append("answerable field absent")
        elif record["answerable"] not in (False, None):
            problems.append("answerable flag inconsistent")
        if problems:
            violations.append(
                {
                    "key": [record["prompt_version"], record["question_id"], record["run_number"]],
                    "problems": problems,
                }
            )
    return {
        "applicable_records": len(rows),
        "checked_records": len(rows),
        "violations": len(violations),
        "violation_detail": violations,
    }


def summarise(rows: list[dict]) -> dict:
    """Aggregate one version.

    Provider failures get their own denominator. A transport error is not a refusal, not an
    answerability success and not adversarial resistance, so the rates below are computed
    over responses that actually came back.
    """

    total = len(rows)
    errors = [row for row in rows if row["provider_result"] == "error"]
    responded = [row for row in rows if row["provider_result"] != "error"]
    accepted = [row for row in responded if row["provider_result"] == "accepted"]
    answered_checks = [row["auto_checks"] for row in accepted if row.get("auto_checks")]

    answerable_correct = sum(
        1
        for row in responded
        if (row["provider_result"] == "accepted") is expected_answerable(row["question_id"])
    )
    overreach = [row for row in responded if row["kind"] == QuestionKind.OVERREACH.value]
    overreach_errors = [row for row in errors if row["kind"] == QuestionKind.OVERREACH.value]
    complied = [
        row
        for row in overreach
        if row["provider_result"] == "accepted" and not resisted_while_answering(row)
    ]
    critical = [row for row in rows if critical_for(row)]
    # Only responses have a response latency. A 30s timeout is not a slow answer, and
    # including it would pull the reported mean toward the failure.
    latencies = [row["latency_ms"] for row in responded]
    # A label that no longer binds silently empties critical_detail, so the artifact says
    # so rather than reading as a clean safety record.
    labels_valid = not unreviewed_records(rows)

    return {
        "total_runs": total,
        "provider_errors": len(errors),
        "responded_runs": len(responded),
        "accepted": len(accepted),
        "not_answerable": sum(1 for row in responded if row["provider_result"] == "not_answerable"),
        "invalid": sum(1 for row in responded if row["provider_result"] == "invalid"),
        "fallback": sum(1 for row in rows if row.get("would_fallback") is True),
        "answerable_correct": f"{answerable_correct}/{len(responded)}",
        "answerable_accuracy_excluding_errors": round(answerable_correct / len(responded), 3)
        if responded
        else None,
        "adversarial_resisted": f"{len(overreach) - len(complied)}/{len(overreach)}",
        "adversarial_provider_errors": len(overreach_errors),
        "semantic_labels_valid": labels_valid,
        "critical_failures": len(critical) if labels_valid else None,
        "critical_detail": [
            {
                "question_id": row["question_id"],
                "run_number": row["run_number"],
                "kinds": [kind.value for kind in critical_for(row)],
            }
            for row in critical
        ],
        "used_card_ids_valid": f"{sum(1 for c in answered_checks if c['used_card_ids_valid'])}"
        f"/{len(answered_checks)}",
        # Post-validation invariant, not a prompt metric: validate_draft already rejected
        # answers containing these, using the same context and the same patterns.
        "post_validation_numbers_outside_evidence": sum(
            1 for c in answered_checks if c["numbers_outside_evidence"]
        ),
        "post_validation_latin_outside_evidence": sum(
            1 for c in answered_checks if c["latin_outside_evidence"]
        ),
        "auto_flag_hits": sum(
            1 for c in answered_checks if c["reversal_hits"] or c["procedure_hits"]
        ),
        "latency_ms": {
            "mean": round(statistics.mean(latencies)) if latencies else None,
            "median": round(statistics.median(latencies)) if latencies else None,
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "answer_chars_median": round(
            statistics.median([c["answer_chars"] for c in answered_checks])
        )
        if answered_checks
        else None,
    }


def opaque_row_id(record: dict, seed: int) -> str:
    """A unique id that reveals nothing about version, run or original position.

    The coordinate is part of the hash input because identical answers recur across runs —
    38 of the 126 responses are byte-identical to another — and hashing the response alone
    collided. Hashing is one-way, so including the coordinate leaks nothing; the mapping
    back lives only in the key file.
    """

    coordinate = f"{record['question_id']}|{record['prompt_version']}|{record['run_number']}"
    digest = hashlib.sha256(
        f"{seed}|{coordinate}|{response_fingerprint(record)}".encode()
    ).hexdigest()
    return f"B{digest[:10]}"


def build_blind_sheet(records: list[dict], *, seed: int = BLIND_SHUFFLE_SEED) -> tuple[list, list]:
    """Return (sheet rows, key rows). Same seed and input always give the same order."""

    questions = {question.question_id: question for question in QUESTIONS}
    shuffled = sorted(records, key=lambda r: opaque_row_id(r, seed))

    sheet, key = [], []
    for record in shuffled:
        question = questions[record["question_id"]]
        checks = record.get("auto_checks") or {}
        row_id = opaque_row_id(record, seed)
        sheet.append(
            {
                "row_id": row_id,
                "question": question.message,
                "evidence_claims": " || ".join(card.claim for card in cards_for(question.scope)),
                "model_answer": record.get("answer") or "",
                "used_card_ids": " ".join(record.get("used_card_ids") or []),
                "auto_provider_result": record["provider_result"],
                "auto_flags": " ".join(
                    checks.get("reversal_hits", []) + checks.get("procedure_hits", [])
                ),
                "human_direction_preserved": "",
                "human_beyond_evidence": "",
                "human_directness": "",
                "human_readability": "",
                "human_note": "",
            }
        )
        key.append(
            {
                "row_id": row_id,
                "question_id": record["question_id"],
                "prompt_version": record["prompt_version"],
                "run_number": record["run_number"],
                "kind": record["kind"],
            }
        )
    return sheet, key


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    records = load_records()

    by_version = defaultdict(list)
    for record in records:
        by_version[record["prompt_version"]].append(record)

    aggregate = {
        "reproducibility_of_auto_checks": verify_auto_checks_reproduce(records),
        "not_answerable_contract": verify_not_answerable_contract(records),
        "semantic_label_binding": {
            "labelled_coordinates": len(label_fingerprints()),
            "fingerprint_mismatches": unreviewed_records(records),
        },
        "overall": {version: summarise(by_version[version]) for version in VERSIONS},
        "by_kind": {
            kind.value: {
                version: summarise([r for r in by_version[version] if r["kind"] == kind.value])
                for version in VERSIONS
            }
            for kind in QuestionKind
        },
    }

    (RESULTS_DIR / "aggregate.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    semantic = {
        "reviewer": "AI-assisted semantic review (not human-reviewed)",
        "method": "각 응답을 해당 EvidenceCard claim과 나란히 읽고 판정. 일탈만 기록.",
        "critical": [
            asdict(j) | {"critical": [k.value for k in j.critical]} for j in CRITICAL_JUDGEMENTS
        ],
        "concerns": [asdict(j) | {"critical": []} for j in CONCERN_JUDGEMENTS],
        "known_auto_false_positives": [
            {"flag": flag, "why": why} for flag, why in KNOWN_FALSE_POSITIVES
        ],
    }
    (RESULTS_DIR / "semantic_review.json").write_text(
        json.dumps(semantic, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    sheet, key = build_blind_sheet(records)
    sheet_path = RESULTS_DIR / "blind_review_v2.csv"
    key_path = RESULTS_DIR / "blind_review_v2_key.csv"
    with sheet_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BLIND_FIELDS)
        writer.writeheader()
        writer.writerows(sheet)
    with key_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=KEY_FIELDS)
        writer.writeheader()
        writer.writerows(key)

    (RESULTS_DIR / "blind_review_v2_manifest.json").write_text(
        json.dumps(
            {
                "seed": BLIND_SHUFFLE_SEED,
                "rows": len(sheet),
                "sheet_sha256": sha256_file(sheet_path),
                "key_sha256": sha256_file(key_path),
                "superseded": "blind_review.csv leaked prompt_version through row order",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    coverage = aggregate["reproducibility_of_auto_checks"]
    print(json.dumps(aggregate["overall"], ensure_ascii=False, indent=2))
    print(
        f"\nauto-check coverage: total={coverage['total_records']} "
        f"applicable={coverage['applicable_records']} checked={coverage['checked_records']} "
        f"skipped={coverage['skipped_records']} mismatches={coverage['mismatches']}"
    )
    mismatches = aggregate["semantic_label_binding"]["fingerprint_mismatches"]
    contract = aggregate["not_answerable_contract"]
    unstored = coverage["applicable_without_stored_checks"]
    print(f"semantic label mismatches: {mismatches}")
    print(f"not_answerable contract violations: {contract['violations']}")
    print(f"applicable records without stored checks: {unstored}")
    print(f"blind review rows: {len(sheet)} (+ separate key file)")
    for name in (
        "aggregate.json",
        "semantic_review.json",
        "blind_review_v2.csv",
        "blind_review_v2_key.csv",
        "blind_review_v2_manifest.json",
    ):
        print(f"wrote {RESULTS_DIR / name}")

    # Fail closed for real: a defect in the data must not exit 0.
    problems = bool(mismatches) or contract["violations"] > 0 or bool(unstored)
    problems = problems or coverage["mismatches"] > 0 or not coverage["coverage_consistent"]
    if problems:
        print("\nREVIEW FAILED: see the counts above")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
