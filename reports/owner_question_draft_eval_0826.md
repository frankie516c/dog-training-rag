# 견주 질문셋 초안 평가

315개 문서에서 구조 청크의 제목을 바탕으로 견주 질문 80개와 안전 경계 질문 4개를 생성했다. 모든 answerable 초안에는 실제 `doc_id`·`chunk_id` anchor가 붙어 있다.

초안 PGVector 결과(80개): Hit@1 0.050, Hit@5 0.0625, MRR@5 0.0531. 이 수치는 검색 품질 결론이 아니다. 제목의 상당수가 사이트 메뉴/FAQ 상위 분류라서, `"{제목} 상황에서..."` 템플릿 질문이 실제 내용과 충분히 의미적으로 맞지 않는다는 생성기 결함을 드러낸다. 80개 중 5개만 anchor 청크가 Top 5에 들어왔다.

따라서 이 초안은 자동 승인하지 않는다. `review_status=GENERATED`, `needs_human_review=true`로 저장했고, 사람이 다음을 고친 뒤에만 청킹/임베딩 A/B의 gold로 승격한다.

- 질문을 실제 견주 상황으로 재작성
- 상위 분류·내비게이션 청크 anchor 제거
- answerable/partial/missing/refuse_boundary 재판정
- 정답 청크와 필수 근거 문장 확인

초안 파일: `data/eval/queries/owner_questions_generated.jsonl`
