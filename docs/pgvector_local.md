# Local PGVector

구조 보존형 청크 7,079개를 `intfloat/multilingual-e5-base`(768차원)로 임베딩해 적재하는 로컬 구성을 제공한다.

```powershell
docker compose -f docker-compose.pgvector.yml up -d
uv run --with "psycopg[binary]" --with sentence-transformers `
  python scripts/pgvector_ingest.py
```

재실행은 `chunk_id`와 `document_id` 기준 upsert이므로 안전하다. 검색 시 질의에는 `query: `, 문서에는 `passage: ` 접두사를 사용한다. 운영 전에는 비밀번호와 포트를 환경변수로 분리하고, 모델 변경 시 별도 `embedding_model` run으로 적재한다.
