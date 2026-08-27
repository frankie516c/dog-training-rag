"""Ingest tier-2 (official/authoritative) PDF position statements into the document corpus.

Companion to ingest_documents.py, not a replacement: that script owns the six
hand-picked Naver-blog/vet-clinic HTML documents and their Korean-specific heading
heuristics (promote_headings, is_hard_wrapped — tuned on particle endings like "다."
that do not exist in English PDF text). This script owns a structurally different
source: short (2-6 page) English-language PDF position statements from veterinary/
behavior authorities (AVSAB and similar), which have no HTML DOM to find headings in
and are short enough that one lead section plus character packing is the right
granularity — there is no multi-section navigation to preserve.

Reuses split_sections/split_chars/chunk_id_for/check_url_allowed/CHUNK_SCHEMA_VERSION
from ingest_documents.py rather than re-implementing them, so a PDF chunk and an HTML
chunk are structurally the same record and run_combined_retrieval_eval.py does not
need to know which pipeline produced either one. CHUNKING comes from the shared
scripts/chunking_config.py so the whole corpus — video, blog, PDF — obeys one length
contract.

This is a staging script, not a MANIFEST-writer: it produces candidate chunks marked
NOT_INGESTED and never touches ingest_documents.py's MANIFEST/CRAWL_POOLS. A human
(or a later, separate ingestion step) decides whether a candidate actually joins the
searchable corpus.

Usage:
    uv run python scripts/ingest_pdf_documents.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))
from ingest_documents import (  # noqa: E402
    AUTHORITY_BY_ROLE,
    CHUNK_SCHEMA_VERSION,
    CHUNKING,
    ROLE_DOCUMENT_BODY,
    check_url_allowed,
    chunk_id_for,
    split_chars,
    split_sections,
    text_sha256,
)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_OUT_DIR = Path("data/raw/documents_candidate_0825_avsab")

# Repeats on every page of these PDFs — masthead/footer, not content. Stripped so it
# does not get chunked three times per page and does not pollute embeddings with
# boilerplate that answers no question a reader would ask.
BOILERPLATE_LINES = (
    "American Veterinary Society",
    "of Animal Behavior",
    "www.AVSAB.org",
    "www.avsabonline.org",
)

# Candidates staged this round. Each is a standalone PDF position statement, not a
# blog post — no "author"/"blog" handle to attribute, only the issuing organization.
CANDIDATES = [
    {
        "doc_id": "avsab-humane-dog-training-2021",
        "source_url": "https://avsab.org/wp-content/uploads/2021/08/AVSAB-Humane-Dog-Training-Position-Statement-2021.pdf",
        "pdf_path": "data/scratch/avsab_pdf_raw/humane-dog-training.pdf",
        "title": "AVSAB Position Statement on Humane Dog Training (2021)",
        "org": "American Veterinary Society of Animal Behavior (AVSAB)",
    },
    {
        "doc_id": "avsab-puppy-socialization-2014",
        "source_url": "https://avsab.org/wp-content/uploads/2018/03/Puppy_Socialization_Position_Statement_Download_-_10-3-14.pdf",
        "pdf_path": "data/scratch/avsab_pdf_raw/puppy-socialization.pdf",
        "title": "AVSAB Position Statement on Puppy Socialization",
        "org": "American Veterinary Society of Animal Behavior (AVSAB)",
    },
    {
        "doc_id": "avsab-dominance-theory-2014",
        "source_url": "https://avsab.org/wp-content/uploads/2018/03/Dominance_Position_Statement_download-10-3-14.pdf",
        "pdf_path": "data/scratch/avsab_pdf_raw/dominance-theory.pdf",
        "title": "AVSAB Position Statement on the Use of Dominance Theory in Behavior Modification",
        "org": "American Veterinary Society of Animal Behavior (AVSAB)",
    },
]


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln and not any(b in ln for b in BOILERPLATE_LINES)]
        # A lone page number line ("1", "2 of 4") is pagination, not content.
        lines = [ln for ln in lines if not re.match(r"^\d{1,3}(\s+of\s+\d{1,3})?$", ln)]
        pages.append("\n".join(lines))
    text = "\n\n".join(pages)
    # pypdf sometimes emits control/replacement characters for PDF ligatures and
    # smart quotes it cannot map; normalize the common ones rather than leaving
    # mojibake in what an embedding model will read as real tokens.
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = re.sub(r"[�’‘]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def build_chunks(entry: dict[str, Any], text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    sections = split_sections(lines)  # no "## " markers present -> one lead section
    records: list[dict[str, Any]] = []
    index = 0
    for section in sections:
        body = "\n".join(section["lines"]).strip()
        if not body:
            continue
        breadcrumb = entry["title"]
        pieces = split_chars(body, reserved=len(breadcrumb) + 1)
        for piece in pieces:
            chunk_text = f"{breadcrumb}\n{piece}".strip()
            # v2: chunk_id는 정체성 payload 기반이다. 이 스크립트는 문서 청커의
            # 규약을 그대로 따라야 한다 — 한쪽만 v1에 남으면 코퍼스에 스키마가
            # 섞이고, 실제로 그런 상태가 한 번 만들어졌었다(AVSAB 115청크만 v1).
            # AVSAB PDF는 Q&A가 아니므로 역할은 항상 DOCUMENT_BODY다.
            role = ROLE_DOCUMENT_BODY
            authority = AUTHORITY_BY_ROLE[role]
            payload = {
                "schema_version": CHUNK_SCHEMA_VERSION,
                "doc_id": entry["doc_id"],
                "chunk_index": index,
                "qa_id": None,
                "segment_role": role,
                "text_sha256": text_sha256(chunk_text),
                **{k: CHUNKING[k] for k in
                   ("target_chars", "min_chars", "max_chars", "overlap_segments")},
            }
            records.append({
                "schema_version": CHUNK_SCHEMA_VERSION,
                "chunk_id": chunk_id_for(payload),
                "doc_id": entry["doc_id"],
                "chunk_index": index,
                "source_url": entry["source_url"],
                "slot": "tier2-avsab-candidate",
                "chunking_method": "pdf_char_v3(no_headings)",
                "heading_path": [entry["title"]],
                "text": chunk_text,
                "char_count": len(chunk_text),
                "embedding_eligible": True,
                "chunking": dict(CHUNKING),
                "qa_id": None,
                "segment_role": role,
                **authority,
            })
            index += 1
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []

    for entry in CANDIDATES:
        check_url_allowed(entry["source_url"], entry["doc_id"])
        pdf_path = Path(entry["pdf_path"])
        if not pdf_path.is_file():
            print(f"[skip] {entry['doc_id']}: PDF not found at {pdf_path} (download it first)")
            continue

        text = extract_pdf_text(pdf_path)
        records = build_chunks(entry, text)
        if not records:
            print(f"[skip] {entry['doc_id']}: produced no chunk")
            continue

        chunk_path = args.out_dir / f"{entry['doc_id']}.jsonl"
        chunk_path.write_bytes(
            ("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n").encode("utf-8")
        )

        frontmatter = "\n".join([
            "---",
            f"doc_id: {entry['doc_id']}",
            "slot: tier2-avsab-candidate",
            f"source_url: {entry['source_url']}",
            f"org: {entry['org']}",
            "collected_at: 2026-08-25",
            "origin: pdf-download",
            "status: NOT_INGESTED — scripts/ingest_pdf_documents.py 산출물, ingest_documents.py MANIFEST 미등록",
            "license_note: [주의] AVSAB 사이트에 명시적 재이용 조건 문구 없음 — 로그인/유료 없이 공개 배포되고",
            "  \"지역 인쇄소에서 인쇄 가능\"이라 안내돼 개인 학습·비공개 RAG 인덱싱 목적엔 이 저장소의 기존",
            "  블로그 수집과 같은 수준의 위험으로 판단했으나(SOURCES.md 정책), 명문 허가는 아니므로 공개 배포",
            "  전 재확인 필요.",
            "---",
            "",
            f"# {entry['title']}",
            "",
            text,
        ])
        (args.out_dir / f"{entry['doc_id']}.md").write_text(frontmatter, encoding="utf-8")

        log.append({
            "doc_id": entry["doc_id"],
            "chunks": len(records),
            "chars": sum(r["char_count"] for r in records),
            "max_chunk_chars": max(r["char_count"] for r in records),
        })
        print(f"[ok] {entry['doc_id']}: {len(records)} chunks, "
              f"max {max(r['char_count'] for r in records)} chars")

    (args.out_dir / "pdf_ingest_log.json").write_bytes(
        json.dumps({"chunking": CHUNKING, "documents": log}, ensure_ascii=False, indent=2).encode("utf-8")
    )
    print(f"\nlog: {args.out_dir / 'pdf_ingest_log.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
