# DAENGS Chat API v0

이 문서는 프론트엔드와 검색·응답 파이프라인이 병렬로 개발될 수 있도록 `POST /chat`의 요청·응답 경계만 고정한다. 아래 값은 실제 카드나 출처가 아닌 합성 fixture다.

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

## 실행 흐름과 근거 제한

`/chat`은 요청 검증 후 안전 규칙과 결정적 범위 분류를 먼저 적용한다. 중독 의심 질문과 지원 범주 밖 질문은 retrieval과 answer 조립을 **모두 건너뛰고** `insufficient_evidence`를 반환한다. 지원 범주로 판정된 질문만 local retrieval을 호출하고, 질문과 같은 범주로 매핑되며 요청 언어와 claim 언어가 같은 카드만 남긴 뒤 그 카드에 provisional scope-matched minimum `0.40`을 적용한다. 남는 카드가 없으면 `insufficient_evidence`다.

범주 분류 결과와 후보 수는 내부 값이며 요청·응답 계약에 나타나지 않는다. 검색 score는 vector 유사도일 뿐 승인 여부나 사실성을 의미하지 않는다. 카드 승인과 RAG 사용 가능성은 기존 JSONL eligibility gate가 별도로 결정하며, `0.40`은 향후 검색 평가 결과로 조정할 임시 기준이다. 규칙과 실측 근거는 [`query-scope-gating.md`](query-scope-gating.md)에 있다.

남은 카드가 질문의 **의도**를 지원하는지도 확인한다. 절차 근거가 없는 연구 카드는 how_to 질문에 쓰이지 않으며, 이때는 조립도 생성도 하지 않고 `insufficient_evidence`가 된다.

answer는 두 경로 중 하나로 만들어진다. generation provider가 설정돼 있으면 검색된 근거만으로 답변을 생성하고, 서버가 그 초안을 검증한 뒤에만 사용한다. provider가 없거나 검증에 실패하면 선택된 카드의 검토된 `claim`을 citation과 같은 순서로 그대로 조립한다. 어느 경로로 답했는지는 응답에 드러나지 않는다. 상세는 [`grounded-rag.md`](grounded-rag.md)와 [`answer-composition.md`](answer-composition.md)에 있다.

번역을 하지 않으므로 카드의 `claim_language`가 요청의 `response_language`와 같은 카드만 사용한다. 현재 승인 카드는 모두 한국어라 `ko` 요청만 `answered`가 되고, 영어 요청은 영어 claim 카드가 생기기 전까지 `insufficient_evidence`다. 실제 answer 언어와 `answer_language` 표시가 어긋나는 경우는 없다.

Citation도 서버가 결정적으로 만든다. 검색된 카드의 `DIRECT` 또는 `SUPPORTING` SourceRef와 검증된 `SourceRegistryEntry`를 결합하며 `CONTEXT_ONLY`는 제외한다.

## 503 응답

검색 계층 초기화나 호출이 실패하면 기존 오류 계약을 유지한다. 내부 경로, 설정값, 오류 본문은 응답에 노출하지 않는다.

```json
{
  "code": "chat_not_ready",
  "message": "검증된 근거를 검색하는 기능을 준비 중입니다."
}
```

## Citation과 근거 계약의 관계

`ChatCitation.card_id`는 검토된 `EvidenceCard`를, `source_id`는 그 카드가 참조하는 `SourceRegistryEntry`를 가리킨다. `locator`와 `evidence_level`은 EvidenceCard v1의 `Locator`, `EvidenceLevel` 계약을 그대로 재사용한다. 현재 실행 계층은 citation이 검색된 카드의 `SourceRef`와 일치하도록 registry에서 source name과 canonical URL을 조회한다. 카드의 현재 승인 hash와 RAG 재사용 조건은 retrieval eligibility gate가 먼저 확인한다.

API에는 `quote`, `excerpt`, `chunk_text`, `raw_text`를 두지 않는다. 원문 또는 장문 인용을 응답에 복제하지 않고, 출처와 정확한 locator를 통해 사용자가 근거를 확인하게 하기 위함이다.

## 실행 설정과 CORS

`/chat`은 **generation 관련 환경변수 없이도 동작한다.** `GENERATION_BASE_URL`, `GENERATION_API_KEY`, `GENERATION_MODEL`이 없으면 grounded generation을 끄고 검토된 claim 조립으로 답한다. 이 경우에도 503이 아니다.

세 변수를 설정하면 같은 OpenAI-compatible adapter로 grounded 경로가 켜진다. 모델명과 endpoint는 설정에서만 오고 코드에 하드코딩돼 있지 않다. provider 초기화나 호출이 실패해도 서비스는 계속 동작하며 결정적 조립으로 내려간다.

기본 CORS origin은 `http://localhost:3000`이다. `DOG_TRAINING_RAG_CORS_ORIGINS`에 JSON 문자열 목록을 설정해 변경할 수 있다.

## 현재 미구현 범위

번역·요약 provenance, reranking, 정식 검색 평가, 스트리밍, 대화 저장과 memory는 구현하지 않는다. `SafetyNotice`는 현재 중독 의심 질문에 한해 `urgent`로만 설정되며, 그 밖의 안전 판정은 후속 계층의 책임이다.

프론트엔드는 provider와 승인 데이터가 준비되기 전까지 mock 모드를 사용할 수 있지만, 503이나 `insufficient_evidence`를 임의의 근거 기반 답변으로 대체해서는 안 된다.
