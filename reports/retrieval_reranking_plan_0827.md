# 검색 랭킹 오프라인 실험 계획 (2026-08-27)

## 고정 입력

- 평가 질문: `data/eval/queries/training_api_eval_v1.jsonl` (25건, 변경 금지)
- gold anchor/판정: 동결 파일의 값을 그대로 사용
- 서비스 코퍼스: `config/serving_corpus_v1.json`의 14개 문서
- 임베딩: `intfloat/multilingual-e5-base`, 기존 PGVector 행만 사용
- 생성 모델/Gemma 호출: 없음

## 비교 방식

1. **Dense baseline**: 현재 런타임과 같은 E5 질의 벡터 및 PGVector dense 순위.
2. **BM25 lexical**: 동일 83개 서비스 청크에 대한 일반 토큰+문자 bigram BM25. 외부 의존성 없이 오프라인 계산.
3. **RRF**: dense top-50과 BM25 top-50의 rank reciprocal fusion(k=60) 후 top-4.
4. RRF가 부족할 경우에만 동일 후보에서 top-20/top-50 경량 재정렬을 검토하며, LLM 질의 확장은 하지 않는다.

## 채택 기준

- answerable anchor Hit@4와 MRR이 dense보다 일반적으로 개선되어야 한다.
- 기존 dense top-4 정답을 밀어내는 회귀가 없어야 한다.
- missing 두 건에서 무관 문서 점수가 악화되지 않아야 한다.
- 검색 단계 지연·메모리·의존성이 운영 가능한 수준이어야 한다.
- 일부 ID를 겨냥한 예외나 top_k 단순 증가는 허용하지 않는다.

산출물은 `data/scratch/retrieval_reranking_0827/`에 저장하고, 결과 확인 전에는 프로덕션 retriever/API를 수정하지 않는다.
