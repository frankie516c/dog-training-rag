"""Dry-run the document parsing logic over the whole crawl pool and classify what breaks.

`ingest_documents.py` promotes short standalone lines to headings and falls back to
character chunking when it detects a hard-wrapped body. Both rules were validated
against the handful of documents in that script's MANIFEST. This script answers a
different question: what happens if the same rules meet the 829 posts actually sitting
in the crawl pool.

It imports the real functions from `ingest_documents` — it does not reimplement them —
and runs them per post, then classifies the output. Nothing is written outside the
scratch directory: no corpus file, no embedding index, no eval snapshot is touched.
The point is to observe, not to ingest.

Usage:
    uv run python scripts/validate_document_parsing.py
    uv run python scripts/validate_document_parsing.py --limit 50   # smoke run
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingest_documents as ing
from chunking_config import CHUNKING

CRAWL_ROOT = Path("../scrapper/data")

# The four pools the task counts as "the raw material": 529 + 189 + 103 + 8 = 829.
# `blog_raw_rescue` is deliberately included even though ingest_documents.CRAWL_POOLS
# does not list it — it is 103 collected posts and a bulk ingest would have to decide
# about them one way or the other.
POOLS = {
    "berrardog": "blog_raw",
    "africaamc": "blog_raw_africaamc",
    "rescue": "blog_raw_rescue",
    "fitpet": "blog_raw_fitpet",
}

DEFAULT_OUT = Path("data/scratch/parse_validation_0825")

# --- classification thresholds ---------------------------------------------
#
# Every threshold here is a reading aid, not a verdict. They are named so the report
# can say "under this rule, N documents" rather than "N documents are broken".

# A promoted heading whose text ends in one of these is a sentence that was cut, not
# a title. Korean titles end on a noun, a question mark, or a nominalised verb; they
# do not end on a connective ending or a subject/object particle.
CONTINUATION_ENDINGS = (
    "하고", "되고", "이고", "라고", "지만", "면서", "으면", "려면", "어서", "아서",
    "해서", "하여", "이며", "하며", "거나", "든지", "는데", "은데", "인데", "니까",
    "므로", "도록", "게도", "에서", "부터", "까지", "에게", "한테", "으로", "로써",
    "라면", "다면", "치면", "보다", "처럼", "만큼", "대로", "위해", "통해", "따라",
    "때문", "경우", "중에", "동안",
)
PARTICLE_ENDINGS = ("은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만", "랑")

BOILERPLATE_MIN_DOCS = 20      # a line this common inside one source is furniture
BOILERPLATE_MIN_SHARE = 0.05   # ...or present in 5% of that source's documents
SHORT_CHUNK_CHARS = CHUNKING["min_chars"]
LONG_CHUNK_CHARS = CHUNKING["max_chars"]

# Characters that mean the file itself is damaged, as opposed to the writer having
# used an unusual symbol on purpose.
REPLACEMENT_CHAR = "�"
ZERO_WIDTH = ("​", "‌", "‍", "‎", "‏", "﻿", "­")
HTML_ENTITY = re.compile(r"&(?:[a-zA-Z]{2,10}|#\d{2,5}|#x[0-9a-fA-F]{2,5});")
HANGUL = re.compile(r"[가-힣]")


def load_pools(crawl_root: Path) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for source, folder in POOLS.items():
        path = crawl_root / folder / "posts.jsonl"
        if not path.is_file():
            raise SystemExit(f"crawl pool not found: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append((source, json.loads(line)))
    return rows


# --- vocabulary for mid-word split detection --------------------------------
#
# A hard-wrapped Naver body breaks lines mid-word. The character fallback rejoins
# those lines with a space, so the word survives into the chunk as two tokens. There
# is no way to be certain a given break was mid-word without a dictionary, so the
# corpus is used as one: a break is *suspected* mid-word when the two halves glued
# together are a token that occurs often elsewhere in the corpus while the left half
# almost never stands alone. This finds real cases and will also find some false
# ones; the report says so.
STRIP_CHARS = "“”‘’\"'()[]{}<>,.!?~·…-—:;"


def build_vocab(rows: Iterable[tuple[str, dict[str, Any]]]) -> collections.Counter:
    vocab: collections.Counter = collections.Counter()
    for _, row in rows:
        for line in row["text"].splitlines():
            for token in line.split():
                token = token.strip(STRIP_CHARS)
                if token:
                    vocab[token] += 1
    return vocab


def suspected_midword_breaks(
    lines: Sequence[str], vocab: collections.Counter
) -> list[tuple[str, str, str]]:
    """Adjacent line pairs whose join looks like it split a word. Returns (left, right, merged)."""
    body = [l.strip() for l in lines if l.strip()]
    hits: list[tuple[str, str, str]] = []
    for left, right in zip(body, body[1:]):
        if not HANGUL.search(left[-1:]) or not HANGUL.search(right[:1]):
            continue
        left_tokens, right_tokens = left.split(), right.split()
        if not left_tokens or not right_tokens:
            continue
        a, b = left_tokens[-1], right_tokens[0]
        if len(a) > 3:
            continue
        merged = a + b
        if vocab[merged] >= 5 and vocab[merged] > vocab[a] and vocab[a] < 20:
            hits.append((a, b, merged))
    return hits


def ends_like_sentence(text: str) -> bool:
    text = text.strip()
    return text.endswith(ing.SENTENCE_ENDINGS) or text.endswith(("?", "!", ".", "…"))


def classify_heading(heading: str, previous_line: str | None) -> list[str]:
    """Why a promoted heading looks wrong. Empty list = looks like a real heading."""
    flags: list[str] = []
    text = heading.strip()
    if text.endswith(CONTINUATION_ENDINGS):
        flags.append("연결어미로_끝남")
    elif text.endswith(PARTICLE_ENDINGS) and len(text) > 2:
        flags.append("조사로_끝남")
    if text.endswith(",") or text.startswith(("그리고", "그래서", "하지만", "그러나", "또한", "즉", "다만")):
        flags.append("접속어_시작_또는_쉼표_끝")
    if previous_line is not None and previous_line.strip() and not ends_like_sentence(previous_line):
        flags.append("직전_문장_미완결")
    if len(text) <= 3 and not text.endswith("?"):
        flags.append("3자_이하")
    if text[:1] in ("✦", "▶", "▷", "●", "■", "★", "☆", "-", "*") and len(text) <= 6:
        flags.append("장식_기호_행")
    return flags


def encoding_flags(text: str) -> dict[str, int]:
    return {
        "replacement_char": text.count(REPLACEMENT_CHAR),
        "lone_surrogate": sum(1 for c in text if 0xD800 <= ord(c) <= 0xDFFF),
        "zero_width": sum(text.count(c) for c in ZERO_WIDTH),
        "html_entity": len(HTML_ENTITY.findall(text)),
        "control_char": sum(1 for c in text if unicodedata.category(c) == "Cc" and c not in "\n\t\r"),
        "private_use": sum(1 for c in text if unicodedata.category(c) == "Co"),
    }


def analyse(rows: Sequence[tuple[str, dict[str, Any]]], vocab: collections.Counter) -> dict[str, Any]:
    # First pass: run the real pipeline, keep everything needed for the second pass.
    parsed: list[dict[str, Any]] = []
    for source, row in rows:
        doc_id = row["doc_id"]
        entry = {
            "doc_id": doc_id,
            "slot": f"dryrun-{source}",
            "source_url": row["url"],
        }
        record: dict[str, Any] = {"source": source, "doc_id": doc_id, "url": row["url"]}
        try:
            ing.check_url_allowed(row["url"], doc_id)
        except ing.IngestError as exc:
            record.update(fatal="blocked_url", detail=str(exc)[:200])
            parsed.append(record)
            continue

        title = row["title"].strip()
        raw_lines = row["text"].splitlines()
        kept, dropped = ing.clean(raw_lines)
        kept = [l for l in kept if l.strip() != title]
        hard_wrapped = ing.is_hard_wrapped(kept)
        if hard_wrapped:
            promoted_lines, promoted_count = list(kept), 0
        else:
            promoted_lines, promoted_count = ing.promote_headings(kept)

        try:
            records, outline = ing.build_chunks(
                entry, title, promoted_lines, promoted_count, hard_wrapped
            )
        except Exception as exc:  # noqa: BLE001 - a crash here is itself a finding
            record.update(fatal="exception", detail=f"{type(exc).__name__}: {exc}"[:200])
            parsed.append(record)
            continue
        if not records:
            record.update(fatal="no_chunk", detail="clean()/build_chunks produced zero chunks")
            parsed.append(record)
            continue

        body_lines = [l.strip() for l in kept if l.strip()]
        lengths = sorted(len(l) for l in body_lines) or [0]
        record.update(
            title=title,
            raw_chars=len(row["text"]),
            kept_lines=len(body_lines),
            dropped_lines=len(dropped),
            median_line_chars=lengths[len(lengths) // 2],
            short_line_share=(
                sum(1 for n in lengths if n <= ing.MAX_HEADING_CHARS) / len(lengths)
            ),
            hard_wrapped=hard_wrapped,
            promoted=promoted_count,
            method=records[0]["chunking_method"],
            chunks=len(records),
            chunk_chars=[r["char_count"] for r in records],
            promoted_lines=promoted_lines,
            kept=kept,
            records=records,
            outline=outline,
        )
        parsed.append(record)

    # Boilerplate: a line that survives clean() and recurs across a source's documents.
    per_source_docs: collections.Counter = collections.Counter()
    line_docs: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for rec in parsed:
        if rec.get("fatal"):
            continue
        per_source_docs[rec["source"]] += 1
        for line in {l.strip() for l in rec["kept"] if l.strip()}:
            line_docs[rec["source"]][line] += 1
    boilerplate: dict[str, set[str]] = {}
    boilerplate_table: dict[str, list[list[Any]]] = {}
    for source, counter in line_docs.items():
        total = per_source_docs[source]
        floor = max(2, min(BOILERPLATE_MIN_DOCS, int(total * BOILERPLATE_MIN_SHARE)))
        hits = [[line, n] for line, n in counter.items() if n >= floor]
        hits.sort(key=lambda p: -p[1])
        boilerplate[source] = {line for line, _ in hits}
        boilerplate_table[source] = hits[:40]

    # Second pass: classify.
    findings: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    per_doc: list[dict[str, Any]] = []
    chunk_id_owner: dict[str, str] = {}
    duplicate_chunk_ids: list[dict[str, Any]] = []

    for rec in parsed:
        if rec.get("fatal"):
            findings[rec["fatal"]].append(
                {"source": rec["source"], "doc_id": rec["doc_id"], "detail": rec.get("detail", "")}
            )
            per_doc.append({"source": rec["source"], "doc_id": rec["doc_id"], "fatal": rec["fatal"]})
            continue

        source, doc_id = rec["source"], rec["doc_id"]
        flags: set[str] = set()

        # --- heading promotion ------------------------------------------------
        bad_headings: list[dict[str, Any]] = []
        all_headings: list[str] = []
        if rec["promoted"]:
            previous: str | None = None
            for line in rec["promoted_lines"]:
                if line.startswith("## "):
                    all_headings.append(line[3:])
                    reasons = classify_heading(line[3:], previous)
                    if reasons:
                        bad_headings.append({"heading": line[3:], "reasons": reasons})
                if line.strip():
                    previous = line
        if bad_headings:
            flags.add("heading_false_promotion")
            findings["heading_false_promotion"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "promoted": rec["promoted"], "bad": len(bad_headings),
                "examples": bad_headings[:6],
            })

        # A document that produced no heading at all: the whole body is one flat
        # breadcrumb, so heading_path carries no more than the title.
        if rec["method"].startswith("char_v3_fallback"):
            flags.add("no_heading_at_all")
            findings["no_heading_at_all"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "hard_wrapped": rec["hard_wrapped"], "chunks": rec["chunks"],
                "median_line_chars": rec["median_line_chars"],
                "short_line_share": round(rec["short_line_share"], 3),
            })

        # Over-promotion: sections so numerous the body is shredded.
        section_bodies = [
            len("\n".join(s["lines"]).strip())
            for s in ing.split_sections(rec["promoted_lines"])
        ]
        tiny_sections = sum(1 for n in section_bodies if 0 < n < 80)
        if rec["promoted"] >= 8 and tiny_sections >= 5:
            flags.add("heading_shredding")
            findings["heading_shredding"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "promoted": rec["promoted"], "sections": len(section_bodies),
                "tiny_sections": tiny_sections,
                "sample_headings": all_headings[:6],
            })

        # --- hard wrap --------------------------------------------------------
        # Missed detection: the shape is hard-wrapped-ish but under the threshold, so
        # promotion ran anyway.
        if (not rec["hard_wrapped"]
                and rec["short_line_share"] >= 0.60
                and rec["median_line_chars"] <= 34
                and rec["promoted"] > 0):
            flags.add("hardwrap_missed")
            findings["hardwrap_missed"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "short_line_share": round(rec["short_line_share"], 3),
                "median_line_chars": rec["median_line_chars"],
                "promoted": rec["promoted"],
                "sample_headings": all_headings[:6],
            })

        midword = suspected_midword_breaks(rec["kept"], vocab)
        if midword:
            flags.add("midword_join")
            findings["midword_join"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "count": len(midword),
                "examples": [{"left": a, "right": b, "merged": m} for a, b, m in midword[:6]],
            })

        # Chunks that stop mid-sentence: the packer flushed on a character budget
        # between two wrapped lines rather than at a sentence end.
        cut = []
        for r in rec["records"]:
            body = r["text"].split("\n", 1)[1] if "\n" in r["text"] else ""
            if body.strip() and not ends_like_sentence(body):
                cut.append(r["chunk_index"])
        if cut:
            flags.add("chunk_cut_midsentence")
            findings["chunk_cut_midsentence"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "cut": len(cut), "of": rec["chunks"],
            })

        # --- length -----------------------------------------------------------
        short = [n for n in rec["chunk_chars"] if n < SHORT_CHUNK_CHARS]
        long_ = [n for n in rec["chunk_chars"] if n > LONG_CHUNK_CHARS]
        if short:
            flags.add("chunk_too_short")
            findings["chunk_too_short"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "count": len(short), "of": rec["chunks"], "sizes": sorted(short)[:8],
            })
        if long_:
            flags.add("chunk_too_long")
            findings["chunk_too_long"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "count": len(long_), "of": rec["chunks"], "sizes": sorted(long_, reverse=True)[:8],
            })

        # --- boilerplate ------------------------------------------------------
        bp = boilerplate.get(source, set())
        bp_lines = [l.strip() for l in rec["kept"] if l.strip() in bp]
        if bp_lines:
            bp_chars = sum(len(l) for l in bp_lines)
            total_chars = sum(len(l.strip()) for l in rec["kept"] if l.strip()) or 1
            unique_bp = set(bp_lines)
            contaminated = [
                r["chunk_index"] for r in rec["records"]
                if any(line in r["text"] for line in unique_bp)
            ]
            flags.add("boilerplate")
            findings["boilerplate"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"],
                "lines": len(bp_lines), "share_of_body": round(bp_chars / total_chars, 3),
                "chunks_touched": len(contaminated), "of": rec["chunks"],
                "examples": bp_lines[:4],
            })

        # --- encoding ---------------------------------------------------------
        enc = encoding_flags("\n".join(rec["kept"]))
        if any(enc.values()):
            flags.add("encoding")
            findings["encoding"].append({
                "source": source, "doc_id": doc_id, "url": rec["url"], **enc,
            })

        # --- identity ---------------------------------------------------------
        for r in rec["records"]:
            owner = chunk_id_owner.get(r["chunk_id"])
            if owner and owner != doc_id:
                duplicate_chunk_ids.append({
                    "source": source,
                    "chunk_id": r["chunk_id"], "first": owner, "second": doc_id,
                    "chars": r["char_count"],
                    "preview": r["text"][:80],
                })
            else:
                chunk_id_owner[r["chunk_id"]] = doc_id

        per_doc.append({
            "source": source, "doc_id": doc_id, "url": rec["url"],
            "method": rec["method"], "hard_wrapped": rec["hard_wrapped"],
            "promoted": rec["promoted"], "chunks": rec["chunks"],
            "median_line_chars": rec["median_line_chars"],
            "short_line_share": round(rec["short_line_share"], 3),
            "flags": sorted(flags),
        })

    if duplicate_chunk_ids:
        findings["duplicate_chunk_id"] = duplicate_chunk_ids

    ok = [r for r in parsed if not r.get("fatal")]
    all_chunk_chars = [n for r in ok for n in r["chunk_chars"]]
    all_chunk_chars.sort()
    return {
        "totals": {
            "documents": len(parsed),
            "parsed": len(ok),
            "fatal": len(parsed) - len(ok),
            "chunks": sum(r["chunks"] for r in ok),
            "chunk_chars_min": all_chunk_chars[0] if all_chunk_chars else 0,
            "chunk_chars_median": all_chunk_chars[len(all_chunk_chars) // 2] if all_chunk_chars else 0,
            "chunk_chars_max": all_chunk_chars[-1] if all_chunk_chars else 0,
            "chunks_below_min": sum(1 for n in all_chunk_chars if n < SHORT_CHUNK_CHARS),
            "chunks_above_max": sum(1 for n in all_chunk_chars if n > LONG_CHUNK_CHARS),
            "chunking": CHUNKING,
        },
        "method_counts": dict(collections.Counter(
            f'{r["source"]}|{r["method"]}' for r in ok
        )),
        "per_source_docs": dict(per_source_docs),
        "findings": dict(findings),
        "boilerplate_table": boilerplate_table,
        "per_doc": per_doc,
        "_parsed": parsed,
    }


def summarise(result: dict[str, Any]) -> str:
    sources = list(POOLS)
    doc_totals = result["per_source_docs"]
    lines: list[str] = []
    t = result["totals"]
    lines.append(
        "문서 {documents}건 / 파싱 성공 {parsed}건 / 치명 실패 {fatal}건 / 청크 {chunks}개".format(**t)
    )
    lines.append(
        "청크 길이 min/median/max = {chunk_chars_min}/{chunk_chars_median}/{chunk_chars_max}"
        " (계약 {chunking})".format(**t)
    )
    lines.append("")
    header = f"{'유형':<26}" + "".join(f"{s:>11}" for s in sources) + f"{'합계':>9}"
    lines.append(header)
    lines.append("-" * 80)
    for kind, rows in sorted(result["findings"].items()):
        counts = collections.Counter(r.get("source", "?") for r in rows)
        label = kind + (" (건)" if kind == "duplicate_chunk_id" else "")
        lines.append(
            f"{label:<26}"
            + "".join(f"{counts.get(s, 0):>11}" for s in sources)
            + f"{sum(counts.values()):>9}"
        )
    lines.append("-" * 80)
    lines.append(f"{'(문서 수)':<26}" + "".join(f"{doc_totals.get(s, 0):>11}" for s in sources)
                 + f"{sum(doc_totals.values()):>9}")
    lines.append("")
    lines.append("chunking_method 분포:")
    for key, n in sorted(result["method_counts"].items()):
        lines.append(f"  {key}: {n}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crawl-root", type=Path, default=CRAWL_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0, help="only the first N posts per pool")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = load_pools(args.crawl_root)
    if args.limit:
        capped: list[tuple[str, dict[str, Any]]] = []
        seen: collections.Counter = collections.Counter()
        for source, row in rows:
            if seen[source] < args.limit:
                capped.append((source, row))
                seen[source] += 1
        rows = capped

    vocab = build_vocab(rows)
    result = analyse(rows, vocab)
    parsed = result.pop("_parsed")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "findings.json").write_bytes(
        json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    )
    # Full parsed output, for pulling examples by hand. Scratch only.
    with (args.out / "chunks_dryrun.jsonl").open("wb") as handle:
        for rec in parsed:
            if rec.get("fatal"):
                continue
            for r in rec["records"]:
                handle.write(
                    (json.dumps({**r, "_source": rec["source"]}, ensure_ascii=False) + "\n")
                    .encode("utf-8")
                )

    summary = summarise(result)
    (args.out / "summary.txt").write_bytes(summary.encode("utf-8"))
    sys.stdout.reconfigure(encoding="utf-8")
    print(summary)
    print(f"\n출력: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
