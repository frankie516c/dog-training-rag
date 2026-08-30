"""Validate and freeze the 25-row human-approved training evaluation set."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/eval/queries/owner_questions_training.jsonl")
DEFAULT_CHUNKS = Path("data/scratch/chunks_structure_v1")
DEFAULT_OUTPUT = Path("data/eval/queries/training_api_eval_v1.jsonl")
DEFAULT_AUDIT = Path("data/scratch/training_eval_freeze_audit.json")
SPECIAL = {"oq0035": ["MEDICAL_REFUSAL"], "oq0036": ["UNCERTAIN"]}


def load_chunks(directory: Path) -> dict[str, dict[str, Any]]:
    chunks: dict[str, dict[str, Any]] = {}
    for path in directory.glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                chunks[row["chunk_id"]] = row
    return chunks


def validate(rows: list[dict[str, Any]], chunks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    approved = [row for row in rows if row.get("review_status") == "APPROVED"]
    if len(rows) != 36 or len(approved) != 25:
        raise ValueError(f"expected 36 rows/25 approved, got {len(rows)}/{len(approved)}")
    failures: list[dict[str, str]] = []
    for row in approved:
        anchors = row.get("anchors") or []
        if row.get("coverage") in {"answerable", "partial"}:
            if len(anchors) != 1:
                failures.append({"query_id": row["query_id"], "reason": "expected exactly one anchor"})
                continue
            anchor = anchors[0]
            chunk = chunks.get(anchor.get("chunk_id"))
            quote = str(anchor.get("quote", ""))
            if not chunk or not quote or quote[:100] not in str(chunk.get("text", "")):
                failures.append({"query_id": row["query_id"], "reason": "anchor chunk/quote mismatch"})
        elif anchors:
            failures.append({"query_id": row["query_id"], "reason": "safety/gap row must not carry an answer anchor"})
    if failures:
        raise ValueError(json.dumps({"anchor_failures": failures}, ensure_ascii=False))
    return {
        "schema_version": "training-api-eval-audit-v1",
        "rows": len(rows),
        "approved": len(approved),
        "excluded_rewrite": len(rows) - len(approved),
        "coverage": dict(sorted(Counter(row["coverage"] for row in approved).items())),
        "query_types": dict(sorted(Counter(row["query_type"] for row in approved).items())),
        "anchor_validated": sum(row["coverage"] in {"answerable", "partial"} for row in approved),
        "status": "frozen human-approved rows; 11 REWRITE rows excluded",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line]
    chunks = load_chunks(args.chunks)
    audit = validate(rows, chunks)
    frozen = []
    for row in rows:
        if row.get("review_status") != "APPROVED":
            continue
        copied = dict(row)
        copied["schema_version"] = "training-api-eval-v1"
        copied["split"] = "api_eval"
        copied["expected_api_decisions"] = SPECIAL.get(
            copied["query_id"],
            ["REFUSE"] if copied["coverage"] == "refuse_boundary" else ["ANSWER"],
        )
        frozen.append(copied)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in frozen), encoding="utf-8")
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**audit, "output": str(args.output), "audit": str(args.audit)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
