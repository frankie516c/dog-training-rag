import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest

from pathlib import Path


REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "evaluate_youtube_retrieval.py"
SPEC = importlib.util.spec_from_file_location("evaluate_youtube_retrieval", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


CORPUS_ORDER = ("chunk-a1", "chunk-a2", "chunk-a3", "chunk-a4", "chunk-b0", "chunk-b1", "chunk-b2")

# Substrings that mark an environment dependent measurement. They belong in the
# runtime artifact, never in the deterministic metrics payload.
TIMING_KEY_TOKENS = (
    "latency", "load_time", "encoding_time", "elapsed", "duration",
    "wall_clock", "started_at", "timestamp", "p50", "p95", "_ms", "_sec",
)


def json_keys(value):
    """Every object key in a JSON document, so tests can assert on structure."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from json_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from json_keys(item)


def _load_script(name):
    """Import a sibling script the same way this module imports the one under test."""
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _chunk_kwargs(row):
    """Reverse of `chunk()`, so a fixture row can be rebuilt with one field changed."""
    return {
        "chunk_id": row["chunk_id"],
        "video_id": row["video_id"],
        "index": row["chunk_index"],
        "start": row["start_ms"],
        "end": row["end_ms"],
        "text": row["text"],
        "eligible": row["embedding_eligible"],
        "chapter_title": row["chapter_title"],
    }


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


# What scripts/chunk_approved_youtube.py writes into every chunk record.
FIXTURE_CHUNKING = {"target_chars": 420, "min_chars": 150, "max_chars": 480, "overlap_segments": 0}


def chunk(chunk_id, video_id, index, start, end, text, eligible=True, chapter_title="본문", chunking=FIXTURE_CHUNKING):
    return {
        "schema_version": "youtube-chunk-v1",
        "chunk_id": chunk_id,
        "video_id": video_id,
        "chunk_index": index,
        "chapter_index": index,
        "chapter_title": chapter_title,
        "chapter_role": "CONTENT" if eligible else "NON_CONTENT",
        "embedding_eligible": eligible,
        "exclusion_reason": None if eligible else "chapter_title:오프닝",
        "start_ms": start,
        "end_ms": end,
        "text": text,
        "source_segment_indices": [index],
        "source_cue_indices": [index],
        "char_count": len(text),
        **({} if chunking is None else {"chunking": dict(chunking)}),
    }


CHUNKS = {
    "vid1": [
        chunk("chunk-a0", "vid1", 0, 0, 10000, "오프닝 잡담", eligible=False, chapter_title="오프닝"),
        chunk("chunk-a1", "vid1", 1, 10000, 20000, "산책 인사법 설명"),
        chunk("chunk-a2", "vid1", 2, 20000, 30000, "목줄 연습 설명"),
        chunk("chunk-a3", "vid1", 3, 30000, 40000, "입마개 연습 설명"),
        chunk("chunk-a4", "vid1", 4, 40000, 50000, "분리불안 신호 설명"),
    ],
    "vid2": [
        chunk("chunk-b0", "vid2", 0, 0, 10000, "점프 교정 설명"),
        chunk("chunk-b1", "vid2", 1, 10000, 20000, "밥상머리 교육 설명"),
        chunk("chunk-b2", "vid2", 2, 20000, 30000, "둔감화 훈련 설명"),
    ],
}
TRANSCRIPT_BOUNDS = {"vid1": (0, 60000), "vid2": (0, 30000)}

QUERY_WEIGHTS = {
    #                       a1   a2   a3   a4   b0   b1   b2
    "산책 인사법은?": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3],
    "줄 연습은?": [0.3, 0.4, 0.8, 0.9, 0.7, 0.6, 0.5],
    "밥상머리 교육은?": [0.9, 0.8, 0.6, 0.5, 0.4, 0.7, 0.3],
}


def query(query_id, question, video_id, spans, split="dev", status="APPROVED", query_type="direct_lookup"):
    return {
        "schema_version": module.QUERY_SCHEMA_VERSION,
        "query_id": query_id,
        "split": split,
        "query_type": query_type,
        "review_status": status,
        "reviewed_at": "2026-08-17" if status == "APPROVED" else None,
        "review_reason": "fixture",
        "question": question,
        "video_id": video_id,
        "relevant_spans": [
            {"span_id": f"{query_id}-s{index}", "start_ms": start, "end_ms": end, "note": ""}
            for index, (start, end) in enumerate(spans, start=1)
        ],
    }


QUERIES = [
    query("q1", "산책 인사법은?", "vid1", [(11000, 19000)]),
    query("q2", "줄 연습은?", "vid1", [(21000, 39000)], query_type="multi_span"),
    query("q3", "밥상머리 교육은?", "vid2", [(11000, 19000), (21000, 29000)], query_type="multi_span"),
]


class ScriptedEncoder:
    """Deterministic stand-in for the real model: passages are basis vectors."""

    def __init__(self, corpus_order=CORPUS_ORDER, weights=None, name="fake-scripted-v1"):
        self.dimension = len(corpus_order)
        text_by_id = {row["chunk_id"]: row["text"] for rows in CHUNKS.values() for row in rows}
        self._passages = {
            module.PASSAGE_PREFIX + text_by_id[chunk_id]: index
            for index, chunk_id in enumerate(corpus_order)
        }
        self._queries = {
            module.QUERY_PREFIX + question: list(vector)
            for question, vector in (weights or QUERY_WEIGHTS).items()
        }
        self.info = module.EncoderInfo(name="fake", dependency_versions={"fake-encoder": name})
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        vectors = []
        for text in texts:
            if text in self._passages:
                vector = [0.0] * self.dimension
                vector[self._passages[text]] = 1.0
            elif text in self._queries:
                vector = list(self._queries[text])
            else:  # pragma: no cover - guards fixture drift
                raise AssertionError(f"unscripted text: {text!r}")
            vectors.append(vector)
        return vectors


class ExplodingLoader:
    """Fails the test if the evaluation reaches the model import."""

    def __init__(self, test):
        self.test = test

    def __call__(self, *args, **kwargs):
        raise AssertionError(f"load_encoder must not be called (args={args!r} {kwargs!r})")


class Fixture:
    def __init__(self, queries=QUERIES, chunks=None, bounds=None):
        self.directory = Path(tempfile.mkdtemp(prefix="eval-fixture-"))
        self.chunk_dir = self.directory / "chunks"
        self.transcript_dir = self.directory / "transcripts"
        self.result_dir = self.directory / "results"
        self.review_path = self.directory / "review" / "retrieval_query_review.md"
        self.query_set = self.directory / "queries" / "youtube_retrieval_queries.jsonl"
        for video_id, rows in (chunks or CHUNKS).items():
            write_jsonl(self.chunk_dir / f"{video_id}.jsonl", rows)
        for video_id, (start, end) in (bounds or TRANSCRIPT_BOUNDS).items():
            write_jsonl(
                self.transcript_dir / f"{video_id}.jsonl",
                [
                    {"segment_index": 0, "video_id": video_id, "start_ms": start, "end_ms": start + 1, "text": "a", "source_cue_indices": [0]},
                    {"segment_index": 1, "video_id": video_id, "start_ms": end - 1, "end_ms": end, "text": "b", "source_cue_indices": [1]},
                ],
            )
        write_jsonl(self.query_set, queries)

    def evaluate(self, encoder=None, **settings):
        return module.run_evaluation(
            self.query_set,
            self.chunk_dir,
            self.transcript_dir,
            self.result_dir,
            module.RunSettings(**settings),
            encoder=encoder if encoder is not None else ScriptedEncoder(),
        )

    def review(self):
        return module.run_review_only(
            self.query_set, self.chunk_dir, self.transcript_dir, self.review_path
        )


@contextlib.contextmanager
def no_model_load(test):
    original = module.load_encoder
    module.load_encoder = ExplodingLoader(test)
    try:
        yield
    finally:
        module.load_encoder = original


@contextlib.contextmanager
def cuda(available):
    """Pin the CUDA probe. `available=None` fails the test if the probe runs at all."""
    def probe():
        if available is None:
            raise AssertionError("the CUDA probe must not run for this command")
        return available

    original = module.cuda_is_available
    module.cuda_is_available = probe
    try:
        yield
    finally:
        module.cuda_is_available = original


def run_main(argv):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = module.main(argv)
    return code, buffer.getvalue()


class RunSettingsTests(unittest.TestCase):
    def test_top_k_below_five_is_rejected(self):
        for top_k in (0, 1, 4):
            with self.assertRaises(module.EvaluationError) as caught:
                module.RunSettings(top_k=top_k).validate()
            self.assertIn("--top-k must be >= 5", str(caught.exception))

    def test_top_k_five_or_more_is_accepted(self):
        module.RunSettings(top_k=5).validate()
        module.RunSettings(top_k=20).validate()

    def test_only_multilingual_e5_base_is_accepted(self):
        module.RunSettings(model_name="intfloat/multilingual-e5-base").validate()
        for name in ("BAAI/bge-m3", "nlpai-lab/KURE-v1", "intfloat/multilingual-e5-large"):
            with self.assertRaises(module.EvaluationError) as caught:
                module.RunSettings(model_name=name).validate()
            self.assertIn("unsupported model", str(caught.exception))

    def test_top_k_is_checked_before_the_model_is_loaded(self):
        fixture = Fixture()
        with no_model_load(self):
            with self.assertRaises(module.EvaluationError):
                module.run_evaluation(
                    fixture.query_set, fixture.chunk_dir, fixture.transcript_dir,
                    fixture.result_dir, module.RunSettings(top_k=4), encoder=None,
                )


class ReviewOnlyTests(unittest.TestCase):
    def test_review_only_writes_a_report_and_never_loads_a_model(self):
        fixture = Fixture()
        with no_model_load(self):
            plans, path = fixture.review()
        self.assertEqual(3, len(plans))
        self.assertTrue(path.is_file())
        self.assertIn("YouTube 검색 평가 질문 검토 보고서", path.read_text(encoding="utf-8"))

    def test_review_only_exits_zero_when_every_query_is_pending(self):
        pending = [dict(row, review_status="PENDING", reviewed_at=None) for row in QUERIES]
        fixture = Fixture(queries=pending)
        with no_model_load(self):
            code, output = run_main([
                "--review-only",
                "--query-set", str(fixture.query_set),
                "--chunk-dir", str(fixture.chunk_dir),
                "--transcript-dir", str(fixture.transcript_dir),
                "--review-path", str(fixture.review_path),
            ])
        self.assertEqual(0, code)
        self.assertIn("PENDING q1", output)
        self.assertIn("'PENDING': 3", output)

    def test_review_report_shows_mapping_without_the_full_transcript(self):
        fixture = Fixture()
        with no_model_load(self):
            _, path = fixture.review()
        report = path.read_text(encoding="utf-8")
        # q2's span 21000-39000 maps to chunk-a2 and chunk-a3. Both are listed with
        # id, chapter title and overlap coefficient...
        self.assertIn("overlap coefficient", report)
        for chunk_id in ("chunk-a2", "chunk-a3"):
            self.assertIn(f"`{chunk_id}`", report)
        self.assertIn("본문", report)
        # ...but only the highest-coefficient chunk of the span is quoted.
        self.assertIn("목줄 연습 설명", report)
        self.assertNotIn("입마개 연습 설명", report)
        # Chunks the gold spans do not touch must not be quoted at all.
        self.assertNotIn("오프닝 잡담", report)
        self.assertNotIn("분리불안 신호 설명", report)

    def test_review_report_quotes_one_capped_sample_per_gold_span(self):
        fixture = Fixture()
        with no_model_load(self):
            plans, path = fixture.review()
        quotes = [
            line[2:] for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("> ")
        ]
        self.assertEqual(sum(len(plan.spans) for plan in plans), len(quotes))
        for quote in quotes:
            self.assertLessEqual(len(quote.rstrip("…")), module.REVIEW_SAMPLE_CHARS)

    def test_review_sample_is_capped_at_120_characters(self):
        long_text = "가" * 400
        chunks = {
            "vid1": [dict(row, text=long_text if row["chunk_id"] == "chunk-a1" else row["text"]) for row in CHUNKS["vid1"]],
            "vid2": CHUNKS["vid2"],
        }
        fixture = Fixture(chunks=chunks)
        with no_model_load(self):
            _, path = fixture.review()
        report = path.read_text(encoding="utf-8")
        self.assertIn("가" * module.REVIEW_SAMPLE_CHARS + "…", report)
        self.assertNotIn("가" * (module.REVIEW_SAMPLE_CHARS + 1), report)


class ValidationTests(unittest.TestCase):
    def _expect_error(self, queries, fragment):
        fixture = Fixture(queries=queries)
        with no_model_load(self):
            with self.assertRaises(module.EvaluationError) as caught:
                fixture.review()
        self.assertIn(fragment, str(caught.exception))

    def test_span_after_the_transcript_end_is_an_eval_set_error(self):
        self._expect_error(
            [query("q1", "산책 인사법은?", "vid1", [(59000, 61000)])],
            "outside the vid1 transcript range",
        )

    def test_span_before_the_transcript_start_is_an_eval_set_error(self):
        bounds = {"vid1": (5000, 60000), "vid2": (0, 30000)}
        fixture = Fixture(queries=[query("q1", "산책 인사법은?", "vid1", [(1000, 19000)])], bounds=bounds)
        with self.assertRaises(module.EvaluationError) as caught:
            fixture.review()
        self.assertIn("outside the vid1 transcript range", str(caught.exception))

    def test_span_without_an_eligible_chunk_is_an_error(self):
        self._expect_error(
            [query("q1", "산책 인사법은?", "vid1", [(1000, 9000)])],
            "maps to no embedding_eligible chunk",
        )

    def test_span_touching_only_a_non_content_chunk_is_not_relevant(self):
        # chunk-a0 covers 0-10000 but is embedding_eligible=false.
        self._expect_error(
            [query("q1", "산책 인사법은?", "vid1", [(2000, 8000)])],
            "maps to no embedding_eligible chunk",
        )

    def test_unknown_video_id_is_an_error(self):
        self._expect_error(
            [query("q1", "산책 인사법은?", "vid9", [(11000, 19000)])],
            "is not in the chunk corpus",
        )

    def test_approved_query_requires_reviewed_at(self):
        broken = dict(QUERIES[0], reviewed_at=None)
        self._expect_error([broken], "APPROVED queries must carry reviewed_at")

    def test_unknown_query_type_and_split_are_rejected(self):
        self._expect_error([dict(QUERIES[0], query_type="freeform")], "query_type must be one of")
        self._expect_error([dict(QUERIES[0], split="train")], "split must be one of")

    def test_empty_relevant_spans_is_rejected(self):
        self._expect_error([dict(QUERIES[0], relevant_spans=[])], "relevant_spans must be a non-empty array")

    def test_duplicate_query_id_is_rejected(self):
        self._expect_error([QUERIES[0], dict(QUERIES[0])], "duplicate query_id")

    def test_reversed_span_is_rejected(self):
        broken = query("q1", "산책 인사법은?", "vid1", [(19000, 11000)])
        self._expect_error([broken], "0 <= start_ms < end_ms")


class ApprovedGateTests(unittest.TestCase):
    def test_all_pending_exits_non_zero_without_loading_a_model(self):
        pending = [dict(row, review_status="PENDING", reviewed_at=None) for row in QUERIES]
        fixture = Fixture(queries=pending)
        with no_model_load(self):
            code, output = run_main([
                "--query-set", str(fixture.query_set),
                "--chunk-dir", str(fixture.chunk_dir),
                "--transcript-dir", str(fixture.transcript_dir),
                "--result-dir", str(fixture.result_dir),
            ])
        self.assertEqual(1, code)
        self.assertIn("no APPROVED query", output)
        self.assertIn("The embedding model is not loaded.", output)
        self.assertFalse(fixture.result_dir.exists())

    def test_empty_split_exits_non_zero_without_loading_a_model(self):
        fixture = Fixture()  # every fixture query is split=dev
        with no_model_load(self):
            code, output = run_main([
                "--split", "test",
                "--query-set", str(fixture.query_set),
                "--chunk-dir", str(fixture.chunk_dir),
                "--transcript-dir", str(fixture.transcript_dir),
                "--result-dir", str(fixture.result_dir),
            ])
        self.assertEqual(1, code)
        self.assertIn("no APPROVED query in split 'test'", output)

    def test_rejected_queries_are_not_evaluated(self):
        queries = [QUERIES[0], dict(QUERIES[1], review_status="REJECTED", reviewed_at="2026-08-17")]
        fixture = Fixture(queries=queries)
        payload = fixture.evaluate()["payload"]
        self.assertEqual(1, payload["query_set"]["evaluated_queries"])
        self.assertEqual(["q1"], [row["query_id"] for row in payload["per_query"]])


class DeviceTests(unittest.TestCase):
    def _cli(self, fixture, *extra):
        return run_main([
            "--query-set", str(fixture.query_set),
            "--chunk-dir", str(fixture.chunk_dir),
            "--transcript-dir", str(fixture.transcript_dir),
            "--result-dir", str(fixture.result_dir),
            *extra,
        ])

    def test_cpu_is_the_default(self):
        self.assertEqual("cpu", module.RunSettings().device)
        self.assertEqual("cpu", module.build_parser().parse_args([]).device)

    def test_only_cpu_and_cuda_are_accepted(self):
        for device in ("cpu", "cuda"):
            module.RunSettings(device=device).validate()
        for device in ("gpu", "mps", "cuda:0", "CPU", ""):
            with self.assertRaises(module.EvaluationError) as caught:
                module.RunSettings(device=device).validate()
            self.assertIn("--device must be one of", str(caught.exception))

    def test_unusable_cuda_fails_before_the_model_is_loaded(self):
        fixture = Fixture()
        with no_model_load(self), cuda(False):
            with self.assertRaises(module.EvaluationError) as caught:
                module.run_evaluation(
                    fixture.query_set, fixture.chunk_dir, fixture.transcript_dir,
                    fixture.result_dir, module.RunSettings(device="cuda"), encoder=None,
                )
        self.assertIn("no usable CUDA device", str(caught.exception))
        self.assertIn("The embedding model is not loaded.", str(caught.exception))
        self.assertFalse(fixture.result_dir.exists())

    def test_cli_exits_non_zero_when_cuda_is_unusable(self):
        fixture = Fixture()
        with no_model_load(self), cuda(False):
            code, output = self._cli(fixture, "--device", "cuda")
        self.assertEqual(1, code)
        self.assertIn("no usable CUDA device", output)
        self.assertIn("--device cpu", output)
        self.assertFalse(fixture.result_dir.exists())

    def test_cli_rejects_an_unknown_device_without_loading_a_model(self):
        fixture = Fixture()
        with no_model_load(self), cuda(None):
            code, output = self._cli(fixture, "--device", "gpu")
        self.assertEqual(1, code)
        self.assertIn("--device must be one of", output)
        self.assertFalse(fixture.result_dir.exists())

    def test_available_cuda_is_recorded_in_the_runtime_artifact(self):
        with cuda(True):
            result = Fixture().evaluate(device="cuda")
        runtime = json.loads(result["runtime_path"].read_text(encoding="utf-8"))
        self.assertEqual("cuda", runtime["device"])

    def test_cpu_run_records_the_device_outside_the_metrics_artifact(self):
        with cuda(None):  # a cpu run has nothing to probe
            result = Fixture().evaluate()
        runtime = json.loads(result["runtime_path"].read_text(encoding="utf-8"))
        self.assertEqual("cpu", runtime["device"])
        # The device is an environment property, so it stays out of the
        # deterministic metrics artifact along with the timings.
        payload = json.loads(result["metrics_path"].read_text(encoding="utf-8"))
        self.assertNotIn("device", set(json_keys(payload)))

    def test_review_only_never_probes_the_device_or_loads_a_model(self):
        fixture = Fixture()
        with no_model_load(self), cuda(None):
            code, output = run_main([
                "--review-only", "--device", "cuda",
                "--query-set", str(fixture.query_set),
                "--chunk-dir", str(fixture.chunk_dir),
                "--transcript-dir", str(fixture.transcript_dir),
                "--review-path", str(fixture.review_path),
            ])
        self.assertEqual(0, code)
        self.assertIn("review report:", output)
        self.assertTrue(fixture.review_path.is_file())


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.payload = Fixture().evaluate()["payload"]
        self.metrics = self.payload["metrics"]

    def test_hit_metrics_are_reported_as_raw_counts(self):
        self.assertEqual({"successful_queries": 1, "total_queries": 3, "ratio": 0.333333}, self.metrics["hit@1"])
        self.assertEqual({"successful_queries": 3, "total_queries": 3, "ratio": 1.0}, self.metrics["hit@3"])
        self.assertEqual({"successful_queries": 3, "total_queries": 3, "ratio": 1.0}, self.metrics["hit@5"])

    def test_mrr_is_a_macro_average_not_a_success_count(self):
        entry = self.metrics["mrr@5"]
        self.assertEqual(1.833333, entry["reciprocal_rank_sum"])
        self.assertEqual(3, entry["total_queries"])
        self.assertEqual(0.611111, entry["macro_average"])
        self.assertNotIn("successful_queries", entry)

    def test_recall_is_a_macro_average(self):
        self.assertEqual({"macro_average": 0.666667, "total_queries": 3}, self.metrics["recall@5"])
        self.assertNotIn("successful_queries", self.metrics["recall@5"])

    def test_span_recall_separates_macro_average_from_micro_counts(self):
        self.assertEqual({"macro_average": 0.833333, "total_queries": 3}, self.metrics["macro_span_recall@5"])
        self.assertEqual(
            {"covered_spans": 3, "total_gold_spans": 4, "ratio": 0.75},
            self.metrics["span_coverage@5"],
        )

    def test_per_query_rows_carry_rank_and_reciprocal_rank(self):
        rows = {row["query_id"]: row for row in self.payload["per_query"]}
        self.assertEqual((1, 1.0, 1.0, 1.0), (rows["q1"]["first_relevant_rank"], rows["q1"]["reciprocal_rank"], rows["q1"]["recall@5"], rows["q1"]["span_recall@5"]))
        self.assertEqual((2, 0.5, 0.5, 1.0), (rows["q2"]["first_relevant_rank"], rows["q2"]["reciprocal_rank"], rows["q2"]["recall@5"], rows["q2"]["span_recall@5"]))
        self.assertEqual((3, 0.333333, 0.5, 0.5), (rows["q3"]["first_relevant_rank"], rows["q3"]["reciprocal_rank"], rows["q3"]["recall@5"], rows["q3"]["span_recall@5"]))

    def test_ineligible_chunks_never_enter_the_ranking(self):
        ranked = {row["chunk_id"] for entry in self.payload["per_query"] for row in entry["results"]}
        self.assertNotIn("chunk-a0", ranked)
        self.assertEqual(7, self.payload["corpus"]["eligible_chunks"])
        self.assertEqual(8, self.payload["corpus"]["total_chunks"])

    def test_missed_relevant_chunk_yields_no_rank(self):
        weights = {"산책 인사법은?": [0.1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4]}
        fixture = Fixture(queries=[QUERIES[0]])
        payload = fixture.evaluate(encoder=ScriptedEncoder(weights=weights))["payload"]
        row = payload["per_query"][0]
        self.assertIsNone(row["first_relevant_rank"])
        self.assertEqual(0.0, row["reciprocal_rank"])
        self.assertEqual(0, payload["metrics"]["hit@5"]["successful_queries"])
        self.assertEqual(0.0, payload["metrics"]["macro_span_recall@5"]["macro_average"])


class DeterminismTests(unittest.TestCase):
    def test_ties_break_on_ascending_chunk_id(self):
        weights = {"산책 인사법은?": [0.5] * 7}
        fixture = Fixture(queries=[QUERIES[0]])
        payload = fixture.evaluate(encoder=ScriptedEncoder(weights=weights), top_k=7)["payload"]
        ranked = [row["chunk_id"] for row in payload["per_query"][0]["results"]]
        self.assertEqual(sorted(CORPUS_ORDER), ranked)

    def test_scores_are_serialized_with_fixed_decimals(self):
        weights = {"산책 인사법은?": [1 / 3, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]}
        fixture = Fixture(queries=[QUERIES[0]])
        payload = fixture.evaluate(encoder=ScriptedEncoder(weights=weights))["payload"]
        self.assertEqual(0.333333, payload["per_query"][0]["results"][0]["score"])
        self.assertEqual(6, payload["run"]["score_decimals"])
        self.assertEqual("ascending chunk_id", payload["run"]["tie_break"])

    def test_fake_encoder_metrics_are_byte_identical_across_runs(self):
        first_fixture, second_fixture = Fixture(), Fixture()
        first = first_fixture.evaluate()["metrics_path"].read_bytes()
        second = second_fixture.evaluate()["metrics_path"].read_bytes()
        self.assertEqual(first, second)
        # The two fixtures run from different temp directories, so a byte-identical
        # artifact is only possible if no run location reached it.
        self.assertNotIn(first_fixture.directory.name, first.decode("utf-8"))

    def test_corpus_provenance_is_content_addressed_not_path_addressed(self):
        payload = Fixture().evaluate()["payload"]
        self.assertEqual(["vid1", "vid2"], payload["corpus"]["video_ids"])
        self.assertEqual(8, payload["corpus"]["total_chunks"])
        self.assertNotIn("chunk_dir", payload["corpus"])
        self.assertNotIn("path", payload["query_set"])

    def test_latency_is_kept_out_of_the_metrics_artifact(self):
        result = Fixture().evaluate()
        payload = json.loads(result["metrics_path"].read_text(encoding="utf-8"))
        # Key based on purpose: the artifact documents its own limitations in prose,
        # and that prose is free to use words like "latency".
        for key in sorted(set(json_keys(payload))):
            for token in TIMING_KEY_TOKENS:
                self.assertNotIn(token, key.lower(), f"timing field {key!r} in metrics payload")
        runtime = json.loads(result["runtime_path"].read_text(encoding="utf-8"))
        self.assertIn("corpus_encode_ms", runtime)
        self.assertEqual(3, len(runtime["per_query"]))

    def test_metadata_records_model_and_dependency_versions(self):
        payload = Fixture().evaluate()["payload"]
        self.assertEqual("fake", payload["run"]["model_name"])
        self.assertEqual({"fake-encoder": "fake-scripted-v1"}, payload["run"]["dependency_versions"])
        self.assertEqual("query: ", payload["run"]["query_prefix"])
        self.assertEqual("passage: ", payload["run"]["passage_prefix"])
        self.assertTrue(payload["corpus"]["fingerprint"].startswith("sha256:"))
        self.assertTrue(payload["query_set"]["fingerprint"].startswith("sha256:"))

    def test_dependency_versions_resolve_without_importing_a_model(self):
        versions = module.dependency_versions(("definitely-not-installed-pkg",))
        self.assertEqual({"definitely-not-installed-pkg": "not-installed"}, versions)


class ReportTests(unittest.TestCase):
    def test_run_report_labels_counts_and_averages_differently(self):
        report = Fixture().evaluate()["report_path"].read_text(encoding="utf-8")
        self.assertIn("성공 개수로 읽는 지표", report)
        self.assertIn("평균으로 읽는 지표 (성공 개수가 아닙니다)", report)
        self.assertIn("| Hit@1 | 1 / 3 |", report)
        self.assertIn("reciprocal_rank 합계", report)
        self.assertIn("| span_coverage@5 | 3 / 4 |", report)

    def test_run_report_records_the_smoke_benchmark_limitation(self):
        report = Fixture().evaluate()["report_path"].read_text(encoding="utf-8")
        self.assertIn("smoke benchmark", report)
        self.assertIn("일반적인 한국어 검색 성능을 증명하지 않는다", report)
        self.assertIn("test 결과를 보면서 threshold", report)


class ChunkingSettingsTests(unittest.TestCase):
    """The corpus must say which chunker run produced it."""

    def _chunks(self, **overrides):
        rows = {video_id: [dict(row) for row in rows] for video_id, rows in CHUNKS.items()}
        for chunk_id, chunking in overrides.items():
            for video_rows in rows.values():
                for row in video_rows:
                    if row["chunk_id"] == chunk_id:
                        if chunking is None:
                            row.pop("chunking", None)
                        else:
                            row["chunking"] = chunking
        return rows

    def test_settings_reach_the_metrics_corpus_block(self):
        payload = Fixture().evaluate()["payload"]
        self.assertEqual(FIXTURE_CHUNKING, payload["corpus"]["chunking"])

    def test_settings_are_a_data_property_so_metrics_stay_byte_identical(self):
        first = Fixture().evaluate()["metrics_path"].read_bytes()
        second = Fixture().evaluate()["metrics_path"].read_bytes()
        self.assertEqual(first, second)
        self.assertIn(b'"target_chars": 420', first)
        runtime = json.loads(Fixture().evaluate()["runtime_path"].read_text(encoding="utf-8"))
        self.assertNotIn("chunking", set(json_keys(runtime)))

    def test_a_corpus_mixing_two_chunker_runs_is_rejected(self):
        mixed = {"target_chars": 220, "min_chars": 80, "max_chars": 320, "overlap_segments": 0}
        fixture = Fixture(chunks=self._chunks(**{"chunk-b1": mixed}))
        with no_model_load(self), self.assertRaises(module.EvaluationError) as caught:
            fixture.evaluate()
        message = str(caught.exception)
        self.assertIn("mixes chunking settings", message)
        self.assertIn("chunk-b1", message)

    def test_a_corpus_missing_the_field_on_some_chunks_is_also_mixed(self):
        fixture = Fixture(chunks=self._chunks(**{"chunk-a2": None}))
        with no_model_load(self), self.assertRaises(module.EvaluationError):
            fixture.evaluate()

    def test_a_legacy_corpus_without_the_field_reports_null(self):
        """Corpora chunked before the field existed stay evaluable, and say nothing."""
        legacy = {
            video_id: [chunk(**{**_chunk_kwargs(row), "chunking": None}) for row in rows]
            for video_id, rows in CHUNKS.items()
        }
        payload = Fixture(chunks=legacy).evaluate()["payload"]
        self.assertIsNone(payload["corpus"]["chunking"])
        self.assertEqual(3, payload["metrics"]["hit@5"]["successful_queries"])

    def test_a_malformed_settings_object_is_rejected_at_load(self):
        broken = {"target_chars": 420, "min_chars": 150, "max_chars": "480", "overlap_segments": 0}
        fixture = Fixture(chunks=self._chunks(**{"chunk-a1": broken}))
        with no_model_load(self), self.assertRaises(module.EvaluationError) as caught:
            fixture.evaluate()
        self.assertIn("chunking.max_chars", str(caught.exception))

    def test_the_chunker_writes_what_the_evaluator_reads(self):
        """Pin the contract between the two scripts, not each side's idea of it."""
        chunker = _load_script("chunk_approved_youtube")
        written = chunker.ChunkingConfig().payload()
        self.assertEqual(sorted(module.CHUNKING_SETTING_KEYS), sorted(written))
        # The adopted defaults must be what a plain, flagless chunker run produces.
        self.assertEqual(ADOPTED_CHUNKING, written)


class SimilarityStatisticsTests(unittest.TestCase):
    """Per query similarity spread, recorded so a threshold can be chosen later."""

    # top1 0.9 stands well clear of the rest; the tail sits outside top-5 on purpose.
    PEAKED = {"산책 인사법은?": [0.9, 0.2, 0.15, 0.1, 0.05, 0.05, 0.05]}
    # No chunk answers the question: everything crowds together near the mean.
    FLAT = {"산책 인사법은?": [0.84, 0.83, 0.82, 0.81, 0.80, 0.79, 0.78]}

    def _inputs(self, weights=None, top_k=module.DEFAULT_TOP_K, queries=QUERIES):
        """Rebuild what run_evaluation feeds build_metrics, without writing artifacts."""
        fixture = Fixture(queries=queries)
        chunks = module.load_chunks(fixture.chunk_dir)
        corpus = module.eligible_chunks(chunks)
        bounds = module.load_transcript_bounds(
            fixture.transcript_dir, [row["video_id"] for row in chunks]
        )
        plans = module.build_query_plans(module.load_queries(fixture.query_set), chunks, bounds)
        encoder = ScriptedEncoder(weights=weights)
        corpus_vectors = encoder.encode([module.PASSAGE_PREFIX + row["text"] for row in corpus])
        chunk_ids = [row["chunk_id"] for row in corpus]
        rankings, stats = {}, {}
        for plan in plans:
            query_vector = encoder.encode([module.QUERY_PREFIX + plan.query["question"]])[0]
            scores = module.similarity_scores(query_vector, corpus_vectors)
            rankings[plan.query_id] = module.rank_scores(scores, chunk_ids, top_k)
            stats[plan.query_id] = module.score_statistics(scores)
        return plans, rankings, {row["chunk_id"]: row for row in corpus}, stats

    def _row(self, weights):
        fixture = Fixture(queries=[QUERIES[0]])
        payload = fixture.evaluate(encoder=ScriptedEncoder(weights=weights))["payload"]
        return payload["per_query"][0]

    def test_per_query_rows_record_top1_mean_and_gap(self):
        row = self._row(self.PEAKED)
        self.assertEqual(0.9, row["top1_score"])
        self.assertEqual(0.214286, row["corpus_mean_score"])
        self.assertEqual(0.685714, row["score_gap"])

    def test_statistics_average_the_whole_corpus_not_the_top_k(self):
        row = self._row(self.PEAKED)
        returned = [result["score"] for result in row["results"]]
        self.assertEqual(5, len(returned))
        # Mean of the returned five is 0.28; the corpus mean must include the tail.
        self.assertNotEqual(0.28, row["corpus_mean_score"])
        self.assertEqual(0.214286, row["corpus_mean_score"])

    def test_top1_score_matches_the_first_ranked_result(self):
        for row in Fixture().evaluate()["payload"]["per_query"]:
            self.assertEqual(row["results"][0]["score"], row["top1_score"], row["query_id"])

    def test_a_flat_distribution_reports_a_small_gap(self):
        # The absolute top1 is high in both cases; only the gap separates them.
        peaked, flat = self._row(self.PEAKED), self._row(self.FLAT)
        self.assertEqual(0.84, flat["top1_score"])
        self.assertEqual(0.81, flat["corpus_mean_score"])
        self.assertEqual(0.03, flat["score_gap"])
        self.assertGreater(peaked["score_gap"], flat["score_gap"])

    def test_rank_margins_are_recorded_next_to_the_corpus_mean_gap(self):
        row = self._row(self.PEAKED)
        # scores 0.9, 0.2, 0.15, 0.1, 0.05 | 0.05, 0.05
        self.assertEqual(0.7, row["top1_minus_top2"])
        self.assertEqual(0.85, row["top1_minus_top5"])
        self.assertEqual(0.314006, row["top5_std"])

    def test_a_flat_top_of_the_ranking_collapses_every_margin(self):
        """The hypothesis under test: no answer in the corpus means no clear rank 1."""
        peaked, flat = self._row(self.PEAKED), self._row(self.FLAT)
        self.assertEqual(0.01, flat["top1_minus_top2"])
        self.assertEqual(0.04, flat["top1_minus_top5"])
        self.assertEqual(0.014142, flat["top5_std"])
        for key in ("top1_minus_top2", "top1_minus_top5", "top5_std"):
            self.assertGreater(peaked[key], flat[key], key)
        # top1 alone does not separate them: 0.84 is a high-looking score either way.
        self.assertGreater(flat["top1_score"], 0.8)

    def test_margins_use_the_fixed_cutoff_not_the_requested_top_k(self):
        """A wider --top-k must not redefine what "top5" means, or runs stop comparing."""
        fixture = Fixture(queries=[QUERIES[0]])
        wide = fixture.evaluate(encoder=ScriptedEncoder(weights=self.PEAKED), top_k=7)["payload"]
        narrow = self._row(self.PEAKED)
        row = wide["per_query"][0]
        self.assertEqual(7, len(row["results"]))
        for key in module.SCORE_STAT_KEYS:
            self.assertEqual(narrow[key], row[key], key)

    def test_margins_are_measured_on_scores_not_on_tie_break_order(self):
        """Ties make rank order arbitrary; equal scores must still give a zero margin."""
        row = self._row({"산책 인사법은?": [0.5] * 7})
        self.assertEqual(0.0, row["top1_minus_top2"])
        self.assertEqual(0.0, row["top1_minus_top5"])
        self.assertEqual(0.0, row["top5_std"])
        self.assertEqual(0.0, row["score_gap"])

    def test_a_corpus_shorter_than_the_cutoff_reports_null_margins(self):
        """Report "undefined" rather than a top5 figure computed over three scores."""
        stats = module.score_statistics([0.9, 0.4, 0.1])
        self.assertEqual(0.5, stats["top1_minus_top2"])
        self.assertIsNone(stats["top1_minus_top5"])
        self.assertIsNone(stats["top5_std"])
        single = module.score_statistics([0.9])
        self.assertIsNone(single["top1_minus_top2"])
        self.assertEqual(0.9, single["top1_score"])

    def test_build_metrics_runs_without_the_statistics_argument(self):
        plans, rankings, chunk_by_id, _ = self._inputs()
        metrics, per_query = module.build_metrics(plans, rankings, chunk_by_id)
        self.assertEqual(3, metrics["hit@5"]["successful_queries"])
        for row in per_query:
            for key in module.SCORE_STAT_KEYS:
                self.assertNotIn(key, row)
            self.assertEqual(5, len(row["results"]))

    def test_statistics_never_move_the_existing_metrics(self):
        plans, rankings, chunk_by_id, stats = self._inputs()
        without, rows_without = module.build_metrics(plans, rankings, chunk_by_id)
        with_stats, rows_with = module.build_metrics(plans, rankings, chunk_by_id, stats)
        self.assertEqual(without, with_stats)
        stripped = [
            {key: value for key, value in row.items() if key not in module.SCORE_STAT_KEYS}
            for row in rows_with
        ]
        self.assertEqual(rows_without, stripped)

    def test_statistics_land_in_metrics_not_in_the_runtime_artifact(self):
        result = Fixture().evaluate()
        payload = json.loads(result["metrics_path"].read_text(encoding="utf-8"))
        runtime = json.loads(result["runtime_path"].read_text(encoding="utf-8"))
        recorded = set(json_keys(payload))
        for key in module.SCORE_STAT_KEYS:
            self.assertIn(key, recorded)
            self.assertNotIn(key, set(json_keys(runtime)))

    def test_statistics_stay_byte_identical_across_runs(self):
        first = Fixture().evaluate()["metrics_path"].read_bytes()
        second = Fixture().evaluate()["metrics_path"].read_bytes()
        self.assertEqual(first, second)

    def test_an_empty_corpus_score_list_is_an_error(self):
        with self.assertRaises(module.EvaluationError):
            module.score_statistics([])


PROVISIONAL_REASON = "MVP baseline 실행을 위한 임시 승인. 영상 근거 및 ASR 품질 정밀 검토 필요"

# Corpus size is a function of the chunking settings in scripts/chunk_approved_youtube.py,
# not a target of its own. It moves whenever those settings move:
#
#   target / min / max   chunks / eligible  run           corpus
#   220 / 80 / 320       53 / 42            baseline_v1   data/processed/youtube/chunks_v1 (kept)
#   520 / 200 / 640      29 / 20            exp_a_v2      not kept
#   420 / 150 / 480      35 / 26            exp_a2_v3     data/processed/youtube/chunks (adopted)
#
# The adopted settings merge the short ASR segments into fewer and longer chunks, hence
# 53 -> 35. Snapshots of each run are under data/eval/results/*_e5_metrics.json.
#
# The settings are no longer pinned by hand: each chunk record carries them, so
# ADOPTED_CHUNKING is checked against what the corpus actually says about itself. The
# counts still have to be pinned — no amount of reading the data reproduces a count
# without re-running the chunker, and that is exactly what makes them a useful tripwire.
#
# To update after an intentional re-chunk: re-run the chunker, confirm the new counts are
# the ones you meant to produce, then update ADOPTED_CHUNKING and both counts together and
# add a row above. Do not change them to whatever the failure happens to print.
ADOPTED_CHUNKING = {
    "target_chars": 420,
    "min_chars": 150,
    "max_chars": 480,
    "overlap_segments": 0,
}
CORPUS_CHUNKS = 35
CORPUS_ELIGIBLE_CHUNKS = 26


class RealQuerySetTests(unittest.TestCase):
    """The shipped query set must validate against the real corpus."""

    query_set = REPO / module.DEFAULT_QUERY_SET
    chunk_dir = REPO / module.DEFAULT_CHUNK_DIR
    transcript_dir = REPO / module.DEFAULT_TRANSCRIPT_DIR

    def setUp(self):
        if not self.chunk_dir.is_dir() or not self.query_set.is_file():
            self.skipTest("local corpus is not present")

    def test_candidate_set_validates_against_the_real_corpus(self):
        chunks = module.load_chunks(self.chunk_dir)
        bounds = module.load_transcript_bounds(self.transcript_dir, (row["video_id"] for row in chunks))
        with no_model_load(self):
            plans = module.build_query_plans(module.load_queries(self.query_set), chunks, bounds)
        self.assertEqual(18, len(plans))
        # The message carries the cause: a count mismatch here is a re-chunk, not a
        # broken query set. See the constants above for the settings each count belongs to.
        # The corpus records the settings it was built with, so the message can name the
        # cause instead of describing it: re-chunk, or a corpus edit under the same settings.
        recorded = module.corpus_chunking(chunks)
        cause = (
            f"the corpus was chunked with {recorded}, not the adopted {ADOPTED_CHUNKING}"
            if recorded != ADOPTED_CHUNKING
            else "the chunking settings still match, so the corpus content itself changed "
            "(a video added, removed or re-transcribed)"
        )
        rechunked = (
            f"corpus size changed: {cause}. Confirm the new corpus is the one you meant to "
            f"build, then update CORPUS_CHUNKS / CORPUS_ELIGIBLE_CHUNKS and the settings "
            f"table next to them."
        )
        self.assertEqual(CORPUS_CHUNKS, len(chunks), rechunked)
        self.assertEqual(CORPUS_ELIGIBLE_CHUNKS, len(module.eligible_chunks(chunks)), rechunked)

    def test_corpus_records_the_adopted_chunking_settings(self):
        """Read the settings off the corpus instead of trusting a hand-kept constant."""
        chunks = module.load_chunks(self.chunk_dir)
        self.assertEqual(
            ADOPTED_CHUNKING,
            module.corpus_chunking(chunks),
            "the corpus was built by a chunker run with different settings than the "
            "adopted ones; see the settings table above",
        )

    def test_corpus_content_obeys_the_settings_it_records(self):
        """A record could claim settings its text does not satisfy; check the claim.

        The chunker never emits a chunk longer than max_chars, so an over-long chunk
        means the recorded settings do not describe how the text was actually cut.
        """
        chunks = module.load_chunks(self.chunk_dir)
        longest = max(chunks, key=lambda row: row["char_count"])
        self.assertLessEqual(
            longest["char_count"],
            ADOPTED_CHUNKING["max_chars"],
            f"chunk {longest['chunk_id']} is longer than the max_chars its own record "
            f"claims: the corpus and its recorded settings disagree",
        )

    def test_dev_is_provisionally_approved_and_test_stays_untouched(self):
        """dev carries a provisional MVP approval; test must stay unreviewed."""
        queries = module.load_queries(self.query_set)
        by_split: dict[str, list] = {}
        for row in queries:
            by_split.setdefault(row["split"], []).append(row)

        dev = by_split["dev"]
        self.assertEqual({"APPROVED"}, {row["review_status"] for row in dev})
        self.assertEqual({"2026-08-17"}, {row["reviewed_at"] for row in dev})
        self.assertEqual({PROVISIONAL_REASON}, {row["review_reason"] for row in dev})

        # The held-out split must not be touched until the final check.
        held_out = by_split["test"]
        self.assertEqual({"PENDING"}, {row["review_status"] for row in held_out})
        self.assertEqual({None}, {row["reviewed_at"] for row in held_out})
        self.assertEqual({""}, {row["review_reason"] for row in held_out})

    def test_split_and_type_distribution(self):
        queries = module.load_queries(self.query_set)
        self.assertEqual({"dev": 12, "test": 6}, module._counts(row["split"] for row in queries))
        self.assertEqual(set(module.QUERY_TYPES), {row["query_type"] for row in queries})


if __name__ == "__main__":
    unittest.main()
