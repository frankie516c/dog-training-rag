# 최소 백엔드 실행

이 문서는 체크포인트 2에서 추가한 Python 3.12 기반 FastAPI 실행 환경을 설명한다. 현재 백엔드는 설정 로딩과 `GET /health`만 제공하며 검색·데이터 파이프라인은 포함하지 않는다.

## 준비

Python 버전과 프로젝트 의존성은 `uv`로 관리한다.

```powershell
uv python install 3.12
uv sync --dev
```

`.python-version`은 Python 3.12를 선택하고, `pyproject.toml`은 `>=3.12,<3.13` 범위를 요구한다.

## 설정

설정은 `DOG_TRAINING_RAG_` 접두사가 붙은 환경변수와 저장소 루트의 `.env`에서 읽는다. 로컬 설정 파일이 필요하면 예시를 복사한다.

```powershell
Copy-Item .env.example .env
```

지원하는 설정은 다음과 같다.

| 환경변수 | 기본값 | 허용값 |
|---|---|---|
| `DOG_TRAINING_RAG_APP_NAME` | `dog-training-rag` | 문자열 |
| `DOG_TRAINING_RAG_ENVIRONMENT` | `local` | `local`, `test`, `production` |
| `DOG_TRAINING_RAG_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

`.env`는 커밋하지 않고 `.env.example`만 추적한다.

## 서버 실행

저장소 루트에서 다음 명령을 실행한다.

```powershell
uv run uvicorn backend.app.main:app --reload
```

기본 주소는 `http://127.0.0.1:8000`이다. 상태 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

정상 응답 예시:

```json
{
  "status": "ok",
  "app": "dog-training-rag",
  "environment": "local"
}
```

## 테스트와 lint

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

이 체크포인트에서는 EvidenceCard, 벡터 DB, 임베딩·생성 provider, 데이터 수집·가공, 프론트엔드를 설정하지 않는다.
