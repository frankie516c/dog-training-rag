"""Extract entities and relations from corpus chunks for the GraphRAG pilot.

Stage 1 runs a hand-picked set of chunks so a person can read every extraction
before 77 of them exist. The set is written out in STAGE1_CHUNK_IDS rather than
sampled, because the point is to cover specific hard cases — an ASR-corrupted
chunk, a procedure with a contraindication, a four-stage symptom ladder, a symptom
list, and two ordinary video chunks that nothing was chosen for.

The chunk text is never edited. What the model sees is the text as stored plus its
heading_path and source metadata; anything the extraction gets wrong is a fact
about the prompt or the model, not about a cleaned-up input.

Model access is injected, the way scripts/generate_answers.py injects its answer
client, so the pipeline can be exercised without a key and the model is recorded
on every record rather than assumed.

Usage:
    uv run python scripts/extract_entities.py --stage 1 --dry-run   # prompts only
    uv run python scripts/extract_entities.py --stage 1 --model <name>
    uv run python scripts/extract_entities.py --stage 2 --model <name>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

DEFAULT_VIDEO_CHUNKS = Path("data/processed/youtube/chunks")
DEFAULT_DOC_CHUNKS = Path("data/processed/documents/chunks")
DEFAULT_OUT_DIR = Path("data/graph")
PROMPT_DRAFT = Path("prompts/entity_extraction_draft.md")

PROMPT_VERSION = "extraction-prompt-v1"
TEMPERATURE = 0.0
MAX_RETRIES = 1  # one retry on unparseable output, then quarantine

NODE_TYPES = ("문제행동", "훈련법", "증상", "질환", "견종", "연령대", "용품", "원칙")
EDGE_TYPES = ("완화한다", "악화시킨다", "선행조건", "금기", "감별필요")
CONFIDENCE = ("high", "medium", "low")
# Types that decide whether the training/medical split actually held.
MEDICAL_TYPES = ("증상", "질환")
TRAINING_TYPES = ("문제행동", "훈련법", "원칙")

# Stage 1, chosen to cover the cases worth seeing before scale.
# Prefixes, not full ids: the full hashes are resolved at load time and a prefix
# matching zero or more than one chunk is an error rather than a silent pick.
STAGE1_CHUNK_IDS = [
    ("chunk-8dd2b93c", "ASR 오기 실증 — '분리브라인/블리브라인' → 분리불안 정규화 대상"),
    ("chunk-98af0dd0", "허브 청크 — 여러 질문의 top-5에 반복 등장하는 범용 훈련 발화"),
    ("chunk-1c201183", "영상 훈련 청크 2 — 피부 민감도·둔감화 (훈련법 노드 확인용)"),
    ("docchunk-747cbb6f", "비마이펫 켄넬 STEP + TIP 금기 (선행조건·금기 엣지 확인용)"),
    ("docchunk-17ae8aab", "비마이펫 — 문을 닫으면 나올 수 없는 이동장 (용품 노드)"),
    ("docchunk-2131a61b", "YD 슬개골 1단계"),
    ("docchunk-70175c6b", "YD 슬개골 2단계"),
    ("docchunk-59c3017c", "YD 슬개골 3단계"),
    ("docchunk-4369dfe3", "YD 슬개골 4단계"),
    ("docchunk-5a1d8e23", "YD 외이염 증상 목록 (증상 노드 다중 추출)"),
    ("docchunk-c2e164c2", "AMC 밤에 짖는 — 치매·관절통증 감별 (감별필요 엣지 확인용)"),
    ("docchunk-188901e2", "베럴독 분리불안 — 증상 파악과 대처"),
]

SYSTEM_PROMPT = """당신은 강아지 훈련·행동 도메인의 지식 그래프 구축을 돕습니다.
주어진 청크 하나에서 엔티티와 관계를 추출해 JSON 하나로만 답하세요.
설명, 인사, 코드펜스 없이 JSON 객체 하나만 출력합니다."""

RULES = """## 노드 타입 (이 8개만 사용)
문제행동 | 훈련법 | 증상 | 질환 | 견종 | 연령대 | 용품 | 원칙

문제행동과 증상의 경계: 보호자가 고치려는 행동이면 문제행동, 몸 상태의 관찰
소견으로 언급되면 증상. 같은 표현이 문맥에 따라 갈립니다.

## 엣지 타입 (이 5개만 사용)
완화한다   (훈련법|원칙) → (문제행동|증상)
악화시킨다 (훈련법|원칙|용품) → (문제행동|증상)
선행조건   X → (훈련법)
금기       X → (훈련법)
감별필요   (증상|문제행동) → (질환)

감별필요는 반드시 증상/문제행동에서 질환으로 향합니다. 훈련법을 거치지 않습니다.
금기와 선행조건은 반대가 아닙니다. 선행조건이 빠지면 훈련이 덜 듣고, 금기를
어기면 상태가 나빠집니다. 문서가 둘을 구분하지 않으면 선행조건으로 두세요.

## ASR 정규화
이 코퍼스는 유튜브 STT라 ASR 오기·발음 뭉개짐이 있다. 표기가 아니라 문맥으로
엔티티를 판정해 표준 용어로 정규화하고, normalized_from 필드에 원표기를 기록하라.
예: '분리브라인'→'분리불안'. 문맥으로도 확신이 없으면 추출하지 말 것.
정규화하지 않았으면 normalized_from은 null입니다.

## 규칙
1. evidence는 청크 본문에서 그대로 잘라온 문자열입니다. 요약하거나 다듬지 마세요.
2. relations의 source/target은 이 청크의 entities에 있는 name이어야 합니다.
   청크 밖 엔티티와 연결하지 않습니다.
3. confidence는 high / medium / low. 확신이 없으면 추출하지 않는 것이 원칙이므로
   low는 "추출은 하되 사람이 봐야 함"이라는 뜻으로만 씁니다.
4. 추출할 것이 없으면 빈 배열을 반환합니다. 채우려고 만들지 마세요.

## 출력 형식
{"entities": [{"name": "", "type": "", "normalized_from": null, "evidence": "", "confidence": ""}],
 "relations": [{"source": "", "target": "", "type": "", "evidence": "", "confidence": ""}]}"""


class ExtractionError(RuntimeError):
    """Raised when inputs, settings or the model client are unusable."""


@dataclass(frozen=True)
class ClientInfo:
    model: str
    temperature: float = TEMPERATURE


class ExtractionClient(Protocol):
    """How an extraction is produced. Injected so the pipeline runs without a key."""

    @property
    def info(self) -> ClientInfo: ...

    def complete(self, system: str, prompt: str) -> tuple[str, dict[str, int]]:
        """Return the raw completion text and a token usage dict."""


@dataclass
class RunTally:
    calls: int = 0
    retries: int = 0
    quarantined: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


def load_chunks(video_dir: Path, doc_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(video_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("embedding_eligible"):
                    row["source_kind"] = "video"
                    rows.append(row)
    for path in sorted(doc_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["source_kind"] = "document"
                rows.append(row)
    if not rows:
        raise ExtractionError("no chunk found; run the ingest first")
    return rows


def resolve_prefixes(
    chunks: Sequence[dict[str, Any]], wanted: Sequence[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Resolve id prefixes to chunks, refusing an ambiguous or missing prefix."""
    by_id = {c["chunk_id"]: c for c in chunks}
    picked: list[dict[str, Any]] = []
    for prefix, why in wanted:
        matches = [c for cid, c in by_id.items() if cid.startswith(prefix)]
        if len(matches) != 1:
            raise ExtractionError(
                f"chunk prefix {prefix!r} matched {len(matches)} chunks; "
                "the stage 1 set must name exactly one each"
            )
        chunk = dict(matches[0])
        chunk["stage1_reason"] = why
        picked.append(chunk)
    return picked


def source_block(chunk: dict[str, Any]) -> str:
    if chunk["source_kind"] == "document":
        return "\n".join([
            f"- 출처: 문서 / {chunk['doc_id']}",
            f"- 출처 URL: {chunk['source_url']}",
            f"- heading_path: {' > '.join(chunk.get('heading_path', []))}",
            f"- 슬롯: {chunk.get('slot')}",
        ])
    return "\n".join([
        f"- 출처: 영상 자막 / {chunk['video_id']} #{chunk['chunk_index']}",
        f"- 챕터: {chunk.get('chapter_title', '')}",
        "- 주의: 이 텍스트는 유튜브 STT 결과라 ASR 오기가 있을 수 있습니다.",
    ])


def build_prompt(chunk: dict[str, Any]) -> str:
    return "\n\n".join([
        RULES,
        "## 이 청크의 출처",
        source_block(chunk),
        "## 청크 본문",
        chunk["text"],
        "위 본문에서 엔티티와 관계를 추출해 JSON 하나로만 답하세요.",
    ])


JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def parse_extraction(raw: str) -> dict[str, Any]:
    """Parse the completion, tolerating a code fence but nothing more inventive."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    match = JSON_BLOCK.search(text)
    if not match:
        raise ValueError("no JSON object in the completion")
    return json.loads(match.group(0))


def validate_extraction(payload: dict[str, Any], chunk_text: str) -> list[str]:
    """Schema and grounding checks. Returns the problems found, empty if clean."""
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["top level is not an object"]
    for key in ("entities", "relations"):
        if not isinstance(payload.get(key), list):
            problems.append(f"{key} must be an array")
    if problems:
        return problems

    names: set[str] = set()
    for index, entity in enumerate(payload["entities"]):
        where = f"entities[{index}]"
        if not isinstance(entity, dict):
            problems.append(f"{where}: not an object")
            continue
        name = entity.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{where}: name must be a non-empty string")
        else:
            names.add(name)
        if entity.get("type") not in NODE_TYPES:
            problems.append(f"{where}: type {entity.get('type')!r} is not one of {list(NODE_TYPES)}")
        if entity.get("confidence") not in CONFIDENCE:
            problems.append(f"{where}: confidence {entity.get('confidence')!r} is invalid")
        normalized = entity.get("normalized_from", None)
        if normalized is not None and not isinstance(normalized, str):
            problems.append(f"{where}: normalized_from must be null or a string")
        evidence = entity.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            problems.append(f"{where}: evidence must be a non-empty string")
        elif not _grounded(evidence, chunk_text):
            # The rule the whole extraction rests on: a model that can compose its
            # own supporting sentence can support anything.
            problems.append(f"{where}: evidence is not a substring of the chunk")

    for index, relation in enumerate(payload["relations"]):
        where = f"relations[{index}]"
        if not isinstance(relation, dict):
            problems.append(f"{where}: not an object")
            continue
        if relation.get("type") not in EDGE_TYPES:
            problems.append(f"{where}: type {relation.get('type')!r} is not one of {list(EDGE_TYPES)}")
        for end in ("source", "target"):
            if relation.get(end) not in names:
                problems.append(f"{where}: {end} {relation.get(end)!r} is not an entity of this chunk")
        if relation.get("confidence") not in CONFIDENCE:
            problems.append(f"{where}: confidence {relation.get('confidence')!r} is invalid")
        evidence = relation.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            problems.append(f"{where}: evidence must be a non-empty string")
        elif not _grounded(evidence, chunk_text):
            problems.append(f"{where}: evidence is not a substring of the chunk")
    return problems


def _grounded(evidence: str, chunk_text: str) -> bool:
    """Substring check, ignoring whitespace differences only."""
    squash = lambda s: "".join(s.split())
    return squash(evidence) in squash(chunk_text)


def extract_one(
    chunk: dict[str, Any], client: ExtractionClient, tally: RunTally
) -> dict[str, Any]:
    prompt = build_prompt(chunk)
    attempts: list[dict[str, Any]] = []
    for attempt in range(MAX_RETRIES + 1):
        started = time.perf_counter()
        raw, usage = client.complete(SYSTEM_PROMPT, prompt)
        tally.calls += 1
        tally.seconds += time.perf_counter() - started
        tally.input_tokens += int(usage.get("input_tokens", 0))
        tally.output_tokens += int(usage.get("output_tokens", 0))
        if attempt:
            tally.retries += 1
        try:
            payload = parse_extraction(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            attempts.append({"attempt": attempt + 1, "error": f"parse: {exc}", "raw": raw[:2000]})
            continue
        problems = validate_extraction(payload, chunk["text"])
        if problems:
            attempts.append({"attempt": attempt + 1, "error": "; ".join(problems[:8]),
                             "raw": raw[:2000]})
            continue
        return {
            "chunk_id": chunk["chunk_id"],
            "source_kind": chunk["source_kind"],
            "doc_id": chunk.get("doc_id"),
            "video_id": chunk.get("video_id"),
            "heading_path": chunk.get("heading_path"),
            "chapter_title": chunk.get("chapter_title"),
            "slot": chunk.get("slot"),
            "stage1_reason": chunk.get("stage1_reason"),
            "model_version": client.info.model,
            "prompt_version": PROMPT_VERSION,
            "temperature": client.info.temperature,
            "attempts": attempt + 1,
            "entities": payload["entities"],
            "relations": payload["relations"],
        }
    tally.quarantined.append({
        "chunk_id": chunk["chunk_id"],
        "model_version": client.info.model,
        "prompt_version": PROMPT_VERSION,
        "attempts": attempts,
    })
    return {}


def run(
    chunks: Sequence[dict[str, Any]],
    client: ExtractionClient,
    out_path: Path,
    quarantine_path: Path,
    log_path: Path,
) -> dict[str, Any]:
    tally = RunTally()
    records = []
    for index, chunk in enumerate(chunks, start=1):
        record = extract_one(chunk, client, tally)
        if record:
            records.append(record)
        print(f"  [{index}/{len(chunks)}] {chunk['chunk_id'][:22]} "
              f"{'ok' if record else 'QUARANTINED'}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf-8"))
    quarantine_path.write_bytes(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in tally.quarantined)
        .encode("utf-8"))
    log = {
        "model_version": client.info.model,
        "prompt_version": PROMPT_VERSION,
        "temperature": client.info.temperature,
        "chunks": len(chunks),
        "extracted": len(records),
        "quarantined": len(tally.quarantined),
        "calls": tally.calls,
        "retries": tally.retries,
        "input_tokens": tally.input_tokens,
        "output_tokens": tally.output_tokens,
        "seconds": round(tally.seconds, 2),
    }
    log_path.write_bytes(json.dumps(log, ensure_ascii=False, indent=2).encode("utf-8"))
    return {"records": records, "log": log, "quarantined": tally.quarantined}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=int, choices=(1, 2), required=True)
    parser.add_argument("--model", default=None, help="model id recorded on every record")
    parser.add_argument("--dry-run", action="store_true",
                        help="write the prompts and exit; no model is called")
    parser.add_argument("--video-chunks", type=Path, default=DEFAULT_VIDEO_CHUNKS)
    parser.add_argument("--doc-chunks", type=Path, default=DEFAULT_DOC_CHUNKS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        everything = load_chunks(args.video_chunks, args.doc_chunks)
        chunks = (
            resolve_prefixes(everything, STAGE1_CHUNK_IDS) if args.stage == 1 else everything
        )
        args.out_dir.mkdir(parents=True, exist_ok=True)
        if args.dry_run:
            path = args.out_dir / f"prompts_stage{args.stage}.md"
            body = "\n\n---\n\n".join(
                f"## {c['chunk_id']}\n\n```\n{build_prompt(c)}\n```" for c in chunks)
            path.write_bytes(
                (f"# extraction prompts (stage {args.stage}, {PROMPT_VERSION})\n\n"
                 f"청크 {len(chunks)}개. 모델 호출 없음.\n\n" + body).encode("utf-8"))
            print(f"청크 {len(chunks)}개 프롬프트만 기록: {path}")
            return 0
        if not args.model:
            raise ExtractionError("--model is required unless --dry-run is used")
        raise ExtractionError(
            f"no extraction client is wired for model {args.model!r}. "
            "Add the provider adapter before running stage "
            f"{args.stage}; --dry-run works without one."
        )
    except (OSError, ExtractionError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
