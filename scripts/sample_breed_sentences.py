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
                           url=pick(d, key_url), src=path.name)
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
                           url=pick(d, key_url), src=path.name)
        else:
            yield dict(doc_id=path.stem, title="", body=raw, url="", src=path.name)


# ---------------------------------------------------------------- 처리

SENT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


def split_sentences(text: str):
    out = []
    for s in SENT_RE.split(text or ""):
        s = " ".join(s.split())
        if 10 <= len(s) <= 400:
            out.append(s)
    return out


def find_terms(sent: str, terms):
    return [t for t in terms if t in sent]


def tag_topics(sent: str):
    hits = []
    for name, spec in TOPICS.items():
        if any(k in sent for k in spec["kw"]):
            hits.append(name)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="./scrapper/data",
                    help="크롤 결과 폴더 (예: C:/backup/dogtraining_0821/scrapper)")
    ap.add_argument("--out", default="./breed_factcheck")
    ap.add_argument("--per-topic", type=int, default=5, help="주제별 무작위 표본 수")
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

    for d in docs:
        sents = split_sentences(f"{d['title']}\n{d['body']}")
        total_sents += len(sents)
        doc_topics = set()

        for i, s in enumerate(sents):
            topics = tag_topics(s)
            doc_topics.update(topics)
            cov_sents.update(topics)

            breeds = find_terms(s, BREEDS)
            traits = find_terms(s, TRAITS)
            if not (breeds or traits):
                continue
            hit_sents += 1
            breed_docs.add(d["doc_id"])

            row = dict(
                doc_id=d["doc_id"], url=d["url"],
                주제="|".join(topics) or "(미분류)",
                견종어="|".join(breeds), 형질어="|".join(traits),
                이전문장=sents[i - 1] if i else "",
                문장=s,
                다음문장=sents[i + 1] if i + 1 < len(sents) else "",
                조건성="", 술어원문="", 메모="",
            )
            for t in (topics or ["(미분류)"]):
                by_topic[t].append(row)
            if any(m in s for m in COND_MARKERS):
                signal_rows.append({**row,
                                    "신호어": "|".join(m for m in COND_MARKERS if m in s)})

        cov_docs.update(doc_topics)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1) 무작위 표본 — 비율 측정용. 신호어 가중 없음.
    sample = []
    for topic, rows in by_topic.items():
        uniq = {r["문장"]: r for r in rows}.values()
        sample.extend(random.sample(list(uniq), min(args.per_topic, len(uniq))))

    cols = ["doc_id", "주제", "견종어", "형질어", "이전문장", "문장", "다음문장",
            "조건성", "술어원문", "메모", "url"]
    with open(outdir / "sample_random.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sample)

    # 2) 신호어 풀 — 술어 형태 수집용
    with open(outdir / "pool_signal.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols + ["신호어"], extrasaction="ignore")
        w.writeheader()
        w.writerows(signal_rows)

    # 3) 커버리지 실측
    print(f"\n문서 {len(docs)}  문장 {total_sents}  "
          f"견종·형질 언급 문장 {hit_sents} ({hit_sents/max(total_sents,1)*100:.1f}%)  "
          f"언급 문서 {len(breed_docs)}")
    print(f"\n{'주제':<10}{'tier':<8}{'문서':>6}{'문장':>7}{'견종언급':>9}{'표본':>6}")
    print("-" * 48)
    for name, spec in TOPICS.items():
        print(f"{name:<10}{spec['tier']:<8}{cov_docs[name]:>6}{cov_sents[name]:>7}"
              f"{len(by_topic.get(name, [])):>9}"
              f"{sum(1 for r in sample if name in r['주제']):>6}")
    print(f"\n-> {outdir}/sample_random.csv  ({len(sample)}행) 여기에만 조건성 라벨")
    print(f"-> {outdir}/pool_signal.csv    ({len(signal_rows)}행) 술어원문만 수집")
    print("\n※ 라벨 달기 전에 판정선 먼저 못박을 것: 조건형 20% 미만이면 견종 강등")


if __name__ == "__main__":
    main()
