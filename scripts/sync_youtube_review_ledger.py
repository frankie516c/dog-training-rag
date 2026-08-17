"""Synchronize YouTube candidates into a persistent manual-review ledger."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable


DEFAULT_METADATA = Path("data/reviews/bodeum_youtube_metadata.csv")
DEFAULT_LEDGER = Path("data/reviews/bodeum_youtube_manual_reviews.csv")
LEDGER_FIELDS = [
    "video_id",
    "title",
    "video_url",
    "classification",
    "review_status",
    "review_reason",
    "reviewed_at",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def synchronize_rows(
    metadata_rows: Iterable[dict[str, str]], ledger_rows: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    """Upsert candidates while preserving all human-authored review fields."""
    metadata = {
        row.get("video_id", ""): row
        for row in metadata_rows
        if row.get("video_id")
    }
    ledger: dict[str, dict[str, str]] = {}
    for row in ledger_rows:
        video_id = row.get("video_id", "")
        if not video_id or video_id in ledger:
            continue
        ledger[video_id] = {field: row.get(field, "") for field in LEDGER_FIELDS}

    for video_id, existing in ledger.items():
        latest = metadata.get(video_id)
        if latest is None:
            continue
        existing["title"] = latest.get("title", "")
        existing["video_url"] = video_url(video_id)
        existing["classification"] = latest.get("classification", "")

    for video_id, latest in metadata.items():
        if latest.get("classification") != "CANDIDATE" or video_id in ledger:
            continue
        ledger[video_id] = {
            "video_id": video_id,
            "title": latest.get("title", ""),
            "video_url": video_url(video_id),
            "classification": "CANDIDATE",
            "review_status": "PENDING",
            "review_reason": "",
            "reviewed_at": "",
        }
    return list(ledger.values())


def write_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def sync(metadata_path: Path, ledger_path: Path) -> list[dict[str, str]]:
    rows = synchronize_rows(read_csv(metadata_path), read_csv(ledger_path))
    write_ledger(ledger_path, rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args(argv)
    if not args.metadata.exists():
        parser.error(f"metadata CSV를 찾을 수 없습니다: {args.metadata}")
    rows = sync(args.metadata, args.ledger)
    statuses: dict[str, int] = {}
    for row in rows:
        status = row["review_status"] or "(EMPTY)"
        statuses[status] = statuses.get(status, 0) + 1
    print(f"review ledger: {len(rows):,}개 ({args.ledger})")
    for status, count in sorted(statuses.items()):
        print(f"{status}: {count:,}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
