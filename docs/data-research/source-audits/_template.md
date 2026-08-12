# Source audit: [소스 이름]

> 이 문서는 사람이 검토하는 조사 기록이다. 아래 괄호의 영문 이름은 Data Contract v0와 대조하기 위한 임시 표지이며 최종 스키마나 직렬화 키가 아니다. 빈 항목을 두지 말고 `해당 없음`과 `미확인`을 구분한다.

## 조사 상태 (`audit_status`)

[candidate / sampled / reviewed / rejected 중 하나와 상태를 판단한 이유]

## 임시 소스 식별자 (`source_id`)

[이 파일명과 같은 소문자 kebab-case 식별자]

## 소스 이름 (`source_name`)

[공식 표시 이름]

## 소스 분류 (`source_class`)

[official_guidance / position_statement / peer_reviewed_primary / peer_reviewed_review / dataset_definition 중 하나. 이 범위 밖이면 legacy 또는 Stretch임을 표시]

## 발행·배포 주체 (`publisher`)

[발행자, 배포자, 원저작자가 다르면 각각 구분]

## 공식 주소 (`canonical_url`)

[공식 랜딩 페이지 또는 공식 문서 URL]

## 확인일 (`accessed_at`)

[YYYY-MM-DD. 필요한 경우 시간과 시간대]

## 확인한 범위 (`scope_observed`)

[전체 규모와 실제로 확인한 표본을 구분하여 건수, 기간, 언어, 문서 범위를 설명]

## 접근 방식 (`access_method`)

[공개 HTML, 공식 PDF, 공식 API, 로그인, 다운로드 등 실제 확인 방법]

## 수집·접근 제약 (`collection_constraints`)

[robots.txt, ToS, 인증, rate limit, 기술적 제한, 금지 사항과 근거 URL. 없다고 판단했다면 확인 범위도 설명]

## 라이선스 기록 (`license_record`)

[라이선스명·버전, 권리자, 적용 대상, 공식 근거 URL과 확인일]

[접근, 자동 수집, 로컬 저장, 변형·파생, RAG 이용, 원문 재현, 재배포, 상업 이용을 각각 구분하여 허용·금지·미확인과 조건을 설명]

[PMC 자료라면 (1) PMC Open Access Subset 또는 공식 OA 제공 상태와 (2) 논문별 라이선스·재사용 조건을 별도로 기록. 무료 열람 여부만으로 허용 판정 금지]

## 콘텐츠 품질 (`content_quality`)

[문서 구조, 내용의 권위·구체성, 결측, 중복, 편향, 표본에서 발견한 품질 문제]

## Locator 후보 (`locator_candidates`)

우선 조사 대상: [공식 HTML / 공식 PDF / 학술 논문 / 데이터셋 정의 페이지]

### 후보 1: [사람이 이해할 수 있는 이름]

- 종류(`kind`): [임시 locator 종류]
- 구성요소(`parts`): [URL, 절, 제목, 페이지, 표·그림, DOI, 데이터셋·레코드 식별자 등]
- 정밀도(`precision`): [찾을 수 있는 단위와 예상 오차]
- 안정성(`stability`): [개정, 이동, 삭제로 깨질 조건과 보완 식별자]

[필요하면 같은 네 항목으로 후보를 추가. video-time-range는 legacy YouTube 조사에만 사용]

## 예상 용도 (`intended_role`)

[정답 기준, 정책 검증, 개념 정의, 평가 기준, 데이터셋 정의 등 이번 MVP에서의 역할]

## 위험과 미확인 사항 (`risks_and_unknowns`)

[법적·기술적·품질상 위험, 충돌하는 근거, 확인하지 못한 질문과 후속 확인 작업]

## 조사 결론 (`recommendation`)

[proceed / proceed_with_conditions / hold / reject 중 하나]

[결론의 근거와 반드시 지켜야 할 조건]

## 근거 링크 (`evidence_links`)

- [공식 문서 또는 약관 이름 — URL — 확인일 — 이 링크가 뒷받침하는 판단]
- [필요한 만큼 추가. 근거가 없으면 `미확인`]

## 조사 메모 (`audit_notes`)

[조사 방법, 표본 선택법, 재현 가능한 최소 명령, 변경 이력, 후속 조사자에게 필요한 메모. 원문·대량 추출물과 로컬 절대경로는 기록하지 않음]
