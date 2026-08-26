"""앵커 재검증의 불변식은 I1이다 — `(doc_id, quote)`가 청크 집합을 결정한다.

전에는 import이 인용문을 **코퍼스 전역**에서 찾아 매칭 문서가 둘 이상이면
거부했다. 평가(`run_combined_retrieval_eval.gold_relevant_chunks()`)는 그때도
`doc_id`로 먼저 좁혔으므로, 두 경로가 서로 다른 질문에 답하고 있었다. 그 결과
**평가에는 아무 문제가 없는데 기록만 거부되는** 비대칭이 생겼고, 코퍼스를 키울
때마다 그 거부가 늘어난다.

여기서 고정하는 것은 두 가지다.

1. 다른 문서에 같은 문장이 있어도 거부하지 않는다 (I1).
2. 청크 id는 그 자체로 근거가 아니다. 문서 청크는 인용문 앵커로, 영상 청크는
   `relevant_spans`로 승격돼야 평가가 읽을 수 있다.

픽스처는 전부 합성이다 — 실제 코퍼스 본문을 쓰지 않는다(`docs/SOURCES.md` 규칙 4).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import import_gold_labels as igl  # noqa: E402

QUOTE = "합성 문장입니다. 이 문장은 테스트 픽스처로만 존재합니다"
OTHER = "또 다른 합성 문장이며 어느 코퍼스에도 없습니다"


def chunk(chunk_id, doc_id, text, *, citation_allowed=True):
    return {
        "chunk_id": chunk_id, "doc_id": doc_id, "text": text,
        "citation_allowed": citation_allowed,
    }


def video_chunk(chunk_id, video_id, start_ms, end_ms):
    return {
        "chunk_id": chunk_id, "video_id": video_id, "text": OTHER,
        "start_ms": start_ms, "end_ms": end_ms, "embedding_eligible": True,
    }


class RevalidateIsScopedToTheDocument(unittest.TestCase):
    def test_a_quote_repeated_in_another_document_is_not_an_error(self):
        """확장으로 같은 문장이 다른 문서에 생겨도 앵커는 살아 있다."""
        corpus = [
            chunk("c1", "doc-a", f"앞말 {QUOTE} 뒷말"),
            chunk("c2", "doc-b", f"다른 글인데 {QUOTE} 이렇게 겹친다"),
        ]
        self.assertIsNone(igl.revalidate_anchor(QUOTE, "doc-a", corpus))
        self.assertIsNone(igl.revalidate_anchor(QUOTE, "doc-b", corpus))

    def test_the_collision_is_still_reported_as_a_note(self):
        """거부하지는 않되, 정형구 신호는 사람에게 남긴다."""
        corpus = [
            chunk("c1", "doc-a", f"앞말 {QUOTE} 뒷말"),
            chunk("c2", "doc-b", f"다른 글인데 {QUOTE} 이렇게 겹친다"),
        ]
        self.assertEqual(igl.anchor_collisions(QUOTE, "doc-a", corpus), ["doc-b"])
        self.assertEqual(igl.anchor_collisions(OTHER, "doc-a", corpus), [])

    def test_a_quote_absent_from_its_own_document_fails(self):
        """doc_id 오기재는 여전히 잡힌다 — 전역 검사 없이도."""
        corpus = [chunk("c1", "doc-a", f"앞말 {QUOTE} 뒷말"), chunk("c2", "doc-b", OTHER)]
        issue = igl.revalidate_anchor(QUOTE, "doc-b", corpus)
        self.assertIsNotNone(issue)
        self.assertIn("doc-b", issue)

    def test_an_unknown_doc_id_fails(self):
        corpus = [chunk("c1", "doc-a", QUOTE)]
        issue = igl.revalidate_anchor(QUOTE, "doc-missing", corpus)
        self.assertIsNotNone(issue)
        self.assertIn("코퍼스에 없다", issue)

    def test_a_non_citable_chunk_does_not_satisfy_the_anchor(self):
        """견주 발화는 인용 불가라 gold 근거가 될 수 없다."""
        corpus = [chunk("c1", "doc-a", QUOTE, citation_allowed=False)]
        self.assertIsNotNone(igl.revalidate_anchor(QUOTE, "doc-a", corpus))

    def test_many_chunks_in_one_document_are_all_gold(self):
        """한 문서 안에서 여러 청크에 걸리는 것은 정상이다 — 평가가 합집합을 쓴다."""
        corpus = [chunk("c1", "doc-a", QUOTE), chunk("c2", "doc-a", f"{QUOTE} 또"),
                  chunk("c3", "doc-b", OTHER)]
        self.assertIsNone(igl.revalidate_anchor(QUOTE, "doc-a", corpus))


class ChunkIdsAreNotEvidenceUntilPromoted(unittest.TestCase):
    def test_a_video_chunk_is_recognised(self):
        by_id = {c["chunk_id"]: c for c in [video_chunk("v1", "VID", 0, 1000),
                                            chunk("c1", "doc-a", QUOTE)]}
        self.assertTrue(igl.is_video_chunk("v1", by_id))
        self.assertFalse(igl.is_video_chunk("c1", by_id))
        self.assertFalse(igl.is_video_chunk("nope", by_id))

    def test_a_document_chunk_without_start_ms_is_not_video(self):
        """문서 청크에는 video_id도 시간 경계도 없다."""
        by_id = {"c1": {"chunk_id": "c1", "doc_id": "doc-a", "text": QUOTE}}
        self.assertFalse(igl.is_video_chunk("c1", by_id))


if __name__ == "__main__":
    unittest.main()
