# Data Contract v0

상태: **조사용 임시 계약**  
적용 범위: 소스 탐색, 접근성·품질·라이선스 조사, locator 가능성 검증  
종료 조건: `EvidenceCard v1`과 그 직렬화 형식이 별도로 승인될 때

이 문서는 데이터 파이프라인의 최종 스키마가 아니다. 여기 적힌 필드명, 값의 형태, 예시 YAML은 조사 결과를 빠뜨리지 않기 위한 작업 메모 규약일 뿐이며, **최종 `EvidenceCard` 필드나 JSON/YAML/DB payload의 직렬화 계약으로 간주하거나 그대로 구현하지 않는다.**

## 1. 조사 결과를 받는 경로

커밋 가능한 조사 결과는 아래 경로에 소스별 Markdown 문서로 받는다.

```text
docs/data-research/source-audits/<source-id>.md
```

- `<source-id>`는 소문자 ASCII `kebab-case`로 정한다. 서비스명만으로 충돌하면 발행자나 데이터셋 식별자를 덧붙인다.
- 한 문서는 한 소스 또는 동일한 이용조건을 공유하는 한 데이터셋 릴리스를 다룬다.
- 여러 소스를 비교한 결론은 `docs/data-research/` 아래 별도 Markdown 문서로 둘 수 있으나, 각 판단이 해당 source audit으로 추적되어야 한다.
- 원문 샘플, 다운로드 파일, 자막, 오디오, 응답 덤프 등 커밋 불가 자료는 다음 로컬 작업 경로에만 둔다.

```text
data/research/<source-id>/
```

현재 커밋 금지 대상은 `data/research/`, `data/raw/`, `data/cache/`, `data/qdrant/`와 다운로드 원문·대량 추출물이다. 현재 `.gitignore`는 `data/` 전체를 제외하지만, 이 문서는 그 상태를 영구 정책으로 확정하지 않는다.

다음 경로는 `EvidenceCard v1`과 저장 정책이 승인된 뒤 provenance와 검토 상태를 갖춘 **추적 가능한 가공 산출물 경로**가 될 수 있다.

```text
data/sources/
data/processed/
data/eval/
data/reviews/
```

이번 체크포인트에서는 위 경로를 만들지 않고 `.gitignore` 예외도 추가하지 않는다. 조사 문서에는 로컬 절대경로나 개인별 파일 경로를 기록하지 않는다.

## 2. Provisional source audit 필드

각 source audit은 아래 항목을 사람이 읽을 수 있는 형태로 기록한다. 해당하지 않는 값은 생략하지 말고 `해당 없음`, 확인하지 못한 값은 `미확인`으로 구분한다.

| 필드 | 기록 내용 |
|---|---|
| `audit_status` | `candidate`, `sampled`, `reviewed`, `rejected` 중 현재 조사 상태 |
| `source_id` | 파일명과 같은 임시 소스 식별자 |
| `source_name` | 데이터셋·사이트·채널·문서의 표시 이름 |
| `source_class` | 이번 MVP의 우선 후보 중 하나. 아래 범위 설명 참고 |
| `publisher` | 게시·배포 주체와 원저작자가 다르면 둘 다 기록 |
| `canonical_url` | 소스의 공식 랜딩 페이지 또는 공식 문서 URL |
| `accessed_at` | 확인일. 날짜가 중요한 판단에는 시간대도 기록 |
| `scope_observed` | 확인한 범위와 대략적 건수·시간·언어·기간. 전체 규모와 표본을 구분 |
| `access_method` | 공개 페이지, 공식 API, 다운로드, 로그인 필요 등 실제 접근 방식 |
| `collection_constraints` | robots.txt, ToS, 인증, rate limit, 기술적·계약상 제한과 확인 URL |
| `license_record` | 4절 원칙에 따른 라이선스·저작권 관찰 기록 |
| `content_quality` | 자막 유형, 정확도, 구조, 중복, 결측, 편향 등 표본에서 본 품질 |
| `locator_candidates` | 원 출처의 근거 위치로 되돌아갈 수 있는 후보 표현. 3절 형식 사용 |
| `intended_role` | 사례 탐색, 정답 기준, 품질 검증, 분포 보정 등 예상 용도 |
| `risks_and_unknowns` | 법적·기술적·품질상 위험과 아직 확인하지 못한 질문 |
| `recommendation` | `proceed`, `proceed_with_conditions`, `hold`, `reject`와 짧은 근거 |
| `evidence_links` | 판단을 뒷받침하는 공식 약관·라이선스·문서 링크와 확인일 |
| `audit_notes` | 조사 방법, 표본 선택법, 재현에 필요한 명령 또는 기타 메모 |

필드 값은 조사 당시 관찰을 보존한다. 추측은 사실처럼 적지 않고 `추정`으로 표시하며, 서로 다른 날짜의 조사 결과를 덮어쓰기보다는 변경 사실과 재확인일을 남긴다.

### 이번 MVP의 source class 범위

이번 MVP에서 우선 조사하는 `source_class` 후보는 다음과 같다.

- `official_guidance`
- `position_statement`
- `peer_reviewed_primary`
- `peer_reviewed_review`
- `dataset_definition`

사례·발화, 영상, 커뮤니티 자료는 현재 Must 범위가 아니다. 기존 YouTube 조사 코드와 그 산출물은 삭제하지 않되 **legacy 또는 Stretch 범위**로 취급하며, 이번 MVP의 우선 source audit이나 검색 파이프라인 입력으로 자동 승격하지 않는다.

### 이번 데이터 조사의 우선 출처

다음 출처부터 source audit을 작성한다.

1. 농림축산식품부
2. AVSAB
3. AAHA
4. University of Pennsylvania C-BARQ
5. Wolfram C-BARQ Survey
6. 라이선스가 확인된 PMC OA 논문

## 3. Locator 후보 표현 방식

Locator는 아직 확정 필드가 아니다. source audit에는 **후보를 순서 있는 목록**으로 기록하고, 후보마다 다음 네 요소를 설명한다.

- `kind`: 위치를 찾는 방법의 임시 이름
- `parts`: 위치 복원에 필요한 구성요소
- `precision`: 기대 정밀도와 오차 또는 범위
- `stability`: URL 변경, 페이지 개정, 삭제 등 깨질 조건과 보완책

이번 MVP의 우선 locator 조사 대상은 **공식 HTML 문서, 공식 PDF, 학술 논문, 데이터셋 정의 페이지**다. 문서의 절·제목·페이지·표·그림·안정적인 fragment 및 논문·데이터셋 식별자를 조합해 원 출처로 돌아갈 수 있는지 먼저 검증한다.

표현 예시는 다음과 같다. 이는 이해를 돕는 표기이며 직렬화 스키마가 아니다. `video-time-range`는 기존 YouTube 조사 자산을 설명하기 위해 남긴 **legacy 예시**이며 이번 MVP의 우선 locator가 아니다.

```yaml
locator_candidates:
  - kind: video-time-range  # legacy 예시
    parts: { canonical_url: "...", start_seconds: 83.2, end_seconds: 96.7 }
    precision: "cue 경계 기준, 약 ±1초"
    stability: "영상 삭제·교체 시 무효; provider id를 함께 보존"
  - kind: document-page-section
    parts: { document_url: "...", edition: "2026", page: 17, heading: "..." }
    precision: "페이지와 절"
    stability: "개정판에서 페이지 이동 가능; 판본과 제목을 함께 보존"
  - kind: dataset-record
    parts: { dataset_id: "...", release: "...", split: "...", record_id: "..." }
    precision: "레코드 단위"
    stability: "릴리스가 바뀌면 record id 재사용 여부 확인 필요"
```

가능하면 사람이 클릭해 확인하는 주소와 기계적으로 재현하는 식별자를 함께 제안한다. 제목이나 인용문처럼 바뀌기 쉬운 텍스트만으로 위치를 나타내지 않으며, locator 후보 안에 원문 본문을 복제하지 않는다.

## 4. 라이선스 기록 원칙

1. **공개 접근과 이용 허락을 구분한다.** 로그인 없이 보인다는 사실을 수집·복제·가공·재배포 허락으로 해석하지 않는다.
2. **관찰 가능한 근거를 남긴다.** 라이선스명, 버전, 권리자, 적용 대상, 공식 URL, 확인일을 기록한다. 화면 문구를 요약하되 필요한 경우 짧은 발췌와 위치만 남긴다.
3. **행위별 범위를 분리한다.** 접근, 자동 수집, 로컬 저장, 변형·파생물, 모델/RAG 이용, 원문 재현, 재배포, 상업 이용의 허용 여부를 한 문장의 “사용 가능”으로 뭉개지 않는다.
4. **약관과 라이선스를 함께 본다.** 콘텐츠 라이선스가 있어도 API·사이트 ToS, robots.txt, 개인정보, 제3자 권리가 별도 제한을 만들 수 있다.
5. **미확인은 허용으로 취급하지 않는다.** 근거가 없거나 충돌하면 `미확인`으로 기록하고, 해당 위험을 해소하기 전에는 대량 추출·영구 적재 대상으로 승격하지 않는다.
6. **조건을 구체화한다.** 저작자 표시, 동일조건변경허락, 비상업, 링크백, 삭제 요청 대응 등 준수 조건을 실행 가능한 문장으로 남긴다.
7. **시점과 판본을 보존한다.** 약관이 바뀔 수 있으므로 확인일과 문서 버전·시행일을 기록한다. 원문 약관 전체를 저장소에 복제하지 않고 공식 링크와 필요한 최소 메모를 남긴다.
8. **개인정보·민감정보는 별도 위험으로 기록한다.** 라이선스가 허용하더라도 개인 식별 정보의 수집·노출이 자동으로 허용되는 것은 아니다.

### PMC 자료의 추가 확인

PMC 자료는 다음 두 조건을 서로 대체할 수 없는 별도 항목으로 확인한다.

1. 해당 자료가 **PMC Open Access Subset**에 포함되거나 공식적으로 OA 제공되는지
2. 해당 논문에 표시된 **개별 라이선스와 구체적인 재사용 조건**이 무엇인지

PMC에서 무료로 열람된다는 사실만으로 다운로드·가공·재사용이 허용된다고 판정하지 않는다. 둘 중 하나라도 미확인이면 `license_record`와 `risks_and_unknowns`에 그대로 표시하고 대량 처리 대상으로 승인하지 않는다.

이 기록은 법률 자문이나 최종 사용 승인서가 아니다. 프로젝트가 공개·상업 서비스로 전환되면 모든 소스를 그 조건에 맞춰 다시 심사한다.

## 5. 원문 및 대량 추출물 커밋 금지

다음 자료는 형식과 용량에 관계없이 Git에 커밋하지 않는다.

- 영상, 오디오, 이미지, PDF·전자책 등 원저작물 파일
- VTT/SRT와 수동·자동·재전사 자막의 원문 또는 실질적으로 복원 가능한 변환본
- 웹 페이지 본문, 게시물·댓글, API 원응답, 데이터셋 레코드의 대량 덤프
- 원문을 이어 붙인 청크 집합, 임베딩·벡터 인덱스, Qdrant 로컬 저장소
- 원자료의 상당 부분을 재구성할 수 있는 캐시·중간 산출물·압축 파일

이 자료들은 필요할 때 `data/research/`, `data/raw/`, `data/cache/`, `data/qdrant/` 중 용도에 맞는 로컬 경로에서만 다루며, `.gitignore` 우회, 강제 추가(`git add -f`), 확장자 변경, 압축·분할로 금지 규칙을 피하지 않는다. 커밋 가능한 것은 코드, 문서, 스키마 초안, 집계 통계, 라이선스·출처 메타데이터, 그리고 원문을 복원할 수 없는 최소한의 합성·비식별 테스트 fixture뿐이다.

`data/sources/`, `data/processed/`, `data/eval/`, `data/reviews/`는 향후 추적 가능성이 검토될 수 있는 경로일 뿐, 현재 커밋 허용 경로가 아니다. `EvidenceCard v1`과 저장 정책이 승인되기 전에는 생성하거나 `.gitignore` 예외를 두지 않는다.

실제 원문 예시가 꼭 필요한 조사 문서에는 판단을 설명하는 최소 길이만 사용하고, 가능하면 요약·해시·길이·오류 유형 같은 비복원적 정보로 대체한다.

## 6. EvidenceCard v1 확정 전 허용되는 데이터 작업

다음 작업만 이 임시 계약 아래에서 진행할 수 있다.

- 후보 소스 발견, 공식 링크 확인, source audit 작성·갱신
- 제목·식별자·게시일·길이·언어·가용성 같은 **메타데이터 전용** 인벤토리와 집계
- 이용조건, 접근 제한, 삭제·변경 가능성, locator 후보의 재현성 조사
- 품질과 처리 가능성을 판단하기 위한 작고 목적이 명시된 표본 검사
- 자막 보유 유형, 오류율, 중복률, 길이 분포 등 원문을 남기지 않는 통계 산출
- 로컬 `data/research/`에서 수행하고 조사 후 폐기 가능한 접근·파싱 실험
- 원문을 포함하지 않는 합성 또는 비식별 fixture로 파서 인터페이스 실험

아직 허용되지 않는 작업은 전체 코퍼스 다운로드·전사·정규화·청킹·임베딩, Qdrant 본 적재, 학습용 데이터셋 생성, 임시 필드를 최종 payload로 고정하는 구현이다. 대량 메타데이터 인덱스는 규모·가용성 조사에 한해 만들 수 있지만 로컬 `data/`에 두며 최종 데이터 모델의 근거로 자동 승격하지 않는다.

## 7. 데이터 CLI 수정 금지 영역

이 체크포인트에서는 문서만 추가한다. 아래 기존 데이터 CLI는 기준선으로 동결하며 수정하지 않는다.

```text
scripts/collect_index.py
scripts/check_subs.py
scripts/vtt_stats.py
```

동결 범위에는 다음이 포함된다.

- 파일 경로와 명령 이름
- positional argument의 개수·순서·의미
- `collect_index.py`가 쓰는 TSV 열 순서와 값의 의미
- stdout의 집계 의미와 사람이 읽는 출력 형식
- 수동자막·자동자막 판별 정책과 YouTube 접근 옵션
- VTT 필터링·롤업 중복 제거·길이 계산 로직
- 이 CLI를 위해 `pyproject.toml`이나 `uv.lock`의 의존성을 바꾸는 일

버그를 발견하면 source audit 또는 별도 이슈에 재현 조건을 기록한다. 수정, 리팩터링, 새 출력 포맷 추가, 최종 `EvidenceCard`에 맞춘 연결은 별도 체크포인트에서 명시적으로 승인한 뒤 진행한다.

## 8. v0에서 확정하지 않는 것

이 문서는 다음을 의도적으로 결정하지 않는다.

- `EvidenceCard v1`의 필수·선택 필드와 명명
- 카드 ID 정책, 중복 제거 키, 버전·갱신 정책
- JSON, JSONL, YAML, Parquet 또는 Qdrant payload 등 직렬화·저장 형식
- 원문과 파생문 사이의 provenance 모델
- 청크 경계, 인용 길이, 임베딩 단위와 검색 payload
- 런타임 검증 스키마와 마이그레이션 정책

위 항목은 source audit 결과와 locator 실험을 검토한 뒤 별도 설계로 확정한다.
