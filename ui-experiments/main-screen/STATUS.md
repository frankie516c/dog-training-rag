# STATUS — 메인 화면 캐릭터 디자인 실험

## 지금 상태

- 살아있는 실험은 **2개**: 실험 1(도트) · 실험 3(2D 리깅). 실험 2(포즈 스왑)는 폐기.
- 최신 초안: `drafts/v2-dot-and-rig.html` (v1은 폐기 전 3-실험 비교본, 참고용으로 남겨둠)
- 둘 다 정적 HTML/CSS/JS 목업이고, **실제 프론트엔드 코드/스택 결정은 아직 안 함**
- 실험 3의 강아지·방은 krea2 실제 연동 전이라 CSS/SVG로 만든 개념 목업 상태 (파츠별 관절 애니메이션만 보여줌)

## 확정된 것

- 기본틀 UI(댕스 앱 캡처 레퍼런스)의 레이아웃 구조: 상단 로고/아이콘, AI 채팅 입력바, 산책 요약 카드, 하단 내비 — 이건 실험과 무관하게 고정
- krea2 실체: `krea/Krea-2-*`, **13B 파라미터** 이미지 생성 모델, 호스팅 API가 기본 경로

## 열린 질문 / 아직 안 정한 것

1. **krea2 연동 방식** — 호스팅 API로 갈지 확정 필요 (로컬 셀프호스팅은 이 작업 PC 사양 VRAM 6GB로는 비추천, `HISTORY.md` 5절 참고)
2. **견종 프리셋 매칭 모델** — 아직 조사 전. krea2보다 훨씬 가벼울 것으로 예상, 로컬 GPU로 충분할 가능성 높음
3. **2D 리깅 구현 방법** — 지금 목업은 CSS transform-origin 회전으로 개념만 보여준 것. 실제로는 파츠 분리된 이미지 + 본(bone) 기반 애니메이션 라이브러리가 필요 (예: Spine, DragonBones, 또는 자체 CSS/JS 리깅)
4. **최종 방향** — 실험 1(도트)과 실험 3(2D 리깅) 중 하나로 좁힐지, 아니면 둘 다 다른 화면/모드로 쓸지 미정
5. **프론트엔드 스택** — 방향이 정해진 뒤에 결정하기로 함

## ⚠️ 참고: 이미 존재하는 프론트엔드 스캐폴드

이번 UI 실험을 만드는 동안, 레포의 다른 브랜치 `feature/chat-ui` (origin에 존재, main엔 아직 병합 안 됨)에 **이미 Next.js 프론트엔드가 있다는 걸 확인함**:

```
frontend/
  app/api/chat/route.ts
  app/layout.tsx
  app/page.tsx
  components/chat.tsx
  lib/chat-client.ts
  lib/chat-contract.ts
  package.json / next.config.ts / tsconfig.json
```

`backend/`에는 grounded RAG 챗 서비스(`chat_service.py`, `retrieval.py`, `generation.py` 등)도 이미 있음. **이 UI 실험은 아직 `feature/chat-ui`를 참고하거나 통합하지 않았음** — 방향이 정해지고 실제 코드 단계로 넘어갈 때, 이 Next.js 스캐폴드 위에 올릴지 새로 시작할지부터 먼저 확인 필요.

## 다음 단계 (제안)

1. 실험 1 vs 3 방향 확정 (또는 둘 다 유지 여부)
2. `feature/chat-ui`의 기존 Next.js 구조 검토 — 이 위에 메인 화면을 붙일지 판단
3. krea2 API 키 발급 및 SDK 연동 착수
4. 견종 프리셋 매칭 + 2D 리깅 구현 방법 조사
