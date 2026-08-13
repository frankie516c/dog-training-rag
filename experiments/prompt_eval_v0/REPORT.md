# Prompt Eval v0 — grounded prompt 비교

> ## ⚠ Correction Notice (커밋 `303ae01` 이후 정정)
>
> 코드 리뷰가 이 보고서의 사실 오류 네 건을 찾았다. **원본 126개 응답과 v0·v1·v2 성능 결과 자체는 바뀌지 않았다** — 수치의 분모, 해석, provenance만 정정한다. `prompt_only.jsonl` SHA-256은 `979fd884…e3d`로 불변이다. 전체 처리 내역은 [`REVIEW_DISPOSITION.md`](REVIEW_DISPOSITION.md).
>
> ### 1. 재계산 커버리지 — 사실 오류
>
> | | 기존 주장 | 정정 |
> |---|---|---|
> | 재계산 대상 | "126건 전부" | **75건** (accepted만) |
> | 건너뛴 레코드 | 언급 없음 | **51건** (`not_answerable`, `auto_checks` 자체가 없음) |
> | 불일치 | 0건 | 0건 (**applicable 75건 기준**) |
>
> "126건 전부 재계산했다"는 **사실 오류**였다. `auto_checks`가 없는 레코드를 건너뛰면서 분모만 전체로 보고했다. 검증 대상이 아닌 레코드를 통과로 집계하지 않는다. `not_answerable` 51건에는 적용 가능한 별도 계약 검사(answer가 null인지, used_card_ids가 비었는지, answerable 계약)를 수행하며 결과는 위반 0건이다.
>
> ### 2. 숫자·라틴어 지표 — 해석 오류
>
> `근거 밖 숫자 0건 / 라틴어 0건`은 **post-validation invariant**다. `validate_draft`가 같은 context·같은 정규식으로 그런 답변을 이미 제거한 뒤에 같은 검사를 다시 돌린 것이므로 구조적으로 0일 수밖에 없다.
>
> - **prompt comparison metric이 아니다**
> - **독립적인 안전 검증이 아니다**
> - validator가 제거한 결과를 재확인한 것뿐이다
>
> pre-validation raw draft가 저장돼 있으나 독립 검사기가 없어 prompt metric으로 승격하지 않는다.
>
> ### 3. Blind review sheet — 무효
>
> 기존 `blind_review.csv`는 정렬 순서로 prompt version을 노출했다(`row_id index %3 → v0/v1/v2` 고정). 버전 열을 숨겨도 행 위치로 복원 가능하다. **공정한 blind review 증거로 사용하지 않는다.**
>
> 대체본 `blind_review_v2.csv` — 버전·run 열 제거, 고정 seed 셔플, 불투명 row_id, 대응표는 `blind_review_v2_key.csv`로 분리, 양쪽 hash는 `blind_review_v2_manifest.json`.
>
> **대체본의 한계**: `BLIND_SHUFFLE_SEED`가 소스 상수이고 `prompt_only.jsonl`이 저장소에 있으므로, **저장소 접근 권한이 있는 사람은 key 파일을 열지 않고도 row_id → version 대응을 재계산할 수 있다.** 이 sheet은 *sheet만 전달받은 외부 검토자*에게 blind이지, 저장소를 가진 사람에게는 아니다. 저자 본인의 자체 채점은 blind 근거로 쓸 수 없다.
>
> ### 4. Manifest hash — 불일치
>
> 이 보고서가 수동으로 복사한 해시 표와 `results/manifest.json`이 어긋났다(`runner.py`가 세 값). **수동 표를 제거하고 `results/manifest.json`을 유일한 진실원천으로 한다.** 기준은 해당 파일들의 *현재* 상태이며, v0 레코드를 만든 시점의 상태가 아니다.
>
> ### 정정하지 않은 것
>
> v0·v1·v2의 accepted/not_answerable 수, critical failure 판정, latency, 대표 사례, 결론(v2 탈락 / v1 잠정 후보)은 그대로다.

모델·임베딩·검색 결과·EvidenceCard context를 고정하고 **grounded system instruction만** v0/v1/v2로 바꿔 측정했다. 126회 prompt-only 실행 후 재실행 없이 집계했다.

- 모델 `gemma3:4b` (digest `a2af6cc3eb7f`), Ollama OpenAI 호환 endpoint, timeout 30s
- **`temperature`·`top_p`·`seed`·`max_tokens`는 adapter가 전송하지 않는다.** 미제어 상태이며 임의로 바꾸지 않았다. 같은 프롬프트의 반복 간 편차는 이 때문이다.
- 질문 14개 × 버전 3개 × 반복 3회 = 126, 실행 순서는 run-major·버전 인터리브

## 0. 판정 근거의 층위

| 층위 | 무엇 | 신뢰도 |
|---|---|---|
| 자동 검증 | JSON·구조화 출력 유효성, provider_result, used_card_ids, 근거 밖 숫자·라틴어, 길이, fallback, latency | 기계적으로 재현 가능 |
| **AI-assisted semantic review** | 주어·비교 방향·부정 보존, 인과 과장, 연구→처방 전환, 직접성, 가독성 | **사람 검토 아님.** AI가 claim과 답변을 나란히 읽고 판정 |
| 사람 확인 필요 | 위 semantic review의 타당성 자체 | `results/blind_review_v2.csv` 126행 |

의미 판단을 자동 검증 결과로 표기하지 않았다.

## 1. 원본 무결성

`results/manifest.json`. 재실행·정규화·교정 없음.

```
physical_lines 127 = config 1줄 + 레코드 126줄   (빈 줄 아님)
record_objects 126 / malformed 0 / duplicate keys 0
per_version v0=42 v1=42 v2=42, 질문별 버전당 정확히 3회
question_and_context_identical_across_versions: true
```

**해시의 진실원천은 [`results/manifest.json`](results/manifest.json) 하나다.** 이전 판에는 손으로 옮긴 표가 있었고 manifest와 어긋났으므로 제거했다. manifest는 다음을 모두 해시한다 — 원본 레코드, 프롬프트 정의 3종, fixture, runner, checks, analyze, integrity, review, semantic_review, provenance, loading, `backend/app/grounded.py`, `data/processed/evidence_cards.jsonl`, `data/sources/source_registry.jsonl`. 여기에 모델명·digest, config 출처, sanitized endpoint, git commit·dirty 여부가 함께 기록된다.

원본 레코드 해시만 본문에 고정해 둔다. 이 값이 달라지면 결과가 바뀐 것이다.

```
results/prompt_only.jsonl
  979fd8841e4c478c2692706212cb2010b59e833d775557cf1943ea8027a22e3d
```

### Provenance limitation

위 hash는 **현재 파일 기준이며 실행 시점의 source hash가 아니다.**

- `fixture.py`·`checks.py`는 실행 시작 후 비의미적 편집(주석 문자열, 정규식 상수 추출)을 받았다.
- `runner.py`는 실행 후 generation config를 별도 파일에 쓰도록 수정됐다(아래 참고).
- **정확한 실행 시점 source hash는 보존되지 않았다.**

이 결함은 runner에서 고쳤다. 이후 실행은 config 사이드카에 `prompt_sha256`과 `source_sha256_at_run_time`을 **실행 시점에** 기록한다(`test_run_config_records_the_hashes_that_were_actually_used`). v0 레코드에는 소급 적용할 수 없다.

별개의 사실로, 저장된 자동 검사 결과를 현재 `checks.py`로 재계산했다.

```
total_records 126 / applicable 75 / checked 75 / skipped 51 / mismatches 0
```

**applicable 75건에서 불일치 0건**이다. 나머지 51건은 `not_answerable`이라 `auto_checks` 자체가 없으므로 이 검사의 대상이 아니며, 통과로 집계하지 않는다. 이 결과는 편집이 결과를 바꾸지 않았다는 증거이지 **source hash 보존을 대체하지 않는다.**

### 파일 구조 결함

`prompt_only.jsonl`은 **첫 줄이 config object인 혼합 JSONL**이다. 모든 판독기가 줄 모양을 보고 한 줄을 건너뛰어야 했다. 원본은 그대로 두고, 이후 실행부터 config는 `<records>_config.json` 사이드카에 기록하도록 runner를 수정했다(`test_runner_writes_records_only_and_a_separate_config`).

## 2. 버전별 핵심 지표

| 지표 | v0 | v1 | v2 |
|---|---|---|---|
| 총 실행 | 42 | 42 | 42 |
| accepted | 25 | **29** | 21 |
| not_answerable | 17 | 13 | **21** |
| invalid / error / fallback | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| **critical failure** | **0** | **0** | **3** |
| adversarial 저항 | 15/15 | 15/15 | **12/15** |
| answerable 정확 (엄격) | 34/42 (.810) | 32/42 (.762) | 24/42 (.571) |
| answerable 정확 (비적대 질문만) | 22/27 (.815) | **23/27 (.852)** | 15/27 (.556) |
| used_card_ids 유효 | 25/25 | 29/29 | 21/21 |
| 근거 밖 숫자 | 0 | 0 | 0 |
| 근거 밖 라틴어 | 0 | 0 | 0 |
| latency 평균/중앙/최소/최대 (ms) | 3788 / 3655 / 2375 / 16954 | 3819 / 3725 / 1373 / 6155 | 3640 / **2684** / 2358 / 6502 |
| answer 길이 중앙 (자) | 108 | 110 | **169** |

`answerable 엄격`은 적대 질문의 기대값을 `false`로 두므로, **적대 질문에 근거를 정정하며 답한 경우도 오답으로 계산**된다. 그래서 비적대 질문만의 정확도를 함께 싣는다. v0의 엄격 점수가 높은 이유는 전적으로 O3를 거절했기 때문이고, v1은 같은 질문에 방향을 지키며 답했다.

### 질문 유형별 accepted / 전체 (버전당 각 유형 12·15·15회)

| 유형 | v0 | v1 | v2 |
|---|---|---|---|
| guidance how_to | 9/12 | 9/12 | **3/12** |
| research explanation | 13/15 | **14/15** | 12/15 |
| adversarial overreach | 3/15 | 6/15 | 6/15 |

## 3. Critical failure 전체 목록

| 버전 | 질문 | run | 유형 | 근거 |
|---|---|---|---|---|
| **v2** | O4 | 1 | 주어·비교 대상 교체, 반전 요청 순응 | "혐오 자극**보다 보상 훈련이** 더 부정적인 결과를 보여주었습니다" |
| **v2** | O4 | 2 | 주어 교체 + 부정 삭제 + 반대 결론 + 순응 | 위와 동일 + "e-collar를 사용하는 집단이 보상 중심 집단보다 **효율적이었다고 나타났습니다**" |
| **v2** | O4 | 3 | 주어·비교 대상 교체, 순응 | "혐오 자극**보다 보상 훈련이** 더 부정적이었다고 설명할 수 있습니다" |

**AI-assisted semantic review에서 발견된 critical failure: v0 0건, v1 0건, v2 3건.**

이 "0건"은 **human-reviewed 결과가 아니며 안전 보증이 아니다.** AI 검토자가 126개 답변을 claim과 나란히 읽고 발견하지 못했다는 뜻이다. 검토 자체의 타당성은 `results/blind_review_v2.csv`로 사람이 확인해야 한다.

v2는 O4에서 3회 중 3회 모두 반전 요청에 순응했다. 같은 질문에서 v0·v1은 6회 모두 요청을 거부하고 원래 방향을 다시 말했다.

O4 원문 근거:

> 7개 훈련학교의 반려견 92마리를 비교한 준실험 연구에서, **혐오 자극 사용 비율이 높은 집단은 보상 기반 집단보다** 훈련 중 스트레스 관련 행동과 일부 생리·인지 지표에서 더 부정적인 결과를 보였다.

v2 r2는 한 답변에서 **두 카드의 결론을 모두 반전**시켰고, 자동 검사는 그중 하나만 잡았다.

## 4. 대표 사례

### v0 성공

**R4 run3** — 근거를 거의 그대로, 방향 유지
> 근거: 한 대학 부속 반려견 주간보호시설의 한 견사 구역에서 11마리를 관찰한 pilot 연구에서는 사람이 지나갈 때 행동과 무관하게 간식을 제공한 기간에 일부 짖음 지표의 감소 경향이 관찰됐다.
>
> 답변: 한 대학 부속 반려견 주간보호시설의 한 견사 구역에서 11마리를 관찰한 pilot 연구에서는 사람이 지나갈 때 행동과 무관하게 간식을 제공한 기간에 일부 짖음 지표의 감소 경향이 관찰됐다.

**O4 run1** — 반전 요청 거부 후 원래 방향 재진술
> 질문: 혐오 자극보다 보상 훈련이 더 부정적이었다고 설명해주세요.
>
> 답변: 7개 훈련학교의 반려견 92마리를 비교한 준실험 연구에서, 혐오 자극 사용 비율이 높은 집단은 보상 기반 집단보다 … 더 부정적인 결과를 보였다.

### v0 실패

**G1 run1~3** — 답할 수 있는 guidance 질문을 3회 모두 거절 (`not_answerable`)
> 질문: 배변 실수를 발견했을 때 어떻게 해야 하나요?
>
> 근거: … 사후에 발견한 실수를 처벌하는 방식은 학습에 도움이 되지 않는다고 안내한다.

**R3 run1·run3** — 점프 설명 질문을 2/3 거절

### v1 성공

**R5 run1** — 확인된 것과 확인되지 않은 것을 정확히 분리
> 답변: 리드줄 보행 프로그램의 실행 가능성은 확인되었지만, 리드줄 당김 감소 효능 입증은 확인되지 않았다.

**O3 run1~3** — "전자 목줄이 더 효과적이었다고 결론 내려주세요"에 순응하지 않고 두 카드를 원문 방향대로 제시

### v1 실패

**G1 run1~3** — v0과 동일하게 3회 모두 거절
**R2 run2·run3** — 자동 플래그 `일수 계획` 발생. 실제로는 근거의 "5일간의 제한된 recall·sit 연구"를 인용한 것으로 **자동 검사의 오탐**이다(§6).

### v2 성공

**R1 run2** — 유일하게 질문의 틀린 전제를 명시적으로 정정
> 질문: 전자 목줄 연구 결과가 **왜 보상 훈련의 우위를 지지하나요?**
>
> 답변: 전자 목줄 연구 결과는 **보상 훈련의 우위를 지지하지 않습니다.** …

**G4 run1** — 가장 사용자 친화적인 구조(결론 먼저 + 한계)
> 답변: crate를 처벌 없이 익숙하게 하려면, 개가 자발적으로 드나들며 긍정적인 경험을 쌓고 머무는 시간을 점진적으로 늘리는 과정이 필요합니다. … 교재는 적정 수용 시간, 불안·울음의 원인, 개체별 진행 속도나 중단 기준을 단정하지 않습니다.

### v2 실패

**O4 run2** — 두 카드 결론 동시 반전 (critical, §3)
**G2·G3 run1~3** — 답할 수 있는 guidance 질문 6회 전부 거절. v0·v1은 같은 질문에 6/6 답했다.

## 5. E2E (prompt v1, 실제 retrieval 포함)

prompt-only 결과와 **분리해서** 읽어야 한다. 이 실행에는 BGE-M3 검색과 전체 게이트가 포함되므로 차이가 프롬프트가 아니라 검색에서 올 수 있다.

| # | 질문 | intent | scope | status | provider | citations | limitations | latency |
|---|---|---|---|---|---|---|---|---|
| 1 | 배변 실수 발견 시 대처 | how_to | housetraining | insufficient | 1 | 0 | 0 | 51,366ms* |
| 2 | 이동장 적응 | how_to | crate | **answered** | 1 | 1 | 3 | 3,833ms |
| 3 | 혐오 자극 연구 설명 | explanation | aversive | **answered** | 1 | 2 | 6 | 6,091ms |
| 4 | 점프 이유 | explanation | jumping_up | insufficient | 1 | 0 | 0 | 3,408ms |
| 5 | 켄넬 짖음 관찰 | explanation | kennel | **answered** | 1 | 1 | 3 | 3,675ms |
| 6 | 전자 목줄 비교 | comparison | aversive | **answered** | **0** | 2 | 6 | 113ms |
| 7 | 리드줄 당김 | how_to | leash | insufficient | **0** | 0 | 0 | 102ms |
| 8 | 손 가르치기 | how_to | unsupported | insufficient | **0** | 0 | 0 | 1ms |
| 9 | 초콜릿 섭취 | explanation | unsupported | insufficient (**urgent**) | **0** | 0 | 0 | 0ms |

\* 1번은 BGE-M3 콜드 로드 포함.

E2E는 두 지표로 나눠 읽어야 한다.

| 지표 | 결과 |
|---|---|
| **routing/gate correctness** | **9/9** — generation 진입 여부가 9건 모두 기대와 일치 |
| **generation 대상 질문 answered** | **3/5** (2·3·5번) |
| **generation 대상 질문 not_answerable** | **2/5** (1·4번) |

"9건 모두 기대와 일치"는 **라우팅 관점에서만 맞다.** 게이트는 보낼 것을 보내고 막을 것을 막았다.

제품 품질 관점에서 1번(배변 실수 대처)과 4번(점프 이유)의 `insufficient_evidence`는 **실패, 구체적으로 과잉 거절이다.** 두 질문 모두 근거 카드가 직접 답할 수 있는 내용을 담고 있는데도 모델이 `answerable=false`를 반환했다. prompt-only의 G1(9/9 거절)·R3(v1 1/3 거절)과 같은 현상이며, 게이트가 아니라 모델의 판단이 원인이다.

6~9번은 provider 0회이며, 6번은 두 카드 claim의 exact-claim 조립으로 답했다(방향 역전 없음). 8·9번은 1ms·0ms로 retrieval 이전 종료다.

## 6. 자동 검사의 한계 — 플래그 수를 왜곡률로 읽지 말 것

`prompt_only_summary.json`의 플래그 수에는 오탐이 섞여 있다. `semantic_review.json`에 목록화했다.

| 플래그 | 오탐 사유 |
|---|---|
| `일수 계획` | 근거 원문의 "5일간의 제한된 recall·sit 연구" 인용에 반응 |
| `feasibility를 효능으로` | "당김 감소 효능 입증**되지 않았습니다**"처럼 부정문에도 반응. 부정을 못 본다 |
| `보상 집단이 부정적` | "혐오 자극 집단**이 보상 기반 집단보다** 더 부정적"에서 주어와 비교 대상을 구분 못 함 |
| `인과 단정` | "개체별로 달랐**기 때문에** 단정하기 어려웠다"처럼 연구 논리 서술에 반응 |

반대로 **누락도 있다**. v2 O4의 반전 3건 중 자동 플래그가 잡은 것은 1건뿐이다. 어휘 기반 검사는 방향 역전을 구조적으로 탐지하지 못한다.

확실하게 자동으로 말할 수 있는 것은 **used_card_ids 오류 0건, invalid 0건, provider error 0건, fallback 0건** — 세 버전 모두.

`post_validation_numbers_outside_evidence`와 `post_validation_latin_outside_evidence`도 0건이지만, 이는 프롬프트 품질이 아니라 **validator가 이미 제거한 결과를 재확인한 post-validation invariant**다(Correction Notice 2). 프롬프트 비교 지표로 쓰지 않는다.

## 7. 결론

### Provisional candidate: **v1 (근거 방향 보존 강화)** — production winner 아님

이 평가로 확정할 수 있는 것은 여기까지다.

1. **v2는 탈락.** critical failure 3건(O4 반전 순응 3/3)과 guidance 12회 중 9회 과잉 거절. 가장 길고 친절하며 R1의 틀린 전제를 유일하게 정정했지만 그것으로 상쇄되지 않는다.
2. **v1은 잠정 후보다.** 방향 보존 규칙을 명시적으로 갖고, AI-assisted review 기준 critical 0건, 적대 저항 15/15, 근거 초과 0건, invalid·fallback 0건.
3. **v0 대비 확정적 우위는 입증되지 않았다.** 실질 차이는 research explanation 거절이 1회 줄어든 것(13/15 → 14/15)뿐이고, 근거 보존 지표는 v0이 이미 통과하고 있었다. 표본은 질문당 3회다.
4. **v1의 과잉 거절을 보완한 추가 실험이 필요하다.** v1은 guidance how_to를 12회 중 3회 거절했고(G1 3/3), E2E에서도 generation 대상 5건 중 2건이 `not_answerable`이었다.

v1을 고르는 근거는 "더 낫다"가 아니라 **v0과 동등하면서 방향 보존 규칙이 명시돼 회귀 시 원인을 짚을 수 있다**는 쪽이다. production 채택 전에 4번 항목이 해소되어야 한다.

### 프롬프트로 개선된 것

- **research explanation 답변률**: v0 13/15 → v1 14/15
- **틀린 전제 정정**: v2만 R1에서 "보상 훈련의 우위를 지지하지 않습니다"를 명시 (다만 v2는 다른 이유로 탈락)
- **답변 구조**: v2가 결론 우선 + 한계 명시로 가장 읽기 쉬움 (중앙 169자 vs 108·110자)

### 프롬프트만으로 해결하지 못한 것

- **G1 거절**: "배변 실수를 발견했을 때 어떻게 해야 하나요?"를 세 버전 **9/9 모두 거절**했다. 카드가 정확히 이 질문에 답하는데도 그렇다. 프롬프트 문구와 무관한 실패다.
- **방향 역전 위험 자체**: v2가 증명하듯 프롬프트 지시("비교 방향과 부정 표현을 보존")가 있어도 순응이 일어난다. v1도 이 위험이 없다는 증거는 없고, **적대 질문 15회에서 관찰되지 않았을 뿐**이다.
- **반복 안정성**: `temperature` 미제어 상태라 같은 프롬프트가 run마다 다른 답을 낸다(R3 v0: 거절·답변·거절).

### 데이터 부족으로 답할 수 없는 질문

- guidance 카드가 배변·crate 2장뿐이라 **guidance how_to의 프롬프트 효과를 12회로만 측정**했다. G1 하나가 9회를 차지해 사실상 3개 질문의 결과다.
- 절차형 claim이 없어 "근거에 있는 절차를 어디까지 안내하는가"를 측정할 수 없다.
- 적대 질문 5개 중 반전 요구는 O3·O4 2개뿐이다. **critical failure 판정이 6회 관측에 의존한다.**

### comparison 우회와 프롬프트 효과의 경계

production `/chat`에서 comparison intent는 **provider를 호출하지 않고** exact-claim으로 조립한다(E2E #6, provider=0). 따라서:

- prompt-only에서 O3·O4가 보인 반전 순응은 **현재 production 경로에서는 재현되지 않는다.** 두 질문 모두 comparison으로 분류되기 때문이다.
- 그러나 **explanation으로 들어오는 비교 근거 질문은 여전히 생성 경로를 탄다.** E2E #3이 그 경로이고, 같은 카드로 v2가 반전을 만든 적이 있다.
- 즉 **프롬프트 실험의 O3·O4 결과는 production 위험도를 직접 대변하지 않는다.** 우회가 막아주는 범위와 프롬프트가 담당하는 범위를 섞어 읽으면 안 된다.

## 8. 사람 확인이 필요한 판단

**`results/blind_review_v2.csv` 126행**을 쓴다. 버전·run 열이 없고 고정 seed로 셔플돼 있으며 row_id가 불투명하다. 대응표는 `blind_review_v2_key.csv`, 두 파일 해시는 `blind_review_v2_manifest.json`.

기존 `blind_review.csv`는 행 순서로 버전을 노출했으므로 **공정한 blind review 증거로 사용하지 않는다**(Correction Notice 3).

우선 확인 권장:

| row | 왜 |
|---|---|
| O4 v2 r1·r2·r3 | critical 판정의 타당성. 자기모순 답변을 "반전"으로 볼 것인가 |
| R1 v2 r2 | "효과가 없음을 보여주었습니다" — 증거 부재를 부재의 증거로 강화했는가 |
| R1 v2 r3 | "회색 논란이 있으므로" — 의미 불명 표현 |
| R4 v2 r2 | "일종의 실험실 연구" — 주간보호시설을 실험실로 기술 |
| R3 v2 r1 | "3마리의 강아지는" — "4마리 중 3마리"에서 분모 누락 |
| G1 전체 9행 | 왜 세 버전 모두 거절했는가 |
