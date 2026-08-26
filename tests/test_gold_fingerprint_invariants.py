"""`corpus_fingerprint`가 존재 이유를 수행하게 만드는 불변식.

이 필드는 "이 판정이 어느 코퍼스에서 내려졌는가"를 가리킨다. 그런데 실측해
보니 **기록만 되고 아무도 읽지 않았다** — `run_combined_retrieval_eval.py`도
`import_gold_labels.py`도 테스트도 값을 검증하지 않았다. 그래서 한 파일에 두
시점의 지문이 섞여도 조용했다.

섞이는 것 자체는 정상이다. 코퍼스를 늘린 뒤 결손 질의만 다시 판정하면 그렇게
된다. **문제는 필드마다 코퍼스 의존성이 다르다는 것이다.**

| 필드 | 코퍼스가 바뀌면 |
|---|---|
| `coverage`, `anchors`, `relevant_spans` | 유효. 앵커는 `doc_id`, span은 시간축이라 재청킹에 견딘다 |
| **`resolved_at`** | **무효.** bake가 만든 후보 풀에서 어느 단계에 근거가 나왔는지를 가리키므로, 풀이 달라지면 `vector_top5`/`vector_top20`/`lexical`의 경계가 이동한다 |

그래서 검사를 `resolved_at`에 건다. 이 값이 있는 행은 그 행의
`corpus_fingerprint`가 **지금 코퍼스의 지문과 같아야** 한다. 이 검사가 걸리는
행의 목록이 곧 "부분 재bake 후 다시 판정받아야 하는 행"이다.

픽스처는 전부 합성이다(`docs/SOURCES.md` 규칙 4).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import run_combined_retrieval_eval as ev  # noqa: E402

GOLD = REPO / "data" / "eval" / "queries" / "gold_batch1.jsonl"
DOC_CHUNKS = REPO / "data" / "processed" / "documents" / "chunks"
VIDEO_CHUNKS = REPO / "data" / "processed" / "youtube" / "chunks"

# resolved_at은 후보 풀에 의존한다. 이 값들만 재판정 대상이다.
POOL_DEPENDENT_FIELD = "resolved_at"


def gold_rows():
    if not GOLD.is_file():
        return []
    return [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]


class ResolvedAtMustMatchTheCurrentCorpus(unittest.TestCase):
    """A-3 — 낡은 지문에 매달린 `resolved_at`은 실패한다."""

    @unittest.skipUnless(DOC_CHUNKS.is_dir() and VIDEO_CHUNKS.is_dir(),
                         "코퍼스가 없는 환경(clean clone)에서는 건너뛴다")
    def test_rows_with_resolved_at_carry_the_current_fingerprint(self):
        rows = gold_rows()
        if not rows:
            self.skipTest("gold 파일이 없다")
        video = [c for c in ev.load_video_chunks(VIDEO_CHUNKS) if c.get("embedding_eligible")]
        documents = list(ev.load_document_chunks(DOC_CHUNKS))
        current = ev.fingerprint(video + documents)

        matching = [r for r in rows if r.get("corpus_fingerprint") == current]
        pool_dependent = [r for r in rows if r.get(POOL_DEPENDENT_FIELD)]
        if not pool_dependent:
            self.skipTest("resolved_at을 가진 행이 없다")
        if not matching:
            # 이 워크트리의 data/processed가 라벨을 만든 코퍼스가 아니다. data/는
            # gitignore 대상이라 워크트리마다 독립이고, 여기 사본이 낡을 수 있다.
            # 그 상태를 "낡은 라벨"로 보고하면 거짓 경보가 되므로 건너뛴다.
            recorded = sorted({(r.get("corpus_fingerprint") or "(없음)")[:26] for r in rows})
            self.skipTest(
                f"로컬 코퍼스({current[:26]}…)가 라벨 코퍼스({', '.join(recorded)}…)가 아니다 "
                "— 이 워크트리의 data/processed 사본이 라벨 시점과 다르다"
            )

        # 여기부터가 본 검사다. 일부 행은 현재 코퍼스에서 판정됐는데 일부는 아니라면,
        # 그것이 부분 재bake로 생기는 상태다. resolved_at은 후보 풀에 의존하므로
        # 낡은 쪽은 무효다.
        stale = [
            (row["query_id"], (row.get("corpus_fingerprint") or "(없음)")[:26])
            for row in pool_dependent
            if row.get("corpus_fingerprint") != current
        ]
        self.assertEqual(
            stale, [],
            f"resolved_at이 낡은 코퍼스 지문에 매달려 있다 (현재 {current[:26]}…). "
            "이 값은 bake가 만든 후보 풀에 의존하므로 코퍼스가 바뀌면 무효다 — "
            "해당 행을 다시 bake해 재판정하거나 resolved_at을 비울 것.",
        )

    def test_the_check_ignores_fields_that_survive_a_corpus_change(self):
        """coverage·anchors는 지문이 달라도 유효하므로 이 검사에 걸리지 않는다."""
        rows = [
            {"query_id": "q1", "coverage": "answerable", "corpus_fingerprint": "sha256:old",
             "anchors": [{"anchor_id": "q1-a1", "doc_id": "d", "quote": "합성"}]},
            {"query_id": "q2", "coverage": "missing", "corpus_fingerprint": "sha256:old"},
        ]
        stale = [r["query_id"] for r in rows
                 if r.get(POOL_DEPENDENT_FIELD) and r.get("corpus_fingerprint") != "sha256:new"]
        self.assertEqual(stale, [])

    def test_a_stale_resolved_at_is_caught(self):
        """같은 규칙을 합성 행에 적용하면 잡힌다 — 검사가 무력하지 않다는 확인."""
        rows = [
            {"query_id": "q1", "resolved_at": "vector_top5", "corpus_fingerprint": "sha256:old"},
            {"query_id": "q2", "resolved_at": "lexical", "corpus_fingerprint": "sha256:new"},
        ]
        stale = [r["query_id"] for r in rows
                 if r.get(POOL_DEPENDENT_FIELD) and r.get("corpus_fingerprint") != "sha256:new"]
        self.assertEqual(stale, ["q1"])


class TheFingerprintIsActuallyRead(unittest.TestCase):
    """A-1·A-2 — 기록만 하고 안 읽던 상태로 돌아가지 않게 고정한다."""

    def test_import_reports_the_fingerprint_distribution(self):
        source = (REPO / "scripts" / "import_gold_labels.py").read_text(encoding="utf-8")
        self.assertIn("corpus_fingerprint", source,
                      "import이 지문 분포를 읽지 않는다 — 섞여도 조용해진다")

    def test_the_snapshot_carries_the_fingerprint_distribution(self):
        source = (REPO / "scripts" / "run_combined_retrieval_eval.py").read_text(encoding="utf-8")
        self.assertIn("gold_corpus_fingerprints", source,
                      "스냅샷에 지문 분포가 없으면 지표를 한 시점의 것으로 오독하게 된다")


if __name__ == "__main__":
    unittest.main()
