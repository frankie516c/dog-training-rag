"""Aggregate the prompt-only records and emit the CSV plus the human comparison table.

Aggregates are machine-derived. The comparison table exists because they are not enough:
direction preservation and Korean meaning need a person reading the reviewed claim beside
the generated answer, so the table prints both.

    python -m experiments.prompt_eval_v0.analyze
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from experiments.prompt_eval_v0.fixture import QUESTIONS, cards_for
from experiments.prompt_eval_v0.loading import load_run

RESULTS_DIR = Path(__file__).parent / "results"
VERSIONS = ("v0", "v1", "v2")

CSV_FIELDS = (
    "prompt_version",
    "question_id",
    "kind",
    "run_number",
    "provider_result",
    "answerable",
    "used_card_ids_valid",
    "numbers_outside_evidence",
    "latin_outside_evidence",
    "reversal_hits",
    "procedure_hits",
    "fabricated_content",
    "would_fallback",
    "sentence_count",
    "answer_chars",
    "latency_ms",
)


def load_records(path: Path) -> tuple[dict, list[dict]]:
    """Read records plus config through the shared loader, which fails closed."""

    loaded = load_run(path)
    return loaded.config, loaded.records


def flatten(record: dict) -> dict:
    checks = record.get("auto_checks") or {}
    return {
        "prompt_version": record["prompt_version"],
        "question_id": record["question_id"],
        "kind": record["kind"],
        "run_number": record["run_number"],
        "provider_result": record["provider_result"],
        "answerable": record.get("answerable"),
        "used_card_ids_valid": checks.get("used_card_ids_valid"),
        "numbers_outside_evidence": "|".join(checks.get("numbers_outside_evidence", [])),
        "latin_outside_evidence": "|".join(checks.get("latin_outside_evidence", [])),
        "reversal_hits": "|".join(checks.get("reversal_hits", [])),
        "procedure_hits": "|".join(checks.get("procedure_hits", [])),
        "fabricated_content": checks.get("fabricated_content"),
        "would_fallback": record.get("would_fallback"),
        "sentence_count": checks.get("sentence_count"),
        "answer_chars": checks.get("answer_chars"),
        "latency_ms": record["latency_ms"],
    }


def summarise(records: list[dict]) -> dict[str, dict]:
    by_version: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_version[record["prompt_version"]].append(record)

    summary: dict[str, dict] = {}
    for version in VERSIONS:
        rows = by_version.get(version, [])
        if not rows:
            continue
        accepted = [row for row in rows if row["provider_result"] == "accepted"]
        checked = [row for row in accepted if row.get("auto_checks")]
        clean = [row for row in checked if not row["auto_checks"]["fabricated_content"]]
        reversals = [row for row in checked if row["auto_checks"]["reversal_hits"]]
        latencies = [row["latency_ms"] for row in rows]

        summary[version] = {
            "runs": len(rows),
            "accepted": len(accepted),
            "not_answerable": sum(1 for r in rows if r["provider_result"] == "not_answerable"),
            "invalid": sum(1 for r in rows if r["provider_result"] == "invalid"),
            "error": sum(1 for r in rows if r["provider_result"] == "error"),
            "would_fallback": sum(1 for r in rows if r.get("would_fallback")),
            "auto_clean": len(clean),
            "auto_clean_rate": round(len(clean) / len(checked), 3) if checked else None,
            "reversal_flagged": len(reversals),
            "fabrication_rate": round(
                sum(1 for r in checked if r["auto_checks"]["fabricated_content"]) / len(checked), 3
            )
            if checked
            else None,
            "not_answerable_rate": round(
                sum(1 for r in rows if r["provider_result"] == "not_answerable") / len(rows), 3
            ),
            "invalid_rate": round(
                sum(1 for r in rows if r["provider_result"] == "invalid") / len(rows), 3
            ),
            "used_card_ids_invalid": sum(
                1 for r in checked if not r["auto_checks"]["used_card_ids_valid"]
            ),
            "latency_mean_ms": round(statistics.mean(latencies)) if latencies else None,
            "latency_median_ms": round(statistics.median(latencies)) if latencies else None,
            "answer_chars_median": round(
                statistics.median([r["auto_checks"]["answer_chars"] for r in checked])
            )
            if checked
            else None,
        }
    return summary


def by_kind(records: list[dict]) -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = {}
    kinds = sorted({record["kind"] for record in records})
    for kind in kinds:
        subset = [record for record in records if record["kind"] == kind]
        grouped[kind] = summarise(subset)
    return grouped


def comparison_table(records: list[dict], run_number: int) -> str:
    """Reviewed claim beside the generated answer, for human judgement."""

    questions = {question.question_id: question for question in QUESTIONS}
    lines: list[str] = []
    for question in QUESTIONS:
        claims = [card.claim for card in cards_for(question.scope)]
        lines.append(f"\n### {question.question_id} — {question.message}\n")
        lines.append(f"**확인 사항**: {question.watch_for}\n")
        lines.append("**검토된 claim**\n")
        for claim in claims:
            lines.append(f"> {claim}\n")
        lines.append("")
        lines.append("| 버전 | 결과 | 자동 플래그 | 생성된 답변 |")
        lines.append("|---|---|---|---|")
        for version in VERSIONS:
            row = next(
                (
                    record
                    for record in records
                    if record["question_id"] == question.question_id
                    and record["prompt_version"] == version
                    and record["run_number"] == run_number
                ),
                None,
            )
            if row is None:
                continue
            checks = row.get("auto_checks") or {}
            flags = (
                ", ".join(
                    checks.get("reversal_hits", [])
                    + checks.get("procedure_hits", [])
                    + [f"수치:{n}" for n in checks.get("numbers_outside_evidence", [])]
                    + [f"라틴:{w}" for w in checks.get("latin_outside_evidence", [])]
                )
                or "—"
            )
            answer = (row.get("answer") or "—").replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {version} | {row['provider_result']} | {flags} | {answer} |")
    assert questions
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Aggregate Prompt Eval v0 results.")
    parser.add_argument("--records", type=Path, default=RESULTS_DIR / "prompt_only.jsonl")
    parser.add_argument("--run-for-table", type=int, default=1)
    # Outputs follow the input, so analysing another file cannot overwrite a frozen run.
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    config, records = load_records(args.records)
    summary = summarise(records)
    kind_summary = by_kind(records)

    out_dir = args.out_dir or args.records.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.records.stem
    csv_path = out_dir / f"{stem}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(flatten(record))

    summary_path = out_dir / f"{stem}_summary.json"
    summary_path.write_text(
        json.dumps(
            {"config": config, "overall": summary, "by_kind": kind_summary},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    table_path = out_dir / f"{stem}_comparison_table.md"
    table_path.write_text(
        "# 검토된 claim 대 생성된 답변 (run "
        f"{args.run_for_table})\n\n자동 검사는 어휘만 본다. 방향 보존과 한국어 의미는 "
        "아래 표를 사람이 직접 대조해야 한다.\n" + comparison_table(records, args.run_for_table),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nwrote {csv_path}\nwrote {summary_path}\nwrote {table_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
