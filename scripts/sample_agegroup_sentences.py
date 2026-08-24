#!/usr/bin/env python3
"""
연령대 언급 문장 표본 추출기 (연령대 축 1차 실측용 — 견종 축과 동일 잣대)

`sample_env_sentences.py`를 복사해 사전과 측정 항목만 연령대 축으로 갈아끼운 것이다.
원본 둘(sample_breed_sentences.py, sample_env_sentences.py)은 재현성 보존을 위해
수정하지 않았다.

배경: `reports/research_graph_viability_0824/04_alternative_axis_candidates_researcher.md`가
"생애주기 어휘 613문장/245문서"(원문 코퍼스 기준)를 인용했으나 이건 그 세션이 미실측
추정으로만 다룬 값이다. 이 스크립트는 그 수치를 재현/검증하고, **견종 축을 기각시킨
바로 그 잣대**(빈도/공기 서술만 있는가, 처치를 가르는 문장이 있는가, 순환 매칭 오염이
있는가)를 연령대에도 그대로 적용한다.

★ 원본(sample_env_sentences.py)과 다른 점
  1. ENV_TERMS -> AGE_TERMS(유아기/성견/노령견) + 숫자 개월·살 표기 정규식 별도 집계
  2. TOPICS 사전과의 순환 매칭(문자열 공유) 자동 점검 추가
  3. 술어 패턴 수집을 "연령대 언급 있음" vs "연령대 언급 없음" 문장으로 분리해서
     같은 주제(topic) 안에서 처치 서술이 실제로 갈리는지 볼 수 있는 원자료를 만든다
     (판정은 하지 않는다 — 원자료만 나란히 낸다)

사용
  python sample_agegroup_sentences.py --root <크롤폴더> --out data/procedure_agegroup_factcheck --per-topic 5
"""

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SEED = 20260822

CORPUS_GLOB = "**/posts.jsonl"

# ---------------------------------------------------------------- 사전

# 논리적으로 도출한 캐노니컬 3구간. 04번 문서가 그은 "생애주기"의 최소 골격이며,
# 임의 확장하지 않았다 — 추가 후보가 떠오르면 리포트의 별도 절에만 적는다.
AGE_TERMS = {
    "유아기": [
        "퍼피", "새끼", "아기 강아지", "유견", "이유기", "생후", "젖먹이",
        "어린 강아지", "새끼 강아지",
    ],
    "성견": [
        "성견", "다 큰", "성체", "다 자란",
    ],
    "노령견": [
        "노령견", "노령", "시니어", "고령견", "늙은 강아지", "나이 든 강아지",
        "나이가 많은", "노견",
    ],
}
AGE_ALL = [t for terms in AGE_TERMS.values() for t in terms]
AGE_GROUP = {t: g for g, terms in AGE_TERMS.items() for t in terms}

# 숫자 개월/살 표기는 리터럴 키워드가 아니라 정규식으로 별도 집계한다.
NUMERIC_AGE_RE = re.compile(r"\d{1,2}\s*(개월|살|살짜리|년생)")

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


def check_circular_overlap():
    """AGE_TERMS와 TOPICS 사전이 문자열을 공유하는지 점검.

    space_setup(agenda_0825.md #18)이 환경어 사전과 TOPICS가 같은 문자열을 공유해
    순환 매칭이 됐던 것과 같은 함정인지 미리 확인한다. 발견되면 그대로 보고만 하고
    사전을 임의로 고치지 않는다.
    """
    topic_kw = set()
    for spec in TOPICS.values():
        topic_kw.update(spec["kw"])
    overlaps = []
    for age_term in AGE_ALL:
        for tk in topic_kw:
            if age_term in tk or tk in age_term:
                overlaps.append((age_term, tk))
    return overlaps


# ---------------------------------------------------------------- 일지 필터

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


def tail_predicate(sent: str, kw: str, ntok: int = 2):
    idx = sent.find(kw)
    if idx < 0:
        return None
    rest = sent[idx + len(kw):].strip(" ~^!?.,")
    if not rest:
        return None
    toks = rest.split()
    if not toks:
        return None
    out = " ".join(toks[-ntok:]).strip(" ~^!?.,")
    if len(out) < 3:
        out = " ".join(toks[-(ntok + 1):]).strip(" ~^!?.,")
    return out if len(out) >= 3 else None


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
    ap.add_argument("--out", default="./agegroup_factcheck")
    ap.add_argument("--per-topic", type=int, default=5)
    ap.add_argument("--pattern", default=CORPUS_GLOB)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-journal-filter", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    args = ap.parse_args()

    overlaps = check_circular_overlap()
    print("[순환 매칭 사전 점검] AGE_TERMS x TOPICS 문자열 공유:", end=" ")
    if overlaps:
        print(f"{len(overlaps)}건 발견 — 아래는 순환 매칭 위험")
        for a, t in overlaps:
            print(f"    연령어 '{a}' <-> TOPICS 키워드 '{t}'")
    else:
        print("0건 (겹치는 문자열 없음)")

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

    with open(outdir / "excluded_journal_docs_agegroup.txt", "w", encoding="utf-8") as f:
        f.write(f"# 문서 단위 일지 필터로 제외된 문서 {len(excluded)}건 / 전체 {len(docs)}건\n")
        for did, rs, ti in excluded:
            f.write(f"{did}\t{rs}\t{ti}\n")

    excl_pct = len(excluded) / max(len(docs), 1) * 100
    print(f"\n[일지 필터] 전체 {len(docs)}  제외 {len(excluded)} ({excl_pct:.1f}%)  "
          f"잔존 {len(kept)}")
    for r, c in reason_count.most_common():
        print(f"    {r:<12} {c:>5}   (사유 중복 집계)")

    # ---- 2) 문장 스캔 ----
    random.seed(SEED)
    by_topic = defaultdict(list)
    kw_sents = Counter()
    kw_docs = defaultdict(set)
    kw_lens = defaultdict(Counter)
    kw_topic = defaultdict(Counter)
    kw_pred_with = defaultdict(Counter)   # 연령어 있는 문장의 술어 tail
    kw_pred_without_topic = defaultdict(Counter)  # 같은 주제, 연령어 없는 문장의 술어 tail
    total_sents = hit_sents = 0
    hit_docs = set()

    numeric_sents = 0
    numeric_docs = set()
    numeric_examples = []

    for d in kept:
        lens = lens_of(d["doc_id"], d.get("src_path", ""))
        tagged = split_tagged(d["title"], d["body"])
        sents = [s for s, _ in tagged]
        total_sents += len(sents)

        for i, (s, is_title) in enumerate(tagged):
            if NUMERIC_AGE_RE.search(s):
                numeric_sents += 1
                numeric_docs.add(d["doc_id"])
                if len(numeric_examples) < 30:
                    numeric_examples.append((d["doc_id"], NUMERIC_AGE_RE.search(s).group(0), s))

            terms = find_terms(s, AGE_ALL)
            topics = tag_topics(s)

            if terms:
                hit_sents += 1
                hit_docs.add(d["doc_id"])
                for t in terms:
                    kw_sents[t] += 1
                    kw_docs[t].add(d["doc_id"])
                    kw_lens[t][lens] += 1
                    for tp in (topics or ["(미분류)"]):
                        kw_topic[t][tp] += 1
                    p = tail_predicate(s, t)
                    if p:
                        for tp in (topics or ["(미분류)"]):
                            kw_pred_with[tp][p] += 1
                row = dict(
                    doc_id=d["doc_id"], url=d["url"], lens=lens,
                    is_title="Y" if is_title else "",
                    주제="|".join(topics) or "(미분류)",
                    age_keyword="|".join(terms),
                    age_group="|".join(sorted({AGE_GROUP[t] for t in terms})),
                    이전문장=sents[i - 1] if i else "",
                    문장=s,
                    다음문장=sents[i + 1] if i + 1 < len(sents) else "",
                    조건성="", 처치분화="", dimension_guess="", 메모="",
                )
                for tp in (topics or ["(미분류)"]):
                    by_topic[tp].append(row)
            elif topics:
                # 연령어는 없지만 같은 주제인 문장 — 술어 대조군
                for tp in topics:
                    for kw in TOPICS[tp]["kw"]:
                        p = tail_predicate(s, kw)
                        if p:
                            kw_pred_without_topic[tp][p] += 1
                            break

    # ---- 3) 표본: 주제 x lens 층화, dedup ----
    sample = []
    for topic in sorted(by_topic):
        uniq = list({r["문장"]: r for r in by_topic[topic]}.values())
        sample.extend(stratify(uniq, args.per_topic, random))
    _seen = set()
    sample = [r for r in sample if not (r["문장"] in _seen or _seen.add(r["문장"]))]

    cols = ["doc_id", "lens", "is_title", "주제", "age_keyword", "age_group",
            "이전문장", "문장", "다음문장",
            "조건성", "처치분화", "dimension_guess", "메모", "url"]
    with open(outdir / "sample_agegroup_v1.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sample)

    with open(outdir / "sample_agegroup_numeric_v1.csv", "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "matched", "문장"])
        for doc_id, matched, s in numeric_examples:
            w.writerow([doc_id, matched, s])

    # ---- 4) 집계 출력 ----
    print(f"\n[모집단] 잔존문서 {len(kept)}  문장 {total_sents}  "
          f"연령어 언급 문장 {hit_sents} ({hit_sents/max(total_sents,1)*100:.1f}%)  "
          f"언급 문서 {len(hit_docs)}")
    print(f"[숫자 개월/살 표기] 문장 {numeric_sents} "
          f"({numeric_sents/max(total_sents,1)*100:.2f}%)  문서 {len(numeric_docs)}  "
          f"(리터럴 키워드가 아니라 정규식 {NUMERIC_AGE_RE.pattern} 기준, 별도 집계)")

    top = [k for k, _ in kw_sents.most_common(args.top)]
    print(f"\n(a) 연령어별 언급 Top {args.top}  [일지 제외 후]")
    print(f"    {'연령어':<12}{'분류':<8}{'문장':>7}{'문서':>7}"
          f"{'trainer':>9}{'vet':>6}{'unknown':>9}")
    for k in top:
        L = kw_lens[k]
        print(f"    {k:<12}{AGE_GROUP[k]:<8}{kw_sents[k]:>7}{len(kw_docs[k]):>7}"
              f"{L['trainer']:>9}{L['vet']:>6}{L['unknown']:>9}")

    print(f"\n(b) 연령어 x 주제 교차 (Top {args.top})")
    focus = ["배변", "분리불안", "짖음", "하우스", "산책", "입질", "(미분류)"]
    print(f"    {'연령어':<12}" + "".join(f"{t:>9}" for t in focus))
    for k in top:
        print(f"    {k:<12}" + "".join(f"{kw_topic[k][t]:>9}" for t in focus))

    print(f"\n(c) 주제별 술어 tail 대조 — 연령어 있음 vs 연령어 없음 (처치 분화 원자료, 판정 아님)")
    for tp in ["짖음", "배변", "분리불안", "산책"]:
        with_top = kw_pred_with[tp].most_common(5)
        without_top = kw_pred_without_topic[tp].most_common(5)
        print(f"    [{tp}] 연령어 있음: {with_top}")
        print(f"    [{tp}] 연령어 없음(대조군): {without_top}")

    print(f"\n-> {outdir}/sample_agegroup_v1.csv  ({len(sample)}행) 라벨 열 전부 공란")
    print(f"-> {outdir}/sample_agegroup_numeric_v1.csv  (숫자 표기 예시 {len(numeric_examples)}행)")


if __name__ == "__main__":
    main()
