"""Run owner fixture questions through the existing dense pipeline for coverage review.

These 20 questions were written from how owners actually phrase a problem, not from
the corpus. They carry no gold span, so Hit@k, MRR and Recall are undefined here and
none of them is computed: inventing a gold label to make the numbers appear would
describe the label, not the retrieval.

What this run produces instead is the material a person needs to judge coverage:
the top-k chunks the pipeline actually returns, the score_gap it would gate on, and
whether that gate agrees with the outcome the fixture expects. The coverage verdict
itself (answerable / partial / missing) is left blank for a human to fill in.

Retrieval is not reimplemented. The encoder, the 'query: '/'passage: ' prefixes, the
eligible-chunk filter, the tie-break and the score statistics are imported from
scripts/evaluate_youtube_retrieval.py, the same way scripts/generate_answers.py does
it, so this report describes the baseline pipeline rather than a lookalike.

Usage:
    uv run python scripts/run_owner_fixture_coverage.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_QUERIES = Path("data/eval/queries/owner_fixtures.jsonl")
DEFAULT_CHUNK_DIR = Path("data/processed/youtube/chunks")
DEFAULT_REPORT = Path("reports/generated/owner_fixtures_coverage.md")

QUERY_SCHEMA_VERSION = "owner-fixture-query-v1"

# The operating point already adopted by scripts/generate_answers.py
# (ANSWER_AT_OR_ABOVE). Restated as a constant rather than imported so this script
# reads standalone, and asserted against the source of truth at run time below.
GATE_THRESHOLD = 0.024

GATE_PASS = "PASS"
GATE_REFUSE = "REFUSE"

TOP_K = 5
REPORT_TOP_N = 3
SNIPPET_CHARS = 150

# Read but never written by this script: coverage is a human judgement.
COVERAGE_VALUES = ("answerable", "partial", "missing")

# Summary section ②: which fixture ids the scenario observations are about. Kept here
# so the report and the questions it discusses cannot drift apart silently.
SCENARIO_1_IDS = ("Q01", "Q04", "Q05")
Q06_ID = "Q06"
EXPECTED_REFUSE_IDS = ("Q17", "Q18", "Q19")
# The three questions written as known gaps before anyone judged coverage. Section ④
# still reports on them by name, but the missing_data population is read from the
# query set rather than from this tuple: coverage review moved ten more questions
# into it, and a hardcoded list would quietly under-report that.
ORIGINAL_MISSING_DATA_IDS = ("Q03", "Q16", "Q20")

# Section ② asks whether both halves of the two-hop question show up in the same
# top-5. Presence is decided by surface keywords, so it is reported as "these words
# appear in the retrieved text", not as "the chunk covers this topic".
Q06_TOPIC_KEYWORDS = {
    "분리불안": ("분리불안", "분리 불안"),
    "켄넬 금기": ("켄넬", "크레이트", "하우스", "울타리", "철장"),
}


class CoverageError(RuntimeError):
    """Raised when inputs or settings are unusable."""


def _load_retrieval() -> Any:
    """Import the evaluator by path so the run works from any working directory."""
    name = "evaluate_youtube_retrieval"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise CoverageError(f"cannot import retrieval code from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_generation() -> Any:
    """Import the answer script only to read the adopted threshold from it."""
    name = "generate_answers"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise CoverageError(f"cannot import generation code from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


retrieval = _load_retrieval()


def check_threshold_matches_baseline() -> None:
    """Fail loudly if the adopted operating point moved without this script following.

    A coverage report that gates at a different number than the answer pipeline is
    worse than no report: it looks like evidence about the pipeline that ships.
    """
    adopted = getattr(_load_generation(), "ANSWER_AT_OR_ABOVE", None)
    if adopted != GATE_THRESHOLD:
        raise CoverageError(
            f"gate threshold drift: this script gates at {GATE_THRESHOLD}, but "
            f"generate_answers.ANSWER_AT_OR_ABOVE is {adopted}. Update both together."
        )


def load_fixtures(path: Path) -> list[dict[str, Any]]:
    """Load the fixture set and check only what this script relies on."""
    if not path.is_file():
        raise CoverageError(f"file not found: {path}")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CoverageError(f"invalid JSON at {path}:{number}") from exc
        if row.get("schema_version") != QUERY_SCHEMA_VERSION:
            raise CoverageError(
                f"{path}:{number}: schema_version must be {QUERY_SCHEMA_VERSION!r}"
            )
        for key in ("query_id", "question"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise CoverageError(f"{path}:{number}: {key} must be a non-empty string")
        if row["query_id"] in seen:
            raise CoverageError(f"{path}:{number}: duplicate query_id {row['query_id']!r}")
        seen.add(row["query_id"])
        if row.get("expected_outcome") not in ("ANSWER", "REFUSE"):
            raise CoverageError(
                f"{path}:{number}: expected_outcome must be 'ANSWER' or 'REFUSE'"
            )
        if row.get("coverage") is not None and row["coverage"] not in COVERAGE_VALUES:
            raise CoverageError(
                f"{path}:{number}: coverage must be null or one of {list(COVERAGE_VALUES)}"
            )
        # note carries why a coverage verdict is not final yet ("provisional: ...").
        # Nullable rather than optional: every row has the key, so a reader never has
        # to tell "no note" apart from "this row predates the field".
        if "note" not in row:
            raise CoverageError(f"{path}:{number}: note is required (use null when empty)")
        if row["note"] is not None and not isinstance(row["note"], str):
            raise CoverageError(f"{path}:{number}: note must be null or a string")
        # Gold is absent by design. A fixture that grew one is no longer this set.
        if row.get("gold_chunk_fingerprints"):
            raise CoverageError(
                f"{path}:{number}: this run is for gold-free fixtures; "
                f"{row['query_id']} carries gold_chunk_fingerprints. "
                "Evaluate it with scripts/evaluate_youtube_retrieval.py instead."
            )
        rows.append(row)
    if not rows:
        raise CoverageError(f"empty fixture set: {path}")
    return rows


def gate_verdict(score_gap: float, threshold: float = GATE_THRESHOLD) -> str:
    """PASS at or above the threshold, REFUSE below it. Boundary is inclusive up."""
    return GATE_PASS if score_gap >= threshold else GATE_REFUSE


def gate_agrees(expected_outcome: str, verdict: str) -> bool:
    """Whether the gate landed where the fixture said it should."""
    return (expected_outcome == "ANSWER") == (verdict == GATE_PASS)


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """First `limit` characters, flattened to one table cell."""
    flat = " ".join(text.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def short_id(chunk_id: str) -> str:
    """Trim the chunk hash to something a table can hold; full ids go in the JSON."""
    return chunk_id[:18] if len(chunk_id) > 18 else chunk_id


def retrieve(
    fixtures: Sequence[dict[str, Any]],
    chunk_dir: Path,
    top_k: int = TOP_K,
    device: str = "cpu",
    encoder: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank every fixture question against the baseline corpus, and return the corpus too.

    Every step below is the evaluator's own function, called in the evaluator's order.
    """
    chunks = retrieval.load_chunks(chunk_dir)
    corpus = retrieval.eligible_chunks(chunks)
    if not corpus:
        raise CoverageError("no embedding_eligible chunk in the corpus")
    chunk_ids = [row["chunk_id"] for row in corpus]
    by_id = {row["chunk_id"]: row for row in corpus}

    retrieval.ensure_device_available(device)
    if encoder is None:
        encoder = retrieval.load_encoder(retrieval.SUPPORTED_MODEL, device)

    corpus_vectors = encoder.encode([retrieval.PASSAGE_PREFIX + row["text"] for row in corpus])
    if len(corpus_vectors) != len(chunk_ids):
        raise CoverageError("encoder returned a different number of passage vectors")

    records: list[dict[str, Any]] = []
    for fixture in fixtures:
        question = str(fixture["question"])
        query_vector = encoder.encode([retrieval.QUERY_PREFIX + question])[0]
        # Statistics come from the full corpus, before the top-k cut, exactly as the
        # evaluator measures them — score_gap is top1 minus the corpus mean.
        scores = retrieval.similarity_scores(query_vector, corpus_vectors)
        ranked = retrieval.rank_scores(scores, chunk_ids, top_k)
        stats = retrieval.score_statistics(scores)
        verdict = gate_verdict(stats["score_gap"])
        records.append(
            {
                "query_id": fixture["query_id"],
                "question": question,
                "demo_scenario": fixture.get("demo_scenario"),
                "hop_type": fixture.get("hop_type"),
                "router_target": fixture.get("router_target"),
                "expected_outcome": fixture["expected_outcome"],
                "guard_level": fixture.get("guard_level"),
                "missing_data": fixture.get("missing_data"),
                "refuse_reason": fixture.get("refuse_reason"),
                "reason": fixture.get("reason"),
                "coverage": fixture.get("coverage"),
                "note": fixture.get("note"),
                "score_stats": stats,
                "score_gap": stats["score_gap"],
                "gate_verdict": verdict,
                "gate_matches_expected": gate_agrees(fixture["expected_outcome"], verdict),
                "top_k": [
                    {
                        "rank": rank,
                        "chunk_id": chunk_id,
                        "score": retrieval.serialize_score(score),
                        "video_id": by_id[chunk_id]["video_id"],
                        "chunk_index": by_id[chunk_id]["chunk_index"],
                        "chapter_title": by_id[chunk_id].get("chapter_title", ""),
                        "text": by_id[chunk_id]["text"],
                    }
                    for rank, (chunk_id, score) in enumerate(ranked, start=1)
                ],
            }
        )
    return records, corpus


def keyword_presence(record: dict[str, Any], keywords: Sequence[str]) -> list[dict[str, Any]]:
    """Ranks whose retrieved text literally contains one of `keywords`."""
    found = []
    for entry in record["top_k"]:
        matched = [word for word in keywords if word in entry["text"]]
        if matched:
            found.append({"rank": entry["rank"], "chunk_id": entry["chunk_id"], "matched": matched})
    return found


def corpus_keyword_counts(
    corpus: Sequence[dict[str, Any]], keywords: Sequence[str]
) -> dict[str, int]:
    """How many eligible chunks contain each keyword anywhere in the corpus.

    Reported next to the top-5 check so a miss can be read for what it is: a keyword
    absent from the whole corpus is a collection gap, while one present in the corpus
    but missing from top-5 is a ranking problem. The report must not blur the two.
    """
    return {
        word: sum(1 for chunk in corpus if word in chunk["text"]) for word in keywords
    }


def _by_id(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {record["query_id"]: record for record in records}


def build_report(
    records: Sequence[dict[str, Any]],
    corpus: Sequence[dict[str, Any]],
    query_set: Path,
    chunk_dir: Path,
) -> str:
    lines: list[str] = []
    lines.append("# 견주 픽스처 커버리지 리포트")
    lines.append("")
    lines.append(
        "견주 실사용 질문 20개를 기존 dense 파이프라인에 그대로 통과시킨 결과입니다. "
        "**gold 청크 라벨이 없는 질문셋이므로 Hit@k·MRR·Recall은 계산하지 않았습니다.** "
        "이 리포트는 사람이 커버리지를 판정하기 위한 검색 결과 덤프입니다."
    )
    lines.append("")
    lines.append("| 실행 설정 | 값 |")
    lines.append("|---|---|")
    lines.append(f"| 질문셋 | `{query_set.as_posix()}` ({len(records)}건) |")
    lines.append(f"| 코퍼스 | `{chunk_dir.as_posix()}` (embedding_eligible {len(corpus)}청크) |")
    lines.append(f"| 임베딩 모델 | `{retrieval.SUPPORTED_MODEL}` |")
    lines.append(f"| top-k | {TOP_K} (표에는 상위 {REPORT_TOP_N}건 표시) |")
    lines.append(
        f"| gate | `score_gap >= {GATE_THRESHOLD}` → {GATE_PASS} / "
        f"미만 → {GATE_REFUSE} (generate_answers.ANSWER_AT_OR_ABOVE와 동일) |"
    )
    lines.append("| score_gap 정의 | top1 점수 − 코퍼스 전체 평균 점수 (top-k 컷 이전) |")
    lines.append("")
    lines.append(
        "`일치` 열은 fixture의 `expected_outcome`과 gate 판정이 같은 방향인지만 봅니다. "
        "gate가 틀렸다는 뜻도, 기대가 틀렸다는 뜻도 아니고 둘이 갈렸다는 표시입니다."
    )
    lines.append("")
    lines.append(
        f"> **이 파일은 `scripts/{Path(__file__).name}`이 생성합니다. 직접 편집하지 마세요.** "
        f"coverage를 비롯한 사람 판정은 `{query_set.as_posix()}`에만 기록하고 이 리포트를 "
        "다시 생성하면 반영됩니다. 리포트를 수기로 고치면 다음 실행에서 지워집니다."
    )
    lines.append("")
    lines.append("## 질문별 결과")

    for record in records:
        labels = [
            f"hop={record['hop_type']}",
            f"router={record['router_target']}",
            f"expected={record['expected_outcome']}",
            f"guard={record['guard_level']}",
            f"missing_data={str(record['missing_data']).lower()}",
        ]
        if record["refuse_reason"]:
            labels.append(f"refuse_reason={record['refuse_reason']}")
        if record["demo_scenario"]:
            labels.append(f"시나리오{record['demo_scenario']}")

        lines.append("")
        lines.append(f"### {record['query_id']}")
        lines.append("")
        lines.append(f"> {record['question']}")
        lines.append("")
        lines.append(f"- 라벨: {' · '.join(labels)}")
        lines.append(f"- 픽스처 메모: {record['reason']}")
        lines.append("")
        lines.append(f"| 순위 | chunk_id | score | 본문 앞 {SNIPPET_CHARS}자 |")
        lines.append("|---|---|---|---|")
        for entry in record["top_k"][:REPORT_TOP_N]:
            lines.append(
                f"| {entry['rank']} | `{short_id(entry['chunk_id'])}` | "
                f"{entry['score']:.4f} | {snippet(entry['text'])} |"
            )
        lines.append("")
        mark = "✓" if record["gate_matches_expected"] else "✗"
        lines.append(
            f"- score_gap: **{record['score_gap']:.4f}** "
            f"(top1 {record['score_stats']['top1_score']:.4f} − "
            f"평균 {record['score_stats']['corpus_mean_score']:.4f})"
        )
        lines.append(f"- gate 판정: **{record['gate_verdict']}**")
        lines.append(f"- expected_outcome({record['expected_outcome']}) 일치 여부: {mark}")
        if record["coverage"] is None:
            lines.append(
                "- coverage: [ ]  ← answerable / partial / missing 중 하나를 사람이 "
                f"`{DEFAULT_QUERIES.as_posix()}`의 coverage 필드에 채웁니다"
            )
        else:
            suffix = f" ({record['note']})" if record["note"] else ""
            lines.append(f"- coverage: **{record['coverage']}**{suffix}")

    lines.append("")
    lines.append("## 요약")
    lines.extend(_summary_lines(records, corpus))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "관찰은 위 검색 결과에 실제로 나타난 것만 적었습니다. "
        "코퍼스에 없는 내용을 추측으로 채우지 않았고, gold 라벨을 만들지 않았습니다."
    )
    return "\n".join(lines).rstrip() + "\n"


def _summary_lines(
    records: Sequence[dict[str, Any]], corpus: Sequence[dict[str, Any]]
) -> list[str]:
    index = _by_id(records)
    lines: list[str] = []

    # ① 시나리오① 후보 3건의 검색 품질 비교
    lines.append("")
    lines.append("### ① 시나리오① 후보(Q01·Q04·Q05) 검색 품질 비교")
    lines.append("")
    lines.append("| id | 질문 요지 | top1 score | score_gap | 1-2위 차 | gate |")
    lines.append("|---|---|---|---|---|---|")
    for query_id in SCENARIO_1_IDS:
        record = index.get(query_id)
        if record is None:
            lines.append(f"| {query_id} | (질문셋에 없음) | - | - | - | - |")
            continue
        stats = record["score_stats"]
        margin = stats["top1_minus_top2"]
        lines.append(
            f"| {query_id} | {snippet(record['question'], 28)} | "
            f"{stats['top1_score']:.4f} | {record['score_gap']:.4f} | "
            f"{'-' if margin is None else f'{margin:.4f}'} | {record['gate_verdict']} |"
        )
    lines.append("")
    ranked = [index[q] for q in SCENARIO_1_IDS if q in index]
    if ranked:
        best = max(ranked, key=lambda r: r["score_gap"])
        worst = min(ranked, key=lambda r: r["score_gap"])
        lines.append(
            f"- score_gap이 가장 큰 쪽은 **{best['query_id']}**({best['score_gap']:.4f}), "
            f"가장 작은 쪽은 **{worst['query_id']}**({worst['score_gap']:.4f})입니다."
        )
        for record in ranked:
            top = record["top_k"][0]
            lines.append(
                f"- {record['query_id']} 1위: `{short_id(top['chunk_id'])}` "
                f"(챕터 「{top['chapter_title']}」, score {top['score']:.4f}) — {snippet(top['text'], 90)}"
            )

    # ② Q06 top-5에 두 축이 각각 보이는지
    lines.append("")
    lines.append("### ② Q06 top-5에 '분리불안'과 '켄넬 금기'가 각각 있는지")
    lines.append("")
    record = index.get(Q06_ID)
    if record is None:
        lines.append(f"- {Q06_ID}가 질문셋에 없습니다.")
    else:
        lines.append(
            "표층 키워드가 검색된 본문에 실제로 등장하는지만 봅니다. "
            "'그 청크가 해당 주제를 다룬다'는 판정이 아닙니다. "
            "코퍼스 전체 열은 top-5에 없는 이유가 랭킹 문제인지 수집 구멍인지 구분하기 위한 것입니다."
        )
        lines.append("")
        lines.append(f"| 축 | 키워드 | Q06 top-5 등장 | eligible 코퍼스 전체({len(corpus)}청크) |")
        lines.append("|---|---|---|---|")
        for label, keywords in Q06_TOPIC_KEYWORDS.items():
            hits = keyword_presence(record, keywords)
            where = (
                ", ".join(
                    f"{hit['rank']}위(`{short_id(hit['chunk_id'])}`: {'/'.join(hit['matched'])})"
                    for hit in hits
                )
                if hits
                else "없음"
            )
            counts = corpus_keyword_counts(corpus, keywords)
            corpus_cell = ", ".join(f"{word} {count}건" for word, count in counts.items())
            lines.append(f"| {label} | {'/'.join(keywords)} | {where} | {corpus_cell} |")
        lines.append("")
        for label, keywords in Q06_TOPIC_KEYWORDS.items():
            counts = corpus_keyword_counts(corpus, keywords)
            total = sum(counts.values())
            if total == 0:
                lines.append(
                    f"- **{label}** — Q06 top-5에도, eligible 코퍼스 전체에도 이 표현이 "
                    "한 번도 나오지 않습니다. top-5가 이 축을 놓친 것이 아니라 "
                    "코퍼스에 해당 표현이 들어간 청크 자체가 없습니다."
                )
            elif not keyword_presence(record, keywords):
                present = ", ".join(f"{w} {c}건" for w, c in counts.items() if c)
                lines.append(
                    f"- **{label}** — eligible 코퍼스 전체에서 {present} 등장하지만 "
                    "Q06 top-5에는 오르지 않았습니다. 등장 건수가 이 정도라면 랭킹에서 밀린 것인지 "
                    "코퍼스가 이 축을 얇게만 스치는 것인지는 해당 청크 본문을 직접 보고 판단해야 합니다."
                )
            else:
                lines.append(f"- **{label}** — top-5 안에 표현이 등장합니다.")
        lines.append("")
        lines.append(
            f"- 두 축이 같은 top-5 안에 함께 잡히는지가 이 시나리오의 전제인데, "
            f"{Q06_ID} score_gap은 {record['score_gap']:.4f}로 gate {record['gate_verdict']}입니다."
        )
        lines.append(
            "- top-5 챕터: "
            + ", ".join(f"「{entry['chapter_title']}」" for entry in record["top_k"])
        )

    # ③ REFUSE 기대 3건이 실제로 걸리는지
    lines.append("")
    lines.append("### ③ REFUSE 기대 3건(Q17·Q18·Q19)이 gate에 걸리는지")
    lines.append("")
    lines.append("| id | refuse_reason | score_gap | gate | 기대와 일치 |")
    lines.append("|---|---|---|---|---|")
    for query_id in EXPECTED_REFUSE_IDS:
        record = index.get(query_id)
        if record is None:
            lines.append(f"| {query_id} | - | - | (질문셋에 없음) | - |")
            continue
        lines.append(
            f"| {query_id} | {record['refuse_reason']} | {record['score_gap']:.4f} | "
            f"{record['gate_verdict']} | {'✓' if record['gate_matches_expected'] else '✗'} |"
        )
    lines.append("")
    blocked = [q for q in EXPECTED_REFUSE_IDS if index.get(q, {}).get("gate_verdict") == GATE_REFUSE]
    lines.append(
        f"- {len(blocked)}/{len(EXPECTED_REFUSE_IDS)}건이 gate에서 {GATE_REFUSE}로 걸렸습니다"
        f"{': ' + ', '.join(blocked) if blocked else ''}."
    )
    passed = [q for q in EXPECTED_REFUSE_IDS if index.get(q, {}).get("gate_verdict") == GATE_PASS]
    if passed:
        lines.append(
            f"- {', '.join(passed)}는 gate를 통과했습니다. "
            "이 셋의 거절 사유는 MEDICAL·SCOPE로, 유사도가 아니라 질문의 성격에서 나옵니다 — "
            "score_gap 하나로는 걸러지지 않는다는 뜻입니다."
        )

    # ④ missing_data 전체가 gate 아래인지
    flagged = [record for record in records if record["missing_data"]]
    lines.append("")
    lines.append(
        f"### ④ missing_data:true {len(flagged)}건이 gate 아래인지 "
        f"(최초 지정 3건: {'·'.join(ORIGINAL_MISSING_DATA_IDS)})"
    )
    lines.append("")
    lines.append("| id | 최초 지정 | score_gap | 임계값 대비 | gate | 기대와 일치 |")
    lines.append("|---|---|---|---|---|---|")
    for record in flagged:
        delta = record["score_gap"] - GATE_THRESHOLD
        origin = "○" if record["query_id"] in ORIGINAL_MISSING_DATA_IDS else "커버리지 판정 후 추가"
        lines.append(
            f"| {record['query_id']} | {origin} | {record['score_gap']:.4f} | {delta:+.4f} | "
            f"{record['gate_verdict']} | {'✓' if record['gate_matches_expected'] else '✗'} |"
        )
    lines.append("")
    below = [r["query_id"] for r in flagged if r["gate_verdict"] == GATE_REFUSE]
    above = [r["query_id"] for r in flagged if r["gate_verdict"] == GATE_PASS]
    lines.append(f"- {len(below)}/{len(flagged)}건이 임계값 아래입니다.")
    original = [r for r in flagged if r["query_id"] in ORIGINAL_MISSING_DATA_IDS]
    original_below = [r["query_id"] for r in original if r["gate_verdict"] == GATE_REFUSE]
    lines.append(
        f"- 최초 지정 3건만 보면 {len(original_below)}/{len(original)}건이 아래입니다"
        f"{': ' + ', '.join(original_below) if original_below else ''}."
    )
    if above:
        lines.append(
            f"- {', '.join(above)}는 코퍼스에 답이 없다고 판정된 질문인데도 gate를 통과했습니다. "
            "gate가 통과시킨 top-1이 무엇인지는 위 질문별 블록에서 확인하세요."
        )

    lines.extend(_human_verdict_lines(records))

    # 전체 일치율
    agreed = [record for record in records if record["gate_matches_expected"]]
    lines.append("")
    lines.append("### 전체")
    lines.append("")
    lines.append(
        f"- gate 판정이 expected_outcome과 일치한 건수: **{len(agreed)}/{len(records)}**"
    )
    disagreed = [record["query_id"] for record in records if not record["gate_matches_expected"]]
    if disagreed:
        lines.append(f"- 갈린 질문: {', '.join(disagreed)}")
    return lines


def _human_verdict_lines(records: Sequence[dict[str, Any]]) -> list[str]:
    """The coverage verdicts a person wrote, read back from the query set.

    Rendered from the same JSONL the labels live in, so this section cannot drift
    from the fixtures the way a hand-written appendix would.
    """
    lines: list[str] = ["", "### ⑤ 사람 커버리지 판정 결과", ""]
    judged = [record for record in records if record["coverage"] is not None]
    if not judged:
        lines.append(
            "- 아직 아무도 채우지 않았습니다. 위 질문별 블록의 `coverage: [ ]`를 보고 "
            f"`{DEFAULT_QUERIES.as_posix()}`의 coverage 필드에 기록하세요."
        )
        return lines

    lines.append(f"판정 완료 {len(judged)}/{len(records)}건. 값은 질문셋에서 읽어온 것입니다.")
    lines.append("")
    lines.append("| coverage | 건수 | 질문 |")
    lines.append("|---|---|---|")
    for value in COVERAGE_VALUES:
        group = [record["query_id"] for record in judged if record["coverage"] == value]
        if group:
            lines.append(f"| {value} | {len(group)} | {', '.join(group)} |")
    provisional = [record for record in judged if record["note"]]
    if provisional:
        lines.append("")
        lines.append(
            "- 잠정 판정: "
            + ", ".join(f"{r['query_id']}({r['coverage']})" for r in provisional)
            + " — 원영상 확인 후 확정합니다."
        )

    # The disagreement that matters is not how many, but which direction.
    false_pass = [
        record
        for record in judged
        if record["gate_verdict"] == GATE_PASS and record["expected_outcome"] == "REFUSE"
    ]
    false_refuse = [
        record
        for record in judged
        if record["gate_verdict"] == GATE_REFUSE and record["expected_outcome"] == "ANSWER"
    ]
    lines.append("")
    lines.append("| 갈린 방향 | 건수 | 질문 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| gate PASS · 기대 REFUSE (통과시키면 안 될 것을 통과) | {len(false_pass)} | "
        f"{', '.join(r['query_id'] for r in false_pass) or '-'} |"
    )
    lines.append(
        f"| gate REFUSE · 기대 ANSWER (답할 수 있는 것을 막음) | {len(false_refuse)} | "
        f"{', '.join(r['query_id'] for r in false_refuse) or '-'} |"
    )
    lines.append("")
    if false_pass and not false_refuse:
        gaps = ", ".join(f"{r['query_id']} {r['score_gap']:.4f}" for r in false_pass)
        lines.append(
            f"- 갈린 {len(false_pass)}건이 **전부 한 방향**입니다. score_gap이 임계값을 넘겼지만 "
            "사람이 보기에 코퍼스에 답이 없는 질문들이고, 반대 방향(답할 수 있는데 막힌 경우)은 "
            "0건입니다. gate가 지나치게 엄격한 것이 아니라 지나치게 관대하다는 뜻입니다."
        )
        lines.append(f"- 해당 질문의 score_gap: {gaps}")
        medical_scope = [r["query_id"] for r in false_pass if r["refuse_reason"] != "GAP"]
        if medical_scope:
            lines.append(
                f"- 이 중 {', '.join(medical_scope)}는 refuse_reason이 GAP이 아닙니다. "
                "유사도를 아무리 조정해도 이 축은 gate로 잡히지 않으며, "
                "`guardrail/seed_lexicon.json` 쪽에서 걸러야 합니다."
            )
    elif false_pass or false_refuse:
        lines.append(
            f"- 양방향으로 갈렸습니다: 통과시키면 안 될 것 {len(false_pass)}건, "
            f"막지 말아야 할 것 {len(false_refuse)}건."
        )
    else:
        lines.append("- gate 판정과 사람 판정이 모든 질문에서 같은 방향입니다.")
    return lines


def run(
    query_set: Path,
    chunk_dir: Path,
    report_path: Path,
    dump_path: Path | None,
    device: str,
    encoder: Any | None = None,
) -> dict[str, Any]:
    check_threshold_matches_baseline()
    fixtures = load_fixtures(query_set)
    records, corpus = retrieve(fixtures, chunk_dir, TOP_K, device, encoder)
    retrieval.write_text(build_report(records, corpus, query_set, chunk_dir), report_path)
    if dump_path is not None:
        retrieval.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            dump_path,
        )
    return {
        "records": records,
        "report_path": report_path,
        "corpus_size": len(corpus),
        "gate_pass": sum(1 for r in records if r["gate_verdict"] == GATE_PASS),
        "gate_refuse": sum(1 for r in records if r["gate_verdict"] == GATE_REFUSE),
        "matched": sum(1 for r in records if r["gate_matches_expected"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--dump",
        type=Path,
        default=None,
        help="optional JSONL of the full top-k records (report shows the top 3 only)",
    )
    parser.add_argument(
        "--device",
        default=retrieval.DEFAULT_DEVICE,
        choices=list(retrieval.DEVICE_CHOICES),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args.queries, args.chunk_dir, args.report, args.dump, args.device)
    except (OSError, CoverageError, retrieval.EvaluationError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    total = len(result["records"])
    print(f"질문 {total}건 / eligible 청크 {result['corpus_size']}개")
    print(f"  gate {GATE_PASS:<7} {result['gate_pass']:>3}건")
    print(f"  gate {GATE_REFUSE:<7} {result['gate_refuse']:>3}건")
    print(f"  expected_outcome 일치 {result['matched']}/{total}건")
    print(f"리포트: {result['report_path']}")
    print("Hit@k·MRR은 계산하지 않았습니다 (gold 라벨 없음).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
