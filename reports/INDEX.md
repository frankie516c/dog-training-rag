# 리포트 인덱스

`reports/` 31개(+하위 `research_graph_viability_0824/` 5개, 실제 총 35개) .md 파일 전체를 읽고
`docs/decision_*.md`와 대조해 상태를 판정한 색인입니다. 이 파일 자체가 리포트를 대체하지
않습니다 — 원본은 전혀 수정하지 않았고, 여기서는 "지금 무엇이 살아있는 결론인지"만 정리합니다.

이 프로젝트는 **폐기된 결론도 지우지 않고 보존**하는 원칙을 씁니다. 아래 "역사적 기록" 절이
그 실천입니다.

---

## 현재 유효한 결론

- **아키텍처: 벡터 RAG 단독.** 엔티티 추출·Neo4j·하이브리드 검색(GraphRAG)을 완전히 폐기했다.
  근거: [docs/decision_graphrag_abandoned_0824.md](../docs/decision_graphrag_abandoned_0824.md),
  [retrieval_perf_graph_vs_vector_0824.md](retrieval_perf_graph_vs_vector_0824.md)(그래프가 랭킹
  지표를 32/32 질의에서 전혀 개선하지 못함 — 코드 구조상 필연).

- **견종(breed) 축은 검색 조건 축이 아니다.** 처치를 가르는 문장 0건(v1)~7.3%대 소수(연령축
  대비), 형질-only 비율이 견종어보다 우세. 다만 `Breed` 노드 자체(유전질환용)는 유지한다 —
  이건 *검색 축 기각*이지 *노드 삭제*가 아니다.
  근거: [breed_conditionality_0822.md](breed_conditionality_0822.md).

- **환경 축(ContextFactor: absence/numeric)은 폐기됐다.** 핵심 근거였던 "혼자→분리불안
  260건 비순환 교차"의 83.1%가 이미 기각된 `space_setup`과 동일한 순환 매칭 오염으로
  드러났다. 근거: [docs/decision_env_axis_discarded_0824.md](../docs/decision_env_axis_discarded_0824.md),
  [research_graph_viability_0824/02_env_axis_projection_dev.md](research_graph_viability_0824/02_env_axis_projection_dev.md).

- **청킹 설정은 v3(target 420 / min 150 / max 480자) 유지.** 대형 청크(v4, 600/220/650)
  실험은 Hit@1·MRR·기대일치 세 지표 모두 v3보다 나빴다.
  근거: [chunking_v4_experiment_0825.md](chunking_v4_experiment_0825.md).

- **검색 게이트 신호는 `score_gap`이 아니라 `margin_top5`가 낫다는 결론이 확정됐다.** 48건
  픽스처 중 임계값 결정에 관여하지 않은 held-out 28건에서 92.9% 일치(기저선 67.9% 대비 우위),
  코퍼스가 83→245청크로 3배 커지는 동안도 흔들리지 않고 오히려 개선됐다. **다만 실제
  `GATE_THRESHOLD` 기본값 전환은 아직 사용자 승인 대기 상태**다(코드 옵션만 추가됨).
  근거: [retrieval_gate_redesign_retry_0825.md](retrieval_gate_redesign_retry_0825.md)
  (1차 시도 [retrieval_gate_redesign_0825.md](retrieval_gate_redesign_0825.md)는 표본 20건
  부족으로 판단 불가였고 48건 확장 후 재시도로 대체됨).

- **현재 코퍼스는 83청크가 아니라 245청크(다양성 우선 확장).** 같은 저자 볼륨 확장(6→68문서,
  Track B)은 gold 성능 하락(Hit@1 0.667→0.583)으로 **롤백**됐다. 반면 제3의 저자·기관 6곳을
  추가한 확장(6→17문서, 83→245청크, Track B2)은 headline 지표(Hit@1) 유지·조달 목표 다수
  개선으로 **롤백하지 않고 유지** 중이다. 교훈: "양보다 다양성".
  근거: [corpus_expansion_diverse_0825.md](corpus_expansion_diverse_0825.md)(현재 상태),
  [corpus_expansion_0825.md](corpus_expansion_0825.md)(롤백된 대조군, 폐기 아님·보존).

- **owner_fixtures는 20건이 아니라 48건(REFUSE 33 · ANSWER 15)이 현재 기준.**
  근거: [owner_fixtures_expansion_0825.md](owner_fixtures_expansion_0825.md).

- **의료 가드레일은 v2 + `training_whitelist_v1`이 confirmed(2026-08-20) 상태.** v1(코퍼스
  추출 기반 사전)은 재현율·정밀도 모두 실패했고, v2(손수 작성 일반 수의 어휘 + 훈련
  화이트리스트)로 교체됐다. Q16(과거형 "진단을 받은" vs 요청 "진단해 주세요" 구분 불가)만
  알려진 한계로 남아 있다(안건화, 미해결).
  근거: [medical_guardrail_v1v2_comparison.md](medical_guardrail_v1v2_comparison.md).

- **출력 가드레일은 `SystemAuthoredText`/`apply_output_guardrail()` 구조로 수정 완료.**
  사람이 쓴 안전 문구("병원 가세요")가 자기 자신의 위험 어휘 필터에 걸려 차단되는 사고를
  겪은 뒤, "무엇이 쓰였는가"가 아니라 "누가 썼는가"(타입)로 예외를 거는 구조로 고쳤다.
  근거: [output_guardrail_self_block_incident.md](output_guardrail_self_block_incident.md).

---

## 열린 질문 (진행중)

- **유튜브 자동자막 전면 배제 원칙 — 재검토 진행중, 아직 정책 변경 안 됨.** faster-whisper
  재전사가 기술적으로는 가능하고 일부 오류 유형(고유명사·문장구조)에서 자동자막보다
  나았지만, paired comparison이 n=1이라 "60건 배치 투입 승인 수준은 아니다"로 스스로
  하향 조정했다. A/B/C/D 등급제 초안이 나와 있으나 B등급의 실제 채택 게이트 조건은
  미확정. 무프롬프트 ablation·9분 reference 작업지도 사람 작업 대기 상태.
  근거: [whisper_retranscription_experiment_0825.md](whisper_retranscription_experiment_0825.md).
  (관련: [youtube_channel_diversity_check_0825.md](youtube_channel_diversity_check_0825.md) —
  설채현 채널은 자동분류 신호 품질이 27배 좋지만 수동자막 0%라 현재 정책상 배제된 상태.)

- **wayopet.com 6건(저자 3명, 다수 자격증 훈련사) — 파서는 완성, 실제 인제스트·재평가는
  아직 안 함.** 다음 라운드로 명시적으로 이월됨.
  근거: [wayopet_custom_parser_0825.md](wayopet_custom_parser_0825.md).

- **`margin_top5`를 운영 기본 게이트로 실제 전환할지 — 사용자 승인 대기.** 코드 옵션은
  만들어졌고 근거도 확정됐으나, `GATE_THRESHOLD` 기본값 자체는 아직 `score_gap` 그대로다.
  근거: [retrieval_gate_redesign_retry_0825.md](retrieval_gate_redesign_retry_0825.md).

- **`combined_corpus_coverage.md`의 사람 coverage 재판정 다수가 공란.** Q06·Q12~Q16 등
  다수 문항이 `coverage 재판정: [ ]`로 비어 있어 사람 확인 대기 중.
  근거: [combined_corpus_coverage.md](combined_corpus_coverage.md).

- **AVSAB PDF의 정식 MANIFEST 스키마(HTML/PDF 소스 구분 필드) 설계 — 미결.** 실제 콘텐츠는
  이미 [corpus_expansion_diverse_0825.md](corpus_expansion_diverse_0825.md)에서 코퍼스에
  통합됐지만(115청크), MANIFEST에 문서 소스 종류를 구분하는 필드를 추가할지는 여전히
  미결 사항으로 남아 있다. 근거: [avsab_pdf_pipeline_0825.md](avsab_pdf_pipeline_0825.md).

- **`docs/agenda_0825.md`의 다수 항목**(가드레일 의미 기반 분류 Q16, 그래프 시드 매칭 확장
  등 그래프 폐기로 무의미해진 항목 제외하고도, 주제 태깅 오탐·lens 명칭 불일치 등)이 여전히
  미해결 백로그다 — 이 INDEX 범위 밖이라 목록만 남긴다.

---

## 역사적 기록 (폐기됨)

**원칙: 삭제하지 않는다.** 아래는 방향 전환으로 더 이상 유효하지 않은 결론들과, 왜
무효화됐는지를 한 줄씩 기록한다.

| 리포트 | 폐기 사유 / 무엇이 대체했는가 |
|---|---|
| [research_graph_viability_0824/00_SYNTHESIS.md](research_graph_viability_0824/00_SYNTHESIS.md) | 그래프DB를 "조건부 유지"로 판정했으나, 이후 실측(retrieval_perf_graph_vs_vector_0824)과 비용 문제로 **완전 폐기**가 최종 결정됨(decision_graphrag_abandoned_0824.md) |
| [research_graph_viability_0824/01_connectivity_audit_dev.md](research_graph_viability_0824/01_connectivity_audit_dev.md) | 위와 동일 — 그래프 구조 실측 자체는 완전 폐기 결정의 근거 자료로 편입됐으나, "조건부 유지"라는 판단 방향은 무효화됨 |
| [research_graph_viability_0824/03_graphrag_sparsity_literature_researcher.md](research_graph_viability_0824/03_graphrag_sparsity_literature_researcher.md) | 그래프 희소성 문헌 검토 — 그래프 접근 자체가 폐기되며 논의 목적이 무의미해짐(문헌 서베이 내용은 참고 가치로 남음) |
| [research_graph_viability_0824/04_alternative_axis_candidates_researcher.md](research_graph_viability_0824/04_alternative_axis_candidates_researcher.md) | "그래프에 얹을 대안 축 우선순위"(심각도>절차>ABC>연령대>원칙) — 그래프 자체가 폐기되며 우선순위 목록의 전제가 사라짐 |
| [agegroup_axis_corpus_diagnosis_0824.md](agegroup_axis_corpus_diagnosis_0824.md) | 연령대축 그래프 승격 가능성 진단 — GraphRAG 완전 폐기로 목적 자체가 무효화. 저자 편중(2명뿐) 발견은 corpus_expansion 작업에 승계됨 |
| [procedure_agegroup_axis_measurement_0824.md](procedure_agegroup_axis_measurement_0824.md) | 절차/연령대 축 1차 실측(그래프용) — 같은 이유로 폐기. 크로스문서 재사용이 단일 저자 문체 반복이라는 발견은 저자다양성 문제의 최초 증거로 승계됨 |
| [procedure_axis_source_diagnosis_0824.md](procedure_axis_source_diagnosis_0824.md) | 절차축 그래프 소스 진단(핀셋 조달 10~20건 권고) — 그래프 폐기로 무효. "821문서 풀이 저자 2명뿐"이라는 핵심 발견은 decision_graphrag_abandoned_0824.md와 corpus_expansion 작업의 직접 근거로 승계됨 |
| [env_axis_measurement_0822.md](env_axis_measurement_0822.md) | 환경축 원시 실측 — 순환 매칭 오염(83.1%)을 당시엔 못 잡아냈고, 이후 재검증(research_graph_viability_0824/02)에서 핵심 근거 수치가 오염된 것으로 밝혀짐. `docs/decision_env_axis_discarded_0824.md`가 이를 대체 |
| [graphrag_final_attempt_stage1_sourcing_0824.md](graphrag_final_attempt_stage1_sourcing_0824.md) | GraphRAG "마지막 투자 시도" 1단계(조달+v3 프롬프트) — 2단계 착수 전 OpenAI 비용 거부 + 무비용 검증(임베딩 유사도)까지 실패해 **완전 폐기**로 귀결. 신규 확보한 핏펫 8건은 벡터RAG 코퍼스 자료로는 유효하게 남음 |
| [retrieval_gap_hybrid_vs_vector_0820.md](retrieval_gap_hybrid_vs_vector_0820.md) | Q12~Q15 하이브리드(그래프) vs 벡터 생성 비교 — 그래프 경로 자체가 폐기되어 "하이브리드가 낫다"는 관찰(생성 품질 층위)이 더 이상 재현 불가능한 경로에 대한 기록이 됨. 벡터 단독 결과·어휘 불일치 진단은 여전히 유효한 정보 |
| [demo_outputs_0820.md](demo_outputs_0820.md) | 발표용 데모 출력 — 시나리오③(Q13)이 그래프 하이브리드 2홉 구제를 시연하는 내용이라 그래프 폐기로 무효. 시나리오①④(벡터 단독·의료 가드레일)와 q003 조사는 개별 사실로는 유효하나 83청크·구버전 게이트 임계값(0.024) 기준의 스냅샷 |
| [reproducibility_check_0822.md](reproducibility_check_0822.md) | 그래프 기반 데모 시나리오(③ Q13) 재현성 확인 — 그래프 경로 자체가 폐기되며 그 부분은 무효. "검색은 완전 재현되고 생성만 LLM 비결정성으로 다르다"는 방법론적 발견은 유효하게 남음 |
| [subtitle_crossval_0822.md](subtitle_crossval_0822.md) | 유튜브 자막으로 견종축 교차검증 시도 — 표본(비순환 견종 30건·환경어 83건)이 판정선에 못 미쳐 결론 없이 종결. 견종축 자체의 결론(breed_conditionality_0822.md)에는 영향 없음, 이 교차검증 시도만 미완으로 종료 |
| [corpus_expansion_0825.md](corpus_expansion_0825.md) | Track B, 6→68문서 볼륨 확장 — gold Hit@1 0.667→0.583 하락 확인 후 **롤백**됨(코드·데이터 원복). "양보다 다양성" 교훈은 같은 날 오후 Track B2([corpus_expansion_diverse_0825.md](corpus_expansion_diverse_0825.md))로 대체 성공 |
| [owner_fixtures_coverage.md](owner_fixtures_coverage.md) | 최초 owner fixture 20건 커버리지(26청크·`score_gap≥0.024` 게이트 기준) — 코퍼스가 245청크로 확장되고 fixture가 48건으로 늘고 게이트 신호도 `margin_top5`로 바뀌며 설정 자체가 대체됨. 사람이 매긴 coverage 판정(missing/partial 다수)은 당시 기준 기록으로 남음 |
| [retrieval_gate_redesign_0825.md](retrieval_gate_redesign_0825.md) | 1차 게이트 재설계 시도(20건 기준) — "표본이 너무 작아 판단 불가"로 자체 결론. owner_fixtures 48건 확장 후 [retrieval_gate_redesign_retry_0825.md](retrieval_gate_redesign_retry_0825.md)가 재시도해 명확한 결론(margin_top5 우수)으로 대체 |
| [youtube_review_screening_0825.md](youtube_review_screening_0825.md) | 최초 스크리닝 — `YOUTUBE_API_KEY` 부재로 채널 확장이 막힌 상태의 기록. [youtube_review_expansion_0825.md](youtube_review_expansion_0825.md)가 키 문제를 해결하고 같은 채점 기준으로 재확장하며 운영상 대체됨(채점 방법론·최우선순위 4건 목록 자체는 그대로 승계되어 유효) |

---

## 전체 리포트 시간순 표

| 날짜 | 파일 | 요약 | 상태 |
|---|---|---|---|
| 2026-08-20 | [q003_top5_investigation_0820.md](q003_top5_investigation_0820.md) | 문서 조달 후 q003 정답 청크가 top-5 밖으로 밀려난 원인(근접 점수 새치기) 조사 | 유효(당시 83청크 기준 기술기록) |
| 2026-08-20 | [owner_fixtures_coverage.md](owner_fixtures_coverage.md) | owner fixture 20건 최초 커버리지(26청크, score_gap 게이트) | 폐기 — 48건·245청크·margin_top5로 대체 |
| 2026-08-20 | [output_guardrail_self_block_incident.md](output_guardrail_self_block_incident.md) | 안전 문구 자기 가드레일 차단 사건과 `SystemAuthoredText` 수정 | 유효 |
| 2026-08-20 | [medical_guardrail_v1v2_comparison.md](medical_guardrail_v1v2_comparison.md) | 의료 가드레일 v1→v2 비교, v2 confirmed | 유효 |
| 2026-08-20 | [demo_outputs_0820.md](demo_outputs_0820.md) | 발표용 데모 출력 5건(시나리오①③④, q003, 한계사례 Q15) | 폐기(부분) — 시나리오③은 그래프 폐기로 무효, 나머지는 구버전 스냅샷 |
| 2026-08-20 | [retrieval_gap_hybrid_vs_vector_0820.md](retrieval_gap_hybrid_vs_vector_0820.md) | Q12~Q15 하이브리드 vs 벡터 생성 비교 | 폐기 — 그래프 경로 폐기 |
| 2026-08-22 | [breed_conditionality_0822.md](breed_conditionality_0822.md) | 견종 조건성 v1+v2 실측, 처치분화 희박·형질-only 우세 | 유효 |
| 2026-08-22 | [env_axis_measurement_0822.md](env_axis_measurement_0822.md) | 환경축 원시 실측(순환매칭 미발견 당시) | 폐기 — decision_env_axis_discarded_0824로 대체 |
| 2026-08-22 | [subtitle_crossval_0822.md](subtitle_crossval_0822.md) | 유튜브 자막 견종 교차검증 시도, 표본 부족으로 미종결 | 폐기(미완 종료) |
| 2026-08-22 | [reproducibility_check_0822.md](reproducibility_check_0822.md) | 동결 그래프·시나리오①③④ 재현성 확인 | 폐기(부분) — 그래프 부분 무효, LLM 비결정성 발견은 유효 |
| 2026-08-24 | [research_graph_viability_0824/01_connectivity_audit_dev.md](research_graph_viability_0824/01_connectivity_audit_dev.md) | 그래프 연결성 전수 감사(밀도 0.13~0.25%, 고립 56%) | 폐기 — GraphRAG 완전 폐기로 대체 |
| 2026-08-24 | [research_graph_viability_0824/02_env_axis_projection_dev.md](research_graph_viability_0824/02_env_axis_projection_dev.md) | 환경축 absence/numeric 그래프 적재 성공 가능성 사영, 순환오염 83.1% 발견 | 유효 — 환경축 폐기 결정의 핵심 근거 |
| 2026-08-24 | [research_graph_viability_0824/03_graphrag_sparsity_literature_researcher.md](research_graph_viability_0824/03_graphrag_sparsity_literature_researcher.md) | GraphRAG 희소성 문헌 검토 | 폐기 — 그래프 접근 자체 폐기 |
| 2026-08-24 | [research_graph_viability_0824/04_alternative_axis_candidates_researcher.md](research_graph_viability_0824/04_alternative_axis_candidates_researcher.md) | 대안 축 후보 순위(심각도>절차>ABC>연령대>원칙) | 폐기 — 그래프 폐기로 전제 소멸 |
| 2026-08-24 | [research_graph_viability_0824/00_SYNTHESIS.md](research_graph_viability_0824/00_SYNTHESIS.md) | 그래프DB 존속 여부 종합판정("조건부") | 폐기 — 완전 폐기로 확정됨 |
| 2026-08-24 | [procedure_agegroup_axis_measurement_0824.md](procedure_agegroup_axis_measurement_0824.md) | 절차/연령대 축 1차 실측 | 폐기 — 그래프 목적 무효, 저자편중 발견은 승계 |
| 2026-08-24 | [procedure_axis_source_diagnosis_0824.md](procedure_axis_source_diagnosis_0824.md) | 절차축 소스 진단(저자 2명, 핀셋 조달 권고) | 폐기 — 그래프 목적 무효, 저자다양성 발견은 승계 |
| 2026-08-24 | [agegroup_axis_corpus_diagnosis_0824.md](agegroup_axis_corpus_diagnosis_0824.md) | 연령대축 코퍼스 충분성 재진단 | 폐기 — 그래프 목적 무효 |
| 2026-08-24 | [retrieval_perf_graph_vs_vector_0824.md](retrieval_perf_graph_vs_vector_0824.md) | 그래프 검색이 벡터 대비 랭킹 지표 이득 0건임을 32개 질의 전수 실측 | 유효 — GraphRAG 폐기 결정의 핵심 근거 |
| 2026-08-24 | [graphrag_final_attempt_stage1_sourcing_0824.md](graphrag_final_attempt_stage1_sourcing_0824.md) | GraphRAG "마지막 투자 시도" 1단계(조달+v3프롬프트 dry-run) | 폐기 — 2단계 착수 전 완전 폐기로 귀결 |
| 2026-08-25 | [youtube_review_screening_0825.md](youtube_review_screening_0825.md) | 유튜브 리뷰큐 우선순위 스크리닝(제목 기반), API 키 부재로 확장 불가 | 폐기(대체) — expansion으로 API키 이슈 해결·확장 |
| 2026-08-25 | [youtube_review_expansion_0825.md](youtube_review_expansion_0825.md) | 보듬TV 채널 전체 수집(900건), 리뷰큐 12→81건 확장 | 유효 |
| 2026-08-25 | [youtube_channel_diversity_check_0825.md](youtube_channel_diversity_check_0825.md) | 설채현 채널 분류품질 27배 우수, 수동자막 0%로 현재 정책상 배제 | 유효(현재 정책 하 결론) |
| 2026-08-25 | [whisper_retranscription_experiment_0825.md](whisper_retranscription_experiment_0825.md) | faster-whisper 재전사 실험, 자동자막 배제 정책 재검토용 1~3차 증거 | 진행중 |
| 2026-08-25 | [retrieval_gate_redesign_0825.md](retrieval_gate_redesign_0825.md) | 게이트 신호 재설계 1차 시도(20건), 표본부족으로 판단보류 | 폐기 — retry(48건)로 대체 |
| 2026-08-25 | [owner_fixtures_expansion_0825.md](owner_fixtures_expansion_0825.md) | owner_fixtures 20→48건 확장 | 유효 |
| 2026-08-25 | [retrieval_gate_redesign_retry_0825.md](retrieval_gate_redesign_retry_0825.md) | 게이트 신호 재설계 재시도(48건), margin_top5 우수 확정 | 유효(전환 권고, 기본값 전환은 승인 대기) |
| 2026-08-25 | [chunking_v4_experiment_0825.md](chunking_v4_experiment_0825.md) | 청킹 v4(대형청크) 실험, v3 유지 결론 | 유효 |
| 2026-08-25 | [corpus_expansion_0825.md](corpus_expansion_0825.md) | Track B, 6→68문서 볼륨 확장, gold 성능 하락으로 롤백 | 폐기(롤백, 교훈은 보존) |
| 2026-08-25 | [tier2_source_feasibility_0825.md](tier2_source_feasibility_0825.md) | 2층(공식·공공) 소스 타당성 조사, AVSAB 1순위 | 유효 |
| 2026-08-25 | [new_source_procurement_0825.md](new_source_procurement_0825.md) | 신규 저자 소스 헌팅, easiestip.com 7건 확보 | 유효 |
| 2026-08-25 | [avsab_pdf_pipeline_0825.md](avsab_pdf_pipeline_0825.md) | AVSAB PDF 인제스트 파이프라인 신규 구축 | 유효(추월됨 — 이후 diverse 확장에서 실제 통합) |
| 2026-08-25 | [corpus_expansion_diverse_0825.md](corpus_expansion_diverse_0825.md) | Track B2, 다양성 우선 확장(6→17문서, 83→245청크) | 유효 — 현재 코퍼스 상태 |
| 2026-08-25 | [wayopet_custom_parser_0825.md](wayopet_custom_parser_0825.md) | wayopet.com 커스텀 파서 구축, 6건 성공(저자 3명) | 진행중 — 실제 인제스트 대기 |
| 2026-08-25(자동생성) | [combined_corpus_coverage.md](combined_corpus_coverage.md) | 조달 후 통합 코퍼스(245청크·margin_top5 게이트) 커버리지 리포트 | 진행중 — 사람 coverage 재판정 다수 공란 |
| 2026-08-25 | [gold_import_and_eval_attempt_0825.md](gold_import_and_eval_attempt_0825.md) | gold 승인 40건 반영, resolved_at 분포, 기준선 평가 시도 | 진행중 — 평가는 gold 청크 미기록으로 중단 |
| 2026-08-26 | [retrieval_baseline_gold6_0826.md](retrieval_baseline_gold6_0826.md) | P1 이전 검색 기준선. **채점 6문항** Hit@1 0.667 / MRR@5 0.764 | 유효(범위 한정) — situation·refuse_boundary 표본 0 |
| 2026-08-26 | [corpus_gap_map_0826.md](corpus_gap_map_0826.md) | 결손 지도(축×유형), 원인 분류 (a)10·(a′)3·(b)3·(c)0, 수집 대상 16건 | 유효 — 수집 미착수 |
| 2026-08-26 | [expansion_candidates_0826.md](expansion_candidates_0826.md) | 우선순위 1·2·3 후보 조사(robots 확인), 중복 판정, 앵커·규약·지문 정리안 | 진행중 — 사람 판단 4건 대기 |

---

## 판단이 애매했던 항목 (보고용 메모)

- **`avsab_pdf_pipeline_0825.md`**: 문서 자체는 "MANIFEST 미등록, NOT_INGESTED"라고 명시하는데,
  같은 날 나중에 작성된 `corpus_expansion_diverse_0825.md`는 AVSAB PDF 3건(115청크)을 이미
  통합했다고 기록한다. 두 문서 사이에 정식 MANIFEST 등록 절차를 거쳤는지, 아니면 사실상
  우회 통합됐는지는 리포트만으로는 확정할 수 없다 — "유효(추월됨)"으로 표시했다.
- **`demo_outputs_0820.md` / `retrieval_gap_hybrid_vs_vector_0820.md` / `reproducibility_check_0822.md`**:
  세 문서 모두 그래프 의존 부분과 그래프 무관 부분이 한 문서 안에 섞여 있다. 전체를 "폐기"로
  표시하면 여전히 유효한 부분(벡터 검색 결과, LLM 비결정성 발견, 의료 가드레일 시연)을
  가리는 셈이라 "폐기(부분)"으로 표시하고 표에 무엇이 남는지 적었다.
- **`subtitle_crossval_0822.md`**: 견종축 자체 결론을 뒤집지도, 확정하지도 못한 채
  "규모가 판정선에 못 미쳤다"로 스스로 종결했다. 실패도 성공도 아닌 미완 상태라 "폐기"
  대신 "폐기(미완 종료)"로 구분했다.
- **`whisper_retranscription_experiment_0825.md`**: 정책 자체(자동자막 전면 배제)를 아직
  안 바꿨으니 "폐기된 정책"은 아니고, 그렇다고 "유효한 결론"도 아니다(정책 변경 승인 미도달).
  "진행중"으로 분류했다.
