# 데이터 소스 조사 안내

## 조사 목적

이 디렉터리는 검색 파이프라인을 만들기 전에 각 후보 소스의 권위, 접근 방식, 재사용 조건, 콘텐츠 품질, locator 재현 가능성을 사람이 검토하기 위한 곳이다. 조사 결과는 [Data Contract v0](../data-contract-v0.md)의 임시 규약을 따르며, 최종 데이터 스키마나 수집 승인을 의미하지 않는다.

## 우선 출처

이번 MVP는 다음 출처를 우선 조사한다.

1. 농림축산식품부
2. AVSAB
3. AAHA
4. University of Pennsylvania C-BARQ
5. Wolfram C-BARQ Survey
6. 라이선스가 확인된 PMC OA 논문

우선 `source_class`는 `official_guidance`, `position_statement`, `peer_reviewed_primary`, `peer_reviewed_review`, `dataset_definition`으로 제한한다. 사례·발화, 영상, 커뮤니티와 기존 YouTube 조사 코드는 legacy 또는 Stretch 범위다.

## Source audit 작성 순서

1. `source-audits/_template.md`를 복사하고 파일명을 정한다.
2. 공식 랜딩 페이지에서 소스명, 발행자, canonical URL과 확인일을 기록한다.
3. 확인 범위와 접근 방식을 적고, 자동 수집·인증·rate limit 등 제약을 확인한다.
4. 라이선스, 약관, 권리자, 허용 행위를 공식 근거별로 기록한다. PMC는 OA 제공 상태와 논문별 라이선스를 따로 확인한다.
5. 작은 표본으로 구조·결측·편향과 locator 후보의 정밀도·안정성을 조사한다.
6. 위험과 미확인 사항을 남기고 조건부 결론을 작성한다.
7. 모든 provisional 필드가 작성되었는지 검토한다. 해당하지 않으면 `해당 없음`, 확인하지 못했으면 `미확인`으로 남긴다.

## 파일명 규칙

Source audit은 다음 위치에 둔다.

```text
docs/data-research/source-audits/<source-id>.md
```

`<source-id>`는 소문자 ASCII `kebab-case`를 사용한다. 서비스명만으로 충돌하면 발행자, 문서명, 데이터셋 식별자 또는 판본을 덧붙인다. 한 파일은 한 소스 또는 같은 이용조건을 공유하는 한 데이터셋 릴리스만 다룬다. `_template.md`는 작성 예시가 아니라 복사용 빈 양식이다.

## 사실, 추정, 미확인의 구분

- **사실**: 공식 페이지, 논문 본문, 라이선스, 약관처럼 확인 가능한 근거가 있으며 URL과 확인일을 함께 기록한 내용
- **추정**: 표본이나 간접 근거로 판단한 내용. 문장 앞에 `추정:`을 붙이고 근거와 한계를 설명
- **미확인**: 확인하지 못했거나 근거가 충돌하는 내용. 빈칸 대신 `미확인`으로 기록하고 다음 확인 작업을 명시

`해당 없음`은 해당 필드가 그 소스에 적용되지 않는다는 뜻이므로 `미확인`과 바꾸어 쓰지 않는다.

## 원문 커밋 금지

`data/research/`, `data/raw/`, `data/cache/`, `data/qdrant/`와 다운로드 원문·대량 추출물은 커밋하지 않는다. 자막, PDF 원문, 웹 본문, API 원응답, 대량 레코드, 청크 집합, 임베딩과 벡터 저장소도 포함한다. 조사 문서에는 판단에 필요한 최소 메모와 공식 링크만 남기며 원문을 복원할 수 있는 분량을 옮기지 않는다.

`data/sources/`, `data/processed/`, `data/eval/`, `data/reviews/`는 향후 `EvidenceCard v1`과 저장 정책 승인 후 추적 가능한 산출물 경로가 될 수 있지만, 지금은 만들거나 `.gitignore` 예외를 추가하지 않는다.

## EvidenceCard v1과의 관계

Source audit은 `EvidenceCard v1` 설계를 위한 입력 자료다. 템플릿의 제목, provisional 필드명, 작성 순서와 표현 방식은 최종 카드 필드나 JSON·JSONL·YAML·DB payload 계약이 아니다. 조사 문서를 런타임 데이터로 직접 파싱하거나 임시 필드를 검색 payload로 고정하지 않는다.

## 데이터 CLI 수정 금지 범위

이번 단계에서는 다음 기존 YouTube CLI를 수정하거나 삭제하지 않는다.

```text
scripts/collect_index.py
scripts/check_subs.py
scripts/vtt_stats.py
```

파일 경로와 명령 이름, 인자, TSV 열, 출력 의미·형식, 자막 판별 정책, YouTube 옵션, VTT 처리 로직과 관련 의존성은 동결한다. 이 템플릿은 사람이 작성·검토하는 문서이며 현재 CLI가 읽는 입력 포맷이 아니다. 향후 데이터 CLI가 source audit을 사용하게 만드는 변경은 별도 승인 후 진행한다.
