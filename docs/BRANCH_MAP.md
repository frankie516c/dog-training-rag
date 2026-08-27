# 브랜치 지도

이 문서는 저장소에 존재하는 브랜치들의 **역할과 포함 관계**를 설명합니다. 어떤 브랜치를
삭제하거나 정리해야 한다는 계획서가 아닙니다. 팀 저장소로 이관하기 전, 각 브랜치가
무엇을 담고 있고 다른 브랜치와 어떤 관계인지 파악하기 위해 작성했습니다.

갱신 시점(2026-08-24) 기준이며, `git merge-base`, `git merge-base --is-ancestor`,
`git rev-list --left-right --count`, `git rev-parse`로 직접 검증한 결과만 담았습니다.
2026-08-21 작성된 초판 이후 브랜치 정리가 있었고, 아래는 그 결과를 반영한 갱신판입니다
— 무엇이 바뀌었는지는 [갱신 이력](#갱신-이력)을 참고하세요.

## main — 유일한 현재 기준 브랜치

이전 버전의 `feature/graphrag-demo-sprint`(최신 하이브리드 RAG 실험)와
`feature/retrieval-evaluation-baseline`(벡터 검색 기준선)은 둘 다 main으로 병합된 뒤
원본 브랜치가 삭제됐습니다. 지금은 별도로 추적할 "핵심 실험 브랜치"가 없고, main이
GraphRAG 폐기·벡터RAG 전환을 포함한 전체 이력을 담은 유일한 브랜치입니다.

## archive/\* — 팀 이관 범위 밖, main에 병합되지 않은 채 보관 중

GraphRAG 폐기 결정(`docs/decision_graphrag_abandoned_0824.md`) 이전, 아직 GraphRAG
노선 위에서 나온 실험들입니다. main과 diverged 상태이며 병합할 계획이 없어
`archive/` 아래로 이름을 옮겨 죽은 브랜치라는 걸 표시해뒀습니다. 커밋 자체는
삭제하지 않았습니다.

| 브랜치 | 역할 | 비고 |
|---|---|---|
| `archive/feature/dog-training-rag` | EvidenceCard·FastAPI `/chat` 서비스 실험 | 팀 이관 시 계약만 선택적으로 재사용 |
| `archive/feature/evidence-response-plans` | dog-training-rag와 완전히 동일 커밋 | 중복 포인터, 별도 확인 불필요 |
| `archive/feature/grounded-rag-v1` | dog-training-rag의 직계 조상 (2커밋 차이) | dog-training-rag만 보면 충분 |
| `archive/feature/chat-ui` | dog-training-rag 위에 얹은 Next.js 프론트엔드 실험 | `frontend/` 아래 16개 파일, 약 7,285줄 추가 (`git diff --stat` 확인) |
| `archive/experiment/grounded-prompt-v0` | 근거 기반 프롬프트 실험 v0 | main·dog-training-rag 어느 쪽에도 흡수되지 않은 독립 분기 |
| `archive/experiment/grounded-prompt-v1-1` | 근거 기반 프롬프트 실험 v1.1 | 위와 동일 |
| `archive/experiment/grounded-prompt-v1-2` | 근거 기반 프롬프트 실험 v1.2 (실패 기록) | 위와 동일 |
| `archive/data/bodeumtv-feasibility-audit` | 보듬TV 수집 타당성 감사 기록 | 위와 동일 |
| `archive/data/evidence-seed-v0` | 검토된 근거 시드 v0 | 위와 동일 |
| `archive/data/source-audit` | 잠정 소스 감사 | 위와 동일 |
| `archive/data/training-coverage-gap` | 훈련 커버리지 갭 감사 | 위와 동일 |

### 검증 근거

- `archive/feature/evidence-response-plans` = `archive/feature/dog-training-rag`: `git rev-parse` 결과 두 브랜치 모두 동일 커밋(`3fec832`)을 가리킴
- `archive/feature/grounded-rag-v1`: `git rev-list --left-right --count`로 dog-training-rag 계열의 직계 조상임을 확인 (2커밋 차이)
- `archive/feature/chat-ui`는 dog-training-rag를 머지한 뒤 그 위에 `frontend/app`, `frontend/components/chat.tsx`, `frontend/lib/chat-client.ts` 등 완전한 Next.js 프론트엔드를 추가한 브랜치. 팀 프론트엔드는 별도로 개발되므로 이관 범위에서 제외
- 나머지 7개(`grounded-prompt-v0/v1-1/v1-2`, `data/*` 4개)는 초판(2026-08-21) 작성 시 `main`, `feature/graphrag-demo-sprint`, `feature/dog-training-rag` 세 브랜치 각각과 `git merge-base --is-ancestor`, `git rev-list --left-right --count`로 확인 — 어느 쪽의 조상도 아니며(`is-ancestor` 전부 거짓), 세 조합 모두 diverged. 즉 GraphRAG 계열에도 dog-training-rag 계열에도 흡수되지 않은, 각자 독립된 시점에서 분기한 별도 보존 기록. main이 이후 진행되긴 했지만 이 결론에 영향을 주는 조상 관계는 아니므로 재검증하지 않았음

## 완전히 삭제된 브랜치 (main에 흡수 확인 후 정리, 2026-08-24)

아래는 `git merge-base --is-ancestor origin/<branch> origin/main`으로 main의 조상임을
확인한 뒤 로컬·원격에서 삭제한 브랜치입니다. 커밋은 main 이력 안에 그대로 남아있고,
브랜치 포인터만 없앴습니다.

- `chore/team-repo-handoff`
- `data/breed-conditionality-factcheck`
- `docs/youtube-caption-troubleshooting`
- `experiment/growing-pixel-room-v7`
- `experiment/main-screen-character-mockups`
- `feature/graphrag-demo-sprint`
- `feature/retrieval-evaluation-baseline`
- `feature/youtube-caption-ingestion`
- `feature/youtube-chapter-chunking`
- `feature/youtube-metadata-catalog`

## RAG와 무관한 활성 브랜치

이 문서가 다루는 GraphRAG/벡터RAG 계열과 무관한, 메인 화면 UI(픽셀 룸) 실험용
활성 브랜치입니다. 위 표들의 포함 관계 분석 대상이 아닙니다.

- `experiment/simple-cute-pixel-room-v8`
- `feature/modular-room-collision-dogs`
- `worktree-vector-rag-transition`

## 갱신 이력

- **2026-08-24**: `feature/graphrag-demo-sprint`, `feature/retrieval-evaluation-baseline`을
  main 병합 확인 후 삭제. 나머지 GraphRAG 이전 실험 7개 + `dog-training-rag` 계열
  4개(`dog-training-rag`, `evidence-response-plans`, `grounded-rag-v1`, `chat-ui`)를
  `archive/` 네임스페이스로 이동. 완전히 병합된 브랜치 10개(위 목록)를 로컬·원격에서
  삭제.
- **2026-08-21**: 초판 작성.

## 갱신 원칙

브랜치가 새로 생기거나 병합·정리되면 이 문서도 함께 갱신합니다. 표의 각 관계는
날짜가 지나면 stale해질 수 있으므로, 이 문서를 근거로 실제 작업을 하기 전에는
`git merge-base`/`git rev-list --left-right --count`로 다시 확인하는 것을 권장합니다.
