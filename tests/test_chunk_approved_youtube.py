import importlib.util
import sys
import unittest

from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "chunk_approved_youtube.py"
SPEC = importlib.util.spec_from_file_location("chunk_approved_youtube", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def segment(index, text, start, end, chapter_index=0, role="CONTENT", chapter_title="Content", eligible=True, reason=None):
    return {
        "segment_index": index,
        "video_id": "synthetic",
        "start_ms": start,
        "end_ms": end,
        "text": text,
        "source_cue_indices": [index + 100],
        "chapter_index": chapter_index,
        "chapter_title": chapter_title,
        "chapter_role": role,
        "embedding_eligible": eligible,
        "exclusion_reason": reason,
    }


class ChunkApprovedYoutubeTests(unittest.TestCase):
    def test_chapter_overlap_tie_and_edge_fallbacks(self):
        chapters = [
            {"chapter_index": 0, "chapter_title": "First", "start_ms": 100},
            {"chapter_index": 1, "chapter_title": "Second", "start_ms": 200},
        ]
        rows = [
            segment(0, "before", 20, 50),
            segment(1, "tie", 190, 210),
            segment(2, "after", 300, 320),
        ]
        attached = module.attach_chapters(rows, chapters)
        self.assertEqual([0, 0, 1], [row["chapter_index"] for row in attached])

    def test_no_chapters_is_embedding_eligible_unchaptered(self):
        rows = module.attach_chapters([segment(0, "content", 0, 10)], [])
        self.assertEqual("UNCHAPTERED", rows[0]["chapter_role"])
        self.assertTrue(rows[0]["embedding_eligible"])
        self.assertIsNone(rows[0]["exclusion_reason"])

    def test_non_content_reason_is_preserved(self):
        role, eligible, reason = module.classify_chapter("오프닝", True)
        self.assertEqual(("NON_CONTENT", False, "chapter_title:오프닝"), (role, eligible, reason))

    def test_short_speaker_marker_does_not_split(self):
        config = module.ChunkingConfig(target_chars=10, min_chars=3, max_chars=20)
        rows = [segment(0, "aaa", 0, 10), segment(1, ">>bbb", 10, 20)]
        chunks = module._chunk_group(rows, config)
        self.assertEqual([["aaa", ">>bbb"]], [[row["text"] for row in chunk] for chunk in chunks])

    def test_target_speaker_marker_is_a_split_candidate(self):
        config = module.ChunkingConfig(target_chars=8, min_chars=3, max_chars=20)
        rows = [segment(0, "abcdefgh", 0, 10), segment(1, ">>q", 10, 20)]
        chunks = module._chunk_group(rows, config)
        self.assertEqual([["abcdefgh"], [">>q"]], [[row["text"] for row in chunk] for chunk in chunks])

    def test_sentence_end_before_speaker_marker_can_split(self):
        config = module.ChunkingConfig(target_chars=5, min_chars=3, max_chars=20)
        rows = [segment(0, "done?", 0, 10), segment(1, ">>next", 10, 20)]
        chunks = module._chunk_group(rows, config)
        self.assertEqual([["done?"], [">>next"]], [[row["text"] for row in chunk] for chunk in chunks])

    def test_target_before_soft_boundary_is_reused(self):
        config = module.ChunkingConfig(target_chars=10, min_chars=5, max_chars=20)
        rows = [
            segment(0, "aaaa.", 0, 10),
            segment(1, "bbbb", 10, 20),
            segment(2, "cccc", 20, 30),
        ]
        chunks = module._chunk_group(rows, config)
        self.assertEqual([["aaaa."], ["bbbb", "cccc"]], [[row["text"] for row in chunk] for chunk in chunks])

    def test_too_long_chunk_uses_segment_boundary(self):
        config = module.ChunkingConfig(target_chars=8, min_chars=4, max_chars=10)
        rows = [segment(0, "aaaa", 0, 1), segment(1, "bbbb", 1, 2), segment(2, "cccc", 2, 3)]
        chunks = module._chunk_group(rows, config)
        self.assertEqual([["aaaa", "bbbb"], ["cccc"]], [[row["text"] for row in chunk] for chunk in chunks])

    def test_short_last_chunk_merges_with_previous(self):
        config = module.ChunkingConfig(target_chars=5, min_chars=5, max_chars=12)
        rows = [segment(0, "aaaa.", 0, 1), segment(1, "b", 1, 2), segment(2, "cc", 2, 3)]
        chunks = module._chunk_group(rows, config)
        self.assertEqual([["aaaa.", "b", "cc"]], [[row["text"] for row in chunk] for chunk in chunks])

    def test_chapters_are_never_merged_and_indexes_are_preserved(self):
        config = module.ChunkingConfig(target_chars=100, min_chars=1, max_chars=100)
        rows = [
            segment(0, "one", 0, 1, chapter_index=0),
            segment(1, "two", 1, 2, chapter_index=1, chapter_title="Second"),
        ]
        chunks = module.build_chunks(rows, config)
        self.assertEqual([0, 1], [row["chapter_index"] for row in chunks])
        self.assertEqual([[0], [1]], [row["source_segment_indices"] for row in chunks])
        self.assertEqual([[100], [101]], [row["source_cue_indices"] for row in chunks])

    def test_chunk_id_is_stable_and_changes_with_settings(self):
        rows = [segment(0, "same", 0, 10)]
        first = module.build_chunks(rows, module.ChunkingConfig(10, 1, 20, 0))[0]["chunk_id"]
        second = module.build_chunks(rows, module.ChunkingConfig(10, 1, 20, 0))[0]["chunk_id"]
        changed = module.build_chunks(rows, module.ChunkingConfig(11, 1, 20, 0))[0]["chunk_id"]
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertRegex(first, r"^chunk-[0-9a-f]{64}$")

    def test_invalid_settings_fail_before_chunking(self):
        with self.assertRaises(module.ChunkingError):
            module.ChunkingConfig(10, 11, 20).validate()


if __name__ == "__main__":
    unittest.main()
