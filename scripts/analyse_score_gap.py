"""Verify headline metrics and analyse the score_gap distribution.

Two jobs in one pass:

1. Regression check. The chunk-size experiment settled on max_chars=480 and
   produced known figures. If a refactor moved ranking, these drift and every
   number in the write-up needs redoing. Expected values are asserted, not
   assumed.

2. Threshold sourcing. A retrieval system that cannot say "no answer here"
   lets the generator invent one. Absolute cosine values drift per query, so
   the gap between the top hit and the corpus mean is the candidate signal.
   This prints its distribution split by whether the query actually succeeded.

Usage:
    uv run python scripts/analyse_score_gap.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_DEV = Path("data/eval/results/retrieval_metrics_dev.json")
DEFAULT_SYNTHETIC = Path("data/eval/results/retrieval_metrics_synthetic.json")

# From the adopted max_chars=480 run. A mismatch means ranking changed.
EXPECTED = {
    "dev": {"hit@1": 0.666667, "mrr@5": 0.736111},
    "synthetic": {"hit@1": 0.490196, "mrr@5": 0.60817},
}

GAP_KEY = "score_gap"


def quantiles(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}

    def at(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[index]

    return {
        "min": ordered[0],
        "p10": at(0.10),
        "p25": at(0.25),
        "median": at(0.50),
        "p75": at(0.75),
        "max": ordered[-1],
    }


def describe(label: str, values: Sequence[float]) -> None:
    if not values:
        print(f"  {label:<22} (없음)")
        return
    q = quantiles(values)
    mean = sum(values) / len(values)
    print(
        f"  {label:<22} n={len(values):>3}  mean={mean:.4f}  "
        f"min={q['min']:.4f}  p25={q['p25']:.4f}  median={q['median']:.4f}  "
        f"p75={q['p75']:.4f}  max={q['max']:.4f}"
    )


def check_metrics(name: str, payload: dict[str, Any]) -> bool:
    metrics = payload["metrics"]
    expected = EXPECTED[name]
    ok = True
    for key, want in expected.items():
        got = metrics[key].get("ratio", metrics[key].get("macro_average"))
        mark = "OK  " if abs(got - want) < 1e-6 else "DRIFT"
        if mark == "DRIFT":
            ok = False
        print(f"  [{mark}] {name:<10} {key:<7} expected={want:<10} got={got}")
    return ok


def collect(payload: dict[str, Any]) -> tuple[list[float], list[float], list[float]]:
    """Gaps split by outcome: rank-1 hit, in top-5 but lower, missed entirely."""
    top1: list[float] = []
    lower: list[float] = []
    missed: list[float] = []
    for entry in payload["per_query"]:
        gap = entry.get(GAP_KEY)
        if gap is None:
            continue
        rank = entry.get("first_relevant_rank")
        if rank == 1:
            top1.append(gap)
        elif rank:
            lower.append(gap)
        else:
            missed.append(gap)
    return top1, lower, missed


def run(dev_path: Path, synthetic_path: Path) -> int:
    payloads = {
        "dev": json.loads(dev_path.read_text(encoding="utf-8")),
        "synthetic": json.loads(synthetic_path.read_text(encoding="utf-8")),
    }

    print("== 회귀 확인 (검색 로직이 그대로인지) ==")
    intact = all(check_metrics(name, payload) for name, payload in payloads.items())
    print()

    if not any(GAP_KEY in entry for p in payloads.values() for entry in p["per_query"]):
        print(f"error: per_query에 {GAP_KEY}가 없습니다. 평가를 다시 실행하세요.", file=sys.stderr)
        return 1

    all_top1: list[float] = []
    all_missed: list[float] = []

    print("== score_gap 분포 (top1 점수 - 코퍼스 평균) ==")
    for name, payload in payloads.items():
        top1, lower, missed = collect(payload)
        all_top1.extend(top1)
        all_missed.extend(missed)
        print(f"[{name}]")
        describe("1위 적중", top1)
        describe("top5 안, 1위 아님", lower)
        describe("top5 밖 (실패)", missed)
        print()

    print("== 임계값 후보 ==")
    if all_top1 and all_missed:
        # A threshold below this keeps every query that actually found its answer.
        floor = min(all_top1)
        # A threshold above this rejects every query whose answer never surfaced.
        ceiling = max(all_missed)
        print(f"  정답 찾은 질문의 최소 gap : {floor:.4f}")
        print(f"  실패한 질문의 최대 gap    : {ceiling:.4f}")
        if floor > ceiling:
            print(f"  → 두 집단이 분리됩니다. 임계값을 {(floor + ceiling) / 2:.4f} 근처로 두면")
            print("     현재 평가셋에서 오탐·미탐 없이 나뉩니다.")
        else:
            print("  → 두 집단이 겹칩니다. 단일 임계값으로는 완전히 나눌 수 없습니다.")
            print("     아래 표에서 감수할 손실을 보고 고르세요.")
            print()
            print("  임계값   유지되는 정답질문   걸러지는 실패질문")
            for step in range(2, 13):
                threshold = step / 100
                kept = sum(1 for g in all_top1 if g >= threshold)
                blocked = sum(1 for g in all_missed if g < threshold)
                print(
                    f"  {threshold:.2f}     {kept:>3} / {len(all_top1):<3}"
                    f"          {blocked:>3} / {len(all_missed)}"
                )
    print()
    print("주의: 이 분포에는 '코퍼스에 답이 없는 질문'이 한 건도 없습니다.")
    print("      전부 정답이 코퍼스에 존재하는 질문입니다. 배변 질문 같은")
    print("      범위 밖 케이스를 평가셋에 넣기 전까지 임계값은 잠정치입니다.")

    return 0 if intact else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", type=Path, default=DEFAULT_DEV)
    parser.add_argument("--synthetic", type=Path, default=DEFAULT_SYNTHETIC)
    args = parser.parse_args(argv)
    try:
        return run(args.dev, args.synthetic)
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
