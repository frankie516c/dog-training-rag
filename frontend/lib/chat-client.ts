import type {
  ChatErrorResponse,
  ChatRequest,
  ChatResponse,
  SafetyLevel,
} from "./chat-contract";

export type ChatMode = "mock" | "api";
export type MockScenario = "answered" | "insufficient" | SafetyLevel | "unavailable";

export const chatMode: ChatMode =
  process.env.NEXT_PUBLIC_CHAT_MODE === "api" ? "api" : "mock";

export class ChatApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ChatApiError";
  }
}

const syntheticCitation = {
  card_id: "11111111-1111-4111-8111-111111111111",
  source_id: "synthetic-source",
  source_name: "합성 UI 테스트 출처",
  canonical_url: "https://example.test/guidance",
  locator: {
    kind: "html" as const,
    url: "https://example.test/guidance#synthetic-section",
    section: "합성 테스트 섹션",
    fragment: null,
    page: null,
    pmcid: null,
    doi: null,
    dataset_id: null,
    item_id: null,
  },
  evidence_level: "DIRECT" as const,
};

function createMockResponse(scenario: Exclude<MockScenario, "unavailable">): ChatResponse {
  if (scenario === "insufficient") {
    return {
      request_id: "33333333-3333-4333-8333-333333333333",
      status: "insufficient_evidence",
      answer: "현재 검증된 근거만으로는 답변하기 어렵습니다.",
      answer_language: "ko",
      citations: [],
      limitations: ["검토가 완료된 합성 근거가 없습니다."],
      safety_notice: null,
    };
  }

  return {
    request_id: "22222222-2222-4222-8222-222222222222",
    status: "answered",
    answer: "합성된 UI 확인용 답변입니다. 실제 훈련 조언이나 승인된 claim이 아닙니다.",
    answer_language: "ko",
    citations: [syntheticCitation],
    limitations: ["합성 fixture이므로 실제 훈련 판단에 사용할 수 없습니다."],
    safety_notice:
      scenario === "caution" || scenario === "urgent"
        ? {
            level: scenario,
            message:
              scenario === "urgent"
                ? "긴급 안전 안내의 표시를 확인하기 위한 합성 메시지입니다."
                : "주의 안전 안내의 표시를 확인하기 위한 합성 메시지입니다.",
          }
        : null,
  };
}

async function readJson<T>(response: Response): Promise<T | null> {
  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

async function requestApi(request: ChatRequest): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (response.status === 503) {
    const error = await readJson<ChatErrorResponse>(response);
    throw new ChatApiError(
      error?.message ?? "검증된 근거를 검색하는 기능을 준비 중입니다.",
      error?.code ?? "chat_not_ready",
      response.status,
    );
  }

  if (!response.ok) {
    const error = await readJson<{ code?: string; message?: string }>(response);
    throw new ChatApiError(
      error?.message ?? "답변을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
      error?.code ?? "chat_request_failed",
      response.status,
    );
  }

  const result = await readJson<ChatResponse>(response);
  if (!result) {
    throw new ChatApiError("API 응답을 읽을 수 없습니다.", "invalid_chat_response", 502);
  }
  return result;
}

export async function sendChat(
  request: ChatRequest,
  mockScenario: MockScenario,
): Promise<ChatResponse> {
  if (chatMode === "api") {
    return requestApi(request);
  }

  await new Promise((resolve) => window.setTimeout(resolve, 500));
  if (mockScenario === "unavailable") {
    throw new ChatApiError(
      "검증된 근거를 검색하는 기능을 준비 중입니다.",
      "chat_not_ready",
      503,
    );
  }
  return createMockResponse(mockScenario);
}
