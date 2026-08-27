"""qa_id 형제 확장 (Q&A authority 라운드 2단계).

합성 픽스처만 쓴다. 실제 wayopet 청크는 아직 코퍼스에 없고(코퍼스 확대
라운드에서 투입), 여기서 검증할 것은 확장 규칙 자체이지 특정 문서가 아니다.

핵심 불변식: **확장은 게이트 통계 계산 이후에만 일어난다.** 확장이 유사도
분포나 랭킹에 영향을 주면 별도로 검증을 마친 게이트 신호 결정이 무효화된다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_combined_retrieval_eval as ev  # noqa: E402


def chunk(chunk_id, role=None, qa_id=None, chunk_index=0):
    record = {
        "chunk_id": chunk_id,
        "text": f"text of {chunk_id}",
        "chunk_index": chunk_index,
        "source_kind": "document",
    }
    if role is not None:
        record["segment_role"] = role
    if qa_id is not None:
        record["qa_id"] = qa_id
    return record


class BuildIndexTests(unittest.TestCase):
    def test_index_groups_answers_by_qa_id_in_document_order(self):
        corpus = [
            chunk("a2", ev.ROLE_EXPERT_ANSWER, "QA1", chunk_index=2),
            chunk("a0", ev.ROLE_EXPERT_ANSWER, "QA1", chunk_index=0),
            chunk("a1", ev.ROLE_EXPERT_ANSWER, "QA1", chunk_index=1),
            chunk("q0", ev.ROLE_OWNER_QUESTION, "QA1", chunk_index=0),
        ]
        index = ev.build_qa_answer_index(corpus)
        # 답변이 여러 청크로 쪼개졌을 때 순서가 뒤섞이면 절차 설명이 끊긴다.
        self.assertEqual(index, {"QA1": ["a0", "a1", "a2"]})

    def test_chunks_without_qa_id_are_absent_from_index(self):
        corpus = [chunk("d0"), chunk("v0", ev.ROLE_EXPERT_ANSWER)]  # qa_id 없음
        self.assertEqual(ev.build_qa_answer_index(corpus), {})


class ExpansionTests(unittest.TestCase):
    def _run(self, evidence, corpus):
        by_id = {c["chunk_id"]: c for c in corpus}
        return ev.expand_qa_siblings(evidence, by_id, ev.build_qa_answer_index(corpus))

    def test_case1_no_qa_id_chunks_means_no_change(self):
        """qa_id 없는 청크만 적중 — 확장 미발생, 동작 불변."""
        corpus = [chunk("d0"), chunk("d1"), chunk("d2")]
        out, info = self._run(["d0", "d1", "d2"], corpus)
        self.assertEqual(out, ["d0", "d1", "d2"])
        self.assertEqual(info["appended_answer_chunk_ids"], [])
        self.assertEqual(info["dropped_orphan_question_chunk_ids"], [])

    def test_case2_owner_question_pulls_in_sibling_answer(self):
        """OWNER_QUESTION 적중 -> 형제 EXPERT_ANSWER 추가."""
        corpus = [
            chunk("q", ev.ROLE_OWNER_QUESTION, "QA1"),
            chunk("a", ev.ROLE_EXPERT_ANSWER, "QA1"),
            chunk("d0"),
        ]
        out, info = self._run(["d0", "q"], corpus)
        self.assertEqual(out, ["d0", "q", "a"])
        self.assertEqual(info["appended_answer_chunk_ids"], ["a"])

    def test_case3_sibling_already_ranked_is_not_duplicated(self):
        """형제 답변이 이미 랭킹 결과에 있으면 중복 추가하지 않는다."""
        corpus = [
            chunk("q", ev.ROLE_OWNER_QUESTION, "QA1"),
            chunk("a", ev.ROLE_EXPERT_ANSWER, "QA1"),
        ]
        out, info = self._run(["a", "q"], corpus)
        self.assertEqual(out, ["a", "q"])  # 원래 순서 유지
        self.assertEqual(info["appended_answer_chunk_ids"], [])

    def test_case4_multiple_answer_chunks_all_added_in_order(self):
        """같은 qa_id에 EXPERT_ANSWER가 여러 청크 — 전부, 문서 순서로 추가.

        일부만 주면 권고가 중간에서 잘린다. 상한(EXPANSION_MAX_SIBLINGS)을
        넘으면 조용히 자르지 않고 몇 개를 버렸는지 기록한다.
        """
        corpus = [chunk("q", ev.ROLE_OWNER_QUESTION, "QA1")] + [
            chunk(f"a{i}", ev.ROLE_EXPERT_ANSWER, "QA1", chunk_index=i) for i in range(3)
        ]
        out, info = self._run(["q"], corpus)
        self.assertEqual(out, ["q", "a0", "a1", "a2"])
        self.assertEqual(info["truncated_siblings_by_qa_id"], {})

    def test_case4b_sibling_count_over_cap_is_recorded_not_silently_cut(self):
        cap = ev.EXPANSION_MAX_SIBLINGS
        corpus = [chunk("q", ev.ROLE_OWNER_QUESTION, "QA1")] + [
            chunk(f"a{i}", ev.ROLE_EXPERT_ANSWER, "QA1", chunk_index=i) for i in range(cap + 2)
        ]
        out, info = self._run(["q"], corpus)
        self.assertEqual(len(info["appended_answer_chunk_ids"]), cap)
        self.assertEqual(info["truncated_siblings_by_qa_id"], {"QA1": 2})

    def test_case5_orphan_question_is_dropped_fail_closed(self):
        """qa_id는 있으나 형제 답변이 없으면 질문을 근거에서 뺀다.

        인용 가능한 짝이 없는 견주 발화를 근거로 남기면, 인용 금지 표시가
        있더라도 모델이 그것만 보고 답을 지어낼 여지가 생긴다.
        """
        corpus = [chunk("q", ev.ROLE_OWNER_QUESTION, "QA_MISSING"), chunk("d0")]
        out, info = self._run(["d0", "q"], corpus)
        self.assertEqual(out, ["d0"])
        self.assertEqual(info["dropped_orphan_question_chunk_ids"], ["q"])
        self.assertEqual(info["appended_answer_chunk_ids"], [])

    def test_expert_answer_hit_alone_needs_no_expansion(self):
        """답변만 적중한 경우는 이미 인용 가능하므로 붙일 것이 없다."""
        corpus = [
            chunk("q", ev.ROLE_OWNER_QUESTION, "QA1"),
            chunk("a", ev.ROLE_EXPERT_ANSWER, "QA1"),
        ]
        out, info = self._run(["a"], corpus)
        self.assertEqual(out, ["a"])
        self.assertEqual(info["appended_answer_chunk_ids"], [])

    def test_expansion_is_idempotent(self):
        corpus = [
            chunk("q", ev.ROLE_OWNER_QUESTION, "QA1"),
            chunk("a", ev.ROLE_EXPERT_ANSWER, "QA1"),
        ]
        once, _ = self._run(["q"], corpus)
        twice, _ = self._run(once, corpus)
        self.assertEqual(once, twice)


class OrderingInvariantTests(unittest.TestCase):
    """확장이 게이트 통계 이후에만 일어남을 고정한다."""

    def test_expansion_does_not_touch_scores_or_ranking(self):
        """expand_qa_siblings는 점수·순위 자료를 인자로 받지도 않는다.

        시그니처 자체로 불변식을 강제한다 — 나중에 누가 여기에 scores를
        넘기려 하면 이 테스트가 먼저 눈에 띈다.
        """
        import inspect

        params = list(inspect.signature(ev.expand_qa_siblings).parameters)
        self.assertEqual(params, ["evidence_ids", "by_id", "qa_index"])
        for forbidden in ("scores", "stats", "ranked", "matrix"):
            self.assertNotIn(forbidden, params)

    def test_gate_stats_computed_before_expansion_in_source(self):
        """호출 순서를 소스에서 고정한다.

        게이트 통계 계산(gate_verdict)이 확장(expand_qa_siblings)보다 먼저
        나와야 한다. 순서가 뒤집히면 유사도 분포가 오염돼 게이트 신호 결정이
        무효화된다.
        """
        source = Path(ev.__file__).read_text(encoding="utf-8")
        for call in ("gate_verdict(stats", "expand_qa_siblings("):
            self.assertIn(call, source)
        first_gate = source.index("gate_verdict(stats")
        first_expand = source.index("expand_qa_siblings(evidence_ids")
        self.assertLess(first_gate, first_expand)

    def test_score_stats_unaffected_by_role_fields(self):
        """score_stats는 점수만 본다 — 역할 필드가 통계에 새지 않는다."""
        scores = [0.9, 0.5, 0.4, 0.3, 0.2]
        self.assertEqual(ev.score_stats(scores), ev.score_stats(list(scores)))


if __name__ == "__main__":
    unittest.main()
