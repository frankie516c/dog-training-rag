import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "normalize_youtube_vtt.py"
SPEC = importlib.util.spec_from_file_location("normalize_youtube_vtt", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


SYNTHETIC_VTT = """WEBVTT
Kind: captions
Language: ko

00:00:00.000 --> 00:00:01.000 align:start position:0%
 
오늘<00:00:00.200><c> 하늘은</c> &amp; 바람은   잔잔해요.

00:00:01.000 --> 00:00:01.010 align:start position:0%
오늘 하늘은 &amp; 바람은 잔잔해요.

00:00:01.010 --> 00:00:03.000 align:start position:0%
오늘 하늘은 &amp; 바람은 잔잔해요.
작은 배가 천천히 출발해요.

00:00:03.000 --> 00:00:03.010 align:start position:0%
천천히 출발해요. 종이 울려요.

00:00:03.010 --> 00:00:04.000 align:start position:0%
새 장면에서 기차가 보여요.

00:00:04.000 --> 00:00:04.010 align:start position:0%
 
 

00:00:04.010 --> 00:00:05.000 align:start position:0%
마지막 안내를 시작합니다.
"""


class NormalizeYoutubeVttTests(unittest.TestCase):
    def test_rolling_suffix_only_cues_preserve_each_new_token(self):
        texts = ["A", "A", "A B", "B", "B C", "C", "C D", "D"]
        cues = tuple(
            module.ParsedCue(
                index=index,
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                raw_text=text,
                normalized_text=text,
            )
            for index, text in enumerate(texts)
        )
        repairs = module.CompatibilityRepairs((), (), ())

        result = module.normalize_rolling_captions(cues, "synthetic", repairs)

        self.assertEqual(["A", "B", "C", "D"], [s.text for s in result.segments])
        self.assertEqual(4, result.diagnostics.output_segments)
        self.assertEqual(6, result.diagnostics.rolling_overlaps)
        self.assertEqual(4, result.diagnostics.excluded_without_new_text)

    def test_parse_and_normalize_synthetic_rolling_captions(self):
        cues, repairs = module.parse_vtt_text(SYNTHETIC_VTT)
        result = module.normalize_rolling_captions(cues, "fictional", repairs)

        self.assertEqual(7, len(cues))
        self.assertEqual(0, cues[0].start_ms)
        self.assertEqual(1000, cues[0].end_ms)
        self.assertIn("<00:00:00.200><c>", cues[0].raw_text)
        self.assertEqual(
            "오늘 하늘은 & 바람은 잔잔해요.", cues[0].normalized_text
        )
        self.assertEqual("", cues[5].raw_text)
        self.assertEqual("", cues[5].normalized_text)

        self.assertEqual(
            [
                "오늘 하늘은 & 바람은 잔잔해요.",
                "작은 배가 천천히 출발해요.",
                "종이 울려요.",
                "새 장면에서 기차가 보여요.",
                "마지막 안내를 시작합니다.",
            ],
            [segment.text for segment in result.segments],
        )
        short_segment = result.segments[2]
        self.assertEqual(3000, short_segment.start_ms)
        self.assertEqual(3010, short_segment.end_ms)
        self.assertEqual((3,), short_segment.source_cue_indices)

        diagnostics = result.diagnostics
        self.assertEqual(7, diagnostics.total_cues)
        self.assertEqual(5, diagnostics.output_segments)
        self.assertEqual(1, diagnostics.empty_cues)
        self.assertEqual(1, diagnostics.exact_duplicates)
        self.assertEqual(2, diagnostics.rolling_overlaps)
        self.assertEqual(1, diagnostics.excluded_without_new_text)
        self.assertEqual(
            sum(len(segment.text.split()) for segment in result.segments),
            diagnostics.final_word_count,
        )

    def test_whitespace_payload_repair_is_narrow_and_records_source_line(self):
        source = """WEBVTT

00:00:00.000 --> 00:00:01.000
 
가상의 첫 문장입니다.

00:00:01.000 --> 00:00:02.000
가상의 둘째 문장입니다.
 

"""
        timing_lines = module.scan_timing_lines(source.splitlines())
        adapted, repairs = module.adapt_for_webvtt(source, timing_lines)

        self.assertEqual((4,), repairs.whitespace_line_numbers)
        self.assertEqual((0,), repairs.whitespace_cue_indices)
        self.assertIn("가상의 둘째 문장입니다.\n ", adapted)
        self.assertNotIn(
            "00:00:00.000 --> 00:00:01.000\n \n가상의 첫 문장입니다.",
            adapted,
        )

        cues, parsed_repairs = module.parse_vtt_text(source)
        self.assertEqual(2, len(cues))
        self.assertEqual(repairs, parsed_repairs)

    def test_empty_cue_uses_and_removes_unique_sentinel(self):
        source = """WEBVTT

00:00:00.000 --> 00:00:00.010
 
 

00:00:00.010 --> 00:00:01.000
새로 만든 본문입니다.
"""
        timing_lines = module.scan_timing_lines(source.splitlines())
        adapted, repairs = module.adapt_for_webvtt(source, timing_lines)
        self.assertEqual((0,), repairs.sentinel_cue_indices)
        self.assertIn(module.EMPTY_CUE_SENTINEL, adapted)

        cues, _ = module.parse_vtt_text(source)
        self.assertEqual("", cues[0].raw_text)
        self.assertEqual("", cues[0].normalized_text)
        self.assertTrue(
            all(module.EMPTY_CUE_SENTINEL not in cue.raw_text for cue in cues)
        )

    def test_reserved_sentinel_in_source_is_rejected(self):
        source = (
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n"
            f"{module.EMPTY_CUE_SENTINEL}\n"
        )
        with self.assertRaisesRegex(module.VttNormalizationError, "reserved"):
            module.parse_vtt_text(source)

    def test_reversed_and_negative_times_are_rejected(self):
        cases = {
            "reversed": "WEBVTT\n\n00:00:02.000 --> 00:00:01.000\n가상 문장\n",
            "negative": "WEBVTT\n\n-00:00:01.000 --> 00:00:01.000\n가상 문장\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(module.VttNormalizationError):
                    module.parse_vtt_text(source)

    def test_timing_line_and_parsed_cue_count_mismatch_is_an_error(self):
        source = """WEBVTT

00:00:00.000 --> 00:00:01.000
00:00:01.000 --> 00:00:02.000
서로 붙어 잘못 구성된 블록입니다.
"""
        with self.assertRaisesRegex(module.VttNormalizationError, "count mismatch"):
            module.parse_vtt_text(source)

    def test_repeated_processing_writes_identical_jsonl_without_sentinel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "fictional.ko-orig.vtt"
            output_dir = root / "processed"
            input_path.write_text(SYNTHETIC_VTT, encoding="utf-8")

            first_result, output_path = module.process_vtt(input_path, output_dir)
            first_bytes = output_path.read_bytes()
            second_result, second_path = module.process_vtt(input_path, output_dir)
            second_bytes = second_path.read_bytes()

            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(first_result.segments, second_result.segments)
            self.assertNotIn(module.EMPTY_CUE_SENTINEL.encode(), second_bytes)
            rows = [json.loads(line) for line in second_bytes.decode().splitlines()]
            self.assertEqual(list(range(len(rows))), [row["segment_index"] for row in rows])
            self.assertTrue(all(row["video_id"] == "fictional" for row in rows))
            self.assertTrue(
                all(isinstance(row["source_cue_indices"], list) for row in rows)
            )


if __name__ == "__main__":
    unittest.main()
