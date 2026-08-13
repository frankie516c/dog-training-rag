# 결정적 근거 응답 조립

체크포인트 5H는 MVP 기본 응답 경로에서 LLM 자유생성을 제거하고, 승인된 `EvidenceCard`의 검토된 `claim`을 그대로 조립해 answer로 사용한다. API 계약과 프론트엔드는 바뀌지 않는다.

## 왜 자유생성을 뺐는가

5G와 5G-1에서 `gemma3:4b`와 `qwen3.5:4b`를 **동일한 검색 결과와 동일한 프롬프트**로 측정했다. 5G-1에서는 `reasoning_effort: "none"`, `temperature: 0`, `seed: 42`까지 맞췄다. 결과는 다음과 같다.

| | 총점 | critical fidelity failure |
|---|---|---|
| `gemma3:4b` | 79 / 100 | 2 / 10 |
| `qwen3.5:4b` | 76 / 100 | 3 / 10 |

관찰된 왜곡은 문체 문제가 아니라 **근거의 주어·조건·목적이 바뀌는** 종류였다.

- `gemma3:4b` — “사후에 발견한 실수를 처벌하는 방식은 도움이 되지 않는다”를 “응가를 아무데나 하는 것은 도움이 되지 않는다”로 바꿨다. 부정의 대상이 처벌에서 배변 행위로 이동했다.
- `qwen3.5:4b` — 혐오 자극 집단과 보상 기반 집단의 비교 방향을 뒤집었고, 리드줄 연구의 목적을 “feasibility 평가가 아니라 당김 감소 효능 입증”으로 반전시켰다.

두 모델의 실패 지점이 서로 달랐다. gemma3는 배변 카드에서만 무너지고 qwen3.5는 같은 배변 카드에서 가장 정확했다. **한쪽을 막는 프롬프트나 문구 필터가 다른 쪽에는 듣지 않는다.**

## 판정 기준

모델 선택 게이트는 평균 점수가 아니라 **주어·조건·인과의 보존 여부**다. 총점이 79점이어도 10건 중 2건에서 근거 관계가 뒤집히면 채택하지 않는다. 출처를 정확히 표시한 채로 내용을 바꿔 말하면, citation이 잘못된 진술에 신뢰를 얹어 주기 때문에 근거 없는 답변보다 나쁘다.

## 현재 MVP 경로

```text
1. safety gate                     (변경 없음)
2. deterministic scope gate        (변경 없음)
3. BGE-M3 semantic retrieval       (변경 없음)
4. scope 일치 카드 필터            (변경 없음)
5. provisional minimum 0.40        (변경 없음)
6. 승인·reuse eligibility          (변경 없음)
7. 언어 일치 필터                  (5H 추가)
8. 검토된 claim의 결정적 조립      (5H — 기존 자유생성 대체)
9. server-side citation·limitations (변경 없음)
```

검색은 그대로 semantic이다. 바뀐 것은 마지막 answer 생성 단계뿐이다.

## 조립 규칙

`backend/app/composition.py`의 `compose_evidence_answer()`가 담당하며 `ChatService`와 책임이 분리돼 있다.

- 카드가 한 장이면 `EvidenceCard.claim`을 **바이트 수준에서 그대로** answer로 쓴다.
- 여러 장이면 citation과 **같은 순서**로 각 claim을 빈 줄(`\n\n`)로 연결한다.
- claim 내부를 요약·번역·교정·재구성하지 않는다.
- 접두사, 결론, 훈련 처방, 권고 문장을 덧붙이지 않는다.
- 같은 `card_id`와 같은 claim 문자열은 한 번만 포함한다.
- `limitations`는 기존 server-side 조립 결과를 그대로 유지한다.
- 조립할 claim이 없거나 claim이 비어 있으면 `insufficient_evidence`를 반환한다.
- 선택 단계를 통과하지 못한 카드(미승인, reuse 차단, scope 불일치, threshold 미달)는 애초에 조립 대상에 들어오지 않는다.

사용자가 보는 것은 **“LLM이 다시 말한 근거”가 아니라 사람이 검토한 근거 문장 그 자체**다.

## 언어 정합성

번역하지 않으므로 언어가 맞지 않으면 답하지 않는다.

- 카드의 `claim_language`가 요청의 `response_language`와 **같은 카드만** 조립·citation·limitations에 사용한다.
- 현재 승인 카드는 모두 한국어이므로 `response_language: "ko"` 요청만 `answered`가 된다.
- 영어 요청에 영어 claim 카드가 없으면 `insufficient_evidence`를 반환한다.
- 한국어 본문을 `answer_language: "en"`으로 표시하는 일은 발생하지 않는다.

## 런타임 구성

이 문서가 설명하는 결정적 조립은 5I-A 이후 **안전 fallback**이다. provider가 설정돼 있으면 grounded generation을 먼저 시도하고, 검증에 실패하거나 provider가 없으면 여기로 내려온다. 전체 흐름은 [`grounded-rag.md`](grounded-rag.md)에 있다.

fallback 경로만으로도 서비스가 완결되므로 다음 상태에서 `/chat`이 정상 동작한다.

- Ollama 미실행
- `GENERATION_BASE_URL`, `GENERATION_API_KEY`, `GENERATION_MODEL` 미설정

`ChatService`는 HTTP provider를 직접 알지 못하고 `GroundedAnswerer`만 선택적으로 받는다. provider 부재는 오류가 아니며 503을 만들지 않는다.

새로운 public API field, dual mode 스위치, provider 선택 UI는 없다. 두 경로는 같은 `ChatResponse`를 만들고, 어느 경로로 답했는지는 응답에 드러나지 않는다.

## 앞으로 더 강한 모델을 쓰려면

자유생성을 다시 넣으려면 **같은 fidelity 평가를 먼저 통과해야 한다.** 최소 조건은 다음과 같다.

1. 동일한 검색 결과·프롬프트·payload로 10회 이상 측정
2. critical fidelity failure **0건** — 주어·조건·인과·연구 목적 변경, 범위의 보편화, 없는 처방 생성, 형식 오염
3. 반복 요청에서 결정적이거나 의미적으로 동일
4. 30초 서비스 예산 내 완료

`tests/test_evidence_regression.py`가 5G·5G-1에서 실제로 관찰된 6개 왜곡 문구를 회귀로 고정한다. 승인 claim에 없는 문장은 응답에도 나오지 않는다는 불변식을 함께 검사한다.
