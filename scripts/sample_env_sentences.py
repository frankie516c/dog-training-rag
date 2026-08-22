#!/usr/bin/env python3
"""
환경어 언급 문장 표본 추출기 (환경 축 팩트체크용)

`sample_breed_sentences.py`를 복사해 사전만 환경어로 갈아끼운 것이다.
원본은 견종 측정 재현성 보존을 위해 수정하지 않았다.

견종 축은 종결됐다: 훈련 도메인에서 견종은 빈도(호발) 관계만 있고 처치 관계는 없다.
이번 측정은 환경 축이 같은 운명인지 아닌지를 재는 것이다. 환경 축은 근거가 견종보다
더 약하다 — 그래프에 노드가 0개이고, ContextFactor 타입 자체가 코퍼스에서 나온 게
아니라 설계자가 제안한 것이다.

★ 원본과 다른 점
  1. BREEDS/TRAITS -> ENV_TERMS (주거/공간 · 보호자/부재 · 생활/이벤트)
  2. 문서 단위 일지 필터 추가. 문장 단위로는 입소 일지를 걸러낼 수 없다.
     견종 측정에서 짖음 21행 중 12행 이상이 훈련소 입소 일지였다.
  3. env_keyword / dimension_guess 열 추가
  4. 술어 패턴 귀납 집계 추가 (수집일 뿐 명명이 아니다)

사용
  python sample_env_sentences.py --root <크롤폴더> --out data/env_factcheck --per-topic 5
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

# 지시받은 목록 그대로. 임의 추가하지 않았다. 추가 제안은 리포트의 별도 절에만 적는다.
ENV_TERMS = {
    "주거/공간": [
        "아파트", "빌라", "주택", "원룸", "마루", "장판", "미끄럼", "미끄러",
        "소음", "방음", "층간소음", "켄넬", "크레이트", "울타리", "펜스",
        "베란다", "현관",
    ],
    "보호자/부재": [
        "혼자", "부재", "외출", "퇴근", "출근", "맞벌이", "1인가구",
        "혼자 있", "혼자 두", "집을 비우", "다견", "합사", "둘째", "가족",
    ],
    "생활/이벤트": [
        "이사", "산책", "방문객", "외부인", "택배", "초인종",
        "배변패드", "배변 패드", "배변판", "하네스", "목줄", "리드줄",
    ],
}
ENV_ALL = [t for terms in ENV_TERMS.values() for t in terms]
ENV_GROUP = {t: g for g, terms in ENV_TERMS.items() for t in terms}

# 주제 10축 = 커리큘럼 8 + 문제행동 2. 원본 그대로 둔다.
# 환경어와 주제의 교차가 이번에 봐야 할 값이다.
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

# 조건 신호어 — pool_signal 전용. 무작위 표본에는 절대 적용하지 않는다.
COND_MARKERS = [
    "해야", "하면 안", "하지 말", "때문에", "탓에", "라서", "이라서",
    "므로", "이므로", "주의", "특히", "경우에는", "권장", "피해야",
    "어렵", "쉽", "유의", "다르게", "달리",
]

# ---------------------------------------------------------------- 일지 필터

# ★ 문서 단위로 거른다. 문장 단위 필터로는 입소 일지를 걸러낼 수 없다.
#   신호 조합은 지시받은 4개만 쓴다. 임의로 추가하지 않았다.
JOURNAL_MARKERS = ("입소", "퇴소", "오늘 입소한", "교육중이랍니다",
                   "유치원 다니", "훈련소에서")
CAPTION_ENDINGS = ("랍니다", "예요", "입니다")
PROMO_TITLE_MARKERS = ("문의", "상담예약", "오픈", "이벤트", "할인")

CAPTION_MAX_BODY = 500      # 개체 소개 캡션 판정용 본문 길이 상한
CAPTION_MIN_HITS = 2        # "반복" 판정 기준
TITLE_SLASH_MIN = 4         # 슬래시 키워드 나열형 제목
HEAD_CHARS = 300            # 본문 앞부분 기준


def journal_reasons(title: str, body: str):
    """제외 사유 목록. 비어 있으면 통과."""
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
    """출처 lens 판정. 확신이 없으면 unknown. 추측하지 않는다."""
    if any(d in src_path for d in LENS_UNKNOWN_DIRS):
        return "unknown"
    for author, lens in LENS_BY_AUTHOR.items():
        if author in doc_id or author in src_path:
            return lens
    return "unknown"


# ---------------------------------------------------------------- 로더


def iter_docs(root: Path, pattern: str = CORPUS_GLOB):
    """본문을 담은 파일만 읽는다. 목록 파일이 섞이면 제목이 문장으로 잡힌다."""
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
    """(문장, is_title) 목록. 제목 유래인지 본문 유래인지 기록한다."""
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


def tail_predicate(sent: str, kw: str, ntok: int = 2):
    """키워드 뒤에 오는 서술부를 원문 그대로 잘라낸다.

    ★ 이건 술어 '후보 수집'이지 명명이 아니다. 정제하지 않고 날것으로 둔다.
    키워드 뒤 문자열의 마지막 ntok개 어절을 그대로 돌려준다. 뒤가 비면 None.
    """
    idx = sent.find(kw)          # 첫 등장 기준. rfind면 문말 키워드에서 조사만 남는다
    if idx < 0:
        return None
    rest = sent[idx + len(kw):].strip(" ~^!?.,")
    if not rest:
        return None
    toks = rest.split()
    if not toks:
        return None
    out = " ".join(toks[-ntok:]).strip(" ~^!?.,")
    if len(out) < 3:             # "을" "은" 같은 조사 조각은 서술부가 아니다
        out = " ".join(toks[-(ntok + 1):]).strip(" ~^!?.,")
    return out if len(out) >= 3 else None


def stratify(rows, quota, rng):
    """lens별로 균등 배분해 뽑는다. 한쪽 lens가 표본을 독점하지 못하게 한다."""
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
    ap.add_argument("--out", default="./env_factcheck")
    ap.add_argument("--per-topic", type=int, default=5, help="주제별 무작위 표본 수")
    ap.add_argument("--pattern", default=CORPUS_GLOB)
    ap.add_argument("--top", type=int, default=10, help="집계에 쓸 상위 키워드 수")
    ap.add_argument("--no-journal-filter", action="store_true",
                    help="일지 필터를 끄고 실행 (대조용)")
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

    with open(outdir / "excluded_journal_docs.txt", "w", encoding="utf-8") as f:
        f.write(f"# 문서 단위 일지 필터로 제외된 문서 {len(excluded)}건 / 전체 {len(docs)}건\n")
        f.write("# doc_id\t사유\t제목앞부분\n")
        for did, rs, ti in excluded:
            f.write(f"{did}\t{rs}\t{ti}\n")

    excl_pct = len(excluded) / max(len(docs), 1) * 100
    print(f"\n[일지 필터] 전체 {len(docs)}  제외 {len(excluded)} ({excl_pct:.1f}%)  "
          f"잔존 {len(kept)}")
    for r, c in reason_count.most_common():
        print(f"    {r:<12} {c:>5}   (사유 중복 집계)")
    if excl_pct > 60:
        print("    ※ 제외율 60% 초과 — 필터가 과하게 걸렸을 수 있음. 그대로 진행함")
    print(f"    -> {outdir}/excluded_journal_docs.txt (감사용, 커밋 대상 아님)")

    # ---- 2) 문장 스캔 ----
    random.seed(SEED)
    by_topic = defaultdict(list)
    pop_rows = []
    kw_sents = Counter()
    kw_docs = defaultdict(set)
    kw_lens = defaultdict(Counter)
    kw_topic = defaultdict(Counter)
    kw_pred = defaultdict(Counter)
    pred_all = Counter()
    total_sents = hit_sents = 0
    hit_docs = set()

    for d in kept:
        lens = lens_of(d["doc_id"], d.get("src_path", ""))
        tagged = split_tagged(d["title"], d["body"])
        sents = [s for s, _ in tagged]
        total_sents += len(sents)

        for i, (s, is_title) in enumerate(tagged):
            terms = find_terms(s, ENV_ALL)
            if not terms:
                continue
            hit_sents += 1
            hit_docs.add(d["doc_id"])
            topics = tag_topics(s)
            groups = sorted({ENV_GROUP[t] for t in terms})

            for t in terms:
                kw_sents[t] += 1
                kw_docs[t].add(d["doc_id"])
                kw_lens[t][lens] += 1
                for tp in (topics or ["(미분류)"]):
                    kw_topic[t][tp] += 1
                p = tail_predicate(s, t)
                if p:
                    kw_pred[t][p] += 1
                    pred_all[p] += 1

            row = dict(
                doc_id=d["doc_id"], url=d["url"], lens=lens,
                is_title="Y" if is_title else "",
                주제="|".join(topics) or "(미분류)",
                env_keyword="|".join(terms), env_group="|".join(groups),
                이전문장=sents[i - 1] if i else "",
                문장=s,
                다음문장=sents[i + 1] if i + 1 < len(sents) else "",
                조건성="", 술어원문="", dimension_guess="", 메모="",
            )
            pop_rows.append(row)
            for tp in (topics or ["(미분류)"]):
                by_topic[tp].append(row)

    # ---- 3) 표본: 주제 x lens 층화, dedup ----
    sample = []
    for topic in sorted(by_topic):
        uniq = list({r["문장"]: r for r in by_topic[topic]}.values())
        sample.extend(stratify(uniq, args.per_topic, random))
    _seen = set()
    sample = [r for r in sample if not (r["문장"] in _seen or _seen.add(r["문장"]))]

    cols = ["doc_id", "lens", "is_title", "주제", "env_keyword", "env_group",
            "이전문장", "문장", "다음문장",
            "조건성", "술어원문", "dimension_guess", "메모", "url"]
    with open(outdir / "sample_env_v1.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sample)

    # ---- 4) 집계 ----
    print(f"\n[모집단] 잔존문서 {len(kept)}  문장 {total_sents}  "
          f"환경어 언급 문장 {hit_sents} ({hit_sents/max(total_sents,1)*100:.1f}%)  "
          f"언급 문서 {len(hit_docs)}")

    top = [k for k, _ in kw_sents.most_common(args.top)]

    print(f"\n(a) 키워드별 언급 Top {args.top}  [일지 제외 후]")
    print(f"    {'키워드':<10}{'분류':<12}{'문장':>7}{'문서':>7}"
          f"{'trainer':>9}{'vet':>6}{'unknown':>9}")
    print("    " + "-" * 62)
    for k in top:
        L = kw_lens[k]
        print(f"    {k:<10}{ENV_GROUP[k]:<12}{kw_sents[k]:>7}{len(kw_docs[k]):>7}"
              f"{L['trainer']:>9}{L['vet']:>6}{L['unknown']:>9}")

    print(f"\n(b) 키워드 x 주제 교차 (Top {args.top})")
    focus = ["배변", "분리불안", "짖음", "하우스", "산책", "입질", "(미분류)"]
    print(f"    {'키워드':<10}" + "".join(f"{t:>9}" for t in focus))
    print("    " + "-" * (10 + 9 * len(focus)))
    for k in top:
        print(f"    {k:<10}" + "".join(f"{kw_topic[k][t]:>9}" for t in focus))

    print("\n(c) 술어 패턴 상위 15 — 원문 그대로. 수집이지 명명이 아님")
    print(f"    (키워드 뒤 마지막 2어절. Top {args.top} 키워드 포함 문장 대상)")
    top_set = set(top)
    pred_top = Counter()
    for k in top_set:
        for p, c in kw_pred[k].items():
            pred_top[p] += c
    print(f"    {'빈도':>5}  서술 형태")
    print("    " + "-" * 50)
    for p, c in pred_top.most_common(15):
        print(f"    {c:>5}  {p}")

    print(f"\n-> {outdir}/sample_env_v1.csv  ({len(sample)}행) 라벨 열 전부 공란")


if __name__ == "__main__":
    main()
