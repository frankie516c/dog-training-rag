# 로컬 Evidence 검색 기반

체크포인트 5B는 사람 검토와 재사용 조건을 모두 통과한 `EvidenceCard`만 dense vector로 변환해 Qdrant local persistent mode에 저장하고 검색하는 기반을 제공한다. `/chat`의 503 응답과 LLM 답변 생성은 변경하지 않는다.

## 임베딩 경계와 BGE-M3

`EmbeddingProvider`는 `model_id`, `dimension`, `embed_documents(texts)`, `embed_query(text)`만 노출한다. production 구현은 `BAAI/bge-m3`를 Sentence Transformers로 실행한다. 한국어와 영어를 함께 다루는 현재 카드 언어 범위와 1,024차원 dense 표현을 지원하기 때문에 초기 기본값으로 선택했다.

현재는 BGE-M3의 dense embedding만 사용하며 sparse 및 ColBERT 출력, hybrid 검색, reranking은 사용하지 않는다. 모든 출력 vector는 정규화하고 Qdrant collection은 cosine distance를 사용한다. 향후 비교 가능한 모델 실험은 검색 계약을 바꾸지 않고 `EmbeddingProvider` 구현을 교체하는 방식으로 수행한다.

Sentence Transformers와 모델 객체는 module import 시 생성하지 않는다. 첫 번째 eligible 문서를 실제로 임베딩하거나, eligible 인덱스에 질의를 임베딩하는 시점에만 모델을 lazy load하므로 그때 최초 모델 다운로드가 발생할 수 있다. 카드가 0개인 build와 빈 인덱스 search는 모델을 로드하지 않는다.

## 임베딩 텍스트

카드별 입력은 다음 네 줄을 정확한 순서로 결합한다.

```text
claim: <claim>
topic: <topic>
tags: <대소문자 비의존 정렬 후 " | "로 결합>
limitations: <대소문자 비의존 정렬 후 " | "로 결합>
```

빈 tags 또는 limitations도 해당 label과 빈 값으로 줄을 유지한다. Source URL, locator, 라이선스 문구, source registry 내용, review decision은 임베딩하지 않는다.

## Eligibility 연결

검색 계층은 `backend.app.data_validation.load_and_validate()`의 `rag_eligible_cards`를 인덱싱 입력으로 그대로 사용한다. 따라서 다음을 모두 만족해야 한다.

1. 카드와 출처·결정의 참조 무결성이 유효하다.
2. 현재 card content hash와 hash version에 맞는 `APPROVED` 결정이 있다.
3. `REJECTED` 결정이 없다.
4. 모든 `DIRECT` 또는 `SUPPORTING` 출처의 `rag_use`가 `permitted` 또는 `permitted_with_conditions`다.

Pending, rejected, 재사용 불가 카드는 제외된다. hash 불일치나 승인·거절 충돌 같은 데이터 오류는 fail closed로 build/search를 중단한다. 세 JSONL 파일이 모두 아직 없는 초기 상태는 데이터 0건으로 취급하지만, 일부만 존재하면 기존 JSONL 검증 오류를 그대로 반환한다. 검색 시 payload의 `card_id`로 현재 검증된 JSONL 결과에서 전체 `EvidenceCard`를 다시 찾으며, stale schema version이나 content hash도 거부한다.

## Qdrant 저장

기본 경로는 Git에서 제외된 `data/qdrant`, 기본 collection은 `evidence_cards_v1`이다. collection은 1,024차원 cosine vector를 사용한다. 전체 rebuild는 기존 collection을 다시 만들고 같은 card ID에서 UUIDv5 point ID를 결정적으로 생성하므로 반복 실행해도 point가 중복되지 않는다.

Payload는 다음 세 값만 저장한다.

```json
{
  "card_id": "<EvidenceCard UUID>",
  "schema_version": "1.0",
  "content_hash": "sha256:<canonical content hash>"
}
```

claim 원문, locator, `SourceRegistryEntry` 전체는 Qdrant에 복제하지 않는다.

## 실행 방법

```powershell
uv run python -m backend.app.retrieval build
uv run python -m backend.app.retrieval search "강아지가 사람에게 자꾸 점프해요"
uv run python -m backend.app.retrieval search "산책 연습" --top-k 5
```

기본 top-k는 5다. score는 query와 vector의 cosine 유사도일 뿐, 근거 승인 여부나 사실의 확실성을 의미하지 않는다. 승인은 JSONL 검증과 eligibility gate가 별도로 판정한다. 실제 승인 데이터가 들어오기 전 build의 `indexed=0`과 search의 `results=0`은 정상이다.

환경변수로 로컬 설정을 재정의할 수 있다.

```text
DOG_TRAINING_RAG_QDRANT_PATH
DOG_TRAINING_RAG_QDRANT_COLLECTION
DOG_TRAINING_RAG_EMBEDDING_MODEL_ID
DOG_TRAINING_RAG_EMBEDDING_DEVICE
```

RTX 3050 6GB처럼 VRAM 제약이 있는 환경에서는 `DOG_TRAINING_RAG_EMBEDDING_DEVICE=cpu`로 CPU를 선택하거나, 환경에 맞게 `cuda`를 명시해 실제 메모리 사용량을 확인한다. 모델·device 변경은 같은 1,024차원 collection 계약과 결과 재구축을 전제로 한다.
