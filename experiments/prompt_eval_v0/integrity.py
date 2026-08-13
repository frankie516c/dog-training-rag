"""Freeze the raw run: verify its shape and hash every input that produced it.

Read-only. The records file is never rewritten, normalised or corrected — if a record is
malformed that is a finding, not something to repair.

    python -m experiments.prompt_eval_v0.integrity
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from experiments.prompt_eval_v0.expectation import (
    check_against,
    expectation_path,
    load_expectation,
    satisfied,
)
from experiments.prompt_eval_v0.fixture import QUESTIONS, cards_for
from experiments.prompt_eval_v0.loading import load_run
from experiments.prompt_eval_v0.prompts import PROMPT_VERSIONS
from experiments.prompt_eval_v0.provenance import git_state, sanitize_config

PACKAGE_DIR = Path(__file__).parent
RESULTS_DIR = PACKAGE_DIR / "results"
RECORDS_PATH = RESULTS_DIR / "prompt_only.jsonl"
VERSIONS = ("v0", "v1", "v2")

REPO_ROOT = PACKAGE_DIR.parents[1]

#: Everything that can change a prompt, a screen or a reported number. The v0 manifest
#: hashed five files and omitted the evidence JSONL that actually determines every prompt,
#: so editing a claim left the manifest fully green.
HASHED_INPUTS = (
    RECORDS_PATH,
    PACKAGE_DIR / "prompts.py",
    PACKAGE_DIR / "fixture.py",
    PACKAGE_DIR / "runner.py",
    PACKAGE_DIR / "checks.py",
    PACKAGE_DIR / "analyze.py",
    PACKAGE_DIR / "integrity.py",
    PACKAGE_DIR / "review.py",
    PACKAGE_DIR / "semantic_review.py",
    PACKAGE_DIR / "provenance.py",
    PACKAGE_DIR / "loading.py",
    PACKAGE_DIR / "fingerprints.py",
    PACKAGE_DIR / "targeted.py",
    PACKAGE_DIR / "e2e.py",
    PACKAGE_DIR / "gate_control.py",
    # Determines critical_failures: without it no semantic label applies.
    RESULTS_DIR / "semantic_label_fingerprints.json",
    # Declares the run shape; deletion is undetectable without it.
    expectation_path(RECORDS_PATH),
    REPO_ROOT / "backend" / "app" / "grounded.py",
    REPO_ROOT / "data" / "processed" / "evidence_cards.jsonl",
    REPO_ROOT / "data" / "sources" / "source_registry.jsonl",
)

#: Known gaps between what produced the v0 records and what is hashed here. Recorded so a
#: reader is not misled into treating these hashes as the exact execution provenance.
PROVENANCE_LIMITATIONS = (
    "fixture.py와 checks.py는 실행 시작 후 비의미적 편집(주석 문자열, 정규식 상수 추출)을 "
    "받았다. 아래 hash는 현재 파일 기준이며, 실행 시점의 source hash는 보존되지 않았다.",
    "runner.py는 실행 후 generation config를 별도 파일에 쓰도록 수정됐다. 아래 hash는 "
    "수정 후 파일이며 v0 레코드를 생성한 버전이 아니다.",
    "prompt_only.jsonl은 첫 줄이 config object인 혼합 JSONL이다. 원본은 그대로 두고, "
    "이후 실행부터 config는 <records>_config.json 사이드카에 기록된다.",
    "저장된 자동 검사 결과를 현재 checks.py로 재계산한 결과는 126건 전부 일치했다. "
    "이는 편집이 결과를 바꾸지 않았다는 증거이며, source hash 보존을 대체하지 않는다.",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ollama_digest(model: str) -> str | None:
    """Best-effort model digest. Absence is recorded, never fabricated."""

    try:
        completed = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in completed.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == model and len(parts) > 1:
            return parts[1]
    return None


def check_records(path: Path) -> dict:
    raw = path.read_bytes().decode("utf-8")
    physical_lines = raw.count("\n") + (0 if raw.endswith("\n") else 1)
    stripped = [line for line in raw.split("\n") if line.strip()]

    config: dict = {}
    records: list[dict] = []
    malformed: list[int] = []
    for index, line in enumerate(stripped, 1):
        try:
            payload = json.loads(line)
        except ValueError:
            malformed.append(index)
            continue
        if "config" in payload and "prompt_version" not in payload:
            config = payload["config"]
            continue
        records.append(payload)

    keys = Counter(
        (record["prompt_version"], record["question_id"], record["run_number"])
        for record in records
    )
    duplicates = sorted(key for key, count in keys.items() if count > 1)

    per_version = Counter(record["prompt_version"] for record in records)
    # Any shape check derived from the observed data is blind to deletion, so the declared
    # expectation is the authority. `per_question` stays for the human-readable report.
    expectation = load_expectation(path)
    shape_vs_declared = check_against(expectation, records)
    missing = shape_vs_declared["incomplete_version_question_pairs"]

    # The same question and the same fixed context must have been sent to every version.
    context_consistent = True
    for question in QUESTIONS:
        expected_ids = [str(card.card_id) for card in cards_for(question.scope)]
        rows = [r for r in records if r["question_id"] == question.question_id]
        for row in rows:
            if row["message"] != question.message or row["card_ids"] != expected_ids:
                context_consistent = False

    return {
        "physical_lines": physical_lines,
        "non_empty_lines": len(stripped),
        "trailing_newline": raw.endswith("\n"),
        "config_lines": 1 if config else 0,
        "record_objects": len(records),
        "malformed_lines": malformed,
        "unique_keys": len(keys),
        "duplicate_keys": [list(key) for key in duplicates],
        "per_version": dict(per_version),
        "missing_or_extra_question_runs": missing,
        "declared_shape_check": shape_vs_declared,
        "matches_declared_shape": satisfied(shape_vs_declared),
        "question_and_context_identical_across_versions": context_consistent,
        # Sanitised: the legacy inline config carries a raw base_url.
        "generation_config": sanitize_config(config),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not RECORDS_PATH.exists():
        raise SystemExit(f"missing {RECORDS_PATH}")

    # check_records first: it reports malformed lines by number, and load_run would raise
    # an uncaught JSONDecodeError on the same input, losing that diagnostic.
    shape = check_records(RECORDS_PATH)
    if shape["malformed_lines"]:
        print(json.dumps(shape, ensure_ascii=False, indent=2))
        print(f"\nintegrity: FAILED — malformed lines {shape['malformed_lines']}")
        return 1
    # Fail closed rather than recording model="" while still printing OK.
    loaded = load_run(RECORDS_PATH)
    model = loaded.config["model"]

    manifest = {
        "records_path": str(RECORDS_PATH.relative_to(PACKAGE_DIR.parents[1])),
        "records_file_layout": (
            "mixed JSONL: line 1 is the run config object, lines 2..n are records"
        ),
        "provenance_limitations": list(PROVENANCE_LIMITATIONS),
        "shape": shape,
        # POSIX keys so two manifests of the same tree diff across machines. A missing
        # input is recorded as missing rather than silently dropped from the list.
        "input_sha256": {
            path.relative_to(PACKAGE_DIR.parents[1]).as_posix(): (
                sha256_file(path) if path.exists() else None
            )
            for path in HASHED_INPUTS
        },
        "missing_inputs": [
            path.relative_to(PACKAGE_DIR.parents[1]).as_posix()
            for path in HASHED_INPUTS
            if not path.exists()
        ],
        "prompt_sha256": {version: sha256_text(text) for version, text in PROMPT_VERSIONS.items()},
        "prompt_chars": {version: len(text) for version, text in PROMPT_VERSIONS.items()},
        "model": model,
        "ollama_model_digest": ollama_digest(model),
        "config_source": loaded.config_source,
        "endpoint": loaded.config.get("endpoint")
        or {"legacy_raw_base_url_present": "base_url" in loaded.config},
        "git": git_state(REPO_ROOT),
    }

    out = RESULTS_DIR / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(shape, ensure_ascii=False, indent=2))
    print("\ninput sha256")
    for name, digest in manifest["input_sha256"].items():
        print(f"  {name:<48} {digest}")
    print("\nprompt sha256")
    for version, digest in manifest["prompt_sha256"].items():
        print(f"  {version:<4} {manifest['prompt_chars'][version]:>5} chars  {digest}")
    print(f"\nmodel: {model}  digest: {manifest['ollama_model_digest']}")
    print(f"wrote {out}")

    # Counts derive from the data, not from a hardcoded 126/42/3, so a --runs 5 file is
    # judged on its own shape.
    ok = (
        shape["record_objects"] > 0
        and not shape["malformed_lines"]
        and not shape["duplicate_keys"]
        and shape["matches_declared_shape"]
        and shape["question_and_context_identical_across_versions"]
        and bool(model)
        and not manifest["missing_inputs"]
    )
    print(f"\nintegrity: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
