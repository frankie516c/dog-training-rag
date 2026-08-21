"""Measure similarity signals for questions the corpus cannot answer.

These queries have no gold span by construction, so Hit@k and MRR do not apply.
What matters is whether any signal separates them from queries the corpus can
answer — that is what a refusal threshold would key on.

Prints, per query, the same statistics the evaluator records for real queries
(top1, corpus mean, gap) plus rank-internal margins, then compares the
distribution against the answerable sets so a threshold can be picked against
both populations rather than one.

Usage:
    uv run python scripts/probe_out_of_corpus.py
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_QUERIES = Path("data/eval/queries/out_of_corpus_queries.json")
DEFAULT_CHUNK_DIR = Path("data/processed/youtube/chunks")
DEFAULT_COMPARE = (
    Path("data/eval/results/retrieval_metrics_dev.json"),
    Path("data/eval/results/retrieval_metrics_synthetic.json"),
)
MODEL_NAME = "intfloat/multilingual-e5-base"
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


class ProbeError(RuntimeError):
    """Raised when inputs are missing or malformed."""


def load_corpus(chunk_dir: Path) -> list[dict[str, Any]]:
    paths = sorted(glob.glob(str(chunk_dir / "*.jsonl")))
    if not paths:
        raise ProbeError(f"no chunk files under {chunk_dir}")
    rows: list[dict[str, Any]] = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    corpus = [row for row in rows if row.get("embedding_eligible")]
    if not corpus:
        raise ProbeError("no embedding_eligible chunk in the corpus")
    return corpus


def load_queries(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    queries = payload.get("queries")
    if not queries:
        raise ProbeError(f"no queries in {path}")
    return queries, payload


def answerable_gaps(paths: Sequence[Path]) -> dict[str, list[float]]:
    """score_gap of answerable queries, split by whether retrieval found the answer."""
    found: list[float] = []
    missed: list[float] = []
    for path in paths:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for entry in payload.get("per_query", []):
            gap = entry.get("score_gap")
            if gap is None:
                continue
            (found if entry.get("first_relevant_rank") else missed).append(gap)
    return {"found": found, "missed": missed}


def run(queries_path: Path, chunk_dir: Path, compare_paths: Sequence[Path]) -> int:
    queries, payload = load_queries(queries_path)
    corpus = load_corpus(chunk_dir)

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME, device="cpu")
    matrix = model.encode(
        [PASSAGE_PREFIX + row["text"] for row in corpus], normalize_embeddings=True
    )

    print(f"corpus: eligible chunk {len(corpus)}개 / 질문 {len(queries)}건")
    print()
    header = f"{'id':>5}  {'주제':<12} {'top1':>7} {'mean':>7} {'gap':>7} {'1-2위':>7} {'1-5위':>7}"
    print(header)
    print("-" * len(header))

    gaps: list[float] = []
    margins: list[float] = []

    for query in queries:
        vector = model.encode(QUERY_PREFIX + query["question"], normalize_embeddings=True)
        scores = sorted((matrix @ vector).tolist(), reverse=True)
        top1 = scores[0]
        mean = sum(scores) / len(scores)
        gap = top1 - mean
        margin_2 = top1 - scores[1]
        margin_5 = top1 - scores[min(4, len(scores) - 1)]
        gaps.append(gap)
        margins.append(margin_2)
        print(
            f"{query['query_id']:>5}  {query.get('topic', ''):<12} "
            f"{top1:7.4f} {mean:7.4f} {gap:7.4f} {margin_2:7.4f} {margin_5:7.4f}"
        )

    print()
    print(f"범위 밖 질문 gap    : min={min(gaps):.4f}  median={statistics.median(gaps):.4f}  max={max(gaps):.4f}")
    print(f"범위 밖 질문 1-2위차 : min={min(margins):.4f}  median={statistics.median(margins):.4f}  max={max(margins):.4f}")
    print()

    reference = answerable_gaps(compare_paths)
    if reference["found"]:
        found = reference["found"]
        print("== 답이 있는 질문과 비교 (gap 기준) ==")
        print(
            f"  정답 찾음  n={len(found):>3}  min={min(found):.4f}  "
            f"median={statistics.median(found):.4f}  max={max(found):.4f}"
        )
        if reference["missed"]:
            missed = reference["missed"]
            print(
                f"  못 찾음    n={len(missed):>3}  min={min(missed):.4f}  "
                f"median={statistics.median(missed):.4f}  max={max(missed):.4f}"
            )
        print(f"  범위 밖    n={len(gaps):>3}  min={min(gaps):.4f}  "
              f"median={statistics.median(gaps):.4f}  max={max(gaps):.4f}")
        print()
        print("  임계값   답 있는 질문 통과   범위 밖 질문 차단")
        for step in range(2, 8):
            threshold = step / 100
            kept = sum(1 for g in found if g >= threshold)
            blocked = sum(1 for g in gaps if g < threshold)
            print(
                f"  {threshold:.2f}     {kept:>3} / {len(found):<3}"
                f"           {blocked:>3} / {len(gaps)}"
            )
    else:
        print("비교용 metrics를 찾지 못했습니다. 평가를 먼저 실행하세요.")

    print()
    print("주의: 범위 밖 판정 근거는 사람이 적은 topic_absent_because이며")
    print("      키워드·유사도 확인을 거쳤지만 코퍼스 전수 검토는 아닙니다.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--compare", type=Path, nargs="*", default=list(DEFAULT_COMPARE))
    args = parser.parse_args(argv)
    try:
        return run(args.queries, args.chunk_dir, args.compare)
    except (OSError, ProbeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
