import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest

from pathlib import Path


REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "backfill_answers.py"
SPEC = importlib.util.spec_from_file_location("backfill_answers", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

generation = module.generation


def record(query_id, band="answer", answer=None, prompt_version=None, generated=None):
    """One generation record, shaped like what generate_answers.py writes."""
    if generated is None:
        generated = band != "refuse"
    if band == "refuse" and answer is None:
        answer = generation.REFUSAL_TEXT
    return {
        "schema_version": generation.GENERATION_SCHEMA_VERSION,
        "query_id": query_id,
        "question": f"{query_id} 질문",
        "source_schema": generation.OUT_OF_CORPUS_SCHEMA,
        "expected_refusal": True,
        "band": band,
        "thresholds": {"refuse_below": 0.018, "answer_at_or_above": 0.024},
        "score_gap": 0.03,
        "top1_score": 0.9,
        "corpus_mean_score": 0.87,
        "retrieved": [{"rank": 1, "chunk_id": "chunk-1", "video_id": "vid1", "chunk_index": 0, "score": 0.9}],
        "prompt_version": prompt_version or generation.PROMPT_VERSION,
        "prompt_path": None,
        "client": "dry-run",
        "answer": answer,
        "generated": generated,
    }


class Fixture:
    def __init__(self, records=None):
        self.directory = Path(tempfile.mkdtemp(prefix="backfill-fixture-"))
        self.target = self.directory / "answers_fixture.jsonl"
        rows = records or [record("n001"), record("n002", band="hedge"), record("n003", band="refuse")]
        self.write_target(rows)

    def write_target(self, rows):
        with self.target.open("w", encoding="utf-8", newline="\n") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def answers(self, mapping, prompt_version=None, schema_version=None, name="replies.json"):
        payload = {
            "schema_version": schema_version or generation.ANSWERS_SCHEMA_VERSION,
            "prompt_version": prompt_version or generation.PROMPT_VERSION,
            "answers": mapping,
        }
        path = self.directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def rows(self):
        return [json.loads(line) for line in self.target.read_text(encoding="utf-8").splitlines() if line.strip()]


class BackfillTests(unittest.TestCase):
    def test_answers_are_merged_into_the_artifact(self):
        fixture = Fixture()
        result = module.backfill(fixture.answers({"n001": "첫 번째 답변"}), fixture.target)
        self.assertEqual(["n001"], result["filled"])
        rows = {row["query_id"]: row for row in fixture.rows()}
        self.assertEqual("첫 번째 답변", rows["n001"]["answer"])
        self.assertEqual("replies.json", rows["n001"]["answer_source"])
        # Untouched records keep everything, including their null answer.
        self.assertIsNone(rows["n002"]["answer"])
        self.assertEqual("n002 질문", rows["n002"]["question"])

    def test_remaining_gaps_are_reported(self):
        fixture = Fixture()
        result = module.backfill(fixture.answers({"n001": "답변"}), fixture.target)
        # n003 is the refuse band: already answered, and never pending.
        self.assertEqual(["n002"], result["pending"])

    def test_empty_answers_are_skipped_not_written_as_blanks(self):
        fixture = Fixture()
        result = module.backfill(fixture.answers({"n001": "답변", "n002": "   "}), fixture.target)
        self.assertEqual(["n001"], result["filled"])
        self.assertIsNone({row["query_id"]: row for row in fixture.rows()}["n002"]["answer"])


class PromptVersionTests(unittest.TestCase):
    """A judged batch has to be one batch, so the prompt has to be the same one."""

    def test_a_different_prompt_version_is_refused(self):
        fixture = Fixture()
        answers = fixture.answers({"n001": "답변"}, prompt_version="grounded-answer-ko-v0")
        with self.assertRaises(module.BackfillError) as caught:
            module.backfill(answers, fixture.target)
        message = str(caught.exception)
        self.assertIn("prompt version mismatch", message)
        self.assertIn("grounded-answer-ko-v0", message)
        self.assertIn(generation.PROMPT_VERSION, message)

    def test_a_stale_record_is_caught_even_when_the_answers_are_current(self):
        fixture = Fixture(records=[record("n001", prompt_version="grounded-answer-ko-v0")])
        with self.assertRaises(module.BackfillError):
            module.backfill(fixture.answers({"n001": "답변"}), fixture.target)

    def test_a_missing_prompt_version_is_refused(self):
        fixture = Fixture()
        path = fixture.directory / "no_version.json"
        path.write_text(
            json.dumps({"schema_version": generation.ANSWERS_SCHEMA_VERSION, "answers": {"n001": "답변"}}),
            encoding="utf-8",
        )
        with self.assertRaises(module.BackfillError) as caught:
            module.backfill(path, fixture.target)
        self.assertIn("prompt_version", str(caught.exception))

    def test_nothing_is_written_when_a_check_fails(self):
        fixture = Fixture()
        before = fixture.target.read_bytes()
        with self.assertRaises(module.BackfillError):
            module.backfill(fixture.answers({"n001": "답변"}, prompt_version="other-v9"), fixture.target)
        self.assertEqual(before, fixture.target.read_bytes())


class RefuseBandTests(unittest.TestCase):
    def test_an_answer_for_the_refuse_band_is_refused(self):
        fixture = Fixture()
        with self.assertRaises(module.BackfillError) as caught:
            module.backfill(fixture.answers({"n003": "지어낸 답변"}), fixture.target)
        message = str(caught.exception)
        self.assertIn("refuse band", message)
        self.assertIn("n003", message)

    def test_the_refusal_text_stays_as_written(self):
        fixture = Fixture()
        module.backfill(fixture.answers({"n001": "답변"}), fixture.target)
        rows = {row["query_id"]: row for row in fixture.rows()}
        self.assertEqual(generation.REFUSAL_TEXT, rows["n003"]["answer"])
        self.assertFalse(rows["n003"]["generated"])


class OverwriteTests(unittest.TestCase):
    def test_an_existing_answer_needs_an_explicit_flag(self):
        fixture = Fixture(records=[record("n001", answer="이미 채운 답변")])
        with self.assertRaises(module.BackfillError) as caught:
            module.backfill(fixture.answers({"n001": "새 답변"}), fixture.target)
        self.assertIn("--force", str(caught.exception))
        self.assertEqual("이미 채운 답변", fixture.rows()[0]["answer"])

    def test_force_replaces_and_says_what_it_replaced(self):
        fixture = Fixture(records=[record("n001", answer="이미 채운 답변")])
        result = module.backfill(fixture.answers({"n001": "새 답변"}), fixture.target, force=True)
        self.assertEqual(["n001"], result["replaced"])
        self.assertEqual("새 답변", fixture.rows()[0]["answer"])


class InputValidationTests(unittest.TestCase):
    def test_an_unknown_query_id_is_refused(self):
        fixture = Fixture()
        with self.assertRaises(module.BackfillError) as caught:
            module.backfill(fixture.answers({"n999": "답변"}), fixture.target)
        self.assertIn("n999", str(caught.exception))

    def test_a_wrong_schema_version_points_at_the_bundle_template(self):
        fixture = Fixture()
        answers = fixture.answers({"n001": "답변"}, schema_version="something-else-v1")
        with self.assertRaises(module.BackfillError) as caught:
            module.backfill(answers, fixture.target)
        self.assertIn("bundle", str(caught.exception))

    def test_a_missing_file_is_reported_not_crashed(self):
        fixture = Fixture()
        with self.assertRaises(module.BackfillError):
            module.backfill(fixture.directory / "nope.json", fixture.target)
        with self.assertRaises(module.BackfillError):
            module.backfill(fixture.answers({"n001": "답변"}), fixture.directory / "nope.jsonl")

    def test_cli_requires_an_answers_file(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            module.build_parser().parse_args([])


class RoundTripTests(unittest.TestCase):
    """The bundle template must be directly usable as the backfill input."""

    def test_the_template_the_bundle_prints_is_accepted(self):
        fixture = Fixture()
        records = fixture.rows()
        prompts = {row["query_id"]: "프롬프트 본문" for row in records if row["band"] != "refuse"}
        bundle = generation.build_bundle(records, prompts)

        block = bundle.split("```json", 1)[1].split("```", 1)[0]
        template = json.loads(block)
        self.assertEqual(generation.ANSWERS_SCHEMA_VERSION, template["schema_version"])
        self.assertEqual(generation.PROMPT_VERSION, template["prompt_version"])
        # The refuse band must not appear in the template: it was never asked.
        self.assertEqual({"n001", "n002"}, set(template["answers"]))

        template["answers"] = {key: f"{key} 답변" for key in template["answers"]}
        path = fixture.directory / "from_template.json"
        path.write_text(json.dumps(template, ensure_ascii=False), encoding="utf-8")
        result = module.backfill(path, fixture.target)
        self.assertEqual(["n001", "n002"], result["filled"])
        self.assertEqual([], result["pending"])


if __name__ == "__main__":
    unittest.main()
