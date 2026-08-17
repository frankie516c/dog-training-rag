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


if __name__ == "__main__":
    unittest.main()
