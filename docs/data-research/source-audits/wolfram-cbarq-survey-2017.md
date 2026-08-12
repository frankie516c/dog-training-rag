# Source audit: C-BARQ Survey

> 이 문서는 사람이 검토하는 조사 기록이다. 괄호의 영문 이름은 Data Contract v0와 대조하기 위한 임시 표지이며 스키마나 직렬화 키가 아니다. 모든 판단은 provisional이며 후속 법률·의미 검토가 필요하다.

## 조사 상태 (`audit_status`)

`sampled` — Wolfram Data Repository의 공식 랜딩 페이지와 DOI 메타데이터만 확인했다. 데이터 파일은 열람·다운로드하지 않았다.

## 임시 소스 식별자 (`source_id`)

`wolfram-cbarq-survey-2017`

## 소스 이름 (`source_name`)

C-BARQ Survey

## 소스 분류 (`source_class`)

`dataset_definition`

## 발행·배포 주체 (`publisher`)

배포: Wolfram Research, Wolfram Data Repository. 원출처 표시: Center for the Interaction of Animals and Society, University of Pennsylvania. 기여자: James Serpell, James Ghirlanda, Alberto Acerbi, Harold Herzog 등으로 표시된다.

## 공식 주소 (`canonical_url`)

https://datarepository.wolframcloud.com/resources/d1df2a7c-ac0e-4244-b787-fc07dd308cc2/

## 확인일 (`accessed_at`)

2026-08-12 (Asia/Seoul)

## 확인한 범위 (`scope_observed`)

공식 랜딩 페이지의 제목, DOI, 생성일 2017-06-12, 원자료 연도 2013 표시, 12,059행·16열이라는 규모 메타데이터, 제공 형식과 `CC-BY` 표기만 확인했다. 데이터 값·전체 열·파일은 조사하지 않았다.

## 접근 방식 (`access_method`)

공식 HTML 랜딩 페이지와 DOI 연결 정보를 브라우저로 수동 열람했다. CSV, JSON, TSV, Wolfram Language 파일은 내려받지 않았다.

## 수집·접근 제약 (`collection_constraints`)

공식 페이지는 여러 다운로드 형식을 안내한다. 자동 접근 약관·rate limit, 형식별 추가 조건은 미확인이다. 이번 범위에서는 메타데이터 감사만 허용하고 원시 데이터 적재를 보류한다.

## 라이선스 기록 (`license_record`)

공식 랜딩 페이지에는 `CC-BY`가 표시된다. 그러나 다음은 미확인이다.

- CC BY 버전과 정확한 라이선스 URL.
- 표시가 데이터셋의 모든 열·값·메타데이터·제3자 요소에 적용되는지.
- University of Pennsylvania 원자료에서 Wolfram 배포본까지의 권리 사슬.
- 접근: 공개 메타데이터 열람 가능.
- 원시 데이터 저장·변형·RAG 적재·재현·재배포·상업 이용: 위 범위가 해소되기 전까지 hold.

## 콘텐츠 품질 (`content_quality`)

영구 DOI와 규모·기여자 메타데이터가 장점이다. 데이터 생성·표본추출·변수 변환·결측·품질관리 설명은 랜딩 페이지 표본만으로 충분히 평가되지 않는다.

## Locator 후보 (`locator_candidates`)

우선 조사 대상: 데이터셋 정의 페이지

### 후보 1: Wolfram 리소스 ID와 필드명

- 종류(`kind`): `dataset-record-field`
- 구성요소(`parts`): DOI `10.24097/wolfram.41397.data`, 리소스 UUID, 공식 필드명, 레코드 식별자(제공 여부 미확인)
- 정밀도(`precision`): 메타데이터 필드 단위; 개별 행은 안정 식별자 미확인
- 안정성(`stability`): DOI는 비교적 안정적이나 페이지·필드 스키마가 바뀔 수 있어 UUID와 확인일을 병기

## 예상 용도 (`intended_role`)

현재는 `measurement_context`, `dataset_limitation`, 출처·권리 사슬 감사에만 사용한다.

### 독립 주장 후보 (`provisional evidence relevance`)

- Wolfram 공식 페이지는 C-BARQ Survey 파생 배포본의 DOI, 규모, 기여자, 원출처 메타데이터를 제공한다.
- 이 배포본의 변수·행은 권리 사슬과 방법론 검토 전에는 훈련 처방 근거로 사용할 수 없다.

## 위험과 미확인 사항 (`risks_and_unknowns`)

라이선스 버전·적용 범위·권리 사슬이 핵심 미확인 사항이다. Wolfram 표시를 UPenn 원도구·원자료·설문 문항에 자동 전이하면 안 된다. 변수 의미와 표본 대표성도 `needs semantic review`이다.

## 조사 결론 (`recommendation`)

provisional recommendation: `hold`

### provisional reuse assessment

메타데이터 감사와 링크 보존만 진행한다. `CC-BY` 표시만으로 원시 데이터 재사용을 추정하지 않으며 권리 사슬 확인 전에는 데이터 적재를 보류한다.

### provisional evidence relevance

측정·데이터셋 맥락에는 관련되지만 훈련 방법 효과나 보호자 행동 수정 상담에는 직접 근거가 아니다.

### 허용 가능한 claim scope

Wolfram 페이지에 표시된 제목, DOI, 생성일, 규모, 기여자·출처, 라이선스 문자열이라는 배포 메타데이터만 허용한다. 원시 값, 설문 의미, 훈련 처방, 원 UPenn 자료의 권리는 주장하지 않는다.

## 근거 링크 (`evidence_links`)

- Wolfram Data Repository 리소스 — https://datarepository.wolframcloud.com/resources/d1df2a7c-ac0e-4244-b787-fc07dd308cc2/ — 2026-08-12 — 제목, DOI, 규모, 기여자, `CC-BY` 표시
- DOI — https://doi.org/10.24097/wolfram.41397.data — 2026-08-12 — 영구 식별자와 공식 랜딩 연결
- UPenn About the C-BARQ — https://vetapps.vet.upenn.edu/cbarq/about.cfm — 2026-08-12 — 원도구 운영기관·측정 맥락 교차 확인

## 조사 메모 (`audit_notes`)

다운로드 링크는 실행하지 않았다. 라이선스 문자열의 버전과 권리 범위가 확인될 때까지 메타데이터 이외 사용은 보류한다.
