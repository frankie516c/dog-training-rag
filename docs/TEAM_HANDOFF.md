# 팀 저장소 이관 handoff 참고서

이 문서는 **통합 구현 계획서가 아니라 선택적 이관 참고서**입니다. 팀 저장소 구조가
확정된 뒤, 필요한 코드와 계약만 골라 가져갈 수 있도록 "지금 이 저장소에 무엇이 있고,
무엇을 그대로 가져가면 안 되며, 무엇이 아직 정해지지 않았는지"를 정리했습니다.
여기 적힌 어떤 항목도 팀 저장소의 최종 구현이나 디렉터리 구조를 확정하지 않습니다.

기준 브랜치는 `feature/graphrag-demo-sprint`입니다. 다른 브랜치와의 관계는
[`docs/BRANCH_MAP.md`](BRANCH_MAP.md)를 참고하세요.

## 현재 재사용 가능한 것

`feature/graphrag-demo-sprint`(현재 브랜치)에 실제로 구현되어 있으며, 참고 가치가
있다고 판단한 것들입니다.

- GraphRAG 엔티티 추출 (`scripts/extract_entities.py`)
- Neo4j 적재 (`scripts/load_graph_neo4j.py`)
- 2-hop 그래프 후보 확장 (`scripts/run_combined_retrieval_eval.py`의 `graph_search`/`graph_walk`)
- 벡터 단독·하이브리드 비교 runner (`scripts/run_combined_retrieval_eval.py`)
- 의료 입력·출력 가드레일 v1/v2 (`scripts/medical_guardrail.py`, `data/guardrail/*.json`)
- YouTube·문서 인제스트 (`scripts/collect_youtube_metadata.py`, `chunk_approved_youtube.py`, `ingest_documents.py` 등)
- 평가 질문과 동결 그래프 (`data/eval/`, `frozen/frozen_*_0820.json(l)`)

## 그대로 이관하면 안 되는 것

- **`run_combined_retrieval_eval.py` 전체** — 벡터 검색, 그래프 검색, 병합, 게이트,
  리포트 생성이 하나의 대형 평가 스크립트에 혼재되어 있습니다. 재사용할 부분만
  함수 단위로 분리해 가져가야 합니다.
- **`generate_answers.py` 전체** — 프롬프트 빌드, 생성 호출, 밴드 분류, CLI와
  결과 저장이 하나의 대형 실험 스크립트에 혼재되어 있습니다.
- **`score_gap` gate를 운영 정책으로 사용하는 것** — `reports/combined_corpus_coverage.md`에
  기록된 대로, 코퍼스가 83청크로 확장된 현재 owner 픽스처 20건 중 19건은 PASS,
  1건(Q10)은 REFUSE입니다. Q10은 기대값도 REFUSE라 이 결과가 평가 실패를 뜻하지는
  않습니다. 전체 20건 중 실제 top1 점수가 상승한 것은 8건이며, 나머지 12건은 top1
  상승 없이 코퍼스 평균이 낮아지며 gap만 산술적으로 커진 결과입니다. 따라서
  `score_gap`은 운영 정책이 아니라 데모·평가용 신호로만 사용합니다.
- **embedded Qdrant 구현을 팀 런타임으로 사용하는 것** — 팀 저장소는 **pgvector**를
  사용할 예정입니다. `feature/dog-training-rag`의 Qdrant 기반 검색 구현
  (`backend/app/retrieval.py`)은 이 결정과 맞지 않으므로 팀 최종 런타임의
  source of truth로 추천하지 않습니다.
- **raw chunk를 승인된 EvidenceCard처럼 사용하는 것** — GraphRAG가 반환하는 raw
  chunk(`chunk_id`)는 기존 EvidenceCard의 승인·ReviewDecision·content hash 검증
  절차를 거친 근거 단위가 아닙니다. 따라서 수동 검토 여부와 별개로, 현재
  ChatCitation의 DIRECT·SUPPORTING 근거와 동일한 계약으로 취급할 수 없습니다.
- **개인 저장소의 `/chat`을 팀 오케스트레이터 계약으로 사용하는 것** — 참고 가치는
  있지만(아래 참조), 팀 공통 계약이 되려면 팀 합의를 거쳐야 합니다.

또한 명확히 해 둘 점: **GraphRAG는 현재 `/chat` 서비스에 연결되어 있지 않습니다.**
GraphRAG(엔티티 추출, Neo4j, 하이브리드 검색)와 FastAPI `/chat` 서비스는 서로 다른
브랜치(`feature/graphrag-demo-sprint` / `feature/dog-training-rag`)에만 각각
존재하며, 이번 handoff 단계에서도 연결하지 않습니다.

## 참고용 재사용 후보 계약 (구현 위치)

아래는 `feature/dog-training-rag`에 존재하는 계약들로, 코드를 가져오지 않고
**참고 좌표만** 기록합니다. 라인 번호는 변경될 수 있어 파일 경로까지만 남깁니다.

```text
feature/dog-training-rag
- backend/app/domain/evidence.py   (EvidenceCard, SourceRegistryEntry, ReviewDecision)
- backend/app/domain/chat.py       (ChatRequest, ChatResponse, ChatCitation)
```

재사용 후보:

- EvidenceCard
- SourceRegistry
- ReviewDecision
- ChatRequest·ChatResponse·ChatCitation
- 근거 승인·검증 정책
- FastAPI 테스트 방식

재사용하지 않을 가능성이 높은 구현:

- embedded Qdrant 기반 런타임 검색
- Qdrant 전용 설정
- 개인 저장소용 `/chat` 조립 구조 전체

## 그라운드룰에 대한 안내

`docs/GROUNDRULES.md`는 이번 handoff 작업에서 수정하지 않았습니다. 그 문서는
**개인 실험 당시(각자 저장소·각자 DB로 진행하던 시기)의 규칙**을 기록한 것이며,
팀 저장소로 이관된 뒤의 현재 팀 규칙이 아닙니다. 특히 "DB: 각자 사용",
"GitHub: SAJOYO org에 각자 레포를 파서 test 작업" 항목은 팀 저장소 이관 이후에는
그대로 적용되지 않을 가능성이 높습니다. 팀 저장소의 실제 규칙이 확정되면 별도
문서(또는 `GROUNDRULES.md`의 개정)로 반영해야 합니다.

## 팀 저장소에서 새로 결정할 것

- pgvector 기반 runtime retriever
- 팀 공통 요청·응답 JSON
- GraphRAG 라우팅 여부
- GraphRAG 후보의 승인·출처 정책
- raw chunk와 EvidenceCard의 관계 — 아래 "근거 단위 관련 미결정 사항" 참고
- 팀 공통 embedding model
- Neo4j를 실제 서비스에 사용할지, 데모·실험으로만 둘지
- 모듈의 최종 디렉터리 위치 — 팀 저장소의 실제 구조가 아직 확정되지 않았으므로
  이 문서에서 구체적인 경로를 단정하지 않습니다.

### 근거 단위 관련 미결정 사항

GraphRAG(raw chunk 근거)와 서비스 실험(EvidenceCard 근거)의 근거 단위가 다르다는
문제에 대해, 아래 선택지만 기록합니다. 멘토 피드백과 팀 공통 데이터 계약이 나오기
전에는 이 중 하나를 확정하지 않습니다.

1. GraphRAG 구축 입력을 승인된 EvidenceCard로 제한
2. raw chunk를 사람 검토 후 EvidenceCard로 승격
3. raw chunk용 별도 출처·검토 계약을 설계
4. GraphRAG를 평가·데모 전용으로 유지

공통 반환 타입(`RetrievedEvidence` 등)의 구체적인 필드나 구현도 이번 handoff
단계에서는 결정하지 않습니다.

## 권장 이관 순서

1. 팀 저장소의 실제 디렉터리와 공통 API 계약 확인
2. pgvector 기반 벡터 검색 구현
3. 벡터 검색 단독 end-to-end 연결
4. 의료 가드레일 연결
5. 멘토 피드백 반영
6. GraphRAG를 별도 retriever adapter로 연결할지 결정
7. 평가셋으로 벡터 단독과 하이브리드 비교
8. 효과가 확인될 때만 운영 경로에 포함
