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

Graph search and the vector+graph hybrid merge are imported from
run_combined_retrieval_eval.py (see `combined_eval` below) rather than
reimplemented — two copies of graph_search/hybrid_merge/gate would drift the
first time only one got fixed. This is what makes demo scenario③ (Q13,
docs/demo_scenarios.md) reproducible through this script instead of the one-off
script that produced it on 2026-08-20 (docs/agenda_0825.md 안건10/11): the same
gate() call, on the same score_gap, decides the same PASS/REFUSE either way.

The default mode calls the live model (see GENERATION_MODEL below, pinned through
the 8/25 demo). --dry-run keeps the old prompts-only behaviour so today's runs stay
comparable to every dry-run result already on disk.

Usage:
    uv run python scripts/generate_answers.py --queries <path>              # live, hybrid
    uv run python scripts/generate_answers.py --queries <path> --graph-off  # vector-only
    uv run python scripts/generate_answers.py --queries <path> --dry-run    # prompts only
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Sequence


DEFAULT_QUERIES = Path("data/eval/queries/out_of_corpus_queries.json")
DEFAULT_CHUNK_DIR = Path("data/processed/youtube/chunks")
DEFAULT_DOC_CHUNK_DIR = Path("data/processed/documents/chunks")
DEFAULT_OUT_DIR = Path("data/eval/generation")

# Graph input defaults to the frozen 2026-08-20 snapshot, not the live
# data/graph/extractions_stage2.jsonl that run_combined_retrieval_eval.py itself
# defaults to. A live Neo4j container (or the extraction files it was reloaded
# from) is not guaranteed to be up, or even unchanged, on demo day; the frozen
# pair is what docs/handoff_neo4j.md's restore path exists for, and it is what
# reports/retrieval_gap_hybrid_vs_vector_0820.md's Q13 numbers were measured
# against. combined_eval.load_graph() takes the path explicitly, so pointing
# generate_answers.py's defaults here does not touch
# run_combined_retrieval_eval.py's own CLI defaults at all.
DEFAULT_GRAPH_EXTRACTIONS = Path("frozen/frozen_stage2_0820.jsonl")
DEFAULT_GRAPH_ALIASES = Path("frozen/frozen_entity_aliases_0820.json")

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
PROMPT_VERSION = "grounded-answer-ko-v2"

REFUSAL_TEXT = (
    "제공된 자료에는 이 질문에 답할 내용이 없습니다. "
    "검색된 자료가 질문과 충분히 관련되어 있지 않아 답변을 생성하지 않았습니다."
)

PROMPT_RULES = (
    "1. 아래 <자료>에 실제로 적혀 있는 내용만으로 답하세요.",
    "2. 자료에 답이 없으면 \"제공된 자료에는 이 질문에 대한 내용이 없습니다\"라고 답하고, 추측하지 마세요.",
    "3. 자료 밖의 일반 지식이나 상식으로 빈칸을 채우지 마세요. 그럴듯한 문장을 만드는 것보다 없다고 말하는 것이 낫습니다.",
    "4. 답변에 쓴 자료를 [1]처럼 번호로 표시하세요.",
    # v2 addition (2026-08-20): a cause-only answer leaves an owner with nothing
    # to do next. This only asks for what rule 1/3 already allow — material that
    # is there — so it does not loosen the no-outside-knowledge rules above it.
    "5. 자료에 다음에 취할 수 있는 구체적인 행동이나 대처법이 나와 있다면 원인 설명과 "
    "함께 안내하세요. 자료에 없으면 억지로 만들지 말고 원인 설명까지만 답하세요.",
)

HEDGE_RULE = (
    "6. 아래 자료는 질문과의 관련성이 낮게 측정되었습니다. 답변 맨 앞에 "
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

# v2 (2026-08-20): earlier wording only said "this isn't evidence" and the model
# had no reason to actually use it — worst case with q007, where the profile's
# own 비고 restated the question's symptoms almost verbatim, so there was nothing
# left for the profile to add. Now asks the model to actively tailor the answer to
# this dog's situation, while keeping the one constraint that matters: grounding
# still comes only from <자료>, never from the profile.
PROFILE_NOTE = (
    "아래 프로필은 질문자가 알려준 반려견의 상황 정보입니다. 답변할 때 이 정보를 "
    "반영해 이 반려견의 상황에 맞게 조언을 조정하세요. 다만 답변에 쓰는 근거는 반드시 "
    "<자료>에서만 가져와야 하고, 프로필은 그 근거로 쓸 수 없습니다. 프로필에 적힌 "
    "질환명이 있어도 그것을 근거 없이 진단처럼 언급하지 마세요."
)

# Live generation config — pinned through the 8/25 demo, same model id as
# scripts/extract_entities.py's DEFAULT_MODEL. Not exposed as CLI flags: the point
# of pinning is that nobody (including a future run of this script) can change
# them without it showing up as a code diff. reasoning_effort is "medium" here,
# not extraction's "low" — this stage writes an answer for a person to read, not a
# JSON record for a validator. temperature is not sent, same as extraction (see
# extract_entities.py's PROMPT_VERSION comment for why: absent from the request,
# not sent as null). max_output_tokens is generous because a reasoning model's
# hidden reasoning tokens can eat into the same budget as the visible answer.
GENERATION_MODEL = "gpt-5.6-terra"
GENERATION_REASONING_EFFORT = "medium"
GENERATION_TEMPERATURE = "not_sent"
GENERATION_MAX_OUTPUT_TOKENS = 4096


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


def _load_module(name: str) -> Any:
    """Import a sibling script by filename, whatever the working directory is.

    Same pattern as _load_retrieval(): the point is to reuse that script's code,
    not its intent, so a change there is felt here too instead of drifting apart.
    """
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise GenerationError(f"cannot import {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# extraction: reused for its OpenAI auth/retry/dual-surface plumbing (ENV_KEY,
# BACKOFF_SECONDS, RETRY_STATUS) — see load_openai_answer_client() below.
# medical_guardrail: reused for classify_output_v2() and, as of 2026-08-20,
# classify_input_v2() too — see MEDICAL_REFUSAL_TEMPLATE and generate()'s call site.
# combined_eval (run_combined_retrieval_eval.py): reused for load_document_chunks
# (the document half of the corpus, absent from evaluate_youtube_retrieval on
# purpose — see that script's own module docstring), and for load_graph/
# build_adjacency/graph_search/hybrid_merge/gate/GATE_PASS — see generate()'s
# graph setup and its per-query loop.
extraction = _load_module("extract_entities")
medical_guardrail = _load_module("medical_guardrail")
combined_eval = _load_module("run_combined_retrieval_eval")

# 2026-08-20: Q17 (a MEDICAL owner-fixture question, docs/agenda_0825.md 안건10)
# landed in the "answer" band on score_gap alone and reached the model, which
# refused on its own — "제공된 자료에는 이 질문에 대한 내용이 없습니다", the same
# ungrounded-refusal text any out-of-scope question gets. That is not wrong, but
# it is not enough for a question a worried owner actually typed: no acknowledgment,
# no explicit vet referral. This is that better text — reuses
# medical_guardrail.VET_REFERRAL_MESSAGE (the module's one canonical "can't
# diagnose, go to a vet" wording, already what classify_input's docstring says
# every MEDICAL verdict must return) with one line of empathy in front.
#
# Wrapped in SystemAuthoredText, not a plain str: VET_REFERRAL_MESSAGE itself
# contains "병원" (a v2 disease/symptom term) and "처방" (a prescriptive marker),
# so passed as a plain str this hand-authored safe text would self-trip
# classify_output_v2 — see medical_guardrail.py's module docstring ("the
# self-block incident") and reports/output_guardrail_self_block_incident.md.
# generate()'s call site routes it through apply_output_guardrail() like any
# other answer; the wrapper, not a branch, is what exempts it.
MEDICAL_REFUSAL_TEMPLATE = medical_guardrail.SystemAuthoredText(
    "걱정이 많으시겠어요. " + medical_guardrail.VET_REFERRAL_MESSAGE
)


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


def load_openai_answer_client(env_path: Path = Path(".env")) -> AnswerClient:
    """The live client. Reuses extract_entities.py's key-reading, retry/backoff and
    dual-surface (Responses API first, Chat Completions fallback) plumbing —
    extraction.ENV_KEY, extraction.BACKOFF_SECONDS, extraction.RETRY_STATUS — since
    that is exactly the "read the key, call the model, retry on 429/503/500"
    problem extraction already solved. What differs from extraction's client:

    - no `text.format` / `response_format` json_schema: an answer is prose for a
      person to read, not a record for a validator.
    - reasoning effort is GENERATION_REASONING_EFFORT ("medium"), not extraction's
      "low".
    - max_output_tokens / max_completion_tokens is capped at
      GENERATION_MAX_OUTPUT_TOKENS so a long answer cannot silently run unbounded,
      chosen generously because a reasoning model's hidden reasoning tokens share
      the same budget as the visible answer.

    Model, reasoning effort, temperature and the token cap are pinned constants
    (see the comment above GENERATION_MODEL) — this function takes no override
    arguments for any of them, on purpose.
    """
    try:
        from dotenv import dotenv_values
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise GenerationError("python-dotenv is required to read the API key") from exc
    key = (dotenv_values(env_path) or {}).get(extraction.ENV_KEY)
    if not key:
        raise GenerationError(
            f"{extraction.ENV_KEY} not found in {env_path.resolve()}. The key is read "
            "from there and is never written to any output of this script."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise GenerationError("openai is required (`uv add openai`)") from exc

    sdk = OpenAI(api_key=key)
    state: dict[str, str | None] = {"surface": None}

    def _responses_call(prompt: str) -> tuple[str, dict[str, Any]]:
        response = sdk.responses.create(
            model=GENERATION_MODEL,
            input=prompt,
            reasoning={"effort": GENERATION_REASONING_EFFORT},
            max_output_tokens=GENERATION_MAX_OUTPUT_TOKENS,
        )
        usage = getattr(response, "usage", None)
        status = getattr(response, "status", None)
        if status == "completed":
            finish_reason = "stop"
        else:
            # Responses API puts the truncation cause here (e.g. "max_output_tokens")
            # instead of Chat Completions' flat finish_reason string.
            incomplete = getattr(response, "incomplete_details", None)
            finish_reason = getattr(incomplete, "reason", None) or status or "unknown"
        return (getattr(response, "output_text", "") or ""), {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "finish_reason": finish_reason,
        }

    def _chat_call(prompt: str) -> tuple[str, dict[str, Any]]:
        response = sdk.chat.completions.create(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            reasoning_effort=GENERATION_REASONING_EFFORT,
            max_completion_tokens=GENERATION_MAX_OUTPUT_TOKENS,
        )
        usage = getattr(response, "usage", None)
        choice = response.choices[0]
        return (choice.message.content or ""), {
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "finish_reason": getattr(choice, "finish_reason", None) or "unknown",
        }

    class OpenAIAnswerClient:
        # Read by generate() via getattr(client, "model_id"/"reasoning_effort", None)
        # to fill record["generation_meta"] — see generate()'s per-query loop.
        model_id = GENERATION_MODEL
        reasoning_effort = GENERATION_REASONING_EFFORT

        @property
        def info(self) -> ClientInfo:
            return ClientInfo(name=f"openai:{GENERATION_MODEL}")

        @property
        def surface(self) -> str | None:
            """Which API surface produced the output. Recorded, not assumed."""
            return state["surface"]

        def complete(self, prompt: str, record: dict[str, Any]) -> str | None:
            last: Exception | None = None
            for delay in (0, *extraction.BACKOFF_SECONDS):
                if delay:
                    time.sleep(delay)
                for name, call in (("responses", _responses_call), ("chat", _chat_call)):
                    if state["surface"] not in (None, name):
                        continue
                    try:
                        text, usage = call(prompt)
                    except Exception as exc:  # noqa: BLE001 - provider errors are not typed
                        message = str(exc)
                        if any(code in message for code in extraction.RETRY_STATUS):
                            last = exc
                            break  # transient: back off, then retry the same surface
                        last = exc
                        continue  # this surface is unusable; try the other one
                    state["surface"] = name
                    record["usage"] = usage
                    return text
            raise GenerationError(f"model call failed: {str(last)[:400]}")

    return OpenAIAnswerClient()


def build_client(mode: str, prompt_dir: Path, env_path: Path = Path(".env")) -> AnswerClient:
    """Pick the client for a run.

    'openai' (the CLI default) calls GENERATION_MODEL for real; 'dry-run' writes
    prompts to prompt_dir instead of calling anything, unchanged from before the
    live client existed, so a --dry-run run today stays comparable to every
    dry-run result already on disk.
    """
    if mode == "dry-run":
        return DryRunClient(prompt_dir)
    if mode == "openai":
        return load_openai_answer_client(env_path)
    raise GenerationError(
        f"unknown --mode {mode!r}. Supported: 'openai' (default, calls {GENERATION_MODEL}) "
        "or 'dry-run' (prompts only, no API call). See build_client() to add another provider."
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


def _chunk_header(position: int, chunk: dict[str, Any]) -> str:
    """The "[N] (...)" citation header build_prompt puts above each chunk's text.

    Video and document chunks are shaped differently (see
    run_combined_retrieval_eval.py's load_video_chunks/load_document_chunks,
    which enforce this as a hard split: a document chunk is not allowed to carry
    "video_id" at all). "video_id" in chunk is therefore an exact, not a guessed,
    discriminator — never both true and false for the same real chunk record.
    """
    if "video_id" in chunk:
        title = chunk.get("chapter_title", "")
        header = f"[{position}] ({chunk['video_id']} #{chunk['chunk_index']}"
        return header + (f" · {title})" if title else ")")
    heading = " > ".join(chunk.get("heading_path", []))
    header = f"[{position}] (문서 · {chunk['doc_id']} #{chunk['chunk_index']}"
    return header + (f" · {heading})" if heading else ")")


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

    chunks may be video or document chunks (or a mix) — this script's own
    retrieval only ever passes video chunks (DEFAULT_CHUNK_DIR), but a caller
    that sources evidence elsewhere (e.g. run_combined_retrieval_eval.py's
    graph-augmented hybrid_merge, whose corpus includes documents) can pass
    those chunks straight through. See _chunk_header().
    """
    rules = list(PROMPT_RULES)
    if band == "hedge":
        rules.append(HEDGE_RULE)
    sources = [
        f"{_chunk_header(position, chunk)}\n{chunk['text']}"
        for position, chunk in enumerate(chunks, start=1)
    ]
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
    env_path: Path = Path(".env"),
    medical_terms: Sequence[str] | None = None,
    whitelist_terms: Sequence[str] | None = None,
    doc_chunk_dir: Path | None = None,
    graph_extractions: Path | None = None,
    graph_aliases: Path | None = None,
    graph_off: bool = False,
) -> dict[str, Any]:
    """
    doc_chunk_dir / graph_extractions / graph_aliases default to None, not to
    DEFAULT_DOC_CHUNK_DIR / DEFAULT_GRAPH_EXTRACTIONS / DEFAULT_GRAPH_ALIASES:
    a direct call (every test in tests/test_generate_answers.py) then gets the
    old video-only, graph-off behaviour byte for byte, the same hermetic
    contract medical_terms/whitelist_terms already have below (real lexicons
    load only for a real CLI client, never for an injected test client). main()
    is what supplies the real defaults — see build_parser().
    """
    validate_thresholds(refuse_below, answer_at_or_above)
    queries, source_schema = load_query_set(queries_path)
    expected_refusal = source_schema == OUT_OF_CORPUS_SCHEMA

    video_chunks = retrieval.load_chunks(chunk_dir)
    video_corpus = retrieval.eligible_chunks(video_chunks)
    if not video_corpus:
        raise GenerationError("no embedding_eligible chunk in the corpus")
    doc_corpus = combined_eval.load_document_chunks(doc_chunk_dir) if doc_chunk_dir is not None else []
    corpus = video_corpus + doc_corpus

    graph_enabled = not graph_off and graph_extractions is not None and graph_aliases is not None
    if graph_enabled:
        graph_nodes, graph_edges = combined_eval.load_graph(graph_extractions, graph_aliases)
        graph_adjacency = combined_eval.build_adjacency(graph_edges)
    else:
        graph_nodes, graph_edges, graph_adjacency = {}, {}, {}

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
        client = build_client(mode, out_dir / "prompts", env_path)
        # medical_terms/whitelist_terms drive classify_output_v2 below (v2, not
        # v1 — v1's disease/symptom terms overlap ordinary training vocabulary,
        # see medical_guardrail.py's v2-addition docstring and docs/agenda_0825.md).
        # Auto-loaded only for the default client construction (a real CLI run) —
        # a caller that injects its own client (every existing test) also controls
        # these explicitly, so those tests stay hermetic and never touch
        # data/guardrail/*.json.
        if medical_terms is None and mode != "dry-run":
            medical_terms = medical_guardrail.load_medical_terms_v2()
        if whitelist_terms is None and mode != "dry-run":
            whitelist_terms = medical_guardrail.load_training_whitelist()

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
                    # A ranked chunk may be a document chunk once doc_chunk_dir is
                    # set (run_combined_retrieval_eval.py's load_document_chunks
                    # enforces that a document chunk never carries "video_id" —
                    # see that function's docstring), so video_id/chunk_index are
                    # read the same discriminated way _chunk_header() reads them.
                    **(
                        {"video_id": chunk_by_id[chunk_id]["video_id"],
                         "chunk_index": chunk_by_id[chunk_id]["chunk_index"]}
                        if "video_id" in chunk_by_id[chunk_id]
                        else {"doc_id": chunk_by_id[chunk_id]["doc_id"],
                              "chunk_index": chunk_by_id[chunk_id]["chunk_index"]}
                    ),
                    "score": retrieval.serialize_score(score),
                }
                for position, (chunk_id, score) in enumerate(ranked, start=1)
            ],
            "prompt_version": PROMPT_VERSION,
            "prompt_path": None,
            "usage": None,
            "medical_input_guardrail": None,
            "graph_gate_verdict": None,
            "graph_chunks_added": None,
            "evidence_chunk_ids": None,
            "client": client.info.name,
        }

        if band == "refuse":
            # The band exists to stop the call, not to label it after the fact.
            # No search of any kind runs here — graph_* stays the None set above.
            record["answer"] = REFUSAL_TEXT
            record["generated"] = False
            record["generation_meta"] = None
            record["raw_model_answer"] = None
            record["output_guardrail"] = None
        else:
            # Medical short-circuit: score_gap alone doesn't know a question is
            # medical (docs/agenda_0825.md 안건10 — Q17 reached the model this way
            # and got an ad-hoc "자료에 없습니다" instead of a vet referral). This
            # is the minimal fix asked for — no new band, no change to score_gap
            # or classify_band, just one check ahead of the existing model call
            # inside the branch that already handles hedge/answer.
            medical_verdict = None
            if medical_terms is not None and whitelist_terms is not None:
                medical_verdict = medical_guardrail.classify_input_v2(
                    question, medical_terms, whitelist_terms
                )
                record["medical_input_guardrail"] = {
                    "is_medical": medical_verdict.is_medical,
                    "matched_terms": list(medical_verdict.matched_terms),
                    "whitelist_matched": list(medical_verdict.whitelist_matched),
                }

            if medical_verdict is not None and medical_verdict.is_medical:
                # No model call: MEDICAL_REFUSAL_TEMPLATE is fixed, hand-authored
                # text. Still routed through apply_output_guardrail() like any
                # other answer — it passes because it is a SystemAuthoredText, not
                # because this branch skips the check (see that constant's comment).
                verdict = medical_guardrail.apply_output_guardrail(
                    MEDICAL_REFUSAL_TEMPLATE, medical_terms, whitelist_terms
                )
                record["answer"] = verdict.text
                record["generated"] = False
                record["generation_meta"] = None
                record["raw_model_answer"] = None
                record["output_guardrail"] = {
                    "is_blocked": verdict.is_blocked,
                    "matched_disease_terms": list(verdict.matched_disease_terms),
                    "matched_prescriptive_markers": list(verdict.matched_prescriptive_markers),
                    "whitelist_matched": list(verdict.whitelist_matched),
                    "system_authored": verdict.system_authored,
                }
                records.append(record)
                continue

            # Graph search, gated exactly the way run_combined_retrieval_eval.py
            # gates it (docs/graph_hybrid_retrieval_design.md 결정 3): the gate's
            # only input is the vector score_gap computed above — graph_search()'s
            # own chunks never reach gate() — and graph chunks are appended to the
            # evidence only on GATE_PASS. On REFUSE the evidence stays vector-only,
            # no matter how many chunks the graph would have found. Reached only
            # after the medical short-circuit above returns/continues, so a
            # MEDICAL question never runs graph_search() at all.
            evidence_ids = [chunk_id for chunk_id, _ in ranked]
            graph_gate_verdict = None
            if graph_enabled:
                graph_gate_verdict = combined_eval.gate(stats["score_gap"])
                if graph_gate_verdict == combined_eval.GATE_PASS:
                    graph_chunks = combined_eval.graph_search(
                        question, graph_nodes, graph_edges, graph_adjacency, chunk_by_id
                    )
                    evidence_ids = combined_eval.hybrid_merge(ranked, graph_chunks)
            record["graph_gate_verdict"] = graph_gate_verdict
            record["graph_chunks_added"] = [
                cid for cid in evidence_ids if cid not in {c for c, _ in ranked}
            ]
            record["evidence_chunk_ids"] = evidence_ids

            prompt = build_prompt(
                question, [chunk_by_id[cid] for cid in evidence_ids], band, profile
            )
            prompts[record["query_id"]] = prompt
            raw_answer = client.complete(prompt, record)
            record["generated"] = True

            # Only a client that identifies itself (model_id) gets generation_meta —
            # a fake/dry-run "answer" was not produced by any model, so recording a
            # model name for it would misattribute it.
            model_id = getattr(client, "model_id", None)
            record["generation_meta"] = (
                {
                    "model": model_id,
                    "reasoning_effort": getattr(client, "reasoning_effort", None),
                    "temperature": GENERATION_TEMPERATURE,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                if raw_answer is not None and model_id is not None
                else None
            )

            # Output-side guardrail: runs on whatever text the client actually
            # returned, real model or test double alike — raw_answer is always a
            # plain str here (no client wraps its own output in SystemAuthoredText),
            # so apply_output_guardrail() always applies the full check. See
            # medical_guardrail.py's classify_output_v2 docstring for why
            # disease-term-alone is a disclaimer, disease+prescriptive-marker is a
            # block, and a whitelist hit (분리불안/불안/... — ordinary training
            # vocabulary) passes through untouched ahead of either.
            if raw_answer is not None and medical_terms is not None and whitelist_terms is not None:
                verdict = medical_guardrail.apply_output_guardrail(raw_answer, medical_terms, whitelist_terms)
                record["raw_model_answer"] = raw_answer
                record["answer"] = verdict.text
                record["output_guardrail"] = {
                    "is_blocked": verdict.is_blocked,
                    "matched_disease_terms": list(verdict.matched_disease_terms),
                    "matched_prescriptive_markers": list(verdict.matched_prescriptive_markers),
                    "whitelist_matched": list(verdict.whitelist_matched),
                    "system_authored": verdict.system_authored,
                }
            else:
                record["raw_model_answer"] = None
                record["answer"] = raw_answer
                record["output_guardrail"] = None
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
    parser.add_argument(
        "--mode",
        default="openai",
        help=f"'openai' calls the live model (default, pinned to {GENERATION_MODEL}); "
             "'dry-run' writes prompts instead of calling a model",
    )
    parser.add_argument("--dry-run", action="store_true", help="alias for --mode dry-run")
    parser.add_argument(
        "--env", type=Path, default=Path(".env"),
        help="path to the .env file holding OPENAI_API_KEY (live mode only)",
    )
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
    parser.add_argument(
        "--doc-chunk-dir", type=Path, default=DEFAULT_DOC_CHUNK_DIR,
        help="document half of the combined corpus (run_combined_retrieval_eval.py's "
             "load_document_chunks); paired with --no-documents below",
    )
    parser.add_argument(
        "--no-documents", action="store_true",
        help="video-only corpus, no documents — the vector-only side of a hybrid comparison",
    )
    parser.add_argument("--graph-extractions", type=Path, default=DEFAULT_GRAPH_EXTRACTIONS)
    parser.add_argument("--graph-aliases", type=Path, default=DEFAULT_GRAPH_ALIASES)
    parser.add_argument(
        "--graph-off", action="store_true",
        help="vector-only evidence, no graph search — for the vector-vs-hybrid comparison "
             "(mirrors run_combined_retrieval_eval.py's own --graph-off)",
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
            env_path=args.env,
            doc_chunk_dir=None if args.no_documents else args.doc_chunk_dir,
            graph_extractions=args.graph_extractions,
            graph_aliases=args.graph_aliases,
            graph_off=args.graph_off,
        )
    except (
        OSError, GenerationError, retrieval.EvaluationError,
        combined_eval.EvalError, json.JSONDecodeError,
    ) as exc:
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
    else:
        calls = [r for r in result["records"] if r.get("generation_meta")]
        blocked = [r for r in calls if (r.get("output_guardrail") or {}).get("is_blocked")]
        in_tok = sum((r["usage"] or {}).get("input_tokens", 0) for r in calls)
        out_tok = sum((r["usage"] or {}).get("output_tokens", 0) for r in calls)
        print(f"실제 모델 호출 {len(calls)}건 · 토큰 in {in_tok} / out {out_tok} "
              f"· 출력 가드레일 차단 {len(blocked)}건")
    if result["bundle_path"]:
        print(f"묶음 파일: {result['bundle_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
