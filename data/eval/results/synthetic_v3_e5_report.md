# YouTube 검색 baseline 결과

| 항목 | 값 |
|---|---|
| 모델 | `intfloat/multilingual-e5-base` |
| split | synthetic |
| top-k | 5 |
| 평가 질문 수 | 51 |
| corpus | chunk 35개 / eligible 26개 |

## 지표

성공 개수로 읽는 지표:

| 지표 | successful_queries / total_queries | 비율 |
|---|---|---|
| Hit@1 | 25 / 51 | 0.490196 |
| Hit@3 | 36 / 51 | 0.705882 |
| Hit@5 | 40 / 51 | 0.784314 |

평균으로 읽는 지표 (성공 개수가 아닙니다):

| 지표 | 정의 | 값 |
|---|---|---|
| MRR@5 | reciprocal_rank 합계 31.016667 / query 51개 | 0.60817 |
| Recall@5 | query별 recall의 macro average | 0.784314 |
| macro_span_recall@5 | query별 span recall의 macro average | 0.784314 |

span 단위 micro count:

| 지표 | covered_spans / total_gold_spans | 비율 |
|---|---|---|
| span_coverage@5 | 40 / 51 | 0.784314 |

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
| s001 | direct_lookup | synthetic | - | 0.0 | 0.0 | 0.0 |
| s002 | paraphrase | synthetic | - | 0.0 | 0.0 | 0.0 |
| s003 | symptom_to_solution | synthetic | 5 | 0.2 | 1.0 | 1.0 |
| s004 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s005 | paraphrase | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s006 | symptom_to_solution | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s007 | direct_lookup | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s008 | paraphrase | synthetic | 3 | 0.333333 | 1.0 | 1.0 |
| s009 | symptom_to_solution | synthetic | 3 | 0.333333 | 1.0 | 1.0 |
| s010 | direct_lookup | synthetic | - | 0.0 | 0.0 | 0.0 |
| s011 | paraphrase | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s012 | symptom_to_solution | synthetic | - | 0.0 | 0.0 | 0.0 |
| s013 | direct_lookup | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s014 | paraphrase | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s015 | symptom_to_solution | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s016 | direct_lookup | synthetic | - | 0.0 | 0.0 | 0.0 |
| s017 | direct_lookup | synthetic | - | 0.0 | 0.0 | 0.0 |
| s018 | paraphrase | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s019 | symptom_to_solution | synthetic | - | 0.0 | 0.0 | 0.0 |
| s020 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s021 | paraphrase | synthetic | 5 | 0.2 | 1.0 | 1.0 |
| s022 | symptom_to_solution | synthetic | 4 | 0.25 | 1.0 | 1.0 |
| s023 | direct_lookup | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s024 | paraphrase | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s025 | symptom_to_solution | synthetic | - | 0.0 | 0.0 | 0.0 |
| s026 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s027 | paraphrase | synthetic | - | 0.0 | 0.0 | 0.0 |
| s028 | symptom_to_solution | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s029 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s030 | paraphrase | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s031 | symptom_to_solution | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s032 | direct_lookup | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s033 | paraphrase | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s034 | symptom_to_solution | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s035 | direct_lookup | synthetic | - | 0.0 | 0.0 | 0.0 |
| s036 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s037 | paraphrase | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s038 | symptom_to_solution | synthetic | 5 | 0.2 | 1.0 | 1.0 |
| s039 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s040 | paraphrase | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s041 | symptom_to_solution | synthetic | - | 0.0 | 0.0 | 0.0 |
| s042 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s043 | paraphrase | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s044 | symptom_to_solution | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s045 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s046 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s047 | paraphrase | synthetic | 2 | 0.5 | 1.0 | 1.0 |
| s048 | symptom_to_solution | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s049 | direct_lookup | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s050 | paraphrase | synthetic | 1 | 1.0 | 1.0 | 1.0 |
| s051 | symptom_to_solution | synthetic | 1 | 1.0 | 1.0 | 1.0 |
