"""Compare refusal signals: corpus-mean gap vs rank-internal margin.

The gap (top1 - corpus mean) puts out-of-corpus queries inside the answerable
distribution, so a cutoff on it costs a lot of good answers. The margin
(top1 - top2) looked far more separable in the probe. This measures both
against the same three populations and prints the trade-off for each, so the
threshold is chosen from data rather than from the two queries that started it.

Populations:
  found      answerable, retrieval surfaced the gold chunk
  missed     answerable, gold chunk never surfaced
  absent     the corpus cannot answer it at all

Usage:
    uv run python scripts/analyse_refusal_signals.py
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
DEFAULT_METRICS = (
    Path("data/eval/results/retrieval_metrics_dev.json"),
    Path("data/eval/results/retrieval_metrics_synthetic.json"),
)
MODEL_NAME = "intfloat/multilingual-e5-base"
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "

SIGNALS = (
    ("score_gap", "gap (top1 - 코퍼스 평균)"),
    ("top1_minus_top2", "margin (top1 - top2)"),
)


class AnalysisError(RuntimeError):
    """Raised when inputs are missing or malformed."""


def load_corpus(chunk_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(chunk_dir / "*.jsonl"))):
        with open(path, encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    corpus = [row for row in rows if row.get("embedding_eligible")]
    if not corpus:
        raise AnalysisError(f"no embedding_eligible chunk under {chunk_dir}")
    return corpus


def answerable(metrics_paths: Sequence[Path]) -> dict[str, dict[str, list[float]]]:
    """Signal values for answerable queries, split by whether the gold surfaced."""
    buckets: dict[str, dict[str, list[float]]] = {
        key: {"found": [], "missed": []} for key, _ in SIGNALS
    }
    seen = False
    for path in metrics_paths:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for entry in payload.get("per_query", []):
            outcome = "found" if entry.get("first_relevant_rank") else "missed"
            for key, _ in SIGNALS:
                value = entry.get(key)
                if value is not None:
                    buckets[key][outcome].append(value)
                    seen = True
    if not seen:
        raise AnalysisError(
            "metrics에 신호 필드가 없습니다. margin 추가 후 평가를 다시 실행하세요."
        )
    return buckets


def probe_absent(queries_path: Path, corpus: Sequence[dict[str, Any]]) -> dict[str, list[float]]:
    payload = json.loads(queries_path.read_text(encoding="utf-8"))
    queries = payload.get("queries") or []
    if not queries:
        raise AnalysisError(f"no queries in {queries_path}")

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME, device="cpu")
    matrix = model.encode(
        [PASSAGE_PREFIX + row["text"] for row in corpus], normalize_embeddings=True
    )

    values: dict[str, list[float]] = {key: [] for key, _ in SIGNALS}
    for query in queries:
        vector = model.encode(QUERY_PREFIX + query["question"], normalize_embeddings=True)
        scores = sorted((matrix @ vector).tolist(), reverse=True)
        values["score_gap"].append(scores[0] - sum(scores) / len(scores))
        values["top1_minus_top2"].append(scores[0] - scores[1])
    return values


def summarise(label: str, values: Sequence[float]) -> None:
    if not values:
        print(f"  {label:<10} (없음)")
        return
    print(
        f"  {label:<10} n={len(values):>3}  min={min(values):.4f}  "
        f"median={statistics.median(values):.4f}  max={max(values):.4f}"
    )


def tradeoff(found: Sequence[float], absent: Sequence[float]) -> None:
    """A threshold is only interesting between the absent max and the found max."""
    if not found or not absent:
        return
    print()
    print("  임계값    답 있는 질문 통과      범위 밖 차단")
    ceiling = max(absent)
    steps = sorted({round(v, 4) for v in (*absent, ceiling * 1.05)})
    for threshold in steps:
        kept = sum(1 for v in found if v >= threshold)
        blocked = sum(1 for v in absent if v < threshold)
        mark = "  ← 범위 밖 전부 차단" if blocked == len(absent) else ""
        print(
            f"  {threshold:.4f}    {kept:>3} / {len(found):<3} ({kept / len(found):>4.0%})"
            f"       {blocked:>3} / {len(absent)}{mark}"
        )


def run(queries_path: Path, chunk_dir: Path, metrics_paths: Sequence[Path]) -> int:
    buckets = answerable(metrics_paths)
    absent = probe_absent(queries_path, load_corpus(chunk_dir))

    for key, title in SIGNALS:
        print(f"== {title} ==")
        summarise("정답 찾음", buckets[key]["found"])
        summarise("못 찾음", buckets[key]["missed"])
        summarise("범위 밖", absent[key])
        tradeoff(buckets[key]["found"], absent[key])
        print()

    print("읽는 법: 범위 밖을 전부 막으면서 답 있는 질문을 가장 많이 남기는 임계값이")
    print("         그 신호의 최선입니다. 두 신호의 최선을 비교해 고르세요.")
    print("         범위 밖 14건은 사람이 주제 부재를 판정한 것이며 전수 검토는 아닙니다.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--metrics", type=Path, nargs="*", default=list(DEFAULT_METRICS))
    args = parser.parse_args(argv)
    try:
        return run(args.queries, args.chunk_dir, args.metrics)
    except (OSError, AnalysisError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
