# Evidence Seed v0 — Semantic Review Record

## 상태와 범위

- 체크포인트: Data-2
- 작성일: 2026-08-12
- 카드 수: 8
- EvidenceCard 내장 상태: `PENDING_SEMANTIC_REVIEW` — v1 계약상 카드 본체에는 pending만 기록한다.
- 별도 ReviewDecision effective 상태: `APPROVED` 8건
- 이 문서는 영어 출처에서 새로 작성한 한국어 요약의 source alignment와 limitations 범위를 검토한 내부 기록이다. 임상 효능 보증이나 상업 사용 승인이 아니다.
- 원문 전체, 장문 인용, 표·그림·부록·원자료는 저장하지 않았다.

## Registry 권리 처리 요약

- Registry에는 실제 카드가 참조하는 source audit 6건만 등록했다.
- PMC 5건은 개별 논문의 CC BY 4.0을 근거로 `rag_use`를 귀속·라이선스 링크·변경 고지 및 제3자 요소 제외 조건부로 기록했다. 자동 수집은 `unknown`이며, 논문의 라이선스가 별도 credit의 표·그림, 외부 도구, 영상, 부록 또는 원자료에 자동 적용된다고 해석하지 않았다.
- UMN은 공식 페이지의 라이선스 표기 충돌을 해소하지 않고 더 제한적인 CC BY-NC 4.0을 적용했다. `rag_use`는 저작자·발행자 표시와 변경 고지를 전제로 비상업 교육용 프로토타입에서만 조건부이며, `commercial_use`는 `prohibited`다.
- 재사용 권리 상태는 카드의 evidence relevance나 연구 강도를 뜻하지 않는다.

## 카드별 derivation 기록

### `0dfe3a92-445c-4c82-a789-5e23cd02f101`

- 한국어 claim: 7개 훈련학교의 반려견 92마리를 비교한 준실험 연구에서, 혐오 자극 사용 비율이 높은 집단은 보상 기반 집단보다 훈련 중 스트레스 관련 행동과 일부 생리·인지 지표에서 더 부정적인 결과를 보였다.
- `source_id`: `pmc7743949-aversive-training-welfare`
- source 원문 언어: `en`
- claim 언어: `ko`
- derivation 유형: `translated_summary`
- locator: `pmc_article`; `PMCID PMC7743949`; `DOI 10.1371/journal.pone.0225023`; section `Results`
- evidence_level: `DIRECT`
- 연구·적용 한계: 훈련학교 단위 준실험이며 무작위 배정이 아니다. 학교·훈련사·보호자·기존 특성의 잔여 교란 가능성이 있고, 방법 범주가 개별 도구·강도·타이밍을 분리하지 않는다. 측정값을 개별 개의 진단이나 모든 혐오 자극의 동일 인과 효과로 확대하지 않는다.
- 라이선스/RAG 조건: CC BY 4.0 적용 본문을 새로 요약했다. 저자·PLOS ONE·canonical URL·라이선스 표시와 변경 고지가 필요하며 별도 credit 요소, 외부 도구, 부록·원자료는 제외한다.
- semantic review 상태: `approved`
- 검토자가 확인해야 할 질문: “더 부정적인 결과”가 행동·코르티솔·인지 편향 결과의 방향과 통계 범위를 과장하지 않는가? 준실험이라는 제한이 claim과 함께 노출되는가?

### `1e8b640c-6731-4a6c-9fe2-328838ac4102`

- 한국어 claim: 63마리를 세 집단으로 비교한 5일간의 제한된 recall·sit 연구에서는 e-collar 집단이 보상 중심 집단보다 더 효율적이거나 e-collar가 필요하다는 근거가 나타나지 않았다.
- `source_id`: `pmc7387681-e-collar-training-efficacy`
- source 원문 언어: `en`
- claim 언어: `ko`
- derivation 유형: `translated_summary`
- locator: `pmc_article`; `PMCID PMC7387681`; `DOI 10.3389/fvets.2020.00508`; section `Results`
- evidence_level: `DIRECT`
- 연구·적용 한계: 집단별 21마리, 전문 훈련사, 5일간 최대 150분의 recall·sit 과제다. 훈련사 스타일과 장치 효과가 완전히 분리되지 않았고 후속 commentary의 통계·해석 비판이 있다. 다른 문제행동이나 장기 효과로 일반화하지 않는다.
- 라이선스/RAG 조건: CC BY 4.0 적용 본문의 새 한국어 요약이다. 저자·Frontiers in Veterinary Science·canonical URL·라이선스 표시와 변경 고지가 필요하며 원 영상·원자료·제3자 요소는 제외한다.
- semantic review 상태: `approved`
- 검토자가 확인해야 할 질문: “근거가 나타나지 않았다”가 부재의 증거로 과장되지 않는가? 후속 commentary를 별도 supporting source로 등록하지 않은 상태에서 한계 설명이 충분한가?

### `2a971dc0-17ca-4d58-b228-74ea827a2203`

- 한국어 claim: 사람에게 점프하는 행동을 조사한 소규모 단일사례 연구에서는 행동을 유지하는 강화 기능이 개체별로 달라, 점프를 하나의 공통 원인으로 단정하기 어려웠다.
- `source_id`: `pmc6940775-jumping-up-functional-analysis`
- source 원문 언어: `en`
- claim 언어: `ko`
- derivation 유형: `translated_summary`
- locator: `pmc_article`; `PMCID PMC6940775`; `DOI 10.3390/ani9121091`; section `3 Experiment 1`
- evidence_level: `DIRECT`
- 연구·적용 한계: 5마리 단일사례 기능 분석이며 가정 방문·현관 맥락에 한정된다. 전문 기능 분석을 보호자의 자가 절차나 점프 행동의 진단 도구로 변환하지 않는다.
- 라이선스/RAG 조건: CC BY 4.0 적용 본문의 새 한국어 요약이다. 저자·학술지·canonical URL·라이선스 표시와 변경 고지가 필요하며 영상·원자료·제3자 요소는 제외한다.
- semantic review 상태: `approved`
- 검토자가 확인해야 할 질문: 원 연구가 확인한 강화 기능의 개체 차이를 정확히 보존하는가? “공통 원인으로 단정하기 어렵다”가 표본 범위를 넘어선 일반 명제로 읽히지 않는가?

### `3bc84211-908e-4db3-85e4-b11df6063304`

- 한국어 claim: 점프 행동의 기능에 맞춰 시간 기반 강화를 적용한 소규모 연구에서 4마리 중 3마리는 점프가 감소했지만 1마리는 반응하지 않아, 같은 개입의 효과가 모든 개에게 일관되지는 않았다.
- `source_id`: `pmc6940775-jumping-up-functional-analysis`
- source 원문 언어: `en`
- claim 언어: `ko`
- derivation 유형: `translated_summary`
- locator: `pmc_article`; `PMCID PMC6940775`; `DOI 10.3390/ani9121091`; section `4.4 Results`
- evidence_level: `DIRECT`
- 연구·적용 한계: 4마리 단일사례 연구이고 비교집단이 없다. 특정 방문 맥락과 개체별 강화 기능에 의존하며 장기 유지와 다른 환경으로의 일반화가 확립되지 않았다. 보편적 단계별 점프 훈련 절차로 바꾸지 않는다.
- 라이선스/RAG 조건: CC BY 4.0 적용 본문의 새 한국어 요약이다. 저자·학술지·canonical URL·라이선스 표시와 변경 고지가 필요하며 영상·원자료·제3자 요소는 제외한다.
- semantic review 상태: `approved`
- 검토자가 확인해야 할 질문: 3/4와 비반응 사례가 정확한가? “기능에 맞춰”라는 표현이 연구 개입과 일치하며 보호자가 스스로 기능 분석을 하라는 권고로 읽히지 않는가?

### `4c518ae7-a44d-4b95-bb92-8b67cb125505`

- 한국어 claim: 한 대학 부속 반려견 주간보호시설의 한 견사 구역에서 11마리를 관찰한 pilot 연구에서는 사람이 지나갈 때 행동과 무관하게 간식을 제공한 기간에 일부 짖음 지표의 감소 경향이 관찰됐다.
- `source_id`: `pmc8772564-quiet-kennel-barking`
- source 원문 언어: `en`
- claim 언어: `ko`
- derivation 유형: `translated_summary`
- locator: `pmc_article`; `PMCID PMC8772564`; `DOI 10.3390/ani12020171`; section `3.1 Results`
- evidence_level: `DIRECT`
- 연구·적용 한계: 총 11마리, 단일 시설, 통제군 부재, 서로 다른 출석 일수를 가진 pilot이다. 가정 짖음, 분리 관련 행동, 통증·질환 관련 발성으로 일반화하지 않으며 장기·인과 효과를 주장하지 않는다.
- 라이선스/RAG 조건: CC BY 4.0 적용 본문의 새 한국어 요약이다. 저자·학술지·canonical URL·라이선스 표시와 변경 고지가 필요하며 요청 제공 데이터와 제3자 요소는 제외한다.
- semantic review 상태: `approved`
- 검토자가 확인해야 할 질문: “일부 짖음 지표의 감소 경향”이 결과의 탐색적 성격을 정확히 반영하는가? counterconditioning이라는 저자 용어와 행동 비의존 간식 제공 절차를 혼동하지 않는가?

### `5d629cb3-f011-4217-8c56-f3cb429f6606`

- 한국어 claim: 60세 이상 보호자 14명이 참여한 단일군 feasibility 연구에서는 3주간의 보상 기반 리드줄 보행 수업을 운영할 수 있었고, 완료자 일부가 기술 향상을 자기보고했다.
- `source_id`: `pmc9680302-leash-walking-feasibility`
- source 원문 언어: `en`
- claim 언어: `ko`
- derivation 유형: `translated_summary`
- locator: `pmc_article`; `PMCID PMC9680302`; `DOI 10.3390/geriatrics7060120`; section `3.2 Process Evaluation`
- evidence_level: `DIRECT`
- 연구·적용 한계: 14명 등록·12명 완료의 소규모 단일군이며 통제군이 없다. 목적은 feasibility와 수용성이지 당김 감소 효능 입증이 아니다. 공격성 있는 개와 낙상 위험이 큰 보호자를 제외한 고령 표본이다.
- 라이선스/RAG 조건: CC BY 4.0 적용 본문의 새 한국어 요약이다. 저자·학술지·canonical URL·라이선스 표시와 변경 고지가 필요하며 요청 제공 데이터와 제3자 요소는 제외한다.
- semantic review 상태: `approved`
- 검토자가 확인해야 할 질문: feasibility와 efficacy가 명확히 구분되는가? “운영할 수 있었다”와 자기보고 향상이 원 연구의 process evaluation 범위를 넘지 않는가?

### `6e73ad54-2c9f-48da-a261-076df3087707`

- 한국어 claim: 이 대학 교육용 교재는 배변 훈련의 기초를 나이에 맞춘 일관된 관리와 원하는 장소에서 배설한 직후의 강화로 설명하며, 사후에 발견한 실수를 처벌하는 방식은 학습에 도움이 되지 않는다고 안내한다.
- `source_id`: `umn-veterinary-preventive-medicine-behavior-2022`
- source 원문 언어: `en`
- claim 언어: `ko`
- derivation 유형: `translated_summary`
- locator: `html`; section `Small Animal Behavior > Dog Topics > Housetraining > Basics of Housetraining`
- evidence_level: `DIRECT`
- 연구·적용 한계: 대학 교육용 교재이며 동료심사 임상시험이나 최신 전문 가이드라인이 아니다. 개체별 일정·성공 기간을 제시하지 않고 지속적 배변 문제를 의료 평가 없이 단순 훈련 문제로 단정하지 않는다.
- 라이선스/RAG 조건: 더 제한적인 CC BY-NC 4.0을 보수적으로 적용한다. Margaret Root Kustritz와 University of Minnesota Libraries Publishing, canonical URL, 라이선스 링크, 변경 고지를 표시한 비상업 교육용 프로토타입에서만 조건부다. 제3자 요소를 제외하고 상업 서비스로 자동 승격하지 않는다.
- semantic review 상태: `approved`
- 검토자가 확인해야 할 질문: 관리·즉시 강화·사후 처벌 회피가 교재 절의 의미를 정확히 요약하는가? 의료적 배변 문제와 개체별 조건을 가리는 보편 처방으로 읽히지 않는가?

### `7f84be65-d3a0-43e1-94c7-2cc84b698808`

- 한국어 claim: 이 대학 교육용 교재는 crate 적응을 개가 자발적으로 드나들며 긍정적 경험을 쌓고 머무는 시간을 점진적으로 늘리는 과정으로 설명하고, crate를 처벌 수단으로 사용하지 않도록 안내한다.
- `source_id`: `umn-veterinary-preventive-medicine-behavior-2022`
- source 원문 언어: `en`
- claim 언어: `ko`
- derivation 유형: `translated_summary`
- locator: `html`; section `Small Animal Behavior > Dog Topics > Crates and kennels`
- evidence_level: `DIRECT`
- 연구·적용 한계: 대학 교육용 교재이며 보편적 효과를 검증한 임상시험이 아니다. 적정 수용 시간, 불안·울음 원인, 진행 속도·중단 기준을 단정하지 않고 분리 관련 행동이나 의료 문제의 처방으로 사용하지 않는다.
- 라이선스/RAG 조건: 더 제한적인 CC BY-NC 4.0을 보수적으로 적용한다. Margaret Root Kustritz와 University of Minnesota Libraries Publishing, canonical URL, 라이선스 링크, 변경 고지를 표시한 비상업 교육용 프로토타입에서만 조건부다. 제3자 요소를 제외하고 상업 서비스로 자동 승격하지 않는다.
- semantic review 상태: `approved`
- 검토자가 확인해야 할 질문: 자발적 출입·긍정적 연관·점진적 시간 증가·처벌 금지라는 요약이 교재 범위를 정확히 보존하는가? 불안을 보이는 개에게 동일 절차를 강요하는 문장으로 읽히지 않는가?

## UMN unresolved condition

- Pressbooks 공식 본문은 CC BY-NC 4.0을 표시한다: https://pressbooks.umn.edu/vetprevmed/part/main-body-2/
- Open Textbook Library 목록에서 CC BY 4.0 표기가 관찰됐다는 기존 체크포인트 기록이 있으나, 2026-08-12 재확인 화면은 CC BY-NC를 표시했다: https://open.umn.edu/opentextbooks/textbooks/1133
- 변경 이력과 적용 범위를 확인하지 못했으므로 충돌이 해소됐다고 판단하지 않는다. 현재 Registry와 두 카드에는 더 제한적인 CC BY-NC 4.0을 적용한다.

## 이번 seed에서 만들지 않은 카드

- 앉아, 엎드려, 손, 기다려, 리콜, 놓아, 입질 대처: 현재 audit만으로 직접적이고 재사용 가능한 단계별 근거가 부족하거나, 연구 결과가 교수 절차 전체를 뒷받침하지 않는다.
- AVSAB·AAHA·C-BARQ·Wolfram: 이번 seed의 허용 범위에서 제외됐거나 원문 변형·RAG 이용 권리가 불명확하다.
- 특정 견종의 공격성, 의료·응급 진단 및 처방: 생성하지 않았다.

## 검토 게이트

- 카드 본체의 상태 필드는 계약상 pending으로 유지되지만, `review_decisions.jsonl`에는 reviewer `frankie516c`의 현재 content hash에 결합된 APPROVED 결정 8건이 있다.
- 로더상 8개 카드는 RAG eligible이며 출처별 `rag_use` 조건을 계속 집행해야 한다. 이 승인은 임상 효능이나 상업적 재사용을 승인하지 않는다.
- claim이나 limitation이 수정되면 공식 모델의 canonical content hash가 달라지므로 이후 결정은 수정된 내용으로 다시 계산해야 한다.
