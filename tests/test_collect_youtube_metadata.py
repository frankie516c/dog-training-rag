import csv
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_youtube_metadata.py"
SPEC = importlib.util.spec_from_file_location("collect_youtube_metadata", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


class FakeAPI:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, resource, **params):
        self.calls.append((resource, params))
        return self.responses.pop(0)


class CollectorTests(unittest.TestCase):
    def test_playlist_paging_and_early_stop(self):
        page1 = {
            "items": [{"contentDetails": {"videoId": str(i)}} for i in range(50)],
            "nextPageToken": "NEXT",
        }
        page2 = {
            "items": [{"contentDetails": {"videoId": str(i)}} for i in range(50, 100)],
            "nextPageToken": "UNUSED",
        }
        api = FakeAPI([page1, page2])
        ids = module.collect_video_ids(api, "uploads", 55)
        self.assertEqual(55, len(ids))
        self.assertEqual(50, api.calls[0][1]["maxResults"])
        self.assertEqual("NEXT", api.calls[1][1]["pageToken"])
        self.assertEqual(2, len(api.calls))

    def test_video_batches_are_50_50_1(self):
        api = FakeAPI([{"items": []}, {"items": []}, {"items": []}])
        module.fetch_videos(api, [str(i) for i in range(101)])
        self.assertEqual(
            [50, 50, 1], [len(call[1]["id"].split(",")) for call in api.calls]
        )

    def test_playlist_memberships_keep_multiple_public_playlists(self):
        api = FakeAPI([
            {"items": [
                {"id": "p1", "snippet": {"title": "퍼피교육"}},
                {"id": "p2", "snippet": {"title": "추천 영상"}},
            ]},
            {"items": [{"contentDetails": {"videoId": "v1"}}]},
            {"items": [
                {"contentDetails": {"videoId": "v1"}},
                {"contentDetails": {"videoId": "other"}},
            ]},
        ])
        result = module.fetch_playlist_memberships(api, "channel", ["v1"])
        self.assertEqual(
            [{"id": "p1", "title": "퍼피교육"}, {"id": "p2", "title": "추천 영상"}],
            result["v1"],
        )
        self.assertTrue(all(call[1]["maxResults"] == 50 for call in api.calls))

    def test_duration_conversion(self):
        self.assertEqual(3723, module.iso8601_duration_to_seconds("PT1H2M3S"))
        self.assertEqual(183845, module.iso8601_duration_to_seconds("P2DT3H4M5S"))
        self.assertEqual(300, module.iso8601_duration_to_seconds("PT5M"))

    def test_description_parser_preserves_intro_and_supports_chapter_formats(self):
        description = (
            "첫 문단 원문입니다.\n두 번째 줄입니다.\n\n"
            "00:00 하이라이트\n01:23 목줄 훈련\n1:02:15 긴 챕터\n"
            "https://example.com\n#강아지"
        )
        intro, chapters = module.parse_description(description)
        self.assertEqual("첫 문단 원문입니다.\n두 번째 줄입니다.", intro)
        self.assertEqual(
            [
                {"timestamp": "00:00", "start_seconds": 0, "title": "하이라이트"},
                {"timestamp": "01:23", "start_seconds": 83, "title": "목줄 훈련"},
                {"timestamp": "1:02:15", "start_seconds": 3735, "title": "긴 챕터"},
            ],
            chapters,
        )

    def test_intro_stops_at_promotion_and_recruitment_is_not_evidence(self):
        description = "내용 소개 원문\n[퍼피교육] 출연 모집처\nhttps://example.com"
        intro, chapters = module.parse_description(description)
        self.assertEqual("내용 소개 원문", intro)
        self.assertEqual([], chapters)
        result = module.classify("강아지 이야기", "[퍼피교육] 출연 모집처\nhttps://x.test", 600)
        self.assertEqual("REVIEW", result[0])
        self.assertNotIn("퍼피교육", " ".join(result[1]))

    def test_navigation_chapters_are_stored_but_not_content_signals(self):
        intro, chapters = module.parse_description(
            "교육 내용\n00:00 하이라이트\n00:15 오프닝\n01:20 목줄 훈련\n05:00 엔딩"
        )
        signals = module.extract_content_signals("퍼피교육", intro, chapters)
        self.assertIn("chapter:목줄 훈련", signals)
        self.assertFalse(any("하이라이트" in signal for signal in signals))
        self.assertFalse(any("오프닝" in signal for signal in signals))
        self.assertFalse(any("엔딩" in signal for signal in signals))

    def test_missing_statistics_remain_blank(self):
        row = module.normalize_video(
            {"id": "x", "snippet": {}, "contentDetails": {"duration": "PT1S"}}, "now"
        )
        self.assertEqual("", row["view_count"])
        self.assertEqual("", row["like_count"])
        self.assertEqual("", row["comment_count"])

    def test_strong_title_and_playlist_are_candidates(self):
        result = module.classify("예민한 강아지 [퍼피교육]", "", 600)
        self.assertEqual("CANDIDATE", result[0])
        self.assertIn("title:퍼피교육", result[1])
        result = module.classify("강아지 이야기", "", 600, ["주니어 교육 모음"])
        self.assertEqual("CANDIDATE", result[0])
        self.assertIn("playlist:주니어 교육", result[1])

    def test_show_title_containing_training_is_not_a_training_playlist(self):
        result = module.classify("강아지 영접하고 옴", "훈련사 이야기", 600, ["안고독한 훈련사"])
        self.assertEqual("REVIEW", result[0])
        self.assertEqual(["description:훈련"], result[1])

    def test_candidate_titles_from_latest_collection_remain_candidates(self):
        titles = [
            '"내 몸 만지지마!!" 개통령 손길도 피하는 예민쓰 파피용 [퍼피교육]',
            "개 조심. 귀여우니까 조심 [퍼피교육]",
            "강형욱도 무장 해제 시킨 '사람 좋아 강아지' [퍼피교육]",
            "잘생긴 남자만 좋아한다는 콩이 [주니어 교육]",
            "그냥 보호자님이 자랑하러 나온 게 확실. [주니어 교육]",
            "강형욱에게 쫄지 않기 위해 기립한 콩알 치와와씨 [퍼피교육]",
            "말랑콩떡 왕찹쌀떡 강아지에 감겨버렸습니다 [퍼피교육]",
            "외모 미쳤다 G무비네 강아지 [퍼피교육]",
            "훈련하기 싫어서 눈알 굴리는 댕쪽이 [퍼피교육]",
            "자신감 심어줬더니 종이컵 물고 튀는 강아지 [퍼피교육]",
            "하네스가 입기 싫은 강아지 [퍼피교육]",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual("CANDIDATE", module.classify(title, "", 600)[0])

    def test_safety_response_video_is_promoted_by_intro_and_chapters(self):
        description = (
            "안전한 반려견 문화를 위해 만든 영상입니다.\n\n"
            "00:00 인트로\n01:12 Step.1 위험 시그널\n"
            "03:34 Step.2 개가 달려들 때\n06:40 Step.3 개가 물었을 때"
        )
        result = module.classify(
            "'길에서 사나운 개를 만났다면?' 어떻게 해야할지 강형욱이 알려드립니다",
            description,
            789,
        )
        self.assertEqual("CANDIDATE", result[0])
        self.assertIn("structure:소개+구체적 챕터", result[1])

    def test_breed_characteristic_chapters_remain_review(self):
        description = (
            "오늘 견종백과로 만나볼 친구는 아키타이누입니다.\n"
            "00:00 하이라이트\n03:50 아키타이누의 활동량?\n06:19 아키타이누의 분리불안?"
        )
        self.assertEqual(
            "REVIEW", module.classify("견종백과 아키타이누편", description, 600)[0]
        )

    def test_description_only_matches_stay_review(self):
        for keyword in ("산책", "교육", "훈련", "짖음", "기다려", "배변"):
            with self.subTest(keyword=keyword):
                result = module.classify("강아지 이야기", f"오늘은 {keyword} 이야기", 600)
                self.assertEqual("REVIEW", result[0])
                self.assertIn(f"description:{keyword}", result[1])

    def test_candidate_evidence_under_180_seconds_stays_review(self):
        self.assertEqual("REVIEW", module.classify("퍼피교육 입질", "", 179)[0])
        self.assertEqual("CANDIDATE", module.classify("퍼피교육 입질", "", 180)[0])

    def test_exclude_priority_and_playlist(self):
        result = module.classify("퍼피교육", "협찬 영상", 600)
        self.assertEqual("EXCLUDE", result[0])
        self.assertEqual(["description:협찬"], result[1])
        self.assertEqual(
            "EXCLUDE", module.classify("강아지 이야기", "", 600, ["강형욱의 개스트쇼"])[0]
        )

    def test_tags_are_metadata_only_not_candidate_evidence(self):
        item = {
            "id": "x",
            "snippet": {"title": "견종백과 방카르편", "tags": ["훈련", "교육"]},
            "contentDetails": {"duration": "PT10M"},
        }
        row = module.normalize_video(item, "now")
        self.assertEqual("REVIEW", row["classification"])
        self.assertEqual(["훈련", "교육"], json.loads(row["tags"]))
        self.assertEqual([], json.loads(row["matched_keywords"]))

    def test_description_boilerplate_and_hashtags_are_ignored(self):
        description = "구독과 좋아요! 훈련 교육\n#산책 #훈련\nCopyright 훈련\n견종 이야기"
        self.assertEqual("REVIEW", module.classify("견종백과", description, 600)[0])
        self.assertEqual([], module.classify("견종백과", description, 600)[1])

    def test_reported_regressions(self):
        cases = [
            ("올해는 이게 내 워터밤이다... [강형욱의개스트쇼]", 600, "EXCLUDE"),
            ("드디어 견종백과 점수 정리합니다", 600, "REVIEW"),
            ("견종백과 방카르편", 600, "REVIEW"),
            ("26초 개스트쇼 쇼츠", 26, "EXCLUDE"),
            ("46초 개스트쇼 쇼츠", 46, "EXCLUDE"),
        ]
        for title, duration, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(expected, module.classify(title, "", duration)[0])

    def test_sixty_seconds_or_less_is_excluded_but_row_remains(self):
        item = {
            "id": "short", "snippet": {"title": "퍼피교육"},
            "contentDetails": {"duration": "PT60S"},
        }
        row = module.normalize_video(item, "now")
        self.assertEqual("short", row["video_id"])
        self.assertEqual("EXCLUDE", row["classification"])
        self.assertEqual(["duration:60초 이하"], json.loads(row["matched_keywords"]))

    def test_missing_api_key_fails_before_api_creation(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(module, "load_dotenv"):
            with self.assertRaisesRegex(module.ConfigurationError, "YOUTUBE_API_KEY"):
                module.main([])

    def test_csv_columns_review_fields_and_playlist_arrays(self):
        memberships = [{"id": "p1", "title": "퍼피교육"}]
        row = module.normalize_video(
            {"id": "x", "snippet": {"title": "교육", "tags": ["훈련"]},
             "contentDetails": {"duration": "PT1S"}},
            "now", memberships,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.csv"
            module.write_csv([row], path)
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            saved = next(reader)
            self.assertEqual(module.CSV_FIELDS, reader.fieldnames)
            self.assertEqual("PENDING", saved["review_status"])
            self.assertEqual("", saved["review_reason"])
            self.assertEqual(["훈련"], json.loads(saved["tags"]))
            self.assertEqual(["p1"], json.loads(saved["playlist_id"]))
            self.assertEqual(["퍼피교육"], json.loads(saved["playlist_title"]))
            self.assertIsInstance(json.loads(saved["chapters"]), list)
            self.assertIsInstance(json.loads(saved["content_signals"]), list)


if __name__ == "__main__":
    unittest.main()
