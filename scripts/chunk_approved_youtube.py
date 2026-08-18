"""Attach approved YouTube transcript segments to chapters and make chunks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


DEFAULT_LEDGER = Path("data/reviews/bodeum_youtube_manual_reviews.csv")
DEFAULT_METADATA = Path("data/reviews/bodeum_youtube_metadata.csv")
DEFAULT_TRANSCRIPT_DIR = Path("data/processed/youtube/transcripts")
DEFAULT_OUTPUT_DIR = Path("data/processed/youtube/chunks")
SCHEMA_VERSION = "youtube-chunk-v1"
NON_CONTENT_MARKERS = (
    "하이라이트", "highlight", "오프닝", "opening", "인트로", "intro",
    "엔딩", "ending", "클로징", "closing", "아웃트로", "outro",
)
SPEAKER_START_RE = re.compile(r"^(?:>>|>|화자\s*:)")
SENTENCE_END_RE = re.compile(r"[.!?。！？]$")


class ChunkingError(ValueError):
    """Raised when chunking inputs or settings are invalid."""


@dataclass(frozen=True)
class ChunkingConfig:
    """Chunking settings. The defaults are the settings the corpus was adopted with.

    Changing a default re-chunks the corpus on the next plain `python
    chunk_approved_youtube.py` run: chunk_id hashes these values, so every id, the
    corpus fingerprint and every committed metrics snapshot stop lining up. The
    settings are written into each chunk record (see `build_chunks`) so a corpus
    always says which run produced it.
    """

    target_chars: int = 420
    min_chars: int = 150
    max_chars: int = 480
    overlap_segments: int = 0

    def validate(self) -> None:
        if not (0 < self.min_chars <= self.target_chars <= self.max_chars):
            raise ChunkingError(
                "chunking settings must satisfy "
                "0 < min_chars <= target_chars <= max_chars"
            )
        if self.overlap_segments < 0:
            raise ChunkingError("overlap_segments must be non-negative")

    def payload(self) -> dict[str, int]:
        return {
            "target_chars": self.target_chars,
            "min_chars": self.min_chars,
            "max_chars": self.max_chars,
            "overlap_segments": self.overlap_segments,
        }


def read_approved_video_ids(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if "video_id" not in (reader.fieldnames or ()) or "review_status" not in (reader.fieldnames or ()):
            raise ChunkingError("ledger must contain video_id and review_status")
        return [
            row["video_id"].strip()
            for row in reader
            if row.get("review_status", "").strip() == "APPROVED"
        ]


def read_metadata(path: Path, video_ids: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            if row.get("video_id") in video_ids:
                result[row["video_id"]] = row
    missing = video_ids - result.keys()
    if missing:
        raise ChunkingError(f"metadata missing approved videos: {sorted(missing)}")
    return result


def load_segments(path: Path, video_id: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ChunkingError(f"transcript not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ChunkingError(f"invalid transcript JSON at line {line_number}") from exc
            if row.get("video_id") != video_id or not isinstance(row.get("text"), str):
                raise ChunkingError(f"invalid transcript row at line {line_number}")
            if not isinstance(row.get("segment_index"), int) or not isinstance(row.get("source_cue_indices"), list):
                raise ChunkingError(f"invalid transcript indexes at line {line_number}")
            if not isinstance(row.get("start_ms"), int) or not isinstance(row.get("end_ms"), int):
                raise ChunkingError(f"invalid transcript timing at line {line_number}")
            if row["start_ms"] < 0 or row["start_ms"] > row["end_ms"]:
                raise ChunkingError(f"invalid transcript interval at line {line_number}")
            rows.append(row)
    if [row["segment_index"] for row in rows] != list(range(len(rows))):
        raise ChunkingError(f"segment indexes are not contiguous for {video_id}")
    return rows


def parse_chapters(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        chapters = json.loads(row.get("chapters") or "[]")
    except json.JSONDecodeError as exc:
        raise ChunkingError(f"invalid chapters JSON for {row.get('video_id')}") from exc
    if not isinstance(chapters, list):
        raise ChunkingError("chapters must be a JSON array")
    result: list[dict[str, Any]] = []
    previous = -1
    for index, chapter in enumerate(chapters):
        try:
            start_ms = int(float(chapter["start_seconds"]) * 1000)
            title = str(chapter["title"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ChunkingError(f"invalid chapter at index {index}") from exc
        if start_ms < 0 or start_ms <= previous:
            raise ChunkingError("chapter starts must be strictly increasing")
        previous = start_ms
        result.append({"chapter_index": index, "chapter_title": title, "start_ms": start_ms})
    return result


def classify_chapter(title: str, has_chapters: bool) -> tuple[str, bool, str | None]:
    if not has_chapters:
        return "UNCHAPTERED", True, None
    normalized = title.strip().casefold()
    for marker in NON_CONTENT_MARKERS:
        if marker.casefold() in normalized:
            return "NON_CONTENT", False, f"chapter_title:{title}"
    return "CONTENT", True, None


def _distance_to_interval(value: int, start: int, end: int) -> int:
    if start <= value <= end:
        return 0
    return start - value if value < start else value - end


def attach_chapters(segments: Sequence[dict[str, Any]], chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not chapters:
        return [dict(segment, chapter_index=None, chapter_title="", chapter_role="UNCHAPTERED", embedding_eligible=True, exclusion_reason=None) for segment in segments]
    ends = [chapters[i + 1]["start_ms"] for i in range(len(chapters) - 1)] + [max((s["end_ms"] for s in segments), default=chapters[-1]["start_ms"])]
    attached = []
    for segment in segments:
        overlaps = [max(0, min(segment["end_ms"], end) - max(segment["start_ms"], chapter["start_ms"])) for chapter, end in zip(chapters, ends)]
        if max(overlaps, default=0) > 0:
            index = max(range(len(chapters)), key=lambda i: (overlaps[i], -i))
        else:
            start = segment["start_ms"]
            containing = [i for i, end in enumerate(ends) if chapters[i]["start_ms"] <= start <= end]
            if containing:
                index = containing[0]
            elif start < chapters[0]["start_ms"]:
                index = 0
            elif start > ends[-1]:
                index = len(chapters) - 1
            else:
                distances = [_distance_to_interval(start, chapter["start_ms"], end) for chapter, end in zip(chapters, ends)]
                index = min(range(len(chapters)), key=lambda i: (distances[i], i))
        chapter = chapters[index]
        role, eligible, reason = classify_chapter(chapter["chapter_title"], True)
        attached.append(dict(segment, chapter_index=index, chapter_title=chapter["chapter_title"], chapter_role=role, embedding_eligible=eligible, exclusion_reason=reason))
    return attached


def _is_soft_before(segment: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    return bool(SPEAKER_START_RE.match(segment["text"].strip())) or bool(previous and segment["start_ms"] - previous["end_ms"] >= 1200)


def _is_speaker_before(segment: dict[str, Any]) -> bool:
    return bool(SPEAKER_START_RE.match(segment["text"].strip()))


def _is_soft_after(segment: dict[str, Any]) -> bool:
    return bool(SENTENCE_END_RE.search(segment["text"].rstrip()))


def _joined_char_count(segments: Sequence[dict[str, Any]]) -> int:
    return sum(len(segment["text"]) for segment in segments) + max(0, len(segments) - 1)


def _chunk_group(segments: Sequence[dict[str, Any]], config: ChunkingConfig) -> list[list[dict[str, Any]]]:
    result: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    last_soft_cut: int | None = None
    index = 0
    while index < len(segments):
        segment = segments[index]
        previous = segments[index - 1] if index else None
        if current:
            strong_before = bool(
                previous and segment["start_ms"] - previous["end_ms"] >= 1200
            )
            speaker_before = _is_speaker_before(segment)
            if strong_before and current_chars >= config.min_chars:
                last_soft_cut = len(current)
            if current_chars >= config.target_chars:
                if last_soft_cut is not None:
                    cut = last_soft_cut
                    result.append(current[:cut])
                    current = current[cut:]
                    current_chars = _joined_char_count(current)
                    last_soft_cut = None
                elif speaker_before:
                    result.append(current)
                    current = []
                    current_chars = 0
        segment_chars = len(segment["text"]) + (1 if current else 0)
        if current and current_chars + segment_chars > config.max_chars:
            cut = last_soft_cut or len(current)
            result.append(current[:cut])
            current = current[cut:]
            current_chars = _joined_char_count(current)
            last_soft_cut = None
            continue
        current.append(segment)
        current_chars += segment_chars
        index += 1
        if _is_soft_after(segment) and current_chars >= config.min_chars:
            last_soft_cut = len(current)
        if current_chars >= config.target_chars and last_soft_cut is not None:
            result.append(current[:last_soft_cut])
            current = current[last_soft_cut:]
            current_chars = _joined_char_count(current)
            last_soft_cut = None
    if current:
        result.append(current)
    if len(result) >= 2 and _joined_char_count(result[-1]) < config.min_chars:
        previous_chars = _joined_char_count(result[-2])
        last_chars = _joined_char_count(result[-1])
        if previous_chars + last_chars <= config.max_chars:
            result[-2].extend(result.pop())
    return result


def make_chunk_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return "chunk-" + hashlib.sha256(canonical).hexdigest()


def build_chunks(segments: Sequence[dict[str, Any]], config: ChunkingConfig) -> list[dict[str, Any]]:
    config.validate()
    groups: list[list[dict[str, Any]]] = []
    for chapter_index in dict.fromkeys(segment["chapter_index"] for segment in segments):
        groups.extend(_chunk_group([s for s in segments if s["chapter_index"] == chapter_index], config))
    output = []
    for chunk_index, group in enumerate(groups):
        first, last = group[0], group[-1]
        source_segments = [s["segment_index"] for s in group]
        source_cues = [cue for s in group for cue in s["source_cue_indices"]]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "video_id": first["video_id"],
            "chapter_index": first["chapter_index"],
            "chapter_role": first["chapter_role"],
            "start_ms": first["start_ms"],
            "end_ms": last["end_ms"],
            "source_segment_indices": source_segments,
            "target_chars": config.target_chars,
            "min_chars": config.min_chars,
            "max_chars": config.max_chars,
            "overlap_segments": config.overlap_segments,
        }
        text = " ".join(s["text"] for s in group)
        output.append({
            "schema_version": SCHEMA_VERSION,
            "chunk_id": make_chunk_id(payload),
            "video_id": first["video_id"],
            "chunk_index": chunk_index,
            "chapter_index": first["chapter_index"],
            "chapter_title": first["chapter_title"],
            "chapter_role": first["chapter_role"],
            "embedding_eligible": first["embedding_eligible"],
            "exclusion_reason": first["exclusion_reason"],
            "start_ms": first["start_ms"],
            "end_ms": last["end_ms"],
            "text": text,
            "source_segment_indices": source_segments,
            "source_cue_indices": source_cues,
            "char_count": len(text),
            # Emitted only. `payload` above is the chunk_id hash input and must keep
            # its exact keys and order; adding a field there would change every id.
            "chunking": config.payload(),
        })
    return output


def write_jsonl(rows: Sequence[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                file.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def process_video(video_id: str, metadata: dict[str, Any], transcript_dir: Path, output_dir: Path, config: ChunkingConfig) -> Path:
    config.validate()
    segments = load_segments(transcript_dir / f"{video_id}.jsonl", video_id)
    attached = attach_chapters(segments, parse_chapters(metadata))
    rows = build_chunks(attached, config)
    output = output_dir / f"{video_id}.jsonl"
    write_jsonl(rows, output)
    return output


def run(ledger: Path = DEFAULT_LEDGER, metadata: Path = DEFAULT_METADATA, transcript_dir: Path = DEFAULT_TRANSCRIPT_DIR, output_dir: Path = DEFAULT_OUTPUT_DIR, config: ChunkingConfig = ChunkingConfig()) -> list[Path]:
    config.validate()
    video_ids = read_approved_video_ids(ledger)
    metadata_rows = read_metadata(metadata, set(video_ids))
    return [process_video(video_id, metadata_rows[video_id], transcript_dir, output_dir, config) for video_id in video_ids]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--transcript-dir", type=Path, default=DEFAULT_TRANSCRIPT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    # Read off the dataclass so a CLI default can never drift from the adopted one.
    defaults = ChunkingConfig()
    parser.add_argument("--target-chars", type=int, default=defaults.target_chars)
    parser.add_argument("--min-chars", type=int, default=defaults.min_chars)
    parser.add_argument("--max-chars", type=int, default=defaults.max_chars)
    parser.add_argument("--overlap-segments", type=int, default=defaults.overlap_segments)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = ChunkingConfig(args.target_chars, args.min_chars, args.max_chars, args.overlap_segments)
    try:
        for path in run(args.ledger, args.metadata, args.transcript_dir, args.output_dir, config):
            print(path)
    except (OSError, UnicodeError, ChunkingError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
