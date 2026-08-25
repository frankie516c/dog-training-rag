"""문서 gold 앵커 (gold 스키마 확장).

gold가 영상 전용이던 동안 문서 청크는 정답이 될 자격이 없었다 — 코퍼스의 대부분을
차지하면서 경쟁자로만 존재했다. 이 확장은 문서에도 정답 자격을 준다.

앵커는 인용문 기반이다. 문자 오프셋은 본문이 한 글자만 바뀌어도 전부 밀리는데,
breadcrumb 제거처럼 본문 편집은 실제로 일어난다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_combined_retrieval_eval as ev  # noqa: E402

LONG = "사회화 시기가 지나고 나면 새로운 자극에 굉장히 예민하게 받아들입니다"


def doc(chunk_id, doc_id, text, index=0):
    return {"chunk_id": chunk_id, "doc_id": doc_id, "text": text,
            "chunk_index": index, "source_kind": "document"}


def vid(chunk_id, video_id, start, end):
    return {"chunk_id": chunk_id, "video_id": video_id, "start_ms": start,
            "end_ms": end, "text": "t", "source_kind": "video"}


class AnchorResolutionTests(unittest.TestCase):
    def test_anchor_resolves_to_the_chunk_containing_the_quote(self):
        docs = [doc("c1", "d1", f"앞부분 {LONG} 뒷부분"), doc("c2", "d1", "다른 내용", 1)]
        query = {"query_id": "q", "anchors": [
            {"anchor_id": "a1", "doc_id": "d1", "quote": LONG}]}
        self.assertEqual(ev.gold_relevant_chunks(query, [], docs), ("c1",))

    def test_anchor_matching_several_chunks_makes_all_of_them_gold(self):
        """같은 문장이 두 청크에 있으면 어느 쪽을 검색해도 답이 나온다."""
        docs = [doc("c1", "d1", f"x {LONG}"), doc("c2", "d1", f"y {LONG}", 1)]
        query = {"query_id": "q", "anchors": [
            {"anchor_id": "a1", "doc_id": "d1", "quote": LONG}]}
        self.assertEqual(ev.gold_relevant_chunks(query, [], docs), ("c1", "c2"))

    def test_short_anchor_is_rejected(self):
        """짧은 인용문은 다른 문단에 우연히 걸린다."""
        docs = [doc("c1", "d1", "짧은 말 그리고 나머지 본문")]
        query = {"query_id": "q", "anchors": [
            {"anchor_id": "a1", "doc_id": "d1", "quote": "짧은 말"}]}
        with self.assertRaises(ev.EvalError) as cm:
            ev.gold_relevant_chunks(query, [], docs)
        self.assertIn(str(ev.MIN_ANCHOR_CHARS), str(cm.exception))

    def test_unmatched_anchor_raises_instead_of_silently_shrinking_gold(self):
        """조용히 줄면 정답 집합이 작아져 Hit@1이 오히려 올라간다."""
        docs = [doc("c1", "d1", "본문이 편집되어 인용문이 사라진 상태")]
        query = {"query_id": "q", "anchors": [
            {"anchor_id": "a1", "doc_id": "d1", "quote": LONG}]}
        with self.assertRaises(ev.EvalError) as cm:
            ev.gold_relevant_chunks(query, [], docs)
        message = str(cm.exception)
        self.assertIn("a1", message)
        self.assertIn("d1", message)  # 복구에 필요한 정보가 메시지에 있어야 한다

    def test_unknown_doc_id_raises(self):
        query = {"query_id": "q", "anchors": [
            {"anchor_id": "a1", "doc_id": "없는문서", "quote": LONG}]}
        with self.assertRaises(ev.EvalError):
            ev.gold_relevant_chunks(query, [], [doc("c1", "d1", LONG)])


class CoexistenceTests(unittest.TestCase):
    """영상 span과 문서 앵커는 병행한다 — 합집합이다."""

    def test_video_only_query_is_unchanged(self):
        videos = [vid("v1", "V", 0, 1000)]
        query = {"query_id": "q", "video_id": "V",
                 "relevant_spans": [{"start_ms": 100, "end_ms": 200}]}
        self.assertEqual(ev.gold_relevant_chunks(query, videos, []), ("v1",))

    def test_a_query_may_hold_both_and_gold_is_the_union(self):
        """문서 답과 영상 답이 동시에 타당한 질의가 실제로 나온다.

        한쪽만 gold로 두면 정답인 검색을 오답으로 채점하게 된다.
        """
        videos = [vid("v1", "V", 0, 1000)]
        docs = [doc("c1", "d1", f"… {LONG} …")]
        query = {
            "query_id": "q",
            "video_id": "V",
            "relevant_spans": [{"start_ms": 100, "end_ms": 200}],
            "anchors": [{"anchor_id": "a1", "doc_id": "d1", "quote": LONG}],
        }
        self.assertEqual(ev.gold_relevant_chunks(query, videos, docs), ("c1", "v1"))

    def test_query_with_no_usable_reference_raises(self):
        with self.assertRaises(ev.EvalError):
            ev.gold_relevant_chunks({"query_id": "q"}, [], [])


if __name__ == "__main__":
    unittest.main()
