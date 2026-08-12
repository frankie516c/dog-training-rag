# EvidenceCard v1

상태: 도메인 계약 v1

스키마 버전: `1.0`
구현: `backend/app/domain/evidence.py`

이 계약은 실제 source audit 10개에서 반복된 출처 식별, 권리 검토, claim 범위, locator, 의미 검토 요구를 최소 모델로 정리한다. 실제 카드나 source registry 데이터, 승인 서비스와 검색 저장 형식은 이 체크포인트에 포함하지 않는다.

## 모델별 책임

| 모델 | 책임 |
|---|---|
| `SourceRegistryEntry` | 출처의 안정적인 ID, 분류, 발행 정보, canonical URL, 원 콘텐츠 언어와 행위별 라이선스·재사용 검토 결과를 보관한다. claim이나 상담 근거 수준을 담지 않는다. |
| `SourceClass` | audit에서 확인된 출처 종류 5개를 표현한다. 출처의 권위나 개별 claim의 강도를 자동 결정하지 않는다. |
| `ContentLanguage` | 현재 MVP가 구조적으로 식별하는 원 출처·claim 언어 `ko`, `en`을 표현한다. |
| `EvidenceLevel` | 특정 `SourceRef`가 해당 카드의 claim을 직접 지지하는지, 보조하는지, 맥락만 제공하는지 표현한다. 라이선스 상태가 아니다. |
| `ReuseAssessment` | 접근, 자동 수집, 저장, 변형, RAG 이용, 인용, 재배포, 상업 이용 중 한 행위의 권리 판단과 조건을 기록한다. |
| `Locator` | 사람이 원 출처의 해당 위치로 돌아가기 위한 유형별 위치 정보다. 원문 본문을 보관하지 않는다. |
| `SourceRef` | 하나의 카드에서 등록 출처 `source_id`, locator, claim별 근거 수준을 결합한다. |
| `EvidenceCard` | 하나의 대표 topic 아래 간결한 claim, 중복 없는 tags, 하나 이상의 source reference와 한계를 보관한다. 신규 카드는 pending 상태만 생성할 수 있다. |
| `ReviewStatus` | `PENDING_SEMANTIC_REVIEW`, `APPROVED`, `REJECTED` 상태 어휘를 정의한다. Pending은 결정이 아니다. |
| `ReviewDecision` | 사람의 승인 또는 거절을 reviewer, 시각, 카드 내용 hash, 결정, note와 함께 별도 기록한다. |

`SourceRegistryEntry`와 `EvidenceCard`는 분리된다. 카드가 출처 메타데이터를 복제하지 않고 `SourceRef.source_id`로 registry entry를 참조하므로 같은 출처를 여러 카드가 공유할 수 있다. 반대로 한 카드는 여러 `SourceRef`를 가질 수 있다.

## 필수·선택 필드

### SourceRegistryEntry

필수 필드는 `schema_version`, `source_id`, `source_class`, `title`, `publisher`, `canonical_url`, 하나 이상의 `content_languages`, `last_verified_at`이다. `source_id`는 소문자 ASCII kebab-case이며 URL은 HTTP(S)여야 한다. 콘텐츠 언어는 현재 `ko`, `en`만 허용하며 빈 목록과 중복을 거부한다.

선택 필드는 `license_name`, `license_url`, `reuse_assessments`이다. `reuse_assessments`의 각 원소는 하나의 행위와 판단 상태, 필요한 조건·note를 담는다. 이는 권리 검토 결과이며 상담 근거 관련성과 별개다.

### Locator와 SourceRef

모든 locator는 `kind`와 HTTP(S) `url`이 필요하다. 유형별 필수값은 다음 절을 따른다. `SourceRef`는 `source_id`, `locator`, `evidence_level`이 필수이고 좁은 근거 관계를 설명하는 `support_note`는 선택이다.

### EvidenceCard

필수 필드는 `schema_version`, UUID `card_id`, 비어 있지 않은 `claim`, `claim_language`, 하나의 대표 `topic`, 하나 이상의 `source_refs`이다. `claim_language`는 `ko` 또는 `en`이다. `tags`와 `limitations`는 선택 목록이다. tags는 앞에서 처음 나타난 표기를 보존하면서 대소문자를 무시해 중복을 제거한다.

모든 source reference가 `CONTEXT_ONLY`인 카드는 거부한다. 최소 하나는 `DIRECT` 또는 `SUPPORTING`이어야 한다. 한국어 claim이 영어 출처를 참조하거나 한국어·영어 출처를 함께 참조하는 것은 유효하며, 언어 경계를 넘는 의미 적합성은 semantic review 대상이다.

원문 본문, 장문 인용, 견종 기반 공격성 판정, C-BARQ 차원 필드는 없다. C-BARQ는 source audit에서 측정 맥락으로 확인되었을 뿐 DAENGS의 최종 taxonomy가 아니다.

### ReviewDecision

필수 필드는 `schema_version`, `card_id`, `reviewer`, 시간대가 있는 `reviewed_at`, `content_hash_version`, `sha256:<64 lowercase hex>` 형식의 `card_content_hash`, `decision`, 비어 있지 않은 `note`이다. `content_hash_version`은 `evidence-card-content-v1`만 허용하며 `decision`에는 `APPROVED`와 `REJECTED`만 허용한다. `ReviewDecision.for_card(...)`가 공식 규칙으로 hash가 결합된 결정을 생성한다.

## 행위별 재사용 검토

`ReuseAssessment.action`은 다음 여덟 행위를 구분한다.

- `access`
- `automated_collection`
- `local_storage`
- `transformation`
- `rag_use`
- `quotation`
- `redistribution`
- `commercial_use`

각 행위의 상태는 `permitted`, `permitted_with_conditions`, `prohibited`, `unknown` 중 하나다. `permitted_with_conditions`에는 비어 있지 않은 `conditions`가 필수다. 한 registry entry에서 같은 행위는 두 번 기록할 수 없다.

`unknown`과 assessment가 누락된 행위는 모두 **허용되지 않은 것으로 취급한다**. 전 행위를 일괄 허용하는 boolean이나 편의 속성은 제공하지 않는다. 실제 사용 전 서비스가 해당 행위의 assessment를 명시적으로 찾아 조건을 집행해야 한다.

## Locator 유형

| kind | 필수 위치 정보 | 선택 정보 | audit 근거 |
|---|---|---|---|
| `html` | `section` 또는 `fragment` | 둘 중 나머지 하나 | AAHA·AVSAB 허브·농림축산식품부 HTML의 절과 fragment |
| `pdf` | 1부터 시작하는 `page` | `section`, `fragment` | AVSAB 공식 PDF의 인쇄 페이지와 절 제목 |
| `pmc_article` | `pmcid`, `section` | `doi`, `fragment` | PMC 논문의 PMCID, DOI, 방법·결과 절·표 식별자 |
| `dataset_definition` | `dataset_id`와 `section` 또는 `item_id` | `doi`, `fragment` | UPenn C-BARQ 항목과 Wolfram 리소스 UUID·필드 |

유형과 관계없는 위치 필드는 거부한다. 예를 들어 HTML locator에 PDF 페이지나 PMCID를 넣을 수 없다.

## 리뷰 상태 전이

```text
새 EvidenceCard
    └─ PENDING_SEMANTIC_REVIEW
         ├─ [승인된 사람이 동일 content hash를 검토] → APPROVED 결정
         └─ [승인된 사람이 동일 content hash를 검토] → REJECTED 결정
```

`EvidenceCard.review_status`는 v1에서 `PENDING_SEMANTIC_REVIEW`만 허용한다. 승인과 거절은 카드가 스스로 선언하는 값이 아니라 별도 `ReviewDecision`으로 기록하고 서비스가 유효한 결정을 조회해 effective status를 계산한다. 카드 내용이 바뀌어 hash가 달라지면 기존 결정은 새 내용에 적용되지 않는다.

## Canonical content hash

버전 `evidence-card-content-v1`은 승인 대상 콘텐츠를 다음 규칙으로 직렬화한다.

1. UTF-8 JSON을 사용하고 `ensure_ascii=false`로 언어 문자를 보존한다.
2. 객체 key를 정렬하고 불필요한 공백 없이 직렬화한다.
3. `SourceRef.support_note`와 locator의 사용하지 않는 optional 필드를 포함해 모든 중첩 `None` 값을 JSON `null`로 보존한다.
4. `tags`, `source_refs`, `limitations`는 의미상 순서가 없으므로 canonical 값 기준으로 정렬한다.
5. claim, claim language, topic, tags, 모든 SourceRef 필드, locator, evidence level, limitations와 `schema_version`을 포함한다.
6. canonical 규칙 자체의 버전도 payload에 포함한다.
7. `review_status`와 `ReviewDecision`은 승인 대상 내용이 아니므로 제외한다.
8. `card_id`는 콘텐츠가 아니라 identity이고 `ReviewDecision.card_id`가 별도로 결정을 특정하므로 hash에서 제외한다.
9. 정규화된 JSON bytes의 SHA-256을 계산해 `sha256:<lowercase hex>`로 표현한다.

`schema_version`은 같은 필드가 향후 다른 의미로 해석되는 일을 방지하기 위해 포함한다. `EvidenceCard.canonical_content_bytes()`와 `EvidenceCard.content_hash()`가 공식 구현이다. 서비스 계층은 결정을 저장하거나 적용할 때 같은 규칙으로 hash를 재계산해 `content_hash_version`, `card_id`, `card_content_hash`가 모두 일치하는지 확인해야 한다.

## 직렬화 예시

다음은 원문이나 장문 인용 없이 유효한 카드 한 개를 표현한다.

```json
{
  "schema_version": "1.0",
  "card_id": "f17cfc7f-dc26-4a27-bb6c-44bff060aa16",
  "claim": "초기 사회화는 개체의 반응과 건강 조건을 고려해 안전하고 긍정적으로 진행해야 한다.",
  "claim_language": "ko",
  "topic": "puppy socialization",
  "tags": ["socialization", "welfare"],
  "source_refs": [
    {
      "source_id": "avsab-puppy-socialization",
      "locator": {
        "kind": "pdf",
        "url": "https://avsab.org/wp-content/uploads/2024/12/Puppy-Socialization-Position-Statement-FINAL.pdf",
        "section": "Socialization and safety conditions",
        "fragment": null,
        "page": 1,
        "pmcid": null,
        "doi": null,
        "dataset_id": null,
        "item_id": null
      },
      "evidence_level": "DIRECT",
      "support_note": "기관 입장문의 일반 원칙 범위에서만 지지한다."
    }
  ],
  "limitations": ["개체별 백신 일정이나 감염 위험을 판정하지 않는다."],
  "review_status": "PENDING_SEMANTIC_REVIEW"
}
```

JSON은 v1의 교환 표현이다. 저장 파일 배치와 JSONL 사용 여부는 아직 정하지 않았다.

출처별 번역·요약·합성 과정을 설명하는 상세 provenance는 이 카드에 원문 필드로 넣지 않는다. 다음 체크포인트에서 원문 전체나 장문 인용을 저장하지 않는 별도 derivation/provenance record로 설계한다.

## 스키마가 강제하는 것

- top-level registry entry, card, review decision의 `schema_version`은 `1.0`이다.
- source ID 형식, HTTP(S) URL, 비어 있지 않은 핵심 문자열을 검증한다.
- 원 출처의 콘텐츠 언어 목록과 claim 언어를 `ko`, `en`으로 제한하고 빈 목록·중복을 거부한다.
- source registry와 card의 구조를 분리하고 card에는 하나 이상의 `SourceRef`를 요구한다.
- 카드에 최소 하나의 `DIRECT` 또는 `SUPPORTING` 참조를 요구한다.
- locator 종류별 필수 요소와 불필요한 타 유형 요소를 검증한다.
- 하나의 대표 topic과 중복 없는 multi-label tags를 보장한다.
- 행위별 재사용 상태와 조건을 검증하고 같은 행위의 중복 assessment를 거부한다.
- canonical hash 규칙과 ReviewDecision의 hash 규칙 버전을 결합한다.
- 신규 카드에는 pending만 허용하고 pending을 review decision으로 기록할 수 없게 한다.
- 승인·거절 결정에 reviewer, timezone-aware 시각, 형식화된 content hash, decision, note를 요구한다.
- 알 수 없는 필드와 enum 값을 거부한다.

## 이후 서비스 계층에서 강제할 것

Pydantic 객체 하나만으로 외부 상태와 사람의 권한을 검증할 수 없으므로 다음은 서비스 계층 책임이다.

- `SourceRef.source_id`가 실제 registry에 존재하고 locator URL이 그 출처에 속하는지 확인
- source registry의 권리 검토 결과와 intended use를 대조하고 라이선스 조건·출처표시를 실행
- reviewer가 승인 권한을 가진 사람인지 인증하고 AI가 review endpoint를 호출하지 못하게 차단
- 제출된 `card_content_hash`를 `evidence-card-content-v1`로 다시 계산해 카드 내용과 일치시키기
- 최신 결정만 적용하고 이미 결정된 hash의 중복·상충 결정 및 허용되지 않은 상태 전이를 차단
- claim이 locator의 실제 내용과 의미상 일치하는지, 한계가 보존됐는지 사람 검토
- 영어 출처에서 한국어 claim을 만들거나 여러 언어 출처를 합성한 경우 번역·요약의 의미 보존 검토
- `CONTEXT_ONLY` 표기가 실제로 맥락 전용인지, DIRECT/SUPPORTING 표기가 claim 범위에 적합한지 검토
- 의료·안전·지역 법률 등 고위험 맥락의 별도 검토 및 production 승인 게이트
- 특정 견종만으로 공격성을 단정하지 않고 C-BARQ 차원을 진단·처방 taxonomy로 자동 변환하지 않기

## Data Contract v0에서 변경된 결정

- source audit의 18개 임시 필드를 복사하지 않고, 안정적인 출처 identity·권리 검토만 `SourceRegistryEntry`로 축소했다.
- `content_quality`, `risks_and_unknowns`, `recommendation` 같은 조사 서술은 final card 필드가 아니다. claim에 필요한 범위 제한만 `limitations`와 `support_note`로 남긴다.
- audit의 locator candidate를 자유형 `parts`가 아니라 네 종류의 검증 가능한 `Locator`로 확정했다.
- 출처 종류(`SourceClass`)와 카드별 근거 관련성(`EvidenceLevel`), 라이선스 재사용 검토를 서로 다른 필드와 모델 책임으로 분리했다.
- 원 출처 언어와 claim 언어를 구조화했으며 상세 derivation/provenance는 다음 체크포인트로 이연했다.
- 전역 재사용 boolean 대신 여덟 행위별 assessment로 권리 검토 범위를 확정했다.
- 하나의 source audit에서 여러 독립 claim 후보가 나온다는 점을 반영해 registry entry와 여러 EvidenceCard의 관계를 분리했다.
- 승인 상태를 카드 작성 입력으로 허용하지 않고 버전된 canonical hash에 결합된 별도 `ReviewDecision`으로 분리했다.
- 최종 저장 경로, registry 데이터 파일, JSONL, derivation/provenance record와 검색 payload는 결정하지 않았다.
