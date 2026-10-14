import { useEffect, useRef, useState } from "react";
import { Composer } from "./components/Composer";
import { Header } from "./components/Header";
import { Message, Typing } from "./components/Message";
import { Welcome } from "./components/Welcome";
import { ApiError, resetConversation, sendMessage } from "./services/api";
import type { ChatMessage } from "./types";

// Page-local keys; crypto.randomUUID is unavailable on non-HTTPS origins.
let nextId = 0;
const uid = () => `m${++nextId}`;

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    // oxlint-disable-next-line react/exhaustive-effect-dependencies -- scroll whenever the conversation changes
  }, [messages, loading]);

  async function send(text: string) {
    if (loading) return;
    // A retry replaces the error bubble instead of stacking a new user message.
    setMessages((prev) => {
      const last = prev.at(-1);
      if (last?.role === "error" && last.retryText === text) return prev.slice(0, -1);
      return [...prev, { id: uid(), role: "user", text }];
    });
    setLoading(true);
    try {
      const res = await sendMessage(text, conversationId);
      setConversationId(res.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: "assistant",
          text: res.reply,
          properties: res.properties,
          toolCalls: res.tool_calls,
          historyReset: res.history_reset,
        },
      ]);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      setMessages((prev) => [...prev, { id: uid(), role: "error", text: msg, retryText: text }]);
    } finally {
      setLoading(false);
    }
  }

  function newChat() {
    if (conversationId) resetConversation(conversationId).catch(() => undefined);
    setConversationId(null);
    setMessages([]);
  }

  return (
    <div className="app">
      <Header onNewChat={newChat} canReset={messages.length > 0 && !loading} />
      {/* role="log" is a polite live region, so screen readers announce each reply or error as it is added. */}
      <main className="chat" role="log" aria-label="Conversation">
        {messages.length === 0 ? (
          <Welcome onPick={send} />
        ) : (
          messages.map((m) => <Message key={m.id} message={m} onRetry={send} busy={loading} />)
        )}
        {loading && <Typing />}
        <div ref={endRef} />
      </main>
      <footer className="footer">
        <Composer onSend={send} disabled={loading} />
        <p className="disclaimer">Demo listings. Prices are monthly rent in KES.</p>
      </footer>
    </div>
  );
}
