"""Generate answers from retrieved chunks, so the grounding can be judged.

The retrieval evaluation stops at "was the right chunk ranked highly". It cannot
see the failure this stage exists to measure: an LLM handed five unrelated chunks
and answering anyway. The output of this script is what an LLM-as-a-judge pass
scores, so every record carries what the judge needs to rule on grounding — the
question, the chunks the model actually saw, the band the question fell into, and
which prompt produced the answer.

Retrieval is imported from evaluate_youtube_retrieval rather than rewritten, so an
answer is generated from exactly the ranking the evaluation measured: same model,
same prefixes, same tie-break.

Usage:
    uv run python scripts/generate_answers.py --queries <path> --dry-run
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence


DEFAULT_QUERIES = Path("data/eval/queries/out_of_corpus_queries.json")
DEFAULT_CHUNK_DIR = Path("data/processed/youtube/chunks")
DEFAULT_OUT_DIR = Path("data/eval/generation")

GENERATION_SCHEMA_VERSION = "youtube-generation-v1"
EVAL_QUERY_SCHEMA = "youtube-eval-query-v1"
OUT_OF_CORPUS_SCHEMA = "youtube-out-of-corpus-v1"
# The shape a person hands back after running the prompts through a model.
# backfill_answers.py reads it; the bundle prints it as a ready-to-fill template.
ANSWERS_SCHEMA_VERSION = "youtube-generation-answers-v1"

# Bands, not one cutoff. score_gap (top1 - corpus mean) does not separate the two
# populations cleanly, measured over the answerable runs and the out-of-corpus set:
#
#   answerable, answer found   n=50   min .0127   median .0349
#   out of corpus              n=14   median .0222   max .0402
#
# The ranges overlap across .0127-.0402, so any single threshold either refuses
# good questions or answers unanswerable ones. Splitting the overlap into three
# bands keeps the confident ends clean and marks the middle as what it is:
#
#   gap <  REFUSE_BELOW        refuse without calling the model at all
#   REFUSE_BELOW <= gap < ANSWER_AT_OR_ABOVE
#                              answer, but tell the reader the evidence is thin
#   gap >= ANSWER_AT_OR_ABOVE  answer normally
#
# What these two values actually buy, counted over the three populations:
#
#                        refuse   hedge   answer
#   answerable, found       2       5       43     (n=50)
#   answerable, missed      2       4        7     (n=13)
#   out of corpus           2       8        4     (n=14)
#
# So the top band is 43/54 answerable, and 10 of 14 unanswerable questions are at
# least marked. The 4 that still reach `answer` are the reason this script exists:
# no gap threshold catches them, so the judge pass has to see what the model does
# when handed unrelated chunks. They are a starting point to argue with, not a
# tuned result — override them with the CLI flags once judged data says better.
REFUSE_BELOW = 0.018
ANSWER_AT_OR_ABOVE = 0.024

BANDS = ("refuse", "hedge", "answer")

# Bump the version whenever the wording below changes: an answer is only
# interpretable next to the prompt that produced it.
PROMPT_VERSION = "grounded-answer-ko-v1"

REFUSAL_TEXT = (
    "제공된 자료에는 이 질문에 답할 내용이 없습니다. "
    "검색된 자료가 질문과 충분히 관련되어 있지 않아 답변을 생성하지 않았습니다."
)

PROMPT_RULES = (
    "1. 아래 <자료>에 실제로 적혀 있는 내용만으로 답하세요.",
    "2. 자료에 답이 없으면 \"제공된 자료에는 이 질문에 대한 내용이 없습니다\"라고 답하고, 추측하지 마세요.",
    "3. 자료 밖의 일반 지식이나 상식으로 빈칸을 채우지 마세요. 그럴듯한 문장을 만드는 것보다 없다고 말하는 것이 낫습니다.",
    "4. 답변에 쓴 자료를 [1]처럼 번호로 표시하세요.",
)

HEDGE_RULE = (
    "5. 아래 자료는 질문과의 관련성이 낮게 측정되었습니다. 답변 맨 앞에 "
    "\"[근거 약함] 아래 답변은 관련성이 낮은 자료에 기반합니다\"를 그대로 넣고, "
    "단정적인 어조를 쓰지 마세요."
)

# Demo-only, minimal: a single owner profile injected into the generation prompt
# so the model can phrase an answer in context (breed, age, ...) without treating
# it as evidence. Never threaded into retrieval, the graph search, hybrid merge or
# the score_gap gate in run_combined_retrieval_eval.py — build_prompt() is the only
# place a profile is read.
PROFILE_SCHEMA_VERSION = "demo-profile-v1"
PROFILE_FIELDS = ("견종", "나이", "몸무게", "기존질환", "비고")

PROFILE_NOTE = (
    "아래 프로필은 질문자가 알려준 반려견의 상황 정보입니다. 근거 자료가 아니므로 "
    "답변의 근거로 쓰지 마세요. 답변 내용은 반드시 <자료>에서만 가져오고, 프로필에 "
    "적힌 질환명이 있어도 그것을 근거 없이 진단처럼 언급하지 마세요."
)


class GenerationError(RuntimeError):
    """Raised when inputs, settings or the answer client are unusable."""


def _load_retrieval() -> Any:
    """Import the evaluator, whatever the working directory is.

    Reused rather than reimplemented: the point of this script is to answer from
    the ranking the evaluation actually measured, so the model, the prefixes and
    the tie-break have to be the same code, not the same intent.
    """
    name = "evaluate_youtube_retrieval"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise GenerationError(f"cannot import retrieval code from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


retrieval = _load_retrieval()


@dataclass(frozen=True)
class ClientInfo:
    name: str
    prompt_version: str = PROMPT_VERSION


class AnswerClient(Protocol):
    """How an answer is produced. Injected so tests can supply a deterministic fake.

    Mirrors the Encoder protocol in the evaluator: the expensive, non-deterministic
    dependency sits behind a two-method interface, and nothing else in the script
    knows whether a model, a person or a stub is on the other side.
    """

    @property
    def info(self) -> ClientInfo: ...

    def complete(self, prompt: str, record: dict[str, Any]) -> str | None: ...


class DryRunClient:
    """Writes each prompt to a file instead of calling a model.

    The intended flow while there is no API key: run this, paste a prompt into
    whatever model you have access to, and put the reply back into the JSONL as
    `answer`. The answer field stays null so an unanswered record can never be
    mistaken for a model that chose to say nothing.
    """

    def __init__(self, prompt_dir: Path):
        self.prompt_dir = prompt_dir
        self.info = ClientInfo(name="dry-run")
        self.written: list[Path] = []

    def complete(self, prompt: str, record: dict[str, Any]) -> str | None:
        self.prompt_dir.mkdir(parents=True, exist_ok=True)
        path = self.prompt_dir / f"{record['query_id']}.md"
        retrieval.write_text(prompt, path)
        self.written.append(path)
        record["prompt_path"] = path.as_posix()
        return None


def build_client(mode: str, prompt_dir: Path) -> AnswerClient:
    """Pick the client for a run. The seam where a real API client will plug in.

    Adding one means writing a class with `info` and `complete` — read the key from
    the environment, call the model, return its text — and returning it here. No
    other part of this script needs to change, and the fake used by the tests
    already proves the seam holds.
    """
    if mode == "dry-run":
        return DryRunClient(prompt_dir)
    raise GenerationError(
        f"unknown --mode {mode!r}. Only 'dry-run' is implemented: no API client is "
        "configured in this repo yet. See build_client() for where to add one."
    )


def classify_band(gap: float, refuse_below: float = REFUSE_BELOW,
                  answer_at_or_above: float = ANSWER_AT_OR_ABOVE) -> str:
    """Which of the three bands a score_gap falls into. Boundaries are inclusive up."""
    if gap < refuse_below:
        return "refuse"
    if gap < answer_at_or_above:
        return "hedge"
    return "answer"


def validate_thresholds(refuse_below: float, answer_at_or_above: float) -> None:
    if not 0 <= refuse_below <= answer_at_or_above:
        raise GenerationError(
            "thresholds must satisfy 0 <= --refuse-below <= --answer-at-or-above "
            f"(got {refuse_below} and {answer_at_or_above})"
        )


def load_query_set(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Read either query schema and say which one it was.

    The out-of-corpus set has no gold span by construction: for those questions the
    correct answer is a refusal, which is exactly what this stage has to be able to
    observe. Both shapes are normalized to (query_id, question) here so nothing
    downstream has to branch on the schema.
    """
    if not path.is_file():
        raise GenerationError(f"file not found: {path}")
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()

    if stripped.startswith("{") and OUT_OF_CORPUS_SCHEMA in text:
        payload = json.loads(text)
        if payload.get("schema_version") != OUT_OF_CORPUS_SCHEMA:
            raise GenerationError(f"{path}: schema_version must be {OUT_OF_CORPUS_SCHEMA!r}")
        rows = payload.get("queries")
        if not isinstance(rows, list) or not rows:
            raise GenerationError(f"{path}: no queries")
        queries = []
        for row in rows:
            for key in ("query_id", "question"):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise GenerationError(f"{path}: every query needs a non-empty {key}")
            queries.append(dict(row))
        return queries, OUT_OF_CORPUS_SCHEMA

    queries = retrieval.load_queries(path)
    for index, row in enumerate(queries, start=1):
        if row.get("schema_version") != EVAL_QUERY_SCHEMA:
            raise GenerationError(
                f"{path}: query #{index} has schema_version {row.get('schema_version')!r}; "
                f"expected {EVAL_QUERY_SCHEMA!r} or a {OUT_OF_CORPUS_SCHEMA!r} document"
            )
    return queries, EVAL_QUERY_SCHEMA


def load_profile(path: Path) -> dict[str, Any]:
    """Read and validate a demo owner profile (see data/profiles/demo_profile_v1.json)."""
    if not path.is_file():
        raise GenerationError(f"profile file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise GenerationError(f"{path}: schema_version must be {PROFILE_SCHEMA_VERSION!r}")
    for key in PROFILE_FIELDS:
        if key not in payload:
            raise GenerationError(f"{path}: missing field {key!r}")
    if not isinstance(payload["기존질환"], list) or not all(
        isinstance(item, str) for item in payload["기존질환"]
    ):
        raise GenerationError(f"{path}: 기존질환 must be an array of strings")
    return payload


def format_profile_block(profile: dict[str, Any]) -> str:
    """The <프로필> block build_prompt inserts ahead of <자료> when a profile is given."""
    conditions = profile["기존질환"]
    conditions_text = ", ".join(conditions) if conditions else "없음"
    return "\n".join(
        [
            "<프로필>",
            PROFILE_NOTE,
            "",
            f"견종: {profile['견종']}",
            f"나이: {profile['나이']}",
            f"몸무게: {profile['몸무게']}",
            f"기존 질환: {conditions_text}",
            f"비고: {profile['비고']}",
            "</프로필>",
        ]
    )


def build_prompt(
    question: str,
    chunks: Sequence[dict[str, Any]],
    band: str,
    profile: dict[str, Any] | None = None,
) -> str:
    """The generation prompt. Same wording for every band except the hedge rule.

    profile is None by default: omitting it (or passing None) reproduces the
    pre-profile prompt byte-for-byte — no profile-shaped gap in the middle of the
    text, no empty <프로필></프로필> block.
    """
    rules = list(PROMPT_RULES)
    if band == "hedge":
        rules.append(HEDGE_RULE)
    sources = []
    for position, chunk in enumerate(chunks, start=1):
        title = chunk.get("chapter_title", "")
        header = f"[{position}] ({chunk['video_id']} #{chunk['chunk_index']}"
        header += f" · {title})" if title else ")"
        sources.append(f"{header}\n{chunk['text']}")
    lines = [
        "아래 <자료>만 근거로 질문에 답하세요.",
        "",
        "규칙:",
        *rules,
        "",
    ]
    if profile is not None:
        lines += [format_profile_block(profile), ""]
    lines += [
        "<자료>",
        "",
        "\n\n".join(sources),
        "",
        "</자료>",
        "",
        f"질문: {question}",
    ]
    return "\n".join(lines)


def answered_records(path: Path) -> list[str]:
    """query_ids in an existing answers file that already carry a generated answer."""
    if not path.is_file():
        return []
    filled = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("generated") and row.get("answer"):
            filled.append(str(row.get("query_id")))
    return filled


def build_bundle(records: Sequence[dict[str, Any]], prompts: dict[str, str]) -> str:
    """One file holding every prompt that needs a model, plus the reply template.

    The dry-run flow is a person carrying prompts to a model by hand. One file to
    copy from beats twelve, and shipping the answer template next to the prompts
    means the reply comes back in the shape backfill_answers.py already reads —
    including the prompt version, which is what stops answers from two different
    prompts being scored as one batch.
    """
    pending = [row for row in records if row["query_id"] in prompts]
    lines = [
        f"# 생성 프롬프트 묶음 ({len(pending)}건)",
        "",
        f"프롬프트 버전: `{PROMPT_VERSION}`",
        "",
        "각 프롬프트를 LLM에 그대로 붙여넣고, 받은 답변을 맨 아래 템플릿의 해당 "
        "query_id 자리에 채우세요. refuse 구간은 모델을 호출하지 않으므로 여기 없습니다.",
        "",
    ]
    for row in pending:
        lines += [
            "---",
            "",
            f"## {row['query_id']} · band: {row['band']} · gap: {row['score_gap']}",
            "",
            "```",
            prompts[row["query_id"]],
            "```",
            "",
        ]
    template = {
        "schema_version": ANSWERS_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "answers": {row["query_id"]: "" for row in pending},
    }
    lines += [
        "---",
        "",
        "## 답변 템플릿",
        "",
        "이 JSON을 파일로 저장한 뒤:",
        "",
        "```",
        "uv run python scripts/backfill_answers.py --answers <파일> --target <생성 산출물>",
        "```",
        "",
        "```json",
        json.dumps(template, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def generate(
    queries_path: Path = DEFAULT_QUERIES,
    chunk_dir: Path = DEFAULT_CHUNK_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    mode: str = "dry-run",
    top_k: int = retrieval.DEFAULT_TOP_K,
    device: str = retrieval.DEFAULT_DEVICE,
    refuse_below: float = REFUSE_BELOW,
    answer_at_or_above: float = ANSWER_AT_OR_ABOVE,
    encoder: Any | None = None,
    client: AnswerClient | None = None,
    bundle: bool = False,
    force: bool = False,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_thresholds(refuse_below, answer_at_or_above)
    queries, source_schema = load_query_set(queries_path)
    expected_refusal = source_schema == OUT_OF_CORPUS_SCHEMA

    chunks = retrieval.load_chunks(chunk_dir)
    corpus = retrieval.eligible_chunks(chunks)
    if not corpus:
        raise GenerationError("no embedding_eligible chunk in the corpus")

    # Answers backfilled by hand cannot be regenerated: they came from a model
    # session that no longer exists. Re-running over them silently would destroy
    # the one part of this artifact that is not reproducible.
    out_path = out_dir / f"answers_{queries_path.stem}.jsonl"
    filled = answered_records(out_path)
    if filled and not force:
        raise GenerationError(
            f"{out_path} already holds {len(filled)} backfilled answer(s) "
            f"(e.g. {filled[0]}). Re-running would overwrite them. Move the file "
            "aside, or pass --force if you mean to discard those answers."
        )

    # Every input is validated before anything expensive starts, as in the evaluator.
    retrieval.ensure_device_available(device)
    if encoder is None:
        encoder = retrieval.load_encoder(retrieval.SUPPORTED_MODEL, device)
    if client is None:
        client = build_client(mode, out_dir / "prompts")

    corpus_vectors = encoder.encode([retrieval.PASSAGE_PREFIX + row["text"] for row in corpus])
    chunk_ids = [row["chunk_id"] for row in corpus]
    chunk_by_id = {row["chunk_id"]: row for row in corpus}

    records: list[dict[str, Any]] = []
    prompts: dict[str, str] = {}
    for query in queries:
        question = str(query["question"])
        query_vector = encoder.encode([retrieval.QUERY_PREFIX + question])[0]
        scores = retrieval.similarity_scores(query_vector, corpus_vectors)
        ranked = retrieval.rank_scores(scores, chunk_ids, top_k)
        stats = retrieval.score_statistics(scores)
        band = classify_band(stats["score_gap"], refuse_below, answer_at_or_above)

        record: dict[str, Any] = {
            "schema_version": GENERATION_SCHEMA_VERSION,
            "query_id": str(query["query_id"]),
            "question": question,
            "source_schema": source_schema,
            "expected_refusal": expected_refusal,
            "band": band,
            "thresholds": {
                "refuse_below": refuse_below,
                "answer_at_or_above": answer_at_or_above,
            },
            "score_gap": stats["score_gap"],
            "top1_score": stats["top1_score"],
            "corpus_mean_score": stats["corpus_mean_score"],
            "retrieved": [
                {
                    "rank": position,
                    "chunk_id": chunk_id,
                    "video_id": chunk_by_id[chunk_id]["video_id"],
                    "chunk_index": chunk_by_id[chunk_id]["chunk_index"],
                    "score": retrieval.serialize_score(score),
                }
                for position, (chunk_id, score) in enumerate(ranked, start=1)
            ],
            "prompt_version": PROMPT_VERSION,
            "prompt_path": None,
            "client": client.info.name,
        }

        if band == "refuse":
            # The band exists to stop the call, not to label it after the fact.
            record["answer"] = REFUSAL_TEXT
            record["generated"] = False
        else:
            prompt = build_prompt(
                question, [chunk_by_id[cid] for cid, _ in ranked], band, profile
            )
            prompts[record["query_id"]] = prompt
            record["answer"] = client.complete(prompt, record)
            record["generated"] = True
        records.append(record)

    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records)
    retrieval.write_text(body, out_path)
    counts = {band: sum(1 for row in records if row["band"] == band) for band in BANDS}

    bundle_path = None
    if bundle and prompts:
        bundle_path = out_dir / "bundles" / f"prompts_{queries_path.stem}.md"
        retrieval.write_text(build_bundle(records, prompts), bundle_path)
    return {
        "records": records,
        "out_path": out_path,
        "band_counts": counts,
        "prompts": prompts,
        "bundle_path": bundle_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--mode", default="dry-run", help="dry-run writes prompts instead of calling a model")
    parser.add_argument("--dry-run", action="store_true", help="alias for --mode dry-run")
    parser.add_argument("--top-k", type=int, default=retrieval.DEFAULT_TOP_K)
    parser.add_argument("--device", default=retrieval.DEFAULT_DEVICE, choices=list(retrieval.DEVICE_CHOICES))
    parser.add_argument("--refuse-below", type=float, default=REFUSE_BELOW)
    parser.add_argument("--answer-at-or-above", type=float, default=ANSWER_AT_OR_ABOVE)
    parser.add_argument(
        "--bundle",
        action="store_true",
        help="also write every prompt into one file with an answer template, to paste by hand",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an answers file that already holds backfilled answers",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help=(
            "path to a demo owner profile JSON (see data/profiles/demo_profile_v1.json). "
            "Omit (default) for the pre-profile prompt, unchanged."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = "dry-run" if args.dry_run else args.mode
    try:
        profile = load_profile(args.profile) if args.profile else None
        result = generate(
            args.queries,
            args.chunk_dir,
            args.out_dir,
            mode,
            args.top_k,
            args.device,
            args.refuse_below,
            args.answer_at_or_above,
            bundle=args.bundle,
            force=args.force,
            profile=profile,
        )
    except (OSError, GenerationError, retrieval.EvaluationError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    counts = result["band_counts"]
    total = sum(counts.values())
    print(f"질문 {total}건 → {result['out_path']}")
    for band in BANDS:
        share = counts[band] / total if total else 0.0
        print(f"  {band:<7} {counts[band]:>3}건 ({share:.1%})")
    if mode == "dry-run":
        print(f"프롬프트: {args.out_dir / 'prompts'} (refuse 구간은 호출하지 않으므로 없음)")
    if result["bundle_path"]:
        print(f"묶음 파일: {result['bundle_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
