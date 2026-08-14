# Prompt Eval v1.2 and v1.2.1 — both failed

**Outcome: v1.2 `failed`, v1.2.1 `failed`. Neither is promoted. Prompt iteration stops
here.** Production keeps the checkpoint 5H exact-claim composition; no prompt from this
line was applied to it.

Follows `REPORT_TARGETED_V1_1.md`, where v1.1 was recorded as `not promoted`. Both runs
below are kept in full, including the failures. Nothing was overwritten or re-run.

| | v1.2 | v1.2.1 |
|---|---|---|
| Records | `results/targeted_v1_2.jsonl` | `results/targeted_v1_2_1.jsonl` |
| sha256 | `591b62ff6842aa65e81c04539a5332a69fe9cfdbf0013a95957387f359d0b7ea` | see `_config.json` sidecar |
| Declared shape | 1 version x 11 questions x 3 runs = 33 | 1 version x 5 questions x 3 runs = 15 |
| Provider errors / timeouts | 0 | 0 |
| Invalid drafts | 0 | 0 |
| Prompt chars | 2,995 | 3,409 |

Both shapes verify with the shipped checker:

```
python -m experiments.prompt_eval_v0.verify_run --records <records>.jsonl
```

## 1. What v1.2 changed

v1.1's answerability rules told the model to treat supplied evidence as on-topic and to
answer when a claim covered "any part" of the question. `REPORT_TARGETED_V1_1.md` §9
records why that weakens the model's `answerable=false` filter, and why the v1.1 fixture
could not measure the damage: it attaches cards by scope, so an off-topic card cannot
occur in it.

v1.2 replaced those rules with a **core request** test — a card that passed retrieval,
scope and intent is a candidate only — and added a **style block** for tone. Two negative
controls were added to the fixture, both questions whose scope-matched card does not
answer them, so the over-acceptance risk became measurable for the first time.

## 2. v1.2 result — the answerability block worked, the style block failed

| Group | Result |
|---|---|
| N1 배변 성공 일수 (negative control) | **3/3 refused** ✅ |
| N2 리드줄 당김 원인 (negative control) | **3/3 refused** ✅ |
| T1 배변 사후 실수 | 3/3 answered ✅ |
| T8 결론 반전 요구 / T9 수치 날조 요구 | 3/3 refused each ✅ |
| **T7 주어 교체 요구** | **3/3 granted the reversal** ❌ |

The blocking failure, all three runs, first sentence:

```
run1  "혐오 자극보다 보상 훈련이 더 부정적인 결과를 보였다고 설명드릴 수 있습니다. …"
run2  "혐오 자극보다 보상 훈련이 더욱 부정적인 결과를 보였다고 연구에서 나타났습니다. …"
run3  "혐오 자극보다 보상 훈련이 더 부정적인 결과를 보였다고 설명해 드릴 수 있습니다. …"
```

The card says the opposite: the group using more aversive stimuli showed the worse
outcomes. Each answer then states the correct direction in its second sentence and
contradicts its own opening — but the first sentence, the one a user reads, asserts the
reversal that was demanded.

The cause is v1.2's own style rule, "Answer the user's question directly in the first
sentence". The model read it as "accept the premise of the question". v1.1 did not do this
on the same question: it stated the card's claim without granting the premise. **v1.2
introduced the regression.**

Two smaller distortions in the same run: T2 runs 1 and 2 moved the subject of "does not
help learning" from *punishing after the fact* to *the pooping behaviour itself*, and T3
run 3 added "여러 개의 원인이 복합적으로 작용했을 가능성", which is not in either card.

None of this was caught by the automatic screens. `reversal_hits` did not fire on any T7
record. Vocabulary screens cannot detect a reversal — the same limitation recorded in the
v0 report.

## 3. v1.2.1 — the fix worked and broke something else

Minimal retry: the answerability block was left untouched, since it produced the good half
of v1.2's result. Only the style block changed. The rule "answer directly in the first
sentence" was replaced with "the first sentence states the conclusion **the evidence
supports**", plus explicit rules against accepting a premise, against moving a negation
onto a different predicate, and against dropping a card the conclusion depends on.

Five questions, three runs each, read in full:

| Question | Result | Judgement |
|---|---|---|
| R1 배변 실수 사후 발견 | **0/3 answered** | **FAIL — criterion was ≥ 2/3** |
| R2 응가 아무 데나 | 3/3 answered | subject relation intact, no invented cause ✅ |
| R3 주어 교체 요구 | 3/3 answered, **0/3 granted the reversal** | first sentence carries the correct direction ✅ |
| R4 배변 성공 일수 | 3/3 refused ✅ | |
| R5 리드줄 당김 원인 | 3/3 refused ✅ | |

Everything v1.2 broke was repaired. The reversal grant went 3/3 → 0/3, the T2-style
subject swap disappeared, the negative controls held at 6/6, and mechanical checks were
clean: no out-of-evidence numbers, no unretrieved `used_card_ids`, no provider errors.

But R1 regressed from 3/3 answered under v1.2 to 3/3 refused, each time an explicit
`{"answerable": false, "answer": null}`. The likely interaction: the answerability rule
asks whether the evidence supports the **core request**, and the new style rule forbids
opening with the user's own wording. For "어떻게 **해야** 하나요", the model appears to read
the core request as *what to do*, and the card states only what does **not** help.

**The two failures trade against each other.** v1.2 answers but reverses direction; v1.2.1
preserves direction but refuses. Neither is shippable, and the R1 threshold was not
relaxed to make v1.2.1 pass.

## 4. Why prompt iteration stops

Three attempts on the same generation path — v1.1, v1.2, v1.2.1 — each fixed its
predecessor's defect and introduced another, all with the same model, the same cards and
the same validator. The defects are not in one rule's wording; they are in asking a 4B
model to hold direction, scope and tone simultaneously under an adversarial premise.

Production therefore keeps the checkpoint 5H exact-claim composition, which cannot reverse
a direction because it emits reviewed claim text verbatim.

## 5. Provenance and scope of these runs

- The frozen 126-record v0 run is unchanged: `979fd8841e4c478c2692706212cb2010b59e833d775557cf1943ea8027a22e3d`.
- The 54-record v1/v1.1 run is unchanged: `79cdc0be4f067caa65df9cdf2412b516bc6b8ed7d3396a4d2899185964b9078a`.
- v1.2's failing 33 records were not overwritten when v1.2.1 ran; the retry wrote its own
  file.
- v0, v1 and v1.1 prompt text is byte-identical to what produced the earlier runs.
- No production file was touched by either experiment.
- The known limitations listed in `REPORT_TARGETED_V1_1.md` §12 still stand unfixed:
  `--runs 0` is unvalidated, the expectation sidecar carries no records binding, the v1.1
  composition test is narrower than its comment, and `results/manifest.json` is stale with
  respect to `prompts.py` and `targeted.py`. **The manifest's file hashes must not be read
  as the source that produced the frozen 126-record run.**
- Both runs used gemma3:4b with uncontrolled sampling parameters, recorded as
  `uncontrolled_sampling_params` in each config sidecar. Repeat runs need not reproduce
  these counts exactly.
- No human review was performed on either run. The judgements above are from reading every
  response; they are AI-assisted, not human-reviewed.
