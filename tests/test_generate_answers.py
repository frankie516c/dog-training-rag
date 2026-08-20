import importlib.util
import json
import sys
import tempfile
import unittest

from pathlib import Path


REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "generate_answers.py"
SPEC = importlib.util.spec_from_file_location("generate_answers", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

retrieval = module.retrieval

CORPUS_ORDER = ("chunk-1", "chunk-2", "chunk-3", "chunk-4", "chunk-5")
TEXTS = {
    "chunk-1": "산책 인사법 설명",
    "chunk-2": "목줄 연습 설명",
    "chunk-3": "입마개 연습 설명",
    "chunk-4": "분리불안 신호 설명",
    "chunk-5": "밥상머리 교육 설명",
}
QUESTION = "산책 인사법은?"


def chunk(chunk_id, index):
    text = TEXTS[chunk_id]
    return {
        "schema_version": "youtube-chunk-v1",
        "chunk_id": chunk_id,
        "video_id": "vid1",
        "chunk_index": index,
        "chapter_index": index,
        "chapter_title": "본문",
        "chapter_role": "CONTENT",
        "embedding_eligible": True,
        "exclusion_reason": None,
        "start_ms": index * 10000,
        "end_ms": (index + 1) * 10000,
        "text": text,
        "source_segment_indices": [index],
        "source_cue_indices": [index],
        "char_count": len(text),
        "chunking": {"target_chars": 420, "min_chars": 150, "max_chars": 480, "overlap_segments": 0},
    }


def weights_for_gap(gap):
    """Query weights whose score_gap is exactly `gap` over the 5-chunk fixture.

    With basis-vector passages, top1 = w[0] and mean = sum(w)/5, so a flat tail of
    `base` gives gap = 0.8 * (w[0] - base). Solving for w[0] lets a test aim at a
    band boundary instead of guessing at one.
    """
    base = 0.5
    return [base + gap / 0.8] + [base] * 4


class ScriptedEncoder:
    """Deterministic stand-in: passages are basis vectors, queries are weights."""

    def __init__(self, weights):
        self.dimension = len(CORPUS_ORDER)
        self._passages = {
            retrieval.PASSAGE_PREFIX + TEXTS[chunk_id]: index
            for index, chunk_id in enumerate(CORPUS_ORDER)
        }
        self._weights = list(weights)
        self.info = retrieval.EncoderInfo(name="fake", dependency_versions={"fake": "1"})

    def encode(self, texts):
        vectors = []
        for text in texts:
            if text in self._passages:
                vector = [0.0] * self.dimension
                vector[self._passages[text]] = 1.0
            elif text.startswith(retrieval.QUERY_PREFIX):
                vector = list(self._weights)
            else:  # pragma: no cover - guards fixture drift
                raise AssertionError(f"unscripted text: {text!r}")
            vectors.append(vector)
        return vectors


class FakeClient:
    """Records every call, so a test can assert a call did not happen."""

    def __init__(self, answer="생성된 답변입니다"):
        self.info = module.ClientInfo(name="fake-client")
        self.prompts = []
        self._answer = answer

    def complete(self, prompt, record):
        self.prompts.append((record["query_id"], prompt))
        return self._answer


class ExplodingClient:
    """Fails the test if an answer is generated at all."""

    info = module.ClientInfo(name="exploding")

    def complete(self, prompt, record):
        raise AssertionError(f"the model must not be called for {record['query_id']!r}")


class Fixture:
    def __init__(self, queries=None, out_of_corpus=False):
        self.directory = Path(tempfile.mkdtemp(prefix="generate-fixture-"))
        self.chunk_dir = self.directory / "chunks"
        self.out_dir = self.directory / "generation"
        self.chunk_dir.mkdir(parents=True)
        with (self.chunk_dir / "vid1.jsonl").open("w", encoding="utf-8", newline="\n") as file:
            for index, chunk_id in enumerate(CORPUS_ORDER):
                file.write(json.dumps(chunk(chunk_id, index), ensure_ascii=False) + "\n")

        self.queries = self.directory / ("queries.json" if out_of_corpus else "queries.jsonl")
        if out_of_corpus:
            payload = {
                "schema_version": module.OUT_OF_CORPUS_SCHEMA,
                "note": "fixture",
                "corpus_covers": [],
                "queries": queries or [
                    {"query_id": "n001", "question": QUESTION, "topic": "없는 주제",
                     "topic_absent_because": "fixture"},
                ],
            }
            self.queries.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        else:
            rows = queries or [self.eval_query("q1", QUESTION)]
            with self.queries.open("w", encoding="utf-8", newline="\n") as file:
                for row in rows:
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def eval_query(query_id, question):
        return {
            "schema_version": module.EVAL_QUERY_SCHEMA,
            "query_id": query_id,
            "split": "dev",
            "query_type": "direct_lookup",
            "review_status": "APPROVED",
            "reviewed_at": "2026-08-17",
            "review_reason": "fixture",
            "question": question,
            "video_id": "vid1",
            "relevant_spans": [{"span_id": f"{query_id}-s1", "start_ms": 0, "end_ms": 9000, "note": ""}],
        }

    def run(self, gap=0.05, client=None, **kwargs):
        return module.generate(
            self.queries,
            self.chunk_dir,
            self.out_dir,
            encoder=ScriptedEncoder(weights_for_gap(gap)),
            client=client if client is not None else FakeClient(),
            **kwargs,
        )


class BandBoundaryTests(unittest.TestCase):
    """The bands are the whole point: check the edges, not the middles."""

    def test_default_boundaries_are_inclusive_upward(self):
        self.assertEqual("refuse", module.classify_band(0.0))
        self.assertEqual("refuse", module.classify_band(0.017999))
        self.assertEqual("hedge", module.classify_band(0.018))
        self.assertEqual("hedge", module.classify_band(0.023999))
        self.assertEqual("answer", module.classify_band(0.024))
        self.assertEqual("answer", module.classify_band(1.0))

    def test_thresholds_are_constants_not_literals(self):
        self.assertEqual(0.018, module.REFUSE_BELOW)
        self.assertEqual(0.024, module.ANSWER_AT_OR_ABOVE)
        self.assertEqual("hedge", module.classify_band(module.REFUSE_BELOW))
        self.assertEqual("answer", module.classify_band(module.ANSWER_AT_OR_ABOVE))

    def test_overridden_thresholds_move_the_bands(self):
        self.assertEqual("answer", module.classify_band(0.02, refuse_below=0.005, answer_at_or_above=0.01))
        self.assertEqual("refuse", module.classify_band(0.05, refuse_below=0.1, answer_at_or_above=0.2))

    def test_crossed_thresholds_are_rejected(self):
        with self.assertRaises(module.GenerationError):
            module.validate_thresholds(0.05, 0.01)
        with self.assertRaises(module.GenerationError):
            module.validate_thresholds(-0.1, 0.01)

    def test_cli_flags_reach_the_bands(self):
        parsed = module.build_parser().parse_args(
            ["--refuse-below", "0.03", "--answer-at-or-above", "0.09"]
        )
        self.assertEqual(0.03, parsed.refuse_below)
        self.assertEqual(0.09, parsed.answer_at_or_above)


class RoutingTests(unittest.TestCase):
    def test_each_band_is_reached_at_its_boundary(self):
        for gap, expected in ((0.0179, "refuse"), (0.018, "hedge"), (0.024, "answer")):
            with self.subTest(gap=gap):
                record = Fixture().run(gap=gap)["records"][0]
                self.assertEqual(expected, record["band"])
                # The fixture aims the gap exactly; confirm it landed where intended.
                self.assertAlmostEqual(gap, record["score_gap"], places=6)

    def test_the_refuse_band_never_calls_the_model(self):
        result = Fixture().run(gap=0.001, client=ExplodingClient())
        record = result["records"][0]
        self.assertEqual("refuse", record["band"])
        self.assertFalse(record["generated"])
        self.assertEqual(module.REFUSAL_TEXT, record["answer"])
        self.assertIsNone(record["prompt_path"])

    def test_the_hedge_and_answer_bands_do_call_the_model(self):
        for gap, band in ((0.02, "hedge"), (0.05, "answer")):
            with self.subTest(band=band):
                client = FakeClient()
                record = Fixture().run(gap=gap, client=client)["records"][0]
                self.assertEqual(band, record["band"])
                self.assertTrue(record["generated"])
                self.assertEqual(1, len(client.prompts))

    def test_the_hedge_prompt_asks_for_a_weak_evidence_notice(self):
        client = FakeClient()
        Fixture().run(gap=0.02, client=client)
        hedge_prompt = client.prompts[0][1]
        self.assertIn("근거 약함", hedge_prompt)

        client = FakeClient()
        Fixture().run(gap=0.05, client=client)
        self.assertNotIn("근거 약함", client.prompts[0][1])

    def test_every_prompt_forbids_answering_from_outside_the_sources(self):
        client = FakeClient()
        Fixture().run(gap=0.05, client=client)
        prompt = client.prompts[0][1]
        self.assertIn("실제로 적혀 있는 내용만으로", prompt)
        self.assertIn("자료에는 이 질문에 대한 내용이 없습니다", prompt)
        self.assertIn("일반 지식이나 상식으로 빈칸을 채우지", prompt)
        # The chunks the model is answering from must actually be in the prompt.
        self.assertIn(TEXTS["chunk-1"], prompt)


class RecordTests(unittest.TestCase):
    def test_the_prompt_version_is_recorded_on_every_record(self):
        for gap in (0.001, 0.02, 0.05):
            with self.subTest(gap=gap):
                record = Fixture().run(gap=gap)["records"][0]
                self.assertEqual(module.PROMPT_VERSION, record["prompt_version"])
                self.assertEqual("grounded-answer-ko-v1", record["prompt_version"])

    def test_the_record_carries_what_a_judge_needs(self):
        record = Fixture().run(gap=0.05)["records"][0]
        self.assertEqual(QUESTION, record["question"])
        self.assertEqual("answer", record["band"])
        self.assertEqual(
            {"refuse_below": 0.018, "answer_at_or_above": 0.024}, record["thresholds"]
        )
        self.assertEqual(5, len(record["retrieved"]))
        self.assertEqual("chunk-1", record["retrieved"][0]["chunk_id"])
        self.assertEqual([1, 2, 3, 4, 5], [row["rank"] for row in record["retrieved"]])
        self.assertEqual("fake-client", record["client"])
        self.assertEqual(module.GENERATION_SCHEMA_VERSION, record["schema_version"])

    def test_records_are_written_as_jsonl(self):
        result = Fixture().run(gap=0.05)
        lines = result["out_path"].read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(1, len(lines))
        self.assertEqual(QUESTION, json.loads(lines[0])["question"])

    def test_band_counts_are_reported(self):
        rows = [Fixture.eval_query(f"q{i}", QUESTION) for i in range(3)]
        result = Fixture(queries=rows).run(gap=0.05)
        self.assertEqual({"refuse": 0, "hedge": 0, "answer": 3}, result["band_counts"])


class QuerySchemaTests(unittest.TestCase):
    def test_the_evaluation_schema_is_accepted(self):
        record = Fixture().run(gap=0.05)["records"][0]
        self.assertEqual(module.EVAL_QUERY_SCHEMA, record["source_schema"])
        self.assertFalse(record["expected_refusal"])

    def test_out_of_corpus_queries_are_marked_as_expecting_a_refusal(self):
        record = Fixture(out_of_corpus=True).run(gap=0.05)["records"][0]
        self.assertEqual(module.OUT_OF_CORPUS_SCHEMA, record["source_schema"])
        self.assertTrue(record["expected_refusal"])
        # A high gap still answers: the flag records what the answer should have
        # been, it does not decide the band. That disagreement is the measurement.
        self.assertEqual("answer", record["band"])

    def test_an_unknown_schema_is_rejected(self):
        fixture = Fixture()
        rows = [dict(Fixture.eval_query("q1", QUESTION), schema_version="something-else-v9")]
        fixture.queries.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        with self.assertRaises(module.GenerationError) as caught:
            fixture.run(gap=0.05)
        self.assertIn("schema_version", str(caught.exception))


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_prompts_and_leaves_the_answer_null(self):
        fixture = Fixture()
        client = module.DryRunClient(fixture.out_dir / "prompts")
        record = fixture.run(gap=0.05, client=client)["records"][0]
        self.assertIsNone(record["answer"])
        self.assertEqual("dry-run", record["client"])
        self.assertEqual(1, len(client.written))
        written = client.written[0].read_text(encoding="utf-8")
        self.assertIn(QUESTION, written)
        self.assertTrue(record["prompt_path"].endswith("q1.md"))

    def test_dry_run_writes_no_prompt_for_a_refusal(self):
        fixture = Fixture()
        client = module.DryRunClient(fixture.out_dir / "prompts")
        record = fixture.run(gap=0.001, client=client)["records"][0]
        self.assertEqual([], client.written)
        self.assertEqual(module.REFUSAL_TEXT, record["answer"])

    def test_an_unimplemented_mode_says_where_to_add_a_client(self):
        with self.assertRaises(module.GenerationError) as caught:
            module.build_client("openai", Path("."))
        message = str(caught.exception)
        self.assertIn("build_client", message)
        self.assertIn("dry-run", message)


class BundleTests(unittest.TestCase):
    """One file to copy from, because the dry-run flow is a person doing it by hand."""

    def _bundle(self, gaps=(0.05, 0.02, 0.001)):
        rows = [Fixture.eval_query(f"q{i}", QUESTION) for i in range(len(gaps))]
        fixture = Fixture(queries=rows)
        # One run per gap would need one encoder per query, so build the records by
        # hand from single-query runs and bundle them together.
        records, prompts = [], {}
        for row, gap in zip(rows, gaps):
            single = Fixture(queries=[row])
            result = single.run(gap=gap, bundle=False)
            records.append(result["records"][0])
            prompts.update(result["prompts"])
        return fixture, records, prompts

    def test_the_bundle_holds_every_prompt_that_needs_a_model(self):
        _, records, prompts = self._bundle()
        text = module.build_bundle(records, prompts)
        self.assertIn("## q0 · band: answer", text)
        self.assertIn("## q1 · band: hedge", text)
        # q2 is the refuse band: never asked, so never in the bundle.
        self.assertNotIn("## q2", text)
        self.assertIn("생성 프롬프트 묶음 (2건)", text)

    def test_each_prompt_is_separated_by_its_query_id(self):
        _, records, prompts = self._bundle()
        text = module.build_bundle(records, prompts)
        for query_id in ("q0", "q1"):
            self.assertIn(f"---\n\n## {query_id} ·", text)
        # Two prompt sections; the trailing "---" belongs to the answer template.
        self.assertEqual(2, text.count("· band: "))

    def test_the_bundle_carries_a_fillable_answer_template(self):
        _, records, prompts = self._bundle()
        text = module.build_bundle(records, prompts)
        template = json.loads(text.split("```json", 1)[1].split("```", 1)[0])
        self.assertEqual(module.ANSWERS_SCHEMA_VERSION, template["schema_version"])
        self.assertEqual(module.PROMPT_VERSION, template["prompt_version"])
        self.assertEqual({"q0": "", "q1": ""}, template["answers"])

    def test_the_bundle_is_written_when_asked_for(self):
        result = Fixture().run(gap=0.05, bundle=True)
        self.assertIsNotNone(result["bundle_path"])
        self.assertTrue(result["bundle_path"].is_file())
        self.assertIn(QUESTION, result["bundle_path"].read_text(encoding="utf-8"))

    def test_no_bundle_unless_asked_for(self):
        self.assertIsNone(Fixture().run(gap=0.05)["bundle_path"])

    def test_no_bundle_when_every_query_was_refused(self):
        result = Fixture().run(gap=0.001, bundle=True)
        self.assertIsNone(result["bundle_path"])


class OverwriteGuardTests(unittest.TestCase):
    """A backfilled answer came from a model session that no longer exists."""

    def _fill(self, fixture, text="사람이 채운 답변"):
        rows = [json.loads(line) for line in
                (fixture.out_dir / "answers_queries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        rows[0]["answer"] = text
        with (fixture.out_dir / "answers_queries.jsonl").open("w", encoding="utf-8", newline="\n") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_regenerating_over_backfilled_answers_is_refused(self):
        fixture = Fixture()
        fixture.run(gap=0.05)
        self._fill(fixture)
        with self.assertRaises(module.GenerationError) as caught:
            fixture.run(gap=0.05)
        self.assertIn("--force", str(caught.exception))
        self.assertIn("q1", str(caught.exception))

    def test_force_regenerates_anyway(self):
        fixture = Fixture()
        fixture.run(gap=0.05)
        self._fill(fixture)
        record = fixture.run(gap=0.05, force=True)["records"][0]
        self.assertEqual("생성된 답변입니다", record["answer"])

    def test_a_dry_run_leaving_nulls_is_not_treated_as_filled(self):
        fixture = Fixture()
        client = module.DryRunClient(fixture.out_dir / "prompts")
        fixture.run(gap=0.05, client=client)
        # Answers are null, so re-running is safe and must not need --force.
        fixture.run(gap=0.05, client=module.DryRunClient(fixture.out_dir / "prompts"))


class ReuseTests(unittest.TestCase):
    """Retrieval must be the evaluator's, not a second implementation."""

    def test_retrieval_helpers_come_from_the_evaluation_module(self):
        self.assertIs(retrieval, sys.modules["evaluate_youtube_retrieval"])
        for name in ("similarity_scores", "rank_scores", "score_statistics", "load_chunks"):
            self.assertTrue(hasattr(retrieval, name), name)

    def test_the_prefixes_are_not_redefined_locally(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('QUERY_PREFIX = "', source)
        self.assertNotIn('PASSAGE_PREFIX = "', source)
        self.assertIn("retrieval.QUERY_PREFIX", source)
        self.assertIn("retrieval.PASSAGE_PREFIX", source)

    def test_ranking_matches_the_evaluator_for_the_same_scores(self):
        encoder = ScriptedEncoder(weights_for_gap(0.05))
        vectors = encoder.encode([retrieval.PASSAGE_PREFIX + TEXTS[c] for c in CORPUS_ORDER])
        query_vector = encoder.encode([retrieval.QUERY_PREFIX + QUESTION])[0]
        expected = retrieval.rank_chunks(query_vector, vectors, list(CORPUS_ORDER), 5)
        record = Fixture().run(gap=0.05)["records"][0]
        self.assertEqual(
            [chunk_id for chunk_id, _ in expected],
            [row["chunk_id"] for row in record["retrieved"]],
        )


DEMO_PROFILE = {
    "schema_version": module.PROFILE_SCHEMA_VERSION,
    "견종": "비숑프리제",
    "나이": "14개월",
    "몸무게": "4.8kg",
    "기존질환": [],
    "비고": "외출 후 현관 배변, 장난감 이동을 반복해서 보임.",
}


class ProfileBlockTests(unittest.TestCase):
    """build_prompt's only new surface: an optional <프로필> block before <자료>."""

    def test_no_profile_reproduces_the_pre_profile_prompt_exactly(self):
        with_no_arg = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "answer")
        with_explicit_none = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "answer", None)
        self.assertEqual(with_no_arg, with_explicit_none)
        self.assertNotIn("프로필", with_no_arg)

    def test_a_profile_adds_exactly_one_block_before_the_sources(self):
        prompt = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "answer", DEMO_PROFILE)
        self.assertEqual(1, prompt.count("<프로필>"))
        self.assertEqual(1, prompt.count("</프로필>"))
        # The profile block sits immediately before the sources section, not just
        # somewhere earlier — rule 1's own text also contains the literal "<자료>".
        self.assertIn("</프로필>\n\n<자료>", prompt)
        self.assertIn("비숑프리제", prompt)
        self.assertIn("14개월", prompt)

    def test_the_profile_block_warns_it_is_not_evidence(self):
        prompt = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "answer", DEMO_PROFILE)
        self.assertIn("근거 자료가 아니므로", prompt)
        self.assertIn("진단처럼 언급하지 마세요", prompt)

    def test_empty_conditions_render_as_none_present(self):
        prompt = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "answer", DEMO_PROFILE)
        self.assertIn("기존 질환: 없음", prompt)

    def test_present_conditions_are_listed(self):
        profile = dict(DEMO_PROFILE, 기존질환=["슬개골 탈구 2기"])
        prompt = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "answer", profile)
        self.assertIn("기존 질환: 슬개골 탈구 2기", prompt)

    def test_the_hedge_rule_and_the_profile_block_coexist(self):
        prompt = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "hedge", DEMO_PROFILE)
        self.assertIn("근거 약함", prompt)
        self.assertIn("<프로필>", prompt)


class LoadProfileTests(unittest.TestCase):
    def _write(self, tmp_path, payload):
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return tmp_path

    def test_the_shipped_demo_profile_loads(self):
        profile = module.load_profile(REPO / "data" / "profiles" / "demo_profile_v1.json")
        for key in module.PROFILE_FIELDS:
            self.assertIn(key, profile)
        self.assertIsInstance(profile["기존질환"], list)

    def test_a_missing_file_is_a_generation_error(self):
        with self.assertRaises(module.GenerationError):
            module.load_profile(Path(tempfile.mkdtemp()) / "nope.json")

    def test_the_wrong_schema_version_is_rejected(self):
        path = self._write(
            Path(tempfile.mkdtemp()) / "p.json", dict(DEMO_PROFILE, schema_version="v0")
        )
        with self.assertRaises(module.GenerationError):
            module.load_profile(path)

    def test_a_missing_field_is_rejected(self):
        payload = dict(DEMO_PROFILE)
        del payload["비고"]
        path = self._write(Path(tempfile.mkdtemp()) / "p.json", payload)
        with self.assertRaises(module.GenerationError):
            module.load_profile(path)

    def test_conditions_must_be_a_string_array(self):
        path = self._write(
            Path(tempfile.mkdtemp()) / "p.json", dict(DEMO_PROFILE, 기존질환="슬개골 탈구")
        )
        with self.assertRaises(module.GenerationError):
            module.load_profile(path)


class ProfileDoesNotTouchRetrievalTests(unittest.TestCase):
    """The one hard requirement: retrieval/gate output cannot move because of a profile.

    build_prompt is the only function given the profile (see generate()'s single
    call site); these compare every generate() output field a profile could in
    principle have leaked into, run with and without one.
    """

    NON_PROMPT_FIELDS = (
        "band", "score_gap", "top1_score", "corpus_mean_score", "retrieved",
        "thresholds", "expected_refusal", "source_schema",
    )

    def test_retrieval_and_gate_fields_are_identical_with_and_without_a_profile(self):
        for gap in (0.001, 0.02, 0.05):  # refuse, hedge, answer
            with self.subTest(gap=gap):
                without = Fixture().run(gap=gap)["records"][0]
                withp = Fixture().run(gap=gap, profile=DEMO_PROFILE)["records"][0]
                mismatches = [
                    key for key in self.NON_PROMPT_FIELDS if without[key] != withp[key]
                ]
                self.assertEqual([], mismatches)

    def test_a_profile_never_reaches_the_refuse_band_prompt_because_none_is_built(self):
        # refuse never calls build_prompt at all (see generate()); confirm a profile
        # does not change that — no prompt_path, no model call either way.
        result = Fixture().run(gap=0.001, profile=DEMO_PROFILE, client=ExplodingClient())
        record = result["records"][0]
        self.assertEqual("refuse", record["band"])
        self.assertIsNone(record["prompt_path"])

    def test_the_profile_only_shows_up_in_the_prompt_text(self):
        client = FakeClient()
        Fixture().run(gap=0.05, profile=DEMO_PROFILE, client=client)
        prompt = client.prompts[0][1]
        self.assertIn("비숑프리제", prompt)


class ProfileCliTests(unittest.TestCase):
    def test_profile_flag_defaults_to_none(self):
        parsed = module.build_parser().parse_args([])
        self.assertIsNone(parsed.profile)

    def test_profile_flag_parses_to_a_path(self):
        parsed = module.build_parser().parse_args(["--profile", "data/profiles/demo_profile_v1.json"])
        self.assertEqual(Path("data/profiles/demo_profile_v1.json"), parsed.profile)


if __name__ == "__main__":
    unittest.main()
