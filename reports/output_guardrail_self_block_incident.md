# 안전 문구가 자기 가드레일에 걸린 사건 (2026-08-20)

수동으로 기록. 자동 생성 아님 — `scripts/generate_answers.py`에 실제 LLM 생성을 연결하는 작업
중 같은 날 안에 발생·발견·수정까지 끝난 사건입니다.

## 무슨 일이 있었나

의료 질문(예: 시나리오④ `Q17` "아토피 피부염... 약용 샴푸나 처방식 사료, 연고 이름을
알려주세요")이 `score_gap` 게이트를 통과해 모델까지 가는 문제(`docs/agenda_0825.md`
안건10)를 고치면서, "의료 질문이면 모델을 부르지 말고 공감 + 범위 밖 설명 + 수의사 상담
권유가 담긴 고정 문구로 바로 답하자"는 `MEDICAL_REFUSAL_TEMPLATE`을 만들었습니다.

```python
MEDICAL_REFUSAL_TEMPLATE = (
    "걱정이 많으시겠어요. 이 질문은 반려견의 건강 상태에 대한 의학적 판단이 필요해 보입니다. "
    "저는 훈련 정보를 안내하는 어시스턴트이고 진단이나 처방을 할 수 없습니다. "
    "가까운 동물병원에서 수의사의 진료를 받으시길 권합니다."
)
```

이 문구를 만든 목적 자체가 "출력 가드레일(`classify_output_v2`)이 걸러야 할 위험한
문장을 대신할, 사람이 손으로 쓴 안전한 문구"였습니다. 그런데 이 문구를 그대로
`classify_output_v2`에 통과시켜보면:

- `"동물병원"` → `data/guardrail/medical_terms_v2.json`의 `"병원"`과 부분 문자열 일치
- `"진단이나 처방을"` → `PRESCRIPTIVE_MARKERS`의 `"처방"`과 부분 문자열 일치

**질환/증상 어휘와 처방성 표현이 한 문장에 같이 있으면 차단**이라는 `classify_output_v2`의
규칙에 그대로 걸립니다. 재현 테스트(`tests/test_medical_guardrail.py`의
`ApplyOutputGuardrailTests.test_the_incident_reproduced_unwrapped_text_would_have_been_blocked`)로
실제 사전 파일을 그대로 로드해 확인한 결과:

```
verdict.is_blocked          → True
verdict.matched_disease_terms        → ('병원',)
verdict.matched_prescriptive_markers → ('처방',)
```

**"수의사 진료를 받으라"는 안전 문구가, 자기 자신을 위험한 답변으로 오판해 차단하는
결과**였습니다. `OUTPUT_BLOCKED_MESSAGE`("이 답변에는... 표시하지 않습니다")로 바뀌었다면
견주는 정작 가장 필요한 "병원 가세요"라는 문장을 못 받았을 것입니다.

## 왜 이런 일이 생기나 — 일반적인 원인

`classify_output_v2`는 **텍스트의 내용**만 보고 판단합니다(부분 문자열 매칭). 그 텍스트가
**누가 쓴 것인지**(모델이 방금 생성한 통제 불가능한 문장인지, 사람이 검토한 고정 문구인지)는
전혀 구분하지 못합니다. 콘텐츠 필터는 원래 "무엇이 쓰여 있는가"만 보도록 설계되는데, 이
사건은 "누가 썼는가"도 검사 대상에서 빠지면 안전 문구 자체가 위험 신호와 같은 어휘를 쓸 때
역설적으로 걸린다는 것을 보여줍니다. 안전한 말("병원 가세요")과 위험한 말("이 약을
처방합니다")이 사전 수준에서는 같은 단어를 공유할 수 있기 때문입니다.

## 처음 고친 방식과 그 한계

최초 수정(같은 날, 몇 시간 뒤)은 단순히 `MEDICAL_REFUSAL_TEMPLATE`을 쓰는 코드 경로에서
`classify_output_v2` 호출 자체를 건너뛰는 것이었습니다. 동작은 맞았지만 문제가 있었습니다 —
**예외가 "이 값"이 아니라 "이 분기"에 붙어 있었습니다.** 나중에 누군가 이 분기에 모델이
생성한 텍스트를 흘려보내도록 코드를 바꾸면, 그 텍스트도 검사 없이 같이 통과합니다. 코드
리뷰에서 "이 분기가 원래 왜 검사를 건너뛰었는지" 맥락을 놓치면 조용히 재발할 수 있는
구조였습니다.

## 최종 수정 — 값에 붙는 예외

`scripts/medical_guardrail.py`에 `SystemAuthoredText`(문자열을 감싸는 불변 래퍼)와
`apply_output_guardrail()`을 추가했습니다:

```python
def apply_output_guardrail(answer, medical_terms, whitelist_terms, markers=PRESCRIPTIVE_MARKERS):
    if isinstance(answer, SystemAuthoredText):
        return OutputVerdict(is_blocked=False, text=answer.text, system_authored=True)
    return classify_output_v2(answer, medical_terms, whitelist_terms, markers)
```

`MEDICAL_REFUSAL_TEMPLATE`은 이제 `SystemAuthoredText`로 감싸져 있고, 모델이 실제로
생성한 답변(`raw_answer`, 항상 평범한 `str`)과 **같은 함수** `apply_output_guardrail()`을
통과합니다. 차이는 분기가 아니라 **타입**에서 납니다 — `str`이면 무조건 진짜 검사를 받고,
`SystemAuthoredText`로 명시적으로 감싼 값만 통과합니다. 나중에 어떤 코드가 이 자리에
모델 텍스트를 넣더라도, 그 텍스트를 일부러 `SystemAuthoredText`로 감싸지 않는 한 자동으로
검사를 받습니다 — 안전장치가 "그 코드를 쓴 사람의 조심성"이 아니라 "타입"에 있습니다.

수정 후 실제 생성 결과(`data/eval/generation/answers_demo_scenario_queries.jsonl`의 `Q17`
행)의 `output_guardrail` 필드:

```json
"output_guardrail": {
  "is_blocked": false,
  "matched_disease_terms": [],
  "matched_prescriptive_markers": [],
  "whitelist_matched": [],
  "system_authored": true
}
```

`system_authored: true`가 찍혀 있다는 것 자체가 "검사를 건너뛴 게 아니라, 검사를 거쳐서
면제됐다"는 감사 기록입니다.

## 발표에서 쓸 수 있는 한 줄

> 콘텐츠 필터는 "무엇이 쓰였는가"만 보고 "누가 썼는가"는 모른다 — 안전 문구도 위험한
> 어휘를 쓸 수 있다는 것을 실측으로 확인했고, 예외를 코드 분기가 아니라 값의 타입에
> 붙여서 미래의 실수(모델 텍스트가 같은 분기로 흘러들어와도 자동으로 검사받게)까지
> 막았습니다.

## 관련 코드/테스트

- `scripts/medical_guardrail.py` — `SystemAuthoredText`, `OutputVerdict.system_authored`,
  `apply_output_guardrail()`. 모듈 독스트링의 "apply_output_guardrail() and
  SystemAuthoredText — the self-block incident" 절에 같은 내용을 영문으로도 기록.
- `scripts/generate_answers.py` — `MEDICAL_REFUSAL_TEMPLATE` 정의부 주석, `generate()`의
  두 `apply_output_guardrail()` 호출부(템플릿 경로·실제 생성 경로).
- `tests/test_medical_guardrail.py` `ApplyOutputGuardrailTests` — 재현 테스트 4건.
- `docs/agenda_0825.md` 안건10 — 이 사건의 발단이 된 입력 가드레일 미연결 문제.
