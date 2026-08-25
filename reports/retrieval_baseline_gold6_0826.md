# 검색 기준선 — **채점 대상 6문항** (P1 이전, 2026-08-26)

> **이 리포트의 모든 지표는 질의 6건에서 나온 값이다.** gold 배치1은 40건이고
> 사람이 40건 전부를 승인했지만, 정답 집합이 실제로 만들어지는 질의는 6건뿐이다.
> **40건짜리 지표로 읽으면 안 된다.**

승인 40건 중:

| | 건수 | 지표에서의 취급 |
|---|---:|---|
| 앵커가 있어 정답 집합이 생김 | **6** | Hit@1 / Hit@5 / MRR@5 의 분모 |
| `coverage=missing` (거절 경계 8건 포함) | 24 | 게이트 판정만. 검색 지표 분모에서 제외 |
| gold 청크가 파일에 기록되지 않아 채점 불가 | 10 | **평가에서 제외됨** |

10건이 빠진 경위는 `reports/gold_import_and_eval_attempt_0825.md`에 있다. 요지는
`import_gold_labels.py`가 export의 `gold_chunk_ids`를 읽기만 하고 행에 쓰지
않는다는 것이다. 이 리포트의 숫자는 **그 10건이 빠진 상태의 값**이다.

## 정본 — 코퍼스와 export가 어느 쪽인가

`data/`는 gitignore 대상이라 워크트리마다 독립이다. 이 실행의 정본은:

- **코퍼스 정본은 `.claude/worktrees/vector-rag-transition/data/processed`** (문서
  277청크 + embedding_eligible 영상 26 = 303청크). bake 지문
  `sha256:db11af7e…`와 일치하는 쪽이며, 메인 워크트리의 219청크 사본은 wayopet
  12파일이 빠진 낡은 사본이다.
- **export·gold 파일 정본은 메인 워크트리** (`dog-training-rag-retrieval/`).

파일은 옮기지 않았고 `--doc-chunks`/`--video-chunks`로 코퍼스만 가리켰다.

## 실행

```
uv run python scripts/run_combined_retrieval_eval.py \
  --doc-chunks   <워크트리>/data/processed/documents/chunks \
  --video-chunks <워크트리>/data/processed/youtube/chunks \
  --gold         <스크래치>/gold_6_baseline.jsonl \
  --metrics      <스크래치>/p1_before_metrics.json \
  --report       <스크래치>/p1_before_report.md
exit=0
```

`--gold`에 넣은 파일은 gold 배치1 40건에서 `gold_relevant_chunks()`가 예외를
던지는 10건을 뺀 30건이다. 추적 스냅샷
(`data/eval/results/combined_v4_e5_metrics.json`)은 덮어쓰지 않았다.

## 결과 — 채점 6문항

```
gold_summary: {"queries": 30, "scored_queries": 6, "refuse_only_queries": 24,
               "hit@1": 0.666667, "hit@5": 1.0, "mrr@5": 0.763889}
```

| 지표 | 값 | 분모 |
|---|---:|---:|
| Hit@1 | 0.667 | **6** |
| Hit@5 | 1.000 | **6** |
| MRR@5 | 0.764 | **6** |

### 질의별 (채점 6건 전부)

| query_id | query_type | 정답 청크 수 | 첫 정답 순위 | RR |
|---|---|---:|---:|---:|
| g004 | definition | 2 | 1 | 1.000 |
| g006 | definition | 1 | 1 | 1.000 |
| g008 | procedure | 1 | 1 | 1.000 |
| g012 | procedure | 1 | 4 | 0.250 |
| g013 | procedure | 1 | 3 | 0.333 |
| g031 | differential | 1 | 1 | 1.000 |

### 유형별 — **n을 반드시 함께 읽을 것**

| query_type | n | Hit@1 | Hit@5 | MRR@5 |
|---|---:|---:|---:|---:|
| definition | **2** | 1.000 | 1.000 | 1.000 |
| procedure | **3** | 0.333 | 1.000 | 0.528 |
| differential | **1** | 1.000 | 1.000 | 1.000 |
| situation | **0** | — | — | — |
| refuse_boundary | **0** | — | — | — |

`situation`이 0건인 것이 이 기준선의 가장 큰 구멍이다. 앞선 집계에서 벡터가
top-5를 놓친 answerable 2건이 **둘 다 `situation`** 이었는데, 그 두 건(g019,
g020)이 정확히 채점 불가 10건에 들어 있다. **이 기준선은 하이브리드 검색
질문에 아무 말도 해주지 못한다.**

`procedure` 3건 중 2건(g012 순위 4, g013 순위 3)이 top-1을 놓쳤다. n=3이다.

## `without_chunk_text()` — 산출물로 검증됨

`run_combined_retrieval_eval.py:1222–1223`에서 스냅샷 기록 경로에 적용된다.
이번에는 실행이 끝까지 갔으므로 산출물을 직접 검사했다:

```
chunk_bodies() 위반: 0건
top_k에 남은 text 필드: 0개
```

## 이번에 고친 것 — 지표를 잘못 읽게 만들던 두 가지

**1. `:743` `row["video_id"]` KeyError.** gold 스키마가 v2로 확장되며 문서도
정답이 될 수 있게 됐는데(`391e647`), 이 줄만 영상 전용 필드를 직접 인덱싱한 채
남아 있었다. 같은 함수의 `gold_relevant_chunks()`는 이미 `.get()`을 쓴다.
문서 앵커 gold 6건은 `video_id`가 없어 전부 여기서 죽었다. `.get()`으로 맞췄다.

**2. 하드코딩된 분모 3곳.** gold가 영상 12건이던 시절의 숫자가 남아 있었다.

| 위치 | 전 | 후 |
|---|---|---|
| `:1151` 리포트 | `(12문항)` | `(채점 N문항 / gold M건)` |
| `:1243` 콘솔 | `gold 12:` | `gold M건 중 채점 N문항(거절 전용 K)` |
| `:1247` 콘솔 | `owner 20:` | `owner N건` |

채점 대상이 6건인데 화면과 리포트에는 12로 찍히고 있었다. 숫자를 실제보다
넓게 읽게 만드는 종류의 오류라 같이 고쳤다.

테스트 324개 통과(스킵 7).

## 이 기준선의 한계 — 한 문단으로

표본이 6건이다. 유형별 칸은 n=1~3이라 비율이 한 건에 0.33~1.0씩 움직인다.
`situation`과 `refuse_boundary`는 채점 표본이 아예 없다. **이 값들은 P1
전후 비교의 기준점으로만 쓸 수 있고, 검색 품질의 절대 수준이나 유형 간 우열의
근거로는 쓸 수 없다.** 10건을 되살린 뒤 다시 재야 한다.
