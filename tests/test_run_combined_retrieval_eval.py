import importlib.util
import sys
import unittest

from pathlib import Path


REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "run_combined_retrieval_eval.py"
MODULE_NAME = "run_combined_retrieval_eval"

# Reuse an already-loaded module instead of re-executing the file: other test
# modules (test_generate_answers.py) load this same script under the same
# sys.modules key and assert identity against it, so a second exec_module()
# here would silently break that identity check.
if MODULE_NAME in sys.modules:
    module = sys.modules[MODULE_NAME]
else:
    SPEC = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT)
    module = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader
    sys.modules[MODULE_NAME] = module
    SPEC.loader.exec_module(module)


def _fixture_row(top1_score, corpus_mean_score, gate_verdict):
    score_gap = top1_score - corpus_mean_score
    return {
        "top1_score": top1_score,
        "corpus_mean_score": corpus_mean_score,
        "score_gap": score_gap,
        "gate_verdict": gate_verdict,
    }


def _base_row(top1_score, corpus_mean_score):
    score_gap = top1_score - corpus_mean_score
    return {
        "score_stats": {
            "top1_score": top1_score,
            "corpus_mean_score": corpus_mean_score,
        },
        "score_gap": score_gap,
    }


class DecompositionSectionCountsTests(unittest.TestCase):
    """Regression test for the 2026-08-21 handoff audit finding: the gate summary
    sentence in _decomposition_section used to be a literal "20건 전부 PASS ...
    지금은 77청크" string, stale from an earlier 77-chunk measurement, while the
    owner fixture table right above it already showed one REFUSE at 83 chunks.
    """

    def test_mixed_pass_refuse_and_chunk_count_are_computed_from_payload(self):
        fixtures = {
            "Q1": _fixture_row(top1_score=0.90, corpus_mean_score=0.80, gate_verdict="PASS"),
            "Q2": _fixture_row(top1_score=0.85, corpus_mean_score=0.80, gate_verdict="PASS"),
            "Q3": _fixture_row(top1_score=0.81, corpus_mean_score=0.80, gate_verdict="REFUSE"),
        }
        base = {
            "Q1": _base_row(top1_score=0.80, corpus_mean_score=0.79),  # top1 moved
            "Q2": _base_row(top1_score=0.85, corpus_mean_score=0.75),  # top1 unchanged
            "Q3": _base_row(top1_score=0.81, corpus_mean_score=0.76),  # top1 unchanged
        }
        corpus = {"combined": {"chunks": 999}}

        lines = module._decomposition_section(fixtures, base, corpus)
        text = "\n".join(lines)

        self.assertIn("999청크", text)
        self.assertIn("픽스처 3건 중 2건은 PASS, 1건은 REFUSE", text)
        self.assertIn("top1이 실제로 오른 질문은 1건", text)
        self.assertNotIn("20건 전부 PASS", text)
        self.assertNotIn("지금은 77청크", text)

    def test_different_payload_size_changes_the_reported_numbers(self):
        """A second, differently-sized payload must not echo the first test's numbers
        (or any other fixed digits) — the sentence has to be recomputed every call."""
        fixtures = {
            f"Q{i}": _fixture_row(
                top1_score=0.9, corpus_mean_score=0.8,
                gate_verdict="PASS" if i < 4 else "REFUSE",
            )
            for i in range(5)
        }
        base = {
            f"Q{i}": _base_row(top1_score=0.9, corpus_mean_score=0.7)
            for i in range(5)
        }
        corpus = {"combined": {"chunks": 12345}}

        lines = module._decomposition_section(fixtures, base, corpus)
        text = "\n".join(lines)

        self.assertIn("12345청크", text)
        self.assertIn("픽스처 5건 중 4건은 PASS, 1건은 REFUSE", text)
        self.assertNotIn("999청크", text)
        self.assertNotIn("3건 중 2건은 PASS", text)
        self.assertNotIn("20건 전부 PASS", text)
        self.assertNotIn("지금은 77청크", text)


if __name__ == "__main__":
    unittest.main()


class WithoutChunkTextTests(unittest.TestCase):
    """The committed snapshot must not carry chunk bodies.

    data/eval/results/*_metrics.json is one of the few paths .gitignore lets through,
    so a `text` field here is published source material. See
    reports/license_premise_audit_0825.md.
    """

    def test_text_is_dropped_only_where_a_chunk_id_identifies_the_row(self):
        payload = {
            "gold": [{
                "query_id": "g001",
                "question": "노즈워크가 뭔가요?",
                "top_k": [{"rank": 1, "chunk_id": "c1", "score": 0.9,
                           "where": "문서 · 도입부", "text": "원문 본문"}],
                "graph_top_k": [{"chunk_id": "c2", "text": "또 다른 원문"}],
            }],
        }
        stripped = module.without_chunk_text(payload)
        row = stripped["gold"][0]
        self.assertNotIn("text", row["top_k"][0])
        self.assertNotIn("text", row["graph_top_k"][0])
        self.assertEqual(row["top_k"][0]["chunk_id"], "c1")
        self.assertEqual(row["top_k"][0]["score"], 0.9)
        self.assertEqual(row["top_k"][0]["where"], "문서 · 도입부")
        # The question is the project's own text, not the source's.
        self.assertEqual(row["question"], "노즈워크가 뭔가요?")

    def test_a_text_field_without_a_chunk_id_is_left_alone(self):
        payload = {"run": {"note": "x", "text": "이건 청크 본문이 아니다"}}
        self.assertEqual(module.without_chunk_text(payload), payload)

    def test_the_original_payload_is_not_mutated(self):
        payload = {"top": [{"chunk_id": "c1", "text": "원문"}]}
        module.without_chunk_text(payload)
        self.assertEqual(payload["top"][0]["text"], "원문")
