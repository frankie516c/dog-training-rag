"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { ChatApiError, chatMode, sendChat, type MockScenario } from "@/lib/chat-client";
import type { ChatCitation, ChatResponse, Locator } from "@/lib/chat-contract";

const MAX_MESSAGE_LENGTH = 1_000;

type ConversationItem =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; response: ChatResponse }
  | { id: string; role: "assistant"; error: { code: string; message: string; status: number } };

function formatLocator(locator: Locator) {
  const kindLabels: Record<Locator["kind"], string> = {
    html: "웹 문서",
    pdf: "PDF",
    pmc_article: "PMC 문서",
    dataset_definition: "데이터셋 정의",
  };
  const details = [
    locator.section && `섹션: ${locator.section}`,
    locator.fragment && `위치: ${locator.fragment}`,
    locator.page && `${locator.page}쪽`,
    locator.pmcid && `PMCID: ${locator.pmcid}`,
    locator.doi && `DOI: ${locator.doi}`,
    locator.dataset_id && `데이터셋: ${locator.dataset_id}`,
    locator.item_id && `항목: ${locator.item_id}`,
  ].filter(Boolean);

  return [kindLabels[locator.kind], ...details].join(" · ");
}

function CitationCard({ citation }: { citation: ChatCitation }) {
  return (
    <li className="citation-card">
      <div className="citation-heading">
        <p>{citation.source_name}</p>
        <span>{citation.evidence_level === "DIRECT" ? "직접 근거" : "보조 근거"}</span>
      </div>
      <p className="locator">{formatLocator(citation.locator)}</p>
      <a href={citation.canonical_url} target="_blank" rel="noreferrer">
        원문 출처 열기 <span aria-hidden="true">↗</span>
      </a>
    </li>
  );
}

function AssistantResponse({ response }: { response: ChatResponse }) {
  const insufficient = response.status === "insufficient_evidence";

  return (
    <div className="response-content">
      <p className={`status-label ${insufficient ? "status-insufficient" : "status-answered"}`}>
        {insufficient ? "근거 부족" : "근거 확인 답변"}
      </p>
      <p className="answer-text">{response.answer}</p>

      {response.safety_notice && (
        <aside
          className={`safety-notice safety-${response.safety_notice.level}`}
          aria-label={response.safety_notice.level === "urgent" ? "긴급 안전 안내" : "주의 안내"}
        >
          <strong>{response.safety_notice.level === "urgent" ? "긴급" : "주의"}</strong>
          <p>{response.safety_notice.message}</p>
        </aside>
      )}

      {response.limitations.length > 0 && (
        <section className="limitations" aria-labelledby={`limitations-${response.request_id}`}>
          <h3 id={`limitations-${response.request_id}`}>답변의 한계</h3>
          <ul>
            {response.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </section>
      )}

      {response.citations.length > 0 && (
        <section className="citations" aria-labelledby={`citations-${response.request_id}`}>
          <h3 id={`citations-${response.request_id}`}>확인한 근거</h3>
          <ul>
            {response.citations.map((citation) => (
              <CitationCard key={`${citation.card_id}-${citation.source_id}`} citation={citation} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function Chat() {
  const [message, setMessage] = useState("");
  const [items, setItems] = useState<ConversationItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [validationMessage, setValidationMessage] = useState("");
  const [mockScenario, setMockScenario] = useState<MockScenario>("answered");
  const endRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [items, isLoading]);

  async function handleSubmit(event?: FormEvent) {
    event?.preventDefault();
    if (isLoading) return;

    const trimmedMessage = message.trim();
    if (!trimmedMessage) {
      setValidationMessage("질문을 입력해 주세요.");
      textareaRef.current?.focus();
      return;
    }
    if (trimmedMessage.length > MAX_MESSAGE_LENGTH) {
      setValidationMessage("질문은 1,000자 이하로 입력해 주세요.");
      textareaRef.current?.focus();
      return;
    }

    setValidationMessage("");
    setIsLoading(true);
    setItems((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", text: trimmedMessage },
    ]);
    setMessage("");

    try {
      const response = await sendChat(
        { message: trimmedMessage, response_language: "ko" },
        mockScenario,
      );
      setItems((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "assistant", response },
      ]);
    } catch (error) {
      const apiError =
        error instanceof ChatApiError
          ? error
          : new ChatApiError("예상하지 못한 오류가 발생했습니다.", "unknown_error", 0);
      setItems((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          error: { code: apiError.code, message: apiError.message, status: apiError.status },
        },
      ]);
    } finally {
      setIsLoading(false);
      textareaRef.current?.focus();
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void handleSubmit();
    }
  }

  return (
    <div className="chat-area">
      {chatMode === "mock" && (
        <div className="mock-controls">
          <label htmlFor="mock-scenario">Mock 응답</label>
          <select
            id="mock-scenario"
            value={mockScenario}
            onChange={(event) => setMockScenario(event.target.value as MockScenario)}
            disabled={isLoading}
          >
            <option value="answered">답변 완료</option>
            <option value="insufficient">근거 부족</option>
            <option value="caution">주의 안내</option>
            <option value="urgent">긴급 안내</option>
            <option value="unavailable">503 준비 중</option>
          </select>
          <span>UI 확인용 합성 fixture</span>
        </div>
      )}

      <div className="conversation" aria-live="polite" aria-busy={isLoading}>
        {items.length === 0 && (
          <div className="empty-state">
            <p className="empty-kicker">훈련 질문을 남겨 주세요</p>
            <p>DAENGS는 확인 가능한 근거와 답변의 한계를 함께 보여드립니다.</p>
          </div>
        )}

        <ol className="message-list">
          {items.map((item) => (
            <li key={item.id} className={`message-row message-${item.role}`}>
              <p className="speaker">{item.role === "user" ? "나" : "DAENGS"}</p>
              <article className="message-bubble">
                {"text" in item && <p className="user-text">{item.text}</p>}
                {"response" in item && <AssistantResponse response={item.response} />}
                {"error" in item && (
                  <div className="error-response" role="alert">
                    <p className="status-label status-error">
                      {item.error.status === 503 ? "서비스 준비 중" : "요청 오류"}
                    </p>
                    <p>{item.error.message}</p>
                    <small>오류 코드: {item.error.code}</small>
                  </div>
                )}
              </article>
            </li>
          ))}
          {isLoading && (
            <li className="message-row message-assistant loading-row">
              <p className="speaker">DAENGS</p>
              <div className="message-bubble loading-message" role="status">
                <span className="loading-dot" aria-hidden="true" />
                근거를 확인하고 있습니다…
              </div>
            </li>
          )}
        </ol>
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={handleSubmit} noValidate>
        <label htmlFor="chat-message">강아지 훈련 질문</label>
        <div className="input-wrap">
          <textarea
            ref={textareaRef}
            id="chat-message"
            value={message}
            onChange={(event) => {
              setMessage(event.target.value);
              if (validationMessage) setValidationMessage("");
            }}
            onKeyDown={handleKeyDown}
            maxLength={MAX_MESSAGE_LENGTH}
            rows={3}
            placeholder="예: 산책 중 집중 연습은 어떻게 시작하나요?"
            aria-describedby="message-help message-error"
            aria-invalid={Boolean(validationMessage)}
            disabled={isLoading}
          />
          <div className="input-meta">
            <span id="message-help">Enter로 전송 · Shift+Enter로 줄바꿈</span>
            <span>{message.length.toLocaleString("ko-KR")} / 1,000</span>
          </div>
        </div>
        <p id="message-error" className="validation-message" role="alert">
          {validationMessage}
        </p>
        <button type="submit" disabled={isLoading || !message.trim()}>
          {isLoading ? "답변 준비 중" : "질문 보내기"}
        </button>
      </form>
      <p className="session-note">대화는 현재 탭에만 유지되며 저장되지 않습니다.</p>
    </div>
  );
}
