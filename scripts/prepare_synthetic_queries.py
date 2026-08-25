"""Sample eligible chunks and emit a generation prompt for synthetic eval queries.

Stage 1 of 2. This script does the sampling (reproducible via --seed) and writes:
  - a prompt file to paste into an LLM
  - a mapping file so stage 2 can rebuild gold spans from the LLM's output

The LLM never sees chunk ids or timestamps. It only sees numbered passages, so
its output cannot leak identifiers that would make the eval trivially easy.

Both files this writes are untracked on purpose, and .gitignore now enforces it.
The prompt carries the passages verbatim — for the YouTube corpus that is subtitle
text, which docs/SOURCES.md says the platform's ToS forbids scraping — and the
mapping carries video_id with start_ms/end_ms, which is the recipe for locating
that text again. Both were committed and public until 2026-08-25
(reports/license_premise_audit_0825.md). Regenerate them locally when rerunning
stage 1; do not add them back to the repository.

Usage:
    uv run python scripts/prepare_synthetic_queries.py --count 20 --per-chunk 3
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_CHUNK_DIR = Path("data/processed/youtube/chunks")
DEFAULT_PROMPT_PATH = Path("data/eval/queries/_synthetic_prompt.md")
DEFAULT_MAPPING_PATH = Path("data/eval/queries/_synthetic_mapping.json")

# multi_span is excluded on purpose: it needs two gold spans, which cannot be
# derived from a single source chunk.
QUERY_TYPES = ("direct_lookup", "paraphrase", "symptom_to_solution", "concept")

TYPE_GUIDE = {
    "direct_lookup": "본문에 직접 나온 사실을 묻는 질문. 단, 본문의 표현을 그대로 베끼지 말 것.",
    "paraphrase": "본문과 뜻은 같지만 단어가 겹치지 않는 질문. 초보 견주가 쓸 법한 일상어로.",
    "symptom_to_solution": "증상이나 상황을 서술하고 해결책을 묻는 질문. 본문의 용어는 쓰지 말 것.",
    "concept": "본문이 설명하는 원리나 이유를 묻는 질문.",
}


class PrepareError(RuntimeError):
    """Raised when inputs are missing or malformed."""


def load_chunks(chunk_dir: Path) -> list[dict[str, Any]]:
    paths = sorted(chunk_dir.glob("*.jsonl"))
    if not paths:
        raise PrepareError(f"no chunk files under {chunk_dir}")
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise PrepareError(f"invalid chunk JSON at {path}:{line_number}") from exc
                for key in ("chunk_id", "video_id", "text", "start_ms", "end_ms"):
                    if key not in row:
                        raise PrepareError(f"chunk missing {key!r} at {path}:{line_number}")
                rows.append(row)
    rows.sort(key=lambda row: (row["video_id"], row["chunk_index"]))
    return rows


def sample_chunks(chunks: Sequence[dict[str, Any]], count: int, seed: int) -> list[dict[str, Any]]:
    eligible = [c for c in chunks if c.get("embedding_eligible")]
    if not eligible:
        raise PrepareError("no embedding_eligible chunk in the corpus")
    if count >= len(eligible):
        return list(eligible)
    return random.Random(seed).sample(eligible, count)


def build_prompt(selected: Sequence[dict[str, Any]], per_chunk: int) -> str:
    types = QUERY_TYPES[:per_chunk] if per_chunk <= len(QUERY_TYPES) else QUERY_TYPES
    lines: list[str] = []
    lines.append("아래는 강아지 훈련 유튜브 영상 자막에서 잘라낸 지문들입니다.")
    lines.append("각 지문마다 아래 유형의 질문을 하나씩 만들어 주세요.")
    lines.append("")
    for query_type in types:
        lines.append(f"- **{query_type}**: {TYPE_GUIDE[query_type]}")
    lines.append("")
    lines.append("규칙")
    lines.append("1. 질문의 답은 반드시 해당 지문 안에만 있어야 합니다.")
    lines.append("2. 지문에 등장한 단어를 그대로 쓰지 마세요. 뜻이 같은 다른 말로 바꾸세요.")
    lines.append("3. 실제 견주가 검색창에 칠 법한 자연스러운 한국어로 쓰세요.")
    lines.append("4. 지문을 읽지 않은 사람도 이해할 수 있는 질문이어야 합니다.")
    lines.append("   (\"이 영상에서\", \"위 내용에서\" 같은 표현 금지)")
    lines.append("5. 답이 여러 지문에 걸칠 것 같으면 그 지문은 건너뛰고 skip으로 표시하세요.")
    lines.append("")
    lines.append("출력은 JSON 배열 하나만. 설명이나 코드펜스 없이.")
    lines.append("```")
    lines.append('[{"passage": 1, "query_type": "direct_lookup", "question": "..."},')
    lines.append(' {"passage": 1, "query_type": "paraphrase", "question": "..."},')
    lines.append(' {"passage": 2, "query_type": "skip", "question": ""}]')
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    for index, chunk in enumerate(selected, start=1):
        lines.append(f"### 지문 {index}")
        lines.append(chunk["text"].strip())
        lines.append("")
    return "\n".join(lines)


def build_mapping(selected: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "youtube-synthetic-mapping-v1",
        "passages": [
            {
                "passage": index,
                "chunk_id": chunk["chunk_id"],
                "video_id": chunk["video_id"],
                "chunk_index": chunk["chunk_index"],
                "start_ms": chunk["start_ms"],
                "end_ms": chunk["end_ms"],
                "chapter_title": chunk.get("chapter_title", ""),
            }
            for index, chunk in enumerate(selected, start=1)
        ],
    }


def run(chunk_dir: Path, count: int, per_chunk: int, seed: int,
        prompt_path: Path, mapping_path: Path) -> None:
    chunks = load_chunks(chunk_dir)
    selected = sample_chunks(chunks, count, seed)

    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(build_prompt(selected, per_chunk), encoding="utf-8")
    mapping_path.write_text(
        json.dumps(build_mapping(selected), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"eligible chunks sampled: {len(selected)}")
    print(f"expected questions (max): {len(selected) * min(per_chunk, len(QUERY_TYPES))}")
    print(prompt_path)
    print(mapping_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--count", type=int, default=20, help="number of chunks to sample")
    parser.add_argument("--per-chunk", type=int, default=3, help="questions per chunk (max 4)")
    parser.add_argument("--seed", type=int, default=42, help="sampling seed, keep it for reproducibility")
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--mapping-path", type=Path, default=DEFAULT_MAPPING_PATH)
    args = parser.parse_args(argv)

    if args.count < 1:
        parser.error("--count must be positive")
    if not 1 <= args.per_chunk <= len(QUERY_TYPES):
        parser.error(f"--per-chunk must be between 1 and {len(QUERY_TYPES)}")

    try:
        run(args.chunk_dir, args.count, args.per_chunk, args.seed,
            args.prompt_path, args.mapping_path)
    except (OSError, PrepareError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
