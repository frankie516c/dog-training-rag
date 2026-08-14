# Grounded RAG와 결정적 fallback

체크포인트 5I-A는 생성형 RAG 경로를 복구하면서 5H의 결정적 조립을 안전망으로 남긴다. API 요청·응답 계약, EvidenceCard, Qdrant payload, threshold 0.40은 그대로다.

## 두 경로

```text
POST /chat
  1. safety gate                       중독 의심 → urgent, 즉시 종료
  2. deterministic scope gate          미지원 범주 → 즉시 종료
  3. 질문 의도 분류                    how_to / comparison / explanation
  4. BGE-M3 + Qdrant retrieval
  5. scope · 언어 · threshold 0.40 필터
  6. 답변 가능성 판정                  근거가 이 의도를 지원하는가
  7. comparison → 5H exact-claim 조립  provider 미호출
  8. how_to · explanation → grounded generation  provider가 있을 때만
  9. 생성 결과 검증                    실패하면 사용자에게 노출하지 않음
 10. server-side citation · limitations
 11. 검증 실패 · provider 없음 · intent 제외 → 5H 결정적 조립
     (조립도 실패하면 insufficient_evidence)
```

1·2단계에서 끝난 질문은 retrieval도 generation도 타지 않는다. 6단계에서 걸러진 질문은 **fallback도 하지 않고** `insufficient_evidence`로 끝난다.

## 질문 의도

`backend/app/answerability.py`의 규칙 기반 분류기다. 모델을 쓰지 않고 결정적이며, API에 노출하지 않는다.

| intent | 인식 예 |
|---|---|
| `comparison` | 더 효과, 더 효율, 보다 나은, 비교, 차이가, 어느 쪽, more effective, better than |
| `how_to` | 어떻게, 방법, 고치, 교정, 가르치, 멈추게, 못하게, 야 하나요, how to, what should I do |
| `explanation` | 왜, 이유, 원인, 뭔가요, why, what causes |

평가 순서는 `comparison` → 명시적 `how_to` → 명시적 `explanation` → **암묵적 `how_to`** → 기본값 `explanation`이다.

`comparison`이 먼저인 이유는 “전자 목줄이 보상 훈련보다 더 효과적인가요?”에 `훈련`이 들어 있지만 절차 요청이 아니기 때문이다.

### 암묵적 how_to

실제 UI 입력은 대부분 질문이 아니라 **문제 서술**이다.

```text
산책할 때 리드줄을 계속 당겨요
사람만 보면 뛰어올라요
켄넬 안에서 계속 짖어요
이동장에 들어가는 걸 무서워해요
응가를 아무 데나 해요
```

보호자는 행동을 서술하고 대처법을 기대한다. “어떻게 고치나요”를 붙이는 경우가 오히려 드물다. 이런 문장을 `explanation`으로 읽었더니 **리드줄 당김 호소에 고령 보호자 대상 feasibility 연구가 답변으로 나갔다.** 이 계약이 막으려던 바로 그 불일치였다.

그래서 반복 부사(`계속`, `자꾸`, `자주`, `맨날`, `항상`), `아무 데나`, 공포 표현(`무서워`, `두려워`, `겁내`), 유발 상황(`만 보면`, `만 오면`)을 암묵적 `how_to` 표지로 둔다. 명시적 표지가 우선하므로 “강아지가 **왜** 계속 짖나요?”는 여전히 `explanation`이고, 연구 결과를 묻는 사람은 연구 결과를 받는다.

비용은 분명하다. 현재 카드 구성에서 리드줄·점프·짖음 문제 서술은 `insufficient_evidence`가 된다. 절차 근거가 없는 상태에서 연구 요약을 대처법인 것처럼 내보내는 것보다 낫다는 판단이며, 절차형 claim을 가진 카드가 추가되면 자동으로 답변 가능해진다.

## 답변 가능성 판정

주제가 같다는 것과 질문에 답할 수 있다는 것은 다르다. 카드 UUID를 하드코딩하지 않고, `topic`·`tags`에서 **카드의 종류**를 정한 뒤 종류별로 지원 의도를 명시한다.

```python
class EvidenceKind(StrEnum):
    PRACTICE_GUIDANCE = "practice_guidance"  # 원칙·과정을 안내하는 자료
    RESEARCH_FINDING = "research_finding"  # 연구 결과 보고


CAPABILITIES = {
    PRACTICE_GUIDANCE: {HOW_TO, EXPLANATION},
    RESEARCH_FINDING: {COMPARISON, EXPLANATION},
}
```

`PRACTICE_GUIDANCE` 표지는 `management`, `gradual exposure`, `기초 원칙`, `관리 원칙` 등이다. **표지가 없으면 `RESEARCH_FINDING`으로 간다.** 이 기본값이 fail-closed 방향이다 — 분류되지 않은 카드는 절대 절차를 승인할 수 없고, 안내 자료를 추가하려면 표지를 의도적으로 등록해야 한다.

현재 승인 카드 8장의 판정은 다음과 같다.

| 카드 topic | kind | how_to |
|---|---|---|
| 배변 훈련의 기초 관리 원칙 | practice_guidance | 가능 |
| crate 적응의 기초 원칙 | practice_guidance | 가능 |
| e-collar 훈련 효율 비교 | research_finding | 불가 |
| 혐오 자극 기반 훈련과 복지 지표 | research_finding | 불가 |
| 사람에게 점프하는 행동의 기능 | research_finding | 불가 |
| 점프 행동의 기능 기반 강화 개입 | research_finding | 불가 |
| kennel 환경의 짖음 pilot | research_finding | 불가 |
| 리드줄 보행 프로그램의 실행 가능성 | research_finding | 불가 |

따라서 “산책할 때 리드줄 당김을 어떻게 고치나요?”는 feasibility 카드가 검색되어도 generation을 호출하지 않고 `insufficient_evidence`를 반환한다. 연구 요약을 교정법인 것처럼 보여주지 않는다.

## 생성 provider

`backend/app/generation.py`의 OpenAI-compatible adapter를 재사용하고, 원문 JSON이 필요한 grounded 경로를 위해 `complete()` 메서드를 추가했다. 기존 `generate()`와 5G 실험 코드·테스트는 그대로다.

모델명과 endpoint는 코드에 없다. 설정에서만 온다.

```text
GENERATION_BASE_URL
GENERATION_API_KEY
GENERATION_MODEL
```

`GENERATION_BASE_URL`과 `GENERATION_MODEL`이 없으면 grounded 경로를 비활성화하고 결정적 조립으로 답한다. **503이 아니다.** 503은 retrieval 초기화 실패에서만 발생하며 5F-2의 계약과 로깅을 유지한다.

## 생성 입력

프롬프트에 들어가는 것은 사용자 질문, 요청 언어, 그리고 선택된 카드의 `card_id`·`topic`·`tags`·`claim`·`limitations`뿐이다. URL, locator, `SourceRegistryEntry`, 라이선스 문구, 원문, 로컬 경로, API key, Qdrant 설정은 넘기지 않는다.

System instruction이 지시하는 것은 다음과 같다 — 근거 밖의 사실·수치·절차 추가 금지, 근거에 절차가 있을 때만 훈련 단계 작성, 연구 결과와 훈련 처방 구분, feasibility를 efficacy로 바꾸지 않기, 비교 방향과 부정 표현 보존, 의료·진단·처치 생성 금지, 답할 근거가 없으면 `answerable=false`, citation·limitation은 서버가 조립하므로 작성 금지.

## 내부 출력 계약과 검증

모델은 사용자에게 직접 말하지 않는다. 구조화된 초안을 반환하고 서버가 검증한다.

```json
{"answerable": true, "answer": "...", "used_card_ids": ["<uuid>"]}
```

검증 결과는 세 가지다 — `ACCEPTED`(초안 사용), `NOT_ANSWERABLE`(모델이 답할 수 없다고 보고), `INVALID`(그 밖의 모든 실패). 뒤의 둘은 서로 다르게 처리한다.

검증 항목:

- 전체를 감싼 code fence 제거 후 JSON 객체로 파싱
- `answerable`이 `false`면 `NOT_ANSWERABLE`, boolean이 아니면 `INVALID`
- `answer`가 비어 있지 않은 문자열이고 2,000자 이하
- `used_card_ids`가 비어 있지 않고, **검색·필터를 통과한 카드의 부분집합**
- 응답 언어 일치 (한글 포함 여부로 판정)
- 답변의 모든 숫자열이 근거 context에 존재
- 답변의 모든 라틴 문자 단어가 근거 context에 존재
- `citations`, `limitations`, `sources` 같은 모델 출력 필드는 읽지 않고 버림

숫자·라틴어 검사는 5G에서 실패가 집중됐던 지점(지어낸 표본 수, 기간, 연구명)을 겨냥한다.

검증에 실패하면 모델이 쓴 문장은 **한 글자도 사용자에게 노출되지 않는다.**

### 알려진 제한 — 결론 방향은 검증되지 않는다

현재 검증기는 **의미가 아니라 어휘**를 본다. 다음 두 답변은 근거의 숫자와 라틴 단어만 사용하므로 전부 통과한다.

| 원본 근거 | 통과하는 역전 답변 |
|---|---|
| e-collar 집단의 우위는 **나타나지 않았다** | e-collar 집단의 우위는 **나타났다** |
| **혐오 자극 집단이** 보상 기반 집단보다 부정적 | **보상 기반 집단이** 혐오 자극 집단보다 부정적 |

부정 삭제와 비교 주어 교체는 어휘를 바꾸지 않기 때문에 숫자·라틴어 검사로는 **구조적으로 탐지 불가능하다.** 5G·5G-1에서 두 4B 모델이 실제로 만든 실패가 정확히 이 유형이다.

`tests/test_grounded.py`의 `test_known_limitation_polarity_reversal_is_not_detected`가 이 동작을 **현재 상태 그대로** 고정한다. 가드가 생기면 이 테스트가 먼저 깨지도록 의도한 것이며, 통과한다는 사실이 안전을 뜻하지 않는다.

프롬프트 지시(`비교 방향과 부정 표현을 보존`)만으로 해결됐다고 보지 않는다. 지시는 측정 대상이지 보증이 아니다.

### 완화 — comparison은 생성 경로에 들어가지 않는다

`chat_service.py`의 `GENERATED_INTENTS`가 provider에 도달할 수 있는 intent를 `how_to`와 `explanation`으로 한정한다. `comparison` 질문은 검색·필터·답변 가능성 판정을 모두 그대로 거친 뒤, **provider를 호출하지 않고** 선택된 카드의 exact claim을 5H composer로 조립한다.

- 검증기가 볼 수 없는 축(부정·비교 방향)을 가장 위험한 intent에서 아예 우회시킨다.
- 손실이 작다. comparison 대상 카드는 e-collar·혐오자극 2장뿐이고 두 claim 모두 이미 완결된 비교 서술이다.
- 검증 가능하다. “comparison 질문에서 provider 호출 0회”는 단정적으로 테스트된다.

`tests/test_chat_service.py::test_comparison_bypasses_the_validator_that_cannot_see_polarity_reversal`이 역전 답변을 반환하도록 구성한 provider를 두고도 호출이 일어나지 않고 역전 문구가 응답에 없음을 확인한다.

**남는 위험**: 같은 e-collar 카드를 `explanation` 질문으로 물으면 생성 경로가 열려 있고, 그 답변에는 여전히 방향 역전이 가능하다. 이번 완화는 위험을 없앤 것이 아니라 가장 위험한 intent에서 걷어낸 것이다. semantic·entailment 가드는 그 자체로 정확도 측정이 필요한 새 문제이므로 MVP 범위 밖이며, 프롬프트 실험에서 `explanation` 답변의 방향 보존을 사람이 직접 대조해야 한다.

## 검증 실패별 동작

| 상황 | 동작 |
|---|---|
| provider 미설정 | 결정적 조립 (200) |
| provider 오류·timeout | 결정적 조립 (200) |
| JSON 파싱 실패 | 결정적 조립 (200) |
| 빈 `answer` | 결정적 조립 (200) |
| 검색되지 않은 card ID 사용 | 결정적 조립 (200) |
| 근거에 없는 수치·라틴어 | 결정적 조립 (200) |
| **`answerable=false`** | **`insufficient_evidence`, fallback 없음** |
| 의도를 지원하는 근거 없음 | `insufficient_evidence`, fallback 없음 |
| safety urgent / 미지원 범주 | `insufficient_evidence`, retrieval·generation 미호출 |
| retrieval 초기화 실패 | 기존 503 |

`answerable=false`만 fallback으로 내려가지 않는다. 모델이 이 근거를 보고 “답할 수 없다”고 판단했는데 곧바로 그 근거의 claim을 보여주면, 방금 부적합하다고 판정된 문장을 답변인 것처럼 내놓는 셈이 된다. 나머지 실패는 모델의 **판단**이 아니라 **동작** 실패이므로 검토된 claim으로 내려가는 것이 맞다.

이 규칙은 모델에 거부권을 준다는 뜻이기도 하다. 모델이 과도하게 `answerable=false`를 반환하면 답변 가능한 질문까지 막히므로, 실제 provider를 붙일 때 이 비율을 측정 항목에 넣어야 한다.

## Citation과 limitations

두 경로 모두 서버가 조립한다. 생성 경로에서는 `used_card_ids`에 해당하는 **서버 측 카드**만 citation과 limitations의 원천이 된다. 모델이 반환한 어떤 출처 정보도 사용하지 않는다.

## 유지되는 5H 계약

`compose_evidence_answer()`, exact-claim fallback, server-side citation·limitations, 언어 필터, safety gate, scope gate, threshold 0.40, 그리고 `tests/test_evidence_regression.py`의 5G·5G-1 왜곡 회귀 fixture는 모두 그대로다. 생성 경로가 붙었다고 해서 결정적 경로가 약해지지 않는다.

## 실제 모델은 아직 정하지 않았다

이번 체크포인트는 배선만 한다. 어떤 모델도 선택·다운로드·호출하지 않았고 단위 테스트는 fake provider만 사용한다. 실제 provider는 별도로 진행 중인 NVIDIA 모델 평가 결과가 나온 뒤 결정하며, 그 모델도 5G·5G-1과 같은 fidelity 평가를 먼저 통과해야 한다 ([`answer-composition.md`](answer-composition.md)).
