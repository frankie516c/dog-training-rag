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
combined_module = module.combined_eval

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

    def test_every_prompt_asks_for_a_next_step_when_the_material_has_one(self):
        client = FakeClient()
        Fixture().run(gap=0.05, client=client)
        prompt = client.prompts[0][1]
        self.assertIn("다음에 취할 수 있는 구체적인 행동이나 대처법", prompt)
        self.assertIn("자료에 없으면 억지로 만들지 말고 원인 설명까지만", prompt)

    def test_the_hedge_rule_is_renumbered_after_the_next_step_rule(self):
        # PROMPT_RULES now runs 1-5; HEDGE_RULE (only appended for hedge) must
        # read "6." so the numbering stays sequential, not duplicate "5."s.
        client = FakeClient()
        Fixture().run(gap=0.02, client=client)  # hedge band
        hedge_prompt = client.prompts[0][1]
        self.assertIn("6. 아래 자료는 질문과의 관련성이 낮게 측정되었습니다", hedge_prompt)
        self.assertNotIn("5. 아래 자료는 질문과의 관련성이 낮게 측정되었습니다", hedge_prompt)


class RecordTests(unittest.TestCase):
    def test_the_prompt_version_is_recorded_on_every_record(self):
        for gap in (0.001, 0.02, 0.05):
            with self.subTest(gap=gap):
                record = Fixture().run(gap=gap)["records"][0]
                self.assertEqual(module.PROMPT_VERSION, record["prompt_version"])
                self.assertEqual("grounded-answer-ko-v2", record["prompt_version"])

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
            module.build_client("anthropic", Path("."))
        message = str(caught.exception)
        self.assertIn("build_client", message)
        self.assertIn("dry-run", message)
        self.assertIn("openai", message)


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


def doc_chunk(chunk_id, index, doc_id="doc-1", heading_path=("문서 제목",), text="문서 본문"):
    return {
        "schema_version": "document-chunk-v1",
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "chunk_index": index,
        "source_url": "https://example.com/doc",
        "slot": "3",
        "heading_path": list(heading_path),
        "text": text,
        "char_count": len(text),
        "embedding_eligible": True,
    }


class DocumentChunkHeaderTests(unittest.TestCase):
    """build_prompt must handle document chunks — no video_id, no chapter_title.

    Needed for demo scenario③ (Q13): the graph-augmented evidence
    run_combined_retrieval_eval.py's hybrid_merge returns is a mix of video and
    document chunks, and generate_answers.py's own retrieval never produces a
    document chunk on its own (DEFAULT_CHUNK_DIR is video-only) — so this path
    was never exercised until Q13 needed it.
    """

    def test_a_document_chunk_gets_a_doc_id_header_not_a_video_id_lookup(self):
        prompt = module.build_prompt(QUESTION, [doc_chunk("docchunk-1", 0)], "answer")
        self.assertIn("[1] (문서 · doc-1 #0 · 문서 제목)", prompt)

    def test_a_document_chunk_without_a_heading_path_gets_no_trailing_bullet(self):
        chunk = doc_chunk("docchunk-1", 0, heading_path=())
        prompt = module.build_prompt(QUESTION, [chunk], "answer")
        self.assertIn("[1] (문서 · doc-1 #0)", prompt)

    def test_video_and_document_chunks_mix_in_one_prompt(self):
        chunks = [chunk("chunk-1", 0), doc_chunk("docchunk-1", 1)]
        prompt = module.build_prompt(QUESTION, chunks, "answer")
        self.assertIn("[1] (vid1 #0", prompt)
        self.assertIn("[2] (문서 · doc-1 #1", prompt)


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

    def test_the_profile_block_asks_the_model_to_tailor_the_answer(self):
        prompt = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "answer", DEMO_PROFILE)
        self.assertIn("이 반려견의 상황에 맞게 조언을 조정하세요", prompt)

    def test_the_profile_block_still_forbids_using_the_profile_as_evidence(self):
        prompt = module.build_prompt(QUESTION, [chunk("chunk-1", 0)], "answer", DEMO_PROFILE)
        self.assertIn("프로필은 그 근거로 쓸 수 없습니다", prompt)
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


class LiveModeCliTests(unittest.TestCase):
    """The project default is the adopted local Ollama provider; --dry-run remains opt-in."""

    def test_mode_defaults_to_ollama(self):
        parsed = module.build_parser().parse_args([])
        self.assertEqual("ollama", parsed.mode)

    def test_dry_run_flag_still_overrides_to_dry_run(self):
        parsed = module.build_parser().parse_args(["--dry-run"])
        self.assertTrue(parsed.dry_run)

    def test_env_flag_defaults_to_dotenv(self):
        parsed = module.build_parser().parse_args([])
        self.assertEqual(Path(".env"), parsed.env)

    def test_openai_mode_reaches_the_real_client_not_the_unknown_mode_error(self):
        # No API key is configured in this fixture on purpose: the point is that
        # build_client("openai", ...) gets past mode dispatch and fails on the key
        # lookup, not on "unknown --mode" the way build_client("anthropic", ...) does.
        with self.assertRaises(module.GenerationError) as caught:
            module.build_client("openai", Path(tempfile.mkdtemp()), Path("no-such-.env"))
        message = str(caught.exception)
        self.assertIn("OPENAI_API_KEY", message)
        self.assertNotIn("unknown --mode", message)

    def test_ollama_mode_dispatches_without_openai_key(self):
        client = module.build_client("ollama", Path(tempfile.mkdtemp()))
        self.assertEqual("ollama:gemma3:4b", client.info.name)


class GenerationMetaTests(unittest.TestCase):
    """model/prompt_version/generated_at land on the record only for a real client."""

    class TaggedFakeClient:
        """A FakeClient that also identifies itself, the way OpenAIAnswerClient does."""

        model_id = "fake-model-x"
        reasoning_effort = "low"

        def __init__(self, answer="생성된 답변입니다"):
            self.info = module.ClientInfo(name="tagged-fake")
            self._answer = answer

        def complete(self, prompt, record):
            return self._answer

    def test_a_client_with_model_id_gets_generation_meta(self):
        record = Fixture().run(gap=0.05, client=self.TaggedFakeClient())["records"][0]
        meta = record["generation_meta"]
        self.assertIsNotNone(meta)
        self.assertEqual("fake-model-x", meta["model"])
        self.assertEqual("low", meta["reasoning_effort"])
        self.assertEqual("not_sent", meta["temperature"])
        self.assertTrue(meta["generated_at"])  # non-empty ISO timestamp

    def test_a_client_without_model_id_gets_no_generation_meta(self):
        record = Fixture().run(gap=0.05, client=FakeClient())["records"][0]
        self.assertIsNone(record["generation_meta"])

    def test_the_refuse_band_gets_no_generation_meta_either(self):
        record = Fixture().run(gap=0.001, client=self.TaggedFakeClient())["records"][0]
        self.assertIsNone(record["generation_meta"])

    def test_dry_run_gets_no_generation_meta(self):
        fixture = Fixture()
        client = module.DryRunClient(fixture.out_dir / "prompts")
        record = fixture.run(gap=0.05, client=client)["records"][0]
        self.assertIsNone(record["generation_meta"])


class OutputGuardrailWiringTests(unittest.TestCase):
    """classify_output_v2 actually runs on the generated text now, not just under test."""

    # Minimal, self-contained lexicons — no real data/guardrail file involved.
    TERMS = ["슬개골 탈구"]
    WHITELIST = ["분리불안", "산책"]

    def test_disease_term_alone_gets_a_disclaimer_not_a_block(self):
        client = FakeClient(answer="슬개골 탈구가 있으면 점프를 피하는 게 좋습니다 [1].")
        record = Fixture().run(
            gap=0.05, client=client, medical_terms=self.TERMS, whitelist_terms=self.WHITELIST
        )["records"][0]
        self.assertIsNotNone(record["output_guardrail"])
        self.assertFalse(record["output_guardrail"]["is_blocked"])
        self.assertEqual(["슬개골 탈구"], record["output_guardrail"]["matched_disease_terms"])
        self.assertEqual([], record["output_guardrail"]["whitelist_matched"])
        self.assertIn("일반 정보이며 진단이 아닙니다", record["answer"])
        self.assertEqual("슬개골 탈구가 있으면 점프를 피하는 게 좋습니다 [1].", record["raw_model_answer"])

    def test_disease_plus_prescriptive_marker_is_blocked(self):
        client = FakeClient(answer="슬개골 탈구에는 소염제를 먹여 보세요.")
        record = Fixture().run(
            gap=0.05, client=client, medical_terms=self.TERMS, whitelist_terms=self.WHITELIST
        )["records"][0]
        self.assertTrue(record["output_guardrail"]["is_blocked"])
        self.assertEqual(module.medical_guardrail.OUTPUT_BLOCKED_MESSAGE, record["answer"])
        self.assertEqual("슬개골 탈구에는 소염제를 먹여 보세요.", record["raw_model_answer"])

    def test_a_whitelist_hit_passes_through_even_with_a_disease_term_present(self):
        # 2026-08-20 regression: v1 flagged "분리불안" in a plain training answer.
        # v2 + whitelist must let this through untouched — see docs/agenda_0825.md.
        client = FakeClient(answer="분리불안과 슬개골 탈구는 관계가 없습니다 [1].")
        record = Fixture().run(
            gap=0.05, client=client, medical_terms=self.TERMS, whitelist_terms=self.WHITELIST
        )["records"][0]
        self.assertFalse(record["output_guardrail"]["is_blocked"])
        self.assertEqual("분리불안과 슬개골 탈구는 관계가 없습니다 [1].", record["answer"])
        self.assertIn("분리불안", record["output_guardrail"]["whitelist_matched"])

    def test_no_medical_terms_means_no_guardrail_pass_at_all(self):
        # This is what every other test in this file exercises (medical_terms
        # defaults to None): the answer passes through untouched.
        client = FakeClient(answer="슬개골 탈구에는 소염제를 먹여 보세요.")
        record = Fixture().run(gap=0.05, client=client)["records"][0]
        self.assertIsNone(record["output_guardrail"])
        self.assertIsNone(record["raw_model_answer"])
        self.assertEqual("슬개골 탈구에는 소염제를 먹여 보세요.", record["answer"])

    def test_medical_terms_without_whitelist_terms_also_skips_the_guardrail(self):
        # Both are required together — see generate()'s call-site condition.
        client = FakeClient(answer="슬개골 탈구에는 소염제를 먹여 보세요.")
        record = Fixture().run(gap=0.05, client=client, medical_terms=self.TERMS)["records"][0]
        self.assertIsNone(record["output_guardrail"])

    def test_the_refuse_band_never_reaches_the_guardrail(self):
        client = FakeClient(answer="슬개골 탈구에는 소염제를 먹여 보세요.")
        record = Fixture().run(
            gap=0.001, client=client, medical_terms=self.TERMS, whitelist_terms=self.WHITELIST
        )["records"][0]
        self.assertIsNone(record["output_guardrail"])
        self.assertEqual(module.REFUSAL_TEXT, record["answer"])


class MedicalRefusalTemplateTests(unittest.TestCase):
    """The Q17 fix: a medical question in hedge/answer band never reaches the model.

    Mirrors owner_fixtures.jsonl Q17 ("아토피 피부염... 약용 샴푸나 처방식 사료,
    연고 이름을 알려주세요") landing in "answer" band on score_gap alone and
    getting the model's own ad-hoc refusal instead of a vet referral — see
    docs/agenda_0825.md 안건10.
    """

    TERMS = ["연고", "접종"]  # a minimal, self-contained v2-style lexicon
    WHITELIST = ["분리불안", "산책"]
    MEDICAL_QUESTION = "강아지 피부병에 바를 연고 좀 추천해 주세요."

    def _fixture_with_medical_question(self, **run_kwargs):
        fixture = Fixture(queries=[Fixture.eval_query("q1", self.MEDICAL_QUESTION)])
        return fixture.run(
            gap=0.05, medical_terms=self.TERMS, whitelist_terms=self.WHITELIST, **run_kwargs
        )

    def test_a_medical_question_never_calls_the_model(self):
        record = self._fixture_with_medical_question(client=ExplodingClient())["records"][0]
        self.assertEqual("answer", record["band"])  # would have called the model otherwise
        self.assertFalse(record["generated"])

    def test_a_medical_question_gets_the_template_not_an_ad_hoc_refusal(self):
        record = self._fixture_with_medical_question(client=ExplodingClient())["records"][0]
        self.assertEqual(module.MEDICAL_REFUSAL_TEMPLATE.text, record["answer"])
        self.assertIn("걱정이 많으시겠어요", record["answer"])
        self.assertIn("동물병원", record["answer"])

    def test_the_medical_verdict_is_recorded(self):
        record = self._fixture_with_medical_question(client=ExplodingClient())["records"][0]
        guardrail = record["medical_input_guardrail"]
        self.assertTrue(guardrail["is_medical"])
        self.assertIn("연고", guardrail["matched_terms"])

    def test_no_generation_meta_for_the_template_path(self):
        record = self._fixture_with_medical_question(client=ExplodingClient())["records"][0]
        self.assertIsNone(record["generation_meta"])
        self.assertIsNone(record["raw_model_answer"])

    def test_the_template_path_still_reports_an_unblocked_system_authored_verdict(self):
        # MEDICAL_REFUSAL_TEMPLATE goes through apply_output_guardrail() same as
        # any answer — it passes because it's a SystemAuthoredText (system_authored
        # is True, nothing matched), not because this path skips the check. This
        # is what makes the exemption safe: it's a property of the wrapped value,
        # not a branch a future edit could route real model text through unchecked.
        record = self._fixture_with_medical_question(client=ExplodingClient())["records"][0]
        guardrail = record["output_guardrail"]
        self.assertIsNotNone(guardrail)
        self.assertTrue(guardrail["system_authored"])
        self.assertFalse(guardrail["is_blocked"])
        self.assertEqual([], guardrail["matched_disease_terms"])
        self.assertEqual([], guardrail["matched_prescriptive_markers"])

    def test_a_whitelisted_training_question_still_calls_the_model(self):
        fixture = Fixture(queries=[Fixture.eval_query("q1", "산책 중 짖는 습관 어떻게 고치나요?")])
        client = FakeClient()
        record = fixture.run(
            gap=0.05, client=client, medical_terms=self.TERMS, whitelist_terms=self.WHITELIST
        )["records"][0]
        self.assertTrue(record["generated"])
        self.assertEqual(1, len(client.prompts))
        self.assertFalse(record["medical_input_guardrail"]["is_medical"])
        self.assertIn("산책", record["medical_input_guardrail"]["whitelist_matched"])

    def test_without_both_lexicons_the_short_circuit_never_engages(self):
        # No medical_terms/whitelist_terms injected (every other test in this
        # file): a medical-looking question still goes to the model as before.
        client = FakeClient()
        record = self._run_without_lexicons(client)
        self.assertTrue(record["generated"])
        self.assertIsNone(record["medical_input_guardrail"])

    def _run_without_lexicons(self, client):
        fixture = Fixture(queries=[Fixture.eval_query("q1", self.MEDICAL_QUESTION)])
        return fixture.run(gap=0.05, client=client)["records"][0]

    def test_the_refuse_band_is_untouched_by_this_check(self):
        # band == "refuse" already never calls the model; medical_input_guardrail
        # stays None there too — this fix only touches the hedge/answer branch.
        fixture = Fixture(queries=[Fixture.eval_query("q1", self.MEDICAL_QUESTION)])
        record = fixture.run(
            gap=0.001, client=ExplodingClient(),
            medical_terms=self.TERMS, whitelist_terms=self.WHITELIST,
        )["records"][0]
        self.assertEqual("refuse", record["band"])
        self.assertEqual(module.REFUSAL_TEXT, record["answer"])
        self.assertIsNone(record["medical_input_guardrail"])


class MedicalTermsAutoLoadTests(unittest.TestCase):
    """generate() only auto-loads the real lexicons when it builds its own client."""

    def test_an_injected_client_never_triggers_auto_load(self):
        # If this reached medical_guardrail.load_medical_terms_v2()/
        # load_training_whitelist() with a bad path it would raise; it must not
        # even try when a client is injected.
        result = Fixture().run(gap=0.05, client=FakeClient())
        self.assertIsNone(result["records"][0]["output_guardrail"])


class GenericScriptedEncoder:
    """Like ScriptedEncoder, but for an arbitrary passage list — needed once the
    corpus can include document chunks, which ScriptedEncoder's hardcoded
    CORPUS_ORDER/TEXTS knows nothing about.
    """

    def __init__(self, passage_texts, weights):
        self.dimension = len(passage_texts)
        self._passages = {
            retrieval.PASSAGE_PREFIX + text: index for index, text in enumerate(passage_texts)
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


def write_graph_fixture(directory, entries):
    """A minimal extractions.jsonl + aliases.json pair, in the same shape
    load_graph_neo4j.build_graph() (and so combined_eval.load_graph()) expects.

    entries: [(entity_name, entity_type, source_chunk_id), ...] — one extraction
    record per entry, no relations. Enough for match_seeds() to find a literal
    substring hit and graph_search() to surface that chunk.
    """
    extractions_path = directory / "extractions.jsonl"
    aliases_path = directory / "aliases.json"
    with extractions_path.open("w", encoding="utf-8", newline="\n") as file:
        for name, entity_type, chunk_id in entries:
            record = {
                "chunk_id": chunk_id,
                "entities": [{
                    "name": name, "type": entity_type, "normalized_from": None,
                    "evidence": name, "confidence": "high",
                }],
                "relations": [],
            }
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    aliases_path.write_text("{}", encoding="utf-8")
    return extractions_path, aliases_path


class GraphReuseTests(unittest.TestCase):
    """Graph search, hybrid merge and the gate must come from
    run_combined_retrieval_eval.py, not a second copy — see that module's own
    graph_search()/hybrid_merge()/gate() and docs/graph_hybrid_retrieval_design.md.
    """

    def test_combined_eval_is_the_combined_retrieval_module(self):
        self.assertIs(combined_module, sys.modules["run_combined_retrieval_eval"])
        for name in ("graph_search", "hybrid_merge", "gate", "load_graph", "build_adjacency"):
            self.assertTrue(hasattr(combined_module, name), name)

    def test_graph_functions_are_not_redefined_locally(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for signature in ("def graph_search(", "def hybrid_merge(", "def gate(",
                          "def load_graph(", "def build_adjacency("):
            self.assertNotIn(signature, source)
        for call in ("combined_eval.graph_search", "combined_eval.hybrid_merge",
                     "combined_eval.gate", "combined_eval.GATE_PASS"):
            self.assertIn(call, source)


class GraphGateSeparationTests(unittest.TestCase):
    """Graph evidence is gated on combined_eval.gate(score_gap) — the vector
    score alone, exactly as run_combined_retrieval_eval.py gates it
    (docs/graph_hybrid_retrieval_design.md 결정 3) — never on this script's own
    band thresholds, which a CLI flag can move independently.
    """

    QUESTION = "산책법이 궁금해요"

    def _fixture(self, seed_chunk="chunk-5"):
        fixture = Fixture(queries=[Fixture.eval_query("q1", self.QUESTION)])
        extractions, aliases = write_graph_fixture(
            fixture.directory, [("산책법", "훈련법", seed_chunk)]
        )
        return fixture, extractions, aliases

    def test_graph_evidence_is_added_on_gate_pass(self):
        fixture, extractions, aliases = self._fixture()
        result = module.generate(
            fixture.queries, fixture.chunk_dir, fixture.out_dir,
            encoder=ScriptedEncoder(weights_for_gap(0.05)), client=FakeClient(),
            top_k=3, graph_extractions=extractions, graph_aliases=aliases,
        )
        record = result["records"][0]
        self.assertEqual("answer", record["band"])
        self.assertEqual(combined_module.GATE_PASS, record["graph_gate_verdict"])
        self.assertEqual(["chunk-5"], record["graph_chunks_added"])
        self.assertIn("chunk-5", record["evidence_chunk_ids"])
        # top_k=3 alone would never have reached chunk-5 (ties break ascending id).
        self.assertNotIn("chunk-5", [row["chunk_id"] for row in record["retrieved"]])

    def test_graph_evidence_is_withheld_when_the_fixed_gate_refuses_in_the_answer_band(self):
        fixture, extractions, aliases = self._fixture()
        # answer_at_or_above is overridden well below combined_eval.GATE_THRESHOLD
        # (0.024, untouched here on purpose): the band says "answer" but the
        # graph gate — always combined_eval.gate() against the fixed threshold —
        # still says REFUSE. Evidence must stay vector-only either way.
        result = module.generate(
            fixture.queries, fixture.chunk_dir, fixture.out_dir,
            encoder=ScriptedEncoder(weights_for_gap(0.022)), client=FakeClient(),
            top_k=3, answer_at_or_above=0.02,
            graph_extractions=extractions, graph_aliases=aliases,
        )
        record = result["records"][0]
        self.assertEqual("answer", record["band"])
        self.assertEqual(combined_module.GATE_REFUSE, record["graph_gate_verdict"])
        self.assertEqual([], record["graph_chunks_added"])
        self.assertNotIn("chunk-5", record["evidence_chunk_ids"])

    def test_graph_off_suppresses_graph_evidence_even_when_configured(self):
        fixture, extractions, aliases = self._fixture()
        result = module.generate(
            fixture.queries, fixture.chunk_dir, fixture.out_dir,
            encoder=ScriptedEncoder(weights_for_gap(0.05)), client=FakeClient(),
            top_k=3, graph_extractions=extractions, graph_aliases=aliases, graph_off=True,
        )
        record = result["records"][0]
        self.assertIsNone(record["graph_gate_verdict"])
        self.assertEqual([], record["graph_chunks_added"])
        self.assertNotIn("chunk-5", record["evidence_chunk_ids"])

    def test_no_graph_paths_means_vector_only_evidence_by_default(self):
        # Every other test in this file runs this way (generate()'s own default):
        # graph_extractions/graph_aliases default to None, so a direct call never
        # touches the frozen files and never runs a graph search.
        record = Fixture().run(gap=0.05)["records"][0]
        self.assertIsNone(record["graph_gate_verdict"])
        self.assertEqual(
            [row["chunk_id"] for row in record["retrieved"]], record["evidence_chunk_ids"]
        )

    def test_the_refuse_band_carries_no_graph_fields_even_when_graph_is_configured(self):
        fixture, extractions, aliases = self._fixture()
        result = module.generate(
            fixture.queries, fixture.chunk_dir, fixture.out_dir,
            encoder=ScriptedEncoder(weights_for_gap(0.001)), client=ExplodingClient(),
            graph_extractions=extractions, graph_aliases=aliases,
        )
        record = result["records"][0]
        self.assertEqual("refuse", record["band"])
        self.assertIsNone(record["graph_gate_verdict"])
        self.assertIsNone(record["graph_chunks_added"])
        self.assertIsNone(record["evidence_chunk_ids"])


class GraphMedicalOrderingTests(unittest.TestCase):
    """The input guardrail runs before graph search: a MEDICAL question never
    triggers graph_search() at all, even when its text would otherwise match a
    graph seed literally. Requirement: retrieval-time search has no reason to
    run for a question the guardrail already routes to a vet referral.
    """

    TERMS = ["연고"]
    WHITELIST = ["없음더미"]  # deliberately disjoint from the graph seed below

    def test_a_medical_question_never_runs_graph_search(self):
        question = "가나다훈련 중에 연고를 발라야 하나요?"
        fixture = Fixture(queries=[Fixture.eval_query("q1", question)])
        extractions, aliases = write_graph_fixture(
            fixture.directory, [("가나다훈련", "훈련법", "chunk-5")]
        )
        result = module.generate(
            fixture.queries, fixture.chunk_dir, fixture.out_dir,
            encoder=ScriptedEncoder(weights_for_gap(0.05)), client=ExplodingClient(),
            medical_terms=self.TERMS, whitelist_terms=self.WHITELIST,
            graph_extractions=extractions, graph_aliases=aliases,
        )
        record = result["records"][0]
        self.assertTrue(record["medical_input_guardrail"]["is_medical"])
        self.assertIsNone(record["graph_gate_verdict"])
        self.assertIsNone(record["graph_chunks_added"])
        self.assertIsNone(record["evidence_chunk_ids"])
        self.assertEqual(module.MEDICAL_REFUSAL_TEMPLATE.text, record["answer"])


class DocumentCorpusIntegrationTests(unittest.TestCase):
    """doc_chunk_dir joins document chunks into the corpus, reusing
    combined_eval.load_document_chunks() — generate_answers.py's own retrieval
    had no document half before this (DEFAULT_CHUNK_DIR is video-only).
    """

    def test_a_document_chunk_can_win_the_ranking_and_render_a_document_header(self):
        fixture = Fixture()
        doc_dir = fixture.directory / "docs"
        doc_dir.mkdir()
        doc_text = "분리불안 문서 본문"
        row = doc_chunk("docchunk-1", 0, doc_id="doc-9", heading_path=("문서",), text=doc_text)
        with (doc_dir / "doc9.jsonl").open("w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

        passages = [TEXTS[c] for c in CORPUS_ORDER] + [doc_text]
        encoder = GenericScriptedEncoder(passages, weights=[0.5] * 5 + [0.95])

        result = module.generate(
            fixture.queries, fixture.chunk_dir, fixture.out_dir,
            encoder=encoder, client=FakeClient(), top_k=1, doc_chunk_dir=doc_dir,
        )
        record = result["records"][0]
        self.assertEqual(1, len(record["retrieved"]))
        self.assertEqual("docchunk-1", record["retrieved"][0]["chunk_id"])
        self.assertEqual("doc-9", record["retrieved"][0]["doc_id"])
        self.assertNotIn("video_id", record["retrieved"][0])

    def test_doc_chunk_dir_none_means_the_corpus_stays_video_only(self):
        record = Fixture().run(gap=0.05)["records"][0]
        self.assertTrue(all("video_id" in row for row in record["retrieved"]))


class GraphCliTests(unittest.TestCase):
    def test_graph_defaults_point_at_the_frozen_snapshot_not_the_live_graph(self):
        parsed = module.build_parser().parse_args([])
        self.assertEqual(module.DEFAULT_GRAPH_EXTRACTIONS, parsed.graph_extractions)
        self.assertEqual(module.DEFAULT_GRAPH_ALIASES, parsed.graph_aliases)
        self.assertEqual(Path("frozen/frozen_stage2_0820.jsonl"), parsed.graph_extractions)
        self.assertEqual(Path("frozen/frozen_entity_aliases_0820.json"), parsed.graph_aliases)

    def test_graph_off_flag_defaults_to_false_and_parses(self):
        self.assertFalse(module.build_parser().parse_args([]).graph_off)
        self.assertTrue(module.build_parser().parse_args(["--graph-off"]).graph_off)

    def test_doc_chunk_dir_defaults_to_the_document_corpus(self):
        parsed = module.build_parser().parse_args([])
        self.assertEqual(module.DEFAULT_DOC_CHUNK_DIR, parsed.doc_chunk_dir)
        self.assertFalse(parsed.no_documents)

    def test_no_documents_flag_parses(self):
        self.assertTrue(module.build_parser().parse_args(["--no-documents"]).no_documents)


if __name__ == "__main__":
    unittest.main()
