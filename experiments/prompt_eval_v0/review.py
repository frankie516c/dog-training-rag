"""Merge automatic screens with the AI-assisted semantic review and emit the review sheets.

Three outputs:
  results/aggregate.json     per-version and per-kind numbers, with denominators
  results/blind_review.csv   one row per response for a person to score independently
  results/semantic_review.json  the AI-assisted judgements, separated from the automatic ones

    python -m experiments.prompt_eval_v0.review
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from experiments.prompt_eval_v0.checks import run_auto_checks
from experiments.prompt_eval_v0.fixture import QUESTIONS, QuestionKind, cards_for
from experiments.prompt_eval_v0.semantic_review import (
    CONCERN_JUDGEMENTS,
    CRITICAL_JUDGEMENTS,
    KNOWN_FALSE_POSITIVES,
    RESISTED_WHILE_ANSWERING,
    critical_for,
    expected_answerable,
)

RESULTS_DIR = Path(__file__).parent / "results"
RECORDS_PATH = RESULTS_DIR / "prompt_only.jsonl"
VERSIONS = ("v0", "v1", "v2")

BLIND_FIELDS = (
    "row_id",
    "question_id",
    "run_number",
    "kind",
    "question",
    "evidence_claims",
    "model_answer",
    "used_card_ids",
    "auto_provider_result",
    "auto_flags",
    "auto_numbers_outside_evidence",
    "auto_latin_outside_evidence",
    # Columns for a person to fill in.
    "human_direction_preserved",
    "human_beyond_evidence",
    "human_directness",
    "human_readability",
    "human_note",
    # Kept last so it can be hidden while scoring.
    "prompt_version_hidden",
)


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
    """Recompute the stored screens with the current code.

    The runner imported checks.py before a later lint-only edit; recomputing proves the
    edit changed layout, not results.
    """

    mismatched = []
    for record in records:
        stored = record.get("auto_checks")
        if not stored or not record.get("answer"):
            continue
        question = next(q for q in QUESTIONS if q.question_id == record["question_id"])
        fresh = run_auto_checks(
            record["answer"],
            cards=cards_for(question.scope),
            used_card_ids=record["used_card_ids"],
            allow_procedure=question.kind is QuestionKind.GUIDANCE_HOW_TO,
        ).as_dict()
        if fresh != stored:
            mismatched.append(
                {
                    "key": [record["prompt_version"], record["question_id"], record["run_number"]],
                    "stored": stored,
                    "recomputed": fresh,
                }
            )
    return {"checked": len(records), "mismatched": mismatched}


def summarise(rows: list[dict]) -> dict:
    total = len(rows)
    accepted = [row for row in rows if row["provider_result"] == "accepted"]
    answered_checks = [row["auto_checks"] for row in accepted if row.get("auto_checks")]

    answerable_correct = sum(
        1
        for row in rows
        if (row["provider_result"] == "accepted") is expected_answerable(row["question_id"])
    )
    overreach = [row for row in rows if row["kind"] == QuestionKind.OVERREACH.value]
    complied = [
        row
        for row in overreach
        if row["provider_result"] == "accepted"
        and (row["question_id"], row["prompt_version"], row["run_number"])
        not in RESISTED_WHILE_ANSWERING
    ]
    critical = [
        row
        for row in rows
        if critical_for(row["question_id"], row["prompt_version"], row["run_number"])
    ]
    latencies = [row["latency_ms"] for row in rows]

    return {
        "total_runs": total,
        "accepted": len(accepted),
        "not_answerable": sum(1 for row in rows if row["provider_result"] == "not_answerable"),
        "invalid": sum(1 for row in rows if row["provider_result"] == "invalid"),
        "error": sum(1 for row in rows if row["provider_result"] == "error"),
        "fallback": sum(1 for row in rows if row.get("would_fallback")),
        "answerable_correct": f"{answerable_correct}/{total}",
        "answerable_accuracy": round(answerable_correct / total, 3) if total else None,
        "adversarial_resisted": f"{len(overreach) - len(complied)}/{len(overreach)}",
        "critical_failures": len(critical),
        "critical_detail": [
            {
                "question_id": row["question_id"],
                "run_number": row["run_number"],
                "kinds": [
                    kind.value
                    for kind in critical_for(
                        row["question_id"], row["prompt_version"], row["run_number"]
                    )
                ],
            }
            for row in critical
        ],
        "used_card_ids_valid": f"{sum(1 for c in answered_checks if c['used_card_ids_valid'])}"
        f"/{len(answered_checks)}",
        "numbers_outside_evidence": sum(
            1 for c in answered_checks if c["numbers_outside_evidence"]
        ),
        "latin_outside_evidence": sum(1 for c in answered_checks if c["latin_outside_evidence"]),
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


def build_blind_sheet(records: list[dict]) -> list[dict]:
    questions = {question.question_id: question for question in QUESTIONS}
    rows = []
    for index, record in enumerate(
        sorted(records, key=lambda r: (r["question_id"], r["run_number"], r["prompt_version"])), 1
    ):
        question = questions[record["question_id"]]
        checks = record.get("auto_checks") or {}
        rows.append(
            {
                "row_id": f"R{index:03d}",
                "question_id": record["question_id"],
                "run_number": record["run_number"],
                "kind": record["kind"],
                "question": question.message,
                "evidence_claims": " || ".join(card.claim for card in cards_for(question.scope)),
                "model_answer": record.get("answer") or "",
                "used_card_ids": " ".join(record.get("used_card_ids") or []),
                "auto_provider_result": record["provider_result"],
                "auto_flags": " ".join(
                    checks.get("reversal_hits", []) + checks.get("procedure_hits", [])
                ),
                "auto_numbers_outside_evidence": " ".join(
                    checks.get("numbers_outside_evidence", [])
                ),
                "auto_latin_outside_evidence": " ".join(checks.get("latin_outside_evidence", [])),
                "human_direction_preserved": "",
                "human_beyond_evidence": "",
                "human_directness": "",
                "human_readability": "",
                "human_note": "",
                "prompt_version_hidden": record["prompt_version"],
            }
        )
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    records = load_records()

    by_version = defaultdict(list)
    for record in records:
        by_version[record["prompt_version"]].append(record)

    aggregate = {
        "reproducibility_of_auto_checks": verify_auto_checks_reproduce(records),
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

    sheet = build_blind_sheet(records)
    with (RESULTS_DIR / "blind_review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BLIND_FIELDS)
        writer.writeheader()
        writer.writerows(sheet)

    print(json.dumps(aggregate["overall"], ensure_ascii=False, indent=2))
    print(
        f"\nauto-check reproducibility: {aggregate['reproducibility_of_auto_checks']['checked']} "
        f"checked, {len(aggregate['reproducibility_of_auto_checks']['mismatched'])} mismatched"
    )
    print(f"blind review rows: {len(sheet)}")
    for name in ("aggregate.json", "semantic_review.json", "blind_review.csv"):
        print(f"wrote {RESULTS_DIR / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
