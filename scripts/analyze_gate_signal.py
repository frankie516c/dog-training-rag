"""Does anything the answer gate can see separate a retrieval hit from a miss?

Re-analysis only — no retrieval, no generation, no database.  It reads the two
artifacts the 0827 runs already produced and asks one question: is there a
quantity derivable from the E5 scores that would let `RuntimeRetriever.gate`
say UNCERTAIN on the 52.6% of answerable questions whose gold anchor is not in
the top 4?

reports/retrieval_gate_signal_0828.md records the answer (no) and why the
best-looking threshold is overfitting rather than signal.

    uv run python scripts/analyze_gate_signal.py
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics as st
import sys
from pathlib import Path

DEFAULT_RERANKING = Path("data/scratch/retrieval_reranking_0827_v5/results.json")
DEFAULT_RAW_OUTPUTS = Path("data/scratch/training_api_eval_v1/raw_outputs")


def load_rows(reranking: Path, raw_outputs: Path) -> list[dict]:
    """One row per answerable frozen query, with every gate-visible quantity."""
    ranks: dict[str, int | None] = {}
    payload = json.loads(reranking.read_text(encoding="utf-8"))
    for detail in payload["methods"]["dense"]["details"]:
        if detail["coverage"] == "answerable":
            ranks[detail["query_id"]] = detail["anchor_rank"]

    rows: list[dict] = []
    for path in sorted(glob.glob(str(raw_outputs / "*.json"))):
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        if record["coverage"] != "answerable":
            continue
        evidence = record["response"].get("evidence") or []
        if len(evidence) < 4:
            continue
        scores = [item["score"] for item in evidence]
        documents = [item["document_id"] for item in evidence]
        rows.append({
            "query_id": record["query_id"],
            # anchor_rank <= 4 — the same hit definition the 0827 report used.
            "hit": bool(record["anchor_hit"]),
            "anchor_rank": ranks.get(record["query_id"]),
            "top_score": scores[0],
            "margin_topk": scores[0] - scores[3],
            "top1_top2": scores[0] - scores[1],
            "distinct_documents": len(set(documents)),
            "score_spread": st.pstdev(scores),
        })
    return rows


def separability(rows: list[dict], key: str) -> dict:
    """Best accuracy any single threshold on `key` can reach — fitted in-sample.

    Both directions are tried, so a "good" number here can mean the rule points
    the opposite way from any confidence story.  That is worth seeing, not
    hiding: it is how you tell a fitted threshold from a signal.
    """
    hit = [row[key] for row in rows if row["hit"]]
    miss = [row[key] for row in rows if not row["hit"]]
    best_accuracy, best_threshold, best_direction = 0.0, None, ""
    for threshold in sorted({round(value, 5) for value in hit + miss}):
        above = (sum(1 for v in hit if v >= threshold)
                 + sum(1 for v in miss if v < threshold)) / len(rows)
        below = (sum(1 for v in hit if v < threshold)
                 + sum(1 for v in miss if v >= threshold)) / len(rows)
        for accuracy, direction in ((above, ">="), (below, "<")):
            if accuracy > best_accuracy:
                best_accuracy, best_threshold, best_direction = accuracy, threshold, direction
    return {
        "hit_range": (min(hit), max(hit)), "hit_median": st.median(hit),
        "miss_range": (min(miss), max(miss)), "miss_median": st.median(miss),
        # Disjoint ranges would mean a threshold exists at all.  They never are.
        "separable": min(hit) > max(miss) or max(hit) < min(miss),
        "best_threshold": best_threshold, "best_direction": best_direction,
        "best_accuracy": best_accuracy,
        "majority_baseline": max(len(hit), len(miss)) / len(rows),
    }


SIGNALS = (
    ("top_score", "top_score (게이트가 0.70 으로 보는 값)"),
    ("margin_topk", "margin = top1 - top4 (계산만 하고 안 쓰는 값)"),
    ("top1_top2", "top1 - top2"),
    ("distinct_documents", "top-4 안의 서로 다른 문서 수"),
    ("score_spread", "top-4 점수 편차"),
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reranking", type=Path, default=DEFAULT_RERANKING)
    parser.add_argument("--raw-outputs", type=Path, default=DEFAULT_RAW_OUTPUTS)
    parser.add_argument("--json", action="store_true", help="사람이 읽는 표 대신 JSON")
    args = parser.parse_args()

    rows = load_rows(args.reranking, args.raw_outputs)
    if not rows:
        raise SystemExit("answerable 행을 못 찾았다 — data/scratch 산출물이 있는지 확인할 것")
    report = {
        "schema_version": "gate-signal-v1",
        "answerable": len(rows),
        "hits": sum(row["hit"] for row in rows),
        "top_score_range": (min(r["top_score"] for r in rows), max(r["top_score"] for r in rows)),
        "signals": {key: separability(rows, key) for key, _ in SIGNALS},
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    low, high = report["top_score_range"]
    print(f"answerable {report['answerable']}건 / hit {report['hits']}건")
    print(f"top_score 관측 범위 {low:.4f} ~ {high:.4f} "
          f"— 임계값 0.70 이 걸리는 횟수 {sum(1 for r in rows if r['top_score'] < 0.70)}건\n")
    for key, label in SIGNALS:
        s = report["signals"][key]
        print(f"{label}")
        print(f"  hit  중앙={s['hit_median']:.4f} [{s['hit_range'][0]:.4f}~{s['hit_range'][1]:.4f}]")
        print(f"  miss 중앙={s['miss_median']:.4f} [{s['miss_range'][0]:.4f}~{s['miss_range'][1]:.4f}]"
              f"  -> {'분리 가능' if s['separable'] else '**겹침**'}")
        print(f"  in-sample 최선 {s['best_direction']}{s['best_threshold']} -> "
              f"{s['best_accuracy']:.1%} (다수 기준선 {s['majority_baseline']:.1%})\n")


if __name__ == "__main__":
    main()
