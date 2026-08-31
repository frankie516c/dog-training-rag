# 승인 질문셋 청킹 비교

검수된 질문 96개(승인 63개 + 재작성 대상의 anchor 보유 질문 포함)를 동일 anchor로 비교했다. 아래는 임베딩 전 후보 제거용 lexical proxy이며 PGVector 품질 수치가 아니다.

| 전략 | 청크 수 | anchor 해석 | Hit@1 | Hit@5 | MRR@5 | 중앙 rank |
|---|---:|---:|---:|---:|---:|---:|
| structure_tokens | 7,079 | 96 | 0.0208 | 0.0625 | 0.0365 | 247.5 |
| fixed_char | 21,338 | 96 | 0.0104 | 0.0208 | 0.0156 | 471.0 |
| paragraph_recursive | 37,170 | 94 | 0.0106 | 0.0213 | 0.0142 | 851.0 |
| sentence_window | 46,900 | 94 | 0.0106 | 0.0213 | 0.0160 | 954.0 |

구조 보존형이 네 후보 중 proxy 기준으로 가장 좋고, 청크 수는 가장 적다. 따라서 전체 E5 재임베딩 A/B는 `structure_tokens`와 `fixed_char` 두 후보만 우선 실행한다. 문단형·문장형은 현재 proxy에서 열세이고 비용도 커 후순위로 둔다.

현재 운영 baseline은 이미 적재된 `structure_tokens + multilingual-e5-base`이며, 승인된 63개 기준 PGVector 결과는 Hit@1 0.222, Hit@5 0.444, MRR@5 0.309이다. fixed_char의 실제 E5 수치는 별도 적재 후 측정한다.
