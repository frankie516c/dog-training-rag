# DAENGS Chat API v0

이 문서는 프론트엔드, 검색 파이프라인, 생성 provider가 병렬로 개발될 수 있도록 `POST /chat`의 요청·응답 경계만 고정한다. 아래 값은 실제 카드나 출처가 아닌 합성 fixture다.

## 요청

`message`는 앞뒤 공백을 제거한 뒤 1자 이상 1,000자 이하이어야 한다. `response_language`는 `ko` 또는 `en`이며 생략하면 `ko`다.

```json
{
  "message": "합성된 산책 연습 질문입니다.",
  "response_language": "ko"
}
```

대화 ID, 사용자나 반려견 프로필, 검색 개수, 모델명, temperature, prompt, 검색 필터는 v0 요청에 포함하지 않는다.

## 성공 응답

### 근거가 충분한 경우

```json
{
  "request_id": "22222222-2222-4222-8222-222222222222",
  "status": "answered",
  "answer": "합성 fixture에 근거한 예시 답변입니다.",
  "answer_language": "ko",
  "citations": [
    {
      "card_id": "11111111-1111-4111-8111-111111111111",
      "source_id": "synthetic-source",
      "source_name": "합성 훈련 원칙 문서",
      "canonical_url": "https://example.test/guidance",
      "locator": {
        "kind": "html",
        "url": "https://example.test/guidance#synthetic-section",
        "section": "합성 절",
        "fragment": null,
        "page": null,
        "pmcid": null,
        "doi": null,
        "dataset_id": null,
        "item_id": null
      },
      "evidence_level": "DIRECT"
    }
  ],
  "limitations": [],
  "safety_notice": null
}
```

`answered`는 하나 이상의 citation을 요구한다. citation의 근거 수준은 `DIRECT` 또는 `SUPPORTING`만 가능하며, 같은 `card_id`와 `source_id` 조합을 중복할 수 없다.

### 근거가 부족한 경우

```json
{
  "request_id": "33333333-3333-4333-8333-333333333333",
  "status": "insufficient_evidence",
  "answer": "현재 검증된 근거만으로는 답변하기 어렵습니다.",
  "answer_language": "ko",
  "citations": [],
  "limitations": ["검토가 완료된 합성 근거가 없습니다."],
  "safety_notice": null
}
```

`insufficient_evidence`는 citation을 포함할 수 없다. 이 상태에서는 근거 없는 훈련 방법을 생성하지 않는 것이 서비스 정책이다.

## 현재 503 응답

현재 `/chat`은 요청 계약을 검증한 다음 검색·생성 기능이 준비되지 않았음을 구조화된 응답으로 알린다.

```json
{
  "code": "chat_not_ready",
  "message": "검증된 근거를 검색하는 기능을 준비 중입니다."
}
```

## Citation과 근거 계약의 관계

`ChatCitation.card_id`는 검토된 `EvidenceCard`를, `source_id`는 그 카드가 참조하는 `SourceRegistryEntry`를 가리킨다. `locator`와 `evidence_level`은 EvidenceCard v1의 `Locator`, `EvidenceLevel` 계약을 그대로 재사용한다. 응답을 조립하는 후속 서비스 계층은 citation이 실제 카드의 `SourceRef`와 일치하고 현재 승인 hash 및 RAG 재사용 조건을 만족하는지 확인해야 한다.

API에는 `quote`, `excerpt`, `chunk_text`, `raw_text`를 두지 않는다. 원문 또는 장문 인용을 응답에 복제하지 않고, 출처와 정확한 locator를 통해 사용자가 근거를 확인하게 하기 위함이다.

## 현재 미구현 범위

실제 EvidenceCard 데이터, 번역·요약 provenance, 임베딩, Qdrant, 검색과 reranking, LLM provider, prompt, 스트리밍, 대화 저장과 memory는 구현하지 않는다. 안전 notice의 생성 판단과 근거 기반 응답 조립도 후속 서비스 계층의 책임이다.

프론트엔드는 실제 검색·생성 API가 연결되기 전까지 mock 모드를 사용해야 하며, 현재의 503 응답을 실제 답변으로 대체하거나 임의의 근거를 생성해서는 안 된다.
