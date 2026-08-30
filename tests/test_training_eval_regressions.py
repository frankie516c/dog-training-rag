"""Regression contracts derived from the frozen training API evaluation set."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import medical_guardrail
from scripts.rag_api import RAGService, model_reported_no_evidence


REPO = Path(__file__).parents[1]
FROZEN = REPO / "data/eval/queries/training_api_eval_v1.jsonl"


def frozen_missing_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line and json.loads(line).get("coverage") == "missing"
    ]


class FrozenMissingGateRegressionTests(unittest.TestCase):
    def test_medical_missing_case_is_classified_as_medical_refusal(self):
        row = next(row for row in frozen_missing_rows() if "MEDICAL_REFUSAL" in row["expected_api_decisions"])
        verdict = medical_guardrail.classify_input_v2(
            row["question"],
            medical_guardrail.load_medical_terms_v2(),
            medical_guardrail.load_training_whitelist(),
        )
        self.assertTrue(verdict.is_medical)

    def test_missing_case_without_evidence_is_uncertain(self):
        row = next(row for row in frozen_missing_rows() if "UNCERTAIN" in row["expected_api_decisions"])
        # This is a content-agnostic contract: a short model response that
        # explicitly says the supplied material has no supporting content and
        # cites nothing must not be labelled as a grounded ANSWER.
        self.assertTrue(model_reported_no_evidence("제공된 자료에는 해당 주장에 대한 근거가 없습니다."))
        self.assertEqual("UNCERTAIN", row["expected_api_decisions"][0])

    def test_a_cited_qualified_answer_is_not_downgraded(self):
        self.assertFalse(model_reported_no_evidence("자료에 구체적 설명은 없지만 [2]의 절차를 참고할 수 있습니다."))

    def test_frozen_medical_missing_row_short_circuits_the_api(self):
        row = next(row for row in frozen_missing_rows() if "MEDICAL_REFUSAL" in row["expected_api_decisions"])
        retriever = _StubRetriever()
        client = _StubClient()
        service = RAGService(
            retriever=retriever,
            client=client,
            medical_terms=medical_guardrail.load_medical_terms_v2(),
            whitelist_terms=medical_guardrail.load_training_whitelist(),
            serving_document_ids=("fixture-doc",),
        )
        response = service.answer(row["question"])
        self.assertEqual("MEDICAL_REFUSAL", response.decision)
        self.assertEqual(0, retriever.search_calls)
        self.assertEqual(0, client.calls)

    def test_frozen_uncertain_missing_row_cannot_become_a_grounded_answer(self):
        row = next(row for row in frozen_missing_rows() if "UNCERTAIN" in row["expected_api_decisions"])
        retriever = _StubRetriever()
        client = _StubClient()
        service = RAGService(
            retriever=retriever,
            client=client,
            medical_terms=[],
            whitelist_terms=[],
            serving_document_ids=("fixture-doc",),
        )
        response = service.answer(row["question"])
        self.assertEqual("UNCERTAIN", response.decision)
        self.assertFalse(response.generated)
        self.assertEqual(1, client.calls)


class _StubRetriever:
    def __init__(self):
        self.search_calls = 0

    def search(self, question: str, top_k: int):
        self.search_calls += 1
        return [{
            "chunk_id": "fixture-chunk",
            "document_id": "fixture-doc",
            "chunk_index": 0,
            "text": "훈련 근거",
            "metadata": {"heading_path": ["훈련"]},
            "score": 0.9,
        }]

    def gate(self, question: str, results):
        return {"decision": "PASS", "reason": "fixture", "top_score": 0.9}


class _StubClient:
    model_id = "gemma3:4b"
    info = type("Info", (), {"name": "ollama:gemma3:4b"})()

    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str, record: dict):
        self.calls += 1
        return "제공된 자료에는 해당 주장에 대한 근거가 없습니다."


if __name__ == "__main__":
    unittest.main()
