"""gold 라벨링 작업대용 정적 데이터를 굽는다.

브라우저에서 임베딩을 돌릴 수 없으므로, 후보 질의별 검색 결과를 미리 계산해
JSON 하나로 만든다. 작업대는 그것을 읽기만 하며 오프라인으로 열린다.

## 2단 그물

라벨링 후보 풀과 검색 설정(TOP_K=5)은 분리한다. top-5만 보고 판단하면
**"코퍼스에 답이 없다"와 "답은 있는데 검색이 못 찾았다"가 뒤섞인다.** 후자는
Hit@1·Recall@5가 측정해야 할 바로 그 대상인데, `missing`으로 라벨링해 버리면
검색을 개선해도 영원히 감지되지 않는다.

  1단 — 벡터 top-20
  2단 — 어휘 검색(질의 핵심어 매칭). 벡터가 놓친 것을 잡는다
  그래도 없으면 → coverage: missing

어느 단계에서 찾았는지를 `resolved_at`으로 남기면, 나중에 검색을 고쳤을 때
개선이 지표로 드러난다.

굽는 시점의 코퍼스 스냅샷 해시를 함께 기록한다 — 코퍼스가 바뀌면 이 작업대
결과가 어느 시점 것인지 알 수 있어야 한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows 콘솔이 cp949라 한글·em dash 출력에서 UnicodeEncodeError가 난다.
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import run_combined_retrieval_eval as ev  # noqa: E402

CANDIDATES = Path("data/eval/queries/gold_candidates_batch1.jsonl")
OUT = Path("data/eval/labeling/gold_labeling_batch1.json")

VECTOR_POOL = 20          # 라벨링 후보 풀. 검색 설정 TOP_K=5와 분리한다.
LEXICAL_LIMIT = 10        # 2단 그물이 추가로 보여줄 최대 건수
MIN_KEYWORD_CHARS = 2

# 조사·일반어는 어휘 검색 핵심어에서 뺀다. 이걸 남기면 거의 모든 청크가 걸린다.
STOPWORDS = {
    "강아지", "반려견", "우리", "저희", "제가", "너무", "자꾸", "계속", "어떻게",
    "어떡하죠", "하나요", "인가요", "건가요", "뭔가요", "때문", "경우", "정도",
    "생각", "이라는", "라는", "에서", "에게", "으로", "하는", "해야", "합니다",
    "있어요", "없어요", "해요", "돼요", "같아요", "싶은데", "모르겠어요",
}


def keywords(question: str) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", question)
    out = []
    for token in tokens:
        if len(token) < MIN_KEYWORD_CHARS or token in STOPWORDS:
            continue
        # 조사가 붙은 형태를 어간 쪽으로 살짝 줄인다(형태소 분석기 없이).
        stem = re.sub(r"(을|를|이|가|은|는|에|의|로|와|과|도|만|께|부터|까지)$", "", token)
        if len(stem) >= MIN_KEYWORD_CHARS:
            out.append(stem)
    return list(dict.fromkeys(out))


def split_sentences(text: str) -> list[str]:
    """앵커 후보용 문장 분할. 완벽할 필요는 없다 — 사람이 고른다."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) >= ev.MIN_ANCHOR_CHARS]


# 호칭 위험 표시는 **문자열 패턴이 아니라 출처**로 한다.
#
# 정규식 힌트를 두 번 시도했다가 폐기했다. 실측에서 "우리 X(조사)"는 0건,
# "X 보호자님"은 42건이 전부 일반어("이라면"·"주세요"·"은데요")였고 실제 호칭은
# 하나도 잡지 못했다. 이 코퍼스의 반려동물 호칭은 문장 중간에 평범한 명사로
# 박혀 있어("…의 상황에 대입", "…에게") 구문 표지가 없기 때문이다. 거짓 경고
# 수백 개에 진짜가 0개인 표시는 라벨러가 경고를 무시하도록 훈련시킬 뿐이다.
#
# 대신 아는 사실만 표시한다: 상담 원문에서 온 문서(qa_segment)는 답변 본문에
# 호칭이 남아 있는 것이 실측으로 확인됐다. 그 문서의 문장은 "확인 필요"로
# 표시하고, 판단은 사람이 문장을 읽고 한다. 이것은 호칭 목록이 아니라 출처
# 사실이므로, 앞으로 들어올 새 호칭에도 그대로 성립한다.
NAME_RISK_KNOWN = "known"      # 호칭이 본문에 남아 있는 것이 확인된 출처
NAME_RISK_UNVERIFIED = "unverified"  # 확인된 바 없음 — 없다는 뜻이 아니다


def name_risk(chunk: dict[str, Any]) -> str:
    if chunk.get("segment_role") in ("OWNER_QUESTION", "EXPERT_ANSWER"):
        return NAME_RISK_KNOWN
    return NAME_RISK_UNVERIFIED


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", type=Path, default=CANDIDATES)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--video-dir", type=Path, default=ev.DEFAULT_VIDEO_CHUNKS)
    ap.add_argument("--doc-dir", type=Path, default=ev.DEFAULT_DOC_CHUNKS)
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.candidates.read_text(encoding="utf-8").splitlines() if l.strip()]

    video_all = ev.load_video_chunks(args.video_dir)
    video = [c for c in video_all if c.get("embedding_eligible")]
    documents = ev.load_document_chunks(args.doc_dir)
    corpus = video + documents
    ids = [c["chunk_id"] for c in corpus]
    by_id = {c["chunk_id"]: c for c in corpus}

    encoder = ev.load_encoder("cpu")
    matrix = encoder.encode([ev.PASSAGE_PREFIX + c["text"] for c in corpus])

    def as_candidate(chunk_id: str, score: float | None, how: str) -> dict[str, Any]:
        chunk = by_id[chunk_id]
        return {
            "chunk_id": chunk_id,
            "score": ev.serialize_score(score) if score is not None else None,
            "found_by": how,
            "source_kind": chunk["source_kind"],
            "where": ev.describe(chunk),
            "doc_id": chunk.get("doc_id"),
            "video_id": chunk.get("video_id"),
            "segment_role": chunk.get("segment_role"),
            "citation_allowed": chunk.get("citation_allowed", True),
            "text": chunk["text"],
            # 호칭 위험은 청크 단위 사실이다 — 문장별로 다르지 않다.
            "name_risk": name_risk(chunk),
            "sentences": [{"text": s} for s in split_sentences(chunk["text"])],
        }

    queries = []
    for row in rows:
        question = str(row["question"])
        vector = encoder.encode([ev.QUERY_PREFIX + question])[0]
        scores = ev.similarity(vector, matrix)
        ranked = ev.rank_scores(scores, ids, VECTOR_POOL)
        picked = {cid for cid, _ in ranked}

        candidates = [as_candidate(cid, s, "vector") for cid, s in ranked]

        # 2단 그물 — 벡터가 놓친 것을 어휘로 잡는다.
        kws = keywords(question)
        lexical: list[tuple[int, str]] = []
        for chunk in corpus:
            if chunk["chunk_id"] in picked:
                continue
            hits = sum(1 for k in kws if k in chunk["text"])
            if hits:
                lexical.append((hits, chunk["chunk_id"]))
        lexical.sort(key=lambda p: (-p[0], p[1]))
        for _hits, cid in lexical[:LEXICAL_LIMIT]:
            candidates.append(as_candidate(cid, None, "lexical"))

        queries.append({
            **{k: row[k] for k in ("query_id", "question", "query_type", "source", "curriculum_axis")},
            "keywords": kws,
            "vector_pool_size": len(ranked),
            "lexical_extra": min(len(lexical), LEXICAL_LIMIT),
            "lexical_total": len(lexical),
            "candidates": candidates,
        })

    fingerprint = ev.fingerprint(corpus)
    payload = {
        "schema_version": "gold-labeling-bake-v1",
        "generated_by": "scripts/bake_gold_labeling.py",
        "corpus": {
            "fingerprint": fingerprint,
            "chunks": len(corpus),
            "video_chunks": len(video),
            "document_chunks": len(documents),
        },
        "config": {
            "vector_pool": VECTOR_POOL,
            "lexical_limit": LEXICAL_LIMIT,
            "retrieval_top_k": ev.TOP_K,
            "min_anchor_chars": ev.MIN_ANCHOR_CHARS,
        },
        "queries": queries,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    total_c = sum(len(q["candidates"]) for q in queries)
    risky = sum(
        1 for q in queries for c in q["candidates"] if c["name_risk"] == NAME_RISK_KNOWN
    )
    print(f"queries={len(queries)} candidates={total_c} corpus={len(corpus)}")
    print(f"fingerprint={fingerprint[:23]}...")
    print(f"호칭 확인 필요 후보 {risky}개 (상담 원문 출처 — 앵커 승인 시 문장을 읽을 것)")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
