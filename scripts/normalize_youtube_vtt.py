"""Parse and normalize YouTube rolling-caption WebVTT files."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import webvtt


DEFAULT_INPUT = Path(
    "data/raw/youtube/subtitles/Ry3NnrbVjAM.ko-orig.vtt"
)
DEFAULT_OUTPUT_DIR = Path("data/processed/youtube/transcripts")
EMPTY_CUE_SENTINEL = "__DOG_TRAINING_RAG_EMPTY_CUE_4E7C9A2D__"
TIMESTAMP_PATTERN = r"(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}"
TIMING_LINE_RE = re.compile(
    rf"^\s*(?P<start>{TIMESTAMP_PATTERN})\s+-->\s+"
    rf"(?P<end>{TIMESTAMP_PATTERN})(?:\s+.*)?$"
)


class VttNormalizationError(ValueError):
    """Raised when the source cannot be normalized without data loss."""


@dataclass(frozen=True)
class TimingLine:
    line_index: int
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class CompatibilityRepairs:
    whitespace_line_numbers: tuple[int, ...]
    whitespace_cue_indices: tuple[int, ...]
    sentinel_cue_indices: tuple[int, ...]


@dataclass(frozen=True)
class ParsedCue:
    index: int
    start_ms: int
    end_ms: int
    raw_text: str
    normalized_text: str


@dataclass(frozen=True)
class TranscriptSegment:
    segment_index: int
    video_id: str
    start_ms: int
    end_ms: int
    text: str
    source_cue_indices: tuple[int, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "segment_index": self.segment_index,
            "video_id": self.video_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "source_cue_indices": list(self.source_cue_indices),
        }


@dataclass(frozen=True)
class Diagnostics:
    total_cues: int
    output_segments: int
    empty_cues: int
    exact_duplicates: int
    rolling_overlaps: int
    excluded_without_new_text: int
    final_word_count: int
    repairs: CompatibilityRepairs


@dataclass(frozen=True)
class NormalizationResult:
    cues: tuple[ParsedCue, ...]
    segments: tuple[TranscriptSegment, ...]
    diagnostics: Diagnostics


def timestamp_to_ms(value: str) -> int:
    """Convert a WebVTT timestamp to integer milliseconds."""
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes_text, seconds_text = parts
    elif len(parts) == 3:
        hours_text, minutes_text, seconds_text = parts
        hours = int(hours_text)
    else:
        raise VttNormalizationError(f"Invalid WebVTT timestamp: {value!r}")

    seconds, milliseconds = seconds_text.split(".")
    minutes = int(minutes_text)
    seconds_value = int(seconds)
    milliseconds_value = int(milliseconds)
    if hours < 0 or minutes < 0 or seconds_value < 0 or milliseconds_value < 0:
        raise VttNormalizationError(f"Negative WebVTT timestamp: {value!r}")
    if minutes > 59 or seconds_value > 59 or milliseconds_value > 999:
        raise VttNormalizationError(f"Invalid WebVTT timestamp: {value!r}")
    return (
        hours * 3_600_000
        + minutes * 60_000
        + seconds_value * 1_000
        + milliseconds_value
    )


def scan_timing_lines(lines: Sequence[str]) -> tuple[TimingLine, ...]:
    """Find and validate timing lines independently of webvtt-py."""
    timing_lines: list[TimingLine] = []
    for line_index, line in enumerate(lines):
        if "-->" not in line:
            continue
        match = TIMING_LINE_RE.fullmatch(line)
        if not match:
            raise VttNormalizationError(
                f"Malformed or negative timing line at source line {line_index + 1}: "
                f"{line!r}"
            )
        start_ms = timestamp_to_ms(match.group("start"))
        end_ms = timestamp_to_ms(match.group("end"))
        if end_ms < start_ms:
            raise VttNormalizationError(
                f"Reversed cue time at source line {line_index + 1}: "
                f"{match.group('start')} --> {match.group('end')}"
            )
        timing_lines.append(TimingLine(line_index, start_ms, end_ms))
    return tuple(timing_lines)


def _cue_payload_lines(
    lines: Sequence[str], timing_lines: Sequence[TimingLine], cue_index: int
) -> Sequence[str]:
    start = timing_lines[cue_index].line_index + 1
    next_timing = (
        timing_lines[cue_index + 1].line_index
        if cue_index + 1 < len(timing_lines)
        else len(lines)
    )
    end = next_timing
    for line_index in range(start, next_timing):
        if lines[line_index] == "":
            end = line_index
            break
    return lines[start:end]


def adapt_for_webvtt(
    source_text: str, timing_lines: Sequence[TimingLine]
) -> tuple[str, CompatibilityRepairs]:
    """Apply narrowly scoped in-memory compatibility repairs for webvtt-py."""
    if EMPTY_CUE_SENTINEL in source_text:
        raise VttNormalizationError(
            "The source already contains the reserved empty-cue sentinel"
        )

    lines = source_text.splitlines()
    remove_line_indices: set[int] = set()
    whitespace_line_numbers: list[int] = []
    whitespace_cue_indices: list[int] = []
    sentinel_after_line_indices: set[int] = set()
    sentinel_cue_indices: list[int] = []

    for cue_index, timing in enumerate(timing_lines):
        line_index = timing.line_index
        if line_index + 2 < len(lines):
            whitespace_line = lines[line_index + 1]
            following_line = lines[line_index + 2]
            if (
                whitespace_line != ""
                and not whitespace_line.strip()
                and following_line.strip()
                and not TIMING_LINE_RE.fullmatch(following_line)
            ):
                remove_line_indices.add(line_index + 1)
                whitespace_line_numbers.append(line_index + 2)
                whitespace_cue_indices.append(cue_index)

        payload_lines = _cue_payload_lines(lines, timing_lines, cue_index)
        if not any(line.strip() for line in payload_lines):
            sentinel_after_line_indices.add(line_index)
            sentinel_cue_indices.append(cue_index)

    adapted_lines: list[str] = []
    for line_index, line in enumerate(lines):
        if line_index in remove_line_indices:
            continue
        adapted_lines.append(line)
        if line_index in sentinel_after_line_indices:
            adapted_lines.append(EMPTY_CUE_SENTINEL)

    repairs = CompatibilityRepairs(
        whitespace_line_numbers=tuple(whitespace_line_numbers),
        whitespace_cue_indices=tuple(whitespace_cue_indices),
        sentinel_cue_indices=tuple(sentinel_cue_indices),
    )
    return "\n".join(adapted_lines), repairs


def normalize_caption_text(text: str) -> str:
    """Decode entities and normalize layout whitespace without editing speech."""
    return " ".join(html.unescape(text).split())


def parse_vtt_text(source_text: str) -> tuple[tuple[ParsedCue, ...], CompatibilityRepairs]:
    """Parse source text with webvtt-py and verify that it lost no cues."""
    lines = source_text.splitlines()
    timing_lines = scan_timing_lines(lines)
    adapted_text, repairs = adapt_for_webvtt(source_text, timing_lines)

    try:
        parsed_vtt = webvtt.from_string(adapted_text)
    except Exception as exc:  # webvtt-py exposes several malformed-input errors
        raise VttNormalizationError(f"webvtt-py failed to parse the source: {exc}") from exc

    captions = list(parsed_vtt)
    if len(captions) != len(timing_lines):
        raise VttNormalizationError(
            "Cue count mismatch after compatibility repairs: "
            f"source timing lines={len(timing_lines)}, parsed cues={len(captions)}"
        )

    sentinel_indices = set(repairs.sentinel_cue_indices)
    cues: list[ParsedCue] = []
    for index, caption in enumerate(captions):
        start_ms = timestamp_to_ms(caption.start)
        end_ms = timestamp_to_ms(caption.end)
        if start_ms < 0 or end_ms < 0:
            raise VttNormalizationError(f"Cue {index} contains a negative timestamp")
        if end_ms < start_ms:
            raise VttNormalizationError(
                f"Cue {index} has reversed time: {caption.start} --> {caption.end}"
            )

        if index in sentinel_indices:
            if normalize_caption_text(caption.raw_text) != EMPTY_CUE_SENTINEL:
                raise VttNormalizationError(
                    f"Empty-cue sentinel was not isolated in parsed cue {index}"
                )
            raw_text = ""
            normalized_text = ""
        else:
            if EMPTY_CUE_SENTINEL in caption.raw_text:
                raise VttNormalizationError(
                    f"Empty-cue sentinel leaked into non-empty cue {index}"
                )
            raw_text = caption.raw_text
            normalized_text = normalize_caption_text(caption.text)

        cues.append(
            ParsedCue(
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                raw_text=raw_text,
                normalized_text=normalized_text,
            )
        )
    return tuple(cues), repairs


def longest_word_overlap(previous: Sequence[str], current: Sequence[str]) -> int:
    """Return the longest previous suffix matching a current prefix."""
    for size in range(min(len(previous), len(current)), 0, -1):
        if list(previous[-size:]) == list(current[:size]):
            return size
    return 0


def normalize_rolling_captions(
    cues: Sequence[ParsedCue], video_id: str, repairs: CompatibilityRepairs
) -> NormalizationResult:
    """Emit only text newly introduced by each rolling caption cue."""
    segments: list[TranscriptSegment] = []
    previous_words: list[str] = []
    empty_cues = 0
    exact_duplicates = 0
    rolling_overlaps = 0
    excluded_without_new_text = 0
    final_word_count = 0

    for cue in cues:
        current_words = cue.normalized_text.split()
        prior_words = previous_words
        # Every non-empty cue becomes the rolling comparison state, even when
        # it emits no new words (for example, a short suffix-only cue).
        previous_words = current_words
        if not current_words:
            empty_cues += 1
            previous_words = []
            continue

        if current_words == prior_words:
            exact_duplicates += 1
            excluded_without_new_text += 1
            continue

        overlap_size = longest_word_overlap(prior_words, current_words)
        if overlap_size:
            rolling_overlaps += 1
        emitted_words = current_words[overlap_size:]
        if not emitted_words:
            excluded_without_new_text += 1
            continue

        emitted_text = " ".join(emitted_words)
        segments.append(
            TranscriptSegment(
                segment_index=len(segments),
                video_id=video_id,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                text=emitted_text,
                source_cue_indices=(cue.index,),
            )
        )
        final_word_count += len(emitted_words)

    diagnostics = Diagnostics(
        total_cues=len(cues),
        output_segments=len(segments),
        empty_cues=empty_cues,
        exact_duplicates=exact_duplicates,
        rolling_overlaps=rolling_overlaps,
        excluded_without_new_text=excluded_without_new_text,
        final_word_count=final_word_count,
        repairs=repairs,
    )
    return NormalizationResult(tuple(cues), tuple(segments), diagnostics)


def write_jsonl(segments: Sequence[TranscriptSegment], output_path: Path) -> None:
    """Write deterministic UTF-8 JSONL without exposing a partial output file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            for segment in segments:
                temporary_file.write(
                    json.dumps(
                        segment.to_json_dict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                temporary_file.write("\n")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def process_vtt(input_path: Path, output_dir: Path) -> tuple[NormalizationResult, Path]:
    """Parse, normalize, and write one YouTube VTT file."""
    source_text = input_path.read_text(encoding="utf-8-sig")
    cues, repairs = parse_vtt_text(source_text)
    video_id = input_path.name.split(".", 1)[0]
    if not video_id:
        raise VttNormalizationError(f"Cannot derive video_id from {input_path}")
    result = normalize_rolling_captions(cues, video_id, repairs)
    output_path = output_dir / f"{video_id}.jsonl"
    write_jsonl(result.segments, output_path)
    return result, output_path


def print_diagnostics(diagnostics: Diagnostics, output_path: Path) -> None:
    """Print stable, human-readable normalization diagnostics."""
    repairs = diagnostics.repairs
    print(f"total_cues: {diagnostics.total_cues}")
    print(f"output_segments: {diagnostics.output_segments}")
    print(f"empty_cues: {diagnostics.empty_cues}")
    print(f"exact_duplicates: {diagnostics.exact_duplicates}")
    print(f"rolling_overlaps: {diagnostics.rolling_overlaps}")
    print(
        "excluded_without_new_text: "
        f"{diagnostics.excluded_without_new_text}"
    )
    print(f"final_word_count: {diagnostics.final_word_count}")
    print(f"whitespace_repairs: {len(repairs.whitespace_line_numbers)}")
    print(
        "whitespace_repair_source_lines: "
        f"{list(repairs.whitespace_line_numbers)}"
    )
    print(
        "whitespace_repair_cue_indices: "
        f"{list(repairs.whitespace_cue_indices)}"
    )
    print(f"empty_cue_sentinel_repairs: {len(repairs.sentinel_cue_indices)}")
    print(f"empty_cue_sentinel_indices: {list(repairs.sentinel_cue_indices)}")
    print(f"output_path: {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize a YouTube rolling-caption WebVTT file to JSONL."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"input VTT path (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"JSONL output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result, output_path = process_vtt(args.input, args.output_dir)
    except (OSError, UnicodeError, VttNormalizationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print_diagnostics(result.diagnostics, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
