"""Dump 질환·증상 entities from the frozen stage-2 extraction into a medical lexicon.

Reads only frozen/frozen_stage2_0820.jsonl. Not data/graph/extractions_stage2.jsonl,
even though the two currently hold identical bytes: the live path is what
scripts/load_graph_neo4j.py and scripts/run_combined_retrieval_eval.py refresh on a
re-extraction, and this guardrail's vocabulary must not change quietly just because
someone reran the graph. If the frozen snapshot is ever superseded, this script's
FROZEN_STAGE2 constant is the one line to update, and the new file's fingerprint
belongs in a new frozen/ doc alongside it.

No curation happens here. Every entity whose "type" is 질환 or 증상 is included,
deduplicated by exact string match. Some of these names are broad domestic-training
vocabulary that happens to share a word with a symptom (e.g. 짖음, 배회) — that is a
property of the source extraction, not something this script is allowed to trim.
scripts/evaluate_medical_guardrail.py measures what that broadness actually costs in
false positives; this script only dumps.

Usage:
    uv run python scripts/build_medical_lexicon.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FROZEN_STAGE2 = Path("frozen/frozen_stage2_0820.jsonl")
DEFAULT_OUT = Path("data/guardrail/medical_terms_v1.json")

LEXICON_SCHEMA_VERSION = "guardrail-medical-terms-v1"
SOURCE_ENTITY_TYPES = ("질환", "증상")


class LexiconError(RuntimeError):
    """Raised when the frozen source is missing or unusable."""


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise LexiconError(f"file not found: {path}")
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise LexiconError(f"invalid JSON at {path}:{number}") from exc
    return out


def collect_terms(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """entity type -> sorted unique entity names, for every type in SOURCE_ENTITY_TYPES."""
    seen: dict[str, set[str]] = {t: set() for t in SOURCE_ENTITY_TYPES}
    for row in rows:
        for entity in row.get("entities", []):
            entity_type = entity.get("type")
            name = entity.get("name")
            if entity_type in seen and isinstance(name, str) and name.strip():
                seen[entity_type].add(name)
    return {t: sorted(names) for t, names in seen.items()}


def build_lexicon(source: Path, generated_at: str) -> dict[str, Any]:
    rows = _rows(source)
    by_type = collect_terms(rows)
    flat = sorted(set().union(*by_type.values())) if by_type else []
    return {
        "schema_version": LEXICON_SCHEMA_VERSION,
        "purpose": (
            "입력 질문이 의료 감별이 필요한 질문인지 판정하기 위한 어휘 사전. "
            "훈련 방법상 위해 조언(강제 진입 등)은 이 사전의 범위 밖이며 별도 방어가 필요하다."
        ),
        "source": source.as_posix(),
        "source_entity_types": list(SOURCE_ENTITY_TYPES),
        "generated_at": generated_at,
        "curation": "none — every matching entity name is included as extracted, deduplicated only",
        "term_count": len(flat),
        "terms": flat,
        "terms_by_type": by_type,
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    source = FROZEN_STAGE2
    out_path = DEFAULT_OUT
    if argv:
        out_path = Path(argv[0])
    try:
        lexicon = build_lexicon(source, datetime.now(timezone.utc).astimezone().isoformat())
    except LexiconError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(json.dumps(lexicon, ensure_ascii=False, indent=2).encode("utf-8"))
    print(f"source: {source}")
    for entity_type, names in lexicon["terms_by_type"].items():
        print(f"  {entity_type}: {len(names)}개")
    print(f"total unique terms: {lexicon['term_count']}")
    print(f"written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
