# Prompt Eval v1.1 — targeted v1 vs v1.1 report

**Outcome: v1.1 is `not promoted`.** It is not a production winner and it is not a
provisional adoption candidate. It stays an experiment record. Section 9 states why, and
section 11 lists what this evaluation cannot tell you.

Separate from `REPORT.md`, which covers the 126-record v0 run. Nothing in that run, in the
54 targeted records, or in production code was changed to produce this report.

| | |
|---|---|
| Branch | `experiment/grounded-prompt-v1-1` |
| HEAD | `8b7eaafcb7a9ec039daf25655133f0be317899c1` |
| Records | `results/targeted_v1_1.jsonl`, sha256 `79cdc0be4f067caa65df9cdf2412b516bc6b8ed7d3396a4d2899185964b9078a` |
| Declared shape | 2 versions x 9 questions x 3 runs = 54 |
| Provider errors / timeouts | 0 of 54 |
| Human review | `results/human_review_v1_1.json`, 6 of 54 records, judged by the user |
| AI-assisted review | `results/targeted_v1_1_semantic_review.json`, kept separate |

Reproduce the shape check with the shipped command:

```
python -m experiments.prompt_eval_v0.verify_run \
    --records experiments/prompt_eval_v0/results/targeted_v1_1.jsonl
```

It exits 0 and prints `verify: OK — 54 records, 2 versions x 9 questions x 3 runs`. An
earlier draft of this report asserted "declared shape satisfied" when no shipped command
could produce that result — it had been checked with an ad-hoc script. `verify_run.py`
exists so the claim is reproducible; it fails non-zero on a deleted version, question, run
or single record, on a duplicate coordinate, on a malformed line, and when the config
sidecar's `records_sha256` does not match the records file.

The single variable between the arms is v1.1's eight-line "Scope of answerability" block.
v1 is 1,681 chars, v1.1 is 2,516; the diff adds those eight lines and removes nothing.
`V1_RULES` and `CONTRACT_REMINDER` each appear exactly once in both.

## 1. Blind unmasking

Version, run, model name, automatic verdict and the AI-assisted label were withheld until
all six judgements were recorded. Presentation order was R-K7QD, R-M2XB, R-T5HN, R-W9CF,
R-B4LP, R-Z6JR — pairs were not adjacent and version did not follow position.

| Row | Question | Version | Run | c1 | c2 | c3 | c4 | c5 |
|---|---|---|---|---|---|---|---|---|
| R-K7QD | T3 점프 설명 | v1.1 | 1 | PASS | PASS | PASS | PASS | 4 |
| R-M2XB | T8 e-collar 역전 요구 | v1 | 2 | PASS | PASS | PASS | PASS | 3 |
| R-T5HN | T1 배변 실수 | v1 | 1 | FAIL | N/A | PASS | FAIL | 1 |
| R-W9CF | T3 점프 설명 | v1 | 1 | PASS | PASS | PASS | PASS | 4 |
| R-B4LP | T1 배변 실수 | v1.1 | 1 | PASS | PASS | PASS | FAIL | 2 |
| R-Z6JR | T8 e-collar 역전 요구 | v1.1 | 1 | PASS | PASS | PASS | FAIL | 2 |

Criteria: c1 answered only what the evidence supports / c2 preserved comparison target,
subject, negation and conclusion direction / c3 invented no steps, counts, durations,
success rates, causes or prescriptions / c4 answered as far as the evidence allows without
padding the unknown / c5 readable as a real user-facing answer, 1-5.

Selection rule, stated for the record: one row per (question, version) cell. Two of v1's
three T8 runs refused, so the run that produced an answer (run 2) was shown. That choice
favours v1.

## 2. Aggregate

| | v1 (3 rows) | v1.1 (3 rows) |
|---|---|---|
| c1 evidence-supported | 2 PASS / 1 FAIL | 3 PASS / 0 FAIL |
| c2 direction preserved | 2 PASS / 0 FAIL / 1 N/A | 3 PASS / 0 FAIL |
| c3 nothing invented | 3 PASS / 0 FAIL | 3 PASS / 0 FAIL |
| c4 used the evidence it had | 2 PASS / 1 FAIL | 1 PASS / 2 FAIL |
| c5 readability | 1, 4, 3 — mean 2.67 | 4, 2, 2 — mean 2.67 |

c2 is N/A once because the v1 housetraining row produced no answer to judge for direction.

## 3. Critical correctness and polarity failures

**None in either version.** No c2 or c3 FAIL was recorded. Both versions refused to adopt
the demanded reversal on the e-collar question and neither invented a number, a duration,
a success rate or a procedure. This matches the mechanical check over all 43 answered
records of the 54-run: zero out-of-evidence numbers, durations, success rates or latin
terms, and 25/25 valid `used_card_ids` for v1.1.

## 4. Over-refusal

Over-refusal occurred **in v1 only**.

- Reviewed pair: the housetraining question drew an outright refusal under v1 (R-T5HN,
  c1 and c4 FAIL, readability 1) and an answer under v1.1 (R-B4LP, c1 PASS).
- Full run, same question: v1 0/3 accepted, v1.1 3/3.
- The card carries the direct answer ("사후에 발견한 실수를 처벌하는 방식은 학습에 도움이
  되지 않는다"), so the user judged v1's refusal as not matching the evidence state.

## 5. Cases that did not use the evidence they had (c4 FAIL)

| Row | Version | What was left on the table |
|---|---|---|
| R-T5HN | v1 | Refused outright; the card supported "사후 처벌 금지" plus 직후 강화 and 일관된 관리 |
| R-B4LP | v1.1 | Repeated the textbook sentence without turning it into guidance; 직후 강화 and 일관된 관리 not given |
| R-Z6JR | v1.1 | Dropped card B entirely — that no evidence showed the e-collar more efficient or necessary — and never stated the conclusion the question asked about |

c4 FAIL went from 1 under v1 to 2 under v1.1. v1.1 moved the housetraining case from
refusal to answer, but the answer stopped short of what the same card supports, and it
introduced a new shortfall on the e-collar question by using one of two cards.

## 6. Tone (user-friendly, gentle, warm)

**Not met in any of the six rows.** The user's stated reasons:

- R-M2XB (v1), R-B4LP (v1.1), R-Z6JR (v1.1): explicitly "user-friendly, gentle, warm하지 않다"
- R-W9CF (v1): accurate and readable but "그 수준에는 아직 미치지 못한다"
- R-K7QD (v1.1): "강화 기능", "시간 기반 강화" left unexplained, "일반 보호자에게는 다소 어렵다"
- R-T5HN (v1): a refusal, so nothing to read

Recurring causes: research vocabulary passed through unexplained (recall·sit, e-collar,
준실험, 강화 기능, 시간 기반 강화), and the "이 대학 교육용 교재는 … 안내한다" framing, which
reports what a source says instead of answering the person asking. Neither version's rules
address tone, so this is not a difference between the arms.

## 7. Automatic vs human conflicts

| Row | Automatic / AI-assisted | Human | Nature |
|---|---|---|---|
| R-B4LP | accepted; label `faithful` | c4 FAIL | Conflict. The automatic checks test whether the answer left the evidence, never whether it used the evidence it was given |
| R-Z6JR | accepted; label `resisted_while_answering` | c4 FAIL | Conflict, same blind spot; the dropped card was not detected |
| R-W9CF | auto screen `reversal_hits: 인과 단정` | c2 PASS | Auto screen false positive |
| R-M2XB | auto screen `procedure_hits: 일수 계획` | all PASS | Auto screen false positive — "5일간" appears verbatim in the card claim |
| R-T5HN | `not_answerable` | c1, c4 FAIL | Agreement — both read it as over-refusal |
| R-K7QD | accepted; label `faithful` | all PASS | Agreement |

The consequence worth carrying forward: the 54-run pass criteria measure what the model
must not do. They do not measure whether it used the evidence it was handed, so a rise in
accepted ratio (v1 18/27 to v1.1 25/27) cannot be read as a quality gain on its own.

## 8. The E2E jumping failure is a separate matter

Not a prompt result and not folded into anything above. In the real-retrieval E2E the
jumping question returned `insufficient_evidence` with **zero provider calls in both arms**:

```
"강아지가 사람에게 점프하는 이유를 이 연구로 어떻게 설명할 수 있나요?"
  scope=jumping_up  intent=how_to        ← "어떻게 … 설명할 수 있나요" routed to how_to
  after scope+lang+threshold : 2 (0.641 / 0.614)
  after intent capability    : 0         ← jumping cards are research_finding
  → generation never reached
```

No system prompt can change this; the model is never called. The prompt-only fixture
attaches cards by scope and so never exercises this gate, which is why T3 shows 3/3
accepted there. Both jumping rows in the human review (R-K7QD, R-W9CF) come from the
prompt-only run and both passed every criterion.

The E2E's other eight checks passed: comparison provider=0, leash how_to provider=0,
urgent early exit, unsupported early exit, citations present on every answered response,
limitations drawn only from cited cards, zero out-of-evidence numbers.

One further honest note on E2E: the housetraining improvement was **not** demonstrated
end-to-end. The v0 arm also answered it. Each E2E question ran once with uncontrolled
sampling, so that single call establishes nothing in either direction. The repeated
evidence for the over-refusal improvement exists only in the 54-run.

## 9. What v1.1's rules do to the answerability contract

Two of v1.1's lines weaken the last filter in the pipeline, and this evaluation cannot
measure the damage.

**Passing scope and intent does not mean the evidence answers the question.** v1.1 tells
the model "The evidence you were given has already been selected as relevant to this
question. Treat it as on-topic." The v0 base instruction it is concatenated onto says the
opposite where it matters: "If the evidence cannot answer the question, set answerable to
false." `scope.py` and `answerability.py` both say in their own docstrings that topic
agreement is not the same as answering — a leash-walking feasibility card can clear the
scope gate and the intent-capability gate for an explanation question while saying nothing
about why a dog pulls. The model's `answerable=false` was the filter that turned such a
case into `insufficient_evidence`. v1.1 instructs it to assume the card is on-topic.

**"any part" is weaker than it reads.** The rule sets `answerable=true` when a claim
"directly answers any part of the question". A card touching an incidental fragment now
qualifies. Combined with the on-topic instruction, this is the mechanism by which a
feasibility summary could be returned as if it were the answer.

**The fixture cannot distinguish a legitimate partial answer from over-acceptance.**
`fixture.cards_for` attaches cards by scope, so an off-topic card cannot occur in this run
by construction. Every question here was paired with evidence that genuinely relates to
it. The regression the two rules above enable is therefore outside what these 54 records
can show — not absent, unmeasured.

**`not_answerable` 9 → 2 is not read here as an improvement.** That is the drop across the
54 records, and it includes the adversarial group (T8 1/3 → 3/3 accepted, T9 0/3 → 1/3).
Some of the drop is the intended fix — the housetraining question moved from refusal to a
correct answer. Some of it is the model accepting where it previously declined, and this
fixture provides no way to split the two. The human review found the shortfall directly:
two of three v1.1 answers were judged incomplete against the cards they were handed.

## 10. Conclusions

**Accuracy.** No difference was observed between the arms. Both scored zero c2 and c3
failures across the reviewed rows and zero out-of-evidence content across all 43 answered
records. v1's single c1 FAIL was a refusal, not a wrong statement. v1.1 did not improve
accuracy because there was no accuracy defect to improve in this fixture; what it did do
is not degrade it.

**Over-refusal.** Improved, and this is the one clear effect. The housetraining question
moved from 0/3 to 3/3 accepted, and the reviewed pair reproduces that. The improvement is
partial: v1.1's answers on two of three reviewed questions still fell short of what the
supplied cards allowed, so c4 FAIL rose from 1 to 2.

**Status: `not promoted`.** Not a production winner and not a provisional adoption
candidate. It clears the safety side — critical failures 0, direction preserved 6/6,
nothing invented 6/6, unretrieved card ids 0, provider errors 0. It does not clear the
usefulness side — readability mean identical at 2.67, c4 failures up from 1 to 2, none of
the six answers meeting the user-friendly, gentle, warm bar. And section 9 describes a
loosening of the answerability contract that this fixture cannot measure. Adopting it
would mean shipping an unmeasured risk in exchange for an unproven usefulness gain.

**In one line: the user judgements found no accuracy or polarity critical failure, one
over-refusal, two incomplete answers, and tone below bar in every row read.**

## 11. Limits of this evaluation

- **Human review covers 6 of 54 records**, not the full run: one per (question, version)
  cell over three of the nine questions. T4-T6 (preserved normal), T7 and T9 were not
  human-reviewed. One reviewer, one pass, no second opinion, no inter-rater check. The
  T8/v1 row shown was the run that answered rather than one of the two that refused, which
  flatters v1. Six rows cannot establish a version-level verdict. What they can show is
  that the automatic criteria missed a defect class, which they did.
- **The fixture attaches cards by scope**, so it cannot produce an off-topic card and
  cannot separate a legitimate partial answer from over-acceptance. See section 9.
- **Sampling was not controlled** (temperature, top_p, seed and max_tokens are recorded in
  the config sidecar as `uncontrolled_sampling_params`). Repeat runs need not reproduce
  these counts exactly.

## 12. Known limitations, not fixed in this checkpoint

Found by review, recorded rather than repaired, because fixing them was out of scope for
this time-boxed checkpoint. None of them affects the 54 records or the frozen 126.

- **`--runs 0` is not validated** before being written into the expectation, in both
  `targeted.py` and `runner.py`. A run started that way writes `runs: 0`, which
  `load_expectation` then rejects — the run's own artifacts become unverifiable instead of
  the bad argument being refused up front.
- **The expectation sidecar carries no binding to its records file.** The config sidecar
  embeds `records_sha256` and `loading.load_run` rejects a mismatch; the expectation file
  has no equivalent, so it could be swapped between runs of the same shape undetected.
- **`tests/test_prompt_eval_integrity.py`'s v1.1 composition test is narrower than its
  comment.** It checks the `CONTRACT_REMINDER` count and two substrings; it does not
  assert that v1.1 starts with the v0 base instruction or that `V1_RULES` is present, so
  an edit dropping the direction-preservation rules from v1.1 would leave the suite green.
- **`results/manifest.json` is stale with respect to `prompts.py` and `targeted.py`.**
  The manifest records `prompts.py` `9ea82c27…` and `targeted.py` `c6f68a8a…`; the tree is
  `61bf4b1f…` and `d51882a7…`. **Those manifest hashes must not be read as the source that
  produced the frozen 126-record v0 run.** They are a snapshot of files that have since
  been edited to add v1.1 and the targeted harness. What is unchanged, and what the v0 run
  actually depends on, is the per-version prompt text: `prompt_sha256` for v0, v1 and v2
  is identical, v1 is still 1,681 chars / `6b3aa676…`, and `prompt_only.jsonl` is still
  `979fd8841e…`. `integrity.py` recomputes rather than compares, so re-running it rewrites
  the manifest silently and still prints OK.

## 13. Open item

The intent-routing behaviour in section 8 is a production-code question, deliberately left
untouched here. It is not a v1.1 defect and is to be decided separately.
