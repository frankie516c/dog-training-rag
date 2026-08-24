#!/usr/bin/env python3
"""
절차/순서(STEP·GATE) 신호 표본 추출기 (절차 축 1차 실측용)

`sample_env_sentences.py`를 복사해 사전과 측정 항목만 절차 축으로 갈아끼운 것이다.
원본 둘(sample_breed_sentences.py, sample_env_sentences.py)은 재현성 보존을 위해
수정하지 않았다.

배경: `docs/schema_procedure_v1.md`는 살구뉴스 켄넬 STEP 글(`salgoonews-kennel-steps-12333`)
문서 1건의 STEP1~6 구조를 근거로 HAS_STEP/NEXT/GATE 스키마를 설계했지만,
"다른 문서에도 같은 구조가 얼마나 있는가"는 측정하지 않은 채 정지했다
(schema_procedure_v1.md 한계 2번). 이 스크립트는 그 공백을 메운다.

이번 측정의 핵심 질문은 명명이 아니라 **"그래프가 리스트보다 나은가"**다 — 절차가
문서 하나 안에서만 완결되면 Method 노드의 정렬 리스트 프로퍼티로 충분하고, 같은
절차/스텝이 서로 다른 문서(=서로 다른 저자·채널)에 걸쳐 재등장해야 그래프 엣지
(NEXT로 여러 Method를 넘나드는 탐색)가 정당화된다. 이 스크립트는 이를 근사치로만
잰다 — 실제 절차명 동일성을 보장하지 않으며, 사람 확인이 필요한 후보 목록일 뿐이다.

★ 원본(sample_env_sentences.py)과 다른 점
  1. ENV_TERMS -> STEP_MARKERS(순번 표지) / GATE_MARKERS(조건분기 표지)
  2. 문서 단위 STEP 구조 판정 추가 (같은 문서에 서로 다른 순번 표지가 2개 이상)
  3. 크로스 문서 재사용 근사 측정 추가 (표지 직후 원문 스니펫의 문서 간 재등장)
  4. GATE 표지가 STEP 문맥 안에 있는지 vs 무관 문맥인지 분리 집계
  5. 라벨용 표본 CSV의 술어/조건성 열은 절차 축에 맞춰 이름만 바꿈(순서서술/게이트여부)

사용
  python sample_procedure_sentences.py --root <크롤폴더> --out data/procedure_agegroup_factcheck --per-topic 5
"""

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.platform == "win32":                       # cp949 UnicodeEncodeError 방지
    sys.stdout.reconfigure(encoding="utf-8")

SEED = 20260822

# 본문을 담은 크롤 산출물만. blog_raw/ · blog_raw_africaamc/ · blog_raw_rescue/의
# posts.jsonl 3종(529 + 189 + 103 = 821건). --pattern으로 덮어쓸 수 있다.
CORPUS_GLOB = "**/posts.jsonl"

# ---------------------------------------------------------------- 사전

# 순번 표지. 04번 리서치 문서가 보고한 "53/821(6.5%)"의 재현·확장이 목적이라
# 그 문서가 언급한 유형(숫자단계, 서수, 접속부사 연쇄)을 폭넓게 잡는다.
STEP_MARKERS = [
    "1단계", "2단계", "3단계", "4단계", "5단계", "6단계", "7단계",
    "STEP1", "STEP 1", "STEP2", "STEP 2", "STEP3", "STEP 3",
    "step1", "step 1", "step2", "step 2",
    "첫째", "둘째", "셋째", "넷째", "다섯째",
    "첫 번째", "두 번째", "세 번째", "네 번째", "다섯 번째",
    "먼저", "그다음", "그 다음", "다음으로", "이후에는", "마지막으로", "마지막은",
    "순서대로", "차례로",
]

# 조건분기(GATE) 후보 표지. schema_procedure_v1.md가 "근거 미확인"이라 명시한 부분 —
# 이 측정으로 실사용 여부를 확인한다.
GATE_MARKERS = [
    "안 되면", "안되면", "실패하면", "하지 않으면", "안 될 경우", "안될 경우",
    "될 때까지", "성공하면", "통과하면", "이틀 연속", "3일 연속", "며칠간",
    "적응이 되면", "익숙해지면", "익숙해지고 나면",
]

STEP_GROUP = {m: "순번표지" for m in STEP_MARKERS}
GATE_GROUP = {m: "게이트후보" for m in GATE_MARKERS}
ALL_MARKERS = STEP_MARKERS + GATE_MARKERS
MARKER_GROUP = {**STEP_GROUP, **GATE_GROUP}

# 주제 10축 = 커리큘럼 8 + 문제행동 2. 원본 그대로 둔다.
# 절차 표지와 주제의 교차가 이번에 봐야 할 값이다.
TOPICS = {
    "배변":     dict(tier="약함",   kw=["배변", "대소변", "소변", "배변패드", "배변 패드",
                                        "배변판", "화장실", "마킹", "실내 배변"]),
    "이름":     dict(tier="거의0",  kw=["이름 부르", "이름을 부르", "호명", "이름 훈련"]),
    "아이컨택": dict(tier="거의0",  kw=["아이컨택", "아이 컨택", "눈맞춤", "눈 맞춤",
                                        "눈을 마주", "시선 맞"]),
    "스킨십":   dict(tier="약함",   kw=["스킨십", "핸들링", "만지는", "만져", "빗질",
                                        "발톱", "터치에"]),
    "입질":     dict(tier="강함",   kw=["입질", "무는", "물기", "깨물", "물어뜯", "물었"]),
    "명령어":   dict(tier="거의0",  kw=["명령어", "지시어", "앉아", "기다려", "엎드려",
                                        "이리와", "콜링", "기본 복종"]),
    "하우스":   dict(tier="중간",   kw=["하우스", "켄넬", "크레이트", "울타리", "펜스",
                                        "방석 훈련"]),
    "산책":     dict(tier="중간",   kw=["산책", "리드줄", "목줄", "하네스", "줄 당김",
                                        "당기는", "끌고"]),
    "분리불안": dict(tier="강함",   kw=["분리불안", "분리 불안", "혼자 있", "혼자 두",
                                        "부재중", "외출할 때", "빈집"]),
    "짖음":     dict(tier="강함",   kw=["짖", "하울링", "우다다", "경계 짖", "요구성"]),
}

# ---------------------------------------------------------------- 일지 필터
# env 스크립트와 동일. 문서 단위로 거른다 — 신호 조합은 지시받은 4개만 쓴다.

JOURNAL_MARKERS = ("입소", "퇴소", "오늘 입소한", "교육중이랍니다",
                   "유치원 다니", "훈련소에서")
CAPTION_ENDINGS = ("랍니다", "예요", "입니다")
PROMO_TITLE_MARKERS = ("문의", "상담예약", "오픈", "이벤트", "할인")

CAPTION_MAX_BODY = 500
CAPTION_MIN_HITS = 2
TITLE_SLASH_MIN = 4
HEAD_CHARS = 300


def journal_reasons(title: str, body: str):
    head = (title or "") + " " + (body or "")[:HEAD_CHARS]
    reasons = []
    if any(m in head for m in JOURNAL_MARKERS):
        reasons.append("입소퇴소일지")
    if (len(body or "") < CAPTION_MAX_BODY
            and sum((body or "").count(e) for e in CAPTION_ENDINGS) >= CAPTION_MIN_HITS):
        reasons.append("개체소개캡션")
    if (title or "").count("/") >= TITLE_SLASH_MIN:
        reasons.append("슬래시제목")
    if any(m in (title or "") for m in PROMO_TITLE_MARKERS):
        reasons.append("홍보영업")
    return reasons


# ---------------------------------------------------------------- lens

LENS_BY_AUTHOR = {"yoonsu3454": "trainer", "africaamc": "vet"}
LENS_UNKNOWN_DIRS = ("blog_raw_rescue",)


def lens_of(doc_id: str, src_path: str) -> str:
    if any(d in src_path for d in LENS_UNKNOWN_DIRS):
        return "unknown"
    for author, lens in LENS_BY_AUTHOR.items():
        if author in doc_id or author in src_path:
            return lens
    return "unknown"


# ---------------------------------------------------------------- 로더


def iter_docs(root: Path, pattern: str = CORPUS_GLOB):
    key_title = ("title", "제목", "subject", "post_title")
    key_body = ("content", "body", "text", "본문", "clean_text", "cleaned")
    key_url = ("url", "link", "source_url", "permalink")
    key_id = ("doc_id", "id", "logNo", "log_no", "post_id")

    def pick(d, keys, default=""):
        for k in keys:
            if k in d and d[k]:
                return str(d[k])
        return default

    files = [p for p in root.rglob(pattern)
             if p.suffix.lower() in (".json", ".jsonl", ".txt", ".md")]
    for path in sorted(files):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  [skip] {path.name}: {e}", file=sys.stderr)
            continue

        if path.suffix.lower() == ".jsonl":
            for i, line in enumerate(raw.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield dict(doc_id=pick(d, key_id, f"{path.stem}#{i}"),
                           title=pick(d, key_title), body=pick(d, key_body),
                           url=pick(d, key_url), src=path.name, src_path=rel)
        elif path.suffix.lower() == ".json":
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            items = obj if isinstance(obj, list) else [obj]
            for i, d in enumerate(items):
                if not isinstance(d, dict):
                    continue
                yield dict(doc_id=pick(d, key_id, f"{path.stem}#{i}"),
                           title=pick(d, key_title), body=pick(d, key_body),
                           url=pick(d, key_url), src=path.name, src_path=rel)
        else:
            yield dict(doc_id=path.stem, title="", body=raw, url="",
                       src=path.name, src_path=rel)


# ---------------------------------------------------------------- 처리

SENT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


def split_sentences(text: str):
    out = []
    for s in SENT_RE.split(text or ""):
        s = " ".join(s.split())
        if 10 <= len(s) <= 400:
            out.append(s)
    return out


def split_tagged(title: str, body: str):
    return ([(s, True) for s in split_sentences(title)]
            + [(s, False) for s in split_sentences(body)])


def find_terms(sent: str, terms):
    return [t for t in terms if t in sent]


def tag_topics(sent: str):
    hits = []
    for name, spec in TOPICS.items():
        if any(k in sent for k in spec["kw"]):
            hits.append(name)
    return hits


def tail_snippet(sent: str, kw: str, nchar: int = 14):
    """마커 뒤 원문을 문자 단위로 잘라낸다. 크로스 문서 재사용 근사 측정용.

    ★ 술어 명명이 아니라 원문 스니펫 재현 여부만 본다. 정규화(공백 제거)해서
    같은 스니펫이 여러 doc_id에 나오면 "재사용 후보"로만 표시한다 — 실제 같은
    절차인지는 사람이 확인해야 한다.
    """
    idx = sent.find(kw)
    if idx < 0:
        return None
    rest = sent[idx + len(kw):].strip(" ~^!?.,")
    if len(rest) < 4:
        return None
    snippet = rest[:nchar]
    return re.sub(r"\s+", "", snippet)


def stratify(rows, quota, rng):
    by_lens = defaultdict(list)
    for r in rows:
        by_lens[r["lens"]].append(r)
    lenses = sorted(by_lens)
    caps = {L: len(by_lens[L]) for L in lenses}
    alloc = {L: 0 for L in lenses}
    remaining = min(quota, sum(caps.values()))
    while remaining > 0:
        avail = [L for L in lenses if alloc[L] < caps[L]]
        if not avail:
            break
        share = max(1, remaining // len(avail))
        for L in avail:
            if remaining <= 0:
                break
            take = min(share, caps[L] - alloc[L], remaining)
            alloc[L] += take
            remaining -= take
    picked = []
    for L in lenses:
        if alloc[L]:
            picked.extend(rng.sample(by_lens[L], alloc[L]))
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="./scrapper/data")
    ap.add_argument("--out", default="./procedure_factcheck")
    ap.add_argument("--per-topic", type=int, default=5)
    ap.add_argument("--pattern", default=CORPUS_GLOB)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-journal-filter", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        sys.exit(f"경로 없음: {root}")

    docs = list(iter_docs(root, args.pattern))
    if args.inspect:
        print(f"문서 {len(docs)}건")
        return

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    # ---- 1) 문서 단위 일지 필터 ----
    kept, excluded = [], []
    reason_count = Counter()
    for d in docs:
        rs = [] if args.no_journal_filter else journal_reasons(d["title"], d["body"])
        if rs:
            excluded.append((d["doc_id"], "|".join(rs), d["title"][:60]))
            for r in rs:
                reason_count[r] += 1
        else:
            kept.append(d)

    with open(outdir / "excluded_journal_docs_procedure.txt", "w", encoding="utf-8") as f:
        f.write(f"# 문서 단위 일지 필터로 제외된 문서 {len(excluded)}건 / 전체 {len(docs)}건\n")
        for did, rs, ti in excluded:
            f.write(f"{did}\t{rs}\t{ti}\n")

    excl_pct = len(excluded) / max(len(docs), 1) * 100
    print(f"\n[일지 필터] 전체 {len(docs)}  제외 {len(excluded)} ({excl_pct:.1f}%)  "
          f"잔존 {len(kept)}")
    for r, c in reason_count.most_common():
        print(f"    {r:<12} {c:>5}   (사유 중복 집계)")

    # ---- 2) 문서 단위 STEP 구조 판정 + 문장 스캔 ----
    random.seed(SEED)
    by_topic = defaultdict(list)
    kw_sents = Counter()
    kw_docs = defaultdict(set)
    kw_lens = defaultdict(Counter)
    kw_topic = defaultdict(Counter)
    total_sents = hit_sents = 0
    hit_docs = set()

    # 크로스 문서 재사용 근사: (마커, 스니펫) -> {doc_id, ...}
    snippet_docs = defaultdict(set)
    snippet_example = {}

    # 문서별로 등장한 서로 다른 STEP 표지 집합 (문서 내 시퀀스 성립 여부 판정용)
    doc_step_markers = defaultdict(set)
    doc_gate_hits = defaultdict(int)
    doc_step_hits = defaultdict(int)

    # GATE 표지가 STEP 문맥(같은 문서에 STEP 표지도 있음) 안인지 밖인지
    gate_in_step_doc = 0
    gate_outside_step_doc = 0

    for d in kept:
        lens = lens_of(d["doc_id"], d.get("src_path", ""))
        tagged = split_tagged(d["title"], d["body"])
        sents = [s for s, _ in tagged]
        total_sents += len(sents)

        for i, (s, is_title) in enumerate(tagged):
            terms = find_terms(s, ALL_MARKERS)
            if not terms:
                continue
            hit_sents += 1
            hit_docs.add(d["doc_id"])
            topics = tag_topics(s)

            for t in terms:
                kw_sents[t] += 1
                kw_docs[t].add(d["doc_id"])
                kw_lens[t][lens] += 1
                for tp in (topics or ["(미분류)"]):
                    kw_topic[t][tp] += 1
                if t in STEP_GROUP:
                    doc_step_markers[d["doc_id"]].add(t)
                    doc_step_hits[d["doc_id"]] += 1
                else:
                    doc_gate_hits[d["doc_id"]] += 1

                snip = tail_snippet(s, t)
                if snip:
                    snippet_docs[(t, snip)].add(d["doc_id"])
                    snippet_example.setdefault((t, snip), s)

            row = dict(
                doc_id=d["doc_id"], url=d["url"], lens=lens,
                is_title="Y" if is_title else "",
                주제="|".join(topics) or "(미분류)",
                procedure_marker="|".join(terms),
                procedure_group="|".join(sorted({MARKER_GROUP[t] for t in terms})),
                이전문장=sents[i - 1] if i else "",
                문장=s,
                다음문장=sents[i + 1] if i + 1 < len(sents) else "",
                순서서술="", 게이트여부="", dimension_guess="", 메모="",
            )
            for tp in (topics or ["(미분류)"]):
                by_topic[tp].append(row)

    # GATE 문맥 판정 (문서 단위)
    for doc_id, gate_n in doc_gate_hits.items():
        if gate_n <= 0:
            continue
        if doc_id in doc_step_markers and len(doc_step_markers[doc_id]) >= 1:
            gate_in_step_doc += 1
        else:
            gate_outside_step_doc += 1

    # ---- 3) 표본: 주제 x lens 층화, dedup ----
    sample = []
    for topic in sorted(by_topic):
        uniq = list({r["문장"]: r for r in by_topic[topic]}.values())
        sample.extend(stratify(uniq, args.per_topic, random))
    _seen = set()
    sample = [r for r in sample if not (r["문장"] in _seen or _seen.add(r["문장"]))]

    cols = ["doc_id", "lens", "is_title", "주제", "procedure_marker", "procedure_group",
            "이전문장", "문장", "다음문장",
            "순서서술", "게이트여부", "dimension_guess", "메모", "url"]
    with open(outdir / "sample_procedure_v1.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sample)

    # ---- 4) 집계 출력 ----
    print(f"\n[모집단] 잔존문서 {len(kept)}  문장 {total_sents}  "
          f"절차표지 언급 문장 {hit_sents} ({hit_sents/max(total_sents,1)*100:.1f}%)  "
          f"언급 문서 {len(hit_docs)}")

    n_step_struct_docs = sum(1 for markers in doc_step_markers.values() if len(markers) >= 2)
    n_step_any_docs = len(doc_step_markers)
    print(f"\n[문서 단위 STEP 구조 판정]")
    print(f"    STEP 표지가 하나라도 있는 문서: {n_step_any_docs} "
          f"({n_step_any_docs/max(len(kept),1)*100:.1f}%)")
    print(f"    서로 다른 STEP 표지 2개 이상(시퀀스 성립 후보): {n_step_struct_docs} "
          f"({n_step_struct_docs/max(len(kept),1)*100:.1f}%)")
    print("    ※ '04번 리서치 문서 53/821(6.5%)'과 마커 목록이 달라 직접 비교값이 아님 — "
          "이 스크립트의 마커 정의 기준 재현치임을 명시할 것")

    print(f"\n[GATE 후보 문맥 판정]")
    print(f"    GATE 표지가 STEP 구조 문서 안에 있음: {gate_in_step_doc}")
    print(f"    GATE 표지가 STEP 구조 밖(무관 문맥 가능성): {gate_outside_step_doc}")

    print(f"\n[크로스 문서 재사용 근사 측정 — (마커,스니펫)이 서로 다른 doc_id 2개 이상]")
    reuse_pairs = [(k, v) for k, v in snippet_docs.items() if len(v) >= 2]
    reuse_pairs.sort(key=lambda kv: -len(kv[1]))
    print(f"    재사용 후보 (마커,스니펫) 쌍 수: {len(reuse_pairs)} / 전체 고유 쌍 {len(snippet_docs)}")
    print(f"    ※ 원문 스니펫 문자열 일치일 뿐 동일 절차 확인 아님 — [추정] 사람 확인 필요")
    for (marker, snip), doc_ids in reuse_pairs[:15]:
        print(f"    {marker:<8} '{snip}'  -> {len(doc_ids)}개 문서: {sorted(doc_ids)[:4]}")

    with open(outdir / "procedure_cross_doc_reuse_candidates.csv", "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["marker", "snippet", "n_docs", "doc_ids", "example_sentence"])
        for (marker, snip), doc_ids in reuse_pairs:
            w.writerow([marker, snip, len(doc_ids), "|".join(sorted(doc_ids)),
                        snippet_example.get((marker, snip), "")])

    top = [k for k, _ in kw_sents.most_common(args.top)]
    print(f"\n(a) 마커별 언급 Top {args.top}")
    print(f"    {'마커':<12}{'분류':<10}{'문장':>7}{'문서':>7}"
          f"{'trainer':>9}{'vet':>6}{'unknown':>9}")
    for k in top:
        L = kw_lens[k]
        print(f"    {k:<12}{MARKER_GROUP[k]:<10}{kw_sents[k]:>7}{len(kw_docs[k]):>7}"
              f"{L['trainer']:>9}{L['vet']:>6}{L['unknown']:>9}")

    print(f"\n(b) 마커 x 주제 교차 (Top {args.top})")
    focus = ["배변", "분리불안", "짖음", "하우스", "산책", "입질", "(미분류)"]
    print(f"    {'마커':<12}" + "".join(f"{t:>9}" for t in focus))
    for k in top:
        print(f"    {k:<12}" + "".join(f"{kw_topic[k][t]:>9}" for t in focus))

    print(f"\n-> {outdir}/sample_procedure_v1.csv  ({len(sample)}행) 라벨 열 전부 공란")
    print(f"-> {outdir}/procedure_cross_doc_reuse_candidates.csv")


if __name__ == "__main__":
    main()
