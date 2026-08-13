# Prompt Eval v0 — 코드 리뷰 15건 disposition

`/review /uncommitted`가 커밋 `303ae01` 시점의 하네스를 검토해 15건을 보고했다. 각 항목의 처리 결과다. 리뷰는 끝까지 실행돼 전문을 반환했고, 지연을 이유로 자체 판단으로 대체하지 않았다.

**요약**: confirmed_and_fixed 12, confirmed_documented_limitation 3, not_reproduced 0, false_positive 0.

원본 126개 응답과 `prompt_only.jsonl`은 수정하지 않았다. SHA-256 `979fd884…e3d` 불변.

---

## HIGH

### 1. config sidecar가 integrity.py에 연결되지 않음 — `confirmed_and_fixed`

**재현**: `check_records`가 JSONL 안의 config 줄만 읽고 `model = shape["generation_config"].get("model", "")`. 수정된 runner는 records만 쓰므로 config가 `{}`가 되고 `model=""`, digest `null`이 되는데 `ok` 판정에는 config가 포함되지 않아 `integrity: OK`가 그대로 출력된다.

**영향**: 다음 실행부터 manifest가 모델 provenance를 조용히 잃는다.

**수정**: `loading.py` 신설 — sidecar 우선, legacy 첫 줄 fallback, 둘 다 없거나 `model`이 비면 `ConfigResolutionError`. `integrity.py`가 이를 사용하고 `ok` 판정에 `bool(model)` 추가.
테스트 5건: `test_legacy_inline_config_is_still_read`, `test_sidecar_config_is_preferred`, `test_missing_config_fails_closed_instead_of_reporting_an_empty_model`, `test_config_without_a_model_fails_closed`, `test_sidecar_belonging_to_another_run_is_rejected`.

### 2. 같은 결함, analyze.py — `confirmed_and_fixed`

**재현**: `load_records`가 in-file config만 추출해 `summary.json`에 기록.

**수정**: `analyze.load_records`가 `loading.load_run`을 호출하도록 교체. 위 테스트가 공통 경로를 덮는다.

### 3. 재계산 커버리지 과장 — `confirmed_and_fixed`

**재현**: 실측 `records=126, 실제 재계산=75, 건너뜀=51`인데 `aggregate.json`은 `checked: 126`을 보고했다. 이 숫자를 REPORT.md·integrity.py·대화 보고에서 반복 인용했다.

**영향**: 커버리지를 68% 과장. 무결성 주장의 근거가 흔들린다.

**수정**: `verify_auto_checks_reproduce`가 `total_records / applicable_records / checked_records / skipped_records / mismatches`를 모두 반환하고, applicable인데 `auto_checks`가 없으면 `applicable_without_stored_checks`로 fail closed. `not_answerable` 51건에는 적용 가능한 별도 계약 검사(`verify_not_answerable_contract`) 신설. REPORT.md에 Correction Notice.
테스트 4건.

### 4. blind review sheet이 blind가 아님 — `confirmed_and_fixed`

**재현**: `row_id index %3 → {0:{v0}, 1:{v1}, 2:{v2}}`. 정렬 키가 `(question_id, run_number, prompt_version)`이라 3행 주기 고정. 버전 열을 숨겨도 행 위치로 복원된다.

**영향**: AI 의미 검토를 사람이 검증할 유일한 수단이 편향 없이 작동 불가.

**수정**: `blind_review_v2.csv` 신설 — 버전·run 열 제거, 고정 seed(20260813) 셔플, 불투명 `row_id`(`B` + sha256 10자리), 대응표는 `blind_review_v2_key.csv`로 분리, 양쪽 hash를 `blind_review_v2_manifest.json`에 기록. 기존 `blind_review.csv`는 legacy로 남기되 공정한 blind 증거로 사용하지 않음을 REPORT.md에 명시.
테스트 4건. 이 중 `test_blind_sheet_row_ids_are_opaque_and_seed_stable`이 **row_id 충돌(126행 중 고유 88개)** 을 잡아냈다 — 동일 응답이 여러 run에 반복돼 지문이 같았기 때문이며, 좌표를 해시 입력에 추가해 해결했다.

---

## MEDIUM

### 5. 숫자·라틴어 지표가 post-validation 동어반복 — `confirmed_and_fixed`

**재현**: 75개 accepted 전부에서 0건. `run_auto_checks`는 `validate_draft`가 ACCEPTED를 낸 뒤에만 호출되고, `_stays_within_evidence`가 같은 context·같은 정규식으로 이미 그런 답변을 제거한다.

**수정**: 지표명을 `post_validation_numbers_outside_evidence` / `post_validation_latin_outside_evidence`로 변경하고 REPORT.md에 "prompt comparison metric 아님, validator가 구조적으로 제거한 결과"로 표기. pre-validation raw draft가 저장돼 있지만 독립 검사기가 없으므로 prompt metric으로 승격하지 않는다.

### 6. semantic label이 좌표만으로 재사용됨 — `confirmed_and_fixed`

**재현**: `RESISTED_WHILE_ANSWERING`과 `CRITICAL_JUDGEMENTS`가 `(question_id, version, run)` 키. v0의 `adversarial_resisted 15/15`는 O4/v0 3건 면제에 의존하며, 면제가 없으면 12/15다.

**수정**: `provenance.response_fingerprint()`가 question·context·raw output·answer·answerable·used_card_ids·prompt version을 canonical JSON으로 묶어 SHA-256. 라벨은 지문이 정확히 일치할 때만 적용되고, 불일치는 unreviewed로 처리. 기존 19개 라벨을 현재 저장 응답의 지문으로 마이그레이션(`fingerprints.py`, 19/19 성공, 누락 0).
테스트 3건 — 답변을 한 글자 바꾸면 라벨이 떨어지는 것까지 확인.

### 7. error 레코드에 `would_fallback` 누락 — `confirmed_and_fixed`

**재현**: 코드상 error 분기가 `would_fallback` 설정 전에 return. 현재 error 0건이라 잠복.

**수정**: error 분기에서 `would_fallback=True`, `auto_checks=None`을 명시. production에서 `GroundedAnswerer.draft`가 예외를 잡아 조립으로 내려가는 동작과 일치한다.

### 8. api_key 미전달 — `confirmed_and_fixed`

**재현**: runner·e2e가 `OpenAICompatibleGenerationProvider`에 key를 넘기지 않음. `main.py`는 넘긴다.

**수정**: `build_provider(config, settings)` 신설로 production 배선과 동일하게 key 전달. 값은 결과·로그·manifest·report 어디에도 기록하지 않는다.
테스트 1건 — fake secret이 provider에는 도달하고 산출물에는 없음을 확인. 실제 API 호출 없음.

### 9. raw base_url이 산출물에 기록됨 — `confirmed_and_fixed`

**재현**: `RunConfig.as_dict()`가 `base_url` 원문을 기록하고 4개 산출물에 전파.

**수정**: `sanitize_endpoint()` — userinfo·query·fragment 제거, credential 의심 path 제거, `provider_type`·`locality`·`sanitized_origin`만 저장. 기존 4개 산출물을 재검사한 결과 실제 노출된 값은 `http://localhost:11434/v1`로 secret 없음. legacy `prompt_only.jsonl`은 수정하지 않고 legacy artifact로 명시한다.
테스트 3건.

### 10. manifest 해시 범위 부족 — `confirmed_and_fixed`

**재현**: `HASHED_INPUTS`에 `data/processed/evidence_cards.jsonl`(프롬프트 내용을 실제로 결정)과 `semantic_review.py`(critical 판정의 출처)가 빠져 있었다.

**수정**: 대상을 5개 → 15개로 확대 — prompts·fixture·runner·checks·analyze·integrity·review·semantic_review·provenance·loading·`backend/app/grounded.py`·evidence_cards.jsonl·source_registry.jsonl·records. `git_state()`로 commit SHA와 dirty 여부도 기록.

### 11. analyze 출력 경로 하드코딩 — `confirmed_and_fixed`

**재현**: `--records`는 인자인데 출력은 `RESULTS_DIR` 고정 → 다른 파일을 분석하면 동결된 산출물을 덮어쓴다.

**수정**: 출력이 입력 stem을 따르도록 변경(`prompt_only.csv`, `prompt_only_summary.json`, `prompt_only_comparison_table.md`) + `--out-dir`. 구 이름 `summary.json`·`comparison_table.md`는 새 이름으로 대체됐다.

### 12. error가 올바른 거절·적대 저항으로 집계됨 — `confirmed_and_fixed`

**재현**: `answerable_correct`가 `(accepted) is expected`를 쓰고 `complied`가 `accepted`를 요구하므로 error 행이 양쪽에서 "정답"이 된다.

**수정**: `summarise`가 `provider_errors` / `responded_runs`를 분리하고 모든 비율을 응답이 도착한 건에 대해서만 계산. 지표명도 `answerable_accuracy_excluding_errors`로 변경, `adversarial_provider_errors` 추가.
테스트 2건.

### 13. e2e가 provider 오류를 기록하지 않음 — `confirmed_documented_limitation`

**재현**: `except Exception: return DraftResult.invalid()`이고 `self.calls`를 호출 전에 증가시킨다. 결과 JSON에 error 필드가 없어 provider 장애와 모델의 invalid draft를 구분할 수 없다.

**미수정 사유**: e2e는 이번 정정 범위(v0 결과 무결성) 밖이고, 수정하면 v1.1 통과 시 실행할 E2E 코드가 검증 없이 바뀐다. `e2e_v1.json`의 provider 호출 5건은 모두 실제 응답을 받았고(3 answered, 2 not_answerable) 장애가 없었음이 latency로 확인된다. **v1.1 E2E 실행 전에 수정할 항목으로 등록한다.**

---

## LOW

### 14. runner.py 해시가 세 값으로 갈림 — `confirmed_and_fixed`

**재현**: REPORT.md 표 `594afb12…`, manifest `8fa34c0a…`, 현재 파일 `8fa34c0a…`. 보고서는 "이 표가 곧 manifest.json"이라고 적혀 있었다.

**수정**: REPORT.md의 수동 해시 표를 제거하고 `results/manifest.json`을 유일한 진실원천으로 지정. 보고서는 파일을 가리키고 값을 복사하지 않는다.

### 15. integrity가 126/42/3을 하드코딩 — `confirmed_and_fixed`

**재현**: `--runs 5`로 만든 210 레코드 파일이 `FAILED`로 판정된다.

**수정**: 관측된 run 번호 집합과 버전 집합에서 기대값을 유도하도록 변경.

---

---

# 2차 리뷰 12건 disposition

1차 정정본을 다시 리뷰한 결과 **새 P1 5건**이 나왔다. 그중 하나는 1차 정정(#6) 자체가 만든 fail-open이고, 넷은 새 파일 `targeted.py`가 이미 고친 결함을 그대로 재도입한 것이다.

**요약**: confirmed_and_fixed 12, 그 밖 0.

| # | 내용 | 처리 |
|---|---|---|
| 1 | **P1** `label_fingerprints()`가 파일 없으면 `{}` 반환 → critical 3→0으로 조용히 떨어지고 `unreviewed_records()`도 clean 보고 | `LabelBindingError`로 fail closed. `labelled_coordinate_keys()`를 판정문에서 직접 유도해 binding 파일에 의존하지 않게 함. 파일을 `HASHED_INPUTS`에 추가. 테스트 2건 |
| 2 | **P1** `manifest.json`이 legacy inline config를 그대로 복사해 raw `base_url` 재노출 | `sanitize_config()`를 `loading.load_run()` 경계에 적용. `check_records`도 통과. 테스트 2건 |
| 3 | **P1** `prompt_only_summary.json`에 동일 누출 | 같은 경계 수정으로 해소 |
| 4 | **P1** `targeted.py`가 `build_provider` 대신 직접 provider 생성 → api_key 미전달 (#8 재도입) | `build_provider(config, settings)` 사용. 소스 검사 테스트 1건 |
| 5 | **P1** `targeted.summarise`가 error 행을 accepted 분모에 포함 → 전면 실패 run이 `over_refusal: 0/9`로 읽힘 (#12 재도입, **v1.1 가설 자체를 훼손**) | `provider_errors`/`responded_runs` 분리, group별 error 별도 집계. 테스트 1건 |
| 6 | **P2** fail-closed가 문서상으로만 존재 — `review.main()`이 항상 0 반환 | 위반을 출력하고 `return 1`. |
| 7 | **P2** `expected_runs = len(run_numbers)`라 run 하나를 통째로 지워도 통과 | `max(run_numbers)` + 연속성 검사. 테스트 1건 |
| 8 | **P2** seed가 소스 상수라 저장소 보유자는 key 없이 대응표 재계산 가능 | 구조적으로 막을 수 없음. REPORT.md에 **"sheet만 받은 외부 검토자에게만 blind, 저자 자체 채점은 blind 근거 아님"** 으로 명시 |
| 9 | **P2** 없는 입력이 `input_sha256`에서 조용히 빠짐 | `None`으로 기록 + `missing_inputs` 배열, 비어 있지 않으면 integrity 실패. 대상에 fingerprints·targeted·e2e·gate_control·semantic_label_fingerprints 추가 |
| 10 | **P2** manifest 키가 OS 의존(`\` vs `/`) | `.as_posix()`. 테스트 1건 |
| 11 | **P2** `targeted.py` summary 경로 하드코딩 + sidecar에 `records_sha256` 없음 | 출력이 `--out` stem을 따르게 하고 sidecar에 binding 기록. `loading.py`는 binding 없는 sidecar를 **거부**하도록 강화(이전엔 `if recorded and …`로 건너뜀). 테스트 1건 |
| 12 | **P2** REPORT.md·모듈 docstring이 무효화된 `blind_review.csv`·삭제된 `summary.json`을 계속 가리킴 | 모두 `blind_review_v2.csv`·`prompt_only_summary.json`으로 갱신 |

부수 지적 2건도 반영했다 — `targeted.py` error 분기에 `would_fallback=True` 추가, `targeted.summarise`의 latency를 응답 도착 건에 대해서만 집계.

---

## 남은 문서화 한계 (confirmed_documented_limitation)

| 항목 | 내용 |
|---|---|
| 13 | e2e provider 오류 미기록. v1.1 E2E 전 수정 예정 |
| 실행 시점 source hash | v0 레코드에는 소급 불가. 이후 실행은 `source_sha256_at_run_time`으로 기록 |
| 자동 화면 정확도 | 방향 역전은 어휘 검사로 탐지 불가(오탐·누락 모두 존재). AI-assisted review로만 판정되며 사람 확인 필요 |
