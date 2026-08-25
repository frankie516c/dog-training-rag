"""Convert LLM-generated questions into the existing eval query schema.

Stage 2 of 2. Reads the raw JSON array produced by the LLM plus the mapping file
written by prepare_synthetic_queries.py, and emits queries in
youtube-eval-query-v1 form so evaluate_youtube_retrieval.py runs unchanged.

Gold spans come from the source chunk's own start_ms/end_ms. They stay valid
across re-chunking because they are absolute timestamps, not chunk ids.

The mapping file this reads is no longer tracked (see prepare_synthetic_queries.py
and .gitignore), so a clean clone cannot rerun this stage without regenerating
stage 1 first. The output it already produced — data/eval/queries/
youtube_synthetic_queries.jsonl, 51 human-reviewed queries — is tracked, so the
eval set itself does not depend on the mapping being present.

Usage:
    uv run python scripts/build_synthetic_queries.py --raw data/eval/queries/_synthetic_raw.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

DEFAULT_MAPPING_PATH = Path("data/eval/queries/_synthetic_mapping.json")
DEFAULT_RAW_PATH = Path("data/eval/queries/_synthetic_raw.json")
DEFAULT_OUTPUT_PATH = Path("data/eval/queries/youtube_synthetic_queries.jsonl")

SCHEMA_VERSION = "youtube-eval-query-v1"
SPLIT = "synthetic"
REVIEW_STATUS = "APPROVED"
REVIEW_REASON = "LLM 생성. 사람 검토 미완 — gold(수기) 세트와 점수를 분리해 보고할 것."
VALID_TYPES = ("direct_lookup", "paraphrase", "symptom_to_solution", "concept")


class BuildError(RuntimeError):
    """Raised when the LLM output or mapping cannot be used."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"invalid JSON in {path}: {exc}") from exc


def load_mapping(path: Path) -> dict[int, dict[str, Any]]:
    payload = load_json(path)
    passages = payload.get("passages") if isinstance(payload, dict) else None
    if not passages:
        raise BuildError(f"no passages in mapping file {path}")
    return {int(entry["passage"]): entry for entry in passages}


def normalise(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise BuildError("LLM output must be a JSON array")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise BuildError(f"item {index} is not an object")
        for key in ("passage", "query_type", "question"):
            if key not in item:
                raise BuildError(f"item {index} missing {key!r}")
        rows.append(item)
    return rows


def build_queries(rows: Sequence[dict[str, Any]], mapping: dict[int, dict[str, Any]],
                  reviewed_at: str) -> tuple[list[dict[str, Any]], list[str]]:
    queries: list[dict[str, Any]] = []
    skipped: list[str] = []
    seen_questions: set[str] = set()
    counter = 0

    for index, row in enumerate(rows, start=1):
        query_type = str(row["query_type"]).strip()
        question = str(row["question"]).strip()

        if query_type == "skip" or not question:
            skipped.append(f"item {index}: marked skip")
            continue
        if query_type not in VALID_TYPES:
            skipped.append(f"item {index}: unknown query_type {query_type!r}")
            continue

        try:
            passage = int(row["passage"])
        except (TypeError, ValueError):
            skipped.append(f"item {index}: passage is not an integer")
            continue
        if passage not in mapping:
            skipped.append(f"item {index}: passage {passage} not in mapping")
            continue

        key = question.replace(" ", "")
        if key in seen_questions:
            skipped.append(f"item {index}: duplicate question")
            continue
        seen_questions.add(key)

        source = mapping[passage]
        counter += 1
        query_id = f"s{counter:03d}"
        queries.append({
            "schema_version": SCHEMA_VERSION,
            "query_id": query_id,
            "split": SPLIT,
            "query_type": query_type,
            "review_status": REVIEW_STATUS,
            "reviewed_at": reviewed_at,
            "review_reason": REVIEW_REASON,
            "question": question,
            "video_id": source["video_id"],
            "relevant_spans": [{
                "span_id": f"{query_id}-s1",
                "start_ms": source["start_ms"],
                "end_ms": source["end_ms"],
                "note": f"생성 원본 chunk #{source['chunk_index']} ({source.get('chapter_title', '')})",
            }],
        })

    return queries, skipped


def write_jsonl(rows: Sequence[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(raw_path: Path, mapping_path: Path, output_path: Path, reviewed_at: str) -> None:
    mapping = load_mapping(mapping_path)
    rows = normalise(load_json(raw_path))
    queries, skipped = build_queries(rows, mapping, reviewed_at)

    if not queries:
        raise BuildError("no usable query was produced")

    write_jsonl(queries, output_path)

    by_type: dict[str, int] = {}
    for query in queries:
        by_type[query["query_type"]] = by_type.get(query["query_type"], 0) + 1

    print(f"queries written: {len(queries)}")
    for query_type in VALID_TYPES:
        print(f"  {query_type}: {by_type.get(query_type, 0)}")
    if skipped:
        print(f"skipped: {len(skipped)}")
        for reason in skipped:
            print(f"  {reason}")
    print(output_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_PATH)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--reviewed-at", default=date.today().isoformat())
    args = parser.parse_args(argv)

    try:
        run(args.raw, args.mapping, args.output, args.reviewed_at)
    except (OSError, BuildError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
