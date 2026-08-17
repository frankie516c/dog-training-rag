# YouTube 훈련 데이터 파이프라인 트러블슈팅

작성일: 2026-08-17
프로젝트: `dog-training-rag`
범위: YouTube Data API 메타데이터 수집부터 후보 분류, Human-in-the-loop 검토, yt-dlp 자동 자막 수집, WebVTT 정규화와 멱등 실행까지

## 전체 파이프라인

```text
YouTube Data API 메타데이터 수집
  -> EXCLUDE / REVIEW / CANDIDATE 자동 분류
  -> Human-in-the-loop 검토
  -> APPROVED 영상 선택
  -> 이용 허가 확인
  -> yt-dlp로 ko-orig 자동 자막 VTT 수집
  -> WebVTT 파싱 및 rolling caption 중복 제거
  -> 결정론적 JSONL 정규화
  -> 재실행 시 정상 결과 건너뜀
```

이 문서는 실제 구현 과정에서 발생한 문제를 시간 순서대로 기록한다. 각 항목은 증상, 원인, 선택한 해결 방법, 검증 결과와 학습 포인트를 포함한다.

---

## Part 1 — YouTube Data API 후보 수집과 사람 검토

### 1. 목표와 최종 결과

보듬TV 공개 영상 전체를 무작정 시청하거나 자막부터 수집하지 않고, YouTube Data API로 메타데이터를 가져와 훈련 관련성이 높은 영상만 검토 대상으로 줄이고자 했다.

최종 흐름은 다음과 같다.

```text
YouTube Data API
→ 메타데이터 수집
→ EXCLUDE / REVIEW / CANDIDATE 자동 분류
→ 사람 검토
→ APPROVED / PENDING / REJECTED 상태 보존
```

최신 영상 200개를 대상으로 한 최종 자동 분류 결과는 다음과 같다.

| 분류 | 개수 | 의미 |
|---|---:|---|
| EXCLUDE | 133 | 쇼츠·예능 등 명백한 비대상 |
| REVIEW | 55 | 자동으로 확정하기 어려워 사람 검토 필요 |
| CANDIDATE | 12 | 훈련 또는 안전·행동 대응 자료일 가능성이 높은 후보 |

CANDIDATE 12개 중 대표 영상 3개를 직접 확인했고, 모두 구체적인 훈련 설명과 실행 방법이 있어 `APPROVED`로 판정했다.

---

### 2. 문제 1 — 모든 영상이 훈련 영상처럼 분류됨

#### 하려던 일

영상 제목, 설명, 태그에 훈련 관련 키워드가 있으면 `TRAINING`으로 분류하려고 했다.

#### 발생한 현상

개스트쇼, 견종 소개, 26초 쇼츠까지 `TRAINING`으로 분류됐다.

예시:

- `올해는 이게 내 워터밤이다… [강형욱의개스트쇼]`
- `드디어 견종백과 점수 정리합니다`
- `차라리 내 나이를 욕해`

이 영상들의 판정 근거는 대부분 `훈련`, `교육`이었다.

#### 원인

보듬TV가 영상 주제와 관계없이 거의 모든 영상에 공통 태그로 `훈련`, `교육`을 넣고 있었다. 태그를 실제 내용의 증거로 취급했기 때문에 공통 채널 태그가 강한 오탐 신호가 됐다.

#### 검토한 해결책

- 태그 키워드에 낮은 점수 부여
- 태그와 제목이 함께 일치할 때만 후보로 분류
- 태그를 분류 근거에서 완전히 제외

#### 선택한 방법

태그는 CSV 메타데이터로 보존하되 자동 분류 근거에서는 완전히 제외했다. 제목과 정제된 설명만 훈련 키워드 판정에 사용했다.

#### 검증

- 개스트쇼 영상 → `EXCLUDE`
- 견종백과 영상 → `REVIEW`
- 60초 이하 영상 → CSV에는 보존하되 `EXCLUDE`
- 회귀 테스트를 추가하고 전체 테스트 11개 통과

#### 한 줄 학습

> 데이터에 존재하는 필드라고 해서 모두 유효한 분류 신호는 아니다. 반복되는 공통 태그는 정보량이 거의 없다.

---

### 3. 문제 2 — 설명의 단순 키워드가 오탐을 계속 만듦

#### 하려던 일

태그를 제외한 뒤 제목과 설명에서 `산책`, `훈련`, `교육`, `짖음` 같은 키워드를 찾아 훈련 영상을 선별하려고 했다.

#### 발생한 현상

최신 200개에서 `TRAINING`이 24개 나왔지만 실제로는 다음과 같은 비훈련 영상이 포함됐다.

- `국내 최장수견 나오미의 장수 비결`
- `견종백과 아키타이누편`
- `강아지와 미국 한 달 살기`
- `1년반 만에 라이브 켰습니다`
- `저 미국 갑니다`

#### 원인

설명에 `산책`이나 `훈련`이 한 번 등장한 것만으로 확정했기 때문이다. 키워드가 등장한 문맥이 실제 교육 방법인지, 단순한 일정·견종 특성·홍보 문구인지 구별하지 못했다.

#### 선택한 방법

자동 분류의 역할을 “훈련 영상 확정”에서 “검토 우선순위 지정”으로 변경했다.

- `TRAINING`을 `CANDIDATE`로 변경
- 설명 키워드만 일치하면 `REVIEW`
- `퍼피교육`, `주니어 교육` 같은 제목·재생목록 신호만 강한 근거로 사용
- 60초 이하는 `EXCLUDE`, 61~179초는 자동 확정하지 않고 `REVIEW`
- `안고독한 훈련사`처럼 이름에 훈련이 들어가지만 예능성인 시리즈는 강한 근거에서 제외

#### 결과

| 개선 전 | 개선 후 |
|---|---|
| EXCLUDE 72 | EXCLUDE 135 |
| REVIEW 104 | REVIEW 54 |
| TRAINING 24 | CANDIDATE 11 |

기존 훈련 후보 중 브이로그·견종백과·라이브 등 12개가 `REVIEW`로 내려갔고, 62초 쇼츠 1개는 `EXCLUDE`로 이동했다.

#### 한 줄 학습

> 키워드가 존재한다는 사실보다 어디에, 어떤 문맥으로 등장했는지가 더 중요하다.

---

### 4. 문제 3 — 영상 설명에서 본문과 홍보 문구가 섞임

#### 하려던 일

영상의 `description`을 활용하여 제목만으로 판단하기 어려운 훈련 내용을 찾으려고 했다.

#### 발생한 현상

설명에는 다음 정보가 한 필드에 섞여 있었다.

- 영상 내용 소개
- 교육 내용과 번호 목록
- 타임스탬프 챕터
- 출연 모집
- SNS와 쇼핑몰 URL
- 해시태그
- 번역 자막 업체 홍보
- 저작권·비즈니스 문의

특히 출연 모집 영역의 `[퍼피교육]`이 실제 영상 내용처럼 분류 근거로 들어갈 수 있었다.

#### 선택한 방법

설명을 구조적으로 분리했다.

- `description_intro`: 첫 챕터 또는 홍보 영역 전까지의 원문 소개
- `chapters`: `timestamp`, `start_seconds`, `title`을 가진 JSON 배열
- `content_signals`: 제목·소개·챕터에서 실제로 발견한 원문 근거

URL, 해시태그, 모집·SNS·비즈니스 문의, 할인·특가, 번역·저작권 반복 문구는 분류 대상에서 제외했다. 원문을 임의로 요약하지 않고 재현 가능한 규칙으로만 잘라냈다.

#### 검증 결과

- 전체 200개 중 챕터 보유 영상: 32개(16%)
- CANDIDATE 11개: 모두 챕터 보유
- REVIEW 중 안전·행동 대응 영상 1개를 추가 발견
- 최종 분류: EXCLUDE 133 / REVIEW 55 / CANDIDATE 12

추가 후보:

```text
'길에서 사나운 개를 만났다면?' 어떻게 해야 할지 강형욱이 알려드립니다
```

`개가 달려들 때`, `개가 물었을 때`, `내 반려견에게 달려들 때` 같은 구체적인 챕터가 있어 CANDIDATE로 승격했다.

#### 한 줄 학습

> 반정형 텍스트는 통째로 검색하지 말고 본문·구조·홍보 영역을 분리해야 신뢰할 수 있는 신호가 된다.

---

### 5. 문제 4 — 자동 재수집이 사람의 검토 결과를 지울 수 있음

#### 하려던 일

CANDIDATE를 사람이 보고 `APPROVED`, `PENDING`, `REJECTED`로 관리하려고 했다.

#### 발생 가능한 문제

자동 생성되는 메타데이터 CSV에 사람이 직접 `APPROVED`를 입력하면 다음 API 수집 시 CSV가 새로 생성되면서 다시 `PENDING`으로 초기화될 수 있다.

#### 원인

재생성 가능한 자동 데이터와 다시 만들기 어려운 사람의 판단을 같은 파일에서 관리하려 했기 때문이다.

#### 선택한 방법

자동 데이터와 사람 검토 데이터를 분리했다.

```text
bodeum_youtube_metadata.csv
→ API로 다시 생성 가능한 데이터

bodeum_youtube_manual_reviews.csv
→ 사람이 직접 만든 검토 기록
```

`video_id`를 고유 키로 사용해 review ledger를 Upsert하도록 구현했다.

- 신규 후보: `PENDING`으로 추가
- 기존 후보: 제목과 자동 분류만 최신 값으로 갱신
- 사람이 입력한 상태·이유·날짜: 보존
- 후보에서 다른 분류로 이동해도 기존 검토 기록 삭제 금지
- 여러 번 실행해도 중복 행 생성 금지

#### 검증 결과

- 전체 ledger: 12개
- 고유 `video_id`: 12개
- 중복: 0개
- APPROVED: 3개
- PENDING: 9개
- 재동기화 후에도 승인 상태와 검토 사유 보존
- 전체 테스트 27개 통과

#### 한 줄 학습

> 자동으로 재생성할 수 있는 데이터와 사람이 비용을 들여 만든 판단 데이터는 수명주기와 저장 위치를 분리해야 한다.

---

### 6. 문제 5 — `caption=true`인데 API로 자막을 받을 수 없음

#### 하려던 일

메타데이터에서 `caption=true`인 영상의 자막을 YouTube Data API로 이어서 가져오려고 했다.

#### 발생한 문제

`caption=true`는 자막이 존재한다는 사실만 나타낸다. 공개 영상이라도 Data API의 `captions.download`는 해당 영상을 편집할 권한이 있는 OAuth 계정을 요구한다.

또한 `licensed_content=true`도 영상이나 자막 재사용 허가를 의미하지 않는다.

#### 선택한 방법

수집 단계를 분리했다.

```text
YouTube Data API
→ 후보 영상 ID와 메타데이터 수집

이용 허가
→ 자막을 가공해도 되는지 확인

허가된 자막 수집 도구
→ 승인된 영상의 자막만 확보
```

보듬TV 측에 학습 목적의 자동생성 자막 사용 허가를 확인한 뒤에야 별도 자막 수집 브랜치로 이동했다. 원본 자막·정제본·청크는 Git에 올리지 않고 코드와 synthetic fixture만 추적하기로 했다.

#### 한 줄 학습

> API로 접근할 수 있다는 사실, 콘텐츠가 공개돼 있다는 사실, 재사용 허가를 받았다는 사실은 서로 다른 조건이다.

---

### 7. 최종 설계에서 분리한 상태

자동 분류와 사람 판단, 이용 허가, 처리 진행 상태는 각각 의미가 다르다.

| 상태 축 | 예시 | 질문 |
|---|---|---|
| `classification` | EXCLUDE / REVIEW / CANDIDATE | 자동 규칙은 이 영상을 어떻게 판단했는가? |
| `review_status` | PENDING / APPROVED / REJECTED | 사람이 내용 가치를 확인했는가? |
| `permission_status` | PENDING / GRANTED / DENIED | 이 자료를 수집·가공해도 되는가? |
| `processing_status` | NOT_STARTED / TRANSCRIBED / CHUNKED / EMBEDDED / FAILED | 파이프라인이 어디까지 진행됐는가? |

자막 처리로 이동하기 위한 조건은 다음과 같다.

```text
review_status == APPROVED
AND
permission_status == GRANTED
```

### 8. 핵심 개념 요약

#### 정밀도와 재현율

- 정밀도: CANDIDATE로 뽑은 영상 중 실제 적합한 영상의 비율
- 재현율: 실제 적합한 영상 중 자동 분류기가 찾아낸 비율
- 현재 전략: CANDIDATE의 정밀도를 높이고 REVIEW로 재현율을 보완

#### Human-in-the-loop

자동화가 후보와 근거를 만들고, 사람의 명시적인 승인 상태가 다음 자동화의 실행 여부를 결정하는 구조다.

#### 멱등성

같은 동기화를 여러 번 실행해도 영상이 중복되거나 사람의 기존 판정이 사라지지 않는 성질이다.

#### Upsert

`video_id`가 없으면 새로 추가하고, 이미 있으면 최신 자동 정보만 갱신하되 사람의 판정은 보존한다.

#### 데이터 계보와 감사 가능성

분류 결과만 저장하지 않고 제목·설명·재생목록·챕터 중 무엇이 근거였는지 기록하여 나중에 판단 과정을 추적할 수 있게 한다.

### 9. 전체 학습 회고

처음에는 API 응답을 CSV로 저장하면 수집이 끝난다고 생각했다. 실제로는 다음 질문을 계속 확인해야 했다.

1. 가져온 필드가 실제로 유효한 신호인가?
2. 자동 분류가 틀렸을 때 어떤 데이터가 원인이었는가?
3. 자동화가 확정해야 하는가, 사람에게 우선순위만 제공해야 하는가?
4. 재실행했을 때 중복과 사람의 검토 결과를 어떻게 보호하는가?
5. 기술적으로 접근 가능한 데이터와 사용 허가된 데이터는 같은가?

이번 작업은 단순한 YouTube 크롤링이 아니라 다음 파이프라인을 설계한 과정이었다.

> API 기반 데이터 수집 → 구조적 정제 → 규칙 기반 후보 분류 → Human-in-the-loop 검토 → 이용 허가 게이트 → 향후 RAG 적재



---

## Part 2 — APPROVED 영상 자막 수집과 WebVTT 정규화

### 1. 문서 범위

이 문서는 YouTube Data API로 분류한 영상 중 사람이 `APPROVED`한 영상만 대상으로 다음 파이프라인을 구현하며 발생한 문제와 해결 과정을 기록한다.

```text
Review ledger
  -> APPROVED video_id 선택
  -> yt-dlp로 ko-orig 자동 자막 VTT 수집
  -> WebVTT 파싱
  -> rolling caption 중복 제거
  -> JSONL 정규화
  -> 재실행 시 기존 정상 결과 건너뜀
```

범위에 포함하지 않은 작업:

- 영상·오디오 다운로드
- ASR 오탈자 교정
- 문장 병합
- 챕터 연결
- RAG 청킹과 임베딩
- Airflow 스케줄링

---

### 2. `ko`가 아니라 `ko-orig`를 선택한 이유

#### 증상

한국어 영상이므로 처음에는 자막 언어를 단순히 `ko`로 지정할 수 있다고 생각했다.

#### 원인

yt-dlp에서 YouTube 자동 생성 한국어 원문 자막은 `ko-orig`로 노출될 수 있다. `ko`와 `ko-orig`는 항상 같은 트랙이라고 가정할 수 없다.

#### 해결

원문 자동 자막 트랙인 `ko-orig`를 명시했다.

```powershell
uv run yt-dlp `
  --no-playlist `
  --skip-download `
  --write-auto-subs `
  --sub-langs "ko-orig" `
  --sub-format "vtt" `
  --output "data/raw/youtube/subtitles/%(id)s.%(ext)s" `
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

필요하면 영상별 제공 자막 목록을 먼저 확인한다.

```powershell
uv run yt-dlp --list-subs "https://www.youtube.com/watch?v=VIDEO_ID"
```

#### 학습 포인트

언어 코드는 사람이 예상해서 고르는 값이 아니라, 실제 영상에서 yt-dlp가 노출한 자막 트랙을 확인하고 선택해야 한다.

---

### 3. `--js-runtimes node`를 PowerShell 명령으로 단독 실행한 오류

#### 증상

다음 입력에서 PowerShell 파서 오류가 발생했다.

```powershell
--js-runtimes node
```

```text
단항 연산자 '--' 뒤에 식이 없습니다.
예기치 않은 'js-runtimes' 토큰입니다.
```

#### 원인

`--js-runtimes`는 독립 실행 명령이 아니라 yt-dlp에 전달하는 옵션이다. PowerShell은 줄의 첫 번째 `--`를 실행할 명령으로 해석할 수 없다.

#### 해결

yt-dlp 명령 안에 옵션을 포함했다.

```powershell
uv run yt-dlp `
  --js-runtimes node `
  --no-playlist `
  --skip-download `
  --write-auto-subs `
  --sub-langs "ko-orig" `
  --sub-format "vtt" `
  --output "data/raw/youtube/subtitles/%(id)s.%(ext)s" `
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

#### 학습 포인트

CLI 옵션은 실행 프로그램 뒤에 붙는다.

```text
실행 프로그램 + 옵션 + 입력값
yt-dlp       + --js-runtimes node + URL
```

---

### 4. ffmpeg·impersonation 경고가 표시됨

#### 증상

자막 다운로드 중 다음 경고가 표시됐다.

- `ffmpeg not found`
- impersonation target을 사용할 수 없음

#### 판단

이번 실행은 `--skip-download`와 `--write-auto-subs`를 사용한 VTT 자막 전용 작업이었다. 실제 VTT 파일이 정상적으로 생성됐으므로 해당 경고는 이번 작업의 차단 오류가 아니었다.

#### 대응 원칙

- 명령 종료 여부만 보지 않고 결과 VTT의 존재와 크기를 확인한다.
- 자막 수집이 성공했다면 ffmpeg 설치를 이번 기능의 필수 범위로 확대하지 않는다.
- 이후 오디오 추출이나 포맷 병합이 필요해질 때 ffmpeg를 별도로 설치한다.

```powershell
Get-Item data\raw\youtube\subtitles\VIDEO_ID.ko-orig.vtt
```

#### 학습 포인트

경고는 실패와 다르다. 현재 기능의 성공 조건을 먼저 정의하고 그 조건으로 판정해야 한다.

---

### 5. VTT에 같은 문장이 반복됨

#### 증상

원본 VTT에는 앞 cue의 문장이 다음 cue에 반복되거나, 기존 문장 뒤에 새로운 단어가 붙는 형태가 다수 존재했다.

```text
A
A
A B
B
B C
C
C D
D
```

이를 그대로 저장하면 같은 발화가 여러 번 반복된다.

#### 원인

YouTube 자동 자막은 화면에 이미 표시된 단어를 유지하면서 새 단어를 추가하는 rolling caption 형식을 사용할 수 있다. 각각의 cue를 독립 문장으로 취급하면 중복이 생긴다.

#### 해결

현재 cue와 바로 이전 cue를 단어 배열로 비교했다.

1. 완전히 같으면 새 텍스트를 출력하지 않는다.
2. `이전 suffix == 현재 prefix`인 가장 긴 구간을 찾는다.
3. 겹치는 부분 뒤에 새로 추가된 단어만 출력한다.
4. 겹치는 부분이 없다면 현재 cue 전체를 출력한다.

위 fixture의 최종 결과는 다음과 같아야 한다.

```text
A B C D
```

#### 핵심 invariant

> 빈 cue가 아닌 모든 cue는 출력할 새 텍스트가 없어도 현재 rolling 상태를 갱신한다.

- 10ms cue도 고유 텍스트가 있으면 보존한다.
- suffix-only cue도 출력 여부와 관계없이 상태를 갱신한다.
- 빈 cue만 rolling 연결을 끊고 상태를 비운다.

#### 학습 포인트

`emitted text`와 `rolling state`는 서로 다르다. 현재 cue에서 출력할 글자가 없더라도 다음 cue 비교를 위한 상태는 갱신해야 한다.

---

### 6. webvtt-py가 일부 cue를 다르게 해석함

#### 증상

실제 VTT의 timing line은 475개였지만, timing 직후의 공백 줄과 payload가 없는 cue 때문에 라이브러리가 일부 block을 예상과 다르게 처리할 수 있었다.

확인된 실제 파일 특성:

- 전체 timing line: 475개
- timing 직후 whitespace-only 줄: 4개
- 실제 빈 payload cue: 3개

#### 원인

WebVTT block 구분은 빈 줄에 민감하다. 라이브러리의 일반적인 파싱 규칙과 YouTube가 생성한 실제 파일의 경계 표현이 완전히 일치하지 않을 수 있다.

#### 해결

원본 파일은 수정하지 않고 인메모리 호환 어댑터만 적용했다.

#### 제한적 whitespace 보정

다음 조건을 모두 만족할 때만 timing 직후의 공백 줄을 메모리에서 제거했다.

- timing line 바로 다음 줄이 whitespace-only
- 그다음 줄에 실제 payload가 존재

전체 빈 줄을 일괄 삭제하지 않았다.

#### 빈 cue sentinel 보정

실제 payload가 전혀 없는 cue에만 고유한 임시 sentinel을 넣었다.

1. 원본에 같은 sentinel이 없는지 확인
2. 인메모리 문자열에 sentinel 삽입
3. webvtt-py 파싱
4. 파싱 직후 sentinel 제거
5. 빈 `raw_text`, `normalized_text`로 복원

#### 파싱 개수 검증

```text
원본의 유효 timing line 수 == 파싱된 cue 수
```

두 값이 다르면 JSONL을 쓰기 전에 오류를 발생시켰다.

#### 학습 포인트

외부 라이브러리를 사용해도 입력 데이터와 라이브러리의 경계 조건은 직접 검증해야 한다. 원본을 고치는 대신, 제한적이고 기록 가능한 호환 계층을 두는 편이 안전하다.

---

### 7. 정규화 결과에서 실제 발화가 누락된 것처럼 보임

#### 증상

최초 결과 보고의 0~30초 표에서 원본에 있던 두 구간이 보이지 않아 rolling 중복 제거가 정상 텍스트까지 삭제한 것으로 의심했다.

#### 조사

회귀 fixture를 실행했을 때 정규화기는 이미 `A B C D`를 정상 출력했다. 실제 JSONL을 직접 검색하자 의심했던 두 segment도 존재했다.

```powershell
Select-String `
  -Path data\processed\youtube\transcripts\Ry3NnrbVjAM.jsonl `
  -Pattern "봉투를","잡을까요" `
  -Encoding UTF8
```

#### 원인

데이터가 누락된 것이 아니라 최초 보고용 표에서 두 행이 빠진 것이었다. 또한 Windows PowerShell에서 `Get-Content` 실행 시 `-Encoding UTF8`을 생략하면 한글 검색이 실패할 수 있어 혼동이 추가됐다.

#### 해결

- 요약 보고서가 아니라 실제 JSONL을 직접 확인했다.
- PowerShell에서 UTF-8을 명시했다.
- rolling state invariant를 코드 구조상 명확히 했다.
- 실제 자막 문장을 사용하지 않은 synthetic 회귀 테스트를 추가했다.

#### 학습 포인트

다음 세 가지는 서로 다른 검증 대상이다.

| 검증 대상 | 확인하는 것 |
|---|---|
| 통계 | cue·segment 개수의 전체적인 변화 |
| 보고서 | 사람이 읽기 위한 일부 표본 |
| 실제 JSONL | 파이프라인이 저장한 최종 데이터 |

통계가 같다고 내용이 정확한 것은 아니며, 보고서에 없다고 실제 데이터에도 없는 것도 아니다.

---

### 8. APPROVED 영상만 일괄 처리하기

#### 요구사항

모든 후보 영상을 다운로드하지 않고 human review ledger에서 다음 조건인 영상만 처리해야 했다.

```text
review_status == APPROVED
```

#### 구현 원칙

- ledger 행 순서 유지
- `video_id`만 다운로드 식별자로 사용
- YouTube video ID 형식 `[A-Za-z0-9_-]{11}` 검증
- 중복 ID가 있으면 ledger 오류로 처리
- 제목·설명·자막 원문을 로그에 출력하지 않음
- 한 영상이 실패해도 다음 영상은 계속 처리

#### 학습 포인트

Human-in-the-loop의 승인 상태가 파이프라인의 실행 조건이 됐다. 사람이 내린 결정을 별도 ledger에 보존하면 데이터 재수집 시에도 승인 결과가 사라지지 않는다.

---

### 9. 멱등성을 파일 존재 여부만으로 판단할 수 없음

#### 초기 위험

단순히 파일이 존재한다는 이유로 건너뛰면 다음 문제가 발생할 수 있다.

- VTT가 일부만 다운로드된 파일일 수 있음
- JSONL이 빈 파일일 수 있음
- JSONL 한 줄이 깨진 JSON일 수 있음
- 다른 `video_id`의 결과가 잘못 저장됐을 수 있음

#### 해결: 상태별 처리

| Raw VTT | JSONL | 기본 동작 |
|---|---|---|
| 정상 | 정상 | `SKIPPED` |
| 정상 | 없음 또는 비정상 | 네트워크 없이 기존 VTT 재정규화 |
| 없음 또는 비정상 | 무엇이든 | 다운로드 후 정규화 |
| `--force` | 무엇이든 | 재다운로드 후 정규화 |

JSONL 검증 조건:

- 행이 1개 이상
- 모든 비어 있지 않은 행이 JSON 객체
- `video_id`가 처리 대상과 일치
- `start_ms`, `end_ms`가 정수
- `0 <= start_ms <= end_ms`
- `text`가 문자열
- `source_cue_indices`가 배열

#### 빈 파일 검증 시 주의

“모든 행이 정상이다”만 검사하면 빈 파일은 검사할 행이 없기 때문에 잘못 통과할 수 있다. 따라서 반드시 `행이 1개 이상`이라는 조건을 별도로 둬야 한다.

#### 학습 포인트

멱등성은 “파일이 있으니 건너뛴다”가 아니라 “이미 생성된 결과가 정상임을 검증한 뒤 필요한 단계만 수행한다”는 의미다.

---

### 10. 실패한 다운로드가 기존 정상 VTT를 덮어쓸 위험

#### 위험

`--force` 또는 재다운로드 중 네트워크 오류가 발생하면 기존 정상 VTT 대신 불완전한 파일이 남을 수 있다.

#### 해결

1. 영상별 임시 경로에 다운로드
2. 파일 존재와 `WEBVTT` 헤더 검증
3. 검증 성공 후 `os.replace`로 최종 raw VTT 교체
4. 실패하면 임시 파일 정리
5. 기존 정상 파일은 유지

JSONL도 기존 정규화기의 임시 파일 작성 후 `os.replace` 방식을 재사용했다.

#### 학습 포인트

원자적 쓰기는 결과 파일이 “완성된 이전 버전” 또는 “완성된 새 버전” 중 하나만 갖도록 만든다. 중간 상태의 파일이 최종 경로에 남는 것을 방지한다.

---

### 11. `--dry-run`이 처리 예정 항목을 성공으로 표시함

#### 증상

최초 dry-run 결과가 다음처럼 출력됐다.

```text
approved: 3 success: 2 skipped: 1 failed: 0
```

실제로는 네트워크 호출과 파일 쓰기를 하지 않았으므로 `success: 2`는 오해를 유발했다.

#### 원인

일반 실행의 처리 결과 상태를 dry-run에서도 그대로 재사용했다. “실제로 성공함”과 “실행하면 처리할 예정임”이 구분되지 않았다.

#### 해결

dry-run 전용 상태와 집계를 분리했다.

```text
approved: 3 would_process: 2 would_skip: 1 failed: 0
dry_run: WOULD_DOWNLOAD=1 WOULD_NORMALIZE=1 WOULD_SKIP=1
```

실제 파일 3개가 모두 생성된 이후의 dry-run은 다음과 같았다.

```text
approved: 3 would_process: 0 would_skip: 3 failed: 0
dry_run: WOULD_DOWNLOAD=0 WOULD_NORMALIZE=0 WOULD_SKIP=3
```

#### 학습 포인트

dry-run은 미래 계획을 보여주는 기능이다. 실제 실행 결과인 `SUCCESS`와 예정 상태인 `WOULD_*`를 같은 용어로 표현하면 운영자가 잘못 판단할 수 있다.

---

### 12. 실제 재실행으로 멱등성 검증

#### 최초 실행

```text
approved: 3 success: 2 skipped: 1 failed: 0
exit code: 0
```

- 기존 정상 결과 1개는 건너뜀
- 신규 영상 2개는 다운로드와 정규화 성공

#### 두 번째 실행

```text
approved: 3 success: 0 skipped: 3 failed: 0
exit code: 0
```

- 세 영상 모두 정상 결과가 존재
- 추가 네트워크 처리 없이 모두 건너뜀

#### 생성 결과

```text
raw VTT: 3개
normalized JSONL: 3개
failed: 0개
```

#### 학습 포인트

단위 테스트는 멱등성 규칙을 코드 수준에서 검증한다. 동일 명령의 실제 재실행은 현재 파일과 네트워크 경계까지 포함한 통합 수준의 멱등성을 검증한다.

---

### 13. Git 출력에서 혼동한 부분

#### `git diff --name-status`에 새 파일이 안 보임

`git diff`는 기본적으로 아직 Git이 추적하지 않는 untracked 파일을 표시하지 않는다. 새 스크립트와 테스트는 `git status`로 확인해야 한다.

```powershell
git status --short
```

#### LF → CRLF 경고

```text
LF will be replaced by CRLF the next time Git touches it
```

Windows 작업 트리의 줄바꿈 변환 안내이며 이번 작업의 `git diff --check` 실패가 아니었다. 별도의 줄바꿈 정책 변경을 이번 기능 범위에 섞지 않았다.

#### 데이터 파일 제외 확인

최종 Git 상태에는 수집기와 테스트만 나타났으며 VTT와 JSONL은 기존 `data/` 규칙으로 제외됐다.

```text
?? scripts/collect_approved_youtube_captions.py
?? tests/test_collect_approved_youtube_captions.py
```

#### 학습 포인트

- 추적 파일 변경: `git diff`
- stage된 변경: `git diff --cached`
- untracked 포함 전체 상태: `git status`

각 명령이 보여주는 범위가 다르다.

---

### 14. 최종 검증 체크리스트

#### 자막 수집

- [x] `APPROVED` 영상만 선택
- [x] `ko-orig` 자동 자막만 수집
- [x] 영상·오디오 다운로드 없음
- [x] 영상별 실패 격리
- [x] 실패가 있으면 exit code 1

#### 정규화

- [x] 원본 VTT 수정 없음
- [x] timing line과 parsed cue 개수 일치
- [x] rolling caption 중복 제거
- [x] 빈 cue와 10ms cue 정책 테스트
- [x] JSONL 원자적 쓰기
- [x] 같은 입력의 결정론적 출력

#### 멱등성

- [x] 정상 VTT와 JSONL이면 skip
- [x] JSONL만 비정상이면 네트워크 없이 재정규화
- [x] VTT가 비정상이면 임시 다운로드 후 교체
- [x] 두 번째 실제 실행에서 3개 모두 skip
- [x] dry-run 상태와 실제 success 상태 구분

#### Git·보안

- [x] raw VTT 제외
- [x] processed JSONL 제외
- [x] API 키·인증 정보 출력 없음
- [x] 자막 전체 원문 로그 출력 없음
- [x] 수집기와 테스트만 코드로 추적

---

### 15. 이번 단계에서 얻은 설계 원칙

1. **수집과 정규화를 분리한다.**
   네트워크 실패와 파싱 실패를 서로 다른 문제로 진단할 수 있다.

2. **원본은 보존하고 가공 결과를 별도로 만든다.**
   정규화 규칙이 바뀌어도 원본 VTT에서 다시 처리할 수 있다.

3. **사람의 승인을 실행 조건으로 사용한다.**
   후보 분류가 곧 데이터 사용 승인을 의미하지 않게 한다.

4. **멱등성은 상태 검증을 포함한다.**
   파일 존재 여부만 확인하지 않고 파일의 최소 구조와 대상 ID를 검증한다.

5. **통계와 실제 내용을 함께 검증한다.**
   cue 수와 단어 수뿐 아니라 JSONL의 특정 구간도 직접 확인한다.

6. **dry-run은 실행 결과와 다른 언어를 사용한다.**
   `SUCCESS`가 아니라 `WOULD_*`로 계획임을 명확히 한다.

7. **자동화 가능한 프로그램은 종료 코드가 계약이다.**
   Airflow 같은 상위 실행기가 성공과 실패를 판단할 수 있어야 한다.
