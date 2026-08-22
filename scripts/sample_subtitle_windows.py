#!/usr/bin/env python3
"""
자막 코퍼스 견종어 문맥창 추출기 (유튜브 교차검증용, Q-B 팩트체크 후속)

목적
  블로그 크롤 풀에서 잰 "견종은 빈도 관계만, 처치 관계 0건" 결론을 매체가 다른
  유튜브 자막(../scrapper/data/subs_crossval/, 읽기 전용)으로 교차검증한다.

★ 채널을 섞지 않는다
  그룹 A = 강형욱의 보듬TV 19편   — 기존 코퍼스와 같은 채널·화자. 확장분이지
                                     독립 검증이 아니다.
  그룹 B = 이찬종의 이삭TV 19 + 설채현의 놀로와 8 = 27편 — 신규 채널, 진짜 교차검증.
  모든 집계는 A/B로 분리해서 낸다. 어디서도 합산하지 않는다.

★ ASR 대응
  그룹 B는 전부 ASR이라 문장부호가 없어 sample_breed_sentences.py의 문장분할이
  작동하지 않는다. 이 스크립트는 그 파일을 수정하지 않고 사전(BREEDS/TRAITS/TOPICS)과
  문장분할 정규식만 import해서, 견종어 등장 위치 기준 앞/뒤 N어절 창을 새로 추출한다.
  그룹 A(수동자막, 문장부호 있음)는 문장분할과 윈도우 두 방식을 병행하고 행마다
  `추출방식` 열로 표시한다.

★ 오인식 후보는 목록만 낸다. 사전에 넣지 않는다. 라벨은 사람이 단다.

사용
  python scripts/sample_subtitle_windows.py \
      --root ../scrapper/data/subs_crossval --out data/subtitle_factcheck
"""

import argparse
import bisect
import csv
import html
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SEED = 20260822
WINDOW_N = 30  # 앞/뒤 어절 수

# 기존 스크립트를 그대로 import (수정 금지, 사전 재사용으로 두 코퍼스 간 정합성 유지)
sys.path.insert(0, str(Path(__file__).parent))
import sample_breed_sentences as _breed
import sample_env_sentences as _env

BREEDS = _breed.BREEDS
TRAITS = _breed.TRAITS
TOPICS = _breed.TOPICS
SENT_RE = _breed.SENT_RE
ENV_ALL = _env.ENV_ALL
ENV_GROUP = _env.ENV_GROUP

CHANNEL_GROUP = {
    "강형욱의 보듬TV": "A",
    "이찬종의 이삭TV": "B",
    "설채현의 놀로와": "B",
}

# 비지식 서술 신호 (표시만 한다. 제거하지 않는다 — 판정은 사람이 한다)
NON_KNOWLEDGE_MARKERS = {
    "인사/구독유도": ["안녕하세요", "구독", "좋아요"],
    "사연소개": ["사연"],
    "광고협찬": ["협찬", "광고"],
}

# OOV 후보 필터 (지시받은 값 그대로 — 임의 추가 없음)
OOV_MIN_FREQ = 3
OOV_MIN_LEN, OOV_MAX_LEN = 2, 6
OOV_CONTEXT_WORDS = ["강아지", "훈련", "아이"]
OOV_CONTEXT_SPAN = 5  # 전후 몇 토큰 안에서 문맥어를 찾을지
# 빈도 집계 전용 정규화. 사전 확장이 아니라 조사 제거로, 원본 토큰은 그대로 보존한다.
_PARTICLE_SUFFIXES = ["에서", "으로", "이나", "라는", "라고", "이라",
                       "은", "는", "이", "가", "을", "를", "도", "만",
                       "의", "와", "과", "로", "다", "요", "죠", "네", "고"]


# ------------------------------------------------------------ vtt 파서

TS_RE = re.compile(r"(\d\d:\d\d:\d\d\.\d\d\d)\s*-->")
TAG_RE = re.compile(r"<[^>]+>")


def parse_vtt(path: Path):
    """cue 목록 [(시작 타임스탬프, 정제 텍스트)]. 태그·헤더 제거, HTML 엔티티 복원."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", raw)
    cues = []
    for b in blocks:
        ts = None
        content_lines = []
        for ln in b.splitlines():
            m = TS_RE.match(ln.strip())
            if m:
                ts = m.group(1)
                continue
            s = ln.strip()
            if not s or s.upper().startswith("WEBVTT") or s.startswith("Kind:") or s.startswith("Language:"):
                continue
            if re.match(r"^\d+$", s):
                continue
            content_lines.append(ln)
        if ts is None:
            continue
        merged = " ".join(content_lines)
        clean = html.unescape(TAG_RE.sub("", merged))
        clean = " ".join(clean.split())
        cues.append((ts, clean))
    return cues


def diff_words(cues):
    """(타임스탬프, 단어) 목록. YouTube 롤업 자막은 캡션이 누적 성장하므로,
    직전 cue 텍스트의 접두어인 부분은 이미 나온 단어라 건너뛰고 새로 늘어난
    부분만 취한다. 수동자막은 cue가 대개 서로 접두어 관계가 아니므로 매 cue가
    통째로 새 단어로 처리된다 — 같은 함수로 두 자막 타입을 함께 다룬다."""
    out = []
    prev = ""
    for ts, clean in cues:
        if not clean or clean == prev:
            continue
        new_part = clean[len(prev):].strip() if prev and clean.startswith(prev) else clean
        if new_part:
            for w in new_part.split():
                out.append((ts, w))
        prev = clean
    return out


def cue_text_for_sentences(cues):
    """문장분할용 원문 재구성. cue 경계를 개행으로 보존해 SENT_RE가 cue 경계에서도
    끊기게 한다 (기존 스크립트가 title/body를 개행으로 잇는 것과 같은 방식)."""
    parts, offsets = [], []
    pos = 0
    for ts, clean in cues:
        if not clean:
            continue
        offsets.append((pos, ts))
        parts.append(clean)
        pos += len(clean) + 1  # + "\n"
    return "\n".join(parts), offsets


def ts_at_offset(offsets, char_idx):
    """offsets: [(누적 char 시작 위치, ts)] 정렬됨. char_idx가 속한 cue의 ts."""
    if not offsets:
        return None
    positions = [p for p, _ in offsets]
    i = bisect.bisect_right(positions, char_idx) - 1
    i = max(0, min(i, len(offsets) - 1))
    return offsets[i][1]


def split_sentences_with_ts(big_text, offsets):
    """SENT_RE로 문장 분할하되 각 문장의 시작 offset으로 타임스탬프를 붙인다.
    길이 필터(10~400자)는 sample_breed_sentences.split_sentences와 동일하게 둔다."""
    out = []
    last = 0
    spans = []
    for m in SENT_RE.finditer(big_text):
        spans.append((last, m.start()))
        last = m.end()
    spans.append((last, len(big_text)))
    for start, end in spans:
        raw = big_text[start:end]
        s = " ".join(raw.split())
        if 10 <= len(s) <= 400:
            out.append((s, ts_at_offset(offsets, start)))
    return out


# ------------------------------------------------------------ 사전 매칭 + 윈도우

def build_offsets(tokens):
    offsets, pos = [], 0
    for t in tokens:
        offsets.append(pos)
        pos += len(t) + 1
    return offsets


def find_dict_occurrences(tokens, token_ts, terms):
    """terms(BREEDS/TRAITS/ENV_ALL 등) 부분문자열 매칭 — 기존 스크립트의
    `find_terms`(문장 내 `t in sent`)와 동일한 방식을 토큰 스트림 전체에 적용."""
    full = " ".join(tokens)
    offsets = build_offsets(tokens)
    results = []
    for term in terms:
        start = 0
        while True:
            idx = full.find(term, start)
            if idx == -1:
                break
            start_tok = bisect.bisect_right(offsets, idx) - 1
            end_tok = bisect.bisect_right(offsets, idx + len(term) - 1) - 1
            start_tok = max(0, start_tok)
            end_tok = max(start_tok, end_tok)
            ts = token_ts[start_tok] if start_tok < len(token_ts) else None
            results.append(dict(term=term, start_tok=start_tok, end_tok=end_tok, timestamp=ts))
            start = idx + len(term)
    return results


def window_text(tokens, start_tok, end_tok, n=WINDOW_N):
    before = tokens[max(0, start_tok - n):start_tok]
    hit = tokens[start_tok:end_tok + 1]
    after = tokens[end_tok + 1:end_tok + 1 + n]
    return " ".join(before) + " 『" + " ".join(hit) + "』 " + " ".join(after)


def flag_non_knowledge(window_str):
    hits = []
    for label, markers in NON_KNOWLEDGE_MARKERS.items():
        if any(m in window_str for m in markers):
            hits.append(label)
    return "|".join(hits)


def tag_topics(text):
    hits = []
    for name, spec in TOPICS.items():
        if any(k in text for k in spec["kw"]):
            hits.append(name)
    return hits


# ------------------------------------------------------------ 로더

def load_manifest(root: Path):
    rows = []
    with open(root / "manifest.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            group = CHANNEL_GROUP.get(d["channel"])
            if group is None:
                print(f"  [경고] 채널 매핑 없음, 건너뜀: {d['channel']} ({d['video_id']})", file=sys.stderr)
                continue
            d["group"] = group
            rows.append(d)
    return rows


def find_vtt(root: Path, video_id: str):
    p = root / "raw" / f"{video_id}.ko.vtt"
    if p.exists():
        return p
    cands = sorted((root / "raw").glob(f"{video_id}.ko-*.vtt"))
    return cands[0] if cands else None


# ------------------------------------------------------------ OOV 후보

def strip_particle(tok):
    for suf in sorted(_PARTICLE_SUFFIXES, key=len, reverse=True):
        if tok.endswith(suf) and len(tok) > len(suf) + 1:
            return tok[: -len(suf)]
    return tok


def is_hangul_run(s):
    return bool(s) and all("\uac00" <= ch <= "\ud7a3" for ch in s)


def levenshtein(a, b):
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def nearest_breed(norm_tok, breed_pool):
    """\ud1a0\ud070\uc774 \uc54c\ub824\uc9c4 \uacac\uc885\uba85\uacfc \uc74c\uc808 \uae38\uc774 \ub300\ube44 \ud3b8\uc9d1\uac70\ub9ac\uac00 \uac00\uae4c\uc6b0\uba74 \ud45c\uc2dc\ub9cc \ud55c\ub2e4
    (\ud544\ud130 \uc544\ub2d8, \uc815\ub82c\u00b7\uac80\ud1a0 \ubcf4\uc870\uc6a9 \u2014 \uc0ac\uc804\uc5d0 \ub123\uc9c0 \uc54a\uc73c\uba70 \ucc44\ud0dd \uc5ec\ubd80\ub97c \uacb0\uc815\ud558\uc9c0 \uc54a\ub294\ub2e4).
    \uae38\uc774 2~3 \ud1a0\ud070\uc740 \ud3b8\uc9d1\uac70\ub9ac 2\ub3c4 \uc0ac\uc2e4\uc0c1 \uc544\ubb34 \ub2e8\uc5b4\ub098 \uac78\ub9ac\ubbc0\ub85c 1\ub85c, 4\uc790 \uc774\uc0c1\uc740 2\ub85c \ub454\ub2e4."""
    limit = 1 if len(norm_tok) <= 3 else 2
    best, best_d = "", limit + 1
    for b in breed_pool:
        if abs(len(b) - len(norm_tok)) > limit:
            continue
        d = levenshtein(norm_tok, b)
        if d < best_d:
            best, best_d = b, d
    return (best, best_d) if best_d <= limit else ("", None)


def collect_oov_candidates(video_records):
    """video_records: [(video_id, channel, group, tokens)]
    사전(BREEDS+TRAITS)에 없으면서 반복되는 견종명처럼 보이는 토큰 후보.
    후보만 낸다 — 사전에 넣지 않는다."""
    known = set(BREEDS) | set(TRAITS)

    def in_dict(tok):
        return any(k in tok or tok in k for k in known)

    norm_freq = Counter()
    norm_examples = defaultdict(list)   # norm -> [(video_id, group, raw_tok, context_window)] (표시용, 최대 3개)
    norm_raw_forms = defaultdict(Counter)
    norm_videos = defaultdict(set)      # norm -> {video_id, ...} — 등장영상수는 이걸로 셈 (예시 cap과 무관)
    norm_groups = defaultdict(set)

    for video_id, channel, group, tokens in video_records:
        for i, tok in enumerate(tokens):
            if in_dict(tok):
                continue
            norm = strip_particle(tok)
            if not (OOV_MIN_LEN <= len(norm) <= OOV_MAX_LEN):
                continue
            if not is_hangul_run(norm):
                continue
            ctx_lo, ctx_hi = max(0, i - OOV_CONTEXT_SPAN), min(len(tokens), i + OOV_CONTEXT_SPAN + 1)
            ctx = tokens[ctx_lo:ctx_hi]
            near = [w for w in OOV_CONTEXT_WORDS if any(w in c for c in ctx)]
            if not near:
                continue
            norm_freq[norm] += 1
            norm_raw_forms[norm][tok] += 1
            norm_videos[norm].add(video_id)
            norm_groups[norm].add(group)
            if len(norm_examples[norm]) < 3:
                norm_examples[norm].append((video_id, group, tok, " ".join(ctx)))

    breed_pool = sorted(set(BREEDS))
    candidates = []
    for norm, freq in norm_freq.items():
        if freq < OOV_MIN_FREQ:
            continue
        near_breed, dist = nearest_breed(norm, breed_pool)
        candidates.append(dict(
            정규화토큰=norm,
            빈도=freq,
            원형들="|".join(f"{t}({c})" for t, c in norm_raw_forms[norm].most_common()),
            등장영상수=len(norm_videos[norm]),
            그룹="|".join(sorted(norm_groups[norm])),
            유사견종후보=near_breed,
            편집거리=dist if dist is not None else "",
            예시1=norm_examples[norm][0][3] if norm_examples[norm] else "",
        ))
    # 정렬은 검토 우선순위 보조일 뿐 채택 여부 판단이 아니다: 유사견종후보 있는 것 먼저, 빈도순.
    candidates.sort(key=lambda r: (r["유사견종후보"] == "", -r["빈도"]))
    return candidates


# ------------------------------------------------------------ 표본 층화

def stratify_by_channel_topic(rows, quota, rng):
    """채널별로 먼저 배분한 뒤 채널 안에서 주제별로 균등 배분. 모집단 부족분은
    남은 채널/주제로 이월한다 (기존 스크립트의 stratify()와 같은 원칙)."""
    by_channel = defaultdict(list)
    for r in rows:
        by_channel[r["channel"]].append(r)
    channels = sorted(by_channel)
    caps = {c: len(by_channel[c]) for c in channels}
    alloc = {c: 0 for c in channels}
    remaining = min(quota, sum(caps.values()))
    while remaining > 0:
        avail = [c for c in channels if alloc[c] < caps[c]]
        if not avail:
            break
        share = max(1, remaining // len(avail))
        for c in avail:
            if remaining <= 0:
                break
            take = min(share, caps[c] - alloc[c], remaining)
            alloc[c] += take
            remaining -= take

    picked = []
    for c in channels:
        if not alloc[c]:
            continue
        pool = by_channel[c]
        by_topic = defaultdict(list)
        for r in pool:
            for t in (r["주제"].split("|") or ["(미분류)"]):
                by_topic[t].append(r)
        topics = sorted(by_topic)
        n_topics = max(1, len(topics))
        base = alloc[c] // n_topics
        rest = alloc[c] - base * n_topics
        chosen, seen_txt = [], set()
        for j, t in enumerate(topics):
            take_n = base + (1 if j < rest else 0)
            uniq = list({r["문맥창"]: r for r in by_topic[t]}.values())
            take_n = min(take_n, len(uniq))
            chosen.extend(rng.sample(uniq, take_n) if take_n else [])
        # quota 못 채웠으면 채널 전체 유니크 풀에서 보충
        if len(chosen) < alloc[c]:
            uniq_all = list({r["문맥창"]: r for r in pool}.values())
            remain_pool = [r for r in uniq_all if r["문맥창"] not in {x["문맥창"] for x in chosen}]
            need = alloc[c] - len(chosen)
            if remain_pool:
                chosen.extend(rng.sample(remain_pool, min(need, len(remain_pool))))
        picked.extend(chosen)
    return picked


# ------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="../scrapper/data/subs_crossval",
                    help="읽기 전용. 자막 원문 저장소 밖 (하드 제약 1)")
    ap.add_argument("--out", default="data/subtitle_factcheck")
    ap.add_argument("--group-b-n", type=int, default=30)
    ap.add_argument("--group-a-n", type=int, default=10)
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        sys.exit(f"경로 없음: {root} (읽기 전용 대상이 없으면 진행 불가)")

    manifest = load_manifest(root)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    # ---- 비디오별 파싱 ----
    per_video = {}   # video_id -> dict(channel, group, tokens, token_ts, cues)
    for m in manifest:
        vid = m["video_id"]
        vtt = find_vtt(root, vid)
        if vtt is None:
            print(f"  [경고] vtt 없음, 건너뜀: {vid}", file=sys.stderr)
            continue
        cues = parse_vtt(vtt)
        pairs = diff_words(cues)
        tokens = [w for _, w in pairs]
        token_ts = [t for t, _ in pairs]
        per_video[vid] = dict(channel=m["channel"], group=m["group"], title=m["title"],
                               tokens=tokens, token_ts=token_ts, cues=cues)

    # ---- (사전 매칭) 그룹별 견종·형질 카운트 ----
    dict_rows_by_group = defaultdict(list)   # group -> list of row dict (윈도우 방식)
    sent_rows_by_group = defaultdict(list)   # group -> list of row dict (문장분할 방식, A만)
    breed_term_hits = defaultdict(Counter)   # group -> Counter(term)
    breed_videos_hit = defaultdict(set)      # group -> set(video_id) with >=1 hit
    env_term_hits = defaultdict(Counter)
    env_videos_hit = defaultdict(set)

    for vid, v in per_video.items():
        group, channel, tokens, token_ts = v["group"], v["channel"], v["tokens"], v["token_ts"]
        if not tokens:
            continue

        # 견종/형질 사전 매칭 -> 윈도우
        occ = find_dict_occurrences(tokens, token_ts, BREEDS + TRAITS)
        if occ:
            breed_videos_hit[group].add(vid)
        for o in occ:
            breed_term_hits[group][o["term"]] += 1
            win = window_text(tokens, o["start_tok"], o["end_tok"])
            row = dict(group=group, channel=channel, video_id=vid,
                       timestamp=o["timestamp"] or "", 견종어=o["term"],
                       문맥창=win, non_knowledge=flag_non_knowledge(win),
                       추출방식="윈도우",
                       주제="|".join(tag_topics(win)) or "(미분류)",
                       관계유형="", 메모="")
            dict_rows_by_group[group].append(row)

        # 환경어 사전 매칭 (집계 전용, 표본 CSV 대상 아님)
        env_occ = find_dict_occurrences(tokens, token_ts, ENV_ALL)
        if env_occ:
            env_videos_hit[group].add(vid)
        for o in env_occ:
            env_term_hits[group][o["term"]] += 1

        # 그룹 A: 문장분할 병행
        if group == "A":
            big_text, offsets = cue_text_for_sentences(v["cues"])
            sents = split_sentences_with_ts(big_text, offsets)
            for s, ts in sents:
                found = [t for t in (BREEDS + TRAITS) if t in s]
                if not found:
                    continue
                row = dict(group=group, channel=channel, video_id=vid,
                           timestamp=ts or "", 견종어="|".join(found),
                           문맥창=s, non_knowledge=flag_non_knowledge(s),
                           추출방식="문장분할",
                           주제="|".join(tag_topics(s)) or "(미분류)",
                           관계유형="", 메모="")
                sent_rows_by_group[group].append(row)

    # ---- OOV 후보 ----
    video_records = [(vid, v["channel"], v["group"], v["tokens"]) for vid, v in per_video.items()]
    oov = collect_oov_candidates(video_records)
    with open(outdir / "oov_candidates.csv", "w", newline="", encoding="utf-8-sig") as f:
        cols = ["정규화토큰", "빈도", "원형들", "등장영상수", "그룹", "유사견종후보", "편집거리", "예시1"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(oov)

    # ---- 그룹 A/B 전체 모집단(윈도우 방식) 보존 — 감사·재표본용, 커밋 대상 아님(gitignore) ----
    all_cols = ["group", "channel", "video_id", "timestamp", "견종어", "문맥창",
                "non_knowledge", "추출방식", "주제", "관계유형", "메모"]
    for g in ("A", "B"):
        rows_g = dict_rows_by_group[g] + sent_rows_by_group[g]
        with open(outdir / f"population_group_{g}.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_g)

    # ---- 표본 CSV: 그룹B 30행(채널x주제 층화, dedup) + 그룹A 10행(대조군) ----
    rng = random.Random(SEED)
    pop_b = list({r["문맥창"]: r for r in dict_rows_by_group["B"]}.values())
    sample_b = stratify_by_channel_topic(pop_b, args.group_b_n, rng)

    pop_a_all = dict_rows_by_group["A"] + sent_rows_by_group["A"]
    pop_a = list({r["문맥창"]: r for r in pop_a_all}.values())
    sample_a = rng.sample(pop_a, min(args.group_a_n, len(pop_a)))

    sample_cols = ["group", "channel", "video_id", "timestamp", "견종어", "문맥창",
                   "non_knowledge", "추출방식", "관계유형", "메모"]
    with open(outdir / "sample_subtitle_v1.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=sample_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sample_b)
        w.writerows(sample_a)

    # ---- 콘솔 집계 리포트 (표+3줄 요약 스타일. 자막 본문 대량 인용 없음) ----
    print("=" * 70)
    print("[개요] 그룹A(보듬TV 확장분) / 그룹B(이삭TV+놀로와, 신규채널) — 절대 합산하지 않음")
    for g, label in (("A", "그룹A 보듬TV"), ("B", "그룹B 신규채널")):
        n_videos = sum(1 for v in per_video.values() if v["group"] == g)
        print(f"  {label:<14} 영상 {n_videos}편")

    print("\n[a] 그룹별 견종·형질 등장 횟수 / 등장 영상 수 / 상위 10개")
    for g in ("A", "B"):
        n_videos_total = sum(1 for v in per_video.values() if v["group"] == g)
        total_hits = sum(breed_term_hits[g].values())
        print(f"\n  그룹{g}: 등장 횟수 {total_hits}  등장 영상 {len(breed_videos_hit[g])}/{n_videos_total}")
        for term, c in breed_term_hits[g].most_common(10):
            print(f"    {term:<12} {c:>4}")

    print("\n[b] 그룹별 환경어 등장 횟수 (기존 환경어 사전) — '혼자' 별도 표기")
    for g in ("A", "B"):
        n_videos_total = sum(1 for v in per_video.values() if v["group"] == g)
        total = sum(env_term_hits[g].values())
        alone = env_term_hits[g].get("혼자", 0)
        print(f"\n  그룹{g}: 환경어 합계 {total}  등장 영상 {len(env_videos_hit[g])}/{n_videos_total}"
              f"  |  '혼자' 단독 {alone}")
        for term, c in env_term_hits[g].most_common(10):
            print(f"    {term:<12} {c:>4}  ({ENV_GROUP.get(term,'?')})")

    print("\n[c] 블로그 실측치(문장 단위, 참고) vs 자막(문맥창 단위, 이번 측정)")
    print("    ★ 단위가 다르다 — 블로그는 '문장', 자막은 '문맥창(±30어절)'. 직접 비율 비교 금지.")
    print(f"    블로그   : 견종·형질 1,345문장/331문서(40.3%)   혼자 1,018문장/264문서")
    for g in ("A", "B"):
        n_videos_total = sum(1 for v in per_video.values() if v["group"] == g)
        print(f"    그룹{g}(자막): 견종·형질 {sum(breed_term_hits[g].values())}문맥창/"
              f"{len(breed_videos_hit[g])}개 영상({n_videos_total}편 중)   "
              f"혼자 {env_term_hits[g].get('혼자',0)}문맥창/{n_videos_total}편")

    print(f"\n[표본] sample_subtitle_v1.csv: 그룹B {len(sample_b)}행 + 그룹A {len(sample_a)}행 "
          f"= {len(sample_b)+len(sample_a)}행 (seed={SEED})")
    print(f"[OOV 후보] {len(oov)}건 -> {outdir}/oov_candidates.csv (사전 미반영, 사람 승인 대기)")
    print(f"[모집단 보존] {outdir}/population_group_A.csv ({len(dict_rows_by_group['A'])+len(sent_rows_by_group['A'])}행), "
          f"population_group_B.csv ({len(dict_rows_by_group['B'])}행)")
    print("\n조건성·관계유형 라벨은 사람이 답니다. 결론·비율 해석 없이 대기합니다.")


if __name__ == "__main__":
    main()
