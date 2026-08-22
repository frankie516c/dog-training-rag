# 핸드오프 2026-08-22

새 세션이 이 문서부터 읽습니다. 브랜치 `data/breed-conditionality-factcheck` 기준이며,
작성 시점에 로컬과 `origin`이 동일하고 미커밋 변경은 없습니다.

## 먼저 알아야 할 금지 사항

이 사이클 내내 유지된 제약입니다. 새 세션도 그대로 따릅니다.

- **Stage2 재추출 금지. `frozen/` 아래 파일 수정 금지.**
- **`extraction-prompt-v3` 작성 금지.** 표본을 사람이 읽은 뒤에 씁니다.
- **Neo4j 적재·반영 금지.** 지금까지는 전부 문서화까지만 했습니다.
- **`uv`에 `--active` 금지.** 프로젝트 `.venv` 안에서만 실행합니다.
- **사전 3종(`BREEDS`/`TRAITS`/`TOPICS`, 환경어) 임의 확장 금지.** 제안은 별도 절에만.
- **라벨 열(`조건성`·`술어원문`·`dimension_guess`·`메모`)을 채우지 말 것.** 사람이 답니다.

## 오늘 확정된 것

### 견종 축 기각

두 단계로 확인했고 둘 다 같은 방향이었습니다.

1. **그래프 실측** — `type='견종'` 노드 **19개가 전부 고아**(간선 0). 추출 결과의 관계 양끝
   이름 126개와 견종 이름 19개의 **교집합 0**이라 적재가 아닌 추출 단계 문제로 확정.
   원인은 **엣지 5종 시그니처가 견종을 구조적으로 배제**한 것. `선행조건`/`금기`의 `X`
   와일드카드는 열려 있었으나 **실사용 0건**.
2. **원문 팩트체크** — 짖음 표본 21행 중 훈련소 일지를 걷어낸 **실질 6건**, 그중
   **처치(훈련법)를 가르는 문장 0건**. 조건형 4건은 전부 빈도 서술.
   **명령어 288문서 / 견종언급 0건**도 같은 방향.

**기각은 검색 축에서 뺀다는 뜻이고 노드 삭제가 아닙니다.** 유전 질환(퍼그 단두종 증후군,
달마시안 요로결석)은 견종에만 걸리며 체급으로 대체되지 않습니다.

### ContextFactor 1차 스키마 — 확정 2개뿐

| 구분 | 확정분 | 근거 |
|---|---|---|
| dimension | `absence` (장시간 부재), `numeric`(시간) | 혼자 1,018문장/264문서, 분리불안 비순환 교차 260건, 미분류율 68%로 Top10 중 최저 |
| 엣지 | `(:Behavior)-[:OCCURS_WHEN]->(:ContextFactor)` | 원문이 "혼자 남겨졌을 때 짖는다" 구조라 행동이 조건에 걸림 |

`surface_forms: ['남겨졌을때','남겨지면','남겨진 상황에서']` — 형태 셋이 의미 하나로 모이는
유일한 일관 구문(44건). 부속으로 `(:Household)-[:HAS_FACTOR {value, unit}]->(:ContextFactor)`.

**측정한 것은 공기(共起)와 조건절 구문이지 인과가 아닙니다.** 문서·발표 어디에도 "인과"·
"유발"·"가장 명확한 인과"를 쓰지 않았습니다. "근거가 가장 두꺼운 조건 관계 후보"가 정확한
표현이고 질문에도 방어됩니다.

### 보류 4건 — 근거와 함께 백로그

전부 `docs/agenda_0825.md` 17~20번에 **"재측정 없이 승격 금지"**를 명시했습니다.

| 항목 | 보류 사유 |
|---|---|
| `trigger_location` | 현관 n=47뿐이고 **enum 값이 하나**. 값이 하나면 dimension이 아니라 상수 |
| `space_setup` | 켄넬 529·울타리 570이 전부 **순환 매칭**(환경어 사전과 `TOPICS` 양쪽에 같은 문자열). 비순환 근거 0건 |
| `REQUIRES` 엣지 | 술어 추출법 한계로 **논항 불명**. "불안해할 수 있어요"와 "훈련할 수 있어요"가 구분 안 됨 |
| `가족` → 가구구성 | **미분류 95%**, 분리불안 교차 0건. 부재가 아니라 가구 구성 |

## 미결

### 1. `claim_type: 'trigger'` → `'co_occurrence'` 이름 변경

**아직 반영하지 않았습니다.** `docs/schema_contextfactor_v1.md`는 현재도 `'trigger'`로
적혀 있습니다. 변경 범위는 **스키마 문서만**입니다.

이유: `trigger`라는 이름이 인과 역할을 이미 단정합니다. 보류 항목 `trigger_location`을
같은 사유로 보류해 놓고 확정분에 같은 단어를 쓰는 것은 일관되지 않습니다. 측정한 것은
공기이므로 `co_occurrence`가 정확합니다.

새 세션이 반영할 때 **같이 고쳐야 하는 곳**: `docs/schema_contextfactor_v1.md`의 엣지
정의 블록과 용어 주의 절, `docs/presentation_0825.md` 11장의 Cypher 블록.

### 2. 일지 필터 검증 미실시

문서 단위 일지 필터는 821문서 중 **57건(6.9%)만** 제외했습니다. 그런데 견종 측정의 짖음
표본에서는 **21행 중 12행 이상(57%)이 입소 일지**였습니다.

**6.9%와 57%의 괴리**는 필터가 덜 잡았을 가능성을 뜻하고, 그렇다면 환경어 언급
**8,145문장이라는 모집단도 부풀어 있을 수 있습니다.** 확정한 `absence`의 근거(혼자
1,018문장, 교차 260건)가 이 분모 위에 있으므로 **확정분의 신뢰도에 직접 걸리는 미결**입니다.

시간 관계상 검증하지 않기로 결정했고, **재실행하지 않기로 한 결정도 유지**됩니다.
발표에서는 질문받기 전에 먼저 밝히기로 했습니다(11장 발표 노트).

### 3. 시나리오 ①③④ 재현 확인 미실시

발표 시연 3건(6·7·8장)이 현재 코드로 재현되는지 확인하지 않았습니다. 관련 위험은
`docs/agenda_0825.md` 11번(`generate_answers.py`가 그래프 검색을 하지 않음 — 하이브리드+
실제생성 정식 경로 없음)에 이미 등록돼 있습니다.

## 다음 작업

둘 다 **별도 세션**에서 진행합니다.

1. **자막 인벤토리** — 보유 자막이 무엇이고 어느 주제를 덮는지 파악
2. **자막 표적 크롤 — 2시간 타임박스**

**두 작업 모두 Neo4j 적재·재추출 금지.** 수집과 인벤토리까지만입니다.

배경: 코퍼스가 얇은 주제가 이미 측정돼 있습니다 — 이름 10문서 · 아이컨택 13문서(사실상
미수집), 명령어 288문서인데 견종언급 0건. 앞의 둘은 조달로 해결될 수 있고, 뒤는 조달해도
같은 결과가 나올 수 있는 다른 성격의 문제입니다
(`reports/breed_conditionality_0822.md` "핀셋 조달 후보" 절).

## 참조 문서

| 문서 | 무엇 |
|---|---|
| `docs/schema_contextfactor_v1.md` | 확정 스키마 + 한계 3건. 한계 절과 스키마는 분리 불가 |
| `docs/agenda_0825.md` | 12~16번 발견·백로그, **17~20번 보류 4건** |
| `docs/presentation_0825.md` | **11장** 발견② 견종 축 기각 → 환경 축 전환 (서사 문구 윤색 금지) |
| `reports/breed_conditionality_0822.md` | 견종 측정 전문. 판정선을 측정 전에 커밋한 기록 포함 |
| `reports/env_axis_measurement_0822.md` | 환경 축 실측 (a)(b)(c) 표, 순환 매칭 주의 |

## 환경·재현

```
브랜치   data/breed-conditionality-factcheck  (origin과 동일, 미커밋 없음)
파이썬   .venv/Scripts/python.exe  (3.12.13)
크롤 풀  C:/backup/dogtraining_0821/scrapper   (posts.jsonl 3종 = 821문서)
Neo4j    docker start neo4j-graphrag  -> localhost:7474 / bolt 7687
```

재현 명령:

```
.venv/Scripts/python.exe scripts/sample_breed_sentences.py \
  --root C:/backup/dogtraining_0821/scrapper --out data/breed_factcheck \
  --per-topic 5 --strong-per-topic 20 --suffix _v2

.venv/Scripts/python.exe scripts/sample_env_sentences.py \
  --root C:/backup/dogtraining_0821/scrapper --out data/env_factcheck --per-topic 5
```

seed 20260822 고정이라 같은 입력이면 같은 표본이 나옵니다.

### 커밋되지 않은 산출물 (`data/*`는 gitignore)

다른 PC에서 라벨 작업을 하려면 아래를 **따로 옮겨야 합니다.**

```
data/breed_factcheck/sample_random.csv       (v1 37행, 감사용 보존)
data/breed_factcheck/sample_random_v2.csv    (v2 63행, 라벨 대상)
data/breed_factcheck/pool_signal.csv         (v1 135행)
data/breed_factcheck/pool_signal_v2.csv      (v2 135행)
data/env_factcheck/sample_env_v1.csv         (44행, 라벨 대상)
data/env_factcheck/excluded_journal_docs.txt (제외 문서 감사용)
```

`pool_signal*`은 **술어 형태 수집 전용이며 비율 계산에 쓰면 안 됩니다.** 신호어로 거른
표본이라 조건형이 과대 추정됩니다.

## 취몽 업로드 (미완)

오늘 작업을 취몽 데일리 로그 **3편**으로 나누기로 하고 초안까지 잡았으나, 서버 오류
(`토큰 갱신 실패 HTTP 502`)로 등록하지 못했습니다.

분할 기준은 `problems`/`solution`/`result` 3필드가 각각 200자 안에서 완결되고 서로 겹치지
않는 단위입니다(이 셋은 포트폴리오에 그대로 실림).

| # | 제목 | category | status |
|---|---|---|---|
| 1 | 견종 축 가설, 원문 실측으로 기각 | final | completed |
| 2 | 표본 오염 4종 제거로 판정선 복구 | final | completed |
| 3 | 환경 축 실측으로 1차 스키마 확정 | final | completed |

**상호·실명·블로그 핸들은 전부 익명 처리**하기로 확정했습니다 — "훈련사 블로그 529건 /
동물병원 블로그 189건"으로만 씁니다. 서버 복구 후 재시도하면 됩니다.
