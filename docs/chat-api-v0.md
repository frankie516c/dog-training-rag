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

## 실행 흐름과 근거 제한

`/chat`은 요청 검증 후 안전 규칙과 결정적 범위 분류를 먼저 적용한다. 중독 의심 질문과 지원 범주 밖 질문은 retrieval과 generation provider를 **호출하지 않고** `insufficient_evidence`를 반환한다. 지원 범주로 판정된 질문만 local retrieval을 호출하고, 질문과 같은 범주로 매핑되는 카드만 남긴 뒤 그 카드에 provisional scope-matched minimum `0.40`을 적용한다. 남는 카드가 없으면 provider를 호출하지 않는다.

범주 분류 결과와 후보 수는 내부 값이며 요청·응답 계약에 나타나지 않는다. 검색 score는 vector 유사도일 뿐 승인 여부나 사실성을 의미하지 않는다. 카드 승인과 RAG 사용 가능성은 기존 JSONL eligibility gate가 별도로 결정하며, `0.40`은 향후 검색 평가 결과로 조정할 임시 기준이다. 규칙과 실측 근거는 [`query-scope-gating.md`](query-scope-gating.md)에 있다.

생성 provider에는 사용자 질문과 응답 언어 외에 선택된 카드의 `claim`, `topic`, `limitations`만 제공한다. 근거 밖의 절차나 사실을 만들지 않고, 처벌·공포 기반 방법을 새로 권고하지 않으며, limitations를 보존하도록 지시한다. URL, locator, 라이선스 문구, 원문, registry metadata는 prompt 근거 본문에 복제하지 않는다.

Citation은 provider 출력에서 받지 않는다. 서버가 검색된 카드의 `DIRECT` 또는 `SUPPORTING` SourceRef와 검증된 `SourceRegistryEntry`를 결합해 결정적으로 만든다. `CONTEXT_ONLY`는 citation에서 제외한다.

## 503 응답

생성 provider가 설정되지 않았거나 provider·검색 호출이 실패하면 기존 오류 계약을 유지한다. API key나 provider 오류 본문은 응답에 노출하지 않는다.

```json
{
  "code": "chat_not_ready",
  "message": "검증된 근거를 검색하는 기능을 준비 중입니다."
}
```

## Citation과 근거 계약의 관계

`ChatCitation.card_id`는 검토된 `EvidenceCard`를, `source_id`는 그 카드가 참조하는 `SourceRegistryEntry`를 가리킨다. `locator`와 `evidence_level`은 EvidenceCard v1의 `Locator`, `EvidenceLevel` 계약을 그대로 재사용한다. 현재 실행 계층은 citation이 검색된 카드의 `SourceRef`와 일치하도록 registry에서 source name과 canonical URL을 조회한다. 카드의 현재 승인 hash와 RAG 재사용 조건은 retrieval eligibility gate가 먼저 확인한다.

API에는 `quote`, `excerpt`, `chunk_text`, `raw_text`를 두지 않는다. 원문 또는 장문 인용을 응답에 복제하지 않고, 출처와 정확한 locator를 통해 사용자가 근거를 확인하게 하기 위함이다.

## Provider와 CORS 설정

동일한 OpenAI-compatible `/chat/completions` adapter를 base URL과 model 설정만 바꿔 OpenAI, NVIDIA NIM 또는 로컬 호환 서버에 연결한다.

```text
GENERATION_BASE_URL
GENERATION_API_KEY
GENERATION_MODEL
```

`GENERATION_BASE_URL`과 `GENERATION_MODEL`은 실행에 필요하다. 인증이 필요 없는 로컬 서버에서는 API key를 비워 둘 수 있다. key는 secret 설정으로 취급하며 응답이나 오류 메시지에 넣지 않는다.

기본 CORS origin은 `http://localhost:3000`이다. `DOG_TRAINING_RAG_CORS_ORIGINS`에 JSON 문자열 목록을 설정해 변경할 수 있다.

## 현재 미구현 범위

번역·요약 provenance, reranking, 정식 검색 평가, 스트리밍, 대화 저장과 memory는 구현하지 않는다. `SafetyNotice`는 현재 중독 의심 질문에 한해 `urgent`로만 설정되며, 그 밖의 안전 판정은 후속 계층의 책임이다.

프론트엔드는 provider와 승인 데이터가 준비되기 전까지 mock 모드를 사용할 수 있지만, 503이나 `insufficient_evidence`를 임의의 근거 기반 답변으로 대체해서는 안 된다.
