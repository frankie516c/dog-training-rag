"""Load the stage 2 extraction into Neo4j for the GraphRAG demo.

DEPRECATED (2026-08-24): GraphRAG was abandoned for this repo — see
docs/decision_graphrag_abandoned_0824.md. Kept, not deleted, as methodological
evidence of how that decision was reached.

Node identity is (name, type), not name alone: 증상 "통증" and 문제행동 "통증" are
different things in this schema and merging them would invent an edge that no
chunk supports. Edges are MERGEd on (source, type, target) so re-running the
loader is idempotent rather than duplicating the graph.

Surface variants are folded through data/graph/entity_aliases.json before the
MERGE. The original spelling is not discarded — it goes on the node's `aliases`
list, so a later reader can tell that 슬개골탈구 was written two ways rather than
having to trust that the fold was correct.

Quarantined chunks are not loaded. They failed the evidence-grounding check, and
a node whose provenance is an ungrounded extraction is worse than a missing node.

Usage:
    uv run python scripts/load_graph_neo4j.py --dry-run   # fold only, no connection
    uv run python scripts/load_graph_neo4j.py             # load
    uv run python scripts/load_graph_neo4j.py --wipe      # delete the graph first
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_EXTRACTIONS = Path("data/graph/extractions_stage2.jsonl")
DEFAULT_ALIASES = Path("data/graph/entity_aliases.json")
DEFAULT_URI = "bolt://localhost:7687"
DEFAULT_DATABASE = "neo4j"
ENV_PASSWORD = "NEO4J_PASSWORD"

# Relationship types are Korean and are written into the query as identifiers, so
# they are whitelisted rather than interpolated from whatever the file contains.
EDGE_TYPES = ("완화한다", "악화시킨다", "선행조건", "금기", "감별필요")


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(name: str, aliases: dict[str, str]) -> str:
    return aliases.get(name, name)


def build_graph(records, aliases):
    """Fold the per-chunk extractions into node and edge tables.

    Returns (nodes, edges, unresolved). `unresolved` holds relations whose source
    or target is not an entity of the same chunk; the prompt forbids those, so
    they are reported rather than silently dropped.
    """
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    edges: dict[Any, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []

    for rec in records:
        chunk_id = rec["chunk_id"]
        # Within a chunk a relation names entities by `name` only, so the type has
        # to come from that chunk's own entity list.
        by_name: dict[str, str] = {}
        for ent in rec["entities"]:
            surface = ent["name"]
            name = canonical(surface, aliases)
            key = (name, ent["type"])
            by_name[surface] = ent["type"]
            node = nodes.setdefault(key, {
                "name": name, "type": ent["type"],
                "source_chunks": [], "aliases": [],
            })
            if chunk_id not in node["source_chunks"]:
                node["source_chunks"].append(chunk_id)
            for variant in (surface, ent.get("normalized_from")):
                if variant and variant != name and variant not in node["aliases"]:
                    node["aliases"].append(variant)

        for rel in rec["relations"]:
            src_surface, tgt_surface = rel["source"], rel["target"]
            if src_surface not in by_name or tgt_surface not in by_name:
                unresolved.append({"chunk_id": chunk_id, "reason": "not an entity of this chunk", **rel})
                continue
            if rel["type"] not in EDGE_TYPES:
                unresolved.append({"chunk_id": chunk_id, "reason": "unknown type", **rel})
                continue
            src = (canonical(src_surface, aliases), by_name[src_surface])
            tgt = (canonical(tgt_surface, aliases), by_name[tgt_surface])
            key = (src, rel["type"], tgt)
            edge = edges.setdefault(key, {
                "source": src, "target": tgt, "type": rel["type"],
                "source_chunks": [],
            })
            if chunk_id not in edge["source_chunks"]:
                edge["source_chunks"].append(chunk_id)

    return nodes, edges, unresolved


def load(driver, database: str, nodes: dict, edges: dict, wipe: bool) -> None:
    with driver.session(database=database) as session:
        if wipe:
            session.run("MATCH (n) DETACH DELETE n")
        session.run(
            "CREATE CONSTRAINT entity_identity IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE"
        )
        for node in nodes.values():
            session.run(
                "MERGE (e:Entity {name: $name, type: $type}) "
                "SET e.source_chunks = $source_chunks, e.aliases = $aliases, "
                "    e.chunk_count = size($source_chunks)",
                name=node["name"], type=node["type"],
                source_chunks=node["source_chunks"], aliases=node["aliases"],
            )
        for edge in edges.values():
            (sname, stype) = edge["source"]
            (tname, ttype) = edge["target"]
            rel_type = edge["type"]
            if rel_type not in EDGE_TYPES:      # belt and braces: never interpolate
                raise ValueError(f"refusing to write unknown relationship type {rel_type!r}")
            query = (
                "MATCH (a:Entity {name: $sname, type: $stype}) "
                "MATCH (b:Entity {name: $tname, type: $ttype}) "
                "MERGE (a)-[r:" + "`" + rel_type + "`" + "]->(b) "
                "SET r.source_chunks = $source_chunks"
            )
            session.run(
                query,
                sname=sname, stype=stype, tname=tname, ttype=ttype,
                source_chunks=edge["source_chunks"],
            )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extractions", type=Path, default=DEFAULT_EXTRACTIONS)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--wipe", action="store_true",
                        help="DETACH DELETE the whole graph before loading")
    parser.add_argument("--dry-run", action="store_true",
                        help="fold the graph and report counts; no connection")
    args = parser.parse_args(argv)

    records = [json.loads(l) for l in
               args.extractions.read_text(encoding="utf-8").splitlines() if l.strip()]
    aliases = load_aliases(args.aliases)
    nodes, edges, unresolved = build_graph(records, aliases)

    by_type: dict[str, int] = defaultdict(int)
    for node in nodes.values():
        by_type[node["type"]] += 1
    by_rel: dict[str, int] = defaultdict(int)
    for edge in edges.values():
        by_rel[edge["type"]] += 1

    print(f"청크 {len(records)} · 노드 {len(nodes)} · 엣지 {len(edges)} · "
          f"해소 실패 관계 {len(unresolved)}")
    print("노드:", dict(sorted(by_type.items(), key=lambda kv: -kv[1])))
    print("엣지:", dict(sorted(by_rel.items(), key=lambda kv: -kv[1])))

    if args.dry_run:
        return 0

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("error: neo4j driver required (`uv add neo4j`)", file=sys.stderr)
        return 1
    from dotenv import dotenv_values

    password = (dotenv_values(args.env) or {}).get(ENV_PASSWORD)
    if not password:
        print(f"error: {ENV_PASSWORD} not in {args.env}", file=sys.stderr)
        return 1

    driver = GraphDatabase.driver(args.uri, auth=(args.user, password))
    try:
        driver.verify_connectivity()
        load(driver, args.database, nodes, edges, args.wipe)
    finally:
        driver.close()
    print(f"적재 완료 → {args.uri}/{args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
