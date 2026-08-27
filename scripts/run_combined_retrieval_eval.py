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

# DEFAULT SIGNAL CHANGED 2026-08-25: margin_top5, not score_gap.
#
# score_gap (top1 - corpus mean) loses discriminative power as the corpus grows
# (docs/agenda_0825.md #1): PASS 11/20 -> 20/20 across a 26->77 chunk expansion,
# 20/20 again at 567 chunks in the corpus-expansion trial rolled back
# 2026-08-25, and 48/48 at the current 245-chunk corpus with the 48-fixture
# owner set below — it now passes literally everything regardless of
# expected_outcome. It matches expected_outcome on only 31-33% of the 48
# fixtures at either 83 or 245 chunks (reports/retrieval_gate_redesign_retry_0825.md)
# — worse than always guessing REFUSE (68.75%).
#
# margin_top5 (top1 - top5, does not reference the corpus mean) was tried
# first on 20 fixtures (reports/retrieval_gate_redesign_0825.md, 14 REFUSE / 6
# ANSWER) and only tied the always-REFUSE baseline there. Once
# reports/owner_fixtures_expansion_0825.md grew the set to 48 (33 REFUSE / 15
# ANSWER), reports/retrieval_gate_redesign_retry_0825.md re-ran it and found:
# (a) 40/48 (83.3%) overall, and on just the 28 fixtures added after this
# threshold was fit — genuine held-out rows — 26/28 (92.9%), well above that
# slice's own always-REFUSE baseline (67.9%); (b) checked across corpus sizes
# by temporarily pulling the 162 chunks added since the last full-corpus
# report back out, its match rate went 72.9% (83 chunks) -> 83.3% (245
# chunks) — improving, not degrading, as the corpus tripled, which is the
# opposite of what score_gap does under the same kind of growth. Three
# independent checks (held-out fixtures, corpus-size swing, and the trivial
# baseline) agree, so this file's default switched.
#
# generate_answers.py's three-band classify_band() (REFUSE/hedge/ANSWER) is a
# separate mechanism and still runs on score_gap alone — this switch does not
# touch it. classify_band has no margin_top5-equivalent thresholds fit for its
# three bands (only this file's binary PASS/REFUSE was tested), so carrying
# this decision over there is a distinct piece of work, not a two-line change.
GATE_SIGNALS = ("score_gap", "margin_top2", "margin_top5")
GATE_MARGIN_TOP2_THRESHOLD = 0.011  # fit on the original 20 rows; held up 21/28 on the 28 added since
GATE_MARGIN_TOP5_THRESHOLD = 0.0183  # fit on the original 20 rows; held up 26/28 on the 28 added since
DEFAULT_GATE_SIGNAL = "margin_top5"

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


# 문서 앵커 최소 길이. 짧은 인용문은 다른 문서·다른 문단에 우연히 걸린다.
MIN_ANCHOR_CHARS = 20


def gold_relevant_chunks(
    query: dict[str, Any],
    video_chunks: Sequence[dict[str, Any]],
    document_chunks: Sequence[dict[str, Any]] = (),
) -> tuple[str, ...]:
    """질의의 gold 청크 집합. 영상 span과 문서 앵커의 **합집합**이다.

    두 참조 체계를 병행하는 이유:
      - 영상은 시간축이 원본의 자연스러운 좌표다. 텍스트 앵커로 옮기면 ASR
        전사가 바뀔 때마다 깨지는데, 재전사 논의가 아직 열려 있다.
      - 문서는 타임라인이 없다. 문자 오프셋은 본문이 한 글자만 바뀌어도 전부
        밀린다(breadcrumb 제거처럼 실제로 일어난다). 인용문 앵커는 그 문장이
        본문에 남아 있는 한 계속 매칭된다.

    한 질의가 둘 다 가질 수 있다 — 문서 답과 영상 답이 동시에 타당한 질의가
    실제로 나오며, 한쪽만 gold로 두면 정답인 검색을 오답으로 채점하게 된다.

    앵커가 어느 청크에도 매칭되지 않으면 **오류를 낸다.** gold가 조용히 줄면
    정답 집합이 작아져 Hit@1이 오히려 올라갈 수 있고, 그것을 개선으로 읽게 된다.
    """
    found: list[str] = []

    if query.get("video_id") and query.get("relevant_spans"):
        by_video = [c for c in video_chunks if c["video_id"] == query["video_id"]]
        for span in query["relevant_spans"]:
            for chunk in by_video:
                if overlap_ms(
                    span["start_ms"], span["end_ms"], chunk["start_ms"], chunk["end_ms"]
                ) > 0:
                    found.append(chunk["chunk_id"])

    for anchor in query.get("anchors") or []:
        quote = anchor["quote"]
        if len(quote) < MIN_ANCHOR_CHARS:
            raise EvalError(
                f"{query['query_id']}/{anchor['anchor_id']}: 앵커가 {len(quote)}자로 "
                f"최소 {MIN_ANCHOR_CHARS}자 미만 — 짧은 인용문은 우연 매칭이 난다"
            )
        in_doc = [c for c in document_chunks if c["doc_id"] == anchor["doc_id"]]
        if not in_doc:
            raise EvalError(
                f"{query['query_id']}/{anchor['anchor_id']}: doc_id "
                f"{anchor['doc_id']!r}에 해당하는 청크가 코퍼스에 없다"
            )
        # 여러 청크에 걸리면 전부 gold다 — 같은 문장이 두 청크에 있다면 어느
        # 쪽을 검색해도 답이 나오므로 둘 다 정답이 맞다.
        hits = [c["chunk_id"] for c in in_doc if quote in c["text"]]
        if not hits:
            available = ", ".join(f"#{c['chunk_index']}" for c in in_doc[:10])
            raise EvalError(
                f"{query['query_id']}/{anchor['anchor_id']}: 앵커 인용문이 "
                f"{anchor['doc_id']}의 어느 청크에도 없다 — 본문이 편집됐거나 "
                f"청크 경계를 가로지른다. 해당 문서 청크: {available}"
            )
        found.extend(hits)

    if not found:
        # coverage: missing은 "코퍼스에 답이 없다"가 정답인 질의다. 거절 경계
        # 질의가 여기 해당하며, 정답 청크를 정의하는 것 자체가 모순이다 —
        # 아무것도 검색되지 않는 것이 성공이기 때문이다. 검색 지표에서 빼고
        # 게이트 판정만 본다(아래 run()의 gold 루프).
        #
        # **명시적으로 missing이라고 적힌 질의만** 예외다. 그 표시가 없는데
        # 매핑이 0건이면 여전히 오류다 — gold가 조용히 줄면 정답 집합이 작아져
        # Hit@1이 오히려 올라가고, 그것을 개선으로 읽게 된다.
        if query.get("coverage") == "missing":
            return ()
        raise EvalError(
            f"{query['query_id']}: gold 참조가 어느 청크에도 매핑되지 않는다 "
            "(relevant_spans·anchors 둘 다 비었거나 해석 실패). 코퍼스에 답이 "
            "없는 것이 정답인 질의라면 coverage: missing을 명시할 것"
        )
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
        "top1_minus_top5": serialize_score(top1 - ordered[4]) if len(ordered) >= 5 else None,
        "top5_std": serialize_score(statistics.pstdev(ordered[:5])) if len(ordered) >= 5 else None,
    }


def gate(score_gap: float) -> str:
    return GATE_PASS if score_gap >= GATE_THRESHOLD else GATE_REFUSE


def gate_verdict(stats: dict[str, Any], signal: str = DEFAULT_GATE_SIGNAL) -> str:
    """Same PASS/REFUSE contract as gate(), generalized over GATE_SIGNALS.

    Default is margin_top5 as of 2026-08-25 (see the GATE_SIGNALS comment for
    why). signal='score_gap' still reproduces gate(stats['score_gap']) exactly
    for anyone who passes it explicitly or via --gate-signal score_gap — it is
    also what generate_answers.py's separate classify_band() still uses, since
    that three-band mechanism was not part of this switch.
    """
    if signal == "score_gap":
        return gate(stats["score_gap"])
    if signal == "margin_top2":
        value = stats.get("top1_minus_top2")
        threshold = GATE_MARGIN_TOP2_THRESHOLD
    elif signal == "margin_top5":
        value = stats.get("top1_minus_top5")
        threshold = GATE_MARGIN_TOP5_THRESHOLD
    else:
        raise EvalError(f"unknown --gate-signal {signal!r}, expected one of {GATE_SIGNALS}")
    if value is None:  # corpus too small for this rank (e.g. <5 chunks for top5)
        return GATE_PASS
    return GATE_PASS if value >= threshold else GATE_REFUSE


def gate_signal_threshold(signal: str) -> float:
    """The operating threshold for whichever --gate-signal is active.

    build_report()'s prose used to hardcode "score_gap >= {GATE_THRESHOLD}" —
    wrong as soon as the default stopped being score_gap. Report text should
    read this instead of the score_gap-specific constant directly.
    """
    return {
        "score_gap": GATE_THRESHOLD,
        "margin_top2": GATE_MARGIN_TOP2_THRESHOLD,
        "margin_top5": GATE_MARGIN_TOP5_THRESHOLD,
    }[signal]


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


ROLE_OWNER_QUESTION = "OWNER_QUESTION"
ROLE_EXPERT_ANSWER = "EXPERT_ANSWER"

# 한 Q&A의 전문가 답변이 여러 청크에 걸칠 때 몇 개까지 근거에 붙일지.
# 무제한이면 긴 답변 하나가 프롬프트를 통째로 차지한다. 상한을 넘으면 조용히
# 자르지 않고 몇 개를 버렸는지 기록한다 — 잘린 것을 모르면 커버리지를 과대평가한다.
#
# 처음 5로 잡았으나 실데이터에서 작았다 — 훈련사 답변은 6~9청크가 흔했고 6개
# 질의가 상한에 걸렸다. 답변부는 인용 가능한 유일한 근거이므로 잘리면 권고가
# 중간에서 끊긴다. 실측 최대(9)를 담고 한 칸 여유를 둔다.
EXPANSION_MAX_SIBLINGS = 10


def build_qa_answer_index(corpus: Sequence[dict[str, Any]]) -> dict[str, list[str]]:
    """qa_id -> EXPERT_ANSWER chunk_id 목록 (문서 순서).

    답변이 여러 청크로 쪼개졌을 때 순서가 뒤섞이면 절차 설명이 끊기므로
    chunk_index 오름차순을 유지한다.
    """
    grouped: dict[str, list[tuple[int, str]]] = {}
    for chunk in corpus:
        if chunk.get("segment_role") != ROLE_EXPERT_ANSWER:
            continue
        qa_id = chunk.get("qa_id")
        if not qa_id:
            continue
        grouped.setdefault(qa_id, []).append(
            (int(chunk.get("chunk_index", 0)), chunk["chunk_id"])
        )
    return {
        qa_id: [cid for _idx, cid in sorted(pairs)]
        for qa_id, pairs in grouped.items()
    }


def expand_qa_siblings(
    evidence_ids: Sequence[str],
    by_id: dict[str, dict[str, Any]],
    qa_index: dict[str, list[str]],
) -> tuple[list[str], dict[str, Any]]:
    """OWNER_QUESTION이 근거에 들어왔으면 같은 qa_id의 EXPERT_ANSWER를 붙인다.

    견주 질문은 citation_allowed=false다 — 사용자 사례 맥락이지 훈련 권고가
    아니다. 질문만 근거로 남으면 인용할 것이 없는 채로 견주 발화가 노출되므로,
    인용 가능한 형제 답변을 함께 가져온다.

    **이 함수는 게이트 통계 계산이 끝난 뒤에만 호출해야 한다.** 유사도 분포를
    건드리면 별도로 검증을 마친 게이트 신호 결정이 무효화된다. 호출 순서는
    테스트로 고정돼 있다.

    규칙:
      - 형제 답변은 문서 순서로 **전부** 붙인다(상한 EXPANSION_MAX_SIBLINGS).
        답변이 여러 청크에 걸칠 때 일부만 주면 권고가 중간에서 잘린다.
      - 이미 랭킹에 들어와 있는 답변은 다시 붙이지 않는다(순서 유지, 중복 제거).
      - **형제 답변이 하나도 없는 OWNER_QUESTION은 근거에서 뺀다(fail-closed).**
        인용 가능한 짝이 없는 견주 발화를 근거로 남기면, 인용 금지 표시가
        있더라도 모델이 그것만 보고 답을 지어낼 여지가 생긴다.
    """
    ordered = list(dict.fromkeys(evidence_ids))
    appended: list[str] = []
    dropped_orphans: list[str] = []
    truncated: dict[str, int] = {}

    for cid in list(ordered):
        chunk = by_id.get(cid)
        if not chunk or chunk.get("segment_role") != ROLE_OWNER_QUESTION:
            continue
        qa_id = chunk.get("qa_id")
        siblings = qa_index.get(qa_id or "", [])
        if not siblings:
            dropped_orphans.append(cid)
            continue
        if len(siblings) > EXPANSION_MAX_SIBLINGS:
            truncated[qa_id] = len(siblings) - EXPANSION_MAX_SIBLINGS
            siblings = siblings[:EXPANSION_MAX_SIBLINGS]
        for sid in siblings:
            if sid not in ordered and sid not in appended:
                appended.append(sid)

    result = [cid for cid in ordered if cid not in dropped_orphans] + appended
    return result, {
        "appended_answer_chunk_ids": appended,
        "dropped_orphan_question_chunk_ids": dropped_orphans,
        "truncated_siblings_by_qa_id": truncated,
    }


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
    gate_signal: str = DEFAULT_GATE_SIGNAL,
) -> dict[str, Any]:
    video_all = load_video_chunks(video_dir)
    video = [c for c in video_all if c.get("embedding_eligible")]
    if not video:
        raise EvalError("no embedding_eligible video chunk")
    documents = load_document_chunks(doc_dir) if doc_dir is not None else []
    corpus = video + documents
    ids = [c["chunk_id"] for c in corpus]
    by_id = {c["chunk_id"]: c for c in corpus}
    # Q&A 형제 확장용 인덱스. Q&A 소스가 없으면 빈 dict이고 확장은 아무 일도
    # 하지 않는다 — qa_id 없는 코퍼스에서 동작이 바뀌지 않음을 뜻한다.
    qa_index = build_qa_answer_index(corpus)

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
        verdict = gate_verdict(stats, gate_signal)
        # Both retrievers always run (no routing on query type); the gate decides
        # only whether the graph's chunks are admitted as evidence, and it never
        # sees them — score_gap above is computed from vector similarity alone.
        graph_chunks = search_graph(str(row["question"]))
        evidence_ids = (
            hybrid_merge(ranked, graph_chunks) if verdict == GATE_PASS
            else [cid for cid, _score in ranked]
        )
        # Q&A 형제 확장은 **여기서**, 게이트 통계(stats)와 판정(verdict)이 모두
        # 확정된 뒤에 일어난다. 확장이 랭킹이나 유사도 분포에 영향을 주면 게이트
        # 신호 결정이 무효화되므로, 근거 목록만 손대고 ranked/stats는 건드리지
        # 않는다. 이 순서는 테스트로 고정돼 있다.
        evidence_ids, expansion = expand_qa_siblings(evidence_ids, by_id, qa_index)
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
            # 확장이 무엇을 붙이고 무엇을 뺐는지 남긴다. 조용히 자르면
            # 커버리지를 과대평가하게 된다.
            "qa_expansion": expansion,
        })

    gold_rows = []
    for row in gold:
        relevant = set(gold_relevant_chunks(row, video, documents))
        ranked, stats = rank_one(str(row["question"]))
        first = next((r for r, (cid, _) in enumerate(ranked, start=1) if cid in relevant), None)
        verdict = gate_verdict(stats, gate_signal)
        graph_chunks = search_graph(str(row["question"]))
        evidence_ids = (
            hybrid_merge(ranked, graph_chunks) if verdict == GATE_PASS
            else [cid for cid, _score in ranked]
        )
        # 픽스처 경로와 같은 조립 규칙을 쓴다 — 두 경로가 근거를 다르게 모으면
        # 드리프트가 생긴다. first_relevant_rank는 ranked에서 이미 계산됐으므로
        # Hit@1/MRR은 확장의 영향을 받지 않는다.
        evidence_ids, expansion = expand_qa_siblings(evidence_ids, by_id, qa_index)
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
            "qa_expansion": expansion,
        })

    # 검색 지표는 정답 청크가 있는 질의로만 낸다. coverage: missing 질의는
    # 아무것도 검색되지 않는 것이 성공이므로 Hit@1/MRR의 분모에 넣으면 지표가
    # 뜻을 잃는다 — 게이트 판정(REFUSE인가)으로 따로 본다.
    scored = [r for r in gold_rows if r["relevant_chunk_count"] > 0]
    refuse_only = [r for r in gold_rows if r["relevant_chunk_count"] == 0]
    hit1 = sum(1 for r in scored if r["first_relevant_rank"] == 1)
    hit5 = sum(1 for r in scored if r["first_relevant_rank"])
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "run": {
            "model_name": MODEL_NAME,
            "top_k": TOP_K,
            "gate_signal": gate_signal,
            "gate_threshold": gate_signal_threshold(gate_signal),
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
            # 분모는 정답 청크가 있는 질의 수다. coverage: missing 질의는 빠진다.
            "scored_queries": len(scored),
            "refuse_only_queries": len(refuse_only),
            "hit@1": serialize_score(hit1 / len(scored)) if scored else None,
            "hit@5": serialize_score(hit5 / len(scored)) if scored else None,
            "mrr@5": serialize_score(
                sum(r["reciprocal_rank"] for r in scored) / len(scored) if scored else 0.0
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
    active_signal = payload["run"].get("gate_signal", "score_gap")
    active_threshold = payload["run"].get("gate_threshold", GATE_THRESHOLD)
    lines.append(
        "gate 신호는 `{} >= {}`이고 **조달 전과 동일**합니다. "
        "코퍼스가 막 바뀐 상태에서 신호나 임계값까지 같이 움직이면 두 효과가 한 측정에 섞입니다."
        .format(active_signal, active_threshold))

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
    parser.add_argument("--gate-signal", choices=GATE_SIGNALS, default=DEFAULT_GATE_SIGNAL,
                        help="default is margin_top5 as of 2026-08-25 (see the GATE_SIGNALS "
                             "comment) — score_gap is kept for comparison runs and because "
                             "generate_answers.py's separate classify_band() still uses it")
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
            gate_signal=args.gate_signal,
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
