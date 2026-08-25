import importlib.util
import json
import sys
import tempfile
import unittest

from pathlib import Path


REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "medical_guardrail.py"
SPEC = importlib.util.spec_from_file_location("medical_guardrail", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


BUILD_SCRIPT = REPO / "scripts" / "build_medical_lexicon.py"
BUILD_SPEC = importlib.util.spec_from_file_location("build_medical_lexicon", BUILD_SCRIPT)
build_module = importlib.util.module_from_spec(BUILD_SPEC)
assert BUILD_SPEC.loader
sys.modules[BUILD_SPEC.name] = build_module
BUILD_SPEC.loader.exec_module(build_module)


TERMS = ("슬개골 탈구", "관절 통증", "통증", "외이도염", "짖음", "분리불안")


class ClassifyInputTests(unittest.TestCase):
    def test_symptom_term_triggers_medical(self):
        verdict = module.classify_input(
            "우리 강아지가 슬개골 탈구 진단을 받았는데 어떻게 관리해야 하나요?", TERMS
        )
        self.assertTrue(verdict.is_medical)
        self.assertIn("슬개골 탈구", verdict.matched_terms)
        self.assertEqual(module.VET_REFERRAL_MESSAGE, verdict.response)

    def test_plain_training_question_passes(self):
        verdict = module.classify_input(
            "손 내밀면 발 올려놓는 개인기 훈련 가르치는 팁 알려주세요.", TERMS
        )
        self.assertFalse(verdict.is_medical)
        self.assertEqual((), verdict.matched_terms)
        self.assertIsNone(verdict.response)

    def test_broad_term_still_matches_a_training_sounding_question(self):
        """짖음 is real extracted vocabulary and also ordinary training vocabulary.

        This is not a bug to special-case away here — it is the false-positive
        cost scripts/evaluate_medical_guardrail.py exists to measure. This test
        only pins the current (documented, not adjusted) behavior.
        """
        verdict = module.classify_input(
            "짖음 교정 훈련은 어떻게 하나요?", TERMS
        )
        self.assertTrue(verdict.is_medical)

    def test_no_terms_no_match(self):
        verdict = module.classify_input("아무 상관 없는 질문입니다.", ())
        self.assertFalse(verdict.is_medical)


V2_TERMS = ("백신", "접종", "중성화", "연고", "처방", "처방식", "약", "발작")
WHITELIST_TERMS = ("짖음", "분리불안", "불안", "하울링", "배변", "산책", "사회화")


class ClassifyInputV2Tests(unittest.TestCase):
    def test_v2_term_triggers_medical(self):
        verdict = module.classify_input_v2(
            "추천할 만한 약용 샴푸나 처방식 사료, 연고 이름을 알려주세요.",
            V2_TERMS, WHITELIST_TERMS,
        )
        self.assertTrue(verdict.is_medical)
        self.assertIn("연고", verdict.matched_terms)

    def test_whitelist_overrides_a_v2_dictionary_match(self):
        """짖음 is whitelisted; it must win even though '약' also matches v2."""
        verdict = module.classify_input_v2(
            "짖음 교정 훈련에 유산균 약을 같이 먹여도 되나요?",
            V2_TERMS, WHITELIST_TERMS,
        )
        self.assertFalse(verdict.is_medical)
        self.assertIn("짖음", verdict.whitelist_matched)

    def test_plain_training_question_passes_without_whitelist_hit(self):
        verdict = module.classify_input_v2(
            "손 내밀면 발 올려놓는 개인기 훈련 팁 알려주세요.", V2_TERMS, WHITELIST_TERMS
        )
        self.assertFalse(verdict.is_medical)
        self.assertEqual((), verdict.whitelist_matched)

    def test_known_tradeoff_mixed_sentence_passes_via_whitelist(self):
        """Documented trade-off: a whitelist hit passes even next to a real marker."""
        verdict = module.classify_input_v2(
            "산책 중에 갑자기 발작을 일으켜요.", V2_TERMS, WHITELIST_TERMS
        )
        self.assertFalse(verdict.is_medical)
        self.assertIn("산책", verdict.whitelist_matched)


class ClassifyOutputTests(unittest.TestCase):
    def test_disease_term_alone_is_not_blocked_but_gets_a_disclaimer(self):
        answer = "슬개골 탈구 진단을 받은 강아지는 걷다가 갑자기 다리를 드는 행동을 보일 수 있습니다 [1]."
        verdict = module.classify_output(answer, TERMS)
        self.assertFalse(verdict.is_blocked)
        self.assertIn("슬개골 탈구", verdict.matched_disease_terms)
        self.assertTrue(verdict.text.startswith(answer))
        self.assertIn(module.OUTPUT_DISCLAIMER.strip(), verdict.text)

    def test_disease_term_with_prescriptive_marker_is_blocked(self):
        answer = "외이도염에는 항생제 성분 연고를 하루 두 번 발라주세요."
        verdict = module.classify_output(answer, TERMS)
        self.assertTrue(verdict.is_blocked)
        self.assertIn("외이도염", verdict.matched_disease_terms)
        self.assertTrue(verdict.matched_prescriptive_markers)
        self.assertEqual(module.OUTPUT_BLOCKED_MESSAGE, verdict.text)

    def test_prescriptive_marker_without_disease_term_is_not_blocked(self):
        """The marker alone (no symptom/disease vocabulary) is not enough.

        Not measured against real data (see medical_guardrail.classify_output's
        docstring) — this pins the documented co-occurrence rule.
        """
        answer = "정기적으로 처방받은 사료를 급여해 주세요."
        verdict = module.classify_output(answer, TERMS)
        self.assertFalse(verdict.is_blocked)
        self.assertEqual(answer, verdict.text)

    def test_plain_training_answer_passes_untouched(self):
        answer = "앉기 훈련은 간식을 코 앞에 두고 위로 올리며 유도합니다 [1]."
        verdict = module.classify_output(answer, TERMS)
        self.assertFalse(verdict.is_blocked)
        self.assertEqual(answer, verdict.text)


class ClassifyOutputV2Tests(unittest.TestCase):
    def test_training_vocabulary_no_longer_triggers_a_disclaimer(self):
        """The bug classify_output_v2 exists to fix: v1 flagged this on 2026-08-20."""
        answer = (
            "현관에 소변을 보거나 장난감을 거실로 끄집어 놓는 것은, 그 냄새를 맡고 집에 "
            "잘 돌아오라는 뜻의 분리불안 행동 유형이라고 설명합니다. [1]"
        )
        verdict = module.classify_output_v2(answer, V2_TERMS, WHITELIST_TERMS)
        self.assertFalse(verdict.is_blocked)
        self.assertEqual(answer, verdict.text)
        self.assertIn("분리불안", verdict.whitelist_matched)

    def test_v2_disease_term_alone_still_gets_a_disclaimer(self):
        answer = "발작 증상이 있다면 자료 [1]에 따라 자극을 줄여주는 것이 좋습니다."
        verdict = module.classify_output_v2(answer, V2_TERMS, WHITELIST_TERMS)
        self.assertFalse(verdict.is_blocked)
        self.assertEqual((), verdict.whitelist_matched)
        self.assertIn("발작", verdict.matched_disease_terms)
        self.assertIn(module.OUTPUT_DISCLAIMER.strip(), verdict.text)

    def test_v2_disease_plus_prescriptive_marker_is_still_blocked(self):
        answer = "발작이 있으면 처방받은 약을 먹여 진정시켜 주세요."
        verdict = module.classify_output_v2(answer, V2_TERMS, WHITELIST_TERMS)
        self.assertTrue(verdict.is_blocked)
        self.assertEqual(module.OUTPUT_BLOCKED_MESSAGE, verdict.text)

    def test_prescriptive_marker_revokes_the_whitelist(self):
        """2026-08-25: the whitelist no longer wins when a marker is present.

        This test previously pinned the opposite — a whitelist hit passed the text
        through even alongside 처방/투약-class markers, mirroring
        classify_input_v2's documented trade-off. Q&A sources broke that: an
        owner's question and a trainer's answer reach the model together, and a
        training term from the answer was neutralising drug vocabulary from the
        question. Measured on synthetic Q&A pairs, 3 of 5 cases that should have
        been blocked passed. Training advice has no reason to say 처방/투약/mg,
        so the marker revokes the exemption.

        The trade-off is not gone, only narrowed: a whitelist hit still wins when
        no marker is present (test_whitelist_still_wins_without_a_marker below).
        """
        answer = "산책 중이라면 처방받은 약을 미리 먹여도 괜찮습니다."
        verdict = module.classify_output_v2(answer, V2_TERMS, WHITELIST_TERMS)
        self.assertTrue(verdict.is_blocked)
        self.assertEqual(module.OUTPUT_BLOCKED_MESSAGE, verdict.text)
        # 무엇이 무효화됐는지 판정에 남는다 — 과차단 관찰용.
        self.assertIn("산책", verdict.whitelist_matched)
        self.assertIn("처방", verdict.matched_prescriptive_markers)

    def test_whitelist_still_wins_without_a_marker(self):
        """마커가 없으면 기존 트레이드오프가 그대로다 — 좁혔을 뿐 없애지 않았다."""
        answer = "분리불안이 있으면 병원에 가보는 것도 방법입니다."
        verdict = module.classify_output_v2(answer, V2_TERMS, WHITELIST_TERMS)
        self.assertFalse(verdict.is_blocked)
        self.assertEqual(answer, verdict.text)
        self.assertIn("분리불안", verdict.whitelist_matched)

    def test_revoked_whitelist_is_recorded_for_over_blocking_review(self):
        """규칙 변경으로 판정이 뒤집힌 자리를 관찰할 창구가 있어야 한다."""
        before = len(module.WHITELIST_REVOKED_LOG)
        module.classify_output_v2(
            "산책 중이라면 처방받은 약을 미리 먹여도 괜찮습니다.", V2_TERMS, WHITELIST_TERMS
        )
        self.assertEqual(len(module.WHITELIST_REVOKED_LOG), before + 1)
        entry = module.WHITELIST_REVOKED_LOG[-1]
        self.assertIn("산책", entry["whitelist_matched"])
        # 상담 원문이 로그로 새면 안 된다 — 어떤 용어가 부딪혔는지만 남긴다.
        self.assertEqual(set(entry), {
            "whitelist_matched", "matched_disease_terms", "matched_prescriptive_markers"
        })

    def test_plain_training_answer_passes_untouched(self):
        answer = "앉기 훈련은 간식을 코 앞에 두고 위로 올리며 유도합니다 [1]."
        verdict = module.classify_output_v2(answer, V2_TERMS, WHITELIST_TERMS)
        self.assertFalse(verdict.is_blocked)
        self.assertEqual(answer, verdict.text)
        self.assertEqual((), verdict.whitelist_matched)


class ApplyOutputGuardrailTests(unittest.TestCase):
    """The self-block incident and its fix: a value-level exemption, not a branch.

    2026-08-20: scripts/generate_answers.py's MEDICAL_REFUSAL_TEMPLATE ("...가까운
    동물병원에서 수의사의 진료를 받으시길 권합니다...") contains "병원" (V2_TERMS)
    and "처방" is a marker in PRESCRIPTIVE_MARKERS — a hand-written safe template
    tripping the exact check it exists to route around.
    """

    SAFE_TEMPLATE_TEXT = (
        "걱정이 많으시겠어요. 이 질문은 반려견의 건강 상태에 대한 의학적 판단이 "
        "필요해 보입니다. 저는 훈련 정보를 안내하는 어시스턴트이고 진단이나 처방을 "
        "할 수 없습니다. 가까운 동물병원에서 수의사의 진료를 받으시길 권합니다."
    )

    def test_the_incident_reproduced_unwrapped_text_would_have_been_blocked(self):
        """Proof the incident was real, not hypothetical: run the actual template
        text through classify_output_v2, against the real shipped lexicons, as a
        plain str — the way it would have reached the guardrail before
        SystemAuthoredText existed."""
        real_terms = module.load_medical_terms_v2()
        real_whitelist = module.load_training_whitelist()
        verdict = module.classify_output_v2(self.SAFE_TEMPLATE_TEXT, real_terms, real_whitelist)
        self.assertTrue(verdict.is_blocked)
        self.assertIn("병원", verdict.matched_disease_terms)
        self.assertIn("처방", verdict.matched_prescriptive_markers)

    def test_a_system_authored_text_passes_through_untouched(self):
        wrapped = module.SystemAuthoredText(self.SAFE_TEMPLATE_TEXT)
        verdict = module.apply_output_guardrail(wrapped, V2_TERMS, WHITELIST_TERMS)
        self.assertFalse(verdict.is_blocked)
        self.assertEqual(self.SAFE_TEMPLATE_TEXT, verdict.text)
        self.assertTrue(verdict.system_authored)
        self.assertEqual((), verdict.matched_disease_terms)
        self.assertEqual((), verdict.matched_prescriptive_markers)

    def test_a_plain_str_is_never_exempt_even_with_identical_text(self):
        """The exemption is on the wrapper, not the content — the same string,
        unwrapped, is checked for real and gets blocked exactly like the
        reproduction above. This is what protects against a future edit that
        starts routing model output through the same call site."""
        verdict = module.apply_output_guardrail(self.SAFE_TEMPLATE_TEXT, V2_TERMS, WHITELIST_TERMS)
        self.assertTrue(verdict.is_blocked)
        self.assertFalse(verdict.system_authored)

    def test_ordinary_generated_text_is_checked_normally_through_the_same_entry_point(self):
        verdict = module.apply_output_guardrail(
            "발작이 있으면 처방받은 약을 먹여 진정시켜 주세요.", V2_TERMS, WHITELIST_TERMS
        )
        self.assertTrue(verdict.is_blocked)
        self.assertFalse(verdict.system_authored)


class LoadMedicalTermsTests(unittest.TestCase):
    def test_missing_file_raises_guardrail_error(self):
        with self.assertRaises(module.GuardrailError):
            module.load_medical_terms(Path("does/not/exist.json"))

    def test_terms_sorted_longest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "medical_terms_v1.json"
            path.write_text(
                json.dumps({"terms": ["통증", "슬개골 탈구", "짖음"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            terms = module.load_medical_terms(path)
            self.assertEqual(terms[0], "슬개골 탈구")

    def test_short_terms_below_min_chars_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "medical_terms_v1.json"
            path.write_text(
                json.dumps({"terms": ["통", "통증"]}, ensure_ascii=False), encoding="utf-8"
            )
            terms = module.load_medical_terms(path)
            self.assertNotIn("통", terms)
            self.assertIn("통증", terms)


class LoadMedicalTermsV2AndWhitelistTests(unittest.TestCase):
    def test_load_medical_terms_v2_reads_the_hand_authored_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "medical_terms_v2.json"
            path.write_text(
                json.dumps({"terms": ["처방식", "약"]}, ensure_ascii=False), encoding="utf-8"
            )
            terms = module.load_medical_terms_v2(path)
            self.assertIn("처방식", terms)

    def test_load_training_whitelist_reads_the_hand_authored_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "training_whitelist_v1.json"
            path.write_text(
                json.dumps({"terms": ["짖음", "분리불안"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            terms = module.load_training_whitelist(path)
            self.assertIn("짖음", terms)

    def test_missing_v2_file_raises_guardrail_error(self):
        with self.assertRaises(module.GuardrailError):
            module.load_medical_terms_v2(Path("does/not/exist.json"))

    def test_missing_whitelist_file_raises_guardrail_error(self):
        with self.assertRaises(module.GuardrailError):
            module.load_training_whitelist(Path("does/not/exist.json"))


class BuildMedicalLexiconTests(unittest.TestCase):
    def test_only_disease_and_symptom_types_are_collected(self):
        rows = [
            {
                "entities": [
                    {"name": "슬개골 탈구", "type": "질환"},
                    {"name": "통증", "type": "증상"},
                    {"name": "앉기", "type": "훈련법"},
                    {"name": "짖음", "type": "문제행동"},
                ]
            }
        ]
        by_type = build_module.collect_terms(rows)
        self.assertEqual({"슬개골 탈구"}, set(by_type["질환"]))
        self.assertEqual({"통증"}, set(by_type["증상"]))

    def test_duplicate_entity_names_are_deduplicated(self):
        rows = [
            {"entities": [{"name": "통증", "type": "증상"}]},
            {"entities": [{"name": "통증", "type": "증상"}]},
        ]
        by_type = build_module.collect_terms(rows)
        self.assertEqual(["통증"], by_type["증상"])

    def test_build_lexicon_flat_terms_is_union_across_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "stage2.jsonl"
            source.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in [
                        {"entities": [{"name": "불안장애", "type": "질환"}]},
                        {"entities": [{"name": "불안장애", "type": "증상"}]},
                        {"entities": [{"name": "짖음", "type": "문제행동"}]},
                    ]
                ),
                encoding="utf-8",
            )
            lexicon = build_module.build_lexicon(source, "2026-08-20T00:00:00+09:00")
            self.assertEqual(["불안장애"], lexicon["terms"])
            self.assertEqual(1, lexicon["term_count"])
            self.assertEqual(source.as_posix(), lexicon["source"])

    def test_missing_source_raises_lexicon_error(self):
        with self.assertRaises(build_module.LexiconError):
            build_module.build_lexicon(Path("does/not/exist.jsonl"), "2026-08-20T00:00:00+09:00")


if __name__ == "__main__":
    unittest.main()
