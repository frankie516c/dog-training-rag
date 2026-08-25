"""<사용자사례> 렌더링 분기 (Q&A authority 라운드 3단계).

## 이 파일이 고정하는 것

견주 발화가 **시스템 문구 권한을 얻지 못한다**는 것. `SystemAuthoredText`는
`apply_output_guardrail`이 검사를 건너뛰게 하는 출력 측 면제 장치이고,
`<사용자사례>`는 프롬프트 입력이라 그 함수를 거치지 않는다. 타입을 부여할
자리가 없을 뿐 아니라, 부여하면 위험 어휘가 가드레일을 우회한다 — 그 타입이
막으려던 것과 정반대다.

합성 입력만 쓴다. 실제 상담 원문은 public 저장소에 넣지 않는다.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_answers as ga  # noqa: E402
import medical_guardrail as mg  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def citable(text="전문가 답변 본문", doc_id="doc-a", index=0):
    return {
        "doc_id": doc_id, "chunk_index": index, "heading_path": ["제목"],
        "text": text, "citation_allowed": True, "segment_role": "EXPERT_ANSWER",
    }


def context_only(text="보호자가 쓴 상담 글", qa_id="QA1"):
    return {
        "doc_id": "doc-a", "chunk_index": 9, "heading_path": ["제목"],
        "text": text, "citation_allowed": False, "segment_role": "OWNER_QUESTION",
        "qa_id": qa_id, "author_display": "와요펫 견주",
    }


# 규칙 문구 자체가 "<사용자사례>는 ..." 라고 태그명을 언급하므로, 태그 문자열로
# 그냥 split 하면 규칙 문장에서 잘린다. 블록은 자기 줄에 단독으로 열리므로
# 줄바꿈을 포함한 구분자를 쓴다.
CTX_OPEN = "\n<사용자사례>\n"


def context_block(prompt: str) -> str:
    """<사용자사례> 블록 본문만 떼어낸다."""
    return prompt.split(CTX_OPEN, 1)[1].split("</사용자사례>", 1)[0]


class RenderingTests(unittest.TestCase):
    def test_context_only_chunk_gets_no_citation_number(self):
        prompt = ga.build_prompt("질문", [citable(), context_only()], band="answer")
        self.assertIn(CTX_OPEN, prompt)
        # [1] 같은 인용 번호가 이 블록 안에 있으면 안 된다.
        self.assertIsNone(re.search(r"\[\d+\]", context_block(prompt)))

    def test_citable_chunks_keep_contiguous_numbering(self):
        """맥락 자료가 섞여도 인용 번호는 1부터 끊김 없이 매겨져야 한다."""
        chunks = [citable(index=0), context_only(), citable(index=1)]
        prompt = ga.build_prompt("질문", chunks, band="answer")
        sources = prompt.split("<자료>", 1)[1].split("</자료>", 1)[0]
        self.assertIn("[1]", sources)
        self.assertIn("[2]", sources)
        self.assertNotIn("[3]", sources)

    def test_context_only_text_sits_outside_the_sources_block(self):
        """규칙 1이 '<자료>에 적혀 있는 내용만'이므로 블록 분리 자체가 방어다."""
        marker = "이것은보호자발화표식"
        prompt = ga.build_prompt("질문", [citable(), context_only(marker)], band="answer")
        sources = prompt.split("<자료>", 1)[1].split("</자료>", 1)[0]
        self.assertNotIn(marker, sources)
        self.assertIn(marker, context_block(prompt))

    def test_rule_appears_only_when_context_block_present(self):
        without = ga.build_prompt("질문", [citable()], band="answer")
        self.assertNotIn(CTX_OPEN, without)
        self.assertNotIn(ga.CONTEXT_ONLY_RULE, without)
        with_ctx = ga.build_prompt("질문", [citable(), context_only()], band="answer")
        self.assertIn(ga.CONTEXT_ONLY_RULE, with_ctx)

    def test_chunks_without_the_field_stay_citable(self):
        """기존 청크(권위 필드 없음)의 동작이 바뀌면 안 된다."""
        legacy = {"doc_id": "d", "chunk_index": 0, "heading_path": [], "text": "본문"}
        prompt = ga.build_prompt("질문", [legacy], band="answer")
        self.assertIn("[1]", prompt)
        self.assertNotIn(CTX_OPEN, prompt)


class SystemAuthoredTextBoundaryTests(unittest.TestCase):
    """견주 발화가 출력 검사 면제 권한을 얻지 못하게 고정한다."""

    def test_build_prompt_returns_plain_str(self):
        """프롬프트가 출력 면제 경로로 새지 않는다."""
        prompt = ga.build_prompt("질문", [citable(), context_only()], band="answer")
        self.assertIsInstance(prompt, str)
        self.assertNotIsInstance(prompt, mg.SystemAuthoredText)

    def test_owner_text_is_fully_checked_by_the_output_guardrail(self):
        """<사용자사례>에 들어갈 텍스트를 출력 가드레일에 넘기면 정상 검사된다.

        면제되지 않음을 증명한다 — 질병어와 처방 마커를 함께 담은 합성 견주
        발화는 차단되어야 한다.
        """
        terms = mg.load_medical_terms_v2()
        markers = mg.PRESCRIPTIVE_MARKERS
        text = f"우리 아이가 {terms[0]}인 것 같아서 제가 {markers[0]}했어요"
        verdict = mg.apply_output_guardrail(text, terms, whitelist_terms=[], markers=markers)
        self.assertFalse(verdict.system_authored)
        self.assertTrue(verdict.is_blocked, verdict)

        # 같은 문자열을 SystemAuthoredText로 감싸면 통과한다 — 이것이 견주
        # 발화에 이 타입을 주면 안 되는 이유다.
        wrapped = mg.apply_output_guardrail(
            mg.SystemAuthoredText(text), terms, whitelist_terms=[], markers=markers
        )
        self.assertTrue(wrapped.system_authored)
        self.assertFalse(wrapped.is_blocked)

    def test_system_authored_text_is_constructed_in_exactly_one_place(self):
        """생성처가 늘어나면 실패한다 — 나중에 누가 견주 발화를 감싸는 것을 막는다."""
        allowed = {"medical_guardrail.py"}  # 정의 자체
        found: dict[str, int] = {}
        for path in SCRIPTS.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            # 호출식만 센다(타입 주석·isinstance·docstring 언급은 제외)
            hits = len(re.findall(r"SystemAuthoredText\(", source))
            if path.name in allowed:
                continue
            if hits:
                found[path.name] = hits
        self.assertEqual(
            found, {"generate_answers.py": 1},
            f"SystemAuthoredText 생성처가 예상과 다르다: {found}",
        )


if __name__ == "__main__":
    unittest.main()
