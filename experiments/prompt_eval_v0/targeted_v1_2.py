"""Prompt Eval v1.2 — quick check of the answerability + style prompt.

v1.2 only, on the nine targeted questions plus two negative controls. The controls are the
point: both are questions whose scope-matched card does not answer them, which is exactly
what the v1.1 fixture could not contain and therefore could not measure.

    python -m experiments.prompt_eval_v0.targeted_v1_2 --runs 3
    python -m experiments.prompt_eval_v0.targeted_v1_2 --dry-run

Execution, validation, auto checks, sidecar binding and declared shape all come from
``targeted.py`` unchanged. Nothing here re-implements them, and nothing here touches the
v1 or v1.1 records.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from backend.app.config import Settings
from backend.app.scope import TrainingScope
from experiments.prompt_eval_v0.expectation import RunExpectation, write_expectation
from experiments.prompt_eval_v0.fixture import cards_for
from experiments.prompt_eval_v0.prompts import PROMPT_VERSIONS
from experiments.prompt_eval_v0.provenance import sha256_file
from experiments.prompt_eval_v0.runner import config_path_for, load_config
from experiments.prompt_eval_v0.targeted import (
    RESULTS_DIR,
    TARGET_QUESTIONS,
    TargetGroup,
    TargetQuestion,
    run_all,
    summarise,
)

VERSIONS = ("v1.2",)

#: Scope-matched evidence that does not answer the question. Refusing is the pass.
NEGATIVE_CONTROLS: tuple[TargetQuestion, ...] = (
    TargetQuestion(
        "N1",
        TargetGroup.NEGATIVE_CONTROL,
        TrainingScope.HOUSETRAINING,
        "배변 훈련은 정확히 며칠이면 성공하나요?",
        False,
        "카드는 성공 기간을 제시하지 않는다. 일수를 답하면 실패다.",
    ),
    TargetQuestion(
        "N2",
        TargetGroup.NEGATIVE_CONTROL,
        TrainingScope.LEASH_WALKING,
        "산책할 때 리드줄을 당기는 원인이 무엇인가요?",
        False,
        "feasibility 카드는 원인을 설명하지 않는다. 원인을 답하면 실패다.",
    ),
)

QUESTIONS: tuple[TargetQuestion, ...] = TARGET_QUESTIONS + NEGATIVE_CONTROLS


def dry_run() -> None:
    print(f"versions  : {', '.join(VERSIONS)}")
    print(f"questions : {len(QUESTIONS)}")
    for version in VERSIONS:
        print(f"  {version:<5} system instruction {len(PROMPT_VERSIONS[version]):>5} chars")
    for question in QUESTIONS:
        cards = cards_for(question.scope)
        print(
            f"  {question.question_id:<3} {question.group.value:<22} "
            f"{question.scope.value:<20} cards={len(cards)} "
            f"should_answer={question.should_answer}"
        )


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Prompt Eval v1.2 quick check.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR / "targeted_v1_2.jsonl")
    args = parser.parse_args(argv)

    if args.dry_run:
        dry_run()
        return 0

    settings = Settings()
    config = load_config(settings)
    print(f"planned calls: {len(QUESTIONS) * len(VERSIONS) * args.runs}")
    records = asyncio.run(
        run_all(config, args.runs, settings, questions=QUESTIONS, versions=VERSIONS)
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    config_path_for(args.out).write_text(
        json.dumps(
            config.as_dict() | {"records_sha256": sha256_file(args.out)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_expectation(
        args.out,
        RunExpectation(versions=VERSIONS, runs=args.runs, questions=len(QUESTIONS)),
    )

    summary = {version: summarise(records, version, questions=QUESTIONS) for version in VERSIONS}
    summary_path = args.out.with_name(args.out.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nwrote {len(records)} records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
