# DAENGS Chat UI

검증된 근거를 바탕으로 답하는 반려견 훈련 도우미의 최소 채팅 UI입니다. 기본값은 실제 출처나 승인되지 않은 claim을 포함하지 않는 합성 mock fixture입니다.

## 설치

Node.js와 npm이 설치된 환경에서 실행합니다.

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
```

## Mock 모드 실행

`.env.local`을 다음과 같이 설정합니다.

```dotenv
NEXT_PUBLIC_CHAT_MODE=mock
NEXT_PUBLIC_CHAT_API_URL=http://localhost:8000
```

```powershell
npm run dev
```

브라우저에서 `http://localhost:3000`을 열고 상단의 **Mock 응답** 선택 상자에서 답변 완료, 근거 부족, 주의, 긴급, 503 상태를 선택할 수 있습니다.

## 실제 API 모드 실행

백엔드가 실행 중인 상태에서 `.env.local`의 모드를 변경하고 프론트엔드 개발 서버를 다시 시작합니다.

```dotenv
NEXT_PUBLIC_CHAT_MODE=api
NEXT_PUBLIC_CHAT_API_URL=http://localhost:8000
```

브라우저 요청은 프론트엔드의 내부 프록시를 거쳐 설정된 서버의 `POST /chat`으로 전달됩니다. 요청 본문은 `{ "message": string, "response_language": "ko" }`이며 API v0 계약을 따릅니다.

## 환경변수

| 이름 | 값 | 설명 |
| --- | --- | --- |
| `NEXT_PUBLIC_CHAT_MODE` | `mock` 또는 `api` | 합성 fixture와 실제 API 중 선택합니다. 미설정 또는 잘못된 값은 안전하게 `mock`으로 동작합니다. |
| `NEXT_PUBLIC_CHAT_API_URL` | URL | API 모드에서 `/chat` 요청을 보낼 백엔드의 기준 URL입니다. |

공개 접두사가 붙은 환경변수이므로 비밀값을 넣지 마세요. 환경변수를 변경한 뒤에는 개발 서버를 다시 시작해야 합니다.

## npm 명령

```powershell
npm run dev    # 개발 서버
npm run lint   # ESLint 검사
npm run build  # 프로덕션 빌드
npm run start  # 빌드된 앱 실행
```

## 현재 제외 범위

- 실제 임베딩, 검색, reranking, LLM 및 EvidenceCard 데이터
- 로그인, 사용자/반려견 프로필, 데이터베이스 및 대화 영구 저장
- 스트리밍, 음성 입출력, 관리자 페이지
- 다크 모드, 디자인 시스템, 외부 상태관리 라이브러리
- 실제 출처 데이터 하드코딩 및 범용 응답 parser

대화 메시지는 React 컴포넌트 상태에만 보관되므로 새로고침하거나 탭을 닫으면 사라집니다.
