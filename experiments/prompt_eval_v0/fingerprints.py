"""Bind the existing semantic labels to the exact responses they were written about.

Run once against the frozen v0 records. It reads only; the records file is never rewritten.

    python -m experiments.prompt_eval_v0.fingerprints
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from experiments.prompt_eval_v0.provenance import response_fingerprint, sha256_file
from experiments.prompt_eval_v0.semantic_review import (
    CONCERN_JUDGEMENTS,
    CRITICAL_JUDGEMENTS,
    RESISTED_WHILE_ANSWERING,
)

RESULTS_DIR = Path(__file__).parent / "results"
RECORDS_PATH = RESULTS_DIR / "prompt_only.jsonl"
OUT_PATH = RESULTS_DIR / "semantic_label_fingerprints.json"


def labelled_coordinates() -> set[tuple[str, str, int]]:
    coordinates = {
        (j.question_id, j.prompt_version, j.run_number)
        for j in (*CRITICAL_JUDGEMENTS, *CONCERN_JUDGEMENTS)
    }
    return coordinates | set(RESISTED_WHILE_ANSWERING)


def load_records() -> list[dict]:
    records = []
    for line in RECORDS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if "prompt_version" in payload:
            records.append(payload)
    return records


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    records = {(r["question_id"], r["prompt_version"], r["run_number"]): r for r in load_records()}

    fingerprints: dict[str, str] = {}
    missing: list[str] = []
    for coordinate in sorted(labelled_coordinates()):
        record = records.get(coordinate)
        key = "|".join(str(part) for part in coordinate)
        if record is None:
            missing.append(key)
            continue
        fingerprints[key] = response_fingerprint(record)

    OUT_PATH.write_text(
        json.dumps(
            {
                "records_sha256": sha256_file(RECORDS_PATH),
                "note": (
                    "각 semantic label이 작성된 시점의 응답 지문. 저장된 응답이 이 값과 "
                    "다르면 label을 적용하지 않고 unreviewed로 처리한다."
                ),
                "fingerprints": fingerprints,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"labelled coordinates : {len(labelled_coordinates())}")
    print(f"fingerprints written : {len(fingerprints)}")
    print(f"missing records      : {missing or 'none'}")
    print(f"wrote {OUT_PATH}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
