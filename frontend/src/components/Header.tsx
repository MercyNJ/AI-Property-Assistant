interface Props {
  onNewChat: () => void;
  canReset: boolean;
}

export function Header({ onNewChat, canReset }: Props) {
  return (
    <header className="header">
      <div className="brand">
        <img src="/favicon.svg" alt="" className="brand-mark" />
        <div>
          <h1>BomaTech</h1>
          <p>Ask for a rental in plain language. Answers come only from the listings database.</p>
        </div>
      </div>
      <button type="button" className="btn-ghost" onClick={onNewChat} disabled={!canReset}>
        New chat
      </button>
    </header>
  );
}
