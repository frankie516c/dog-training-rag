# 그래프 검색이 벡터 검색 대비 리트리벌 성능 이득을 내는가 — 전수 실측

측정일 2026-08-24. `scripts/run_combined_retrieval_eval.py`를 `--graph-off`(벡터 단독)와
기본 실행(하이브리드)으로 각각 1회 돌려 owner_fixtures 20건 + gold 12건, 총 32개 질의
전수를 비교했다. API 키·Neo4j 연결 없이 로컬 임베딩 + `data/graph/` 로컬 파일만으로
실행했다(README 명시 사항 그대로). 산출물은 `data/scratch/`(gitignore)에만 썼고 커밋된
스냅샷(`data/eval/results/*`, 기존 `reports/*`)은 건드리지 않았다.

```
corpus: 영상 26 + 문서 57 = 83청크
graph:  노드 284 · 엣지 102 (frozen_graph 기준, 최대 2홉)
```

**이 문서는 측정과 코드 구조 확인만 담는다.** "그래프 DB를 접어야 한다"는 상위 판단은
`reports/research_graph_viability_0824/00_SYNTHESIS.md`가 이미 조건부로 내렸고, 이 문서는
그 판단이 남겨둔 유일한 공백("검색 성능 이득이 측정된 적 없다")을 메우기 위한 후속
실측이다.

## 1. 집계 지표 — 완전히 동일함

| 지표 | 벡터 단독 | 하이브리드 |
|---|---:|---:|
| gold 12 · Hit@1 | 0.666667 | 0.666667 |
| gold 12 · Hit@5 | 0.75 | 0.75 |
| gold 12 · MRR@5 | 0.708333 | 0.708333 |
| owner 20 · gate PASS | 19/20 | 19/20 |
| owner 20 · gate ↔ expected 일치 | 7/20 | 7/20 |

생성된 리포트 파일(`data/scratch/vector_only_report_0824.md`,
`data/scratch/hybrid_report_0824.md`, 31,298바이트)은 **MD5 체크섬까지 완전히 동일**하다
(`e599b4e53b382985fcaa0c4ec8b3b625`).

## 2. 질의 단위 실측 — `top_k`(순위 산정 기준)는 32/32 전수 동일

`top_k`(랭킹·Hit@k·MRR·gate·first_relevant_rank 계산에 쓰이는 벡터 순위 리스트)를
직접 비교하면 **32개 질의 전부 chunk_id 순서까지 완전히 동일**했다.

| 구분 | 그래프 시드 매칭(비어있지 않음) | evidence_chunk_ids 변화 | top_k/gate/rank 변화 |
|---|---:|---:|---:|
| owner_fixtures (20) | 12/20 | 11/20 | **0/20** |
| gold (12) | 5/12 | 3/12 | **0/12** |
| 합계 | 17/32 | 14/32 | **0/32** |

그래프는 17개 질의에서 실제로 후보를 찾아 `evidence_chunk_ids`에 추가했다(1건은 추가
후보가 벡터 top-5와 완전히 겹쳐 중복 제거로 순증가 0). 그러나 **이 추가가 순위·게이트·
정답 랭크에 영향을 준 사례는 정확히 0건**이다.

## 3. 왜 0건인가 — 코드 구조상 원인 (추정이 아니라 소스 확인)

`scripts/run_combined_retrieval_eval.py`를 직접 읽은 결과, 이건 표본이 작아서 우연히
0건이 나온 것이 아니라 **현재 구현에서 구조적으로 0건 외의 값이 나올 수 없다.**

```python
# hybrid_merge() 독스트링 (line 334)
"""Vector top-k first, graph chunks appended after, duplicates dropped.
No routing (both retrievers always ran) and no score normalization
(graph hits carry no score to normalize against) — order is the only
thing preserved."""

# run() 안 주석 (line 403)
# Both retrievers always run (no routing on query type); the gate decides
# only whether the graph's chunks are admitted as evidence, and it never
# sees them — score_gap above is computed from vector similarity alone.
```

`gate_verdict`·`score_gap`은 `rank_one()`이 반환하는 벡터 유사도 `ranked`만으로
계산되고, `search_graph()` 결과는 그 뒤에 `hybrid_merge(ranked, graph_chunks)`로
**항상 벡터 순위 리스트 뒤에 이어붙기만** 한다. gold 세트의 `first_relevant_rank`·
`reciprocal_rank`도 동일하게 `ranked`(벡터 전용)만으로 계산된다(`enumerate(ranked, ...)`).
즉 `graph_chunks`가 `top_k`·게이트·정답 랭크에 반영될 경로 자체가 코드에 없다 —
README가 이미 "게이트 판정은 벡터 score_gap만으로 내리고, 그래프 결과는 판정에 관여하지
않습니다"라고 적어 둔 것과 정확히 일치한다.

**따름정리**: 이 스크립트가 보고하는 Hit@1/Hit@5/MRR@5/gate/first_relevant_rank로는,
코퍼스나 질의 셋을 무엇으로 바꿔도 하이브리드가 벡터 단독과 다른 값을 낼 수 없다.
"그래프가 검색 성능을 개선하는지"를 이 지표들로 다시 재는 것은 재측정이 아니라 같은
결과를 반복 확인하는 것에 불과하다.

## 4. 2026-08-20 리포트와의 정합성 — "그래프가 도움됐다"는 주장은 다른 층위였다

`reports/retrieval_gap_hybrid_vs_vector_0820.md`(Q12·Q13·Q14·Q15)는 이번 실측과
**모순되지 않는다.** 그 문서도 게이트는 두 조건 모두 PASS/PASS로 동일하다고 이미
적어 두었다(§요약 표). 그 문서가 "하이브리드가 낫다"고 말한 근거는 랭킹 지표가
아니라, **그래프가 6번째 이후 자리에 추가한 청크를 사람(LLM)이 읽고 더 나은 생성
답변을 작성했다는 정성적 비교**였다(Q12·Q13의 "생성 응답 — 하이브리드" 절). 즉:

| 층위 | 측정 방법 | 결과 |
|---|---|---|
| 검색 랭킹(top_k·Hit@k·MRR·gate) | `run_combined_retrieval_eval.py` 자동 지표 | **32/32 동일 — 이득 0건** (이번 실측) |
| 생성 답변 품질 | 그래프 추가 청크를 읽은 LLM 답변 사람 비교 | Q12·Q13에서 개선 관찰(0820 리포트, 4건 중 2건, 수동 1회성) |

두 층위는 이 코드베이스에서 **완전히 분리**되어 있다(`docs/agenda_0825.md` #11 —
`generate_answers.py`는 애초에 그래프 검색을 하지 않는 별도 경로). 이번 실측은 첫 번째
층위(검색 랭킹)만 전수 조사했고, 두 번째 층위(생성 품질)는 범위 밖이다 — 재현
가능한 자동 측정이 아니라 0820 리포트처럼 매 질의 사람이 읽고 판단해야 하는 작업이고,
실 API 호출(`generate_answers.py`)이 필요해 이번 지시 범위(랭킹 성능)를 벗어난다.

## 5. 한계

- **평가 코퍼스가 작다**: 83청크(영상26+문서57)로, 전체 크롤 풀(821문서)이나 그래프
  추출 엔티티 수(282~360)에 비해 훨씬 작은 부분집합이다. 이 결과가 코퍼스가 커진
  뒤에도 유지되는지는 확인하지 않았다.
- **`score_gap` 게이트 자체가 이미 판별력을 잃은 상태**로 알려져 있다(`docs/agenda_0825.md`
  #1, `docs/TEAM_HANDOFF.md` — "gate는 데모·평가용 신호일 뿐 운영 정책 아님"). owner
  20건 중 19건이 PASS인 것 자체가 게이트의 한계이지 이번 측정의 오류는 아니다.
- **생성 품질(4절)은 이번에 재측정하지 않았다** — 0820 리포트의 2/4 개선 관찰이 32개
  전체 질의에서 재현되는지는 미확인이다.
- **그래프 시드 매칭이 문자열 리터럴 매칭이라는 점**(`docs/agenda_0825.md` #6)이 17/32
  발화율의 상한을 이미 제한하고 있을 수 있다 — 시드가 더 잘 잡혔다면 evidence는
  늘었겠지만, 그래도 3절의 구조적 이유 때문에 `top_k`/게이트/랭크에는 영향이 없다.

## 6. 결론 — 강한 확신

**현재 구현·현재 평가 지표 정의 기준으로, 그래프 검색이 벡터 검색 대비 리트리벌 성능
(Hit@1/Hit@5/MRR@5/gate/정답 랭크)을 개선한다는 근거는 없다 — 32개 질의 전수에서 개선
0건이며, 이는 표본 문제가 아니라 `hybrid_merge`가 그래프 후보를 벡터 순위 뒤에만
이어붙고 지표 계산이 벡터 순위만 참조하는 코드 구조상 필연적 결과다(강한 확신).**

다만 이것이 "그래프 DB를 접어라"는 결론까지 자동으로 확정하지는 않는다 — (1) 이
스크립트의 지표 정의 자체가 그래프에 불리하게 설계되어 있어(재순위 없이 부착만),
그래프가 실제로 기여할 수 있는 유일한 경로인 생성 품질 축은 이번에 측정하지 않았고,
(2) 평가 코퍼스가 83청크로 작다. `00_SYNTHESIS.md`가 조건부로 남겨둔 "검색 성능 축"
질문에 대해 이 문서는 "현재 정의된 랭킹 지표로는 이득 없음(강한 확신)"이라고 답하지만,
"그래프가 어떤 식으로도 가치가 없다"까지는 답하지 않는다 — 그러려면 재순위 방식의
하이브리드 설계(그래프 후보에 점수를 부여해 벡터 후보와 경쟁시키는 방식)나 생성 품질의
전수 재측정이 별도로 필요하다.

## 다음 실측 후보 (이번에 하지 않음)

1. 그래프 후보에 점수를 부여해 벡터 후보와 병합 랭킹시키는 대안 설계로 재측정 —
   현재 설계(부착만)가 아니라 재순위 설계에서도 이득이 없는지 확인.
2. 생성 품질 축 32개 전수 재현 — `generate_answers.py`와 그래프 검색을 잇는 정식
   경로가 없다는 기존 한계(agenda #11)가 선행 조건.
3. 코퍼스를 821문서 전체로 확장한 뒤 재측정 — 83청크에서 안 보이는 효과가 스케일에서
   나타나는지 확인.
