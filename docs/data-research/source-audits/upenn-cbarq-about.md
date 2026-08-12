# Source audit: About the C-BARQ

> 이 문서는 사람이 검토하는 조사 기록이다. 괄호의 영문 이름은 Data Contract v0와 대조하기 위한 임시 표지이며 스키마나 직렬화 키가 아니다. 모든 판단은 provisional이며 후속 법률·의미 검토가 필요하다.

## 조사 상태 (`audit_status`)

`reviewed` — University of Pennsylvania의 공식 About, disclaimer, privacy, organization signup 페이지를 확인하고 14개 영문 행동 차원명과 순서를 대조했다.

## 임시 소스 식별자 (`source_id`)

`upenn-cbarq-about`

## 소스 이름 (`source_name`)

About the C-BARQ

## 소스 분류 (`source_class`)

`dataset_definition`

## 발행·배포 주체 (`publisher`)

운영·배포: Center for the Interaction of Animals and Society, University of Pennsylvania School of Veterinary Medicine. 원 도구 개발·데이터 권리의 세부 주체는 추가 확인이 필요하다.

## 공식 주소 (`canonical_url`)

https://vetapps.vet.upenn.edu/cbarq/about.cfm

## 확인일 (`accessed_at`)

2026-08-12 (Asia/Seoul)

## 확인한 범위 (`scope_observed`)

공식 About 페이지의 개요와 다음 14개 영문 차원명·순서만 확인했다.

1. Stranger-directed aggression
2. Owner-directed aggression
3. Dog-directed aggression
4. Dog rivalry
5. Stranger-directed fear
6. Nonsocial fear
7. Dog-directed fear
8. Separation-related behavior
9. Attachment and attention-seeking
10. Trainability
11. Chasing
12. Excitability
13. Touch sensitivity
14. Energy level

설문 문항, 번역 문항, 채점법, 규준은 확인·기록 범위에서 제외했다. 이 목록은 DAENGS taxonomy 채택을 뜻하지 않는다.

## 접근 방식 (`access_method`)

University of Pennsylvania 공개 HTML 4개 페이지를 브라우저로 수동 열람했다. 로그인, 설문 수행, 데이터 다운로드는 하지 않았다.

## 수집·접근 제약 (`collection_constraints`)

공개 설명 페이지는 열람 가능하다. 조직용 이용은 별도 가입·구독 조건이 있고, 연구 목적 접근은 신청 절차와 범위 제한이 있다. 본 데이터베이스 제공을 당연히 포함하지 않는다. 자동 수집 조건은 미확인이다.

## 라이선스 기록 (`license_record`)

공식 페이지에서 C-BARQ 문항·채점·규준·데이터에 적용되는 명시적 공개 라이선스를 확인하지 못했다. disclaimer는 정보 제공 목적과 무보증을 밝히며 전문가 조언을 대체하지 않는다.

- 접근: 공개 설명 HTML 열람 가능.
- 자동 수집, 설문·번역·채점법·규준·원자료 저장, 변형·재배포·상업 이용: 미확인 또는 별도 계약 대상이므로 보류.
- RAG 이용 검토 범위: 공식 명칭·순번, 발행기관, URL과 자체 작성 measurement context만.

## 콘텐츠 품질 (`content_quality`)

도구 운영기관의 1차 정의라는 강점이 있다. 행동 차원은 보호자 보고 측정 구조이며 진단·원인·처방 자체가 아니다. 표본과 규준, 버전 차이는 이 페이지 정보만으로 평가할 수 없다.

## Locator 후보 (`locator_candidates`)

우선 조사 대상: 공식 HTML

### 후보 1: About 페이지와 차원 순번

- 종류(`kind`): `dataset-definition-item`
- 구성요소(`parts`): canonical URL, 페이지 제목, 1~14 순번, 공식 영문 차원명
- 정밀도(`precision`): 개별 차원명 단위
- 안정성(`stability`): 페이지 개정·차원 변경 위험이 있어 확인일과 운영기관을 함께 기록

## 예상 용도 (`intended_role`)

`measurement_context`와 행동 측정 개념 탐색에만 사용한다.

### 독립 주장 후보 (`provisional evidence relevance`)

- 공식 C-BARQ About 페이지는 보호자 보고 행동 평가를 14개 명명된 행동 차원으로 설명한다.
- 이 14개 차원은 측정 맥락 후보이며 훈련 처방 분류나 임상 진단으로 직접 전환되지 않는다.

## 위험과 미확인 사항 (`risks_and_unknowns`)

저작권·라이선스, 버전 이력, 데이터 접근 계약, 번역 권리, 채점·규준 권리는 미확인이다. 차원명 의미를 DAENGS 행동 taxonomy나 훈련 단계에 매핑하려면 `needs semantic review`이다. 설문 문항과 원자료를 유추·복제하지 않는다.

## 조사 결론 (`recommendation`)

provisional recommendation: `proceed_with_conditions`

### provisional reuse assessment

공식 영문 차원명·순번과 서지 메타데이터의 제한적 기록만 검토 가능하다. 설문 문항, 번역, 채점, 규준, 원자료는 hold이다.

### provisional evidence relevance

행동 측정 구조를 이해하는 데 관련되지만 훈련 효과·행동 수정·보호자 처방 근거에는 관련성이 낮다.

### 허용 가능한 claim scope

운영기관, 도구 목적, 14개 공식 영문 차원명·순번이라는 measurement context만 허용한다. 진단, 원인, 효과, 훈련 단계, taxonomy 채택 주장은 허용하지 않는다.

## 근거 링크 (`evidence_links`)

- About the C-BARQ — https://vetapps.vet.upenn.edu/cbarq/about.cfm — 2026-08-12 — 공식 정의와 14개 영문 차원명·순번
- C-BARQ Disclaimer — https://vetapps.vet.upenn.edu/cbarq/disclaimer.cfm — 2026-08-12 — 정보 목적·무보증·전문 조언 비대체
- Privacy Policy — https://vetapps.vet.upenn.edu/cbarq/privacy-policy.cfm — 2026-08-12 — 운영과 정보 처리 맥락
- Organization Signup — https://vetapps.vet.upenn.edu/cbarq/organization-signup.cfm — 2026-08-12 — 조직 접근·구독 조건

## 조사 메모 (`audit_notes`)

14개 영문 차원명과 순서만 수동 대조했다. 설문·번역·점수·규준·원자료는 열람하거나 저장하지 않았다.
