# dog-training-rag

개인 GraphRAG/RAG 실험 저장소입니다. 강아지 훈련·행동 질문에 답하기 위해 YouTube
훈련 영상·문서 코퍼스를 대상으로 벡터 검색과 GraphRAG 하이브리드 검색을 비교하고,
근거 기반(grounded) 답변 생성과 의료 경계 가드레일을 평가합니다.

여기 적힌 스택과 구조는 이 저장소의 실험 선택이며, 팀 저장소의 확정된 런타임
구조가 아닙니다.

## 2026-08-24 — GraphRAG 폐기, 벡터RAG 단독으로 전환

**그래프 검색(엔티티/관계 추출, Neo4j 적재, 벡터+그래프 하이브리드)을 폐기했다.**
앞으로는 벡터 검색 단독(`--graph-off` 경로)으로 간다. 이 문서의 "검색 구조"·
"현재 브랜치 기술 구성" 절에 남아 있는 그래프 관련 서술은 **폐기 전 구현 기록**이며
현재 방향이 아니다. 결정 경위와 실측 근거(하이브리드가 벡터 대비 랭킹 지표 개선
0건, 코퍼스가 실질 저자 2명뿐이라 절차/연령대 등 대안 축도 재현 불가)는
[`docs/decision_graphrag_abandoned_0824.md`](docs/decision_graphrag_abandoned_0824.md)를,
그 앞의 축별 개별 조사는
[`reports/research_graph_viability_0824/`](reports/research_graph_viability_0824/)와
[`docs/decision_env_axis_discarded_0824.md`](docs/decision_env_axis_discarded_0824.md)를
참고하라. 그래프 관련 코드·frozen 스냅샷은 삭제하지 않고 그대로 남겨 뒀다 —
이 저장소의 실측 과정 자체가 방법론적 증거이기 때문이다.

## 현재 상태

현재 브랜치(`feature/graphrag-demo-sprint` 계열)에 실제로 구현된 범위는 다음과
같습니다.

- YouTube 메타데이터 후보 수집과 수동 검토 ledger (`scripts/collect_youtube_metadata.py`, `data/reviews/`)
- 승인된 자막 수집·정규화·챕터 기반 청킹 (`scripts/collect_approved_youtube_captions.py`, `scripts/normalize_youtube_vtt.py`, `scripts/chunk_approved_youtube.py`)
- 외부 문서 인제스트, 로그인·유료 구간 URL 차단 (`scripts/ingest_documents.py`)
- 벡터 검색 평가 기준선 (`scripts/evaluate_youtube_retrieval.py`)
- LLM 기반 엔티티·관계 추출 (`scripts/extract_entities.py`)
- Neo4j 적재 (`scripts/load_graph_neo4j.py`)
- 벡터+그래프 하이브리드 후보 병합 (`scripts/run_combined_retrieval_eval.py`)
- 근거 기반 답변 생성 실험 (`scripts/generate_answers.py`)
- 의료 입력·출력 가드레일 v1/v2 (`scripts/medical_guardrail.py`)
- 평가 질문·결과·동결 그래프 스냅샷 (`data/eval/`, `frozen/`)

FastAPI `/chat` 서비스, EvidenceCard 근거 계약, Next.js 채팅 UI는 이 브랜치에
없습니다. 다른 브랜치에 있는 별도 실험이며, [관련 실험 브랜치](#관련-실험-브랜치)를
참고하세요.

## 검색 구조

**아래는 2026-08-24 폐기 전 구현 기록이다.** 그래프·하이브리드 절은 현재
사용하지 않는다(위 "GraphRAG 폐기" 절 참고). 벡터 검색만 현재 경로다.

- **벡터 검색**: 질문과 코퍼스 청크(영상+문서)의 임베딩 유사도로 후보를 검색합니다.
- **그래프 검색**: 질문 문자열에 리터럴로 매칭된 엔티티에서 최대 2-hop까지 후보를
  확장합니다. Neo4j에 연결하지 않고 `data/graph/` 아래의 추출 결과 파일을 직접
  읽습니다.
- **하이브리드**: 벡터 후보 뒤에 그래프 후보를 추가하고 청크 단위로 중복을
  제거합니다. 게이트 판정(PASS/REFUSE)은 벡터 `score_gap`만으로 내리고, 그래프
  결과는 판정에 관여하지 않습니다.
- **답변 생성**: 병합된 근거 후보를 LLM이 읽고 답변을 작성합니다.

알려진 한계:

- `score_gap` 게이트는 코퍼스가 커지면서 판별력이 흔들린 사례가 있어 운영
  정책으로 확정하지 않았습니다.
- GraphRAG는 현재 데모·평가 단계이며 FastAPI `/chat`과 연결되어 있지 않습니다.
- GraphRAG가 반환하는 raw chunk와 EvidenceCard의 근거 계약은 아직 통합되지
  않았습니다.

설계 결정과 근거는 [`docs/graph_hybrid_retrieval_design.md`](docs/graph_hybrid_retrieval_design.md),
이관 시 재사용 판단은 [`docs/TEAM_HANDOFF.md`](docs/TEAM_HANDOFF.md)를 참고하세요.

## 현재 브랜치 기술 구성

| 구분 | 선택 | 비고 |
|---|---|---|
| 언어 | Python 3.12 | `pyproject.toml`의 `requires-python` |
| 패키지 관리 | uv | `pip install` 직접 사용 금지 |
| 임베딩 | sentence-transformers, `intfloat/multilingual-e5-base` | 로컬 실행 |
| 생성 | OpenAI API | `scripts/extract_entities.py`, `scripts/generate_answers.py`에서 사용 |
| 그래프 DB | Neo4j | `scripts/load_graph_neo4j.py`. 검색 평가 자체는 Neo4j 없이 로컬 파일로 동작 |
| 수집 | yt-dlp | YouTube 자막·메타데이터 수집 |
| 자막 파싱 | webvtt-py | VTT 정규화 |

`google-genai`는 `pyproject.toml`에 있지만 `scripts/`, `tests/` 어디에서도
import되지 않는, 현재 실행 경로에서 쓰이지 않는 정리 후보 의존성입니다.

Qdrant, FastAPI, Next.js, `bge-m3`, `faster-whisper`는 이 브랜치의 실행 경로에
없습니다 — 다른 브랜치의 선택이거나(`docs/GROUNDRULES.md`) 아직 구현되지 않은
계획입니다.

## 저장소 구조

```
scripts/      수집·청킹·추출·검색·생성·평가 CLI
data/         추적 허용된 평가셋·가드레일 어휘·수동 검토 ledger·데모 프로필
docs/         설계 결정, 소스 지도, 브랜치·handoff 문서
frozen/       재추출하면 동일하게 재현되지 않는 그래프 동결 스냅샷
reports/      평가·실패 분석 리포트
tests/        파이프라인·가드레일 unittest
prompts/      엔티티 추출 프롬프트 초안
guardrail/    초기 가드레일 시드 어휘
```

`data/`의 나머지(수집된 원본 영상·자막·오디오, 처리된 청크, 그래프 추출 중간
산출물 등)는 저장소에 커밋하지 않습니다. 아래 [데이터와 비밀정보 정책](#데이터와-비밀정보-정책)을
참고하세요.

## 빠른 시작

```powershell
uv sync
```

### 설치 확인 (부작용 없음)

API 키·Neo4j 연결·로컬 데이터 없이 실행되고, tracked 파일을 건드리지 않습니다.
처음 clone했다면 이것부터 실행해 설치가 됐는지 확인하세요.

```powershell
uv run python scripts/extract_entities.py --stage 2 --dry-run --limit 2
uv run python scripts/load_graph_neo4j.py --dry-run
uv run python -m unittest discover -s tests -p "test_*.py"
```

### 검색 평가 시험 실행

`scripts/run_combined_retrieval_eval.py`를 옵션 없이 실행하면 기본 출력 경로가
`data/eval/results/`, `reports/` 아래 커밋된 스냅샷이라 그대로 덮어씁니다. 처음
시험할 때는 `--metrics`/`--report`로 `.gitignore`가 이미 제외하는 로컬 경로
(`data/scratch/`)를 지정하세요. 둘 다 API 키·Neo4j 연결이 필요 없습니다 — 하이브리드
모드도 그래프를 `data/graph/`의 로컬 파일로만 읽습니다.

```powershell
# 벡터 전용
uv run python scripts/run_combined_retrieval_eval.py --graph-off --metrics data/scratch/metrics.json --report data/scratch/report.md

# 벡터+그래프 하이브리드 (기본값)
uv run python scripts/run_combined_retrieval_eval.py --metrics data/scratch/metrics.json --report data/scratch/report.md
```

커밋된 스냅샷을 실제로 갱신하려는 것이라면 `--metrics`/`--report` 없이 기본
경로로 실행해 덮어쓴 뒤 `git diff`로 변경을 검토하세요.

### 답변 생성 시험 실행

`--dry-run`은 API를 호출하지 않지만 기본 출력 경로(`data/eval/generation/`)는
tracked 패턴(`answers_*.jsonl`)과 겹칠 수 있어, `--out-dir`로 로컬 경로를
지정하세요.

```powershell
uv run python scripts/generate_answers.py --dry-run --out-dir data/scratch/gen
```

실제로 API를 호출하려면 `--dry-run` 없이 실행하고, `.env`에 `OPENAI_API_KEY`가
있어야 합니다 (`.env.example` 참고).

### 로컬 데이터 생성 단계 (dry-run 없음)

아래 두 명령은 이전 단계가 만든 로컬 `data/` 산출물을 입력·출력으로 쓰고,
dry-run 옵션이 없습니다. 저장소를 새로 clone한 상태에서는 이 순서대로 실행해야
이후 단계에 쓸 로컬 데이터가 생깁니다.

```powershell
# YouTube 메타데이터 수집 (제한 수집) — .env에 YOUTUBE_API_KEY 필요
uv run python scripts/collect_youtube_metadata.py --max-videos 20

# 승인된 자막을 챕터 기준으로 청킹 — 로컬 검토 ledger·전사 결과 필요
uv run python scripts/chunk_approved_youtube.py
```

## 데이터와 비밀정보 정책

사용한 자료와 출처 목록은 [`docs/SOURCES.md`](docs/SOURCES.md)에서 확인할 수
있습니다.

Git에 올리지 않는 것 (`.gitignore` 기준):

- 원본 영상·오디오·자막, 일반 수집 데이터
- 처리된 청크, 그래프 추출 중간 산출물
- 벡터 인덱스·임베딩 캐시
- `.env`와 API 키

의도적으로 추적하는 것:

- 평가 질문셋과 그 합성 근거 (`data/eval/queries/`)
- 이름 붙인 평가 스냅샷·리포트 (`data/eval/results/*_metrics.json`, `*_report.md`)
- 답변 생성 결과 (`data/eval/generation/answers_*.jsonl`)
- 의료 가드레일 어휘 파일 (`data/guardrail/`)
- 데모 프로필 (`data/profiles/`)
- 수동 검토 ledger (`data/reviews/bodeum_youtube_manual_reviews.csv`)
- 재추출 시 결과가 흔들리는 그래프 동결 스냅샷 (`frozen/`)

## 관련 실험 브랜치

- `feature/dog-training-rag`: EvidenceCard·FastAPI `/chat` 서비스 실험
- `feature/chat-ui`: Next.js 채팅 UI 실험

두 브랜치 모두 이 GraphRAG 기준 브랜치에 병합되지 않았습니다. 팀 이관 시 구현
전체가 아니라 필요한 계약과 코드만 선택적으로 참고합니다. 전체 브랜치 관계는
[`docs/BRANCH_MAP.md`](docs/BRANCH_MAP.md)를 참고하세요.

## 팀 이관

팀 런타임은 pgvector를 쓸 예정이며, 현재 저장소의 Qdrant 기반 서비스 실험이나
GraphRAG 평가 스크립트를 그대로 이관하지 않습니다. 팀 공통 요청·응답 JSON, 근거
단위 계약, GraphRAG 운영 여부는 팀 저장소에서 별도로 결정합니다. 재사용 가능한
것과 재사용하면 안 되는 것의 상세 목록은 [`docs/TEAM_HANDOFF.md`](docs/TEAM_HANDOFF.md)를
참고하세요.
