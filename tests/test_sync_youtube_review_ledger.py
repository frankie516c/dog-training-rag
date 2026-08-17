import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "sync_youtube_review_ledger.py"
SPEC = importlib.util.spec_from_file_location("sync_youtube_review_ledger", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


def metadata(video_id, title, classification="CANDIDATE"):
    return {"video_id": video_id, "title": title, "classification": classification}


class ReviewLedgerTests(unittest.TestCase):
    def test_first_candidate_is_added_pending(self):
        rows = module.synchronize_rows([metadata("a", "첫 후보")], [])
        self.assertEqual(1, len(rows))
        self.assertEqual("PENDING", rows[0]["review_status"])
        self.assertEqual("https://www.youtube.com/watch?v=a", rows[0]["video_url"])

    def test_rerun_does_not_duplicate_or_change_result(self):
        first = module.synchronize_rows([metadata("a", "첫 후보")], [])
        second = module.synchronize_rows([metadata("a", "첫 후보")], first)
        self.assertEqual(first, second)
        self.assertEqual(1, len(second))

    def test_human_review_is_preserved_while_metadata_is_refreshed(self):
        ledger = [{
            "video_id": "a", "title": "이전 제목", "video_url": "old",
            "classification": "REVIEW", "review_status": "APPROVED",
            "review_reason": "직접 확인", "reviewed_at": "2026-08-17",
        }]
        row = module.synchronize_rows([metadata("a", "최신 제목")], ledger)[0]
        self.assertEqual("최신 제목", row["title"])
        self.assertEqual("CANDIDATE", row["classification"])
        self.assertEqual("APPROVED", row["review_status"])
        self.assertEqual("직접 확인", row["review_reason"])
        self.assertEqual("2026-08-17", row["reviewed_at"])

    def test_new_candidate_is_appended(self):
        existing = module.synchronize_rows([metadata("a", "기존")], [])
        rows = module.synchronize_rows(
            [metadata("a", "기존"), metadata("b", "신규")], existing
        )
        self.assertEqual(["a", "b"], [row["video_id"] for row in rows])

    def test_classification_change_keeps_existing_record(self):
        existing = module.synchronize_rows([metadata("a", "후보")], [])
        rows = module.synchronize_rows([metadata("a", "변경", "REVIEW")], existing)
        self.assertEqual(1, len(rows))
        self.assertEqual("REVIEW", rows[0]["classification"])
        self.assertEqual("PENDING", rows[0]["review_status"])


if __name__ == "__main__":
    unittest.main()
