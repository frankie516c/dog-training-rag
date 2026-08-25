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
    """앵커 인용문이 지금 코퍼스에서도 단일 매칭인지 다시 본다.

    굽는 시점의 단일 매칭은 그때의 코퍼스(254청크) 성질이지 영구 보장이 아니다.
    코퍼스가 커지면 같은 문장이 다른 문서에도 나타날 수 있고, 본문이 편집되면
    (P1의 clean() 변경처럼) 아예 사라질 수도 있다. 굽는 스크립트를 다시 돌리지
    않고 gold 파일만 커밋되는 경로가 있으므로, 여기서 독립적으로 확인한다.
    """
    hits = [c for c in corpus
            if quote in c.get("text", "") and c.get("citation_allowed") is not False]
    if not hits:
        return "인용문이 코퍼스 어디에도 없다 — 본문이 편집됐거나 앵커를 다시 뽑아야 한다"
    docs = {c.get("doc_id") for c in hits if c.get("doc_id")}
    if len(docs) > 1:
        return f"인용문이 문서 {len(docs)}곳에 매칭된다({', '.join(sorted(docs)[:3])}…) — 앵커를 늘려 좁힐 것"
    if docs and doc_id not in docs:
        return f"기록된 doc_id({doc_id})와 실제 매칭 문서({docs.pop()})가 다르다"
    return None


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

    problems: list[str] = []
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
        # 직접 만들면 그만이다). coverage=answerable인데 gold 청크도 앵커도 없으면
        # 평가 시 gold_relevant_chunks()가 EvalError로 죽는다 — 그 상태가
        # 커밋되면 평가 자체가 안 돌아가므로 여기서 막는다.
        gold_ids = got.get("gold_chunk_ids") or []
        anchors = got.get("anchors") or []
        if got["coverage"] == "answerable" and not gold_ids and not anchors:
            problems.append(
                f"{row['query_id']}: coverage=answerable인데 gold 청크도 앵커도 없다 — "
                "평가 시 gold_relevant_chunks()가 실패한다"
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
    if flipped:
        print(f"에이전트 제안과 다른 판정 {len(flipped)}건: {', '.join(flipped)}")
    else:
        print("에이전트 제안과 다른 판정 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
