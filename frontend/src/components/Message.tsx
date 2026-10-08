import type { ChatMessage } from "../types";
import { describeToolCall } from "../format";
import { PropertyCard } from "./PropertyCard";

interface Props {
  message: ChatMessage;
  onRetry: (text: string) => void;
  busy: boolean;
}

export function Message({ message: m, onRetry, busy }: Props) {
  if (m.role === "user") {
    return (
      <div className="row row-user">
        <div className="bubble bubble-user">{m.text}</div>
      </div>
    );
  }

  if (m.role === "error") {
    return (
      <div className="row" role="alert">
        <div className="bubble bubble-error">
          <p>{m.text}</p>
          <button type="button" className="btn-link" onClick={() => onRetry(m.retryText)} disabled={busy}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="row">
      <div className="assistant">
        {m.historyReset && (
          <p className="notice">
            This reply couldn't see your earlier messages because the chat expired or the server restarted.
          </p>
        )}
        {m.toolCalls.length > 0 && (
          <ul className="tools">
            {m.toolCalls.map((t, i) => (
              <li key={i}>{describeToolCall(t)}</li>
            ))}
          </ul>
        )}
        <div className="bubble bubble-assistant">{m.text}</div>
        {m.properties.length > 0 && (
          <div className="cards">
            {m.properties.map((p) => (
              <PropertyCard key={p.id} p={p} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function Typing() {
  return (
    <div className="row" aria-live="polite">
      <div className="bubble bubble-assistant typing">
        <span />
        <span />
        <span />
        <em>Searching listings…</em>
      </div>
    </div>
  );
}
