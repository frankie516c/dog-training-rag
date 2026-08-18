# YouTube 검색 baseline 결과

| 항목 | 값 |
|---|---|
| 모델 | `intfloat/multilingual-e5-base` |
| split | dev |
| top-k | 5 |
| 평가 질문 수 | 12 |
| corpus | chunk 29개 / eligible 20개 |

## 지표

성공 개수로 읽는 지표:

| 지표 | successful_queries / total_queries | 비율 |
|---|---|---|
| Hit@1 | 6 / 12 | 0.5 |
| Hit@3 | 9 / 12 | 0.75 |
| Hit@5 | 11 / 12 | 0.916667 |

평균으로 읽는 지표 (성공 개수가 아닙니다):

| 지표 | 정의 | 값 |
|---|---|---|
| MRR@5 | reciprocal_rank 합계 8.0 / query 12개 | 0.666667 |
| Recall@5 | query별 recall의 macro average | 0.875 |
| macro_span_recall@5 | query별 span recall의 macro average | 0.875 |

span 단위 micro count:

| 지표 | covered_spans / total_gold_spans | 비율 |
|---|---|---|
| span_coverage@5 | 11 / 13 | 0.846154 |

## split 사용 정책

- dev(12): 모델·설정 비교와 오류 분석에 사용한다.
- test(6): 최종 설정을 확정한 뒤 마지막 확인에만 사용한다.
- test 결과를 보면서 threshold, passage 구성, 모델 설정을 조정하지 않는다.

## 한계

- 영상 3개 / embedding_eligible chunk 42개만으로 측정한 smoke benchmark다.
- 이 수치는 일반적인 한국어 검색 성능을 증명하지 않는다.
- corpus가 작아 무작위 순위로도 지표가 크게 흔들린다. 절대값이 아니라 설정 간 상대 비교에만 쓴다.
- gold span은 사람이 검토한 구간이며 span에 겹치는 eligible chunk 전부를 정답으로 본다.
- 동일 환경에서의 ranking/metrics 재현성만 보장한다. CPU/GPU 또는 라이브러리 버전이 다르면 embedding score는 달라질 수 있다.
- latency는 환경 의존 값이라 결정론 검증 대상이 아니며 metrics 산출물과 분리해 기록한다.

## 질문별 결과

| query | type | split | first_relevant_rank | RR | recall@5 | span_recall@5 |
|---|---|---|---|---|---|---|
| q001 | direct_lookup | dev | 1 | 1.0 | 1.0 | 1.0 |
| q002 | direct_lookup | dev | 2 | 0.5 | 1.0 | 1.0 |
| q003 | direct_lookup | dev | 2 | 0.5 | 1.0 | 1.0 |
| q004 | paraphrase | dev | 2 | 0.5 | 1.0 | 1.0 |
| q005 | paraphrase | dev | 1 | 1.0 | 1.0 | 1.0 |
| q006 | paraphrase | dev | 4 | 0.25 | 1.0 | 1.0 |
| q007 | symptom_to_solution | dev | 1 | 1.0 | 1.0 | 1.0 |
| q008 | symptom_to_solution | dev | - | 0.0 | 0.0 | 0.0 |
| q009 | symptom_to_solution | dev | 1 | 1.0 | 1.0 | 1.0 |
| q010 | concept | dev | 4 | 0.25 | 1.0 | 1.0 |
| q011 | concept | dev | 1 | 1.0 | 1.0 | 1.0 |
| q012 | multi_span | dev | 1 | 1.0 | 0.5 | 0.5 |
