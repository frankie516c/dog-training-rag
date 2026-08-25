"""split_wayopet_qa.py 픽스처 테스트.

## 이름을 넣지 않는 이유

이 저장소는 public이다. 실제 게시글의 훈련사 실명·반려견 호칭·원문 문장을
테스트에 리터럴로 박으면 그것이 그대로 공개된다. 그래서 픽스처는 **패턴과
수치로만** 고정한다 — 문서 slug, 경계 개수, 판정, 세그먼트 길이 범위,
제거 span 개수. 실제 텍스트는 단언하지 않는다.

합성 입력으로 검증하는 항목은 실제 이름 대신 자리표시자를 쓴다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.split_wayopet_qa import (  # noqa: E402
    ANSWER_AUTHOR_DISPLAY,
    QUESTION_AUTHOR_DISPLAY,
    R1_BOUNDARY,
    parse_document,
    strip_boilerplate,
    to_segments,
)

RAW_DIR = Path(__file__).resolve().parents[1] / "data/raw/documents_candidate_0825_wayopet"

# 조달된 6건의 고정 기대값. 텍스트가 아니라 구조만 고정한다.
# boundary_count는 fail-closed 조건(정확히 1개)의 회귀 감시용.
EXPECTED = {
    "wayopet-fear-barking-candidate": {"boundary": 1, "status": "OK", "removed": 0},
    "wayopet-kennel-fear-candidate": {"boundary": 1, "status": "OK", "removed": 1},
    "wayopet-night-lunging-candidate": {"boundary": 1, "status": "OK", "removed": 1},
    "wayopet-noise-barking-candidate": {"boundary": 1, "status": "OK", "removed": 1},
    "wayopet-walk-lunging-candidate": {"boundary": 1, "status": "OK", "removed": 1},
    "wayopet-walk-training-candidate": {"boundary": 1, "status": "OK", "removed": 1},
}


def _docs():
    if not RAW_DIR.is_dir():
        pytest.skip("수집물이 없는 환경 — data/ 는 커밋되지 않는다")
    return sorted(RAW_DIR.glob("*.md"))


def test_all_six_parse_cleanly():
    """6건 모두 경계가 정확히 1개이고 자동 처리된다."""
    paths = _docs()
    assert len(paths) == len(EXPECTED)
    for path in paths:
        record = parse_document(path, ordinal=0)
        want = EXPECTED[path.stem]
        assert record["boundary_count"] == want["boundary"], path.stem
        assert record["parse_status"] == want["status"], path.stem


def test_removed_span_counts_are_stable():
    """제거된 boilerplate 구간 수가 바뀌면 패턴이 흘렀거나 과하게 먹은 것이다."""
    for path in _docs():
        record = parse_document(path, ordinal=0)
        if record["parse_status"] != "OK":
            continue
        assert len(record["removed_boilerplate_spans"]) == EXPECTED[path.stem]["removed"], path.stem


def test_answer_carries_no_boundary_marker_or_question_headers():
    """분리 후 답변부에 경계 마커나 질문 폼 헤더가 남으면 안 된다."""
    for path in _docs():
        record = parse_document(path, ordinal=0)
        if record["parse_status"] != "OK":
            continue
        assert not R1_BOUNDARY.search(record["answer_text"]), path.stem
        for header in ("증상과 행동", "시작된 시점", "보호자님 반응"):
            assert header not in record["answer_text"], f"{path.stem}: {header}"


def test_display_names_carry_no_individual_identifier():
    """표시명은 플랫폼+역할 고정. 마스킹명조차 표시 경로에 나오면 안 된다."""
    for path in _docs():
        record = parse_document(path, ordinal=0)
        if record["parse_status"] != "OK":
            continue
        for segment in to_segments(record):
            assert segment["author_display"] in (
                QUESTION_AUTHOR_DISPLAY,
                ANSWER_AUTHOR_DISPLAY,
            )
            assert "*" not in segment["author_display"]


def test_qa_id_is_position_based_not_text_derived():
    """같은 텍스트가 여러 Q&A에 나와도 qa_id가 충돌하면 안 된다.

    텍스트 해시로 만들면 충돌이 조용히 일어난다 — 그래서 위치 기반이다.
    """
    ids = set()
    for path in _docs():
        record = parse_document(path, ordinal=0)
        assert record["qa_id"] not in ids
        ids.add(record["qa_id"])
        assert record["source_url"] in record["qa_id"]


def test_segments_are_role_split_and_linked_by_qa_id():
    for path in _docs():
        record = parse_document(path, ordinal=0)
        if record["parse_status"] != "OK":
            continue
        segments = to_segments(record)
        assert [s["segment_role"] for s in segments] == ["OWNER_QUESTION", "EXPERT_ANSWER"]
        assert len({s["qa_id"] for s in segments}) == 1


def test_segments_carry_no_authority_fields_yet():
    """권위 필드는 소비하는 코드와 같은 라운드에서 붙인다.

    지금 붙이면 계약이 구현된 것처럼 보이지만 코어가 읽지 않아 작동하지 않는다.
    """
    for path in _docs():
        record = parse_document(path, ordinal=0)
        if record["parse_status"] != "OK":
            continue
        for segment in to_segments(record):
            for field in ("authority", "citation_allowed", "retrieval_allowed"):
                assert field not in segment


# --- 합성 입력: 실제 게시글 텍스트를 쓰지 않는다 ---

def test_overlapping_boilerplate_spans_do_not_eat_content():
    """겹치는 제거 패턴이 실제 내용을 지우면 안 된다.

    두 패턴이 같은 문장을 잡을 때 병합 없이 각각 잘라내면, 두 번째 삭제가 이미
    짧아진 문자열에 적용돼 본문을 파먹는다. 조용히 깨지는 종류라 고정해 둔다.
    """
    keep = "여기부터가 실제 답변 내용입니다."
    text = f"안녕하세요. 자리표시자 보호자님 홍길동 훈련사입니다.🙂 {keep}"
    out, removed = strip_boilerplate(text, base_offset=0)
    assert keep in out
    assert len(removed) == 1  # 겹친 두 패턴이 하나로 병합된다
    assert "훈련사입니다" not in out


def test_boundary_absent_or_duplicated_is_fail_closed(tmp_path):
    """경계가 1개가 아니면 자동 처리하지 않는다(0개·2개 모두)."""
    marker = "김*이 훈련사님의 답변"
    for count in (0, 2):
        doc = tmp_path / f"case{count}.md"
        doc.write_text(
            "---\nsource_url: https://example.invalid/qna/x\n---\n"
            "질문 본문\n" + (marker + "\n답변 본문\n") * count,
            encoding="utf-8",
        )
        record = parse_document(doc, ordinal=0)
        assert record["parse_status"] == "PARSE_REVIEW"
        assert record["boundary_count"] == count
        assert to_segments(record) == []
