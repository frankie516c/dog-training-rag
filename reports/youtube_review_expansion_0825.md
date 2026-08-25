# 유튜브 리뷰 큐 확장 (우선순위 4, 2026-08-25)

`reports/youtube_review_screening_0825.md`가 `YOUTUBE_API_KEY` 부재로 막혀 있던
채널 확장을 이번에 완료했다.

## 부수적으로 발견·조치한 것 — `.env.example`에 실키 노출

작업 시작 전, 사용자가 발급받은 실제 YouTube API 키가 `.env`가 아니라 git 추적
대상인 `.env.example`에 들어가 있는 것을 발견했다. 커밋되면 공개 저장소에 그대로
노출될 뻔한 상황이었다.

- `.env.example`을 커밋된 원본과 바이트 단위로 동일하게 복원(키 값 제거)
- 실제 키는 `.env`(gitignore 대상)로 이동
- `origin/main`을 재확인해 이 사이 커밋·푸시가 없었음을 확인 — 실제 외부 노출은
  없었다

## 채널 전체 수집

`scripts/collect_youtube_metadata.py --max-videos 900`으로 보듬TV 채널 전체를
수집했다. `docs/SOURCES.md`에 기록된 "832개"보다 실제로 더 많아, 900개를 요청해
정확히 900개를 모두 받았다 — 채널 규모가 그 사이 늘었거나 원래 기록이 과소
집계였을 수 있다(원인 미규명, 이번 범위 밖).

| 분류 | 건수 |
|---|---:|
| EXCLUDE | 479 |
| REVIEW | 340 |
| **CANDIDATE** | **81** |

기존에는 200개만 수집돼 있었고(CANDIDATE 12건 — 이게 정확히 기존
`bodeum_youtube_manual_reviews.csv` 12건과 100% 일치함, 즉 기존 작업은 이미
모아둔 것 안에서는 남김없이 다 반영돼 있었다), 이번에 700개를 추가로 확보하며
CANDIDATE가 12→81건으로 늘었다.

## 신규 CANDIDATE 69건을 리뷰 원장에 추가

`reports/youtube_review_screening_0825.md`와 동일한 채점 기준(제목 기반 0~3점 —
명시적 how-to 어구, 전/후 대비 구조, 단계/순서 표지)을 코드화해 신규 69건에
자동 적용했다. **기존 12건의 `review_status`·`reviewed_at`은 전혀 건드리지
않았다** — 승인 3건은 그대로 APPROVED, PENDING 9건도 그대로 PENDING이다.

| 신규 69건 점수 분포 | 건수 |
|---|---:|
| 0점 | 68 |
| 1점 | 1 |

## 정직하게 보고할 발견 — 자동분류 CANDIDATE의 실제 신호는 약하다

메타데이터의 `matched_keywords`를 직접 열어보니, CANDIDATE 판정 대부분이
**`title:퍼피교육`·`playlist:퍼피교육`**(플레이리스트 소속) +
**`structure:소개+구체적 챕터`**(챕터 유무)에서 나온다 — 즉 "이 영상이 실제로
훈련 절차를 다루는가"가 아니라 **"어느 재생목록에 들어있고 챕터가 있는가"**가
분류 근거다. 실제 제목을 보면 "귀여우니까 조심", "감겨버렸습니다",
"무장 해제 시킨" 처럼 리액션/소개형이 다수다. 신규 69건 중 68건이 제목만으로는
절차 신호 0점인 이유가 여기 있다 — 스코어링이 관대해서가 아니라 실제로
플레이리스트 소속만으로 CANDIDATE가 된 영상이 많기 때문이다.

**유일한 실질적 신규 발견**: `MzZPmL7xB3Q`("흥분하면 소변 누는 강아지 교육하는
방법 From 강형욱 To 빈지노")가 명시적 "교육하는 방법"이라는 how-to 어구를 갖고
있어 1점을 받았다 — 이건 사람이 우선 확인해볼 가치가 있다.

## 판단 — 다음에 할 일

1. **`classification_reason`이 플레이리스트 의존적이라는 게 확인됐으니**,
   `scripts/collect_youtube_metadata.py`의 CANDIDATE 판정 로직 자체를 손보는
   게 다음 라운드 후보다(이번 범위 밖 — 판정 로직 변경은 별도 승인 필요).
2. 사람이 볼 때는 여전히 기존 4건(`t3kYE-WP3Yw` 3점 · `muPemAmkfkc` 2점 ·
   `JozcQCCFiFk`/`oTn32b8GX6g` 1점)이 최우선이고, 신규에서는 `MzZPmL7xB3Q`
   (1점) 정도만 추가로 볼 가치가 있다. 나머지 68건은 "제목만으로는 신호
   없음" — 시청하기 전에는 판단 보류.

## 참조

- `data/reviews/bodeum_youtube_manual_reviews.csv` (12→81건, gitignore 예외로
  추적됨)
- `data/reviews/bodeum_youtube_metadata.csv` (200→900건, gitignore 대상,
  로컬 전용)
- `reports/youtube_review_screening_0825.md` (채점 기준 원본, API 키 부재로
  막혔던 지점)
- `data/scratch/expand_review_ledger.py` (재현용, gitignore 대상)
