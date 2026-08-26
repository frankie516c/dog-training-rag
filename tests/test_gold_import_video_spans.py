"""영상 gold는 청크 id가 아니라 시간축으로 기록된다.

앵커가 `doc_id`를 쓰는 이유와 같다 — `chunk_id`는 본문 해시라 재청킹·재전사에
못 견디고, 밀리초는 원본의 좌표라 견딘다. import이 사람이 고른 영상 청크를
`(video_id, relevant_spans)`로 승격하고, 그 구간이 지금 코퍼스에서 정확히 청크
하나로 되돌아오는지 다시 본다.

두 가지가 조용히 지나가면 안 된다.

1. `embedding_eligible=False` 청크가 gold가 되는 것 — 검색 대상이 아니라
   어떤 검색기도 찾을 수 없는 정답이 되고 지표가 영구히 0이 된다.
2. 한 span이 여러 청크에 걸치는 것 — 정답 집합이 조용히 커져 Hit@1이 쉬워진다.

픽스처는 전부 합성이다(`docs/SOURCES.md` 규칙 4).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import import_gold_labels as igl  # noqa: E402

BODY = "합성 전사 문장이며 실제 코퍼스에서 오지 않았습니다"


def vchunk(chunk_id, video_id, index, start_ms, end_ms, *, eligible=True, reason=None):
    return {
        "chunk_id": chunk_id, "video_id": video_id, "chunk_index": index,
        "start_ms": start_ms, "end_ms": end_ms, "text": BODY,
        "embedding_eligible": eligible, "exclusion_reason": reason,
    }


class PromoteVideoChunks(unittest.TestCase):
    def test_a_chunk_becomes_a_span_with_its_own_boundaries(self):
        by_id = {"v1": vchunk("v1", "VID", 3, 1000, 5000)}
        video_id, spans, problems = igl.promote_video_chunks("q1", ["v1"], by_id)
        self.assertEqual(problems, [])
        self.assertEqual(video_id, "VID")
        self.assertEqual(len(spans), 1)
        self.assertEqual((spans[0]["start_ms"], spans[0]["end_ms"]), (1000, 5000))
        self.assertEqual(spans[0]["span_id"], "q1-s1")

    def test_an_embedding_ineligible_chunk_is_refused(self):
        by_id = {"v1": vchunk("v1", "VID", 3, 1000, 5000, eligible=False, reason="자동자막")}
        _video_id, spans, problems = igl.promote_video_chunks("q1", ["v1"], by_id)
        self.assertEqual(spans, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("embedding_eligible", problems[0])
        self.assertIn("자동자막", problems[0])

    def test_an_unknown_chunk_id_is_reported_not_dropped(self):
        _video_id, spans, problems = igl.promote_video_chunks("q1", ["ghost"], {})
        self.assertEqual(spans, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("찾지 못했다", problems[0])

    def test_chunks_from_two_videos_are_refused(self):
        """행 단위 video_id가 스칼라라 조용히 하나만 고르면 정답이 사라진다."""
        by_id = {"a": vchunk("a", "VID1", 0, 0, 1000), "b": vchunk("b", "VID2", 0, 0, 1000)}
        video_id, spans, problems = igl.promote_video_chunks("q1", ["a", "b"], by_id)
        self.assertIsNone(video_id)
        self.assertEqual(spans, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("영상 2개", problems[0])

    def test_two_chunks_from_one_video_become_two_spans(self):
        by_id = {"a": vchunk("a", "VID", 0, 0, 1000), "b": vchunk("b", "VID", 5, 9000, 9999)}
        video_id, spans, problems = igl.promote_video_chunks("q1", ["a", "b"], by_id)
        self.assertEqual(problems, [])
        self.assertEqual(video_id, "VID")
        self.assertEqual([s["span_id"] for s in spans], ["q1-s1", "q1-s2"])


class RevalidateSpan(unittest.TestCase):
    def test_a_span_matching_exactly_one_chunk_passes(self):
        corpus = [vchunk("a", "VID", 0, 0, 1000), vchunk("b", "VID", 1, 1000, 2000)]
        span = {"span_id": "q1-s1", "start_ms": 0, "end_ms": 1000}
        self.assertIsNone(igl.revalidate_span("VID", span, corpus))

    def test_a_span_straddling_two_chunks_fails(self):
        """재청킹으로 경계가 움직이면 정답 집합이 조용히 커진다."""
        corpus = [vchunk("a", "VID", 0, 0, 1000), vchunk("b", "VID", 1, 900, 2000)]
        span = {"span_id": "q1-s1", "start_ms": 500, "end_ms": 1500}
        issue = igl.revalidate_span("VID", span, corpus)
        self.assertIsNotNone(issue)
        self.assertIn("2개에 걸친다", issue)

    def test_a_span_matching_nothing_fails(self):
        corpus = [vchunk("a", "VID", 0, 0, 1000)]
        span = {"span_id": "q1-s1", "start_ms": 50_000, "end_ms": 60_000}
        issue = igl.revalidate_span("VID", span, corpus)
        self.assertIsNotNone(issue)
        self.assertIn("겹치는 영상 청크가 없다", issue)

    def test_ineligible_chunks_do_not_satisfy_a_span(self):
        corpus = [vchunk("a", "VID", 0, 0, 1000, eligible=False)]
        self.assertIsNotNone(igl.revalidate_span("VID", {"span_id": "s", "start_ms": 0, "end_ms": 1000}, corpus))

    def test_another_videos_chunk_does_not_satisfy_a_span(self):
        corpus = [vchunk("a", "OTHER", 0, 0, 1000)]
        self.assertIsNotNone(igl.revalidate_span("VID", {"span_id": "s", "start_ms": 0, "end_ms": 1000}, corpus))

    def test_touching_boundaries_do_not_count_as_overlap(self):
        """끝이 맞닿는 것은 겹침이 아니다 — 그렇지 않으면 이웃 청크가 전부 gold가 된다."""
        corpus = [vchunk("a", "VID", 0, 0, 1000), vchunk("b", "VID", 1, 1000, 2000)]
        span = {"span_id": "s", "start_ms": 1000, "end_ms": 2000}
        self.assertIsNone(igl.revalidate_span("VID", span, corpus))


if __name__ == "__main__":
    unittest.main()
