"""Offline preview of the three demo Cypher queries against the folded graph.

This is NOT Neo4j output. It re-implements the same traversal in Python so the
"do the paths exist at all" question can be answered before the database exists,
and so a query can be checked for direction before anyone waits on a container.

Direction is the thing this file exists to catch. 감별필요 runs
(증상|문제행동) → (질환), so a disease name is always the arrow's target. The
first pass of these queries put the disease on the left and returned nothing from
a graph that had 19 matching edges; queries 1 and 2 therefore walk *into* the
named node, not out of it.

Usage:
    uv run python scripts/preview_queries.py
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_graph_neo4j import (  # noqa: E402
    DEFAULT_ALIASES,
    DEFAULT_EXTRACTIONS,
    build_graph,
    load_aliases,
)

MAX_HOPS = 2
LIMIT = 5


def label(key) -> str:
    return f"{key[0]}({key[1]})"


def incoming_paths(graph_in, target, allowed, max_hops):
    """Every path of length 1..max_hops that ends at `target`.

    Walks backwards along incoming edges, so the printed chain still reads
    left-to-right in the direction the edges actually point.
    """
    found = []
    stack = [(target, [])]
    while stack:
        node, trail = stack.pop()
        if len(trail) >= max_hops:
            continue
        for rtype, prev in graph_in.get(node, []):
            if rtype not in allowed:
                continue
            if prev == target or prev in [n for _, n in trail]:
                continue  # no revisiting
            step = [(prev, rtype)] + trail
            found.append(step)
            stack.append((prev, step))
    return found


def chain(steps, target) -> str:
    out = ""
    for node, rtype in steps:
        out += f"{label(node)} -[{rtype}]-> "
    return out + label(target)


def main() -> int:
    records = [json.loads(line) for line
               in DEFAULT_EXTRACTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    nodes, edges, unresolved = build_graph(records, load_aliases(DEFAULT_ALIASES))

    graph_in: dict = {}
    for (src, rtype, tgt) in edges:
        graph_in.setdefault(tgt, []).append((rtype, src))

    print(f"노드 {len(nodes)} · 엣지 {len(edges)} · 해소 실패 관계 {len(unresolved)}")

    print("\n" + "=" * 70)
    print("QUERY 1  (b)-[:감별필요|완화한다|금기 *1..2]->(a)  WHERE a.name CONTAINS '분리불안'")
    print("=" * 70)
    seeds = [k for k in nodes if "분리불안" in k[0]]
    print(f"시드 노드 {len(seeds)}개: {[label(s) for s in seeds]}")
    rows = [(t, p) for t in seeds
            for p in incoming_paths(graph_in, t, {"감별필요", "완화한다", "금기"}, MAX_HOPS)]
    print(f"경로 총 {len(rows)}개 (상위 {LIMIT}):")
    for target, steps in rows[:LIMIT]:
        print("  " + chain(steps, target))
    if not rows:
        print("  (없음)")

    print("\n" + "=" * 70)
    print("QUERY 2  (b)-[:감별필요]->(a)  WHERE a.name CONTAINS '슬개골'")
    print("=" * 70)
    seeds = [k for k in nodes if "슬개골" in k[0] or "주저앉" in k[0]]
    print(f"시드 노드 {len(seeds)}개: {[label(s) for s in seeds]}")
    rows2 = [(src, tgt) for tgt in seeds
             for rtype, src in graph_in.get(tgt, []) if rtype == "감별필요"]
    print(f"경로 총 {len(rows2)}개 (상위 {LIMIT}):")
    for src, tgt in rows2[:LIMIT]:
        print(f"  {label(src)} -[감별필요]-> {label(tgt)}")
    if not rows2:
        print("  (없음)")

    print("\n" + "=" * 70)
    print("QUERY 3  타입별 집계")
    print("=" * 70)
    node_types = collections.Counter(k[1] for k in nodes)
    rel_types = collections.Counter(r for (_, r, _) in edges)
    print("노드:")
    for key, count in node_types.most_common():
        print(f"  {key}: {count}")
    print(f"  합계: {sum(node_types.values())}")
    print("관계:")
    for key, count in rel_types.most_common():
        print(f"  {key}: {count}")
    print(f"  합계: {sum(rel_types.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
