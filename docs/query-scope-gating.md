# Query scope와 안전 게이트

체크포인트 5E는 `POST /chat` 내부에 결정적(rule-based) 범위 분류와 최소 안전 게이트를 추가한다. API 요청·응답 계약, EvidenceCard, ReviewDecision, Qdrant payload는 바꾸지 않는다.

## global threshold 단독으로는 실패한다

BGE-M3 dense 검색에 global cosine threshold `0.45` 하나만 적용한 smoke test에서 다음을 관찰했다.

| 질문 | 관찰 |
|---|---|
| 점프, 배변, e-collar, 켄넬 짖음 | 예상 카드가 1위 |
| 이동장 적응 | 관련 crate 카드가 `0.429`인데 **무관한 점프 카드가 `0.456`** |
| 초콜릿 섭취 | **무관한 짖음 카드가 `0.482`** |
| 손·악수 | **무관한 카드 3개가 모두 `0.45` 이상** |

즉 score의 절대값은 "이 카드가 질문의 주제인가"를 말해주지 않는다. threshold를 올리면 이동장 질문처럼 정답 카드가 낮은 경우가 먼저 잘려 나가고, 내리면 무관한 카드가 더 많이 들어온다. 한 축으로는 분리되지 않는 문제이므로 **주제 일치라는 두 번째 축**을 먼저 적용한다.

## rule-based scope gate를 둔 이유

- **결정적이다.** 같은 질문은 항상 같은 범주로 간다. 재현·디버깅·회귀 테스트가 가능하다.
- **모델을 부르지 않는다.** 미지원·안전 질문은 임베딩 검색과 answer 조립을 모두 건너뛴다. 응답이 빠르고, 검색 인덱스가 비어 있어도 정상적인 200 응답을 준다. (5H 이후 기본 경로에는 생성 provider 자체가 없다 — [`answer-composition.md`](answer-composition.md))
- **fail closed가 자연스럽다.** 규칙에 없으면 답하지 않는다. LLM classifier는 모르는 질문도 그럴듯하게 분류해 근거 없는 답변으로 이어진다.

이 게이트는 검색 품질 향상 장치가 아니라 **범위 밖 답변을 막는 장치**다. reranker, hybrid retrieval, LLM classifier는 이번 범위가 아니다.

## 처리 순서

```text
1. 안전 규칙 확인            → urgent면 즉시 종료 (retrieval·generation 미호출)
2. 지원 범주 판정            → 결정 실패면 즉시 종료 (retrieval·generation 미호출)
3. BGE-M3 후보 검색          → 내부 후보 수로 조회
4. 카드 범주 필터            → 질문 범주와 다른 카드 제거, 매핑 실패 카드 제거
5. 범주 일치 카드에만 점수   → provisional minimum 미만 제거
6. 근거가 남을 때만 생성 호출
7. citation은 서버가 결정적으로 조립
```

`TrainingScope`는 내부 타입이다. 요청으로 받지 않고, 응답에 넣지 않고, Qdrant payload에도 쓰지 않는다. API에 `top_k`를 추가하지 않으며, 후보 수는 서버 내부 상수다.

## 지원 범주 6개

| 범주 | 질문 쪽 인식 예 |
|---|---|
| `aversive_or_ecollar` | 전자목줄, 전기목줄, 충격 목줄, 혐오 훈련·자극, e-collar, shock collar, aversive |
| `jumping_up` | 점프, 뛰어올라, jump up / (달려들·올라타·매달리) + (앞발·사람·손님 …) |
| `kennel_barking` | (짖·bark) + (켄넬·견사·보호소·kennel·shelter …) |
| `leash_walking` | 리드줄, 산책줄, loose leash / (목줄·leash) + (당기·끌·pull) |
| `housetraining` | 배변, 대소변, housetraining / (소변·오줌·대변·똥) + (실수·훈련·가리 …) |
| `crate_adaptation` | (이동장·크레이트·crate·켄넬) + (적응·들어가·무서·두려·거부·훈련 …) |

### 규칙 우선순위

규칙은 위 순서대로 평가하고 먼저 맞는 것이 이긴다. 겹치는 어휘가 있어 순서가 의미를 만든다.

- **aversive가 leash보다 먼저다.** "전자 목줄이 …"에는 `목줄`이 들어 있지만 리드줄 보행 질문이 아니다.
- **barking이 crate보다 먼저다.** "켄넬 안에서 계속 짖어요"는 `kennel_barking`, "이동장에 들어가는 것을 무서워해요"는 `crate_adaptation`이다. 컨테이너 단어가 있어도 짖음이 함께 있으면 짖음 카드가 더 가까운 근거다.

### 일반어 단독으로는 판정하지 않는다

`목줄`, `leash`, `짖`, `훈련`, `소변` 같은 단어 하나만으로는 범주를 확정하지 않는다. 두 번째 행동 표현이 함께 있어야 한다. "목줄을 새로 샀어요", "강아지가 짖어요"는 미지원으로 떨어진다.

### 미지원 질문의 fail-closed 정책

손·악수, 앉아, 엎드려, 기다려, 리콜, 놓아처럼 **현재 카드에 절차 근거가 없는** 질문은 이웃 범주로 추측하지 않는다. 판정에 실패하면 다음을 반환한다.

- `status`: `insufficient_evidence`
- `citations`: 빈 목록
- generation provider: 호출하지 않음
- 한국어 기본 answer: `현재 검증된 훈련 근거 범위에서는 이 질문에 답하기 어렵습니다.`

## 안전 게이트 범위

이 서비스는 훈련 RAG다. 중독이 의심되는 질문을 훈련 카드로 검색하는 것 자체가 잘못된 동작이다.

탐지 조건은 **고위험 섭취 대상 + 섭취 동사**가 함께 있을 때뿐이다.

- 대상: 초콜릿, 자일리톨, 포도·건포도, 양파, 마늘, 마카다미아 (chocolate, xylitol, grape, raisin, onion, garlic, macadamia)
- 동사: 먹었·먹어·삼켰·섭취·주워 먹, ate·eaten·swallow·ingest

한쪽만으로는 발동하지 않는다. "강아지가 간식을 먹었어요"는 섭취 동사만 있어 urgent가 아니고, "초콜릿색 래브라도"는 대상 단어만 있어 urgent가 아니다.

탐지 시 동작은 다음과 같다.

- `status`: `insufficient_evidence`, `citations`: 빈 목록
- `safety_notice.level`: `urgent`, 메시지는 즉시 동물병원·응급 동물병원에 연락하라는 일반 안내
- **retrieval과 generation provider를 모두 호출하지 않는다**
- 복용량 계산, 진단, 처치법은 생성하지 않는다

물질 목록은 작고 명시적으로 유지한다. 이 게이트의 역할은 "멈추고 수의사에게 보내기" 하나이며, 의료 지식베이스로 키우지 않는다.

## topic filter와 dense score의 역할 분리

두 신호는 서로를 대체하지 않는다.

- **scope 일치(결정적)** — "이 카드가 질문의 주제인가". 카드의 `topic`과 `tags`만 보고 정확히 한 범주로 매핑한다. `card_id`·UUID를 하드코딩하지 않고, `source_id`만으로 주제를 정하지 않는다. 실제로 배변 카드와 crate 카드는 같은 `source_id`를 공유하므로 출처는 주제의 근거가 될 수 없다. 마커가 하나도 안 맞거나 두 범주에 걸치면 매핑 실패로 보고 후보에서 제거한다(fail closed).
- **dense score(연속값)** — "같은 주제 안에서 얼마나 가까운가". 주제가 다르면 점수가 아무리 높아도 채택하지 않고 citation에도 넣지 않는다.

카드 마커에서 `kennel`은 의도적으로 제외했다. 짖음 카드와 crate 카드 양쪽 tags에 있어 결정적 마커로 쓰면 한 카드가 두 범주에 걸려 모두 fail closed 된다.

## provisional 0.40의 의미

scope가 일치한 후보에만 적용하는 최소 cosine 값이다. 기본값 `0.40`, 환경변수로 재정의한다.

```text
DOG_TRAINING_RAG_SCOPE_MATCHED_MINIMUM_SCORE
```

이 값은 **질문 7개 smoke test에서 나온 임시 기준**이다. 이동장 질문의 정답 카드가 `0.429`였기 때문에 `0.45`로는 유일한 정답을 놓친다는 관찰이 근거의 전부다. 정식 검색 평가(질의 세트, 정답 라벨, recall·precision 측정) 이후 반드시 재조정한다. score는 vector 유사도일 뿐 승인 여부나 사실성이 아니며, 승인은 기존 JSONL eligibility gate가 따로 판정한다.

scope가 일치하지 않으면 `0.40` 이상이어도 무조건 제외한다. 반대로 scope가 일치해도 `0.40` 미만이면 제외한다.

## 데이터 범주를 늘릴 때의 규칙

카드를 새로 추가해 다루는 주제가 늘어나면 **코드와 fixture를 함께 늘려야 한다.** 카드만 추가하면 그 카드는 어떤 질문에도 매핑되지 않아 조용히 죽은 데이터가 된다.

1. `TrainingScope`에 범주를 추가한다.
2. 카드 마커를 추가하고, 기존 카드가 두 범주에 걸리지 않는지 확인한다.
3. query router에 인식 규칙과 우선순위를 추가한다.
4. `tests/fixtures/query_scope_eval.json`에 지원·미지원 질문을 추가한다.
5. 모든 승인 카드가 정확히 한 범주로 매핑되는지 확인하는 테스트가 통과하는지 본다.

평가 fixture는 합성 질문만 담는다. 원문, 카드 본문, 사용자 데이터는 넣지 않는다.
