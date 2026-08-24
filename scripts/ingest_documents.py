"""Ingest the six selected documents into a document corpus alongside the video chunks.

These are blog articles, not transcribed video. They have no video_id, no timeline
and no speaker, so the chunk records here do not carry those fields — an empty
`start_ms` on a document is not "unknown timing", it is a field that does not apply,
and filling it with a placeholder would put a number where there is no measurement.
The same reasoning the owner fixtures used for their absent gold labels.

Splitting is header-first. Where a document has headings, the section boundary is a
better chunk boundary than a character count, and `heading_path` records where each
chunk sits so a parent-child retriever can be attached later without re-chunking.
Sections longer than the v3 ceiling are then split on characters, so every chunk in
the combined corpus obeys the same length contract as the video chunks.

Only the six documents named in docs/acquisition_list.md are ingested. The crawl pool
is 718 posts; this is not a bulk load.

Usage:
    uv run python scripts/ingest_documents.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from chunking_config import CHUNKING as _SHARED_CHUNKING

CRAWL_ROOT = Path("../scrapper/data")
MANUAL_DIR = CRAWL_ROOT / "manual"
CRAWL_POOLS = ("blog_raw", "blog_raw_africaamc", "blog_raw_newsource_0825", "blog_raw_fitpet")

DEFAULT_DOC_DIR = Path("data/raw/documents")
DEFAULT_CHUNK_DIR = Path("data/processed/documents/chunks")
DEFAULT_LOG = Path("data/processed/documents/ingest_log.json")

CHUNK_SCHEMA_VERSION = "document-chunk-v1"

# Same length contract as the video chunking (scripts/chunking_config.py), so the
# combined corpus is one corpus rather than two with different chunk sizes silently
# skewing every similarity score. A local copy, not the same dict object, so a test
# harness can monkeypatch this module's CHUNKING without touching the shared default.
CHUNKING = dict(_SHARED_CHUNKING)

# --- header promotion -------------------------------------------------------
#
# Validated against exactly these six documents. It reads a standalone short line as
# a heading, which is true of the blogs here and is NOT a general rule: a bulk ingest
# of the wider crawl pool must re-check it against a fresh sample before trusting it,
# because a false promotion silently shatters a list into one-line sections and a
# missed one buries a section boundary. `chunking_method` records whether a chunk's
# headings were promoted this way, so a corpus can always be filtered back to the
# documents whose structure a person actually looked at.
MAX_HEADING_CHARS = 40
SENTENCE_ENDINGS = (
    "니다.", "습니다.", "합시다.", "세요.", "됩니다.", "다.", "요.", "죠.", "까?",
    "합니다", "좋습니다",
)
# A run of this many consecutive heading-shaped lines is a list, not a stack of
# headings — except its last line, which is promoted when body text follows it.
LIST_RUN_LENGTH = 3
DATE_LINE = re.compile(r"^\d{1,2}월 \d{1,2},? ?\d{0,4}$")

# Naver blog bodies arrive hard-wrapped: the writer broke lines mid-sentence, so a
# "short standalone line" is a phrase, not a heading. Promotion cannot run on these —
# measured on the three crawl documents, 89-100% of their lines are under the heading
# length and their medians are 18-19 characters. Detect the shape and fall back to
# character chunking, which is the rule these documents were always going to hit.
HARD_WRAP_SHORT_SHARE = 0.85
HARD_WRAP_MEDIAN_CHARS = 30

# --- cleaning ---------------------------------------------------------------
#
# Removed: navigation left by the crawler, greetings, promotion, hashtags and clinic
# booking blurbs. Never removed: a line that gives advice. Every dropped line is
# counted and written to the ingest log so the deletion can be argued with.
NAV_EXACT = {
    "이웃추가", "본문 기타 기능", "본문 폰트 크기 조정", "본문 폰트 크기 작게 보기",
    "본문 폰트 크기 크게 보기", "가", "공유하기", "URL복사", "신고하기", "인쇄하기",
    "반려견 행동교정", "댓글", "공감",
}
GREETING = ("안녕하세요", "안녕하십니까")
SIGNATURE_SUBSTRINGS = (
    "한국애견연맹", "훈련사입니다", "애견훈련사", "좋은하루", "좋은 하루",
    "연락하세요", "상담이필요하시면", "상담이 필요하시면", "포스팅을 마칠", "감사합니다",
)
PROMO_SUBSTRINGS = (
    "24시간 진료", "24시간 동물병원", "전화 문의", "방문 및 전화",
    "진료를 받아보세요", "협진을 통해", "예약 문의", "상담 신청",
    "오시는 길", "진료시간", "이웃추가", "구독",
)
HASHTAG = re.compile(r"^\s*(#\S+\s*)+$")
BLOG_SIGNATURE = ("아프리카동물메디컬센터입니다", "서울 강서구에 위치한")

# docs/SOURCES.md > 라이선스·저작권 메모: "robots.txt·ToS로 수집이 금지된 자료,
# 로그인·유료 구간 자료의 무단 수집"은 공정이용 판단에서 불리해지는 케이스로
# 명시돼 있다. mypetlife-kennel-training(슬롯 3, `/premium/...`)이 그 정책을
# 어긴 채로 수집·인제스트까지 되어 사후 제거된 사고 이후, 같은 경로 패턴이
# 다시 들어오면 인제스트 시점에 즉시 막는다.
BLOCKED_URL_PATH_SEGMENTS = ("premium", "member", "paid")
BLOCKED_URL_PATTERN = re.compile(
    r"/(" + "|".join(BLOCKED_URL_PATH_SEGMENTS) + r")(/|\?|#|$)",
    re.IGNORECASE,
)


class IngestError(RuntimeError):
    """Raised when an input document or the manifest is unusable."""


# Every document ingested, and which slot it answers for. Written out rather than
# discovered so that a rerun cannot quietly pull in a seventh document.
MANIFEST = [
    {
        "doc_id": "berrardog-patella-221074570293",
        "slot": "1a",
        "origin": "crawl",
        "crawl_id": "naver_blog-yoonsu3454-221074570293",
        "blog": "베럴독 (네이버 블로그 yoonsu3454)",
        "author": "조재호 애견훈련소장",
    },
    {
        "doc_id": "yd-patella-stages",
        "slot": "1a",
        "origin": "manual",
        "file": "yd_patella.md",
        "blog": "강서YD동물의료센터",
        "author": "강서YD동물의료센터",
    },
    {
        "doc_id": "yd-otitis-externa",
        "slot": "1b",
        "origin": "manual",
        "file": "yd_otitis.md",
        "blog": "강서YD동물의료센터",
        "author": "강서YD동물의료센터",
    },
    {
        "doc_id": "africaamc-night-barking-222955061390",
        "slot": "2",
        "origin": "crawl",
        "crawl_id": "naver_blog-africaamc-222955061390",
        "blog": "아프리카동물메디컬센터 (네이버 블로그 africaamc)",
        "author": "아프리카동물메디컬센터",
    },
    {
        "doc_id": "berrardog-separation-anxiety-222630433514",
        "slot": "3",
        "origin": "crawl",
        "crawl_id": "naver_blog-yoonsu3454-222630433514",
        "blog": "베럴독 (네이버 블로그 yoonsu3454)",
        "author": "조재호 애견훈련소장",
    },
    {
        "doc_id": "salgoonews-kennel-steps-12333",
        "slot": "3",
        "origin": "manual",
        "file": "salgoonews_kennel.md",
        "blog": "살구뉴스",
        "author": "유영지",
    },
    # Track E (2026-08-25) — a third independent blog, deliberately not more of
    # yoonsu3454/africaamc. reports/new_source_procurement_0825.md. A 7th
    # easiestip post (39230461, "화장실 배변 훈련") was dropped before it ever
    # reached this list: its real content was a 216-char teaser stub, the rest
    # was the site's related-post footer.
    {
        "doc_id": "easiestip-wait-training",
        "slot": "vector-new-source-0825",
        "origin": "crawl",
        "crawl_id": "generic-m-easiestip-com-33662647",
        "blog": "더벅한 강아지 (easiestip.com)",
        "author": "더벅한 강아지",
    },
    {
        "doc_id": "easiestip-kennel-training",
        "slot": "vector-new-source-0825",
        "origin": "crawl",
        "crawl_id": "generic-m-easiestip-com-51729265",
        "blog": "더벅한 강아지 (easiestip.com)",
        "author": "더벅한 강아지",
    },
    {
        "doc_id": "easiestip-separation-anxiety-hideseek",
        "slot": "vector-new-source-0825",
        "origin": "crawl",
        "crawl_id": "generic-m-easiestip-com-66536148",
        "blog": "더벅한 강아지 (easiestip.com)",
        "author": "더벅한 강아지",
    },
    {
        "doc_id": "easiestip-isolation-vs-separation-anxiety",
        "slot": "vector-new-source-0825",
        "origin": "crawl",
        "crawl_id": "generic-m-easiestip-com-81848586",
        "blog": "더벅한 강아지 (easiestip.com)",
        "author": "더벅한 강아지",
    },
    {
        "doc_id": "easiestip-bell-training",
        "slot": "vector-new-source-0825",
        "origin": "crawl",
        "crawl_id": "generic-m-easiestip-com-88606952",
        "blog": "더벅한 강아지 (easiestip.com)",
        "author": "더벅한 강아지",
    },
    {
        "doc_id": "easiestip-bark-on-command",
        "slot": "vector-new-source-0825",
        "origin": "crawl",
        "crawl_id": "generic-m-easiestip-com-91597821",
        "blog": "더벅한 강아지 (easiestip.com)",
        "author": "더벅한 강아지",
    },
    # Handled and vetted 2026-08-24 (reports/graphrag_final_attempt_stage1_sourcing_0824.md),
    # briefly ingested and rolled back with the rest of the failed 68-doc expansion
    # (reports/corpus_expansion_0825.md), re-added here alone — a 4th independent
    # voice (a pet-commerce company blog), not more volume from an existing one.
    {
        "doc_id": "fitpet-fence-training",
        "slot": "vector-new-source-0825",
        "origin": "crawl",
        "crawl_id": "generic-www-fitpetmall-com-92633876",
        "blog": "핏펫(Fitpet)",
        "author": "핏펫",
    },
    {
        "doc_id": "fitpet-potty-training",
        "slot": "vector-new-source-0825",
        "origin": "crawl",
        "crawl_id": "generic-www-fitpetmall-com-81774060",
        "blog": "핏펫(Fitpet)",
        "author": "핏펫",
    },
]


def load_crawl_pool(root: Path) -> dict[str, dict[str, Any]]:
    pool: dict[str, dict[str, Any]] = {}
    for name in CRAWL_POOLS:
        path = root / name / "posts.jsonl"
        if not path.is_file():
            raise IngestError(f"crawl pool not found: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                pool[row["doc_id"]] = row
    return pool


def check_url_allowed(url: str, doc_id: str) -> None:
    """Refuse a source URL whose path names a login/paid section.

    Enforces docs/SOURCES.md's "로그인·유료 구간 자료의 무단 수집" exclusion at
    collection time, rather than relying on a person to notice a paywalled URL
    during selection — that is exactly how mypetlife-kennel-training got in.
    """
    match = BLOCKED_URL_PATTERN.search(url)
    if match:
        segment = match.group(1)
        raise IngestError(
            f"{doc_id}: source_url contains blocked path segment '/{segment}/' ({url}) — "
            "docs/SOURCES.md의 '로그인·유료 구간 자료의 무단 수집' 배제 정책에 걸림. "
            "유료/로그인 구간 콘텐츠는 수집 대상에서 제외할 것."
        )


def read_manual(path: Path) -> dict[str, str]:
    """Read a hand-saved markdown file and its three-line header."""
    if not path.is_file():
        raise IngestError(f"manual document not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    for index, line in enumerate(lines[:5]):
        match = re.match(r"^(source_url|source|collected_at):\s*(.+)$", line.strip())
        if match:
            meta[match.group(1)] = match.group(2).strip()
            body_start = index + 1
        elif line.strip():
            break
    for key in ("source_url", "source", "collected_at"):
        if key not in meta:
            raise IngestError(f"{path}: missing '{key}' in the first lines")
    meta["body"] = "\n".join(lines[body_start:]).strip("\n")
    return meta


def clean(lines: Sequence[str]) -> tuple[list[str], list[str]]:
    """Drop navigation, greetings, promotion and hashtags. Return kept and dropped."""
    kept: list[str] = []
    dropped: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            kept.append("")
            continue
        if text in NAV_EXACT or DATE_LINE.match(text) or HASHTAG.match(text):
            dropped.append(text)
            continue
        if any(text.startswith(g) for g in GREETING):
            dropped.append(text)
            continue
        if any(sig in text for sig in BLOG_SIGNATURE) and len(text) < 60:
            dropped.append(text)
            continue
        if any(promo in text for promo in PROMO_SUBSTRINGS):
            dropped.append(text)
            continue
        if any(sig in text for sig in SIGNATURE_SUBSTRINGS) and len(text) < 45:
            dropped.append(text)
            continue
        kept.append(line.rstrip())
    # collapse runs of blank lines produced by the removals
    collapsed: list[str] = []
    for line in kept:
        if not line and collapsed and not collapsed[-1]:
            continue
        collapsed.append(line)
    return [l for l in collapsed], dropped


def is_hard_wrapped(lines: Sequence[str]) -> bool:
    """Whether the writer broke lines mid-sentence rather than at paragraph ends."""
    body = [l.strip() for l in lines if l.strip()]
    if len(body) < 10:
        return False
    lengths = sorted(len(l) for l in body)
    median = lengths[len(lengths) // 2]
    short_share = sum(1 for n in lengths if n <= MAX_HEADING_CHARS) / len(lengths)
    return short_share >= HARD_WRAP_SHORT_SHARE and median <= HARD_WRAP_MEDIAN_CHARS


def is_heading_shaped(text: str) -> bool:
    text = text.strip()
    if not text or text.startswith("#") or len(text) > MAX_HEADING_CHARS:
        return False
    if DATE_LINE.match(text):
        return False
    return not text.endswith(SENTENCE_ENDINGS)


def promote_headings(lines: Sequence[str]) -> tuple[list[str], int]:
    """Turn heading-shaped standalone lines into '## ' headings.

    A run of LIST_RUN_LENGTH or more such lines is a list and is left as body text,
    except for its final line when body text follows it — that line introduces the
    next section rather than closing the list.
    """
    body = [(index, line) for index, line in enumerate(lines) if line.strip()]
    flags = [is_heading_shaped(line) for _, line in body]
    promote: set[int] = set()
    position = 0
    while position < len(body):
        if not flags[position]:
            position += 1
            continue
        end = position
        while end < len(body) and flags[end]:
            end += 1
        run = body[position:end]
        if len(run) < LIST_RUN_LENGTH:
            promote.update(index for index, _ in run)
        elif end < len(body):
            promote.add(run[-1][0])
        position = end

    out = list(lines)
    for index in sorted(promote):
        out[index] = "## " + out[index].strip()
    return out, len(promote)


def split_sections(lines: Sequence[str]) -> list[dict[str, Any]]:
    """Split on '## ' headings. The text before the first heading is a lead section."""
    sections: list[dict[str, Any]] = []
    current = {"heading": None, "lines": []}
    for line in lines:
        if line.startswith("## "):
            if any(l.strip() for l in current["lines"]) or current["heading"]:
                sections.append(current)
            current = {"heading": line[3:].strip(), "lines": []}
        else:
            current["lines"].append(line)
    if any(l.strip() for l in current["lines"]) or current["heading"]:
        sections.append(current)
    return sections


def split_chars(text: str, settings: dict[str, int] = CHUNKING, reserved: int = 0) -> list[str]:
    """Greedy paragraph-then-sentence packing to the v3 target, capped at max_chars.

    `reserved` is the room the heading breadcrumb will take once it is prepended, so
    the finished chunk honours max_chars rather than the body alone doing so.
    """
    target = max(1, settings["target_chars"] - reserved)
    maximum = max(target, settings["max_chars"] - reserved)
    units: list[str] = []
    for block in [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]:
        if len(block) <= maximum:
            units.append(block)
            continue
        sentence = ""
        for piece in re.split(r"(?<=[.!?。])\s+|\n", block):
            piece = piece.strip()
            if not piece:
                continue
            if len(sentence) + len(piece) + 1 > maximum and sentence:
                units.append(sentence)
                sentence = piece
            else:
                sentence = f"{sentence} {piece}".strip()
        if sentence:
            units.append(sentence)

    chunks: list[str] = []
    buffer = ""
    for unit in units:
        candidate = f"{buffer}\n{unit}".strip() if buffer else unit
        if len(candidate) > maximum and buffer:
            chunks.append(buffer)
            buffer = unit
        elif len(candidate) >= target:
            chunks.append(candidate)
            buffer = ""
        else:
            buffer = candidate
    if buffer:
        # A short tail joins the previous chunk when that keeps it under the ceiling,
        # rather than standing as a fragment below min_chars.
        if chunks and len(chunks[-1]) + len(buffer) + 1 <= maximum:
            chunks[-1] = f"{chunks[-1]}\n{buffer}"
        else:
            chunks.append(buffer)
    return [c for c in chunks if c.strip()]


def chunk_id_for(text: str) -> str:
    return "docchunk-" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_chunks(
    entry: dict[str, Any],
    title: str,
    lines: Sequence[str],
    auto_promoted: int,
    hard_wrapped: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    sections = split_sections(lines)
    header_sections = [s for s in sections if s["heading"]]
    if header_sections:
        method = "header+char_v3" + ("(auto_promoted)" if auto_promoted else "(manual_headings)")
    elif hard_wrapped:
        method = "char_v3_fallback(hard_wrapped)"
    else:
        method = "char_v3_fallback"

    records: list[dict[str, Any]] = []
    outline: list[str] = []
    index = 0
    # A heading with no body of its own is a parent ("주요 원인" above four causes).
    # Emitting it as its own chunk yields a title-only fragment that answers nothing,
    # so it is carried down into the sections it introduces instead — which is also
    # the nesting a parent-child retriever will want to read off heading_path later.
    pending_parents: list[str] = []
    for section in sections:
        heading = section["heading"]
        body = "\n".join(section["lines"]).strip()
        if not body and not heading:
            continue
        if not body and heading:
            pending_parents.append(heading)
            outline.append("  {} [부모 헤더]".format(heading))
            continue
        path = [title] + pending_parents + ([heading] if heading and heading != title else [])
        pending_parents = []
        # The breadcrumb rides in the text because it is part of what the section says;
        # a chunk that reads "1단계 ..." without "슬개골 탈구 단계별 증상" above it is
        # not retrievable by anyone asking about the disease.
        breadcrumb = " > ".join(path)
        pieces = split_chars(body, reserved=len(breadcrumb) + 1) if body else [""]
        for piece in pieces:
            text = f"{breadcrumb}\n{piece}".strip()
            records.append({
                "schema_version": CHUNK_SCHEMA_VERSION,
                "chunk_id": chunk_id_for(text),
                "doc_id": entry["doc_id"],
                "chunk_index": index,
                "source_url": entry["source_url"],
                "slot": entry["slot"],
                "chunking_method": method,
                "heading_path": path,
                "text": text,
                "char_count": len(text),
                "embedding_eligible": True,
                "chunking": dict(CHUNKING),
            })
            index += 1
        outline.append("{}{} [{}청크]".format(
            "  " if heading else "", " > ".join(path[1:]) or "(도입부)",
            len(pieces)))
    return records, outline


def front_matter(entry: dict[str, Any], removed: int, method: str) -> str:
    return "\n".join([
        "---",
        f"doc_id: {entry['doc_id']}",
        f"slot: {entry['slot']}",
        f"source_url: {entry['source_url']}",
        f"blog: {entry['blog']}",
        f"author: {entry['author']}",
        f"collected_at: {entry['collected_at']}",
        f"origin: {entry['origin']}",
        f"chunking_method: {method}",
        f"removed_paragraphs: {removed}",
        "license: 출처 명기 · 데모 내부 사용 · 재배포 없음",
        "---",
        "",
    ])


def ingest(
    crawl_root: Path,
    doc_dir: Path,
    chunk_dir: Path,
    log_path: Path,
) -> dict[str, Any]:
    pool = load_crawl_pool(crawl_root)
    doc_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    log: list[dict[str, Any]] = []
    total_chunks = 0
    for entry in MANIFEST:
        entry = dict(entry)
        if entry["origin"] == "crawl":
            row = pool.get(entry["crawl_id"])
            if row is None:
                raise IngestError(f"{entry['doc_id']}: {entry['crawl_id']} not in the crawl pool")
            entry["source_url"] = row["url"]
            entry["collected_at"] = row["fetched_at"][:10]
            title = row["title"].strip()
            raw_lines = row["text"].splitlines()
        else:
            meta = read_manual(crawl_root / "manual" / entry["file"])
            entry["source_url"] = meta["source_url"]
            entry["collected_at"] = meta["collected_at"]
            raw_lines = meta["body"].splitlines()
            title = ""
            for line in raw_lines:
                if line.startswith("## "):
                    title = line[3:].strip()
                    break
            raw_lines = [l for l in raw_lines if not (l.startswith("## ") and l[3:].strip() == title)]

        check_url_allowed(entry["source_url"], entry["doc_id"])

        kept, dropped = clean(raw_lines)
        # The title is repeated as the first body line by the crawler; drop the echo.
        kept = [l for l in kept if l.strip() != title]
        hard_wrapped = is_hard_wrapped(kept)
        if hard_wrapped:
            # Promotion here would read sentence fragments as headings. Measured before
            # this guard existed, it turned a 2,206-character article into 40 sections
            # averaging 55 characters, with headings like "그 대처 방법, 나아가 동물병원에 가는 것이".
            promoted_lines, promoted_count = list(kept), 0
        else:
            promoted_lines, promoted_count = promote_headings(kept)
        records, outline = build_chunks(
            entry, title, promoted_lines, promoted_count, hard_wrapped
        )
        if not records:
            raise IngestError(f"{entry['doc_id']}: produced no chunk")

        method = records[0]["chunking_method"]
        (doc_dir / f"{entry['doc_id']}.md").write_bytes(
            (front_matter(entry, len(dropped), method)
             + f"## {title}\n\n" + "\n".join(promoted_lines).strip() + "\n").encode("utf-8")
        )
        (chunk_dir / f"{entry['doc_id']}.jsonl").write_bytes(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf-8")
        )
        total_chunks += len(records)
        log.append({
            "doc_id": entry["doc_id"],
            "slot": entry["slot"],
            "title": title,
            "source_url": entry["source_url"],
            "origin": entry["origin"],
            "chunking_method": method,
            "auto_promoted_headings": promoted_count,
            "hard_wrapped": hard_wrapped,
            "removed_paragraphs": len(dropped),
            "removed_samples": dropped[:12],
            "chunks": len(records),
            "chars": sum(r["char_count"] for r in records),
            "max_chunk_chars": max(r["char_count"] for r in records),
            "outline": outline,
        })

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(
        json.dumps({"chunking": CHUNKING, "documents": log}, ensure_ascii=False, indent=2)
        .encode("utf-8")
    )
    return {"documents": len(log), "chunks": total_chunks, "log": log}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crawl-root", type=Path, default=CRAWL_ROOT)
    parser.add_argument("--doc-dir", type=Path, default=DEFAULT_DOC_DIR)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = ingest(args.crawl_root, args.doc_dir, args.chunk_dir, args.log)
    except (OSError, IngestError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"문서 {result['documents']}건 -> 청크 {result['chunks']}개")
    for row in result["log"]:
        print(f"  [{row['slot']}] {row['doc_id']}: {row['chunks']}청크 "
              f"(max {row['max_chunk_chars']}자, 제거 {row['removed_paragraphs']}문단, "
              f"{row['chunking_method']})")
    print(f"로그: {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
