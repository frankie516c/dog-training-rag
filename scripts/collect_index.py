# -*- coding: utf-8 -*-
"""채널 전체 영상 인덱스를 TSV로 덤프한다.

영상을 받지 않고 목록만 훑으므로 ffmpeg가 필요 없다.
수집 규모를 먼저 파악한 뒤 자막 전략을 정하기 위한 1단계.

    python scripts/collect_index.py <채널 URL> <출력 TSV>
"""
import sys
import os
from yt_dlp import YoutubeDL

sys.stdout.reconfigure(encoding="utf-8")


def main(url: str, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    opts = {
        "extract_flat": True,   # 개별 영상 페이지를 열지 않는다 — 수백 배 빠르다
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = [e for e in (info.get("entries") or []) if e and e.get("id")]

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for e in entries:
            dur = e.get("duration") or 0
            title = (e.get("title") or "").replace("\t", " ").replace("\n", " ")
            f.write(f"{e['id']}\t{dur}\t{title}\n")

    total = sum(e.get("duration") or 0 for e in entries)
    durations = sorted(e.get("duration") or 0 for e in entries)
    median = durations[len(durations) // 2] if durations else 0

    print(f"채널      : {info.get('title', '?')}")
    print(f"영상 수   : {len(entries):,}개")
    print(f"총 길이   : {total / 3600:.1f}시간")
    print(f"중앙값    : {median / 60:.1f}분")
    print(f"10분 이상 : {sum(1 for d in durations if d >= 600):,}개")
    print(f"저장      : {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
