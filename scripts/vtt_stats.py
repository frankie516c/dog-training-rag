# -*- coding: utf-8 -*-
"""YouTube 자동자막 VTT는 롤업 방식이라 같은 문구가 반복된다.
인라인 타이밍 태그를 걷어내고 중복을 접은 뒤 실제 본문 분량을 잰다."""
import sys, re, io, glob, os

sys.stdout.reconfigure(encoding="utf-8")

TS = re.compile(r"^\d\d:\d\d:\d\d\.\d\d\d\s+-->")
TAG = re.compile(r"<[^>]+>")          # <00:00:01.234><c> 등
CUE_SET = re.compile(r"align:|position:")

for path in sorted(glob.glob(sys.argv[1])):
    lines, dur = [], 0.0
    with io.open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if TS.match(line):
                end = line.split("-->")[1].strip().split(" ")[0]
                h, m, s = end.split(":")
                dur = max(dur, int(h) * 3600 + int(m) * 60 + float(s))
                continue
            if not line.strip() or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
                continue
            txt = TAG.sub("", line).strip()
            if not txt or CUE_SET.search(txt):
                continue
            lines.append(txt)

    # 롤업 중복 접기: 직전 확정 줄과 같거나, 직전 줄의 접두사인 경우 버림
    folded = []
    for t in lines:
        if folded and (t == folded[-1] or folded[-1].endswith(t) or t.startswith(folded[-1])):
            folded[-1] = t if len(t) > len(folded[-1]) else folded[-1]
            continue
        folded.append(t)

    body = " ".join(folded)
    name = os.path.basename(path)
    mins = dur / 60 or 1
    print(f"{name}")
    print(f"  영상 길이   : {dur/60:.1f}분")
    print(f"  원본 줄 수  : {len(lines)}  →  중복 제거 후 {len(folded)}")
    print(f"  본문 글자수 : {len(body):,}자   (분당 {len(body)/mins:.0f}자)")
    print(f"  샘플: {body[:160]}...")
    print()
