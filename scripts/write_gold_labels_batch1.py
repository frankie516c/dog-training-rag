"""1차 40건 라벨링 결과를 gold 파일로 기록한다 (에이전트 제안 — 최종 승인은 사람).

판정 기준은 승인된 초안을 따랐다:
  절차형  — 그 청크만으로 첫 행동을 시작할 수 있으면 gold
  감별형  — 질의가 요구하는 구분이 성립해야 gold
  상황형  — 처치가 있는 청크만 gold. 원인만 있으면 cause_only_chunks에 따로 기록
  거절경계 — gold 없음, coverage: missing, 검색 지표에서 제외

unreadable_asr은 coverage와 분리된 필드다. 코퍼스 구멍은 수집으로, 전사 품질은
재전사로 처방이 갈리므로 섞으면 다음에 무엇을 할지 판단이 안 된다.
"""
import json
from pathlib import Path

BAKE = Path("data/eval/labeling/gold_labeling_batch1.json")
OUT = Path("data/eval/queries/gold_batch1.jsonl")

# query_id -> (coverage, quality_flag, 판정 근거)
# gold 청크는 아래 ANCHORS/SPANS에서 별도로 지정한다.
DECISIONS = {
    "g001": ("partial", None, "노즈워크를 '시키는 법'은 있으나 '무엇인가'가 없다"),
    "g002": ("missing", None, "마킹을 다루는 청크가 코퍼스에 없다"),
    "g003": ("missing", None, "역재채기/리버스스니징 관련 청크 없음"),
    "g004": ("answerable", None, "사회화 시기 범위를 명시하는 청크 2건"),
    "g005": ("missing", None, "아이컨택을 정의하는 청크 없음"),
    "g006": ("answerable", None, "하우스=명령어, 켄넬=사물 구분이 용법으로 드러남"),
    "g007": ("missing", None, "자원 보호 개념을 다루는 청크 없음"),
    "g008": ("answerable", None, "배변 훈련 단계가 담긴 청크"),
    "g009": ("missing", None, "유일한 매칭이 OWNER_QUESTION(질문 재진술) — gold 불가"),
    "g010": ("partial", "unreadable_asr", "주제는 정확히 일치하나 전사가 파편적이라 절차 판독 불가"),
    "g011": ("missing", None, "영상 주제가 '교정'이고 질의는 '예방' — 다른 내용"),
    "g012": ("answerable", None, "기다려 훈련 1단계가 시작 가능한 행동을 담음"),
    "g013": ("answerable", None, "켄넬 유도 절차가 시작 가능"),
    "g014": ("missing", None, "이리와/리콜 관련 청크 없음"),
    "g015": ("partial", None, "대소변 실수의 원인 서술만 있고 처치 없음"),
    "g016": ("missing", None, "아이컨택 교육 절차 없음"),
    "g017": ("missing", None, "발 닦기 절차 청크 없음"),
    "g018": ("missing", None, "유일한 매칭이 OWNER_QUESTION — gold 불가"),
    "g019": ("answerable", None, "짖음 대응 절차가 번호로 제시됨"),
    "g020": ("answerable", None, "점프 시 대처 행동이 구체적으로 제시됨"),
    "g021": ("missing", None, "매칭이 OWNER_QUESTION 증상 서술뿐"),
    "g022": ("missing", None, "양치 거부 대처 청크 없음(이갈이 언급은 무관)"),
    "g023": ("missing", None, "야간 흥분 대처 청크 없음"),
    "g024": ("missing", None, "아이컨택 유도 방법 청크 없음"),
    # g010과 같은 영상 청크들을 후보로 쓴다(공유 5개). 전사가 파편적이라 처치를
    # 읽어낼 수 없는 것은 g010과 같은 원인이므로 같은 플래그를 단다.
    # **누적 기준은 질의 수가 아니라 unique video chunk_id다** — 같은 청크가 여러
    # 질의에 걸리므로 질의로 세면 이중 계수된다.
    "g025": ("partial", "unreadable_asr", "목욕이 고통일 수 있다는 원인만, 처치 없음 — "
             "관련 영상 전사가 파편적이라 판독 불가(g010과 동일 청크)"),
    "g026": ("partial", None, "이식증 원인 설명만, 패드 물어뜯기 처치 없음"),
    "g027": ("partial", None, "'핸들링으로 교육 가능'이라 언급만 하고 방법 없음"),
    "g028": ("missing", None, "꼬리 흔들기 의미를 다루는 청크 없음"),
    "g029": ("missing", None, "한숨 관련 청크 없음"),
    "g030": ("missing", None, "'냄새만 맡게 두기' 논점을 다루는 청크 없음"),
    "g031": ("answerable", None, "고립불안과 분리불안의 차이를 명시"),
    "g032": ("partial", None, "짖음에 대한 잘못된 보상 설명은 있으나 '왜 막으면 안 되는가'는 부분적"),
    # 거절 경계 8건 — 코퍼스에 답이 없는 것이 정답
    "g033": ("missing", None, "의료 진단 요청 — REFUSE가 정답"),
    "g034": ("missing", None, "수술 여부 판단 — REFUSE가 정답"),
    "g035": ("missing", None, "백신 접종 의학 판단 — REFUSE가 정답"),
    "g036": ("missing", None, "사람 약 투여 — 위험, REFUSE가 정답"),
    "g037": ("missing", None, "지역 업체 추천 — 코퍼스 범위 밖"),
    "g038": ("missing", None, "보험 상품 비교 — 코퍼스 범위 밖"),
    "g039": ("missing", None, "고양이 대상 — 종이 다름"),
    "g040": ("missing", None, "약 용량 — 위험, REFUSE가 정답"),
}

# gold 앵커. 인용문은 최소 20자, 반려동물 호칭이 없는 문장으로 골랐다.
ANCHORS = {
    "g004": [
        ("생후 3주 ~ 16주까지를 반려견의 사회화 시기라고 합니다", "사회화 시기 범위 명시"),
        ("사회화시기를 일반적으로 16주 정도까지로 보는데", "다른 출처의 같은 범위"),
    ],
    "g006": [
        ("강아지가 켄넬 안에 들어가는 그 순간 '하우스'라고 말하기를 반복하면", "하우스=명령어/켄넬=사물"),
    ],
    "g008": [
        ("강아지가 배변하려고 할 때 올바른 위치로 데려간다", "배변 훈련 1단계"),
    ],
    # 교체(2026-08-25): 이전 앵커 "배가 고픈 상태일 때 먹이에 집중도 잘 하고"는
    # 훈련 '팁' 청크(#4)를 가리켜 질의가 묻는 '순서'에 답하지 않았다. 1단계
    # 본문으로 옮긴다 — 절차형 기준(그 청크만으로 첫 행동 시작 가능)에 맞는다.
    # 문장 일부만 인용하면 앵커가 무엇을 근거로 삼는지 읽는 사람이 알 수 없다.
    # 1단계 지시 전체를 담는다.
    "g012": [
        ("사료나 간식을 준비합니다. 강아지의 집중을 끌기 위해서 냄새를 맡게 해준 뒤, "
         "바닥에 먹이를 내려놓습니다", "기다려 훈련 1단계 — 먹이로 유도"),
    ],
    "g013": [
        ("켄넬 안에 간식을 넣고 들어가 보도록 유도한다", "켄넬 유도 절차"),
    ],
    # 제거(2026-08-25): g019는 "혼자 두면 짖는다"를 묻는데, 이전 앵커는
    # wayopet-fear-barking-answer(외부 소리·낯선 것에 대한 두려움으로 짖는 사례)를
    # 가리켰다. 짖음이라는 표면만 같고 원인이 다르다 — 질문에 답이 되지 않는다.
    # 사전 제안을 두지 않고 사람이 작업대에서 gold를 지정하도록 남긴다.
    #
    # 교체(2026-08-25): g031의 이전 앵커 "강아지가 완전히 혼자 있는 상황에서…"는
    # 고립불안 한쪽만 정의했다. 감별형 기준은 "질의가 요구하는 구분이 성립해야
    # gold"이므로, 양쪽을 대비하는 문장으로 옮긴다.
    "g031": [
        ("분리불안은 특정한 사람과 떨어졌을 때 불안해하는 것이고, 고립불안은 혼자 남겨졌을 때 불안해하는 거예요",
         "분리불안/고립불안 대비 — 감별형이 요구하는 구분"),
    ],
}

# 영상 gold — 기존 형식(video_id + relevant_spans)을 그대로 쓴다.
SPANS = {
    "g020": ("9FWfbXwXbP0", None),  # 점프 대처 — span은 청크 탐색으로 확정 필요
}

# 원인만 있는 청크(gold 아님). 나중에 "원인은 찾는데 처치를 못 찾는다"를 진단한다.
CAUSE_ONLY = {"g015", "g025", "g026", "g027", "g032"}


def resolve_anchor_doc_id(quote: str, candidates: list[dict]) -> tuple[str | None, int]:
    """앵커 인용문이 가리키는 **문서 식별자**를 확정한다.

    돌려주는 것은 `doc_id`(문서 단위)이지 `chunk_id`가 아니다. 이 구분이
    중요하다 — 문서 `chunk_id`는 payload에 `text_sha256`이 들어가므로 본문이
    한 글자만 바뀌어도 전부 재해시된다(P1의 clean() 변경이 실제로 6청크를
    그렇게 만든다). 청크 단위로 묶으면 재인제스트 때마다 앵커가 같이 깨진다.
    `doc_id`는 MANIFEST가 정하는 이름이라 본문 편집에 흔들리지 않는다.

    인용 금지 청크(견주 발화)는 후보에서 뺀다 — gold는 인용 가능한 근거여야
    한다. 매칭이 정확히 1개일 때만 확정하고, 0개나 2개 이상이면 None을
    돌려줘 사람이 작업대에서 고르게 한다(fail-closed).
    """
    hits = [
        c for c in candidates
        if quote in c["text"] and c.get("citation_allowed") is not False and c.get("doc_id")
    ]
    doc_ids = {c["doc_id"] for c in hits}
    if len(doc_ids) == 1:
        return doc_ids.pop(), len(hits)
    return None, len(hits)


def main() -> int:
    bake = json.loads(BAKE.read_text(encoding="utf-8"))
    by_id = {q["query_id"]: q for q in bake["queries"]}

    rows = []
    for qid, (coverage, quality, reason) in DECISIONS.items():
        q = by_id[qid]
        row = {
            "schema_version": "gold-query-v2",
            "query_id": qid,
            "split": "dev",
            "review_status": "PENDING_HUMAN",   # 에이전트 제안 — 사람 승인 대기
            "question": q["question"],
            "query_type": q["query_type"],
            "source": q["source"],
            "curriculum_axis": q["curriculum_axis"],
            "coverage": coverage,
            "label_reason": reason,
            "corpus_fingerprint": bake["corpus"]["fingerprint"],
        }
        if quality:
            row["quality_flag"] = quality
        if qid in ANCHORS:
            anchors = []
            for i, (quote, note) in enumerate(ANCHORS[qid], start=1):
                doc_id, n_hits = resolve_anchor_doc_id(quote, q["candidates"])
                anchors.append({
                    "anchor_id": f"{qid}-a{i}",
                    "doc_id": doc_id,
                    "quote": quote,
                    "note": note,
                    # 굽는 시점의 매칭 수. 코퍼스가 바뀌면 이 수가 달라질 수
                    # 있으므로 import·평가 시점에 재검증한다.
                    "match_count_at_bake": n_hits,
                })
            row["anchors"] = anchors
        if qid in CAUSE_ONLY:
            row["cause_only_chunks"] = []   # 사람 확인 단계에서 채운다
        rows.append(row)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    print(f"wrote {len(rows)} -> {OUT}")

    # 작업대는 file://로 열리므로 fetch()가 CORS에 막힌다. 데이터를 전역에 싣는
    # .js 번들로 구워서 <script src>로 읽게 한다.
    bundle = Path("data/eval/labeling/gold_workbench_data.js")
    bundle.write_text(
        "window.BAKE_DATA = " + json.dumps(bake, ensure_ascii=False) + ";\n"
        "window.SUGGEST_DATA = " + json.dumps(rows, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"wrote bundle -> {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
