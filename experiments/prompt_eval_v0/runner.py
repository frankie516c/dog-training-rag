"""Prompt-only evaluation runner.

Retrieval is deliberately excluded: each question is bound to a fixed EvidenceCard context,
so any difference between runs comes from the prompt or from the model's own variance, not
from a different search result. The winning prompt is measured again with real retrieval by
a separate script.

    python -m experiments.prompt_eval_v0.runner --runs 3
    python -m experiments.prompt_eval_v0.runner --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from backend.app.config import Settings
from backend.app.domain import ContentLanguage
from backend.app.generation import GenerationError, OpenAICompatibleGenerationProvider
from backend.app.grounded import DraftVerdict, validate_draft
from experiments.prompt_eval_v0.checks import run_auto_checks
from experiments.prompt_eval_v0.expectation import RunExpectation, write_expectation
from experiments.prompt_eval_v0.fixture import QUESTIONS, EvalQuestion, QuestionKind, cards_for
from experiments.prompt_eval_v0.prompts import PROMPT_VERSIONS, build_messages
from experiments.prompt_eval_v0.provenance import sanitize_endpoint, sha256_file

RESULTS_DIR = Path(__file__).parent / "results"
VERSIONS = ("v0", "v1", "v2")


#: Files whose content determines what is sent to the model.
SOURCE_INPUTS = ("prompts.py", "fixture.py", "runner.py", "checks.py")


def source_hashes() -> dict[str, str]:
    """Hash the run's own inputs at execution time.

    The v0 run hashed these only afterwards, so a later lint edit left the manifest unable
    to prove what actually ran. Capturing them here closes that gap for every future run.
    """

    package_dir = Path(__file__).parent
    return {
        name: hashlib.sha256((package_dir / name).read_bytes()).hexdigest()
        for name in SOURCE_INPUTS
        if (package_dir / name).exists()
    }


@dataclass(frozen=True)
class RunConfig:
    """Everything that must stay identical across prompt versions."""

    model: str
    base_url: str
    timeout_seconds: float
    #: The adapter sends no temperature, seed, top_p or max_tokens. Recorded, not changed.
    uncontrolled_sampling: tuple[str, ...] = ("temperature", "top_p", "seed", "max_tokens")

    def as_dict(self) -> dict:
        # The raw base_url is never written: gateway URLs can carry credentials in
        # userinfo, query or path. Only what reproduction needs survives.
        return {
            "model": self.model,
            "endpoint": sanitize_endpoint(self.base_url),
            "timeout_seconds": self.timeout_seconds,
            "uncontrolled_sampling_params": list(self.uncontrolled_sampling),
            "prompt_sha256": {
                version: hashlib.sha256(text.encode("utf-8")).hexdigest()
                for version, text in PROMPT_VERSIONS.items()
            },
            "source_sha256_at_run_time": source_hashes(),
        }


def config_path_for(records_path: Path) -> Path:
    """Sidecar path holding the generation config for a records file."""

    return records_path.with_name(records_path.stem + "_config.json")


def load_config(settings: Settings) -> RunConfig:
    base_url = (settings.generation_base_url or "").strip()
    model = (settings.generation_model or "").strip()
    if not base_url or not model:
        raise SystemExit(
            "GENERATION_BASE_URL and GENERATION_MODEL must be set for the prompt eval run"
        )
    return RunConfig(model=model, base_url=base_url, timeout_seconds=30.0)


async def evaluate_one(
    provider: OpenAICompatibleGenerationProvider,
    *,
    version: str,
    question: EvalQuestion,
    run_number: int,
) -> dict:
    cards = cards_for(question.scope)
    messages = build_messages(
        version=version,
        message=question.message,
        response_language=ContentLanguage.KOREAN,
        cards=cards,
    )

    started = time.perf_counter()
    raw: str | None = None
    error: str | None = None
    try:
        raw = await provider.complete(messages)
    except GenerationError as exc:
        error = f"GenerationError: {exc}"
    except Exception as exc:  # provider transport problem, recorded separately
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000)

    record: dict = {
        "prompt_version": version,
        "question_id": question.question_id,
        "kind": question.kind.value,
        "scope": question.scope.value,
        "run_number": run_number,
        "message": question.message,
        "card_ids": [str(card.card_id) for card in cards],
        "latency_ms": latency_ms,
        "raw_response": raw,
        "error": error,
    }

    if error is not None:
        # A transport failure is not a refusal. In production GroundedAnswerer catches it
        # and falls back to composition, so record that explicitly instead of leaving the
        # key absent and letting `.get()` read as "no fallback".
        record.update(
            provider_result="error",
            answerable=None,
            answer=None,
            used_card_ids=[],
            auto_checks=None,
            would_fallback=True,
        )
        return record

    result = validate_draft(raw or "", cards=cards, response_language=ContentLanguage.KOREAN)
    verdict = {
        DraftVerdict.ACCEPTED: "accepted",
        DraftVerdict.NOT_ANSWERABLE: "not_answerable",
        DraftVerdict.INVALID: "invalid",
    }[result.verdict]
    record["provider_result"] = verdict
    record["answerable"] = result.verdict is DraftVerdict.ACCEPTED
    # A rejected draft never reaches a user, so production would fall back to composition.
    record["would_fallback"] = result.verdict is DraftVerdict.INVALID

    if result.draft is None:
        record.update(answer=None, used_card_ids=[], auto_checks=None)
        return record

    used = [str(card_id) for card_id in result.draft.used_card_ids]
    record["answer"] = result.draft.answer
    record["used_card_ids"] = used
    record["auto_checks"] = run_auto_checks(
        result.draft.answer,
        cards=cards,
        used_card_ids=used,
        allow_procedure=question.kind is QuestionKind.GUIDANCE_HOW_TO,
    ).as_dict()
    return record


def build_provider(config: RunConfig, settings: Settings) -> OpenAICompatibleGenerationProvider:
    """Mirror production wiring, including the API key. The key is never recorded."""

    api_key = settings.generation_api_key
    return OpenAICompatibleGenerationProvider(
        base_url=config.base_url,
        model=config.model,
        api_key=api_key.get_secret_value() if api_key is not None else None,
        timeout_seconds=config.timeout_seconds,
    )


async def run_all(config: RunConfig, runs: int, settings: Settings) -> list[dict]:
    provider = build_provider(config, settings)
    records: list[dict] = []
    # Run-major, version-interleaved per question: reduces order bias without changing the
    # question order within a run.
    for run_number in range(1, runs + 1):
        for question in QUESTIONS:
            for version in VERSIONS:
                record = await evaluate_one(
                    provider,
                    version=version,
                    question=question,
                    run_number=run_number,
                )
                records.append(record)
                marker = record["provider_result"]
                print(
                    f"  run{run_number} {question.question_id:<3} {version} "
                    f"{record['latency_ms']:>6}ms  {marker}"
                )
    return records


def dry_run() -> None:
    """Build every prompt without calling a provider."""

    print(f"versions      : {', '.join(PROMPT_VERSIONS)}")
    print(f"questions     : {len(QUESTIONS)}")
    for version in VERSIONS:
        system = PROMPT_VERSIONS[version]
        print(f"\n--- {version}: system instruction {len(system)} chars")
        for question in QUESTIONS:
            cards = cards_for(question.scope)
            messages = build_messages(
                version=version,
                message=question.message,
                response_language=ContentLanguage.KOREAN,
                cards=cards,
            )
            user_chars = len(messages[1]["content"])
            print(
                f"    {question.question_id:<3} {question.scope.value:<20} "
                f"cards={len(cards)} user={user_chars}"
            )


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Prompt Eval v0 prompt-only runner.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR / "prompt_only.jsonl")
    args = parser.parse_args(argv)

    if args.dry_run:
        dry_run()
        return 0

    settings = Settings()
    config = load_config(settings)
    print(f"config: {json.dumps(config.as_dict(), ensure_ascii=False)}")
    print(f"planned calls: {len(QUESTIONS) * len(VERSIONS) * args.runs}")

    records = asyncio.run(run_all(config, args.runs, settings))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # One object per line, records only. The v0 run wrote its config as the first line of
    # this file, which made the JSONL heterogeneous and forced every reader to skip a line
    # by shape. The config now lives in its own file.
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    config_path = config_path_for(args.out)
    config_path.write_text(
        json.dumps(
            config.as_dict() | {"records_sha256": sha256_file(args.out)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # Declared shape, so a later deletion of a version or a run is detectable.
    expectation_file = write_expectation(
        args.out,
        RunExpectation(versions=VERSIONS, runs=args.runs, questions=len(QUESTIONS)),
    )

    print(f"\nwrote {len(records)} records to {args.out}")
    print(f"wrote run config to {config_path}")
    print(f"wrote run expectation to {expectation_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
