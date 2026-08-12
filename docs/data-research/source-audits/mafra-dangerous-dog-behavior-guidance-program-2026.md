# Source audit: 맹견, 개물림 사고견 행동지도 프로그램 개발 및 보급

> 이 문서는 사람이 검토하는 조사 기록이다. 괄호의 영문 이름은 Data Contract v0와 대조하기 위한 임시 표지이며 스키마나 직렬화 키가 아니다. 모든 판단은 provisional이며 후속 법률·의미 검토가 필요하다.

## 조사 상태 (`audit_status`)

`reviewed` — 공식 보도자료 HTML, 게시 메타데이터, 공공누리 표시와 연결 안내를 사람이 확인했다.

## 임시 소스 식별자 (`source_id`)

`mafra-dangerous-dog-behavior-guidance-program-2026`

## 소스 이름 (`source_name`)

맹견, 개물림 사고견 행동지도 프로그램 개발 및 보급

## 소스 분류 (`source_class`)

`official_guidance`

## 발행·배포 주체 (`publisher`)

발행·배포: 대한민국 농림축산식품부 동물복지정책국.

## 공식 주소 (`canonical_url`)

https://www.mafra.go.kr/bbs/home/792/577782/artclView.do

## 확인일 (`accessed_at`)

2026-08-12 (Asia/Seoul)

## 확인한 범위 (`scope_observed`)

2026-04-29 게시된 한국어 보도자료 1건의 제목, 발행부서, 본문, 공공누리 표시를 확인했다. 법률에 따른 교육명령 대상과 프로그램의 5개 영역·20개 세부 항목이라는 구성 설명까지만 조사했다.

## 접근 방식 (`access_method`)

농림축산식품부 공개 HTML을 브라우저로 열람했다. 첨부 원문이나 파일은 내려받지 않았다.

## 수집·접근 제약 (`collection_constraints`)

공개 열람은 가능하다. 자동 수집의 robots.txt·rate limit·사이트 약관은 이번 소량 수동 조사에서 미확인이다. 원문 대량 수집은 범위 밖이며 공공누리 조건과 사이트 운영 정책을 별도로 따라야 한다.

## 라이선스 기록 (`license_record`)

페이지에 공공누리 제1유형인 `출처표시`가 표시되어 있다. 공식 유형 설명은 https://www.kogl.or.kr/info/license.do 에서 확인했다(2026-08-12). 권리자는 농림축산식품부로 표시되나, 첨부물·제3자 요소는 각 표시를 다시 확인해야 한다.

- 접근: 공개 HTML 열람 가능.
- 자동 수집: 미확인.
- 로컬 저장·변형·RAG 이용·재배포·상업 이용: 공공누리 제1유형의 출처표시 조건을 전제로 검토 가능. 이번 체크포인트에서는 메타데이터와 자체 요약만 저장한다.
- 원문 재현: 가능 범위를 넓게 추정하지 않고, 출처·라이선스 표시 및 제3자 권리 확인 전에는 보류한다.

## 콘텐츠 품질 (`content_quality`)

국가 안전관리 정책과 프로그램 구성의 1차 공식 설명이라는 권위가 있다. 효과를 비교한 연구 설계·성과 지표·개별 반려견 적용 기준은 제공하지 않으므로 훈련 효과 자료로는 불충분하다.

## Locator 후보 (`locator_candidates`)

우선 조사 대상: 공식 HTML

### 후보 1: 게시물 URL과 본문 소제목

- 종류(`kind`): `official-web-section`
- 구성요소(`parts`): canonical URL, 게시일, 본문 소제목 또는 해당 문단의 첫 문장
- 정밀도(`precision`): 프로그램 대상·구성 설명이 있는 문단 단위
- 안정성(`stability`): 문구 개정이나 CMS 이동 시 깨질 수 있어 게시물 번호 `577782`와 제목을 함께 보존

## 예상 용도 (`intended_role`)

국가 차원의 안전관리 대상과 행동지도 프로그램 구성에 대한 `policy_context`로만 사용한다.

### 독립 주장 후보 (`provisional evidence relevance`)

- 해당 프로그램은 법률에 따른 교육명령 대상인 맹견 또는 개물림 사고견을 위한 국가 안전관리 맥락에서 개발되었다.
- 공식 설명은 해당 프로그램을 5개 분야인 접근 공격성, 놀람 촉발, 두려움 촉발, 사회적 공격성, 흥분 촉발로 구분하며, 각 분야별 4개 세부항목, 총 20개 항목으로 구성된다고 제시한다.

## 위험과 미확인 사항 (`risks_and_unknowns`)

교육 프로그램 전체 매뉴얼, 시행 성과, 효과 평가 설계는 미확인이다. 프로그램 구성 설명을 일반 보호자의 자가 훈련 절차나 효과 보장으로 확대하면 정책 문서의 범위를 벗어난다. 세부 문구를 상담 taxonomy에 연결하려면 `needs semantic review`이다.

## 조사 결론 (`recommendation`)

provisional recommendation: `proceed_with_conditions`

### provisional reuse assessment

공공누리 제1유형 표시가 있는 공식 HTML의 메타데이터와 자체 요약은 출처표시 조건 아래 검토 가능하다. 첨부물과 제3자 요소는 별도 권리 확인이 필요하다.

### provisional evidence relevance

국가 안전관리 대상과 프로그램 구조에는 관련성이 높지만, 개별 보호자 훈련의 효과 근거에는 관련성이 없다.

### 허용 가능한 claim scope

발행기관, 게시일, 법적 안전관리 맥락, 공식 페이지가 밝힌 프로그램 구성만 허용한다. 개별 반려견의 훈련 단계·처방·효과 주장은 허용하지 않는다.

## 근거 링크 (`evidence_links`)

- 농림축산식품부 보도자료 — https://www.mafra.go.kr/bbs/home/792/577782/artclView.do — 2026-08-12 — 발행기관, 날짜, 프로그램 대상·구성, 공공누리 표시
- 공공누리 이용조건 — https://www.kogl.or.kr/info/license.do — 2026-08-12 — 제1유형의 출처표시 조건

## 조사 메모 (`audit_notes`)

원문·첨부 파일을 저장하지 않고 공개 페이지를 수동 조사했다. 이 문서는 정책 맥락 후보를 기록하며 훈련 상담용 사실 채택에는 별도 의미 검토가 필요하다.
