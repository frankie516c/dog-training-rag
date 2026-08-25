"""wayopet.com Q&A를 견주 질문부와 훈련사 답변부로 분리한다 (fail-closed).

## 왜 분리하는가

wayopet Q&A 한 문서에는 견주 질문과 훈련사 답변이 함께 들어 있고, 실측 결과
문서의 약 3분의 1이 견주 발화다. 이대로 청킹하면 견주가 "시도했다가 효과가
없었다"고 직접 밝힌 방법이 전문가 권고처럼 검색·인용될 수 있다. 같은 이유로
다화자 영상 콘텐츠를 D등급으로 뺐고, 여기도 같은 기준을 적용한다.

## 이 스크립트의 범위

분리와 intermediate/audit 산출물 생성까지만 한다. **청크 생성·임베딩·인덱스
재빌드는 하지 않는다** — 청킹 v4 파라미터가 확정되면 코퍼스가 어차피 전부
재해시되므로, 그 전에 청크를 만들면 두 번 일하게 된다. 따라서 이 스크립트는
코퍼스를 변경하지 않으며 평가 스냅샷도 건드리지 않는다.

권위 계약(authority/citation_allowed 필드, qa_id 확장 검색, 인용 렌더링 분기)은
별도 라운드로 분리했다. 근거는 docs/design_qa_authority_retrieval.md 참조.

## fail-closed 원칙

경계(R1)가 정확히 1개일 때만 자동 처리한다. 0개나 2개 이상이면 PARSE_REVIEW로
표시하고 자동 통과시키지 않는다. R1은 지금까지 확보한 6건에 대해서만 검증된
규칙이며, 마스킹 형식이 다른 게시글(2자·4자 이름, 다른 마스킹 패턴)에는 매칭이
실패한다. 그 경우 PARSE_REVIEW에 빠지는 것이 **의도된 동작**이다 — 조용히
잘못 자르는 것보다 사람이 보는 편이 낫다.

raw 파일은 절대 수정하지 않는다. 모든 처리는 산출물 쪽에서만 한다.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

RAW_DIR = Path("data/raw/documents_candidate_0825_wayopet")
OUT_DIR = Path("data/intermediate/wayopet")

# 표시명은 플랫폼+역할로 고정한다. 개별 식별자(마스킹명 포함)를 표시 경로에
# 넣지 않는다 — 본문에서 실명을 지우면서 메타데이터에 남기면 제거가 무의미해지고,
# 헤더는 마스킹인데 본문은 실명인 사례가 실제로 확인됐다. 마스킹명이 필요하면
# *_masked_internal 필드로만 다루고 표시용 경로에는 노출하지 않는다.
QUESTION_AUTHOR_DISPLAY = "와요펫 견주"
ANSWER_AUTHOR_DISPLAY = "와요펫 훈련사"

QUESTION_STATUS = "excluded_pending_authority_pipeline"

# --- 경계 규칙 ---
# R1(주 규칙, 경계 계수용): 마스킹 성명 + 역할어. 역할어가 붙어 있어서
# 질문자와 훈련사를 구분할 수 있다 — 둘 다 같은 마스킹 형식이라 성명만으로는
# 구분되지 않으므로, '작성자 전환'을 독립 규칙으로 쓰지 않는다.
R1_BOUNDARY = re.compile(r"([가-힣]\*[가-힣])\s*훈련사님의\s*답변")
# R2(교차검증): R1 바로 앞에 오는 귀속 리드인. 개수가 R1과 다르면 구조 이상.
R2_LEADIN = re.compile(r"와요에서\s*활동\s*중인")
# R4(질문부 구조 확인): 견주 입력 폼의 섹션 헤더. 경계 앞에만 있어야 한다.
R4_QUESTION_HEADERS = [
    re.compile(rf"^\s*{k}\s*$", re.M) for k in ("증상과 행동", "시작된 시점", "보호자님 반응")
]
# 질문 작성자 마스킹명: 질문 제목 다음 줄에 온다.
R_QUESTION_AUTHOR = re.compile(r"^([가-힣]\*[가-힣])\s*$", re.M)

# R3(참고용, 검증 조건 아님): 답변측 섹션 헤더. 문서마다 표현이 달라
# (일부는 '원인 분석' 대신 서술형 헤더를 쓴다) 필수 조건으로 쓰면 정상 문서가
# PARSE_REVIEW로 잘못 빠진다. 통계로만 남긴다.
R3_ANSWER_HEADERS = [
    re.compile(r"^\s*원인\s*분석\s*$", re.M),
    re.compile(r"^\s*솔루션\s*제안\s*$", re.M),
]

# --- 제거 대상 boilerplate (경계 아님) ---
# R5a(필수): 답변 본문의 자기소개. 여기서 훈련사 실명이 노출된다 — 헤더는
# 마스킹인데 본문은 실명인 사례가 확인됐다. 이름을 리터럴로 적지 않고
# 패턴으로만 잡는다.
R5A_SELF_INTRO = re.compile(
    r"안녕하세요[.,]?\s*[^\n]{0,30}?[가-힣]{2,4}\s*훈련사입니다[.!?]?\s*[\U0001F300-\U0001FAFF☀-➿]*"
)
# R5b(노이즈 제거): 도입부 인사말. PII 처리가 아니라 검색 노이즈 제거다 —
# 인사말만 지워도 본문에 남는 개별 사례 호칭이 훨씬 많으므로, 이것을 PII
# 대책이라고 부르면 처리된 것처럼 보이지만 실제로는 반쪽이다. 본문 치환은
# 이 라운드에서 하지 않는다.
# 뒤쪽은 문장부호·이모티콘까지만 먹는다. 넉넉히 허용하면 실제 답변 내용을
# 인사말로 오인해 잘라낸다(실측으로 확인된 오류).
R5B_GREETING = re.compile(
    r"안녕하세요[.,]?\s*[^\n]{0,20}?보호자님\s*(?:[!.,~]|:-\)|[\U0001F300-\U0001FAFF☀-➿]|\s)*"
)


class ParseIssue(Exception):
    """자동 처리 불가 — PARSE_REVIEW로 보낸다."""


def read_frontmatter(raw: str) -> tuple[dict[str, str], int]:
    """--- 로 감싼 frontmatter를 얕게 파싱하고 본문 시작 오프셋을 함께 준다.

    오프셋을 돌려주는 이유: span은 raw 파일 전체 기준이어야 나중에 raw를 다시
    파싱하지 않고도 무엇이 잘렸는지 확인·복원할 수 있다.
    """
    if not raw.startswith("---"):
        return {}, 0
    end = raw.find("\n---", 3)
    if end == -1:
        return {}, 0
    block = raw[3:end]
    body_start = raw.find("\n", end + 1) + 1
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, body_start


def strip_boilerplate(text: str, base_offset: int) -> tuple[str, list[dict[str, Any]]]:
    """R5a/R5b를 제거하고, 무엇을 지웠는지 raw 기준 오프셋과 원문으로 남긴다.

    원문을 남기는 것은 검증·복원을 위해서다. 다만 원문에는 실명이 들어가므로
    이 산출물은 커밋하지 않는다(data/ 는 gitignore).

    **겹치는 span은 반드시 병합한 뒤에 잘라낸다.** R5a("안녕하세요 ... OOO
    훈련사입니다")와 R5b("안녕하세요 ... 보호자님")는 같은 문장에서 같은 위치를
    잡을 수 있다 — 실제로 그런 문서가 있었다. 병합 없이 각각 잘라내면 두 번째
    삭제가 이미 짧아진 문자열에 적용돼 **실제 답변 내용을 지운다**(실측으로
    확인된 손상). 조용히 깨지는 종류라 여기서 막는다.
    """
    matches: list[tuple[int, int, str]] = []
    for label, pattern in (("self_intro", R5A_SELF_INTRO), ("greeting", R5B_GREETING)):
        for m in pattern.finditer(text):
            matches.append((m.start(), m.end(), label))
    if not matches:
        return text, []

    matches.sort()
    merged: list[tuple[int, int, list[str]]] = []
    for start, end, label in matches:
        if merged and start <= merged[-1][1]:  # 겹치거나 맞닿음
            prev_start, prev_end, kinds = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end), kinds + [label])
        else:
            merged.append((start, end, [label]))

    removed = [
        {
            "kind": "+".join(dict.fromkeys(kinds)),
            "raw_start": base_offset + s,
            "raw_end": base_offset + e,
            "text": text[s:e],
        }
        for s, e, kinds in merged
    ]

    out = text
    for s, e, _ in reversed(merged):  # 뒤에서부터 잘라야 앞쪽 오프셋이 밀리지 않는다
        out = out[:s] + out[e:]
    return re.sub(r"\n{3,}", "\n\n", out).strip(), removed


def parse_document(path: Path, ordinal: int) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    meta, body_start = read_frontmatter(raw)
    body = raw[body_start:]
    source_url = meta.get("source_url", "")

    boundaries = list(R1_BOUNDARY.finditer(body))
    leadins = len(R2_LEADIN.findall(body))
    answer_headers = sum(len(p.findall(body)) for p in R3_ANSWER_HEADERS)

    record: dict[str, Any] = {
        "doc_slug": path.stem,
        "source_url": source_url,
        # qa_id는 위치 기반이다. 텍스트 해시로 만들면 동일 텍스트가 여러 Q&A에
        # 등장할 때 충돌하고, 그 충돌은 에러 없이 조용히 깨진다.
        "qa_id": f"{source_url}#qa{ordinal}" if source_url else f"{path.stem}#qa{ordinal}",
        "boundary_count": len(boundaries),
        "leadin_count": leadins,
        "answer_header_count": answer_headers,  # R3: 참고용 통계, 판정 조건 아님
    }

    if len(boundaries) != 1:
        record["parse_status"] = "PARSE_REVIEW"
        record["review_reason"] = (
            f"경계(R1)가 {len(boundaries)}개 — 정확히 1개일 때만 자동 처리한다"
        )
        return record

    m = boundaries[0]
    q_body = body[: m.start()]
    a_body = body[m.end():]

    q_start, q_end = body_start, body_start + m.start()
    a_start, a_end = body_start + m.end(), body_start + len(body)

    # 질문부 구조가 경계 뒤로 새지 않았는지 확인한다.
    leaked = sum(len(p.findall(a_body)) for p in R4_QUESTION_HEADERS)
    if leaked:
        record["parse_status"] = "PARSE_REVIEW"
        record["review_reason"] = f"질문부 섹션 헤더가 경계 뒤에 {leaked}개 — 경계 위치 의심"
        return record

    answer_text, removed = strip_boilerplate(a_body, a_start)
    question_text = q_body.strip()

    # 공백 검사 — 한쪽이 비면 경계를 잘못 잡은 것이다.
    if not question_text or not answer_text:
        record["parse_status"] = "PARSE_REVIEW"
        record["review_reason"] = "분리 결과 질문부 또는 답변부가 비었다"
        return record

    # 마커 잔존 검사 — 경계 표지가 어느 쪽에도 남아 있으면 안 된다.
    if R1_BOUNDARY.search(question_text) or R1_BOUNDARY.search(answer_text):
        record["parse_status"] = "PARSE_REVIEW"
        record["review_reason"] = "분리 후에도 경계 마커가 본문에 남아 있다"
        return record

    q_authors = R_QUESTION_AUTHOR.findall(q_body)

    record.update({
        "parse_status": "OK",
        "question_text": question_text,
        "answer_text": answer_text,
        "question_span_offset": [q_start, q_end],
        "answer_span_offset": [a_start, a_end],
        "removed_boilerplate_spans": removed,
        "question_author_display": QUESTION_AUTHOR_DISPLAY,
        "answer_author_display": ANSWER_AUTHOR_DISPLAY,
        # 표시 경로에 절대 쓰지 않는다. intermediate 전용.
        "question_author_masked_internal": q_authors[0] if q_authors else None,
        "answer_author_masked_internal": m.group(1),
        "question_status": QUESTION_STATUS,
    })
    return record


def to_segments(record: dict[str, Any]) -> list[dict[str, Any]]:
    """권위 계약이 붙을 자리를 미리 나눠 둔 세그먼트 레코드.

    authority/citation_allowed/retrieval_allowed 필드는 **여기서 부여하지 않는다.**
    현재 코어(rank_scores/build_prompt/evidence_chunk_ids)가 그 필드를 소비하지
    않으므로, 지금 붙이면 계약이 구현된 것처럼 보이지만 실제로는 작동하지 않는
    반쪽 상태가 된다. 소비하는 코드와 같은 라운드에서 함께 넣는다.
    """
    if record["parse_status"] != "OK":
        return []
    common = {
        "qa_id": record["qa_id"],
        "source_url": record["source_url"],
        "doc_slug": record["doc_slug"],
    }
    return [
        {
            **common,
            "segment_role": "OWNER_QUESTION",
            "text": record["question_text"],
            "span_offset": record["question_span_offset"],
            "author_display": record["question_author_display"],
            "status": record["question_status"],
        },
        {
            **common,
            "segment_role": "EXPERT_ANSWER",
            "text": record["answer_text"],
            "span_offset": record["answer_span_offset"],
            "author_display": record["answer_author_display"],
            "removed_boilerplate_spans": record["removed_boilerplate_spans"],
        },
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    paths = sorted(args.raw_dir.glob("*.md"))
    if not paths:
        print(f"no source under {args.raw_dir}")
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    records = [parse_document(p, ordinal=0) for p in paths]

    segments: list[dict[str, Any]] = []
    for r in records:
        segments.extend(to_segments(r))

    seg_path = args.out_dir / "segments.jsonl"
    with seg_path.open("w", encoding="utf-8") as f:
        for s in segments:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    audit = {
        "generated_by": "scripts/split_wayopet_qa.py",
        "raw_dir": str(args.raw_dir),
        "note": "코퍼스 미변경 — 청크 생성·임베딩·인덱스 재빌드 없음",
        "documents": [
            {k: v for k, v in r.items() if k not in ("question_text", "answer_text")}
            for r in records
        ],
    }
    audit_path = args.out_dir / "audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for r in records if r["parse_status"] == "OK")
    review = len(records) - ok
    print(f"documents={len(records)} OK={ok} PARSE_REVIEW={review}")
    print(f"segments={len(segments)} -> {seg_path}")
    print(f"audit -> {audit_path}")
    for r in records:
        if r["parse_status"] != "OK":
            print(f"  PARSE_REVIEW {r['doc_slug']}: {r['review_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
