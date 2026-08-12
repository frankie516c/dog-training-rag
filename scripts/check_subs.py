# -*- coding: utf-8 -*-
"""채널 인덱스에서 N개를 균등 샘플링해 한국어 자막(수동/자동) 보유 여부를 실측한다."""
import sys, io, random
from yt_dlp import YoutubeDL

sys.stdout.reconfigure(encoding="utf-8")

idx_path, n = sys.argv[1], int(sys.argv[2])

rows = []
with io.open(idx_path, encoding="utf-8") as f:
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3 and p[0]:
            rows.append(p)

# 업로드 최신순으로 정렬돼 있으므로 균등 간격 샘플 = 전 기간 커버
step = max(1, len(rows) // n)
sample = rows[::step][:n]

opts = {"quiet": True, "no_warnings": True, "skip_download": True,
        "extract_flat": False, "writesubtitles": False}

manual = auto = none = err = 0
print(f"{'video_id':<12} {'수동자막':<10} {'자동자막':<10} title")
print("-" * 78)
with YoutubeDL(opts) as ydl:
    for vid, dur, title in sample:
        try:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        except Exception as e:
            err += 1
            print(f"{vid:<12} {'ERROR':<10} {'':<10} {str(e)[:40]}")
            continue
        subs = info.get("subtitles") or {}
        autos = info.get("automatic_captions") or {}
        has_m = any(k == "ko" or k.startswith("ko-") for k in subs)
        has_a = any(k == "ko" or k.startswith("ko-") for k in autos)
        if has_m:
            manual += 1
        elif has_a:
            auto += 1
        else:
            none += 1
        print(f"{vid:<12} {('O' if has_m else '-'):<10} {('O' if has_a else '-'):<10} {title[:38]}")

tot = manual + auto + none
print("-" * 78)
print(f"샘플 {tot}개 (에러 {err})  |  수동자막 {manual}  자동자막만 {auto}  자막없음 {none}")
if tot:
    print(f"→ 한국어 자막 확보율 {100*(manual+auto)/tot:.0f}%  (그중 수동 {100*manual/tot:.0f}%)")
