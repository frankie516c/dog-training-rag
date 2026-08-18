"""Put answers produced by hand back into a generation artifact.

While there is no API key, generate_answers.py --dry-run writes prompts and leaves
`answer` null. A person runs those prompts through whatever model they have and
comes back with text. This script is the return leg: it merges that text into the
artifact so the judge pass reads one file that says what was asked, what was
retrieved, which prompt was used and what came back.

The checks here all guard the same thing — that a judged batch is one comparable
batch. Answers made under a different prompt version, answers for a band that
never called a model, and answers silently replacing earlier ones would each make
two rows in the artifact mean different things.

Usage:
    uv run python scripts/backfill_answers.py --answers replies.json \\
        --target data/eval/generation/answers_out_of_corpus_queries.jsonl
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Sequence


def _load_generation() -> Any:
    """Import generate_answers for the schema constants, whatever the cwd is."""
    name = "generate_answers"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise BackfillError(f"cannot import generation code from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class BackfillError(RuntimeError):
    """Raised when the answers file and the target artifact do not agree."""


generation = _load_generation()

DEFAULT_TARGET = Path("data/eval/generation/answers_out_of_corpus_queries.jsonl")


def load_answers(path: Path) -> tuple[dict[str, str], str]:
    """Read the reply document and return (answers, prompt_version)."""
    if not path.is_file():
        raise BackfillError(f"file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BackfillError(f"{path}: expected a JSON object")
    if payload.get("schema_version") != generation.ANSWERS_SCHEMA_VERSION:
        raise BackfillError(
            f"{path}: schema_version must be {generation.ANSWERS_SCHEMA_VERSION!r} "
            f"(got {payload.get('schema_version')!r}). The bundle file prints a "
            "ready-made template."
        )
    prompt_version = payload.get("prompt_version")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        raise BackfillError(f"{path}: prompt_version must say which prompt produced these answers")
    answers = payload.get("answers")
    if not isinstance(answers, dict) or not answers:
        raise BackfillError(f"{path}: answers must be a non-empty object of query_id -> text")
    cleaned: dict[str, str] = {}
    for query_id, text in answers.items():
        if not isinstance(text, str):
            raise BackfillError(f"{path}: answer for {query_id!r} must be a string")
        if text.strip():
            cleaned[str(query_id)] = text
    if not cleaned:
        raise BackfillError(f"{path}: every answer is empty; nothing to backfill")
    return cleaned, prompt_version


def load_target(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise BackfillError(f"file not found: {path}")
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BackfillError(f"invalid JSON at {path}:{number}") from exc
        records.append(row)
    if not records:
        raise BackfillError(f"{path}: no records")
    return records


def backfill(
    answers_path: Path,
    target_path: Path,
    force: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    answers, prompt_version = load_answers(answers_path)
    records = load_target(target_path)
    by_id = {str(row.get("query_id")): row for row in records}

    unknown = sorted(set(answers) - set(by_id))
    if unknown:
        raise BackfillError(
            f"{answers_path}: {len(unknown)} query_id(s) are not in {target_path}: "
            f"{', '.join(unknown[:5])}"
        )

    # Version first: if the answers came from a different prompt, nothing else about
    # this merge is worth checking. Two prompts produce two populations, and a judge
    # score over the mixture measures neither.
    mismatched = sorted(
        query_id for query_id in answers
        if by_id[query_id].get("prompt_version") != prompt_version
    )
    if mismatched:
        found = {by_id[query_id].get("prompt_version") for query_id in mismatched}
        raise BackfillError(
            f"prompt version mismatch: answers say {prompt_version!r}, the artifact says "
            f"{', '.join(repr(item) for item in sorted(found, key=str))} for "
            f"{len(mismatched)} record(s) (e.g. {mismatched[0]}). Answers written against "
            "a different prompt cannot be judged in the same batch; re-run the prompts "
            "from the current bundle."
        )

    refused = sorted(query_id for query_id in answers if by_id[query_id].get("band") == "refuse")
    if refused:
        raise BackfillError(
            f"{len(refused)} answer(s) target the refuse band (e.g. {refused[0]}). "
            "That band never called a model, so its answer is the fixed refusal text. "
            "An answer here means the prompt came from somewhere this artifact cannot "
            "account for. Lower --refuse-below and re-generate if it should have been asked."
        )

    occupied = sorted(
        query_id for query_id in answers
        if by_id[query_id].get("answer") and by_id[query_id].get("generated")
    )
    if occupied and not force:
        raise BackfillError(
            f"{len(occupied)} record(s) already hold an answer (e.g. {occupied[0]}). "
            "Pass --force to replace them, which discards the answers already there."
        )

    for query_id, text in answers.items():
        by_id[query_id]["answer"] = text
        by_id[query_id]["answer_source"] = answers_path.name

    if write:
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records)
        generation.retrieval.write_text(body, target_path)

    pending = [
        str(row.get("query_id")) for row in records
        if row.get("generated") and not row.get("answer")
    ]
    return {
        "records": records,
        "filled": sorted(answers),
        "replaced": occupied,
        "pending": pending,
        "target_path": target_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=Path, required=True, help="JSON of query_id -> answer text")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET, help="generation artifact to fill")
    parser.add_argument("--force", action="store_true", help="replace answers that are already filled")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = backfill(args.answers, args.target, args.force)
    except (OSError, BackfillError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{len(result['filled'])}건 채움 → {result['target_path']}")
    if result["replaced"]:
        print(f"  덮어쓴 답변 {len(result['replaced'])}건: {', '.join(result['replaced'])}")
    if result["pending"]:
        print(f"  아직 비어 있음 {len(result['pending'])}건: {', '.join(result['pending'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
