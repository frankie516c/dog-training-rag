"""split_wayopet_qa.py 픽스처 테스트.

## 이름을 넣지 않는 이유

이 저장소는 public이다. 실제 게시글의 훈련사 실명·반려동물 호칭·원문 문장을
테스트에 리터럴로 박으면 그것이 그대로 공개된다. 그래서 픽스처는 **패턴과
수치로만** 고정한다 — 문서 slug, 경계 개수, 판정, 제거 span 개수. 실제 텍스트는
단언하지 않는다. 합성 입력으로 검증하는 항목은 자리표시자를 쓴다.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from split_wayopet_qa import (  # noqa: E402
    ANSWER_AUTHOR_DISPLAY,
    QUESTION_AUTHOR_DISPLAY,
    R1_BOUNDARY,
    parse_document,
    strip_boilerplate,
    to_segments,
)

RAW_DIR = Path(__file__).resolve().parents[1] / "data/raw/documents_candidate_0825_wayopet"

# 조달된 6건의 고정 기대값. 텍스트가 아니라 구조만 고정한다.
EXPECTED = {
    "wayopet-fear-barking-candidate": {"boundary": 1, "status": "OK", "removed": 0},
    "wayopet-kennel-fear-candidate": {"boundary": 1, "status": "OK", "removed": 1},
    "wayopet-night-lunging-candidate": {"boundary": 1, "status": "OK", "removed": 1},
    "wayopet-noise-barking-candidate": {"boundary": 1, "status": "OK", "removed": 1},
    "wayopet-walk-lunging-candidate": {"boundary": 1, "status": "OK", "removed": 1},
    "wayopet-walk-training-candidate": {"boundary": 1, "status": "OK", "removed": 1},
}


class WayopetFixtureTests(unittest.TestCase):
    """조달된 6건에 대한 회귀 고정. data/ 는 커밋되지 않으므로 없으면 건너뛴다."""

    def setUp(self) -> None:
        if not RAW_DIR.is_dir():
            self.skipTest("수집물이 없는 환경 — data/ 는 커밋되지 않는다")
        self.paths = sorted(RAW_DIR.glob("*.md"))
        if not self.paths:
            self.skipTest("수집물 없음")

    def test_all_six_parse_cleanly(self):
        self.assertEqual(len(self.paths), len(EXPECTED))
        for path in self.paths:
            record = parse_document(path, ordinal=0)
            want = EXPECTED[path.stem]
            self.assertEqual(record["boundary_count"], want["boundary"], path.stem)
            self.assertEqual(record["parse_status"], want["status"], path.stem)

    def test_removed_span_counts_are_stable(self):
        """제거 구간 수가 바뀌면 패턴이 흘렀거나 과하게 먹은 것이다."""
        for path in self.paths:
            record = parse_document(path, ordinal=0)
            if record["parse_status"] != "OK":
                continue
            self.assertEqual(
                len(record["removed_boilerplate_spans"]), EXPECTED[path.stem]["removed"], path.stem
            )

    def test_answer_carries_no_boundary_marker_or_question_headers(self):
        for path in self.paths:
            record = parse_document(path, ordinal=0)
            if record["parse_status"] != "OK":
                continue
            self.assertIsNone(R1_BOUNDARY.search(record["answer_text"]), path.stem)
            for header in ("증상과 행동", "시작된 시점", "보호자님 반응"):
                self.assertNotIn(header, record["answer_text"], f"{path.stem}: {header}")

    def test_display_names_carry_no_individual_identifier(self):
        """표시명은 플랫폼+역할 고정. 마스킹명조차 표시 경로에 나오면 안 된다."""
        for path in self.paths:
            record = parse_document(path, ordinal=0)
            if record["parse_status"] != "OK":
                continue
            for segment in to_segments(record):
                self.assertIn(
                    segment["author_display"],
                    (QUESTION_AUTHOR_DISPLAY, ANSWER_AUTHOR_DISPLAY),
                )
                self.assertNotIn("*", segment["author_display"])

    def test_qa_id_is_position_based_not_text_derived(self):
        """텍스트 해시로 만들면 동일 텍스트 중복 시 조용히 충돌한다."""
        seen = set()
        for path in self.paths:
            record = parse_document(path, ordinal=0)
            self.assertNotIn(record["qa_id"], seen)
            seen.add(record["qa_id"])
            self.assertIn(record["source_url"], record["qa_id"])

    def test_segments_are_role_split_and_linked_by_qa_id(self):
        for path in self.paths:
            record = parse_document(path, ordinal=0)
            if record["parse_status"] != "OK":
                continue
            segments = to_segments(record)
            self.assertEqual(
                [s["segment_role"] for s in segments], ["OWNER_QUESTION", "EXPERT_ANSWER"]
            )
            self.assertEqual(len({s["qa_id"] for s in segments}), 1)

    def test_segments_carry_no_authority_fields_yet(self):
        """권위 필드는 청크 레코드가 갖는다. 분리 산출물은 역할만 싣는다."""
        for path in self.paths:
            record = parse_document(path, ordinal=0)
            if record["parse_status"] != "OK":
                continue
            for segment in to_segments(record):
                for field in ("authority", "citation_allowed", "retrieval_allowed"):
                    self.assertNotIn(field, segment)


class BoilerplateAndFailClosedTests(unittest.TestCase):
    """합성 입력만 쓴다 — 실제 게시글 텍스트를 넣지 않는다."""

    def test_overlapping_boilerplate_spans_do_not_eat_content(self):
        """겹치는 제거 패턴이 실제 내용을 지우면 안 된다.

        두 패턴이 같은 문장을 잡을 때 병합 없이 각각 잘라내면, 두 번째 삭제가
        이미 짧아진 문자열에 적용돼 본문을 파먹는다. 조용히 깨지는 종류다.
        """
        keep = "여기부터가 실제 답변 내용입니다."
        text = f"안녕하세요. 자리표시자 보호자님 홍길동 훈련사입니다.🙂 {keep}"
        out, removed = strip_boilerplate(text, base_offset=0)
        self.assertIn(keep, out)
        self.assertEqual(len(removed), 1)  # 겹친 두 패턴이 하나로 병합된다
        self.assertNotIn("훈련사입니다", out)

    def test_boundary_absent_or_duplicated_is_fail_closed(self):
        """경계가 1개가 아니면 자동 처리하지 않는다(0개·2개 모두)."""
        marker = "김*이 훈련사님의 답변"
        with tempfile.TemporaryDirectory() as tmp:
            for count in (0, 2):
                doc = Path(tmp) / f"case{count}.md"
                doc.write_text(
                    "---\nsource_url: https://example.invalid/qna/x\n---\n"
                    "질문 본문\n" + (marker + "\n답변 본문\n") * count,
                    encoding="utf-8",
                )
                record = parse_document(doc, ordinal=0)
                self.assertEqual(record["parse_status"], "PARSE_REVIEW")
                self.assertEqual(record["boundary_count"], count)
                self.assertEqual(to_segments(record), [])


if __name__ == "__main__":
    unittest.main()
