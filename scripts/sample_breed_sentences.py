#!/usr/bin/env python3
"""
견종·형질 언급 문장 표본 추출기 (Q-B 팩트체크용)

목적
  크롤 풀(베럴독 551 + AMC 189)에서 견종/형질이 언급된 문장을 뽑아
  두 가지 라벨을 사람이 달 수 있는 형태로 내보낸다.
    라벨1 조건성  : 조건형 / 열거형   -> "견종이 훈련법을 실제로 가르는가"
    라벨2 술어원문: 원문 표현 그대로 -> extraction-prompt-v3 엣지 타입 귀납

두 개의 출력을 분리한다 (섞으면 비율 측정이 오염됨)
  1) sample_random.csv  : 주제별 무작위(seed 고정). ★ 비율 측정은 이것만 사용
  2) pool_signal.csv    : 조건 신호어("~해야","~때문에")를 포함한 문장 전량.
                          술어 형태 수집용. 비율 계산에 절대 쓰지 말 것.

사용
  python sample_breed_sentences.py --inspect              # 먼저 이걸로 포맷 확인
  python sample_breed_sentences.py --root <크롤폴더> --per-topic 5
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

# 그래프에 실재하는 19개 + 코퍼스에 나올 법한 확장
BREEDS = [
    "골든리트리버", "골든 리트리버", "리트리버", "래브라도", "라브라도",
    "말티즈", "몰티즈", "말티푸", "비글", "비숑프리제", "비숑",
    "슈나우저", "스탠더드푸들", "토이푸들", "푸들", "스피츠",
    "시바견", "시바", "시츄", "요크셔테리어", "요크셔", "치와와",
    "코카스파니엘", "코카 스파니엘", "포메라니안", "포메",
    "진돗개", "웰시코기", "코기", "닥스훈트", "보더콜리", "퍼그",
    "프렌치불독", "불독", "시베리안허스키", "허스키", "사모예드",
    "도베르만", "저먼셰퍼드", "셰퍼드", "잭러셀테리어", "미니핀",
    "파피용", "페키니즈", "달마시안", "비숑프리제",
]

# ★ 형질어를 반드시 같이 잡는다.
#   그래프의 견종 19개에 '귓털이 많은 견종', '소형견', '집개'가 섞여 있었다.
#   조건이 견종명이 아니라 형질에 걸려 있으면 v3 술어 설계가 통째로 달라진다.
TRAITS = [
    "소형견", "중형견", "대형견", "초소형견", "집개", "믹스견",
    "이중모", "단모종", "장모종", "곱슬", "귓털", "귀털",
    "처진 귀", "접힌 귀", "선 귀",
    "단두종", "주둥이가 짧", "코가 짧",
    "사냥견", "목양견", "경비견", "테리어",
    "활동량이 많은", "예민한 견종", "겁이 많은 견종",
]

# 주제 10축 = 커리큘럼 8 + 문제행동 2
# tier: 예상 견종 민감도. 측정 결과를 이 층별로 갈라 봐야 결론이 선다.
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

# lens = 문서 출처. 형질-only 비율이 코퍼스 구성비(훈련 551 대 질환 189)의 반영일 수
# 있으므로, 훈련 문서에서 잰 비율로 질환 스키마를 결정하지 않기 위해 분리한다.
# 퍼그 단두종·달마시안 요로결석 같은 유전 질환은 체급으로 대체 불가하다.
LENS_BY_AUTHOR = {"yoonsu3454": "trainer", "africaamc": "vet"}

# blog_raw_rescue는 author가 yoonsu3454지만 별도 필터로 건져낸 질환 중심 세트라
# 편집 관점이 훈련사 글과 같다고 볼 수 없다. 추측하지 않고 unknown으로 둔다.
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
    """포맷을 모르므로 방어적으로 읽는다. 안 맞으면 --inspect 결과 보고 여기만 고칠 것.

    2026-08-22 실측 수정: root 전체를 rglob하면 blog_list*/의 목록 파일(posts_list,
    excluded, posts_training)까지 문서로 잡혀 6431건이 된다. 이 파일들은 본문 없이
    제목만 있어서 hit 문장 1539건 중 194건(12.6%)이 본문이 아닌 제목이 되고, 제목은
    구조상 열거형이라 조건성 비율이 왜곡된다. 본문을 담은 파일만 읽도록 좁힌다.
    (key_body의 'text'는 이미 실제 키와 일치하므로 키는 고치지 않았다.)
    """
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
            yield dict(doc_id=path.stem, title="", body=raw, url="", src=path.name, src_path=rel)


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
    """(문장, is_title) 목록.

    기존에는 f"{title}
{body}"를 통째로 넣었다. SENT_RE가 개행에서도 끊으므로
    제목과 본문을 따로 분할해 이어붙인 것과 문장 목록이 동일하다. 다만 제목은
    구조상 열거형("말티즈 슬개골탈구 증상")이라 조건성 비율을 열거형 쪽으로
    밀기 때문에, 집계 때 분리할 수 있도록 유래를 기록한다.
    """
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


def stratify(rows, quota, rng):
    """lens별로 균등 배분해 뽑는다. 한쪽 lens가 표본을 독점하지 못하게 한다.

    균등 배분이 원칙이되, 어떤 lens의 모집단이 배정량보다 적으면 남은 몫을 다른
    lens로 넘긴다(총 quota를 채우기 위해). 배분은 결정적이고 seed에만 의존한다.
    """
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
    ap.add_argument("--root", default="./scrapper/data",
                    help="크롤 결과 폴더 (예: C:/backup/dogtraining_0821/scrapper)")
    ap.add_argument("--out", default="./breed_factcheck")
    ap.add_argument("--per-topic", type=int, default=5, help="주제별 무작위 표본 수")
    ap.add_argument("--strong-per-topic", type=int, default=None,
                    help="tier=강함 주제의 표본 수 (미지정 시 --per-topic과 동일). "
                         "37행에 20%% 판정선을 긋는 것은 문장 1개로 뒤집히므로 키운다")
    ap.add_argument("--suffix", default="",
                    help="출력 파일명 접미사 (예: _v2). 기존 CSV를 덮어쓰지 않기 위함")
    ap.add_argument("--pattern", default=CORPUS_GLOB,
                    help=f"읽을 파일 glob (기본 {CORPUS_GLOB}). 목록 파일 혼입 방지용")
    ap.add_argument("--inspect", action="store_true", help="포맷·건수만 보고 종료")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        sys.exit(f"경로 없음: {root}")

    docs = list(iter_docs(root, args.pattern))
    if args.inspect:
        print(f"문서 {len(docs)}건")
        for d in docs[:3]:
            print(f"\n  doc_id={d['doc_id']}  src={d['src']}")
            print(f"  title={d['title'][:60]}")
            print(f"  body={d['body'][:160]}...")
            print(f"  body_len={len(d['body'])}")
        empty = sum(1 for d in docs if len(d["body"]) < 100)
        print(f"\n본문 100자 미만 {empty}건 — 이 값이 크면 iter_docs의 key_body를 고칠 것")
        return

    random.seed(SEED)
    by_topic = defaultdict(list)     # 무작위 표본 모집단
    signal_rows = []                 # 조건 신호어 포함 전량
    cov_docs = Counter()             # 주제별 문서 수 (커버리지 실측)
    cov_sents = Counter()
    breed_docs, total_sents, hit_sents = set(), 0, 0

    pop_rows = []                    # 견종·형질 hit 문장 전량 (집계용)
    doc_lens = {}                    # doc_id -> lens
    hits_per_doc = Counter()

    for d in docs:
        lens = lens_of(d["doc_id"], d.get("src_path", ""))
        doc_lens[d["doc_id"]] = lens
        tagged = split_tagged(d["title"], d["body"])
        sents = [s for s, _ in tagged]
        total_sents += len(sents)
        doc_topics = set()

        for i, (s, is_title) in enumerate(tagged):
            topics = tag_topics(s)
            doc_topics.update(topics)
            cov_sents.update(topics)

            breeds = find_terms(s, BREEDS)
            traits = find_terms(s, TRAITS)
            if not (breeds or traits):
                continue
            hit_sents += 1
            breed_docs.add(d["doc_id"])
            hits_per_doc[d["doc_id"]] += 1

            row = dict(
                doc_id=d["doc_id"], url=d["url"], lens=lens,
                is_title="Y" if is_title else "",
                주제="|".join(topics) or "(미분류)",
                견종어="|".join(breeds), 형질어="|".join(traits),
                이전문장=sents[i - 1] if i else "",
                문장=s,
                다음문장=sents[i + 1] if i + 1 < len(sents) else "",
                조건성="", 술어원문="", 메모="",
            )
            pop_rows.append(row)
            for t in (topics or ["(미분류)"]):
                by_topic[t].append(row)
            if any(m in s for m in COND_MARKERS):
                signal_rows.append({**row,
                                    "신호어": "|".join(m for m in COND_MARKERS if m in s)})

        cov_docs.update(doc_topics)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1) 무작위 표본 — 비율 측정용. 신호어 가중 없음.
    #    lens x 주제로 층화한다. 코퍼스가 훈련 551 대 질환 189이라 층화하지 않으면
    #    trainer가 표본을 독점하고, 그 비율로 질환 스키마를 정하게 된다.
    strong_quota = args.strong_per_topic or args.per_topic
    sample, quota_used = [], {}
    for topic in sorted(by_topic):
        uniq = list({r["문장"]: r for r in by_topic[topic]}.values())
        tier = TOPICS.get(topic, {}).get("tier", "")
        quota = strong_quota if tier == "강함" else args.per_topic
        quota_used[topic] = quota
        sample.extend(stratify(uniq, quota, random))

    # 다주제 문장(예: 주제="분리불안|짖음")은 by_topic에 두 번 들어가므로 표본에도
    # 중복으로 뽑힐 수 있다. 중복은 조건성 비율에서 이중 계산되어 20% 판정선을
    # 흔든다. 주제 열이 이미 다주제를 모두 담고 있어 정보 손실 없이 합칠 수 있다.
    _seen = set()
    sample = [r for r in sample
              if not (r["문장"] in _seen or _seen.add(r["문장"]))]

    cols = ["doc_id", "lens", "is_title", "주제", "견종어", "형질어",
            "이전문장", "문장", "다음문장", "조건성", "술어원문", "메모", "url"]
    with open(outdir / f"sample_random{args.suffix}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sample)

    # 2) 신호어 풀 — 술어 형태 수집용
    with open(outdir / f"pool_signal{args.suffix}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols + ["신호어"], extrasaction="ignore")
        w.writeheader()
        w.writerows(signal_rows)

    # 3) 커버리지 실측
    def trait_only(rows):
        n = len(rows)
        t = sum(1 for r in rows if r["형질어"] and not r["견종어"])
        return t, n, (t / n * 100 if n else 0.0)

    print(f"\n문서 {len(docs)}  문장 {total_sents}  "
          f"견종·형질 언급 문장 {hit_sents} ({hit_sents/max(total_sents,1)*100:.1f}%)  "
          f"언급 문서 {len(breed_docs)}")
    print(f"\n{'주제':<10}{'tier':<8}{'문서':>6}{'문장':>7}{'견종언급':>9}{'표본':>6}")
    print("-" * 48)
    for name, spec in TOPICS.items():
        print(f"{name:<10}{spec['tier']:<8}{cov_docs[name]:>6}{cov_sents[name]:>7}"
              f"{len(by_topic.get(name, [])):>9}"
              f"{sum(1 for r in sample if name in r['주제']):>6}")

    # (a) lens별 형질-only 비율 — 코퍼스 구성비의 반영인지 확인용
    print(f"\n[a] lens별 형질-only  {'lens':<10}{'문서':>6}{'hit문장':>8}"
          f"{'형질only':>9}{'비율':>8}{'표본':>6}{'표본형질only':>13}")
    print("-" * 62)
    for L in ("trainer", "vet", "unknown"):
        pr = [r for r in pop_rows if r["lens"] == L]
        sr = [r for r in sample if r["lens"] == L]
        t, n, pct = trait_only(pr)
        st, sn, spct = trait_only(sr)
        nd = sum(1 for v in doc_lens.values() if v == L)
        print(f"{'':<20}{L:<10}{nd:>6}{n:>8}{t:>9}{pct:>7.1f}%{sn:>6}"
              f"{(str(st)+'/'+str(sn)) if sn else '-':>13}")

    # (b) 견종 언급 '문서' 수와 집중도 — 여러 글에 퍼진 건지 몇 글에 몰린 건지
    print(f"\n[b] 견종·형질 언급 문서 {len(breed_docs)}/{len(docs)} "
          f"({len(breed_docs)/max(len(docs),1)*100:.1f}%)")
    top = hits_per_doc.most_common()
    if top:
        cum = 0
        for share in (0.25, 0.50):
            need = 0
            cum = 0
            for _, c in top:
                cum += c
                need += 1
                if cum >= hit_sents * share:
                    break
            print(f"    상위 {need}개 문서가 hit 문장의 {share*100:.0f}% 차지")
        print(f"    문서당 hit 문장 최대 {top[0][1]}  중앙값 "
              f"{sorted(hits_per_doc.values())[len(hits_per_doc)//2]}")

    # (c) 강함 tier 3주제 — 판정선에 직접 쓰인다
    strong = [n for n, s in TOPICS.items() if s["tier"] == "강함"]
    tot = sum(len(by_topic.get(n, [])) for n in strong)
    print(f"\n[c] 강함 tier {'+'.join(strong)}")
    for n in strong:
        print(f"    {n:<8} 문서 {cov_docs[n]:>4}  문장 {cov_sents[n]:>6}  "
              f"견종언급 {len(by_topic.get(n, [])):>4}")
    print(f"    견종언급 합계 = {tot}   (판정선: 50건 미만이면 크롤 확대 없이 종결)")

    # is_title 규모
    ti = sum(1 for r in pop_rows if r["is_title"])
    ts = sum(1 for r in sample if r["is_title"])
    print(f"\n[d] 제목 유래 문장: 모집단 {ti}/{len(pop_rows)} "
          f"({ti/max(len(pop_rows),1)*100:.1f}%)  표본 {ts}/{len(sample)}")

    print(f"\n-> {outdir}/sample_random{args.suffix}.csv  ({len(sample)}행) 여기에만 조건성 라벨")
    print(f"-> {outdir}/pool_signal{args.suffix}.csv    ({len(signal_rows)}행) 술어원문만 수집")
    print("\n※ 라벨 달기 전에 판정선 먼저 못박을 것: 조건형 20% 미만이면 견종 강등")



if __name__ == "__main__":
    main()
