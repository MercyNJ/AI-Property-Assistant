import type { ChatResponse } from "../types";

// Empty in development (Vite proxies /api); set VITE_API_URL to the backend origin in production.
const API_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
const TIMEOUT_MS = 60_000;

export class ApiError extends Error {}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("The request timed out. Please try again.");
    }
    throw new ApiError("Can't reach the server. Check your connection and that the backend is running.");
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let detail = `The server returned an error (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export function sendMessage(message: string, conversationId: string | null): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
}

export function resetConversation(conversationId: string): Promise<void> {
  return request<void>(`/api/chat/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
}
