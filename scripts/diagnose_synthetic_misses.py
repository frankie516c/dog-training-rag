"""Diagnose synthetic eval misses: is the top hit merely a sibling chunk?

A synthetic gold span points at exactly one source chunk. When several chunks
cover the same topic, retrieval can surface an equally correct neighbour and
still be scored as a miss. This script separates those two cases by comparing
the chapter of the rank-1 result against the chapter of the gold chunk.

Usage:
    uv run python scripts/diagnose_synthetic_misses.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_METRICS = Path("data/eval/results/retrieval_metrics_synthetic.json")


def gold_chapter(entry: dict[str, Any]) -> str | None:
    """Chapter of the highest-ranked relevant chunk, or None if none made top-k."""
    for result in entry["results"]:
        if result.get("relevant"):
            return str(result.get("chapter_title", ""))
    return None


def run(metrics_path: Path) -> None:
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    entries = payload["per_query"]

    same_chapter: list[str] = []
    other_chapter: list[str] = []
    out_of_topk: list[str] = []

    print(f"{'query':>6}  {'verdict':<8}  rank1 chapter / gold chapter")
    print("-" * 78)

    for entry in entries:
        if entry.get("first_relevant_rank") == 1:
            continue

        query_id = entry["query_id"]
        top = entry["results"][0] if entry["results"] else {}
        top_chapter = str(top.get("chapter_title", ""))
        gold = gold_chapter(entry)

        if gold is None:
            verdict = "MISSED"
            out_of_topk.append(query_id)
            gold_label = "(top-k 밖)"
        elif gold == top_chapter:
            verdict = "SAME"
            same_chapter.append(query_id)
            gold_label = gold
        else:
            verdict = "DIFF"
            other_chapter.append(query_id)
            gold_label = gold

        print(f"{query_id:>6}  {verdict:<8}  {top_chapter[:28]} / {gold_label[:28]}")

    total = len(entries)
    top1 = sum(1 for e in entries if e.get("first_relevant_rank") == 1)

    print()
    print(f"queries: {total}   rank-1 적중: {top1}")
    print(f"  SAME   (1위가 정답과 같은 챕터 — 라벨 유일성 문제 가능성): {len(same_chapter)}")
    print(f"  DIFF   (1위가 다른 챕터 — 실제 검색 실패):                {len(other_chapter)}")
    print(f"  MISSED (정답이 top-k 안에 아예 없음):                     {len(out_of_topk)}")
    if same_chapter:
        print(f"  SAME 목록: {', '.join(same_chapter)}")
    if out_of_topk:
        print(f"  MISSED 목록: {', '.join(out_of_topk)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    args = parser.parse_args(argv)
    try:
        run(args.metrics)
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
