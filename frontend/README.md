# DAENGS Chat UI

검증된 근거를 바탕으로 답하는 반려견 훈련 도우미의 최소 채팅 UI입니다. 브라우저는 Next.js Route Handler를 통해 실제 채팅 백엔드에 요청합니다.

## 설치

Node.js와 npm이 설치된 환경에서 실행합니다.

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
```

## 실행

백엔드가 `127.0.0.1:8000`에서 실행 중인 상태에서 `.env.local`에 서버 전용 백엔드 주소를 설정합니다.

```dotenv
CHAT_API_URL=http://127.0.0.1:8000
```

```powershell
npm run dev
```

브라우저에서 `http://localhost:3000`을 엽니다. 브라우저는 같은 origin의 `POST /api/chat`만 호출하고, Next.js 서버가 `POST {CHAT_API_URL}/chat`으로 전달합니다. 요청 본문은 `{ "message": string, "response_language": "ko" }`이며 API v0 계약을 따릅니다.

## 환경변수

| 이름 | 값 | 설명 |
| --- | --- | --- |
| `CHAT_API_URL` | URL | Next.js 서버가 `/chat` 요청을 보낼 백엔드의 기준 URL입니다. 기본 예시는 `http://127.0.0.1:8000`입니다. |

`CHAT_API_URL`은 서버 전용이며 브라우저 번들에 포함되지 않습니다. 실제 `.env.local`은 commit하지 마세요. 환경변수를 변경한 뒤에는 개발 서버를 다시 시작해야 합니다.

## npm 명령

```powershell
npm run dev    # 개발 서버
npm run lint   # ESLint 검사
npm run build  # 프로덕션 빌드
npm run start  # 빌드된 앱 실행
```

## 현재 제외 범위

- 로그인, 사용자/반려견 프로필, 데이터베이스 및 대화 영구 저장
- 스트리밍, 음성 입출력, 관리자 페이지
- 다크 모드, 디자인 시스템, 외부 상태관리 라이브러리
- 범용 응답 parser 및 런타임 스키마 검증

대화 메시지는 React 컴포넌트 상태에만 보관되므로 새로고침하거나 탭을 닫으면 사라집니다.
