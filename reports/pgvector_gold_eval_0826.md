# PGVector 검색 평가 (2026-08-26)

기존 승인 gold 40건(평가 대상 answerable/partial 16건)을 새 PGVector에 실행했다. 결과는 Hit@1/5/MRR 모두 0이지만, 이는 검색기가 실패했다는 뜻이 아니다.

16건 전부 gold anchor의 `doc_id`가 현재 새 수집 코퍼스(315개 문서)에 존재하지 않았다. 기존 gold는 과거 영상·수동 문서 코퍼스용이고, 이번 적재는 국립축산과학원·EPIS·Europe PMC 등 신규 수집본이다. 따라서 평가 가능한 행은 0건이다.

다음 조치:

1. 새 코퍼스에서 견주 질문을 다시 샘플링한다.
2. 질문마다 관련 문서·청크 anchor와 기대 거절 여부를 사람 또는 검수 에이전트가 붙인다.
3. 동일 질문셋으로 chunking/embedding/PGVector 검색을 비교한다.

평가 산출물은 `data/scratch/pgvector_gold_eval.json`이다. 평가 가능한 anchor가 생기기 전까지 숫자 0을 검색 품질 지표로 사용하지 않는다.
