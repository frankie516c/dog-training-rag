import { Chat } from "@/components/chat";

export default function Home() {
  return (
    <main className="page-shell">
      <section className="chat-shell" aria-labelledby="service-title">
        <header className="service-header">
          <div className="brand-row">
            <p className="brand-mark" aria-hidden="true">
              D
            </p>
            <div>
              <h1 id="service-title">DAENGS</h1>
              <p>검증된 근거를 바탕으로 답하는 반려견 훈련 도우미</p>
            </div>
          </div>
        </header>
        <Chat />
      </section>
    </main>
  );
}
