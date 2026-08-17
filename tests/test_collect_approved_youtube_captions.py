import csv
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_approved_youtube_captions.py"
SPEC = importlib.util.spec_from_file_location("collect_approved_youtube_captions", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


IDS = ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]


def write_ledger(path: Path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["video_id", "review_status"])
        writer.writeheader()
        writer.writerows(rows)


def write_raw(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")


def write_jsonl(path: Path, video_id: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "segment_index": 0, "video_id": video_id, "start_ms": 0,
        "end_ms": 1000, "text": "hello", "source_cue_indices": [0],
    }) + "\n", encoding="utf-8")


class FakeYoutubeDL:
    instances = []
    fail_ids = set()

    def __init__(self, options):
        self.options = options
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def download(self, urls):
        video_id = urls[0].split("v=", 1)[1]
        if video_id in self.fail_ids:
            raise RuntimeError("download failed")
        output = Path(self.options["outtmpl"].replace("%(ext)s", "ko-orig.vtt"))
        output.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")


class CollectorTests(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.instances = []
        FakeYoutubeDL.fail_ids = set()

    def setup_paths(self, rows):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        ledger = root / "ledger.csv"
        raw = root / "raw"
        output = root / "jsonl"
        write_ledger(ledger, rows)
        self.addCleanup(temp.cleanup)
        return ledger, raw, output

    def fake_process(self, raw_path, output_dir):
        video_id = raw_path.name.split(".", 1)[0]
        write_jsonl(output_dir / f"{video_id}.jsonl", video_id)
        return object(), output_dir / f"{video_id}.jsonl"

    def test_approved_only_and_limit(self):
        ledger, raw, output = self.setup_paths([
            {"video_id": IDS[0], "review_status": "PENDING"},
            {"video_id": IDS[1], "review_status": "APPROVED"},
            {"video_id": IDS[2], "review_status": "APPROVED"},
        ])
        with patch.object(module, "YoutubeDL", FakeYoutubeDL), patch.object(module, "process_vtt", self.fake_process):
            code, counts = module.run(ledger, raw, output, limit=1)
        self.assertEqual(0, code)
        self.assertEqual(1, counts["success"])
        self.assertEqual(IDS[1], FakeYoutubeDL.instances[0].options["outtmpl"].split("\\")[-1].split(".")[0])

    def test_valid_raw_and_jsonl_are_skipped_without_download(self):
        ledger, raw, output = self.setup_paths([{"video_id": IDS[0], "review_status": "APPROVED"}])
        write_raw(raw / f"{IDS[0]}.ko-orig.vtt")
        write_jsonl(output / f"{IDS[0]}.jsonl", IDS[0])
        with patch.object(module, "YoutubeDL", FakeYoutubeDL):
            code, counts = module.run(ledger, raw, output)
        self.assertEqual(0, code)
        self.assertEqual({"success": 0, "skipped": 1, "failed": 0}, counts)
        self.assertEqual([], FakeYoutubeDL.instances)

    def test_valid_raw_invalid_jsonl_normalizes_without_download(self):
        ledger, raw, output = self.setup_paths([{"video_id": IDS[0], "review_status": "APPROVED"}])
        write_raw(raw / f"{IDS[0]}.ko-orig.vtt")
        with patch.object(module, "YoutubeDL", FakeYoutubeDL), patch.object(module, "process_vtt", side_effect=self.fake_process) as process:
            code, counts = module.run(ledger, raw, output)
        self.assertEqual(0, code)
        self.assertEqual(1, counts["success"])
        self.assertEqual([], FakeYoutubeDL.instances)
        process.assert_called_once()

    def test_missing_raw_downloads_to_temp_then_replaces_final(self):
        ledger, raw, output = self.setup_paths([{"video_id": IDS[0], "review_status": "APPROVED"}])
        with patch.object(module, "YoutubeDL", FakeYoutubeDL), patch.object(module, "process_vtt", self.fake_process):
            code, counts = module.run(ledger, raw, output)
        self.assertEqual(0, code)
        self.assertEqual(1, counts["success"])
        self.assertTrue(raw.joinpath(f"{IDS[0]}.ko-orig.vtt").is_file())
        self.assertEqual([], list(raw.glob(".*")))

    def test_force_redownloads_even_when_both_outputs_are_valid(self):
        ledger, raw, output = self.setup_paths([{"video_id": IDS[0], "review_status": "APPROVED"}])
        write_raw(raw / f"{IDS[0]}.ko-orig.vtt")
        write_jsonl(output / f"{IDS[0]}.jsonl", IDS[0])
        with patch.object(module, "YoutubeDL", FakeYoutubeDL), patch.object(module, "process_vtt", self.fake_process):
            module.run(ledger, raw, output, force=True)
        self.assertEqual(1, len(FakeYoutubeDL.instances))

    def test_failed_download_keeps_existing_valid_raw(self):
        ledger, raw, output = self.setup_paths([{"video_id": IDS[0], "review_status": "APPROVED"}])
        raw_path = raw / f"{IDS[0]}.ko-orig.vtt"
        write_raw(raw_path)
        original = raw_path.read_bytes()
        FakeYoutubeDL.fail_ids = {IDS[0]}
        with patch.object(module, "YoutubeDL", FakeYoutubeDL):
            code, counts = module.run(ledger, raw, output, force=True)
        self.assertEqual(1, code)
        self.assertEqual(1, counts["failed"])
        self.assertEqual(original, raw_path.read_bytes())

    def test_one_failure_does_not_stop_other_videos(self):
        ledger, raw, output = self.setup_paths([
            {"video_id": IDS[0], "review_status": "APPROVED"},
            {"video_id": IDS[1], "review_status": "APPROVED"},
        ])
        FakeYoutubeDL.fail_ids = {IDS[0]}
        with patch.object(module, "YoutubeDL", FakeYoutubeDL), patch.object(module, "process_vtt", self.fake_process):
            code, counts = module.run(ledger, raw, output)
        self.assertEqual(1, code)
        self.assertEqual(1, counts["failed"])
        self.assertEqual(1, counts["success"])

    def test_dry_run_does_not_create_directories_or_call_download(self):
        ledger, raw, output = self.setup_paths([{"video_id": IDS[0], "review_status": "APPROVED"}])
        with patch.object(module, "YoutubeDL", FakeYoutubeDL), patch.object(module, "process_vtt", self.fake_process):
            code, counts = module.run(ledger, raw, output, dry_run=True)
        self.assertEqual(0, code)
        self.assertEqual(1, counts["would_download"] + counts["would_normalize"])
        self.assertFalse(raw.exists())
        self.assertFalse(output.exists())
        self.assertEqual([], FakeYoutubeDL.instances)

    def test_dry_run_uses_would_counts_and_summary(self):
        ledger, raw, output = self.setup_paths([
            {"video_id": IDS[0], "review_status": "APPROVED"},
            {"video_id": IDS[1], "review_status": "APPROVED"},
            {"video_id": IDS[2], "review_status": "APPROVED"},
        ])
        write_raw(raw / f"{IDS[0]}.ko-orig.vtt")
        write_jsonl(output / f"{IDS[0]}.jsonl", IDS[0])
        write_raw(raw / f"{IDS[1]}.ko-orig.vtt")
        buffer = StringIO()
        with redirect_stdout(buffer), patch.object(module, "YoutubeDL", FakeYoutubeDL):
            code = module.main([
                "--ledger", str(ledger), "--raw-dir", str(raw),
                "--output-dir", str(output), "--dry-run",
            ])
        self.assertEqual(0, code)
        self.assertIn("approved: 3 would_process: 2 would_skip: 1 failed: 0", buffer.getvalue())
        self.assertIn("WOULD_DOWNLOAD=1", buffer.getvalue())
        self.assertIn("WOULD_NORMALIZE=1", buffer.getvalue())
        self.assertIn("WOULD_SKIP=1", buffer.getvalue())
        self.assertEqual([], FakeYoutubeDL.instances)

    def test_empty_jsonl_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.jsonl"
            path.write_text("", encoding="utf-8")
            self.assertFalse(module.jsonl_is_valid(path, IDS[0]))

    def test_invalid_or_duplicate_ledger_fails_before_processing(self):
        ledger, raw, output = self.setup_paths([
            {"video_id": IDS[0], "review_status": "APPROVED"},
            {"video_id": IDS[0], "review_status": "PENDING"},
        ])
        with self.assertRaises(module.CaptionCollectionError):
            module.run(ledger, raw, output)

        write_ledger(ledger, [{"video_id": "bad", "review_status": "APPROVED"}])
        with self.assertRaises(module.CaptionCollectionError):
            module.run(ledger, raw, output)


if __name__ == "__main__":
    unittest.main()
