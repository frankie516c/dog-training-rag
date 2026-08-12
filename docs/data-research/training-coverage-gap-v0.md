# Training Coverage Gap v0

## 문서 목적

이 문서는 기존 source audit 10건과 이번 체크포인트에서 검토한 후보를 기준으로, DAENGS 강아지 훈련 RAG가 현재 뒷받침할 수 있는 질문과 아직 답변하면 안 되는 질문을 구분한다. 실제 EvidenceCard, JSONL, ReviewDecision, 임베딩 또는 원문 데이터는 생성하지 않는다.

- 조사일: 2026-08-12
- 판단 성격: provisional coverage assessment
- 범위: 기본 명령, 생활 훈련, 산책 훈련, 문제행동 초기 대응
- 우선순위: 정부·공공기관, 수의행동학 기관, 대학, 학술 OA
- 제외 범위: YouTube, 블로그, 커뮤니티, 상업 훈련업체 콘텐츠

## 판단 기준

각 행은 다음 세 판단을 분리한다.

1. `재사용 상태`: 라이선스 적용 범위와 법적 불확실성
2. `현재 근거 수준`: DAENGS 훈련 상담에 대한 직접성, 연구 설계와 일반화 한계
3. `proceed / hold / reject`: 해당 범주의 제한된 claim을 다음 조사 단계로 넘길 수 있는지에 대한 잠정 권고

`proceed_with_conditions`는 출처 전체나 훈련 처방의 승인을 의미하지 않는다. locator도 문서 구조에 기반한 `locator candidate`이며, 이후 semantic review가 필요하다.

## Coverage 표

| 사용자 질문 범주 | 현재 근거 수준 | 후보 출처 | 재사용 상태 | locator 가능성 | proceed / hold / reject | 아직 답변할 수 없는 질문 |
|---|---|---|---|---|---|---|
| 기본 명령 — 앉아 | 낮음. 기존 e-collar 비교 연구가 `sit` 수행을 결과로 측정하지만 단계별 교수법을 검증하지 않는다. | 기존 `pmc7387681-e-collar-training-efficacy`; UMN Behavior 장의 일반 학습 원리 | 기존 PMC 논문은 해당 audit의 CC BY 조건 범위에서 검토 가능. UMN은 CC BY-NC 4.0이므로 비상업 조건부 | PMC의 PMCID·절 제목, UMN HTML 절 제목을 후보로 기록 가능 | `hold` — 보상 기반 원칙·방법 비교 context는 있으나 독립적인 앉아 교수 절차 근거가 없음 | 앉아를 처음부터 어떤 단계·신호·기준으로 가르치는가? 반복 횟수와 난이도는 어떻게 조절하는가? |
| 기본 명령 — 엎드려 | 매우 낮음. 기존 audit과 신규 후보에 직접 검증된 교수 근거가 없다. | 이번 우선 출처군에서 적격 후보 미확보 | 재사용 판단 대상 없음 | 없음 | `hold` | 엎드려를 유도·포착하는 안전한 단계는 무엇이며 신체 조건별 예외는 무엇인가? |
| 기본 명령 — 기다려 | 낮음. Cornell 자료가 `stay`와 `wait`를 구분하지만 일차 연구가 아니며 제3자 발행물 재게시다. | Cornell Riney Canine Health Center, “Training ‘stay’ vs. ‘wait’” | 공개 열람만 가능. Belvoir Media Group의 Cornell DogWatch 자료를 허가받아 재게시한 것으로 표시되어 변형·RAG 권리가 불명확 | 공식 HTML 절 단위 후보는 가능하나 재사용 hold | `hold` | stay와 wait를 DAENGS에서 어떻게 구분할지, 거리·시간·방해 자극을 어떤 순서로 늘릴지 답할 수 없음 |
| 기본 명령 — 이리 와·리콜 | 낮음. 기존 비교 연구는 recall 성과를 측정하지만 단계별 절차 근거가 아니다. UC Davis 안내는 직접적이나 재사용을 제한한다. | 기존 `pmc7387681-e-collar-training-efficacy`; UC Davis “Recall Training in Dogs” | 기존 PMC는 audit 조건부. UC Davis 페이지는 서면 동의 없는 복제를 금지하므로 원문 변형·RAG 적재 `hold` | PMC PMCID·결과 절 후보 가능. UC Davis는 링크·메타데이터만 | `hold` — 혐오 자극 대비 보상 기반 방법의 제한적 context만 유지 | 장거리·고방해 상황에서 리콜을 단계화하는 방법, 실패 시 안전관리, long line 전환 기준은 무엇인가? |
| 기본 명령 — 놓아 | 없음. `drop it` 또는 물건 놓기 훈련을 직접 다룬 적격 재사용 출처를 확보하지 못했다. | 이번 우선 출처군에서 적격 후보 미확보 | 재사용 판단 대상 없음 | 없음 | `hold` | 자원 지키기와 일반 물건 놓기를 어떻게 구분하며 교환·신호를 어떤 단계로 가르치는가? |
| 생활 훈련 — 배변 | 중간 이하·조건부. 대학 교육용 교재가 직접 다루지만 임상시험이나 최신 전문 가이드라인은 아니다. | 신규 `umn-veterinary-preventive-medicine-behavior-2022` | CC BY-NC 4.0. 비상업 이용·귀속·변경 표시 조건부이며 상업성 불명확 시 `hold` | HTML `Housetraining` 절을 locator candidate로 사용 가능 | `proceed_with_conditions` — 비상업 요건과 semantic review를 통과한 일반 학습·관리 claim만 | 연령·건강·주거조건별 횟수와 일정, 실수 지속 시 의학적 평가 기준, 개체별 예상 기간은 답할 수 없음 |
| 생활 훈련 — 하우스·켄넬 | 중간 이하·조건부. 대학 교재가 crates and kennels를 직접 다루나 보편적 효과를 검증한 연구는 아니다. | 신규 `umn-veterinary-preventive-medicine-behavior-2022` | CC BY-NC 4.0 조건부. 제3자 이미지·제품 요소 제외, 상업성 불명확 시 `hold` | HTML `Crates and kennels` 절을 locator candidate로 사용 가능 | `proceed_with_conditions` — 제한된 적응·관리 원리만 | 적정 수용 시간, 울음·불안·분리 관련 행동의 감별, 강아지별 진행 속도와 중단 기준은 답할 수 없음 |
| 산책 훈련 — 리드줄 당김 | 낮음·조건부. 고령 보호자 14명 대상 단일군 feasibility 연구로, 일반 효과 시험이 아니다. | 신규 `pmc9680302-leash-walking-feasibility` | 논문 본문 CC BY 4.0 조건부. 요청 제공 원자료와 제3자 요소 제외 | PMCID·DOI와 `2.2 Procedures`, `3.2 Process Evaluation`, `4 Discussion`을 locator candidate로 사용 가능 | `proceed_with_conditions` — 좁은 표본에서 프로그램의 구성·실행 가능성만 | 모든 보호자·개에서 당김이 얼마나 감소하는가? 단계별 속도·거리·장비 선택과 장기 유지 효과는 무엇인가? |
| 산책 훈련 — 리콜 | 낮음. 기본 명령의 이리 와와 동일한 근거 공백이며 산책 환경 일반화 자료가 없다. | 기존 `pmc7387681-e-collar-training-efficacy`; UC Davis recall 안내 | 기존 PMC 조건부, UC Davis 원문 재사용 `hold` | 기존 PMC locator candidate만 제한적으로 가능 | `hold` | 야외 방해 자극, 안전줄, 이탈·실패 관리, 울타리 밖 일반화를 포함한 검증된 절차는 무엇인가? |
| 문제행동 초기 대응 — 입질·마우딩 | 낮음. 3마리 대상 owner-implemented 기능 분석 연구는 직접 관련되지만 공개 열람과 재사용 허가는 별개다. | PMC8854529, “Owner-Implemented Functional Analyses and Reinforcement-Based Treatments for Mouthing in Dogs” | PMC 전문은 열람 가능하나 논문별 명시적 CC 라이선스를 확인하지 못해 본문 변형·RAG 적재 `hold` | PMCID와 절 구조는 후보가 될 수 있으나 재사용 전진 불가 | `hold` | 놀이성 마우딩과 실제 공격·통증·공포성 입질을 어떻게 안전하게 구분하는가? 가정에서 시도 가능한 범위와 즉시 전문가에게 의뢰할 기준은 무엇인가? |
| 문제행동 초기 대응 — 짖음 | 낮음·조건부. kennel ward의 11마리 pilot로 특정 통행 자극 맥락만 다룬다. | 신규 `pmc8772564-quiet-kennel-barking`; Agriculture Victoria “Barking dogs” | PMC 논문 본문은 CC BY 4.0 조건부. Agriculture Victoria는 개인·기관 내부·비상업 복제 범위만 명확해 RAG 변형은 `hold` | PMC PMCID·DOI·절 제목 후보 가능. 정부 페이지는 링크·메타데이터만 | `proceed_with_conditions` — kennel 통행 맥락의 pilot 관찰만. 가정 짖음은 `hold` | 경계·요구·분리·통증 관련 짖음을 어떻게 구분하고 각각 어떤 초기 대응을 하는가? 장기 효과는 있는가? |
| 문제행동 초기 대응 — 점프 | 낮음·조건부. 5마리 기능 분석과 4마리 개입의 단일사례 연구이며 4마리 중 3마리에서 감소가 관찰됐다. | 신규 `pmc6940775-jumping-up-functional-analysis` | 논문 본문 CC BY 4.0 조건부. 영상·원자료·제3자 요소 제외 | PMCID·DOI와 Experiment·Results·Discussion 절을 locator candidate로 사용 가능 | `proceed_with_conditions` — 행동 기능과 맥락 의존성 및 소규모 결과만 | 보호자가 전문 기능 분석 없이 안전하게 할 수 있는 첫 단계는 무엇인가? 다른 방문자·장소와 장기 유지에 일반화되는가? |

## 신규 source audit과 잠정 coverage 결론

### `proceed_with_conditions`

- `umn-veterinary-preventive-medicine-behavior-2022`: 배변 및 하우스·켄넬에 직접 관련되지만 현재 RAG 판단에는 더 제한적인 CC BY-NC 4.0을 적용한다. 비상업 프로토타입에서만 조건부로 검토하고 상업 서비스로 자동 승격하지 않으며, 두 공식 페이지의 라이선스 표기 충돌은 미해결 상태다.
- `pmc9680302-leash-walking-feasibility`: 리드줄 보행 프로그램의 feasibility를 좁은 고령 보호자 표본에서만 설명할 수 있다.
- `pmc6940775-jumping-up-functional-analysis`: 점프 행동의 기능·맥락별 차이와 일부 단일사례 결과만 설명할 수 있다.
- `pmc8772564-quiet-kennel-barking`: kennel 통행 자극 상황의 pilot 결과로만 제한한다.

이 결정은 라이선스상 재사용 가능성만으로 만들어지지 않았다. 각 출처의 DAENGS 상담 관련성과 허용 claim scope를 별도 audit에 기록했으며, 후속 semantic review 전에는 근거 단위로 전환하지 않는다.

## Holds와 rejects

### `hold`

- UC Davis, “Recall Training in Dogs”: 대학 수의과대학의 직접 안내지만 서면 동의 없는 복제를 금지하므로 링크·메타데이터 외 RAG 이용을 보류한다.
- Cornell, “Training ‘stay’ vs. ‘wait’”: 대학 페이지이나 제3자 Cornell DogWatch 발행물을 허가받아 재게시한 자료로 재사용 권리가 불명확하다.
- PMC8854529 mouthing 연구: 직접 관련성은 있으나 개별 논문의 명시적 CC 라이선스를 확인하지 못했고 표본이 3마리로 제한된다.
- Agriculture Victoria, “Barking dogs”: 정부 안내이나 확인한 copyright 조건만으로는 변형·RAG 적재가 명확하지 않다.
- 앉아, 엎드려, 놓아: 이번 우선 출처군에서 직접적이고 재사용 조건이 명확한 단계별 교수 근거를 확보하지 못했다.

### `reject` for training prescription

- New Zealand MPI *Code of Welfare: Dogs*: 정부 저작물의 CC BY 4.0 표시는 확인되지만 행동 절의 dominance·hierarchy framing이 현재 AVSAB dominance position과 충돌하므로 일반 훈련 taxonomy와 처방 근거로 사용하지 않는다. 법적·복지 맥락이 필요할 때 별도 재검토한다.
- 특정 견종의 공격성 자료를 일반 반려견 행동으로 확장하는 후보는 선정하지 않았다.
- 진단·치료가 필요한 공격성, 통증, 분리 관련 행동을 일반 훈련 단계로 변환하는 claim은 이 체크포인트 범위에서 reject한다.

## Locator 및 claim 관리 원칙

- 모든 위치 표시는 `locator candidate`이며 확정값이 아니다.
- PMC는 PMCID, DOI, 절 제목을 함께 사용하고 문장 단위 의미와 제한점을 semantic review한다.
- HTML 교재는 공식 URL, 장 제목, 절 경로, 확인일을 함께 사용한다.
- 동적 페이지의 줄 번호와 검색 결과 snippet은 locator로 사용하지 않는다.
- 라이선스가 허용되는 본문이라도 제3자 이미지·척도·도구·원자료에 같은 라이선스가 자동 적용된다고 판단하지 않는다.

## 남은 needs_review

- DAENGS 운영 형태가 UMN 교재의 CC BY-NC 4.0 비상업 조건에 부합하는지 검토
- Pressbooks의 CC BY-NC 4.0과 Open Textbook Library에서 관찰된 CC BY 4.0 표기 충돌의 변경 이력·적용 범위 검토. 2026-08-12 현재 목록이 CC BY-NC로 표시되는 사실만으로 충돌이 해소됐다고 판단하지 않음
- PMC 세 논문의 candidate 문장을 연구 설계·표본·환경 한계와 분리하지 않는 semantic review
- 기다려와 wait/stay 용어의 제품 taxonomy를 정하기 전 공식적이고 재사용 가능한 직접 출처 추가 탐색
- 엎드려, 놓아, 야외 리콜, 가정 내 짖음, 안전한 입질 초기 대응의 OA 또는 명시적 공공 라이선스 출처 추가 탐색
- 의료·행동 전문가 의뢰 기준은 수의학적 진단을 훈련 조언으로 바꾸지 않는 별도 안전 검토 필요

## 근거 링크

- UMN Behavior 장: https://pressbooks.umn.edu/vetprevmed/chapter/chapter-9-behavior/
- UMN Pressbooks license 표시: https://pressbooks.umn.edu/vetprevmed/part/main-body-2/
- Open Textbook Library 목록: https://open.umn.edu/opentextbooks/textbooks/1133
- Leash walking feasibility: https://pmc.ncbi.nlm.nih.gov/articles/PMC9680302/
- Jumping up functional analysis: https://pmc.ncbi.nlm.nih.gov/articles/PMC6940775/
- Quiet Kennel Exercise: https://pmc.ncbi.nlm.nih.gov/articles/PMC8772564/
- UC Davis recall: https://healthtopics.vetmed.ucdavis.edu/health-topics/canine/recall-training-dogs
- Cornell stay vs. wait: https://www.vet.cornell.edu/departments-centers-and-institutes/riney-canine-health-center/canine-health-information/training-stay-vs-wait
- Mouthing study: https://pmc.ncbi.nlm.nih.gov/articles/PMC8854529/
- Agriculture Victoria barking: https://agriculture.vic.gov.au/livestock-and-animals/animal-welfare-victoria/dogs/dog-training-and-behavioural-problems/barking-dogs
- New Zealand MPI Code of Welfare: Dogs: https://www.mpi.govt.nz/animals/animal-welfare/codes/all-animal-welfare-codes/code-of-welfare-dogs

## 범위 제한 확인

- 기존 source audit, 코드, 환경 파일을 수정하지 않았다.
- 원문, PDF, XML, 자막, 이미지, 데이터셋 또는 대량 추출물을 저장하지 않았다.
- EvidenceCard, JSONL, ReviewDecision, 임베딩 또는 Qdrant payload를 생성하지 않았다.
- 이 문서는 coverage gap 조사 결과이며 최종 DAENGS taxonomy나 훈련 처방을 확정하지 않는다.
