"""Cross-encoder reranking over the serving corpus, measured offline.

reports/retrieval_reranking_0827.md rejected BM25, RRF and lexical reranking and
recorded that a cross-encoder was never in scope, so the rejection did not cover
it.  This script closes that gap, and answers a second question the 0827 run did
not ask: reports/retrieval_gate_signal_0828.md showed that nothing derivable
from the E5 cosine separates a retrieval hit from a miss, which leaves the
answer gate unable to say UNCERTAIN when all four chunks are wrong.  A
cross-encoder scores the pair jointly instead of comparing two independent
encodings, so its score is a candidate for that job.  Both are measured here.

**No database.**  The 14 serving documents' chunks are on disk under
data/scratch/chunks_structure_v1/, and encoding them reproduces the published
dense baseline exactly (Hit@1 21.1% / Hit@4 47.4% / MRR@4 0.307), which is
asserted at startup — a run that cannot reproduce it is not comparable and stops.

    uv run python scripts/compare_cross_encoder_rerank.py
    uv run python scripts/compare_cross_encoder_rerank.py --model BAAI/bge-reranker-base
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from pgvector_runtime import RuntimeRetriever  # noqa: E402

DEFAULT_CHUNKS = REPO / "data/scratch/chunks_structure_v1"
DEFAULT_EVAL = REPO / "data/eval/queries/training_api_eval_v1.jsonl"
DEFAULT_SERVING = REPO / "config/serving_corpus_v1.json"
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"

#: reports/retrieval_reranking_0827.md, dense row.  Reproducing these is the
#: precondition for comparing anything against them.
PUBLISHED_DENSE = {"eligible_rows": 65, "hit_at_1": 0.2105, "hit_at_4": 0.4737, "mrr_at_4": 0.3070}


def load_chunks(chunks_dir: Path, serving: Path) -> list[dict]:
    document_ids = json.loads(serving.read_text(encoding="utf-8"))["document_ids"]
    rows: list[dict] = []
    for document_id in document_ids:
        path = chunks_dir / f"{document_id}.jsonl"
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    # The serving retriever drops extraction artifacts at query time, so the
    # candidate pool here has to drop the same ones or the pools differ.
    return [row for row in rows if RuntimeRetriever.is_retrieval_eligible(row["text"])]


def load_answerable(eval_path: Path) -> list[dict]:
    rows = [json.loads(line) for line in eval_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("coverage") == "answerable"]


def metrics(ranks: list[int | None], n: int) -> dict:
    """Hit@k and MRR over the same denominator the 0827 report used (all rows)."""
    return {
        "hit_at_1": sum(1 for r in ranks if r == 1) / n,
        "hit_at_4": sum(1 for r in ranks if r and r <= 4) / n,
        "mrr_at_4": sum(1 / r for r in ranks if r and r <= 4) / n,
        "mrr_at_50": sum(1 / r for r in ranks if r and r <= 50) / n,
        "mean_rank": st.mean([r for r in ranks if r]) if any(ranks) else None,
    }


def separability(scores_hit: list[float], scores_miss: list[float]) -> dict:
    """Does the reranker's own score tell a hit from a miss?

    Reported the same way reports/retrieval_gate_signal_0828.md reported the E5
    quantities, so the two are directly comparable — including the in-sample
    best threshold, which is an upper bound and not a proposal.
    """
    if not scores_hit or not scores_miss:
        return {"separable": None}
    total = len(scores_hit) + len(scores_miss)
    best = (0.0, None)
    for threshold in sorted({round(v, 4) for v in scores_hit + scores_miss}):
        accuracy = (sum(1 for v in scores_hit if v >= threshold)
                    + sum(1 for v in scores_miss if v < threshold)) / total
        if accuracy > best[0]:
            best = (accuracy, threshold)
    return {
        "hit_median": st.median(scores_hit), "hit_range": (min(scores_hit), max(scores_hit)),
        "miss_median": st.median(scores_miss), "miss_range": (min(scores_miss), max(scores_miss)),
        "separable": min(scores_hit) > max(scores_miss),
        "best_accuracy": best[0], "best_threshold": best[1],
        "majority_baseline": max(len(scores_hit), len(scores_miss)) / total,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--candidates", type=int, default=50, help="리랭크할 dense 상위 N (0827 과 같은 50)")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--input", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--serving", type=Path, default=DEFAULT_SERVING)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--skip-baseline-check", action="store_true")
    args = parser.parse_args()

    import numpy as np
    from sentence_transformers import CrossEncoder, SentenceTransformer

    chunks = load_chunks(args.chunks, args.serving)
    rows = load_answerable(args.input)
    n = len(rows)
    print(f"retrieval-eligible 청크 {len(chunks)}개 / answerable {n}건")

    encoder = SentenceTransformer(EMBEDDING_MODEL)
    passages = encoder.encode(["passage: " + c["text"] for c in chunks],
                              normalize_embeddings=True, batch_size=16, show_progress_bar=False)
    queries = encoder.encode(["query: " + r["question"] for r in rows],
                             normalize_embeddings=True, batch_size=16, show_progress_bar=False)
    sims = queries @ passages.T

    dense_ranks: list[int | None] = []
    candidates: list[list[int]] = []
    for i, row in enumerate(rows):
        order = list(np.argsort(-sims[i]))
        anchors = set(row.get("anchor_chunk_ids") or [])
        dense_ranks.append(next((j + 1 for j, idx in enumerate(order) if chunks[idx]["chunk_id"] in anchors), None))
        candidates.append(order[: args.candidates])

    dense = metrics(dense_ranks, n)
    print(f"\ndense    Hit@1 {dense['hit_at_1']:.1%}  Hit@4 {dense['hit_at_4']:.1%}  MRR@4 {dense['mrr_at_4']:.3f}")
    drift = [k for k, v in PUBLISHED_DENSE.items()
             if k != "eligible_rows" and abs(dense[k] - v) > 0.005]
    if len(chunks) != PUBLISHED_DENSE["eligible_rows"]:
        drift.append("eligible_rows")
    if drift and not args.skip_baseline_check:
        raise SystemExit(
            f"0827 dense 기준선을 재현하지 못했다 ({', '.join(drift)}). 비교가 성립하지 않으므로 중단한다.\n"
            "  코퍼스·청킹·임베딩 모델 중 무엇이 바뀌었는지 먼저 확인할 것."
        )

    started = time.perf_counter()
    reranker = CrossEncoder(args.model)
    load_seconds = time.perf_counter() - started

    rerank_ranks: list[int | None] = []
    top_scores_hit: list[float] = []
    top_scores_miss: list[float] = []
    details: list[dict] = []
    started = time.perf_counter()
    for i, row in enumerate(rows):
        pool = candidates[i]
        pairs = [(row["question"], chunks[idx]["text"]) for idx in pool]
        scores = reranker.predict(pairs, batch_size=16, show_progress_bar=False)
        order = [pool[j] for j in np.argsort(-np.asarray(scores))]
        anchors = set(row.get("anchor_chunk_ids") or [])
        rank = next((j + 1 for j, idx in enumerate(order) if chunks[idx]["chunk_id"] in anchors), None)
        rerank_ranks.append(rank)
        top_score = float(max(scores))
        (top_scores_hit if rank and rank <= 4 else top_scores_miss).append(top_score)
        details.append({
            "query_id": row["query_id"], "query_type": row["query_type"],
            "dense_rank": dense_ranks[i], "rerank_rank": rank, "rerank_top_score": top_score,
        })
    rerank_seconds = time.perf_counter() - started
    rerank = metrics(rerank_ranks, n)

    # 0827 의 탈락 기준: 기존 dense 정답을 top-4 밖으로 밀어내면 안 된다.
    regressions = [d["query_id"] for d in details
                   if d["dense_rank"] and d["dense_rank"] <= 4 and not (d["rerank_rank"] and d["rerank_rank"] <= 4)]
    gains = [d["query_id"] for d in details
             if d["rerank_rank"] and d["rerank_rank"] <= 4 and not (d["dense_rank"] and d["dense_rank"] <= 4)]

    print(f"rerank   Hit@1 {rerank['hit_at_1']:.1%}  Hit@4 {rerank['hit_at_4']:.1%}  MRR@4 {rerank['mrr_at_4']:.3f}"
          f"   ({args.model}, top-{args.candidates})")
    print(f"\n{'query':<9}{'type':<20}{'dense':>7}{'rerank':>8}   변화")
    for d in sorted(details, key=lambda x: x["query_id"]):
        before, after = d["dense_rank"], d["rerank_rank"]
        mark = ("+ 새로 들어옴" if d["query_id"] in gains
                else "- 밀려남" if d["query_id"] in regressions else "")
        print(f"{d['query_id']:<9}{d['query_type']:<20}{str(before):>7}{str(after):>8}   {mark}")
    print(f"\n새로 top-4 에 든 것 {len(gains)}건 {gains}")
    print(f"top-4 밖으로 밀린 것 {len(regressions)}건 {regressions}")

    gate = separability(top_scores_hit, top_scores_miss)
    print(f"\n게이트 신호 — 리랭커 top 점수가 hit/miss 를 가르는가")
    if gate.get("separable") is None:
        print("  한쪽이 비어 판정 불가")
    else:
        print(f"  hit  중앙={gate['hit_median']:.4f} [{gate['hit_range'][0]:.4f}~{gate['hit_range'][1]:.4f}]")
        print(f"  miss 중앙={gate['miss_median']:.4f} [{gate['miss_range'][0]:.4f}~{gate['miss_range'][1]:.4f}]")
        print(f"  -> {'분리 가능' if gate['separable'] else '**겹침**'}"
              f" / in-sample 최선 {gate['best_accuracy']:.1%} (기준선 {gate['majority_baseline']:.1%})")

    payload = {
        "schema_version": "cross-encoder-rerank-v1", "model": args.model,
        "candidates": args.candidates, "eligible_rows": len(chunks), "answerable": n,
        "dense": dense, "rerank": rerank, "gains": gains, "regressions": regressions,
        "gate_signal": gate, "details": details,
        "seconds": {"model_load": load_seconds, "rerank_total": rerank_seconds,
                    "rerank_per_query": rerank_seconds / n},
    }
    print(f"\n리랭크 {rerank_seconds:.1f}초 ({rerank_seconds / n:.2f}초/질문), 모델 로드 {load_seconds:.1f}초")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"결과: {args.out}")


if __name__ == "__main__":
    main()
