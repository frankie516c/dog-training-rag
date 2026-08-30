"""Run the frozen owner-training candidate set against the live local API.

Each completed response is persisted immediately, so an interrupted Gemma run
resumes rather than discarding completed examples.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/eval/queries/training_api_eval_candidate_v1.jsonl")
DEFAULT_OUT = Path("data/scratch/training_api_eval_candidate_v1")


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("error") is None]
    answerable = [row for row in completed if row["coverage"] == "answerable"]
    latencies = sorted(row["elapsed_seconds"] for row in completed)
    return {
        "schema_version": "training-api-eval-result-v1",
        "completed": len(completed),
        "errors": len(rows) - len(completed),
        "decision_match_rate": (
            sum(row["decision_match"] for row in completed) / len(completed) if completed else 0
        ),
        "anchor_hit_at_k": (
            sum(row["anchor_hit"] for row in answerable) / len(answerable) if answerable else 0
        ),
        "answerable_generated_rate": (
            sum(row["generated"] for row in answerable) / len(answerable) if answerable else 0
        ),
        "decision_counts": dict(sorted(Counter(
            row.get("response", {}).get("decision", "ERROR") for row in rows
        ).items())),
        "mean_latency_seconds": sum(latencies) / len(latencies) if latencies else 0,
        "p95_latency_seconds": latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/chat")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    questions = load_jsonl(args.input)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.out_dir / "raw_outputs"
    raw_dir.mkdir(exist_ok=True)
    result_path = args.out_dir / "results.jsonl"
    prior = load_jsonl(result_path) if result_path.exists() else []
    completed_ids = {row["query_id"] for row in prior}
    pending = [row for row in questions if row["query_id"] not in completed_ids]
    if args.limit is not None:
        pending = pending[:args.limit]

    with result_path.open("a", encoding="utf-8") as result_file:
        for index, question in enumerate(pending, start=1):
            started = time.perf_counter()
            try:
                response = post_json(args.endpoint, {"question": question["question"], "top_k": 4}, args.timeout)
                evidence_ids = {card["chunk_id"] for card in response.get("evidence", [])}
                anchors = set(question.get("anchor_chunk_ids", []))
                record = {
                    "query_id": question["query_id"],
                    "question": question["question"],
                    "coverage": question["coverage"],
                    "expected_api_decisions": question["expected_api_decisions"],
                    "response": response,
                    "decision_match": response.get("decision") in question["expected_api_decisions"],
                    "anchor_hit": bool(anchors & evidence_ids) if anchors else None,
                    "generated": bool(response.get("generated")),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "error": None,
                }
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                record = {
                    "query_id": question["query_id"],
                    "question": question["question"],
                    "coverage": question["coverage"],
                    "expected_api_decisions": question["expected_api_decisions"],
                    "response": None,
                    "decision_match": False,
                    "anchor_hit": None,
                    "generated": False,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "error": str(exc)[:300],
                }
            result_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            result_file.flush()
            (raw_dir / f"{question['query_id']}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps({"completed": index, "total_pending": len(pending), "query_id": question["query_id"], "decision": (record.get("response") or {}).get("decision", "ERROR")}, ensure_ascii=False), flush=True)

    all_rows = load_jsonl(result_path)
    result_summary = summary(all_rows)
    (args.out_dir / "summary.json").write_text(
        json.dumps(result_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result_summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
