# TODO — 안전 게이트 · 검색 품질 작업

작업 단위 체크리스트. 상태는 `[ ]` 대기 / `[~]` 진행 중 / `[x]` 완료 / `[-]` 보류.
완료할 때마다 `STATUS.md`의 "지금 상태"를, 근거·수치가 나오면 `HISTORY.md`를 갱신한다.

세션이 끊겨도 여기부터 다시 읽으면 이어갈 수 있게 쓴다.

---

## A. 화이트리스트 우선순위 확정 (선행) — **완료 2026-08-28**

결론: 경계 → 화이트리스트. 위해 구멍 6/6 → 0/6, 통과 대조군 4/4 유지, 동결 계약 위반 0.

- [x] A-1. `gate()`에서 경계 검사를 화이트리스트 위로 되돌린다
- [x] A-2. `test_whitelist_precedence_lets_harm_through`를 "막힌다" 계약으로 뒤집는다
- [x] A-3. 통과 대조군 4건 · 동결 25건 계약이 그대로인지 재측정
- [x] A-4. `gate()` docstring의 우선순위 설명을 결과에 맞춘다

## 1. 커밋 · PR

- [~] 1-1. `git add -f data/eval/queries/gate_pass_controls_v1.jsonl` (gitignore 예외)
- [ ] 1-2. dog-training-rag-retrieval 커밋
- [ ] 1-3. DAENGS_dev `fix/training-rag-safety-decision` 커밋 · push · PR
- [ ] 1-4. DAENGS backend venv의 `ml` 그룹 상태를 사용자에게 확인받는다

## 2. 게이트가 거짓말하는 것 닫기

죽은 임계값(`top_score < 0.70`)과 계산만 하고 안 쓰는 `margin_topk`.

- [ ] 2-1. 동결 25건에서 hit/miss별 `top_score`·`margin` 분포를 뽑는다
      (`data/scratch/retrieval_reranking_0827_v5/results.json` — DB 불필요)
- [ ] 2-2. 분리 가능한 신호가 있는지 판정한다. **없으면 없다고 기록하고 2-3을 건너뛴다**
- [ ] 2-3. 판정 규칙을 고치고 회귀 테스트를 추가한다
- [ ] 2-4. 동결 25건 decision 일치율이 88.0%에서 어떻게 변하는지 기록

## 3. cross-encoder 리랭커

- [ ] 3-1. Docker · pgvector 기동 (2번과 달리 후보 본문이 필요하다)
- [ ] 3-2. `compare_retrieval_reranking.py`에 cross-encoder 갈래를 추가
- [ ] 3-3. 동결 25건으로 Hit@1 / Hit@4 / MRR 재측정, dense 기준선(47.4%)과 비교
- [ ] 3-4. 기존 dense 정답 9건이 top-4 밖으로 밀리지 않는지 확인 (0827 실험의 탈락 기준)
- [ ] 3-5. 채택 시 `rag_api.py`의 `top_k: le=4` 상한을 풀고 검색 10 → 리랭크 → 프롬프트 4로 분리
- [ ] 3-6. 보고서 작성 (`reports/`)

## 보류 (이번 범위 아님, 잊지 않기 위해 적어 둠)

- [-] 인제스트 키 버그 — `ON CONFLICT(chunk_id)`가 `embedding_model`을 덮어써
      같은 청킹의 두 임베딩 런이 공존할 수 없다. **청킹·임베딩을 건드리기 직전에 반드시 먼저.**
      리랭커는 재적재가 없어 이 버그를 안 건드린다.
- [-] 운영 · 보안 — 훈련 RAG가 PM2 · compose · deploy 어디에도 없음 / 상하류 타임아웃
      45초 vs 180초 어긋남 / `0.0.0.0:8010` 무인증 LAN 노출. **시연 일정이 잡히면 최우선.**
- [-] 콘솔 `검색 점검` 화면의 훈련 갈래가 근거 본문·점수·인용 검증을 안 보여 줌
- [-] 질문 · 판정 되먹임 경로 없음 (평가셋이 실제 질문 위에서 자라지 못함)
