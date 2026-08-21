# 브랜치 지도

이 문서는 저장소에 존재하는 브랜치들의 **역할과 포함 관계**를 설명합니다. 어떤 브랜치를
삭제하거나 정리해야 한다는 계획서가 아닙니다. 팀 저장소로 이관하기 전, 각 브랜치가
무엇을 담고 있고 다른 브랜치와 어떤 관계인지 파악하기 위해 작성했습니다.

작성 시점(2026-08-21) 기준이며, `git merge-base`, `git merge-base --is-ancestor`,
`git rev-list --left-right --count`, `git diff --stat`으로 직접 검증한 결과만 담았습니다.

## 핵심 6개 브랜치

| 브랜치 | 역할 | 현재 상태 | 최신 브랜치 포함 여부 | 팀 이관 시 처리 |
|---|---|---|---|---|
| `main` | 초기 YouTube 수집 기준 | 과거 기준 | GraphRAG 브랜치에 포함 | 직접 이관하지 않음 |
| `feature/retrieval-evaluation-baseline` | 벡터 검색 기준선 | 완료 | GraphRAG 브랜치에 포함 | 별도 병합 불필요 |
| `feature/graphrag-demo-sprint` | 최신 하이브리드 RAG 실험 | 현재 기준 | 해당 없음 | 검색·그래프 기준 |
| `feature/dog-training-rag` | EvidenceCard·FastAPI 서비스 실험 | 별도 분기 | 미포함 | 계약만 선택 재사용 |
| `feature/evidence-response-plans` | dog-training-rag와 동일 | 중복 포인터 | 미포함 | 별도 이관 불필요 |
| `feature/grounded-rag-v1` | dog-training-rag의 조상 | 과거 기준 | dog-training-rag에 포함 | 별도 이관 불필요 |

### 검증 근거

- `main`과 `feature/graphrag-demo-sprint`: `git rev-list --left-right --count origin/main...origin/feature/graphrag-demo-sprint` → `0  48` (graphrag-demo-sprint가 main의 선형 연장, main 쪽에만 있는 커밋 없음)
- `feature/retrieval-evaluation-baseline`: `git merge-base --is-ancestor origin/feature/retrieval-evaluation-baseline origin/feature/graphrag-demo-sprint` → 참. `git rev-list --left-right --count origin/main...origin/feature/retrieval-evaluation-baseline` → `0  13` (main의 직계 후손이자 graphrag-demo-sprint의 조상)
- `feature/evidence-response-plans` = `feature/dog-training-rag`: `git rev-parse` 결과 두 브랜치 모두 동일 커밋(`3fec832`)을 가리킴
- `feature/grounded-rag-v1`: `git rev-list --left-right --count origin/feature/grounded-rag-v1...origin/feature/dog-training-rag` → `0  2` (dog-training-rag의 직계 조상, 2커밋 차이)
- `feature/dog-training-rag`와 `feature/graphrag-demo-sprint`: `git rev-list --left-right --count origin/feature/dog-training-rag...origin/feature/graphrag-demo-sprint` → `17  61`, merge-base `9aa2828`("chore: use Python 3.12", main의 조상) — 두 브랜치는 diverged 상태이며 하나가 다른 하나를 포함하지 않음

## 이번 이관 범위에서 제외한 브랜치

| 브랜치 | 역할 | 현재 상태 | 최신 브랜치 포함 여부 | 팀 이관 시 처리 |
|---|---|---|---|---|
| `feature/chat-ui` | 개인 Chat UI 실험 (Next.js) | 별도 분기 | 미포함 | 이번 범위 제외 |

`feature/chat-ui`는 `feature/dog-training-rag`를 머지한 뒤 그 위에 완전한 Next.js
프론트엔드(`frontend/app`, `frontend/components/chat.tsx`, `frontend/lib/chat-client.ts` 등)를
추가한 브랜치입니다. `git diff --stat origin/feature/dog-training-rag origin/feature/chat-ui`로
확인한 결과 `frontend/` 아래 16개 파일, 약 7,285줄이 추가되어 있습니다. 팀 프론트엔드는
별도로 개발되므로 이번 AI/RAG 이관 범위에서 제외하고, 존재 여부만 이 문서에 기록합니다.

## 별도 실험·감사 기록 브랜치

아래 브랜치들은 `main`, `feature/graphrag-demo-sprint`, `feature/dog-training-rag`
세 브랜치 중 어디에도 포함되지 않는, **별도로 보존된 실험·감사 기록**입니다.
불필요하거나 삭제해도 되는 브랜치라는 뜻이 아니며, 이번 handoff 범위에서 다루지
않는다는 것만 표시합니다.

| 브랜치 | 성격 (커밋 메시지 기준) |
|---|---|
| `data/bodeumtv-feasibility-audit` | 보듬TV 수집 타당성 감사 기록 |
| `data/evidence-seed-v0` | 검토된 근거 시드 v0 |
| `data/source-audit` | 잠정 소스 감사 |
| `data/training-coverage-gap` | 훈련 커버리지 갭 감사 |
| `experiment/grounded-prompt-v0` | 근거 기반 프롬프트 실험 v0 |
| `experiment/grounded-prompt-v1-1` | 근거 기반 프롬프트 실험 v1.1 |
| `experiment/grounded-prompt-v1-2` | 근거 기반 프롬프트 실험 v1.2 (실패 기록) |

### 검증 근거

이전 버전은 `main`의 조상이 아니라는 확인만으로 이 7개 브랜치를 "독립"이라고
표시했습니다. 하지만 `main`의 조상이 아니라는 사실만으로는 GraphRAG나
dog-training-rag 계열에 흡수됐을 가능성을 배제하지 못하므로, 세 핵심 브랜치
(`main`, `feature/graphrag-demo-sprint`, `feature/dog-training-rag`) 각각과
`git merge-base --is-ancestor`, `git rev-list --left-right --count`로 다시
확인했습니다.

7개 브랜치 모두 세 핵심 브랜치 중 어느 쪽의 조상도 아니며(`is-ancestor` 전부
거짓), 세 조합 모두에서 `rev-list --left-right --count`의 양쪽 값이 모두
0보다 커서(diverged) 어느 핵심 브랜치에도 포함되지 않습니다. 즉 GraphRAG 계열에
흡수된 것도, dog-training-rag 계열에 포함된 것도 아닌, 각자 독립된 시점에서
분기한 별도 보존 기록입니다. 정리 여부는 이 문서의 판단 범위 밖입니다.

## main에 이미 흡수된 브랜치

아래 브랜치들은 `git merge-base --is-ancestor origin/<branch> origin/main` 확인 결과
모두 `main`의 조상이며, 이미 `main` → `feature/graphrag-demo-sprint` 계열에 포함돼
있습니다.

- `docs/youtube-caption-troubleshooting`
- `feature/youtube-caption-ingestion`
- `feature/youtube-chapter-chunking`
- `feature/youtube-metadata-catalog`

## 갱신 원칙

브랜치가 새로 생기거나 병합·정리되면 이 문서도 함께 갱신합니다. 표의 각 관계는
날짜가 지나면 stale해질 수 있으므로, 이 문서를 근거로 실제 작업을 하기 전에는
`git merge-base`/`git rev-list --left-right --count`로 다시 확인하는 것을 권장합니다.
