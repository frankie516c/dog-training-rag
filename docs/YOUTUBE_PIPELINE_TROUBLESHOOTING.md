# 보듬TV YouTube 메타데이터 파이프라인 트러블슈팅

## 1. YouTube API 기반 수집기 도입

### 증상

기존 `yt-dlp` 중심 수집으로는 공식 채널 업로드 목록의 구조화된 메타데이터와 통계를 안정적으로 수집하기 어려웠다.

### 원인과 해결

채널 업로드 플레이리스트, 영상 상세 메타데이터, 통계가 서로 다른 API 리소스에 나뉘어 있었다. 다음 흐름을 구현했다.

1. `channels.list`
2. `relatedPlaylists.uploads` 확인
3. `playlistItems.list`로 영상 ID 수집
4. `videos.list`로 50개씩 상세 조회

영상·음원·자막은 다운로드하지 않고 CSV만 생성했다.

### 검증

페이지네이션, `maxResults=50`, 101개 ID의 `50/50/1` 분할, 최신 200개 실제 API 수집을 확인했다.

## 2. API 캐시 권한 오류

### 증상

Windows에서 `uv add` 또는 `uv run` 실행 시 `Failed to initialize cache ... Access is denied` 오류가 발생했다.

### 원인과 해결

사용자 전역 `uv` 캐시 디렉터리 접근 권한 문제였다. 캐시 접근이 필요한 `uv` 명령만 권한 승격으로 실행했다.

### 검증

`python-dotenv` 설치, lock 파일 갱신, 테스트 실행을 완료했다.

## 3. API 키 보안 및 환경 변수 관리

### 해결

```dotenv
YOUTUBE_API_KEY=
YOUTUBE_CHANNEL_HANDLE=Bodeumofficial
```

- `.env`는 Git에서 제외
- `.env.example`에는 빈 키만 저장
- API 오류 메시지에 전체 요청 URL이나 키를 출력하지 않음
- 추적 파일에서 Google API 키와 설정된 `YOUTUBE_API_KEY` 패턴 검사

### 검증

`.env` 무추적, 실제 API 키 0건, `.env.example` 키 값 비어 있음, 오류 키 마스킹을 확인했다.

## 4. 공통 태그로 인한 TRAINING 오탐

### 증상과 원인

보듬TV 영상 대부분에 `훈련`, `교육` 태그가 공통으로 붙어 실제 내용과 무관한 영상까지 TRAINING으로 분류됐다. 태그는 채널 운영용 공통 메타데이터일 수 있다.

### 해결

- 태그는 CSV 보존용으로만 사용
- 제목·설명·챕터·재생목록을 판정 근거로 사용
- `TRAINING`을 `CANDIDATE`로 변경
- 설명 키워드 단독 일치는 `REVIEW`
- 60초 이하 영상은 CSV에 남기되 `EXCLUDE`

### 검증

개스트쇼 워터밤 → EXCLUDE, 견종백과 사례 → REVIEW, 26초·46초 쇼츠 → EXCLUDE로 확인했다.

## 5. `안고독한 훈련사` 재생목록 오탐

### 증상

재생목록 제목의 `훈련`이라는 단어만으로 인터뷰·일상 시리즈가 CANDIDATE가 됐다.

### 해결

강한 교육 재생목록 근거를 다음 표기로 제한했다.

- `퍼피교육`, `퍼피 교육`
- `주니어교육`, `주니어 교육`

`안고독한 훈련사`는 REVIEW로 보냈다.

## 6. description 구조 기반 후보 판정

### 증상과 원인

description 전체를 검색하면 해시태그, 출연 모집, URL, 저작권 문구가 훈련 근거처럼 잡혔다. 설명에는 영상 소개, 챕터, 광고·협찬, SNS·URL, 해시태그가 섞여 있었다.

### 해결

- `description_intro`: 첫 챕터 또는 홍보 영역 전까지의 원문
- `chapters`: `timestamp`, `start_seconds`, `title` JSON 배열
- `content_signals`: `title:...`, `intro:...`, `chapter:...` 원문 근거

지원 타임스탬프는 `00:00`, `01:23`, `1:02:15`다. 하이라이트·오프닝·인트로·엔딩·클로징은 챕터로 저장하되 근거에서는 제외했다.

제목 또는 소개에 행동·교육 표현이 있고 챕터에 `달려들 때`, `물었을 때`, `목줄 훈련`, `입질 버릇 고치는 방법` 같은 구체적 대응 표현이 있으면 CANDIDATE로 승격한다.

### 검증

`길에서 사나운 개를 만났다면?` 영상이 REVIEW에서 CANDIDATE로 승격됐다.

## 7. 자동 분류와 사람 검토 결과의 덮어쓰기

### 증상과 원인

metadata CSV를 재수집하면 사람이 입력한 승인·반려 상태가 사라질 위험이 있었다. 자동 수집과 사람 검토를 같은 CSV에 저장했기 때문이다.

### 해결

별도 ledger를 만들었다.

```text
data/reviews/bodeum_youtube_manual_reviews.csv
```

필드:

- `video_id`
- `title`
- `video_url`
- `classification`
- `review_status`
- `review_reason`
- `reviewed_at`

신규 CANDIDATE는 `PENDING`으로 추가하고, 최신 title·classification·URL만 갱신한다. `review_status`, `review_reason`, `reviewed_at`은 보존한다. 분류가 바뀌어도 기존 행을 삭제하지 않으며, video_id upsert로 중복을 막는다.

### 검증

현재 ledger는 전체 12개, APPROVED 3개, PENDING 9개, 고유 video_id 12개, 중복 0개다.

## 8. Git 추적 범위와 원본 데이터 보호

### 증상

`data/` 전체 ignore 규칙은 사람이 작성한 ledger까지 Git에서 제외했다.

### 해결

다음 파일만 Git 추적 예외로 설정했다.

```text
data/reviews/bodeum_youtube_manual_reviews.csv
```

metadata CSV, description 원본, 자막, 오디오, 영상, 임시 파일은 계속 제외한다.

### 검증

Git 추적 파일은 manual ledger 하나뿐이며 metadata CSV는 계속 ignore된다.

## 9. 최종 검증 및 브랜치 운영

### 검증 결과

- 전체 테스트 27개 통과
- `git diff --check` 통과
- 최신 200개 실제 API 수집 성공
- 보안 검사에서 실제 API 키 0건
- 작업 트리 깨끗함

### 커밋 이력

```text
b3b4e2c feat: add YouTube metadata candidate collector
5e3dcc8 refactor: improve YouTube candidate classification
db10bd7 feat: extract structured YouTube description signals
0c70948 feat: add idempotent YouTube review ledger
```

### 브랜치

```text
feature/youtube-metadata-catalog
```

브랜치는 origin에 push했고 main에는 직접 merge하지 않았다.
