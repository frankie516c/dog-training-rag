# 유튜브 리뷰 큐 스크리닝 — 우선순위 추천 (2026-08-25)

**이 문서는 추천일 뿐이다. 승인은 사람만 한다.** `data/reviews/bodeum_youtube_manual_reviews.csv`의
`review_status`는 건드리지 않았고, PENDING 9건 전부 PENDING 그대로다.

## 방법

각 영상의 **제목**만으로(설명·자막은 아직 없음) 절차/훈련 신호를 0~3점으로 채점했다.
채점 기준은 기존 APPROVED 3건의 review_reason("구체적인 훈련 설명과 실행 방법 포함")과
오늘 확립한 절차 표지(순번 표지, "어떻게/방법" 같은 명시적 how-to 어구, 전/후 대비 구조)를
따랐다. 새 컬럼 `screening_score`/`screening_note`를 CSV에 추가했다.

## 추천 순서 (점수 높은 순)

| 우선순위 | video_id | 제목 | 점수 | 근거 |
|---|---|---|---:|---|
| 1 | `t3kYE-WP3Yw` | '길에서 사나운 개를 만났다면?' 어떻게 해야할지 강형욱이 알려드립니다 | **3** | 제목에 명시적 "어떻게 해야할지 알려드립니다" — 문제상황(공격적인 개 조우) → 대처법 구조가 뚜렷함. 기존 APPROVED 3건과 같은 성격 |
| 2 | `muPemAmkfkc` | 자신감 심어줬더니 종이컵 물고 튀는 에이미네 강아지 | 2 | "자신감 심어줬더니"가 적용된 기법을 암시, 전/후 대비 구조 존재. 다만 "물고 튀는" 부분은 결과 묘사라 훈련법 자체는 본문 확인 필요 |
| 3 | `JozcQCCFiFk` | 개 조심. 귀여우니까 조심 | 1 | 행동 특성 언급은 있으나 대처법 서술 없음 — 캡션형에 가까움 |
| 3 | `oTn32b8GX6g` | 강형욱도 무장 해제 시킨 '사람 좋아 강아지' | 1 | 성격 소개형, 절차 신호 약함 |
| 5 | `0chbMAzvlnk`, `covQLV3If8o`, `UFHKROVUYvg`, `Om9UPA9mQ1I`, `W6-dl3rN7fI` | (리액션/예능/외모 소개형) | 0 | 제목만으로는 절차·기법 신호 없음. 리액션 콘텐츠이거나 연예인 콜라보 예능 성격 |

## 사람이 볼 때 권장 순서

1·2번(`t3kYE-WP3Yw`, `muPemAmkfkc`) 먼저 시청 — 절차형 콘텐츠일 가능성이 가장 높다.
3번대(`JozcQCCFiFk`, `oTn32b8GX6g`)는 시간 있으면 확인. 0점 5건은 후순위로 미뤄도
무방해 보이나, **제목만 본 판단**이라 실제로는 다를 수 있다 — 최종 판단은 항상
직접 시청 기준이어야 한다(기존 3건 승인 사유도 "대표 표본 직접 시청"이었다).

## 채널 신규 후보 확장 — 실행 불가, API 키 필요

`scripts/collect_youtube_metadata.py --max-videos 5`를 실행해 보듬TV 채널의 나머지
~820개 영상 중 신규 후보를 찾으려 했으나, **`.env`에 `YOUTUBE_API_KEY`가 없어 즉시
실패했다**(`오류: YOUTUBE_API_KEY가 필요합니다. .env를 확인하세요.`). 키를 발급받거나
추측하지 않았다 — 채널 확장은 사용자가 YouTube Data API v3 키를 `.env`에 넣은 뒤
같은 명령으로 재시도하면 된다. 그 전까지는 이미 리뷰 큐에 있는 12건(APPROVED 3 +
PENDING 9) 안에서만 우선순위를 매길 수 있다.

## 참조

- `data/reviews/bodeum_youtube_manual_reviews.csv` (screening_score/screening_note 컬럼 추가)
- `docs/SOURCES.md` (채널 규모 832개, 수동자막 ~25% 정책)
- `scripts/sample_procedure_sentences.py` (STEP_MARKERS — 채점 기준 참고)
