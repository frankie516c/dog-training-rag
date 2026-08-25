# gold 승인 반영 → 평가 시도 (2026-08-25)

지시받은 [0]~[5]를 순서대로 실행한 기록입니다. **[3]에서 막혀 [4]의 재인제스트는
실행하지 않았습니다.** 각 절에 실행한 명령과 나온 값을 그대로 적습니다.

규칙 4번을 따릅니다 — 이 문서에 코퍼스 본문은 인용하지 않았습니다. 식별자
(`doc_id`, `chunk_index`), 개수, 그리고 이 프로젝트가 쓴 질문 문장만 씁니다.

---

## 요약

| 단계 | 결과 |
|---|---|
| [0] 상태 선언 | 코퍼스가 두 워크트리로 갈려 있음 — 아래 참조 |
| [1] gold import | **통과.** 승인 40 / 미판정 0 |
| [2] resolved_at 분포 | **완료.** 교차표 아래 |
| [3] 기준선 평가 | **실패로 중단.** `g001`에서 `EvalError`, exit=1 |
| [4] P1 재인제스트 | **실행 안 함.** 선행 확인은 완료(겹침 0) — 사유 아래 |
| [5] 하이브리드 근거 | **완료.** 숫자만. 판단 없음 |

막힌 지점은 하나입니다: **사람이 고른 정답 청크 15개가 gold 파일에 기록되지
않습니다.** [3]과 [4]가 여기에 함께 걸려 있습니다.

---

## [0] 시작 전 상태 선언

두 워크트리의 `data/processed`가 다릅니다. `data/`는 gitignore 대상이라 git이
동기화하지 않고, 워크트리마다 독립적으로 존재합니다.

| | 브랜치 @ HEAD | 문서 청크 | 영상 청크 | export | gold_batch1 |
|---|---|---:|---:|---|---|
| `dog-training-rag-retrieval/` | `verify/document-parsing-829` @ `ad403b3` | **219** (17파일) | 35 | **있음** 32,938바이트 21:07 | APPROVED 40/40 |
| `.claude/worktrees/vector-rag-transition/` | `worktree-vector-rag-transition` @ `6cb3fc9` | **277** (29파일) | 35 | 없음 | APPROVED 0/40 |

**지시는 "277 쪽이 아니면 멈춰라"였고, 두 조건이 서로 다른 워크트리에 있습니다**
— 277 코퍼스는 워크트리에, export와 승인된 gold는 메인에 있습니다. 어느 한쪽에
둘 다 있지 않습니다.

파일을 옮기거나 어느 쪽이 정본인지 정하지 않았습니다. 대신 **작업 디렉터리는
메인, 코퍼스는 `--doc-chunks`/`--video-chunks`로 277 쪽을 가리키는** 방식으로
모든 단계를 실행했습니다. 지시의 목적(평가 코퍼스가 277이어야 한다)은
충족하지만 문언(워크트리 자체가 277이어야 한다)과는 어긋납니다. **이 선택이
잘못이면 되돌려 주십시오** — 파일은 아무것도 옮기지 않았습니다.

277 코퍼스가 bake와 동일하다는 것은 지문으로 확인했습니다:

```
bake 기록  : sha256:db11af7eab3b1072fc01040fe2453c05f96fc17122e97099dff362665562ab24
재계산     : 동일 (문서 277 + embedding_eligible 영상 26 = 303청크)
```

---

## [1] gold import — 통과

전제 확인 (`data/eval/labeling/gold_labels_export.json`, 메인 워크트리):

```
행 수 = 40                    (요구: 40) → 통과
human_confirmed = {True: 40}
coverage 지정됨 = 40
gold_chunk_ids 총 지정 = 15
```

실행:

```
uv run python scripts/import_gold_labels.py \
  --doc-chunks   <워크트리>/data/processed/documents/chunks \
  --video-chunks <워크트리>/data/processed/youtube/chunks
→ 승인 40 / 미판정 0 -> data\eval\queries\gold_batch1.jsonl
→ 에이전트 제안과 다른 판정 2건: g001, g011
```

기본 경로(메인의 219청크)로 먼저 돌렸을 때는 재검증 훅이 거부했습니다. 거부
이유를 그대로 남깁니다:

```
기록하지 않았다 — 아래를 먼저 해결할 것:
  g004 앵커 재검증: 인용문이 코퍼스 어디에도 없다 — 본문이 편집됐거나 앵커를 다시 뽑아야 한다
  g004 앵커 재검증: 인용문이 코퍼스 어디에도 없다 — 본문이 편집됐거나 앵커를 다시 뽑아야 한다
```

`g004`의 앵커 2개가 `wayopet-walk-training-answer`와 `wayopet-fear-barking-answer`를
가리키는데, 메인 워크트리에는 wayopet 문서 12파일이 없습니다. **라벨 문제가
아니라 코퍼스 사본 문제**이며, 우회하지 않고 bake 지문과 일치하는 코퍼스를
가리켜 통과시켰습니다. bake는 다시 굽지 않았습니다.

---

## [2] resolved_at 최종 분포

`coverage` × `resolved_at`, n=40:

| coverage | vector_top5 | vector_top20 | lexical | missing | 합계 |
|---|---:|---:|---:|---:|---:|
| answerable | 7 | 1 | 1 | 0 | **9** |
| partial | 2 | 3 | 2 | 0 | **7** |
| missing | 0 | 0 | 0 | 24 | **24** |
| **합계** | **9** | **4** | **3** | **24** | **40** |

- `coverage=missing` ⟺ `resolved_at=missing`이 정확히 일대일입니다. 어긋난 행 0개.
- `missing` 24건 중 **8건은 `query_type=refuse_boundary`** 입니다(수의 진단, 투약
  용량, 백신, 사람 약, 훈련소 추천, 펫보험, 고양이). 코퍼스에 없는 것이 정답인
  질의라 커버리지 결손으로 세면 안 됩니다.
- 그 8건을 빼면 실질 32건 중 answerable 9 / partial 7 / missing 16입니다.

---

## [3] 기준선 평가 — 실패로 중단

실행 (추적 파일 `combined_v4_e5_metrics.json`을 덮지 않도록 출력은 스크래치로
돌렸습니다):

```
uv run python scripts/run_combined_retrieval_eval.py \
  --doc-chunks <워크트리>/.../documents/chunks \
  --video-chunks <워크트리>/.../youtube/chunks \
  --gold data/eval/queries/gold_batch1.jsonl \
  --metrics <스크래치>/p1_before_metrics.json \
  --report  <스크래치>/p1_before_report.md

error: g001: gold 참조가 어느 청크에도 매핑되지 않는다
       (relevant_spans·anchors 둘 다 비었거나 해석 실패). …
exit=1
```

지표는 나오지 않았습니다. 질의 유형별 recall@k·MRR도 산출 불가입니다.

### 원인 — 사람이 고른 정답이 파일에 기록되지 않는다

`scripts/import_gold_labels.py`에서 `gold_chunk_ids`가 나오는 곳은 **118행
하나뿐이고 읽기 전용**입니다:

```python
118:  gold_ids = got.get("gold_chunk_ids") or []
121:  if got["coverage"] == "answerable" and not gold_ids and not anchors:   # 검증에만 사용
```

기록 블록(146–164행)은 `coverage`·`review_status`·`quality_flag`·`resolved_at`·
`cause_only_chunks`·`anchors`·`agent_suggestion_overridden`을 씁니다.
**`gold_chunk_ids`를 행에 쓰는 줄이 없습니다.** export의 15개 지정이 통째로
버려집니다. 커밋된 `gold_batch1.jsonl`에는 `gold_chunks` 필드 자체가 없습니다.

### 실측 — 40건 중 10건이 gold 매핑에 실패

`gold_relevant_chunks()`를 277 코퍼스로 40행에 직접 돌린 결과:

```
gold 매핑 성공 30 / EvalError 10
  g001 g019 g020                    [answerable]
  g010 g011 g015 g025 g026 g027 g032 [partial]
```

성공한 30건 중 24건은 `coverage=missing`이라 빈 집합을 반환하고 끝납니다.
**실제로 정답 집합이 만들어지는 질의는 앵커가 있는 6건뿐입니다**
(g004, g006, g008, g012, g013, g031).

이 예외는 의도된 것입니다 — `run_combined_retrieval_eval.py:232`에 gold가 조용히
줄면 정답 집합이 작아져 Hit@1이 오히려 올라가고 그것을 개선으로 읽게 된다고
적혀 있습니다. 설계대로 막힌 것이고, 막힌 것이 맞습니다.

### `without_chunk_text()` 적용 여부 — 확인됨

`run_combined_retrieval_eval.py:1222–1223`에서 스냅샷 기록 시 적용됩니다:

```python
args.metrics.write_bytes(
    json.dumps(without_chunk_text(payload), ensure_ascii=False, indent=2).encode("utf-8"))
```

주석대로 `payload`가 아니라 디스크로 나가는 길에서만 벗깁니다(`build_report()`는
본문을 계속 읽습니다). **다만 이번 실행은 그 지점에 도달하기 전에 죽었으므로,
"결과 JSON에 본문 0건"은 코드로만 확인했고 산출물로는 검증하지 못했습니다.**

---

## [4] P1 재인제스트 — 선행 확인만 하고 실행하지 않음

### 선행 확인 결과: 겹침 0

P1이 건드리는 문서와, 그 안에서 **실제로 텍스트가 바뀌는 청크**:

| doc_id | 규칙 | 문서 청크 수 | 바뀌는 청크 |
|---|---|---:|---|
| `berrardog-patella-221074570293` | R1 (확정) | 4 | `#0` |
| `berrardog-separation-anxiety-222630433514` | R4 (확정) | 12 | `#11` |
| `fitpet-fence-training` | R4b (보류) | 10 | `#8` |

대조 결과:

- **커밋된 gold의 앵커 7개 → 겹침 0건.** 앵커가 가리키는 문서는
  wayopet 2건, easiestip 3건, fitpet-potty 1건으로 P1 대상 문서가 아닙니다.
- **export의 gold 청크 15개 → 문서 단위로는 1건 겹침, 청크 단위로는 0건.**
  `g001`의 gold가 `berrardog-separation-anxiety-222630433514`에 있지만
  **`#9`이고, P1이 바꾸는 것은 `#11`** 입니다.

`chunk_id`는 `CHUNK_ID_PAYLOAD_KEYS`(`doc_id`, `chunk_index`, `text_sha256`,
청킹 파라미터)의 해시입니다(`ingest_documents.py:75, 728`). `#9`은 자기 텍스트가
바뀌지 않고, 변경 지점 `#11`이 뒤에 있어 인덱스도 밀리지 않습니다. 다만 이것은
**청킹이 본문을 앞에서부터 순차로 자른다는 성질에 기댄 결론이고, 재인제스트 후
chunk_id를 실제로 비교해 확인한 것은 아닙니다.**

### 실행하지 않은 이유

지시는 "안 겹치면 재인제스트 후 [3]을 같은 조건으로 다시 돌려 before/after를
같은 표에 올려라"였습니다. **[3]이 before를 만들지 못했으므로 after를 만들어도
비교할 대상이 없습니다.** 그리고 지금 재인제스트하면 gold 청크 지정이 아직
파일에 없는 상태에서 `chunk_id`가 움직입니다 — 나중에 [3]의 버그를 고쳐
export를 다시 반영할 때, export에 적힌 `chunk_id` 15개가 새 코퍼스와 맞지 않을
수 있습니다. 되돌리기 어려운 쪽이라 멈췄습니다.

---

## [5] 하이브리드 검색 판단 근거 — 숫자만

**판단은 하지 않습니다.**

### [5-a] 벡터 단독이 놓친 질의

| 분류 | 건수 | 질의 |
|---|---:|---|
| `lexical` — 벡터풀 20 안에 아예 없음 | 3 | g011, g015, g019 |
| `vector_top20` — 풀에는 있으나 top-5 밖 | 4 | g010, g020, g025, g026 |

### [5-b] BM25 정확일치 대용 지표

질의에서 뽑힌 키워드가 **사람이 고른 gold 청크 본문에 그대로 나오는지** 셌습니다.

| qid | resolved_at | coverage | 키워드 수 | 정확일치 | 일치 키워드 |
|---|---|---|---:|---:|---|
| g010 | vector_top20 | partial | 4 | 1 | `만지` |
| g011 | lexical | partial | 4 | 1 | `입질` |
| g015 | lexical | partial | 4 | — | gold 청크 미지정 |
| g019 | lexical | answerable | 5 | 1 | `혼자` |
| g020 | vector_top20 | answerable | 4 | 0 | 없음 |
| g025 | vector_top20 | partial | 4 | — | gold 청크 미지정 |
| g026 | vector_top20 | partial | 3 | — | gold 청크 미지정 |

```
gold 청크가 지정된 것        4건
그중 정확일치 1개 이상       3건
gold 청크 미지정             3건  (g015, g025, g026 — export에서 cause_only만 지정)
```

**주의: 표본이 7건이고 그중 3건은 gold 청크가 없어 측정 자체가 불가능합니다.**
`g020`은 벡터가 top-5를 놓쳤는데 키워드 정확일치도 0입니다.

### 참고 — 품질 플래그

`quality_flag=unreadable_asr` 2건(g010, g025). `g025`의 `label_reason`에
"g010과 동일 청크"라고 적혀 있어, 질의 수가 아니라 unique video `chunk_id`로
세면 더 적습니다. 검색 문제가 아니라 전사 품질 문제입니다.

---

## 막힌 지점 — 결정이 필요한 것

`import_gold_labels.py`에 기록 한 줄이 빠진 것이지만, **어떤 형태로 기록할지가
정답의 정의를 바꾸는 결정**이라 손대지 않았습니다.

`gold_relevant_chunks()`는 현재 두 체계만 읽습니다 — 영상은 `relevant_spans`
(시간축), 문서는 `anchors`(인용문 + `doc_id`). 청크 id 직접 지정은 읽지 않습니다.

| 선택지 | 내용 | 대가 |
|---|---|---|
| A | `gold_chunks`로 청크 id를 그대로 싣고 평가에 세 번째 경로 추가 | `chunk_id`가 `text_sha256` 기반이라 재인제스트 때 깨짐 — 앵커를 `doc_id`로 잡은 이유와 정면 충돌 |
| B | 지정된 청크에서 인용문을 뽑아 앵커로 승격 | 재인제스트에 견딤. 인용문 선택에 사람 판단이 다시 들어감 |
| C | 영상은 `relevant_spans`로, 문서는 앵커로 나눠 넣음 | 기존 두 체계 유지. 변환 작업이 큼. export의 15개 중 영상 청크 4건(g010·g011·g020·g027)은 span 변환 필요 |

export(`gold_labels_export.json`, 21:07)에 사람 판정 원본이 온전히 남아 있어
어느 쪽을 고르든 재기록은 가능합니다. **이 파일은 `.gitignore:69`에 걸려 추적되지
않으므로 지우면 복구 경로가 없습니다.**

---

## 이번에 건드리지 않은 것

- bake 재실행 없음. `write_gold_labels_batch1.py`도 돌리지 않음
- 푸시 없음 (`ad59223`·`4ce9a1a`의 보류 조건 유지)
- 이력 재작성 없음
- 추적 파일 `data/eval/results/combined_v4_e5_metrics.json` 덮어쓰지 않음 —
  평가 출력은 스크래치 경로로 돌림
- 워크트리 간 파일 이동·복사 없음
