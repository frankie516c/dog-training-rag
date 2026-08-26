"""작업대에서 승인한 라벨을 gold 질의 파일로 반영한다.

사람이 승인한 결과만 `review_status: APPROVED`가 된다 — 에이전트 제안은
`PENDING_HUMAN`으로 남아 있고, 이 스크립트를 거쳐야 승인 상태가 된다.

## 커밋 직전 마지막 그물

앵커 인용문은 커밋되는 파일에 들어가고 이 저장소는 public이다. 사람의 앵커
승인이 실제 관문이지만, 그것을 통과한 뒤에도 여기서 한 번 더 본다. 목록 대조가
아니라 **패턴 검사**이며, 걸리면 기록을 막는다.

정규식으로 반려동물 호칭을 찾는 것은 실측에서 실패했다(거짓 경고만 나오고 진짜는
0건). 그래서 이 그물은 호칭을 찾으려 하지 않고, **커밋되면 안 되는 것이 확실한
패턴**만 본다 — 마스킹된 실명(김*수 꼴), 이메일, 전화번호, URL 안의 개인 식별자.
호칭 판단은 사람이 이미 한 것으로 본다.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPORT = Path("data/eval/labeling/gold_labels_export.json")
GOLD = Path("data/eval/queries/gold_batch1.jsonl")

# 커밋되면 안 되는 것이 확실한 패턴만 본다.
BLOCKERS = [
    ("마스킹된 실명", re.compile(r"[가-힣]\*[가-힣]")),
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("전화번호", re.compile(r"0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}")),
]


def check_anchor(quote: str) -> list[str]:
    return [name for name, pattern in BLOCKERS if pattern.search(quote)]


def load_corpus(chunk_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory in chunk_dirs:
        for path in sorted(directory.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def revalidate_anchor(quote: str, doc_id: str, corpus: Sequence[dict[str, Any]]) -> str | None:
    """앵커가 지금 코퍼스에서도 그 문서의 청크를 가리키는지 다시 본다.

    불변식은 I1이다 — **앵커는 `(doc_id, quote)` 쌍으로 청크 집합을 결정한다.**
    인용문은 그 문서 안에서만 유일하면 되고, 코퍼스 전역 유일성은 요구하지 않는다.

    전역 유일성을 요구하던 판이 먼저 있었고 그것을 버린 이유는 두 가지다.

    1. 평가 경로가 이미 I1이다. `run_combined_retrieval_eval.gold_relevant_chunks()`는
       `doc_id`로 먼저 좁힌 뒤 인용문을 찾는다. 전역 검사는 **평가에는 아무 문제가
       없는데 기록만 거부하는** 비대칭을 만들었다.
    2. 코퍼스를 키우면 같은 문장이 다른 문서에 나타나는 것이 정상이다. 전역
       유일성은 확장할 때마다 gold를 흔들어 성립할 수 없다. `doc_id`를 청크가
       아니라 문서 단위로 올린 결정이 애초에 I1을 전제한다.

    "기록된 doc_id가 실제와 다르다"는 검사는 사라지지 않았다 — 그 문서 안에
    인용문이 없으면 여기서 걸린다.
    """
    in_doc = [c for c in corpus if c.get("doc_id") == doc_id]
    if not in_doc:
        return f"doc_id {doc_id!r}에 해당하는 청크가 코퍼스에 없다"
    hits = [c for c in in_doc
            if quote in c.get("text", "") and c.get("citation_allowed") is not False]
    if not hits:
        return (f"{doc_id}의 어느 청크에도 인용문이 없다 — 본문이 편집됐거나 "
                "청크 경계를 가로지르거나, doc_id가 잘못 기록됐다")
    return None


def is_video_chunk(chunk_id: str, by_id: dict[str, dict[str, Any]]) -> bool:
    """영상 청크인가. 영상만 `video_id`와 시간 경계를 갖는다."""
    chunk = by_id.get(chunk_id)
    return bool(chunk and chunk.get("video_id") and chunk.get("start_ms") is not None)


def promote_video_chunks(
    query_id: str,
    chunk_ids: Sequence[str],
    by_id: dict[str, dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    """영상 청크 id를 `(video_id, relevant_spans)`로 승격한다.

    평가는 영상 정답을 시간축으로 읽는다 — `relevant_spans`의 구간과 겹치는
    청크가 gold다. 청크 자신의 `start_ms`/`end_ms`를 그대로 span으로 쓰면
    정확히 그 청크로 되돌아온다(배치1 4건 실측: 각 span이 같은 영상의 다른
    청크와 하나도 겹치지 않는다). 여백을 두거나 중점을 잡는 보정이 필요 없다.

    시간축을 쓰는 이유는 앵커가 `doc_id`를 쓰는 이유와 같다 — `chunk_id`는
    본문 해시라 재청킹·재전사에 못 견딘다. 밀리초는 원본의 좌표라 견딘다.

    돌려주는 것은 `(video_id, spans, problems)`다. 사람이 고른 청크를 조용히
    버리지 않으려고 문제를 모아서 함께 돌려준다.
    """
    problems: list[str] = []
    spans: list[dict[str, Any]] = []
    videos: set[str] = set()
    for index, chunk_id in enumerate(chunk_ids, start=1):
        chunk = by_id.get(chunk_id)
        if chunk is None:
            problems.append(f"{query_id}: gold 영상 청크 {chunk_id[:20]}…를 코퍼스에서 찾지 못했다")
            continue
        # 임베딩에서 제외된 청크는 검색 대상이 아니다. gold로 두면 어떤 검색기도
        # 찾을 수 없는 정답이 되어 지표가 영구히 0이 된다.
        if not chunk.get("embedding_eligible"):
            problems.append(
                f"{query_id}: gold 영상 청크가 embedding_eligible=False다 "
                f"({chunk.get('exclusion_reason') or '사유 미기재'}) — 검색 대상이 아니라 정답이 될 수 없다"
            )
            continue
        videos.add(chunk["video_id"])
        spans.append({
            "span_id": f"{query_id}-s{index}",
            "start_ms": chunk["start_ms"],
            "end_ms": chunk["end_ms"],
            "note": f"영상 청크 #{chunk.get('chunk_index')}에서 승격",
        })
    if len(videos) > 1:
        # 행 단위 video_id가 스칼라라 한 질의가 여러 영상을 가리킬 수 없다.
        # 조용히 하나만 고르면 나머지 정답이 사라지므로 막는다.
        problems.append(
            f"{query_id}: gold 영상 청크가 영상 {len(videos)}개에 걸쳐 있다 "
            f"({', '.join(sorted(videos))}) — 현재 스키마는 행마다 video_id 하나만 담는다"
        )
        return None, [], problems
    return (videos.pop() if videos else None), spans, problems


def revalidate_span(
    video_id: str,
    span: dict[str, Any],
    corpus: Sequence[dict[str, Any]],
) -> str | None:
    """span이 지금 코퍼스에서도 정확히 청크 하나로 되돌아오는지 본다.

    `revalidate_anchor()`의 영상판이다. 재청킹이나 재전사로 경계가 움직이면 한
    span이 여러 청크에 걸치거나 아무 데도 안 걸릴 수 있는데, 전자는 정답 집합이
    조용히 커져 Hit@1을 쉽게 만들고 후자는 평가를 죽인다.
    """
    hits = [
        c for c in corpus
        if c.get("video_id") == video_id and c.get("start_ms") is not None
        and c.get("embedding_eligible")
        and min(c["end_ms"], span["end_ms"]) - max(c["start_ms"], span["start_ms"]) > 0
    ]
    if not hits:
        return f"{span['span_id']}: 구간과 겹치는 영상 청크가 없다 — 재청킹으로 경계가 움직였다"
    if len(hits) > 1:
        return (f"{span['span_id']}: 구간이 청크 {len(hits)}개에 걸친다"
                f"(#{[c.get('chunk_index') for c in hits]}) — 정답 집합이 의도보다 넓어진다")
    return None


def anchor_collisions(quote: str, doc_id: str, corpus: Sequence[dict[str, Any]]) -> list[str]:
    """인용문이 **다른** 문서에도 나타나는지 본다. 거부하지 않고 보고만 한다.

    I1 아래에서 이것은 오류가 아니다 — 앵커는 `doc_id`로 이미 좁혀져 있다.
    다만 인용문이 여러 문서에 퍼져 있다는 것은 그 문장이 정형구라는 신호이고,
    사람이 앵커를 다시 고를 판단 재료가 되므로 버리지 않고 남긴다.
    """
    others = {c.get("doc_id") for c in corpus
              if c.get("doc_id") and c.get("doc_id") != doc_id
              and quote in c.get("text", "")
              and c.get("citation_allowed") is not False}
    return sorted(others)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--export", type=Path, default=EXPORT)
    ap.add_argument("--gold", type=Path, default=GOLD)
    ap.add_argument("--min-anchor-chars", type=int, default=20)
    ap.add_argument("--doc-chunks", type=Path, default=Path("data/processed/documents/chunks"))
    ap.add_argument("--video-chunks", type=Path, default=Path("data/processed/youtube/chunks"))
    ap.add_argument("--skip-revalidate", action="store_true",
                    help="코퍼스가 없는 환경에서 앵커 재검증을 건너뛴다")
    args = ap.parse_args()

    if not args.export.is_file():
        print(f"{args.export} 없음 — 작업대에서 '내려받기' 후 이 위치에 둘 것")
        return 1

    export = json.loads(args.export.read_text(encoding="utf-8"))
    by_id = {q["query_id"]: q for q in export["queries"]}

    rows = [json.loads(l) for l in args.gold.read_text(encoding="utf-8").splitlines() if l.strip()]

    corpus: list[dict[str, Any]] = []
    if not args.skip_revalidate:
        dirs = [d for d in (args.doc_chunks, args.video_chunks) if d.is_dir()]
        corpus = load_corpus(dirs)
        if not corpus:
            print("경고: 코퍼스 청크를 찾지 못해 앵커 재검증을 건너뛴다 "
                  f"({args.doc_chunks}, {args.video_chunks})")
    corpus_by_id = {c["chunk_id"]: c for c in corpus}

    problems: list[str] = []
    notes: list[str] = []
    approved = skipped = 0
    flipped: list[str] = []

    for row in rows:
        got = by_id.get(row["query_id"])
        if not got or not got.get("coverage"):
            skipped += 1
            continue

        # 데이터 무결성 조건 — 작업대 blockers()와 **독립**으로 검사한다.
        #
        # 작업대는 UI 편의이고 우회 가능하다(gold 파일을 손으로 쓰거나 export를
        # 직접 만들면 그만이다). coverage=answerable인데 평가가 읽을 수 있는 근거가
        # 없으면 gold_relevant_chunks()가 EvalError로 죽는다 — 그 상태가 커밋되면
        # 평가 자체가 안 돌아가므로 여기서 막는다.
        #
        # **청크 id는 그 자체로 근거가 아니다.** 평가는 두 체계만 읽는다 — 영상은
        # relevant_spans(시간축), 문서는 anchors(인용문 + doc_id). chunk_id는
        # text_sha256 기반이라 재인제스트에 못 견뎌 어느 쪽도 될 수 없다.
        #
        # 이 구분이 없던 판에서는 gold_chunk_ids가 앵커의 대체물로 인정됐고,
        # 그런데 기록 블록은 그것을 행에 쓰지 않았다. 그래서 "통과"로 판정된 행이
        # 파일에서는 근거 0이 되어, 검증문이 예고한 바로 그 실패를 검증문 자신이
        # 통과시켰다(g001·g019·g020이 이 경로로 빠져나갔다). 그래서 승격된 근거만
        # 센다.
        gold_ids = got.get("gold_chunk_ids") or []
        anchors = got.get("anchors") or []
        promotable_video = [cid for cid in gold_ids if is_video_chunk(cid, corpus_by_id)]
        unpromoted_docs = [
            cid for cid in gold_ids
            if cid not in promotable_video and not is_video_chunk(cid, corpus_by_id)
        ]
        if got["coverage"] == "answerable" and not anchors and not promotable_video:
            problems.append(
                f"{row['query_id']}: coverage=answerable인데 승격된 근거가 없다 — "
                "문서 청크는 인용문 앵커로, 영상 청크는 relevant_spans로 올려야 한다"
            )
        if unpromoted_docs and not anchors:
            problems.append(
                f"{row['query_id']}: 문서 청크 {len(unpromoted_docs)}개가 gold로 지정됐으나 "
                "앵커가 없다 — 청크 id는 승격 전까지 근거가 아니다"
            )
        for cid in gold_ids:
            if cid in (got.get("cause_only_chunk_ids") or []):
                problems.append(
                    f"{row['query_id']}: 같은 청크가 gold와 cause_only에 동시 지정 ({cid[:24]}…)"
                )

        for anchor in anchors:
            quote = anchor["quote"]
            if len(quote) < args.min_anchor_chars:
                problems.append(f"{row['query_id']}: 앵커가 {len(quote)}자 (<{args.min_anchor_chars})")
            for hit in check_anchor(quote):
                problems.append(f"{row['query_id']}: 앵커에 {hit} 포함 — 커밋 불가")
            if not anchor.get("doc_id"):
                problems.append(f"{row['query_id']}: 앵커 doc_id 미확정")
            elif corpus:
                issue = revalidate_anchor(quote, anchor["doc_id"], corpus)
                if issue:
                    problems.append(f"{row['query_id']} 앵커 재검증: {issue}")
                else:
                    others = anchor_collisions(quote, anchor["doc_id"], corpus)
                    if others:
                        notes.append(
                            f"{row['query_id']}/{anchor.get('anchor_id', '?')}: 인용문이 다른 문서 "
                            f"{len(others)}곳에도 있다({', '.join(others[:3])}…). I1에서는 오류가 "
                            "아니지만 정형구일 수 있으니 앵커를 다시 볼 것"
                        )
            if not anchor.get("name_checked"):
                problems.append(f"{row['query_id']}: 앵커 호칭 확인 미완료")

        row["coverage"] = got["coverage"]
        row["review_status"] = "APPROVED"
        if got.get("quality_flag"):
            row["quality_flag"] = got["quality_flag"]
        else:
            row.pop("quality_flag", None)
        if got.get("resolved_at"):
            row["resolved_at"] = got["resolved_at"]
        if got.get("cause_only_chunk_ids"):
            row["cause_only_chunks"] = got["cause_only_chunk_ids"]
        # 영상 청크는 여기서 시간축으로 승격한다. 문서 청크와 달리 사람의 인용문
        # 선택이 필요 없다 — 청크 경계가 그대로 구간이다.
        if promotable_video and corpus:
            video_id, spans, span_problems = promote_video_chunks(
                row["query_id"], promotable_video, corpus_by_id)
            problems.extend(span_problems)
            for span in spans:
                issue = revalidate_span(video_id, span, corpus)
                if issue:
                    problems.append(f"{row['query_id']} span 재검증: {issue}")
            if video_id and spans and not span_problems:
                row["video_id"] = video_id
                row["relevant_spans"] = spans
        if got.get("anchors"):
            row["anchors"] = [
                {"anchor_id": f"{row['query_id']}-a{i}", "doc_id": a["doc_id"],
                 "quote": a["quote"], "note": a.get("note")}
                for i, a in enumerate(got["anchors"], start=1)
            ]
        if got.get("differs_from_suggestion"):
            flipped.append(row["query_id"])
            row["agent_suggestion_overridden"] = True
        approved += 1

    if problems:
        print("기록하지 않았다 — 아래를 먼저 해결할 것:\n")
        for p in problems:
            print("  " + p)
        return 2

    args.gold.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    print(f"승인 {approved} / 미판정 {skipped} -> {args.gold}")

    # 불변식 A-1 — 지문이 섞이는 것 자체는 정상이다(부분 재bake). 문제는 그것이
    # 조용한 것이다. corpus_fingerprint는 "이 판정이 내려진 시점의 코퍼스"를
    # 가리키므로 다시 판정하지 않은 행의 값을 덮어쓰면 거짓이 된다. 대신 분포를
    # 찍어 사람이 보게 한다.
    prints = collections.Counter(r.get("corpus_fingerprint") or "(없음)" for r in rows)
    if len(prints) > 1:
        print(f"  지문 {len(prints)}종:")
        for value, count in prints.most_common():
            print(f"    {value[:26]}… {count}행")
    for note in notes:
        print(f"  참고: {note}")
    if flipped:
        print(f"에이전트 제안과 다른 판정 {len(flipped)}건: {', '.join(flipped)}")
    else:
        print("에이전트 제안과 다른 판정 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
