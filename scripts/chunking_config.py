"""Shared chunking length contract for the vector-only corpus.

`chunk_approved_youtube.py` (video) and `ingest_documents.py` (document) both
chunk to this same char budget so the combined corpus is one corpus rather than
two with different chunk sizes silently skewing every similarity score. Kept in
one module, not duplicated as two local constants, so the two scripts cannot
drift apart without someone noticing the import.

These are the v3 values, adopted 2026-08-20 after a v1(220/80/320) vs v3
comparison (data/eval/results/baseline_v1_e5_report.md vs exp_a2_v3_e5_report.md,
Hit@1 0.583 -> 0.667). A larger v4(600/220/650) trial was re-tested 2026-08-25
after GraphRAG was dropped (docs/decision_graphrag_abandoned_0824.md removed the
old constraint that chunk size had to match the graph-extraction unit) — v4
measured *worse* on the same harness (Hit@1 0.667 -> 0.5, MRR@5 0.708 -> 0.590),
so v3 stays. See reports/chunking_v4_experiment_0825.md for the full comparison.

Changing any value here re-chunks (re-hashes) the entire corpus on the next run
of either chunker — `chunk_id` hashes these settings.
"""

TARGET_CHARS = 420
MIN_CHARS = 150
MAX_CHARS = 480
OVERLAP_SEGMENTS = 0

CHUNKING = {
    "target_chars": TARGET_CHARS,
    "min_chars": MIN_CHARS,
    "max_chars": MAX_CHARS,
    "overlap_segments": OVERLAP_SEGMENTS,
}
