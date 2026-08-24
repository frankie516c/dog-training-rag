"""Rank the owner fixtures and the gold queries against the video+document corpus.

Graph/hybrid path DEPRECATED (2026-08-24): see docs/decision_graphrag_abandoned_0824.md
— reports/retrieval_perf_graph_vs_vector_0824.md measured 0/32 queries where the
graph candidates changed top_k, gate, or rank, which this docstring's own design
(gate decided from vector ranked[] alone, graph chunks merged in after) makes
structural rather than a sampling artifact. --graph-off (vector-only) remains the
live path; kept here rather than split out to preserve the A/B comparison history.



One code path for both query sets. The point of the acquisition was to change what
the corpus can answer, and score_gap is measured against the corpus mean, so every
number moves when documents land — including for questions the documents have
nothing to do with. Measuring the two sets with one runner is what makes the before
and after comparable at all.

scripts/evaluate_youtube_retrieval.py is deliberately neither imported nor modified.
It is kept as the reproduction of the video-only baseline, and it cannot read this
corpus anyway: it requires a video_id and a transcript file for every chunk, which
a blog article does not have. What is reimplemented here is only rank, reciprocal
rank and the score statistics. Span coverage stays that script's business.

Usage:
    uv run python scripts/run_combined_retrieval_eval.py
    uv run python scripts/run_combined_retrieval_eval.py --no-documents   # baseline check
    uv run python scripts/run_combined_retrieval_eval.py --graph-off      # vector-only, hybrid comparison
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_graph_neo4j import build_graph, load_aliases  # noqa: E402

DEFAULT_VIDEO_CHUNKS = Path("data/processed/youtube/chunks")
DEFAULT_DOC_CHUNKS = Path("data/processed/documents/chunks")
DEFAULT_FIXTURES = Path("data/eval/queries/owner_fixtures.jsonl")
DEFAULT_GOLD = Path("data/eval/queries/youtube_retrieval_queries.jsonl")
DEFAULT_METRICS = Path("data/eval/results/combined_v4_e5_metrics.json")
DEFAULT_REPORT = Path("reports/combined_corpus_coverage.md")
DEFAULT_GRAPH_EXTRACTIONS = Path("data/graph/extractions_stage2.jsonl")
DEFAULT_GRAPH_ALIASES = Path("data/graph/entity_aliases.json")

DEFAULT_BASELINE_FIXTURES = Path("data/eval/results/owner_fixtures_topk.jsonl")
DEFAULT_BASELINE_GOLD = Path("data/eval/results/retrieval_metrics_dev.json")
DEFAULT_DRYRUN = Path("data/eval/generation/answers_dryrun_scenario.jsonl")

METRICS_SCHEMA_VERSION = "combined-retrieval-metrics-v1"

MODEL_NAME = "intfloat/multilingual-e5-base"
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "

TOP_K = 5
REPORT_TOP_N = 3
SNIPPET_CHARS = 150
SCORE_DECIMALS = 6

# Unchanged on purpose. Re-tuning the operating point against a corpus that just
# changed would mix two effects in one measurement; recalibration is a separate
# question with its own date.
GATE_THRESHOLD = 0.024
GATE_PASS = "PASS"
GATE_REFUSE = "REFUSE"

# Fixtures the acquisition was meant to unblock, and the slot that should do it.
UNBLOCK_TARGETS = {
    "Q06": "3", "Q12": "1a", "Q13": "2", "Q14": "1b", "Q15": "1a", "Q16": "1a",
}
# Demo scenario ① and its reserve, both gold queries.
SCENARIO_IDS = ("q007", "q011")

# Vector failures registered before the graph exists, so the graph can be judged on
# cases chosen while it could not influence the choice. Each is a question the
# documents were meant to answer where dense retrieval did not reach them.
RETRIEVAL_GAP_IDS = ("Q12", "Q13", "Q14", "Q15")

# Graph search: match entity names in the question for seeds, walk this many hops.
GRAPH_MAX_HOPS = 2
MIN_ENTITY_NAME_CHARS = 2


class EvalError(RuntimeError):
    """Raised when a corpus, a query set or a setting is unusable."""


def serialize_score(value: float) -> float:
    return float(format(float(value), f".{SCORE_DECIMALS}f"))


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvalError(f"file not found: {path}")
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise EvalError(f"invalid JSON at {path}:{number}") from exc
    return out


def load_video_chunks(chunk_dir: Path) -> list[dict[str, Any]]:
    """Video chunks, with the timing kept: gold spans are resolved against it."""
    paths = sorted(chunk_dir.glob("*.jsonl"))
    if not paths:
        raise EvalError(f"no chunk file under {chunk_dir}")
    rows: list[dict[str, Any]] = []
    for path in paths:
        for row in _rows(path):
            for key in ("chunk_id", "video_id", "text"):
                if not isinstance(row.get(key), str) or not row[key]:
                    raise EvalError(f"{path}: invalid {key}")
            for key in ("chunk_index", "start_ms", "end_ms"):
                if not isinstance(row.get(key), int) or isinstance(row.get(key), bool):
                    raise EvalError(f"{path}: invalid {key}")
            row["source_kind"] = "video"
            rows.append(row)
    return rows


def load_document_chunks(chunk_dir: Path) -> list[dict[str, Any]]:
    """Document chunks. No video_id, no timing — those fields do not apply here."""
    if not chunk_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(chunk_dir.glob("*.jsonl")):
        for row in _rows(path):
            for key in ("chunk_id", "doc_id", "text", "source_url", "slot"):
                if not isinstance(row.get(key), str) or not row[key]:
                    raise EvalError(f"{path}: invalid {key}")
            if not isinstance(row.get("heading_path"), list):
                raise EvalError(f"{path}: heading_path must be an array")
            for absent in ("video_id", "start_ms", "end_ms"):
                if absent in row:
                    raise EvalError(
                        f"{path}: document chunks must not carry {absent!r}; "
                        "a document has no timeline and a placeholder would read as one"
                    )
            row["source_kind"] = "document"
            rows.append(row)
    return rows


def fingerprint(chunks: Sequence[dict[str, Any]]) -> str:
    """Content hash over (chunk_id, text), order-independent.

    Same construction the video baseline used, so a video-only run here reproduces
    the fingerprint recorded in the earlier snapshots and the two can be compared.
    """
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda row: row["chunk_id"]):
        digest.update(chunk["chunk_id"].encode("utf-8"))
        digest.update(b"\x00")
        digest.update(chunk["text"].encode("utf-8"))
        digest.update(b"\x00")
    return "sha256:" + digest.hexdigest()


def overlap_ms(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def gold_relevant_chunks(
    query: dict[str, Any], video_chunks: Sequence[dict[str, Any]]
) -> tuple[str, ...]:
    """Eligible video chunks whose interval overlaps any gold span of the query."""
    by_video = [c for c in video_chunks if c["video_id"] == query["video_id"]]
    found: list[str] = []
    for span in query["relevant_spans"]:
        for chunk in by_video:
            if overlap_ms(span["start_ms"], span["end_ms"], chunk["start_ms"], chunk["end_ms"]) > 0:
                found.append(chunk["chunk_id"])
    if not found:
        raise EvalError(f"{query['query_id']}: gold spans map to no eligible chunk")
    return tuple(sorted(dict.fromkeys(found)))


def load_encoder(device: str = "cpu") -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - optional extra
        raise EvalError("sentence-transformers is required (`uv add sentence-transformers`)") from exc
    model = SentenceTransformer(MODEL_NAME, device=device)

    class Encoder:
        def encode(self, texts: Sequence[str]) -> list[list[float]]:
            return [
                list(map(float, vector))
                for vector in model.encode(list(texts), normalize_embeddings=True)
            ]

    return Encoder()


def similarity(query_vector: Sequence[float], matrix: Sequence[Sequence[float]]) -> list[float]:
    return [sum(a * b for a, b in zip(query_vector, row)) for row in matrix]


def rank_scores(scores: Sequence[float], ids: Sequence[str], top_k: int) -> list[tuple[str, float]]:
    """Rank on the raw score; ties break on ascending chunk_id, as the baseline did."""
    order = sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))
    return [(ids[i], scores[i]) for i in order[:top_k]]


def score_stats(scores: Sequence[float]) -> dict[str, float | None]:
    ordered = sorted(scores, reverse=True)
    top1 = ordered[0]
    mean = sum(scores) / len(scores)
    return {
        "top1_score": serialize_score(top1),
        "corpus_mean_score": serialize_score(mean),
        "score_gap": serialize_score(top1 - mean),
        "top1_minus_top2": serialize_score(top1 - ordered[1]) if len(ordered) > 1 else None,
        "top5_std": serialize_score(statistics.pstdev(ordered[:5])) if len(ordered) >= 5 else None,
    }


def gate(score_gap: float) -> str:
    return GATE_PASS if score_gap >= GATE_THRESHOLD else GATE_REFUSE


def describe(chunk: dict[str, Any]) -> str:
    if chunk["source_kind"] == "document":
        return "문서 · " + " > ".join(chunk["heading_path"][1:] or ["(도입부)"])
    return "영상 · " + str(chunk.get("chapter_title", ""))[:28]


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    flat = " ".join(text.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


# --------------------------------------------------------------------------- graph


def load_graph(extractions_path: Path, aliases_path: Path) -> tuple[dict, dict]:
    """Fold the stage-2 extraction into (nodes, edges), reusing the loader's own rule.

    This is the same fold `scripts/load_graph_neo4j.py` writes into Neo4j, computed
    here without a database connection so eval runs stay reproducible offline
    (`scripts/preview_queries.py` does the same for the demo Cypher queries).
    """
    records = _rows(extractions_path)
    aliases = load_aliases(aliases_path)
    nodes, edges, _unresolved = build_graph(records, aliases)
    return nodes, edges


def build_adjacency(edges: dict) -> dict[tuple[str, str], list[tuple[tuple[str, str], Any]]]:
    """Undirected neighbor list: (node key) -> [(other node key, edge key), ...]."""
    adjacency: dict[tuple[str, str], list[tuple[tuple[str, str], Any]]] = {}
    for edge_key, edge in edges.items():
        src, tgt = edge["source"], edge["target"]
        adjacency.setdefault(src, []).append((tgt, edge_key))
        adjacency.setdefault(tgt, []).append((src, edge_key))
    return adjacency


def match_seeds(question: str, nodes: dict) -> list[tuple[str, str]]:
    """Entity nodes whose name or a recorded alias appears in the question text."""
    seeds = []
    for key, node in nodes.items():
        names = [node["name"], *node["aliases"]]
        if any(len(name) >= MIN_ENTITY_NAME_CHARS and name in question for name in names):
            seeds.append(key)
    return sorted(seeds)


def graph_walk(
    seeds: Sequence[tuple[str, str]],
    adjacency: dict,
    max_hops: int = GRAPH_MAX_HOPS,
) -> tuple[dict[tuple[str, str], int], dict[Any, int]]:
    """Multi-source BFS from the seeds, up to `max_hops` edges out.

    Returns every node and edge touched, each mapped to the hop distance it was
    first reached at (seeds are hop 0). Traversal is undirected: the relation
    schema is directional (e.g. 감별필요 always points into a disease), but a graph
    *search* over it should reach a neighbor regardless of which way the arrow
    happens to point, or the disease side of a 감별필요 edge is unreachable from
    its own symptom.
    """
    visited_nodes: dict[tuple[str, str], int] = {key: 0 for key in seeds}
    visited_edges: dict[Any, int] = {}
    frontier = list(seeds)
    for hop in range(1, max_hops + 1):
        next_frontier: list[tuple[str, str]] = []
        for node_key in frontier:
            for neighbor_key, edge_key in adjacency.get(node_key, []):
                if edge_key not in visited_edges:
                    visited_edges[edge_key] = hop
                if neighbor_key not in visited_nodes:
                    visited_nodes[neighbor_key] = hop
                    next_frontier.append(neighbor_key)
        frontier = next_frontier
    return visited_nodes, visited_edges


def graph_search(
    question: str,
    nodes: dict,
    edges: dict,
    adjacency: dict,
    by_id: dict[str, dict[str, Any]],
    max_hops: int = GRAPH_MAX_HOPS,
) -> list[dict[str, Any]]:
    """Entity-seeded, 2-hop graph search that returns chunks, not paths.

    Every node and edge the walk touches carries `source_chunks` — the chunks the
    extraction was read off of. The union of those, in the order the walk reached
    them and with duplicates dropped, is the chunk list a path-shaped result would
    otherwise have to be flattened into anyway; returning chunks directly keeps the
    output in the same shape as a vector hit (a corpus chunk dict), so the two can
    be merged without a translation step.
    """
    seeds = match_seeds(question, nodes)
    if not seeds:
        return []
    visited_nodes, visited_edges = graph_walk(seeds, adjacency, max_hops)
    ordered_nodes = sorted(visited_nodes, key=lambda key: (visited_nodes[key], key))
    ordered_edges = sorted(visited_edges, key=lambda key: (visited_edges[key], key))
    chunk_ids: list[str] = []
    for key in ordered_nodes:
        chunk_ids.extend(nodes[key]["source_chunks"])
    for key in ordered_edges:
        chunk_ids.extend(edges[key]["source_chunks"])
    deduped = list(dict.fromkeys(chunk_ids))
    return [by_id[cid] for cid in deduped if cid in by_id]


def hybrid_merge(
    vector_ranked: Sequence[tuple[str, float]], graph_chunks: Sequence[dict[str, Any]]
) -> list[str]:
    """Vector top-k first, graph chunks appended after, duplicates dropped.

    No routing (both retrievers always ran) and no score normalization (graph hits
    carry no score to normalize against) — order is the only thing preserved.
    """
    ordered = [chunk_id for chunk_id, _score in vector_ranked]
    ordered.extend(chunk["chunk_id"] for chunk in graph_chunks)
    return list(dict.fromkeys(ordered))


def run(
    video_dir: Path,
    doc_dir: Path | None,
    fixtures_path: Path,
    gold_path: Path,
    device: str,
    encoder: Any | None = None,
    graph_extractions: Path = DEFAULT_GRAPH_EXTRACTIONS,
    graph_aliases: Path = DEFAULT_GRAPH_ALIASES,
    graph_off: bool = False,
) -> dict[str, Any]:
    video_all = load_video_chunks(video_dir)
    video = [c for c in video_all if c.get("embedding_eligible")]
    if not video:
        raise EvalError("no embedding_eligible video chunk")
    documents = load_document_chunks(doc_dir) if doc_dir is not None else []
    corpus = video + documents
    ids = [c["chunk_id"] for c in corpus]
    by_id = {c["chunk_id"]: c for c in corpus}

    if graph_off:
        graph_nodes: dict = {}
        graph_edges: dict = {}
        graph_adjacency: dict = {}
    else:
        graph_nodes, graph_edges = load_graph(graph_extractions, graph_aliases)
        graph_adjacency = build_adjacency(graph_edges)

    def search_graph(question: str) -> list[dict[str, Any]]:
        if graph_off:
            return []
        return graph_search(question, graph_nodes, graph_edges, graph_adjacency, by_id)

    fixtures = [r for r in _rows(fixtures_path)]
    gold = [
        r for r in _rows(gold_path)
        if r.get("split") == "dev" and r.get("review_status") == "APPROVED"
    ]
    if not gold:
        raise EvalError(f"no APPROVED dev query in {gold_path}")

    if encoder is None:
        encoder = load_encoder(device)
    matrix = encoder.encode([PASSAGE_PREFIX + c["text"] for c in corpus])
    if len(matrix) != len(ids):
        raise EvalError("encoder returned a different number of passage vectors")

    def rank_one(question: str) -> tuple[list[tuple[str, float]], dict[str, Any]]:
        vector = encoder.encode([QUERY_PREFIX + question])[0]
        scores = similarity(vector, matrix)
        return rank_scores(scores, ids, TOP_K), score_stats(scores)

    fixture_rows = []
    for row in fixtures:
        ranked, stats = rank_one(str(row["question"]))
        verdict = gate(stats["score_gap"])
        # Both retrievers always run (no routing on query type); the gate decides
        # only whether the graph's chunks are admitted as evidence, and it never
        # sees them — score_gap above is computed from vector similarity alone.
        graph_chunks = search_graph(str(row["question"]))
        evidence_ids = (
            hybrid_merge(ranked, graph_chunks) if verdict == GATE_PASS
            else [cid for cid, _score in ranked]
        )
        fixture_rows.append({
            "query_id": row["query_id"],
            "question": row["question"],
            "expected_outcome": row["expected_outcome"],
            "coverage": row.get("coverage"),
            "note": row.get("note"),
            "guard_level": row.get("guard_level"),
            "refuse_reason": row.get("refuse_reason"),
            "missing_data": row.get("missing_data"),
            "demo_scenario": row.get("demo_scenario"),
            **stats,
            "gate_verdict": verdict,
            "gate_matches_expected": (row["expected_outcome"] == "ANSWER") == (verdict == GATE_PASS),
            "top_k": [
                {
                    "rank": rank,
                    "chunk_id": cid,
                    "score": serialize_score(score),
                    "source_kind": by_id[cid]["source_kind"],
                    "where": describe(by_id[cid]),
                    "slot": by_id[cid].get("slot"),
                    "text": by_id[cid]["text"],
                }
                for rank, (cid, score) in enumerate(ranked, start=1)
            ],
            "graph_top_k": [
                {
                    "chunk_id": chunk["chunk_id"],
                    "source_kind": chunk["source_kind"],
                    "where": describe(chunk),
                    "slot": chunk.get("slot"),
                    "text": chunk["text"],
                }
                for chunk in graph_chunks
            ],
            "evidence_chunk_ids": evidence_ids,
        })

    gold_rows = []
    for row in gold:
        relevant = set(gold_relevant_chunks(row, video))
        ranked, stats = rank_one(str(row["question"]))
        first = next((r for r, (cid, _) in enumerate(ranked, start=1) if cid in relevant), None)
        verdict = gate(stats["score_gap"])
        graph_chunks = search_graph(str(row["question"]))
        evidence_ids = (
            hybrid_merge(ranked, graph_chunks) if verdict == GATE_PASS
            else [cid for cid, _score in ranked]
        )
        gold_rows.append({
            "query_id": row["query_id"],
            "question": row["question"],
            "query_type": row["query_type"],
            "video_id": row["video_id"],
            "relevant_chunk_count": len(relevant),
            "first_relevant_rank": first,
            "reciprocal_rank": serialize_score(1 / first) if first else 0.0,
            **stats,
            "gate_verdict": verdict,
            "top_k": [
                {
                    "rank": rank,
                    "chunk_id": cid,
                    "score": serialize_score(score),
                    "source_kind": by_id[cid]["source_kind"],
                    "where": describe(by_id[cid]),
                    "is_gold": cid in relevant,
                    "text": by_id[cid]["text"],
                }
                for rank, (cid, score) in enumerate(ranked, start=1)
            ],
            "graph_top_k": [
                {
                    "chunk_id": chunk["chunk_id"],
                    "source_kind": chunk["source_kind"],
                    "where": describe(chunk),
                    "is_gold": chunk["chunk_id"] in relevant,
                    "text": chunk["text"],
                }
                for chunk in graph_chunks
            ],
            "evidence_chunk_ids": evidence_ids,
        })

    hit1 = sum(1 for r in gold_rows if r["first_relevant_rank"] == 1)
    hit5 = sum(1 for r in gold_rows if r["first_relevant_rank"])
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "run": {
            "model_name": MODEL_NAME,
            "top_k": TOP_K,
            "gate_threshold": GATE_THRESHOLD,
            "query_prefix": QUERY_PREFIX,
            "passage_prefix": PASSAGE_PREFIX,
            "tie_break": "ascending chunk_id",
            "device": device,
            "graph_enabled": not graph_off,
            "graph_max_hops": GRAPH_MAX_HOPS,
        },
        "graph": {
            "enabled": not graph_off,
            "nodes": len(graph_nodes),
            "edges": len(graph_edges),
        },
        "corpus": {
            "video": {
                "chunks_total": len(video_all),
                "chunks_eligible": len(video),
                "fingerprint": fingerprint(video),
            },
            "documents": {
                "chunks": len(documents),
                "documents": len({c["doc_id"] for c in documents}),
                "fingerprint": fingerprint(documents) if documents else None,
            },
            "combined": {"chunks": len(corpus), "fingerprint": fingerprint(corpus)},
        },
        "owner_fixtures": fixture_rows,
        "gold": gold_rows,
        "gold_summary": {
            "queries": len(gold_rows),
            "hit@1": serialize_score(hit1 / len(gold_rows)),
            "hit@5": serialize_score(hit5 / len(gold_rows)),
            "mrr@5": serialize_score(
                sum(r["reciprocal_rank"] for r in gold_rows) / len(gold_rows)
            ),
        },
    }


# --------------------------------------------------------------------------- report


def _baseline_fixtures(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return {r["query_id"]: r for r in _rows(path)}


def _baseline_gold(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {r["query_id"]: r for r in payload.get("per_query", [])}


def _delta(new: float, old: float | None) -> str:
    if old is None:
        return "-"
    return f"{new - old:+.4f}"


def build_report(
    payload: dict[str, Any],
    base_fixtures: dict[str, dict[str, Any]],
    base_gold: dict[str, dict[str, Any]],
    dryrun: dict[str, Any],
) -> str:
    corpus = payload["corpus"]
    fixtures = {r["query_id"]: r for r in payload["owner_fixtures"]}
    gold = {r["query_id"]: r for r in payload["gold"]}
    lines: list[str] = []

    lines.append("# 조달 후 통합 코퍼스 커버리지 리포트")
    lines.append("")
    lines.append(
        "문서 6건을 넣은 뒤 owner 픽스처 20건과 gold 12건을 **같은 러너 한 번으로** "
        "다시 측정한 결과입니다. `score_gap`은 top1에서 통합 코퍼스 평균을 뺀 값이라 "
        "문서가 들어오면 조달과 무관한 질문의 gap도 함께 움직입니다. 그래서 두 질문셋을 "
        "따로 재지 않았습니다."
    )
    lines.append("")
    lines.append(
        "> **이 파일은 `scripts/run_combined_retrieval_eval.py`가 생성합니다. 직접 편집하지 마세요.** "
        "coverage 판정은 `data/eval/queries/owner_fixtures.jsonl`에, dry-run 답변은 "
        "`data/eval/generation/dryrun_answers.json`에 기록하고 리포트를 다시 생성하면 반영됩니다."
    )
    lines.append("")
    lines.append("| 코퍼스 | 청크 | fingerprint |")
    lines.append("|---|---|---|")
    lines.append("| 영상 (v3, 불변) | {} (eligible) | `{}` |".format(
        corpus["video"]["chunks_eligible"], corpus["video"]["fingerprint"][:26]))
    lines.append("| 문서 (신규 {}건) | {} | `{}` |".format(
        corpus["documents"]["documents"], corpus["documents"]["chunks"],
        (corpus["documents"]["fingerprint"] or "-")[:26]))
    lines.append("| **통합** | **{}** | `{}` |".format(
        corpus["combined"]["chunks"], corpus["combined"]["fingerprint"][:26]))
    lines.append("")
    lines.append(
        "gate 임계값은 `score_gap >= {}`로 **조달 전과 동일**합니다. "
        "코퍼스가 막 바뀐 상태에서 임계값까지 같이 움직이면 두 효과가 한 측정에 섞입니다."
        .format(GATE_THRESHOLD))

    lines.extend(_decomposition_section(fixtures, base_fixtures, corpus))
    lines.extend(_unblock_section(fixtures, base_fixtures))
    lines.extend(_scenario_section(gold, base_gold, dryrun))
    lines.extend(_retrieval_gap_section(fixtures, base_fixtures))
    lines.extend(_gold_section(payload, base_gold))
    lines.extend(_fixture_table(payload["owner_fixtures"], base_fixtures))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "관찰은 검색 결과에 실제로 나타난 것만 적었습니다. coverage 재판정은 비어 있으며 "
        "사람이 채웁니다."
    )
    return "\n".join(lines).rstrip() + "\n"


def _decomposition_section(
    fixtures: dict[str, dict[str, Any]], base: dict[str, dict[str, Any]],
    corpus: dict[str, Any],
) -> list[str]:
    """Split the gap movement into "the corpus answers better" and "the mean fell".

    score_gap is top1 minus the corpus mean. Adding documents that are unrelated to a
    given question lowers that mean, which raises the gap without retrieval having
    improved at all. Reporting the gap alone would read as twenty questions getting
    better, so the two terms are shown separately.
    """
    lines = ["", "## ⓪ gap 상승의 분해 — 검색이 좋아진 것과 평균이 내려간 것", ""]
    rows = []
    for query_id, row in fixtures.items():
        old = base.get(query_id)
        if not old or "score_stats" not in old:
            continue
        rows.append((
            query_id,
            row["top1_score"] - old["score_stats"]["top1_score"],
            old["score_stats"]["corpus_mean_score"] - row["corpus_mean_score"],
            row["score_gap"] - old["score_gap"],
        ))
    if not rows:
        lines.append("- 비교할 조달 전 측정치가 없습니다.")
        return lines

    lines.append("| id | Δtop1 (검색이 실제로 좋아진 몫) | Δ평균 하락 (문서가 늘어난 몫) | Δgap |")
    lines.append("|---|---|---|---|")
    for query_id, d_top1, d_mean, d_gap in rows:
        lines.append("| {} | {:+.4f} | {:+.4f} | {:+.4f} |".format(
            query_id, d_top1, d_mean, d_gap))
    lines.append("")
    moved = [r for r in rows if r[1] > 0.001]
    still = [r for r in rows if r[1] <= 0.001]
    lines.append(
        "- **top1이 실제로 오른 질문은 {}건**입니다: {}. 나머지 {}건은 top1이 그대로인데 "
        "gap만 올랐습니다 — 문서가 코퍼스 평균을 끌어내린 결과이지, 그 질문에 답할 근거가 "
        "생겼다는 뜻이 아닙니다.".format(
            len(moved), ", ".join("{} {:+.4f}".format(q, d) for q, d, _, _ in moved),
            len(still)))
    total = len(fixtures)
    pass_n = sum(1 for r in fixtures.values() if r["gate_verdict"] == GATE_PASS)
    refuse_n = total - pass_n
    lines.append(
        "- **현재 {}청크에서 owner 픽스처 {}건 중 {}건은 PASS, {}건은 REFUSE입니다.** "
        "임계값 {}는 26청크 코퍼스에서 잡은 값이고, 코퍼스 평균 변화가 score_gap에 "
        "영향을 줄 수 있으므로, 이 gate는 운영 정책이 아닌 데모·평가용 신호로만 "
        "사용해야 합니다.".format(
            corpus["combined"]["chunks"], total, pass_n, refuse_n, GATE_THRESHOLD))
    lines.append(
        "- 판별력이 남아 있는 신호는 Δtop1입니다. 조달이 겨냥한 질문과 그렇지 않은 질문이 "
        "이 열에서는 갈립니다.")
    return lines


def _unblock_section(
    fixtures: dict[str, dict[str, Any]], base: dict[str, dict[str, Any]]
) -> list[str]:
    lines = ["", "## ① 해제 대상 6문항의 top-5 · gap 변화", ""]
    lines.append(
        "`겨냥 슬롯 문서`가 실제 해제 여부에 가까운 열입니다. top-5에 문서가 들어왔다는 "
        "것만으로는 **그 질문을 겨냥해 조달한** 문서인지 알 수 없습니다."
    )
    lines.append("")
    lines.append("| id | 겨냥 슬롯 | Δtop1 | gap 이전 | gap 이후 | gate 이전→이후 | top-5 문서 | 겨냥 슬롯 문서 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for query_id, slot in UNBLOCK_TARGETS.items():
        row = fixtures.get(query_id)
        if row is None:
            lines.append(f"| {query_id} | {slot} | - | - | - | - | (없음) |")
            continue
        old = base.get(query_id, {})
        old_gap = old.get("score_gap")
        old_gate = old.get("gate_verdict", "-")
        docs = [e for e in row["top_k"] if e["source_kind"] == "document"]
        on_slot = [e for e in docs if e.get("slot") == slot]
        d_top1 = (
            row["top1_score"] - old["score_stats"]["top1_score"]
            if "score_stats" in old else None
        )
        lines.append(
            "| {} | {} | {} | {} | {:.4f} | {} → **{}** | {}/5 | **{}/5** |".format(
                query_id, slot,
                f"{d_top1:+.4f}" if d_top1 is not None else "-",
                f"{old_gap:.4f}" if old_gap is not None else "-",
                row["score_gap"], old_gate, row["gate_verdict"],
                len(docs), len(on_slot),
            )
        )
    lines.append("")
    for query_id in UNBLOCK_TARGETS:
        row = fixtures.get(query_id)
        if row is None:
            continue
        lines.append("### {} · {}".format(query_id, snippet(row["question"], 60)))
        lines.append("")
        lines.append("| 순위 | 출처 | score | 본문 앞 {}자 |".format(SNIPPET_CHARS))
        lines.append("|---|---|---|---|")
        for entry in row["top_k"]:
            mark = "**문서**" if entry["source_kind"] == "document" else "영상"
            lines.append("| {} | {} · {} | {:.4f} | {} |".format(
                entry["rank"], mark, entry["where"].split(" · ", 1)[-1][:26],
                entry["score"], snippet(entry["text"])))
        lines.append("")
        slot = UNBLOCK_TARGETS[query_id]
        on_slot = [e for e in row["top_k"] if e.get("slot") == slot]
        off_slot = [e for e in row["top_k"]
                    if e["source_kind"] == "document" and e.get("slot") != slot]
        lines.append("- score_gap **{:.4f}** · gate **{}** · coverage(판정 전) {}".format(
            row["score_gap"], row["gate_verdict"], row["coverage"]))
        if on_slot:
            lines.append("- 겨냥 슬롯({}) 문서가 {}위에 올랐습니다.".format(
                slot, ", ".join(str(e["rank"]) for e in on_slot)))
        else:
            lines.append(
                "- **겨냥 슬롯({}) 문서가 top-5에 없습니다.** 이 질문을 위해 조달한 문서가 "
                "검색되지 않았다는 뜻입니다.".format(slot))
        if off_slot:
            lines.append("- 다른 슬롯 문서가 {}위에 올라 있습니다 (슬롯 {}).".format(
                ", ".join(str(e["rank"]) for e in off_slot),
                ", ".join(sorted({str(e.get("slot")) for e in off_slot}))))
        lines.append("- coverage 재판정: [ ]  ← answerable / partial / missing")
        lines.append("")
    return lines


def _scenario_section(
    gold: dict[str, dict[str, Any]], base: dict[str, dict[str, Any]], dryrun: dict[str, Any]
) -> list[str]:
    lines = ["", "## ② 시나리오① 후보 q007 · q011 변화와 dry-run 답변", ""]
    lines.append("| id | rank 이전 | rank 이후 | gap 이전 | gap 이후 | 변화 | top-5 중 신규 문서 |")
    lines.append("|---|---|---|---|---|---|---|")
    for query_id in SCENARIO_IDS:
        row = gold.get(query_id)
        if row is None:
            continue
        old = base.get(query_id, {})
        docs = sum(1 for e in row["top_k"] if e["source_kind"] == "document")
        lines.append("| {} | {} | **{}** | {} | {:.4f} | {} | {}/5 |".format(
            query_id, old.get("first_relevant_rank", "-") or "미검출",
            row["first_relevant_rank"] or "미검출",
            f"{old.get('score_gap'):.4f}" if old.get("score_gap") is not None else "-",
            row["score_gap"], _delta(row["score_gap"], old.get("score_gap")), docs))
    lines.append("")
    for query_id in SCENARIO_IDS:
        row = gold.get(query_id)
        if row is None:
            continue
        lines.append("### {} · {}".format(query_id, row["question"]))
        lines.append("")
        lines.append("| 순위 | 출처 | 정답 | score | 본문 앞 {}자 |".format(SNIPPET_CHARS))
        lines.append("|---|---|---|---|---|")
        for entry in row["top_k"]:
            lines.append("| {} | {} | {} | {:.4f} | {} |".format(
                entry["rank"],
                "**문서**" if entry["source_kind"] == "document" else "영상",
                "✓" if entry["is_gold"] else "",
                entry["score"], snippet(entry["text"])))
        lines.append("")
        answer = dryrun.get(query_id)
        if answer:
            lines.append("**dry-run 생성 답변** ({})".format(answer.get("produced_by", "미기재")))
            lines.append("")
            for para in str(answer["answer"]).split("\n"):
                lines.append("> " + para if para.strip() else ">")
            lines.append("")
        else:
            lines.append(
                "**dry-run 생성 답변**: 없음 — `{}`에 기록하면 여기에 렌더링됩니다."
                .format(DEFAULT_DRYRUN.as_posix()))
            lines.append("")
    return lines


def _retrieval_gap_section(
    fixtures: dict[str, dict[str, Any]], base: dict[str, dict[str, Any]]
) -> list[str]:
    """The four questions the graph path will have to rescue, registered in advance.

    Registering them now matters: after the graph exists it will be tempting to pick
    the cases it happens to win. These were chosen while only the vector path had run.
    """
    lines = ["", "## ③ retrieval-gap 사전 등록 — 그래프 경로가 구제해야 할 벡터 실패", ""]
    lines.append(
        "네 건 모두 **근거 문서는 코퍼스에 있는데 벡터 검색이 닿지 못한** 경우입니다. "
        "조달로 메우는 구멍이 아니라 검색 경로의 실패이므로, 그래프 완성 후 이 4건으로 "
        "**하이브리드 vs 벡터**를 비교합니다. 그래프가 만들어지기 전에 골라 둔 목록입니다."
    )
    lines.append("")
    lines.append("| id | coverage | 겨냥 슬롯 문서 top-5 | Δtop1 | 실패 양상 |")
    lines.append("|---|---|---|---|---|")
    for query_id in RETRIEVAL_GAP_IDS:
        row = fixtures.get(query_id)
        if row is None:
            continue
        slot = UNBLOCK_TARGETS.get(query_id, "-")
        on_slot = [e for e in row["top_k"] if e.get("slot") == slot]
        old = base.get(query_id, {})
        d_top1 = (
            row["top1_score"] - old["score_stats"]["top1_score"]
            if "score_stats" in old else None
        )
        lines.append("| {} | {} | {}/5 | {} | {} |".format(
            query_id, row["coverage"], len(on_slot),
            f"{d_top1:+.4f}" if d_top1 is not None else "-",
            row.get("note") or "-"))
    lines.append("")
    lines.append(
        "- 판정 근거는 gap이 아닙니다. gap은 코퍼스가 커지면서 오른 산술 효과가 섞여 있어 "
        "이 네 건에서도 전부 상승했습니다 (⓪ 절 참조)."
    )
    lines.append(
        "- Q13의 Δtop1이 0이 아닌 것에 주의하세요. 1위가 올라간 것은 맞지만 올라온 문서가 "
        "겨냥 슬롯이 아닙니다 — 상승분이 곧 해제가 아니라는 사례입니다."
    )
    return lines


def _gold_section(payload: dict[str, Any], base: dict[str, dict[str, Any]]) -> list[str]:
    summary = payload["gold_summary"]
    lines = ["", "## ④ gold 12 rank · gap 이동 요약", ""]
    lines.append("| id | type | rank 이전 | rank 이후 | RR 이후 | gap 이전 | gap 이후 | 변화 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    moved = []
    for row in payload["gold"]:
        old = base.get(row["query_id"], {})
        old_rank = old.get("first_relevant_rank")
        new_rank = row["first_relevant_rank"]
        if old_rank != new_rank:
            moved.append((row["query_id"], old_rank, new_rank))
        lines.append("| {} | {} | {} | {} | {} | {} | {:.4f} | {} |".format(
            row["query_id"], row["query_type"],
            old_rank or "미검출", new_rank or "미검출",
            row["reciprocal_rank"],
            f"{old.get('score_gap'):.4f}" if old.get("score_gap") is not None else "-",
            row["score_gap"], _delta(row["score_gap"], old.get("score_gap"))))
    lines.append("")
    lines.append("- Hit@1 **{}** · Hit@5 **{}** · MRR@5 **{}** (12문항)".format(
        summary["hit@1"], summary["hit@5"], summary["mrr@5"]))
    if moved:
        lines.append("- 순위가 바뀐 질문: " + ", ".join(
            "{} {}→{}".format(q, o or "미검출", n or "미검출") for q, o, n in moved))
    else:
        lines.append("- 정답 청크 순위는 12문항 모두 그대로입니다.")
    lines.append("- 이 표가 `docs/demo_scenarios.md` 갱신 재료입니다.")
    return lines


def _fixture_table(rows: Sequence[dict[str, Any]], base: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["", "## ⑤ owner 픽스처 20건 전체", ""]
    lines.append("| id | 기대 | coverage(이전) | gap 이전 | gap 이후 | 변화 | gate | 일치 | 문서 진입 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        old = base.get(row["query_id"], {})
        docs = sum(1 for e in row["top_k"] if e["source_kind"] == "document")
        lines.append("| {} | {} | {} | {} | {:.4f} | {} | {} | {} | {}/5 |".format(
            row["query_id"], row["expected_outcome"], row["coverage"],
            f"{old.get('score_gap'):.4f}" if old.get("score_gap") is not None else "-",
            row["score_gap"], _delta(row["score_gap"], old.get("score_gap")),
            row["gate_verdict"], "✓" if row["gate_matches_expected"] else "✗", docs))
    lines.append("")
    changed = [r["query_id"] for r in rows
               if base.get(r["query_id"], {}).get("gate_verdict") not in (None, r["gate_verdict"])]
    lines.append("- gate 판정이 뒤집힌 질문: {}".format(", ".join(changed) if changed else "없음"))
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-chunks", type=Path, default=DEFAULT_VIDEO_CHUNKS)
    parser.add_argument("--doc-chunks", type=Path, default=DEFAULT_DOC_CHUNKS)
    parser.add_argument("--no-documents", action="store_true",
                        help="video-only run, to check this runner against the old baseline")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--baseline-fixtures", type=Path, default=DEFAULT_BASELINE_FIXTURES)
    parser.add_argument("--baseline-gold", type=Path, default=DEFAULT_BASELINE_GOLD)
    parser.add_argument("--dryrun", type=Path, default=DEFAULT_DRYRUN)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--graph-extractions", type=Path, default=DEFAULT_GRAPH_EXTRACTIONS)
    parser.add_argument("--graph-aliases", type=Path, default=DEFAULT_GRAPH_ALIASES)
    parser.add_argument("--graph-off", action="store_true",
                        help="vector-only run, no graph search — for the vector-vs-hybrid comparison")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run(
            args.video_chunks,
            None if args.no_documents else args.doc_chunks,
            args.fixtures, args.gold, args.device,
            graph_extractions=args.graph_extractions,
            graph_aliases=args.graph_aliases,
            graph_off=args.graph_off,
        )
        dryrun = (
            {r["query_id"]: r for r in _rows(args.dryrun)} if args.dryrun.is_file() else {}
        )
        args.metrics.parent.mkdir(parents=True, exist_ok=True)
        args.metrics.write_bytes(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        if not args.no_documents:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_bytes(build_report(
                payload,
                _baseline_fixtures(args.baseline_fixtures),
                _baseline_gold(args.baseline_gold),
                dryrun,
            ).encode("utf-8"))
    except (OSError, EvalError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    corpus = payload["corpus"]
    summary = payload["gold_summary"]
    print("corpus: 영상 {} + 문서 {} = {}청크".format(
        corpus["video"]["chunks_eligible"], corpus["documents"]["chunks"],
        corpus["combined"]["chunks"]))
    print("gold 12: Hit@1 {} · Hit@5 {} · MRR@5 {}".format(
        summary["hit@1"], summary["hit@5"], summary["mrr@5"]))
    passed = sum(1 for r in payload["owner_fixtures"] if r["gate_verdict"] == GATE_PASS)
    matched = sum(1 for r in payload["owner_fixtures"] if r["gate_matches_expected"])
    print("owner 20: gate PASS {} / 기대 일치 {}".format(passed, matched))
    graph = payload["graph"]
    if graph["enabled"]:
        print("graph: 노드 {} · 엣지 {} (최대 {}홉)".format(
            graph["nodes"], graph["edges"], payload["run"]["graph_max_hops"]))
    else:
        print("graph: off (--graph-off)")
    print("metrics: {}".format(args.metrics))
    if not args.no_documents:
        print("report: {}".format(args.report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
