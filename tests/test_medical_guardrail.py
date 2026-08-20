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
