"""Evaluate YouTube chunk retrieval against a reviewed Korean query set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence


DEFAULT_QUERY_SET = Path("data/eval/queries/youtube_retrieval_queries.jsonl")
DEFAULT_CHUNK_DIR = Path("data/processed/youtube/chunks")
DEFAULT_TRANSCRIPT_DIR = Path("data/processed/youtube/transcripts")
DEFAULT_REVIEW_PATH = Path("data/eval/review/retrieval_query_review.md")
DEFAULT_RESULT_DIR = Path("data/eval/results")

QUERY_SCHEMA_VERSION = "youtube-eval-query-v1"
METRICS_SCHEMA_VERSION = "youtube-retrieval-metrics-v1"

# This MVP is written against the multilingual-e5 prefix contract only.
# A bge-m3 adapter is a follow-up change, not an accepted --model-name value.
SUPPORTED_MODEL = "intfloat/multilingual-e5-base"
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
DEPENDENCY_PACKAGES = ("sentence-transformers", "transformers", "torch", "tokenizers")

MIN_TOP_K = 5
DEFAULT_TOP_K = 5
HIT_CUTOFFS = (1, 3, 5)
RANK_CUTOFF = 5
SCORE_DECIMALS = 6
REVIEW_SAMPLE_CHARS = 120

REVIEW_STATUSES = ("PENDING", "APPROVED", "REJECTED")
SPLITS = ("dev", "test")
SPLIT_CHOICES = ("dev", "test", "all")
QUERY_TYPES = (
    "direct_lookup",
    "paraphrase",
    "symptom_to_solution",
    "concept",
    "multi_span",
)

SPLIT_POLICY = (
    "dev(12): 모델·설정 비교와 오류 분석에 사용한다.",
    "test(6): 최종 설정을 확정한 뒤 마지막 확인에만 사용한다.",
    "test 결과를 보면서 threshold, passage 구성, 모델 설정을 조정하지 않는다.",
)
LIMITATIONS = (
    "영상 3개 / embedding_eligible chunk 42개만으로 측정한 smoke benchmark다.",
    "이 수치는 일반적인 한국어 검색 성능을 증명하지 않는다.",
    "corpus가 작아 무작위 순위로도 지표가 크게 흔들린다. 절대값이 아니라 설정 간 상대 비교에만 쓴다.",
    "gold span은 사람이 검토한 구간이며 span에 겹치는 eligible chunk 전부를 정답으로 본다.",
    "동일 환경에서의 ranking/metrics 재현성만 보장한다. CPU/GPU 또는 라이브러리 버전이 다르면 embedding score는 달라질 수 있다.",
    "latency는 환경 의존 값이라 결정론 검증 대상이 아니며 metrics 산출물과 분리해 기록한다.",
)


class EvaluationError(ValueError):
    """Raised when run settings, the corpus, or the query set are invalid."""


@dataclass(frozen=True)
class RunSettings:
    top_k: int = DEFAULT_TOP_K
    model_name: str = SUPPORTED_MODEL
    split: str = "dev"

    def validate(self) -> None:
        if self.top_k < MIN_TOP_K:
            raise EvaluationError(
                f"--top-k must be >= {MIN_TOP_K} because Hit@5, MRR@5 and Recall@5 are always reported "
                f"(got {self.top_k})"
            )
        if self.model_name != SUPPORTED_MODEL:
            raise EvaluationError(
                f"unsupported model: {self.model_name!r}. This MVP implements the "
                f"{SUPPORTED_MODEL!r} prefix contract only ('{QUERY_PREFIX}' / '{PASSAGE_PREFIX}'); "
                "a bge-m3 adapter is out of scope for this change"
            )
        if self.split not in SPLIT_CHOICES:
            raise EvaluationError(f"--split must be one of {list(SPLIT_CHOICES)} (got {self.split!r})")


@dataclass(frozen=True)
class EncoderInfo:
    name: str
    dependency_versions: dict[str, str]


class Encoder(Protocol):
    """Minimal encoder contract so tests can inject a deterministic fake."""

    @property
    def info(self) -> EncoderInfo: ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class SpanMatch:
    chunk: dict[str, Any]
    overlap_ms: int
    overlap_coefficient: float


@dataclass(frozen=True)
class SpanMapping:
    span_id: str
    start_ms: int
    end_ms: int
    note: str
    matches: tuple[SpanMatch, ...]


@dataclass(frozen=True)
class QueryPlan:
    query: dict[str, Any]
    spans: tuple[SpanMapping, ...]
    relevant_chunk_ids: tuple[str, ...]

    @property
    def query_id(self) -> str:
        return str(self.query["query_id"])

    @property
    def review_status(self) -> str:
        return str(self.query["review_status"])

    @property
    def split(self) -> str:
        return str(self.query["split"])


def format_ms(value: int) -> str:
    seconds, milliseconds = divmod(int(value), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def serialize_score(value: float) -> float:
    """Serialize with a fixed number of decimals; ranking always uses the raw score."""
    return float(format(float(value), f".{SCORE_DECIMALS}f"))


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    if not path.is_file():
        raise EvaluationError(f"file not found: {path}")
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvaluationError(f"invalid JSON at {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise EvaluationError(f"row must be a JSON object at {path}:{line_number}")
            yield line_number, row


def load_chunks(chunk_dir: Path) -> list[dict[str, Any]]:
    paths = sorted(chunk_dir.glob("*.jsonl"))
    if not paths:
        raise EvaluationError(f"no chunk files under {chunk_dir}")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        for line_number, row in _iter_jsonl(path):
            for key in ("chunk_id", "video_id", "text"):
                if not isinstance(row.get(key), str) or not row[key]:
                    raise EvaluationError(f"invalid {key} at {path}:{line_number}")
            for key in ("chunk_index", "start_ms", "end_ms"):
                if not isinstance(row.get(key), int) or isinstance(row.get(key), bool):
                    raise EvaluationError(f"invalid {key} at {path}:{line_number}")
            if not isinstance(row.get("embedding_eligible"), bool):
                raise EvaluationError(f"invalid embedding_eligible at {path}:{line_number}")
            if row["start_ms"] < 0 or row["start_ms"] > row["end_ms"]:
                raise EvaluationError(f"invalid chunk interval at {path}:{line_number}")
            if row["chunk_id"] in seen:
                raise EvaluationError(f"duplicate chunk_id at {path}:{line_number}")
            seen.add(row["chunk_id"])
            rows.append(row)
    rows.sort(key=lambda row: (row["video_id"], row["chunk_index"]))
    return rows


def eligible_chunks(chunks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [chunk for chunk in chunks if chunk["embedding_eligible"]]


def load_transcript_bounds(transcript_dir: Path, video_ids: Iterable[str]) -> dict[str, tuple[int, int]]:
    bounds: dict[str, tuple[int, int]] = {}
    for video_id in sorted(set(video_ids)):
        path = transcript_dir / f"{video_id}.jsonl"
        starts: list[int] = []
        ends: list[int] = []
        for line_number, row in _iter_jsonl(path):
            if not isinstance(row.get("start_ms"), int) or not isinstance(row.get("end_ms"), int):
                raise EvaluationError(f"invalid transcript timing at {path}:{line_number}")
            starts.append(row["start_ms"])
            ends.append(row["end_ms"])
        if not starts:
            raise EvaluationError(f"empty transcript: {path}")
        bounds[video_id] = (min(starts), max(ends))
    return bounds


def load_queries(path: Path) -> list[dict[str, Any]]:
    rows = [row for _, row in _iter_jsonl(path)]
    if not rows:
        raise EvaluationError(f"empty query set: {path}")
    return rows


def _validate_query_schema(query: dict[str, Any], index: int) -> None:
    where = f"query #{index}"
    if query.get("schema_version") != QUERY_SCHEMA_VERSION:
        raise EvaluationError(f"{where}: schema_version must be {QUERY_SCHEMA_VERSION!r}")
    for key in ("query_id", "question", "video_id"):
        if not isinstance(query.get(key), str) or not query[key].strip():
            raise EvaluationError(f"{where}: {key} must be a non-empty string")
    where = f"query {query['query_id']}"
    if query.get("split") not in SPLITS:
        raise EvaluationError(f"{where}: split must be one of {list(SPLITS)}")
    if query.get("query_type") not in QUERY_TYPES:
        raise EvaluationError(f"{where}: query_type must be one of {list(QUERY_TYPES)}")
    if query.get("review_status") not in REVIEW_STATUSES:
        raise EvaluationError(f"{where}: review_status must be one of {list(REVIEW_STATUSES)}")
    reviewed_at = query.get("reviewed_at")
    if reviewed_at is not None and not isinstance(reviewed_at, str):
        raise EvaluationError(f"{where}: reviewed_at must be null or a date string")
    if query["review_status"] == "APPROVED" and not (reviewed_at or "").strip():
        raise EvaluationError(f"{where}: APPROVED queries must carry reviewed_at")
    if not isinstance(query.get("review_reason"), str):
        raise EvaluationError(f"{where}: review_reason must be a string")
    spans = query.get("relevant_spans")
    if not isinstance(spans, list) or not spans:
        raise EvaluationError(f"{where}: relevant_spans must be a non-empty array")
    span_ids: set[str] = set()
    for span in spans:
        if not isinstance(span, dict):
            raise EvaluationError(f"{where}: each relevant span must be an object")
        if not isinstance(span.get("span_id"), str) or not span["span_id"].strip():
            raise EvaluationError(f"{where}: span_id must be a non-empty string")
        if span["span_id"] in span_ids:
            raise EvaluationError(f"{where}: duplicate span_id {span['span_id']!r}")
        span_ids.add(span["span_id"])
        for key in ("start_ms", "end_ms"):
            if not isinstance(span.get(key), int) or isinstance(span.get(key), bool):
                raise EvaluationError(f"{where}/{span['span_id']}: {key} must be an integer")
        if span["start_ms"] < 0 or span["start_ms"] >= span["end_ms"]:
            raise EvaluationError(f"{where}/{span['span_id']}: span must satisfy 0 <= start_ms < end_ms")
        if not isinstance(span.get("note", ""), str):
            raise EvaluationError(f"{where}/{span['span_id']}: note must be a string")


def overlap_ms(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def overlap_coefficient(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    shortest = min(end_a - start_a, end_b - start_b)
    if shortest <= 0:
        return 0.0
    return overlap_ms(start_a, end_a, start_b, end_b) / shortest


def map_span_to_chunks(
    span: dict[str, Any], chunks: Sequence[dict[str, Any]]
) -> tuple[SpanMatch, ...]:
    """Order by overlap coefficient so matches[0] is the chunk quoted in the review report."""
    matches = []
    for chunk in chunks:
        overlap = overlap_ms(span["start_ms"], span["end_ms"], chunk["start_ms"], chunk["end_ms"])
        if overlap <= 0:
            continue
        coefficient = overlap_coefficient(
            span["start_ms"], span["end_ms"], chunk["start_ms"], chunk["end_ms"]
        )
        matches.append(SpanMatch(chunk=chunk, overlap_ms=overlap, overlap_coefficient=coefficient))
    matches.sort(
        key=lambda match: (
            -match.overlap_coefficient,
            -match.overlap_ms,
            match.chunk["chunk_id"],
        )
    )
    return tuple(matches)


def build_query_plans(
    queries: Sequence[dict[str, Any]],
    chunks: Sequence[dict[str, Any]],
    bounds: dict[str, tuple[int, int]],
) -> list[QueryPlan]:
    """Validate every query and resolve gold spans to eligible chunks.

    Runs before any model import so that a broken eval set never triggers a download.
    """
    known_videos = {chunk["video_id"] for chunk in chunks}
    by_video: dict[str, list[dict[str, Any]]] = {}
    for chunk in eligible_chunks(chunks):
        by_video.setdefault(chunk["video_id"], []).append(chunk)

    plans: list[QueryPlan] = []
    seen_ids: set[str] = set()
    for index, query in enumerate(queries, start=1):
        _validate_query_schema(query, index)
        query_id = query["query_id"]
        if query_id in seen_ids:
            raise EvaluationError(f"duplicate query_id {query_id!r}")
        seen_ids.add(query_id)

        video_id = query["video_id"]
        if video_id not in known_videos:
            raise EvaluationError(f"query {query_id}: video_id {video_id!r} is not in the chunk corpus")
        if video_id not in bounds:
            raise EvaluationError(f"query {query_id}: transcript for {video_id!r} was not loaded")
        if video_id not in by_video:
            raise EvaluationError(
                f"query {query_id}: video {video_id!r} has no embedding_eligible chunk"
            )

        transcript_start, transcript_end = bounds[video_id]
        mappings: list[SpanMapping] = []
        relevant: list[str] = []
        for span in query["relevant_spans"]:
            span_id = span["span_id"]
            if span["start_ms"] < transcript_start or span["end_ms"] > transcript_end:
                raise EvaluationError(
                    f"query {query_id}/{span_id}: gold span {span['start_ms']}-{span['end_ms']}ms "
                    f"is outside the {video_id} transcript range "
                    f"{transcript_start}-{transcript_end}ms"
                )
            matches = map_span_to_chunks(span, by_video[video_id])
            if not matches:
                raise EvaluationError(
                    f"query {query_id}/{span_id}: gold span maps to no embedding_eligible chunk"
                )
            mappings.append(
                SpanMapping(
                    span_id=span_id,
                    start_ms=span["start_ms"],
                    end_ms=span["end_ms"],
                    note=str(span.get("note", "")),
                    matches=matches,
                )
            )
            relevant.extend(match.chunk["chunk_id"] for match in matches)

        unique_relevant = tuple(sorted(dict.fromkeys(relevant)))
        if not unique_relevant:
            raise EvaluationError(f"query {query_id}: no relevant chunk resolved")
        plans.append(
            QueryPlan(query=query, spans=tuple(mappings), relevant_chunk_ids=unique_relevant)
        )
    return plans


def rank_chunks(
    query_vector: Sequence[float],
    corpus_vectors: Sequence[Sequence[float]],
    chunk_ids: Sequence[str],
    top_k: int,
) -> list[tuple[str, float]]:
    """Rank on the raw score; ties break on ascending chunk_id."""
    scores = [sum(a * b for a, b in zip(query_vector, vector)) for vector in corpus_vectors]
    order = sorted(range(len(chunk_ids)), key=lambda index: (-scores[index], chunk_ids[index]))
    return [(chunk_ids[index], scores[index]) for index in order[:top_k]]


def _ratio(numerator: float, denominator: float) -> float:
    return serialize_score(numerator / denominator) if denominator else 0.0


def build_metrics(
    plans: Sequence[QueryPlan],
    rankings: dict[str, list[tuple[str, float]]],
    chunk_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    total = len(plans)
    hits = {cutoff: 0 for cutoff in HIT_CUTOFFS}
    reciprocal_sum = 0.0
    recall_sum = 0.0
    span_recall_sum = 0.0
    covered_spans = 0
    total_spans = 0
    per_query: list[dict[str, Any]] = []

    for plan in plans:
        ranked = rankings[plan.query_id]
        relevant = set(plan.relevant_chunk_ids)
        ranked_ids = [chunk_id for chunk_id, _ in ranked]
        cutoff_ids = ranked_ids[:RANK_CUTOFF]

        for cutoff in HIT_CUTOFFS:
            if relevant.intersection(ranked_ids[:cutoff]):
                hits[cutoff] += 1

        first_rank: int | None = None
        for position, chunk_id in enumerate(cutoff_ids, start=1):
            if chunk_id in relevant:
                first_rank = position
                break
        reciprocal = 1.0 / first_rank if first_rank else 0.0
        reciprocal_sum += reciprocal

        recall = len(relevant.intersection(cutoff_ids)) / len(relevant)
        recall_sum += recall

        query_covered = 0
        for span in plan.spans:
            span_chunks = {match.chunk["chunk_id"] for match in span.matches}
            if span_chunks.intersection(cutoff_ids):
                query_covered += 1
        covered_spans += query_covered
        total_spans += len(plan.spans)
        span_recall = query_covered / len(plan.spans)
        span_recall_sum += span_recall

        per_query.append(
            {
                "query_id": plan.query_id,
                "split": plan.split,
                "query_type": plan.query["query_type"],
                "video_id": plan.query["video_id"],
                "gold_span_count": len(plan.spans),
                "relevant_chunk_count": len(relevant),
                "first_relevant_rank": first_rank,
                "reciprocal_rank": serialize_score(reciprocal),
                "recall@5": serialize_score(recall),
                "span_recall@5": serialize_score(span_recall),
                "covered_spans": query_covered,
                "results": [
                    {
                        "rank": position,
                        "chunk_id": chunk_id,
                        "video_id": chunk_by_id[chunk_id]["video_id"],
                        "chunk_index": chunk_by_id[chunk_id]["chunk_index"],
                        "chapter_title": chunk_by_id[chunk_id].get("chapter_title", ""),
                        "score": serialize_score(score),
                        "relevant": chunk_id in relevant,
                    }
                    for position, (chunk_id, score) in enumerate(ranked, start=1)
                ],
            }
        )

    metrics = {
        **{
            f"hit@{cutoff}": {
                "successful_queries": hits[cutoff],
                "total_queries": total,
                "ratio": _ratio(hits[cutoff], total),
            }
            for cutoff in HIT_CUTOFFS
        },
        "mrr@5": {
            "reciprocal_rank_sum": serialize_score(reciprocal_sum),
            "total_queries": total,
            "macro_average": _ratio(reciprocal_sum, total),
        },
        "recall@5": {
            "macro_average": _ratio(recall_sum, total),
            "total_queries": total,
        },
        "macro_span_recall@5": {
            "macro_average": _ratio(span_recall_sum, total),
            "total_queries": total,
        },
        "span_coverage@5": {
            "covered_spans": covered_spans,
            "total_gold_spans": total_spans,
            "ratio": _ratio(covered_spans, total_spans),
        },
    }
    return metrics, per_query


def _counts(values: Iterable[str]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for value in values:
        counted[value] = counted.get(value, 0) + 1
    return dict(sorted(counted.items()))


def corpus_fingerprint(chunks: Sequence[dict[str, Any]]) -> str:
    """Hash the retrieval-relevant content only, in a canonical order.

    Identical corpus content gives an identical fingerprint no matter where the
    files live or how they are split across chunk files.
    """
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda row: row["chunk_id"]):
        digest.update(chunk["chunk_id"].encode("utf-8"))
        digest.update(b"\x00")
        digest.update(chunk["text"].encode("utf-8"))
        digest.update(b"\x00")
    return "sha256:" + digest.hexdigest()


def file_fingerprint(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_text(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _sample(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= REVIEW_SAMPLE_CHARS:
        return collapsed
    return collapsed[:REVIEW_SAMPLE_CHARS] + "…"


def _short_id(chunk_id: str) -> str:
    return chunk_id[: len("chunk-") + 8]


def _watch_url(video_id: str, start_ms: int) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={start_ms // 1000}s"


def build_review_report(
    plans: Sequence[QueryPlan],
    chunks: Sequence[dict[str, Any]],
    query_set_path: Path,
) -> str:
    eligible = eligible_chunks(chunks)
    videos = sorted({chunk["video_id"] for chunk in chunks})
    lines: list[str] = []
    lines.append("# YouTube 검색 평가 질문 검토 보고서")
    lines.append("")
    lines.append("이 문서는 `--review-only` 실행이 생성합니다. 모델을 불러오지 않고 질문셋 스키마와")
    lines.append("gold span → eligible chunk 매핑만 검증합니다. 매핑된 chunk는 모두 목록으로 표시하지만")
    lines.append("자막 전문은 싣지 않으며, span당 overlap coefficient가 가장 큰 chunk 하나에서만")
    lines.append(f"최대 {REVIEW_SAMPLE_CHARS}자 표본을 인용합니다.")
    lines.append("")
    lines.append("## 요약")
    lines.append("")
    lines.append("| 항목 | 값 |")
    lines.append("|---|---|")
    lines.append(f"| 질문셋 | `{query_set_path.as_posix()}` |")
    lines.append(f"| 질문 수 | {len(plans)} |")
    lines.append(f"| 상태 분포 | {_counts(plan.review_status for plan in plans)} |")
    lines.append(f"| split 분포 | {_counts(plan.split for plan in plans)} |")
    lines.append(f"| 유형 분포 | {_counts(str(plan.query['query_type']) for plan in plans)} |")
    lines.append(f"| 영상 분포 | {_counts(str(plan.query['video_id']) for plan in plans)} |")
    lines.append(f"| gold span 수 | {sum(len(plan.spans) for plan in plans)} |")
    lines.append(f"| corpus | 영상 {len(videos)}개 / chunk {len(chunks)}개 / eligible {len(eligible)}개 |")
    lines.append("")
    lines.append("## 검토 방법")
    lines.append("")
    lines.append("1. 질문이 이 corpus만 보고 답할 수 있는지 확인합니다.")
    lines.append("2. gold span이 실제 답변 근거 구간인지 시간 링크로 확인합니다.")
    lines.append("3. 매핑된 chunk 표본이 근거로 충분하면 `review_status`를 `APPROVED`로,")
    lines.append("   근거가 어긋나면 `REJECTED`로 바꾸고 `review_reason`과 `reviewed_at`을 채웁니다.")
    lines.append("4. 최초 생성 시점의 질문과 span은 모두 `PENDING`입니다. 검토 전에는 평가에 쓰이지 않습니다.")
    lines.append("")
    lines.append("## split 사용 정책")
    lines.append("")
    for item in SPLIT_POLICY:
        lines.append(f"- {item}")
    lines.append("")

    for status in REVIEW_STATUSES:
        group = [plan for plan in plans if plan.review_status == status]
        if not group:
            continue
        lines.append(f"## {status} ({len(group)}건)")
        lines.append("")
        for plan in group:
            query = plan.query
            lines.append(f"### {plan.query_id} · {query['query_type']} · {plan.split}")
            lines.append("")
            lines.append(f"- 질문: {query['question']}")
            lines.append(f"- 영상: `{query['video_id']}`")
            lines.append(f"- 상태: {status} / reviewed_at: {query.get('reviewed_at') or '-'}")
            if str(query.get("review_reason", "")).strip():
                lines.append(f"- 검토 사유: {query['review_reason']}")
            lines.append(f"- 정답 chunk {len(plan.relevant_chunk_ids)}개 / gold span {len(plan.spans)}개")
            lines.append("")
            for span in plan.spans:
                lines.append(
                    f"#### {span.span_id} · {format_ms(span.start_ms)}–{format_ms(span.end_ms)}"
                )
                lines.append("")
                if span.note:
                    lines.append(f"- 메모: {span.note}")
                lines.append(f"- 확인 링크: {_watch_url(query['video_id'], span.start_ms)}")
                lines.append("")
                lines.append("| chunk | chapter | chunk 구간 | overlap(ms) | overlap coefficient |")
                lines.append("|---|---|---|---|---|")
                for match in span.matches:
                    chunk = match.chunk
                    chapter = f"{chunk.get('chapter_index')}: {chunk.get('chapter_title', '')}"
                    lines.append(
                        f"| `{_short_id(chunk['chunk_id'])}` (#{chunk['chunk_index']}) "
                        f"| {chapter} "
                        f"| {format_ms(chunk['start_ms'])}–{format_ms(chunk['end_ms'])} "
                        f"| {match.overlap_ms} "
                        f"| {serialize_score(match.overlap_coefficient)} |"
                    )
                lines.append("")
                top = span.matches[0]
                lines.append(
                    f"overlap coefficient 최대 chunk `{_short_id(top.chunk['chunk_id'])}` 표본 "
                    f"(최대 {REVIEW_SAMPLE_CHARS}자, 나머지 chunk는 매핑 정보만 표시):"
                )
                lines.append("")
                lines.append(f"> {_sample(top.chunk['text'])}")
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_run_report(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    lines: list[str] = []
    lines.append("# YouTube 검색 baseline 결과")
    lines.append("")
    lines.append("| 항목 | 값 |")
    lines.append("|---|---|")
    lines.append(f"| 모델 | `{payload['run']['model_name']}` |")
    lines.append(f"| split | {payload['run']['split']} |")
    lines.append(f"| top-k | {payload['run']['top_k']} |")
    lines.append(f"| 평가 질문 수 | {payload['query_set']['evaluated_queries']} |")
    lines.append(f"| corpus | chunk {payload['corpus']['total_chunks']}개 / eligible {payload['corpus']['eligible_chunks']}개 |")
    lines.append("")
    lines.append("## 지표")
    lines.append("")
    lines.append("성공 개수로 읽는 지표:")
    lines.append("")
    lines.append("| 지표 | successful_queries / total_queries | 비율 |")
    lines.append("|---|---|---|")
    for cutoff in HIT_CUTOFFS:
        entry = metrics[f"hit@{cutoff}"]
        lines.append(
            f"| Hit@{cutoff} | {entry['successful_queries']} / {entry['total_queries']} | {entry['ratio']} |"
        )
    lines.append("")
    lines.append("평균으로 읽는 지표 (성공 개수가 아닙니다):")
    lines.append("")
    lines.append("| 지표 | 정의 | 값 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| MRR@5 | reciprocal_rank 합계 {metrics['mrr@5']['reciprocal_rank_sum']} / "
        f"query {metrics['mrr@5']['total_queries']}개 | {metrics['mrr@5']['macro_average']} |"
    )
    lines.append(
        f"| Recall@5 | query별 recall의 macro average | {metrics['recall@5']['macro_average']} |"
    )
    lines.append(
        f"| macro_span_recall@5 | query별 span recall의 macro average "
        f"| {metrics['macro_span_recall@5']['macro_average']} |"
    )
    lines.append("")
    lines.append("span 단위 micro count:")
    lines.append("")
    coverage = metrics["span_coverage@5"]
    lines.append("| 지표 | covered_spans / total_gold_spans | 비율 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| span_coverage@5 | {coverage['covered_spans']} / {coverage['total_gold_spans']} "
        f"| {coverage['ratio']} |"
    )
    lines.append("")
    lines.append("## split 사용 정책")
    lines.append("")
    for item in SPLIT_POLICY:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 한계")
    lines.append("")
    for item in payload["limitations"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 질문별 결과")
    lines.append("")
    lines.append("| query | type | split | first_relevant_rank | RR | recall@5 | span_recall@5 |")
    lines.append("|---|---|---|---|---|---|---|")
    for entry in payload["per_query"]:
        lines.append(
            f"| {entry['query_id']} | {entry['query_type']} | {entry['split']} "
            f"| {entry['first_relevant_rank'] if entry['first_relevant_rank'] else '-'} "
            f"| {entry['reciprocal_rank']} | {entry['recall@5']} | {entry['span_recall@5']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def dependency_versions(packages: Sequence[str] = DEPENDENCY_PACKAGES) -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    resolved: dict[str, str] = {}
    for package in packages:
        try:
            resolved[package] = version(package)
        except PackageNotFoundError:
            resolved[package] = "not-installed"
    return resolved


def load_encoder(model_name: str) -> Encoder:
    """Import and load the embedding model. Never called by --review-only."""
    if model_name != SUPPORTED_MODEL:
        raise EvaluationError(f"unsupported model: {model_name!r}")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise EvaluationError(
            "sentence-transformers is required for evaluation runs "
            "(`uv add sentence-transformers`); --review-only does not need it"
        ) from exc

    model = SentenceTransformer(model_name)

    class SentenceTransformerEncoder:
        info = EncoderInfo(name=model_name, dependency_versions=dependency_versions())

        def encode(self, texts: Sequence[str]) -> list[list[float]]:
            return [
                list(map(float, vector))
                for vector in model.encode(list(texts), normalize_embeddings=True)
            ]

    return SentenceTransformerEncoder()


def run_review_only(
    query_set: Path,
    chunk_dir: Path,
    transcript_dir: Path,
    review_path: Path,
) -> tuple[list[QueryPlan], Path]:
    chunks = load_chunks(chunk_dir)
    bounds = load_transcript_bounds(transcript_dir, (chunk["video_id"] for chunk in chunks))
    plans = build_query_plans(load_queries(query_set), chunks, bounds)
    write_text(build_review_report(plans, chunks, query_set), review_path)
    return plans, review_path


def run_evaluation(
    query_set: Path,
    chunk_dir: Path,
    transcript_dir: Path,
    result_dir: Path,
    settings: RunSettings,
    encoder: Encoder | None = None,
) -> dict[str, Any]:
    settings.validate()
    chunks = load_chunks(chunk_dir)
    corpus = eligible_chunks(chunks)
    if not corpus:
        raise EvaluationError("no embedding_eligible chunk in the corpus")
    bounds = load_transcript_bounds(transcript_dir, (chunk["video_id"] for chunk in chunks))
    queries = load_queries(query_set)
    plans = build_query_plans(queries, chunks, bounds)

    approved = [plan for plan in plans if plan.review_status == "APPROVED"]
    if not approved:
        raise EvaluationError(
            f"no APPROVED query in {query_set}: review the candidates first "
            "(`--review-only`) and set review_status/reviewed_at. "
            "The embedding model is not loaded."
        )
    selected = approved if settings.split == "all" else [p for p in approved if p.split == settings.split]
    if not selected:
        raise EvaluationError(
            f"no APPROVED query in split {settings.split!r}. The embedding model is not loaded."
        )

    # Every schema, span, video_id and eligible-mapping check is done above,
    # so this is the first line that may import or download a model.
    if encoder is None:
        encoder = load_encoder(settings.model_name)

    started = time.perf_counter()
    corpus_vectors = encoder.encode([PASSAGE_PREFIX + chunk["text"] for chunk in corpus])
    corpus_seconds = time.perf_counter() - started
    chunk_ids = [chunk["chunk_id"] for chunk in corpus]
    if len(corpus_vectors) != len(chunk_ids):
        raise EvaluationError("encoder returned a different number of passage vectors")

    rankings: dict[str, list[tuple[str, float]]] = {}
    latencies: list[dict[str, Any]] = []
    for plan in selected:
        query_started = time.perf_counter()
        query_vector = encoder.encode([QUERY_PREFIX + str(plan.query["question"])])[0]
        ranked = rank_chunks(query_vector, corpus_vectors, chunk_ids, settings.top_k)
        rankings[plan.query_id] = ranked
        latencies.append(
            {
                "query_id": plan.query_id,
                "encode_and_rank_ms": round((time.perf_counter() - query_started) * 1000, 3),
            }
        )

    chunk_by_id = {chunk["chunk_id"]: chunk for chunk in corpus}
    metrics, per_query = build_metrics(selected, rankings, chunk_by_id)

    payload = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "run": {
            "split": settings.split,
            "top_k": settings.top_k,
            "model_name": encoder.info.name,
            "query_prefix": QUERY_PREFIX,
            "passage_prefix": PASSAGE_PREFIX,
            "score_decimals": SCORE_DECIMALS,
            "tie_break": "ascending chunk_id",
            "dependency_versions": dict(sorted(encoder.info.dependency_versions.items())),
        },
        # Provenance is content addressed on purpose: a run location or a temp
        # directory must never reach this artifact, or it stops being byte
        # identical across machines for the same corpus.
        "corpus": {
            "video_ids": sorted({chunk["video_id"] for chunk in chunks}),
            "videos": len({chunk["video_id"] for chunk in chunks}),
            "total_chunks": len(chunks),
            "eligible_chunks": len(corpus),
            "fingerprint": corpus_fingerprint(corpus),
        },
        "query_set": {
            "fingerprint": file_fingerprint(query_set),
            "total_queries": len(plans),
            "approved_queries": len(approved),
            "evaluated_queries": len(selected),
            "split_counts": _counts(plan.split for plan in selected),
            "type_counts": _counts(str(plan.query["query_type"]) for plan in selected),
        },
        "metrics": metrics,
        "per_query": per_query,
        "split_policy": list(SPLIT_POLICY),
        "limitations": list(LIMITATIONS),
    }

    metrics_path = result_dir / f"retrieval_metrics_{settings.split}.json"
    report_path = result_dir / f"retrieval_report_{settings.split}.md"
    runtime_path = result_dir / f"retrieval_runtime_{settings.split}.json"
    write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n", metrics_path)
    write_text(build_run_report(payload), report_path)
    write_text(
        json.dumps(
            {
                "note": "latency and timestamps are environment dependent and are excluded from determinism checks",
                "run_started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "corpus_encode_ms": round(corpus_seconds * 1000, 3),
                "per_query": latencies,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        runtime_path,
    )
    return {
        "payload": payload,
        "metrics_path": metrics_path,
        "report_path": report_path,
        "runtime_path": runtime_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-set", type=Path, default=DEFAULT_QUERY_SET)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--transcript-dir", type=Path, default=DEFAULT_TRANSCRIPT_DIR)
    parser.add_argument("--review-path", type=Path, default=DEFAULT_REVIEW_PATH)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="validate the query set and write the review report without loading any model",
    )
    parser.add_argument("--split", default="dev", help=f"one of {list(SPLIT_CHOICES)}")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help=f"must be >= {MIN_TOP_K}")
    parser.add_argument(
        "--model-name",
        default=SUPPORTED_MODEL,
        help=f"only {SUPPORTED_MODEL} is supported in this MVP",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.review_only:
            plans, path = run_review_only(
                args.query_set, args.chunk_dir, args.transcript_dir, args.review_path
            )
            statuses = _counts(plan.review_status for plan in plans)
            print(f"review report: {path}")
            print(f"queries: {len(plans)} {statuses}")
            print(f"splits: {_counts(plan.split for plan in plans)}")
            print(f"types: {_counts(str(plan.query['query_type']) for plan in plans)}")
            print(f"gold spans: {sum(len(plan.spans) for plan in plans)}")
            for plan in plans:
                if plan.review_status != "PENDING":
                    continue
                spans = ", ".join(
                    f"{span.span_id} {format_ms(span.start_ms)}-{format_ms(span.end_ms)} "
                    f"→ {len(span.matches)} chunk"
                    for span in plan.spans
                )
                print(f"  PENDING {plan.query_id} [{plan.query['query_type']}/{plan.split}] {spans}")
            return 0

        settings = RunSettings(top_k=args.top_k, model_name=args.model_name, split=args.split)
        settings.validate()
        result = run_evaluation(
            args.query_set,
            args.chunk_dir,
            args.transcript_dir,
            args.result_dir,
            settings,
        )
        print(result["metrics_path"])
        print(result["report_path"])
        print(result["runtime_path"])
    except (OSError, UnicodeError, EvaluationError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
