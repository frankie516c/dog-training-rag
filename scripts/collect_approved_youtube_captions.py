"""Download and normalize approved Korean automatic YouTube captions."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from yt_dlp import YoutubeDL

try:
    from normalize_youtube_vtt import process_vtt
except ModuleNotFoundError:  # pragma: no cover - supports direct module loading in tests
    from scripts.normalize_youtube_vtt import process_vtt


DEFAULT_LEDGER = Path("data/reviews/bodeum_youtube_manual_reviews.csv")
DEFAULT_RAW_DIR = Path("data/raw/youtube/subtitles")
DEFAULT_OUTPUT_DIR = Path("data/processed/youtube/transcripts")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
REQUIRED_LEDGER_COLUMNS = {"video_id", "review_status"}


class CaptionCollectionError(RuntimeError):
    """Raised before processing when the ledger is invalid."""


def read_approved_video_ids(ledger_path: Path) -> list[str]:
    if not ledger_path.is_file():
        raise CaptionCollectionError(f"ledger not found: {ledger_path}")
    with ledger_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or ())
        missing = REQUIRED_LEDGER_COLUMNS - columns
        if missing:
            raise CaptionCollectionError(
                f"ledger missing required columns: {', '.join(sorted(missing))}"
            )
        ids: list[str] = []
        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            video_id = (row.get("video_id") or "").strip()
            if not VIDEO_ID_RE.fullmatch(video_id):
                raise CaptionCollectionError(
                    f"invalid video_id at ledger row {row_number}"
                )
            if video_id in seen:
                raise CaptionCollectionError(
                    f"duplicate video_id at ledger row {row_number}"
                )
            seen.add(video_id)
            if (row.get("review_status") or "").strip() == "APPROVED":
                ids.append(video_id)
    return ids


def raw_vtt_is_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        first_line = path.read_text(encoding="utf-8-sig").splitlines()[0]
    except (OSError, UnicodeError, IndexError):
        return False
    return first_line.strip() == "WEBVTT"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def jsonl_is_valid(path: Path, video_id: str) -> bool:
    if not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    if not lines:
        return False
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return False
        if not isinstance(row, dict):
            return False
        if row.get("video_id") != video_id:
            return False
        start_ms = row.get("start_ms")
        end_ms = row.get("end_ms")
        if not _is_int(start_ms) or not _is_int(end_ms):
            return False
        if start_ms < 0 or start_ms > end_ms:
            return False
        if not isinstance(row.get("text"), str):
            return False
        if not isinstance(row.get("source_cue_indices"), list):
            return False
    return True


def download_vtt(video_id: str, raw_path: Path, raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{video_id}.", dir=raw_dir) as temp_name:
        temp_dir = Path(temp_name)
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ko-orig"],
            "subtitlesformat": "vtt",
            "outtmpl": str(temp_dir / f"{video_id}.%(ext)s"),
        }
        with YoutubeDL(options) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        candidates = sorted(temp_dir.glob(f"{video_id}.ko-orig.vtt"))
        if len(candidates) != 1 or not raw_vtt_is_valid(candidates[0]):
            raise RuntimeError("downloaded ko-orig VTT failed validation")
        os.replace(candidates[0], raw_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    return parser


def _positive_limit(value: int | None) -> None:
    if value is not None and value < 1:
        raise CaptionCollectionError("--limit must be at least 1")


def run(
    ledger_path: Path = DEFAULT_LEDGER,
    raw_dir: Path = DEFAULT_RAW_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    force: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> tuple[int, dict[str, int]]:
    _positive_limit(limit)
    video_ids = read_approved_video_ids(ledger_path)
    if limit is not None:
        video_ids = video_ids[:limit]
    if dry_run:
        counts = {
            "would_download": 0,
            "would_normalize": 0,
            "would_skip": 0,
            "failed": 0,
        }
    else:
        counts = {"success": 0, "skipped": 0, "failed": 0}
    for video_id in video_ids:
        raw_path = raw_dir / f"{video_id}.ko-orig.vtt"
        jsonl_path = output_dir / f"{video_id}.jsonl"
        raw_ok = raw_vtt_is_valid(raw_path)
        json_ok = jsonl_is_valid(jsonl_path, video_id)
        if not force and raw_ok and json_ok:
            counts["would_skip" if dry_run else "skipped"] += 1
            continue
        if dry_run:
            counts["would_normalize" if raw_ok else "would_download"] += 1
            continue
        try:
            if force or not raw_ok:
                download_vtt(video_id, raw_path, raw_dir)
            if not raw_vtt_is_valid(raw_path):
                raise RuntimeError("raw VTT failed validation")
            process_vtt(raw_path, output_dir)
            if not jsonl_is_valid(jsonl_path, video_id):
                raise RuntimeError("normalized JSONL failed validation")
            counts["success"] += 1
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            counts["failed"] += 1
    return (1 if counts["failed"] else 0), counts


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        exit_code, counts = run(
            args.ledger,
            args.raw_dir,
            args.output_dir,
            force=args.force,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    except CaptionCollectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        would_process = counts["would_download"] + counts["would_normalize"]
        approved = would_process + counts["would_skip"] + counts["failed"]
        print(
            "approved: {0} would_process: {1} would_skip: {2} failed: {3}".format(
                approved, would_process, counts["would_skip"], counts["failed"]
            )
        )
        print(
            "dry_run: WOULD_DOWNLOAD={0} WOULD_NORMALIZE={1} WOULD_SKIP={2}".format(
                counts["would_download"], counts["would_normalize"], counts["would_skip"]
            )
        )
    else:
        print(
            "approved: {0} success: {1} skipped: {2} failed: {3}".format(
                sum(counts.values()), counts["success"], counts["skipped"], counts["failed"]
            )
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
