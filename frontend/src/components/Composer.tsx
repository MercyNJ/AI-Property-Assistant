import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

const MAX = 1000;

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
}

export function Composer({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const trimmed = text.trim();
  const ref = useRef<HTMLTextAreaElement>(null);

  // Auto-grow in all browsers (field-sizing is Chromium-only); CSS max-height caps it.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
    // oxlint-disable-next-line react/exhaustive-effect-dependencies -- re-measure whenever the text changes
  }, [text]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        ref={ref}
        value={text}
        onChange={(e) => setText(e.target.value.slice(0, MAX))}
        onKeyDown={onKeyDown}
        placeholder="e.g. 2-bedroom in Kasarani under 35k, furnished"
        rows={1}
        aria-label="Message"
        // oxlint-disable-next-line jsx-a11y/no-autofocus -- the message box is the page's primary input
        autoFocus
      />
      <button type="submit" className="btn-send" disabled={disabled || !trimmed}>
        Send
      </button>
    </form>
  );
}
