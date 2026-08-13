"""Unit tests for the Prompt Eval v0 harness.

The harness must not change production behaviour and must build comparable prompts: same
user turn, same output contract, only the system turn differs.
"""

import json

import pytest

from backend.app.domain import ContentLanguage
from backend.app.grounded import SYSTEM_INSTRUCTION, build_grounded_messages
from backend.app.scope import TrainingScope
from experiments.prompt_eval_v0.checks import run_auto_checks
from experiments.prompt_eval_v0.fixture import (
    GATE_QUESTIONS,
    QUESTIONS,
    QuestionKind,
    approved_cards,
    cards_for,
)
from experiments.prompt_eval_v0.prompts import PROMPT_VERSIONS, build_messages

VERSIONS = ("v0", "v1", "v2")


def test_v0_is_the_production_instruction_unchanged() -> None:
    assert PROMPT_VERSIONS["v0"] == SYSTEM_INSTRUCTION


def test_v1_and_v2_extend_v0_without_replacing_it() -> None:
    for version in ("v1", "v2"):
        assert PROMPT_VERSIONS[version].startswith(SYSTEM_INSTRUCTION)
        assert len(PROMPT_VERSIONS[version]) > len(SYSTEM_INSTRUCTION)

    assert len(PROMPT_VERSIONS["v2"]) > len(PROMPT_VERSIONS["v1"])


def test_v1_states_the_direction_rules() -> None:
    system = PROMPT_VERSIONS["v1"]

    for rule in (
        "Never swap the subject",
        "Never delete a negation",
        "was not more effective",
        "Do not state it as causation",
        "into a training procedure",
        "success rates more specific",
        "never output your checking",
    ):
        assert rule in system


def test_v2_keeps_v1_rules_and_adds_answer_shape() -> None:
    v1_rules = ("Never swap the subject", "Never delete a negation", "Do not state it as causation")
    system = PROMPT_VERSIONS["v2"]

    for rule in v1_rules:
        assert rule in system
    for rule in (
        "answers the question directly",
        "everyday Korean",
        "practice-guidance evidence goes",
        "set answerable to false",
        "Never write citations",
    ):
        assert rule in system


def test_every_version_keeps_the_same_output_contract() -> None:
    for version in VERSIONS:
        assert '"answerable"' in PROMPT_VERSIONS[version]
        assert '"used_card_ids"' in PROMPT_VERSIONS[version]


@pytest.mark.parametrize("question", QUESTIONS, ids=[q.question_id for q in QUESTIONS])
def test_user_turn_is_identical_across_versions(question) -> None:
    cards = cards_for(question.scope)
    user_turns = {
        build_messages(
            version=version,
            message=question.message,
            response_language=ContentLanguage.KOREAN,
            cards=cards,
        )[1]["content"]
        for version in VERSIONS
    }

    assert len(user_turns) == 1, "only the system turn may differ between versions"


def test_v0_messages_match_the_production_builder() -> None:
    question = QUESTIONS[0]
    cards = cards_for(question.scope)

    experiment = build_messages(
        version="v0",
        message=question.message,
        response_language=ContentLanguage.KOREAN,
        cards=cards,
    )
    production = build_grounded_messages(
        message=question.message,
        response_language=ContentLanguage.KOREAN,
        cards=cards,
    )

    assert experiment == production


def test_prompt_carries_no_source_metadata() -> None:
    cards = cards_for(TrainingScope.AVERSIVE_OR_ECOLLAR)
    prompt = "\n".join(
        item["content"]
        for item in build_messages(
            version="v2",
            message="질문",
            response_language=ContentLanguage.KOREAN,
            cards=cards,
        )
    )

    for forbidden in ("pmc7387681", "https://", "locator", "qdrant", "Bearer", "C:\\"):
        assert forbidden not in prompt


def test_unknown_version_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_messages(
            version="v3",
            message="질문",
            response_language=ContentLanguage.KOREAN,
            cards=cards_for(TrainingScope.HOUSETRAINING),
        )


def test_fixture_covers_every_required_kind_and_is_uniquely_identified() -> None:
    ids = [question.question_id for question in QUESTIONS]
    assert len(ids) == len(set(ids))
    assert {question.kind for question in QUESTIONS} == set(QuestionKind)
    assert len(GATE_QUESTIONS) == 4

    counts = {kind: sum(1 for q in QUESTIONS if q.kind is kind) for kind in QuestionKind}
    assert counts[QuestionKind.GUIDANCE_HOW_TO] >= 4
    assert counts[QuestionKind.RESEARCH_EXPLANATION] >= 5
    assert counts[QuestionKind.OVERREACH] >= 5


def test_every_question_resolves_to_approved_cards() -> None:
    approved = {card.card_id for card in approved_cards()}

    for question in QUESTIONS:
        cards = cards_for(question.scope)
        assert cards
        assert all(card.card_id in approved for card in cards)


def test_guidance_questions_use_guidance_scopes() -> None:
    guidance_scopes = {
        question.scope for question in QUESTIONS if question.kind is QuestionKind.GUIDANCE_HOW_TO
    }

    assert guidance_scopes == {TrainingScope.HOUSETRAINING, TrainingScope.CRATE_ADAPTATION}


# --------------------------------------------------------------------------------------
# Automatic screens
# --------------------------------------------------------------------------------------


def ecollar_checks(answer: str, *, allow_procedure: bool = False):
    cards = cards_for(TrainingScope.AVERSIVE_OR_ECOLLAR)
    return run_auto_checks(
        answer,
        cards=cards,
        used_card_ids=[str(cards[0].card_id)],
        allow_procedure=allow_procedure,
    )


def test_faithful_answer_passes_every_screen() -> None:
    checks = ecollar_checks("제한된 연구에서 e-collar 집단의 우위는 나타나지 않았습니다.")

    assert checks.used_card_ids_valid
    assert not checks.fabricated_content


def test_reversal_screens_catch_the_known_inversions() -> None:
    assert (
        "e-collar 우위 긍정"
        in ecollar_checks("e-collar 집단이 보상 중심 집단보다 더 효과적이었습니다.").reversal_hits
    )
    assert (
        "보상 집단이 부정적"
        in ecollar_checks(
            "보상 기반 집단은 혐오 자극 집단보다 더 부정적인 결과를 보였습니다."
        ).reversal_hits
    )
    assert "인과 단정" in ecollar_checks("혐오 자극 때문에 스트레스가 생깁니다.").reversal_hits
    assert "성공률 생성" in ecollar_checks("성공률 90%를 기대할 수 있습니다.").reversal_hits


def test_invented_numbers_and_latin_terms_are_flagged() -> None:
    checks = ecollar_checks("Pavlov 연구에서 500마리를 관찰했습니다.")

    assert "500" in checks.numbers_outside_evidence
    assert "Pavlov" in checks.latin_outside_evidence
    assert checks.fabricated_content


def test_procedure_screen_only_applies_when_procedures_are_disallowed() -> None:
    answer = "1단계. 7일 계획을 세우세요.\n2단계. 하루 5번 반복하세요."

    assert ecollar_checks(answer, allow_procedure=False).procedure_hits
    assert ecollar_checks(answer, allow_procedure=True).procedure_hits == []


def test_used_card_ids_outside_the_context_are_invalid() -> None:
    cards = cards_for(TrainingScope.HOUSETRAINING)
    checks = run_auto_checks(
        "근거 범위 안의 답변입니다.",
        cards=cards,
        used_card_ids=["00000000-0000-4000-8000-000000000000"],
        allow_procedure=True,
    )

    assert checks.used_card_ids_valid is False


def test_run_config_goes_to_a_sidecar_not_the_records_file(tmp_path) -> None:
    """The v0 run wrote its config as line 1 of the JSONL. New runs must not."""

    from experiments.prompt_eval_v0.runner import config_path_for

    records = tmp_path / "prompt_only.jsonl"
    sidecar = config_path_for(records)

    assert sidecar == tmp_path / "prompt_only_config.json"
    assert sidecar != records
    assert sidecar.suffix == ".json"


def test_runner_writes_records_only_and_a_separate_config(tmp_path, monkeypatch) -> None:
    import experiments.prompt_eval_v0.runner as runner_module
    from experiments.prompt_eval_v0.runner import RunConfig, config_path_for

    config = RunConfig(model="synthetic", base_url="http://localhost:1/v1", timeout_seconds=1.0)
    fake_records = [
        {"prompt_version": "v0", "question_id": "G1", "run_number": 1, "latency_ms": 1},
        {"prompt_version": "v1", "question_id": "G1", "run_number": 1, "latency_ms": 2},
    ]
    monkeypatch.setattr(runner_module, "load_config", lambda settings: config)
    monkeypatch.setattr(runner_module.asyncio, "run", lambda coro: (coro.close(), fake_records)[1])

    out = tmp_path / "records.jsonl"
    assert runner_module.main(["--runs", "1", "--out", str(out)]) == 0

    lines = [line for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == len(fake_records)
    for line in lines:
        assert "prompt_version" in json.loads(line), "records file must hold records only"

    written_config = json.loads(config_path_for(out).read_text(encoding="utf-8"))
    assert written_config["model"] == "synthetic"
    assert "temperature" in written_config["uncontrolled_sampling_params"]
    # Provenance the v0 run could not prove after the fact.
    assert set(written_config["prompt_sha256"]) == set(VERSIONS)
    assert set(written_config["source_sha256_at_run_time"]) >= {"prompts.py", "fixture.py"}


def test_run_config_records_the_hashes_that_were_actually_used() -> None:
    """Source hashes must be captured at run time, not reconstructed later."""

    import hashlib

    from experiments.prompt_eval_v0.runner import RunConfig, source_hashes

    config = RunConfig(
        model="synthetic", base_url="http://localhost:1/v1", timeout_seconds=1.0
    ).as_dict()

    for version, digest in config["prompt_sha256"].items():
        expected = hashlib.sha256(PROMPT_VERSIONS[version].encode("utf-8")).hexdigest()
        assert digest == expected

    assert config["source_sha256_at_run_time"] == source_hashes()
    assert all(len(digest) == 64 for digest in config["source_sha256_at_run_time"].values())


def test_runner_dry_run_builds_every_prompt(capsys: pytest.CaptureFixture[str]) -> None:
    from experiments.prompt_eval_v0.runner import dry_run

    dry_run()
    captured = capsys.readouterr().out

    for version in VERSIONS:
        assert f"--- {version}:" in captured
    for question in QUESTIONS:
        assert question.question_id in captured


def test_gate_control_records_are_serialisable() -> None:
    assert json.dumps([gate.message for gate in GATE_QUESTIONS], ensure_ascii=False)
