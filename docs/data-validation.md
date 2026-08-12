# Evidence JSONL 로딩과 검증

체크포인트 4는 다음 세 경로를 MVP의 추적 가능한 UTF-8 JSONL 저장 위치로 고정한다. 각 줄에는 해당 Pydantic 객체 하나를 JSON으로 직렬화한다.

```text
data/sources/source_registry.jsonl          SourceRegistryEntry
data/processed/evidence_cards.jsonl         EvidenceCard
data/reviews/review_decisions.jsonl         ReviewDecision
```

실제 데이터 파일은 이 체크포인트에서 만들지 않는다. 위 파일만 Git 추적이 가능하며 `data/research/`, `data/raw/`, `data/cache/`, `data/qdrant/`와 다른 다운로드·원문·대량 추출물은 계속 제외한다.

## 검증 CLI

기본 경로를 검사한다.

```powershell
uv run python -m backend.app.data_validation
```

테스트나 별도 작업 복사본은 명시적으로 경로를 바꿀 수 있다.

```powershell
uv run python -m backend.app.data_validation `
  --source-registry <source_registry.jsonl> `
  --evidence-cards <evidence_cards.jsonl> `
  --review-decisions <review_decisions.jsonl>
```

CLI는 전체 source, card, decision 수와 RAG 사용 가능 카드, 미승인, 거절, 재사용 차단, invalid 수를 출력한다. JSON 또는 스키마 오류에는 파일과 줄 번호가 포함되며 종료 코드는 1이다.

## RAG eligibility

카드는 다음 조건을 모두 만족할 때만 RAG 후보로 반환된다.

1. 모든 `source_id`가 registry에 존재한다.
2. 현재 canonical content hash에 결합된 `APPROVED` 결정이 있고 `REJECTED` 결정이 없다.
3. `DIRECT` 또는 `SUPPORTING`으로 사용된 모든 출처에 `rag_use` assessment가 있다.
4. 각 `rag_use` 상태가 `permitted` 또는 `permitted_with_conditions`이다.

미승인과 거절, `rag_use`의 `unknown`·`prohibited`·누락은 오류로 승인하지 않고 제외 집계한다. 조건부 허용의 조건과 note는 eligible 결과의 `rag_use_conditions`에 source ID와 함께 보존한다. Approval과 rejection 충돌, 현재 카드와 decision hash 불일치, 참조 무결성 위반은 데이터 오류다. 로더는 approval을 생성하지 않는다.
