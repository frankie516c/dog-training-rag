# 검색 게이트 재설계 — 상대 마진 실측 (Track G, 2026-08-25)

`docs/agenda_0825.md` #1이 제기한 문제(`score_gap`이 코퍼스가 커질수록 관대해져
판별력을 잃음 — PASS 11/20→20/20, 오늘 567청크 실험에서도 20/20)에 대해,
제안된 대안 신호 중 **상대 마진(top1-top2, top1-top5)**을 실측했다. **83청크
(v3, 롤백 후 기준선) 위에서만 측정했다** — 코퍼스 확장과 게이트 재설계를
동시에 바꾸면 어느 효과인지 구분이 안 되기 때문.

## 측정 방법

`scripts/run_combined_retrieval_eval.py`에 `--gate-signal
{score_gap,margin_top2,margin_top5}` 옵션을 추가했다(기본값은 `score_gap`
그대로 — 기존 동작 무변경, 278개 테스트 전부 통과 확인). `score_stats()`에
`top1_minus_top5`를 신규로 추가했다(`top1_minus_top2`는 이미 계산되고
있었음). owner fixtures 20건(REFUSE 14 · ANSWER 6)의 `expected_outcome`과
각 신호의 PASS/REFUSE 판정 일치율을 비교했다.

## 결과

| 신호 | 임계값 | PASS 건수 | 일치율 | 비고 |
|---|---:|---:|---:|---|
| `score_gap`(기존, GATE_THRESHOLD=0.024) | 0.024 | 19/20 | **7/20 (35%)** | 거의 항상 PASS — REFUSE 14건 중 1건(Q10)만 맞춤 |
| `margin_top2`(신규, in-sample 최적) | 0.011 | 4/20 | **14/20 (70%)** | — |
| `margin_top5`(신규, in-sample 최적) | 0.0183 | 3/20 | **15/20 (75%)** | — |

**중요한 함정 — 이 숫자를 그대로 "마진이 낫다"로 읽으면 안 된다.** owner
fixtures는 REFUSE 14건·ANSWER 6건으로 불균형하다. **아무 질문이나 무조건
REFUSE로 답하는 자명한 기준선도 14/20(70%)을 얻는다** — REFUSE 14건은
자동으로 맞고 ANSWER 6건만 틀리기 때문이다. `margin_top2`(70%)는 이 자명한
기준선과 **정확히 같고**, `margin_top5`(75%)는 겨우 1건(5%p) 위다.

즉 두 마진 신호 모두 **"코퍼스 평균 대비가 아니라 실제로 애매한 질문을
가려낸다"는 증거가 되지 못한다** — 두 신호가 하는 일의 대부분은 그냥 "거의
다 REFUSE로 판정"해서 다수 클래스(REFUSE)를 맞히는 것이었다. `margin_top2`
임계값에서 실제로 PASS로 판정된 4건 중 ANSWER는 2건뿐(정밀도 50%), 전체
ANSWER 6건 중 2건만 잡아냈다(재현율 33%) — 이건 무작위보다 별로 나을 게 없는
수준이다.

또한 위 임계값들은 **이 20건 자체에서 사후적으로 고른 최적값**(in-sample)이지,
별도 검증셋으로 교차검증한 값이 아니다. 다음에 fixtures가 늘어나면 최적
임계값도 달라질 수 있다.

## 리랭커(cross-encoder) 조사 — 이번엔 시도 못함

로컬 캐시에 cross-encoder 계열 모델이 없었고(신규 다운로드 필요, 네트워크·시간
소요), 이번 라운드 범위 밖이라 실측하지 않았다. **다국어(특히 한국어) 지원이
검증된 cross-encoder 후보를 찾는 것부터가 별도 조사 작업**이다 — 이번 문서는
"시도했는데 안 됐다"가 아니라 "이번엔 시도하지 않았다"임을 명확히 한다.

## 결론 및 권고

**기본 게이트를 지금 바꾸는 것은 권고하지 않는다.** `score_gap`이 나쁘다는
진단(agenda #1)은 여전히 유효하지만, 이번에 측정한 두 대안(margin_top2/top5)도
**20건짜리 표본에서는 "거의 다 REFUSE" 이상의 실질적 판별력을 보여주지
못했다** — 표본이 너무 작아서 어떤 임계값을 골라도 다수 클래스를 맞히는
착시와 구분이 안 된다.

**다음 단계 제안**:
1. owner fixtures를 20건보다 훨씬 늘리기 전에는(최소 50~100건, ANSWER/REFUSE
   비율도 더 균형있게) 어떤 게이트 신호도 신뢰성 있게 비교할 수 없다 —
   이게 이번 조사의 가장 중요한 결론이다.
2. `--gate-signal` 옵션은 이번에 만들어 뒀으니, fixtures가 늘어나면 재측정만
   하면 된다(코드 변경 불필요).
3. 리랭커 조사는 한국어 지원 cross-encoder 후보 물색부터 별도로 진행 필요.
4. 기본값(`score_gap`, `GATE_THRESHOLD=0.024`)은 agenda #1의 경고(코퍼스
   커지면 관대해짐)를 유지한 채 그대로 둔다 — "운영 정책이 아니라 데모·평가용
   신호"라는 기존 문서화(`docs/TEAM_HANDOFF.md`)와 일관된 상태.

## 참조

- `docs/agenda_0825.md` #1 (원 문제 제기)
- `docs/decision_graphrag_abandoned_0824.md`, `reports/corpus_expansion_0825.md`
  (score_gap 판별력 상실의 26→77→567청크 재현 이력)
- `scripts/run_combined_retrieval_eval.py`의 `GATE_SIGNALS`, `gate_verdict()`
  (신규 옵션 구현)
