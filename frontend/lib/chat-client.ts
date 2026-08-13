import type {
  ChatErrorResponse,
  ChatRequest,
  ChatResponse,
} from "./chat-contract";

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

export async function sendChat(request: ChatRequest): Promise<ChatResponse> {
  return requestApi(request);
}
