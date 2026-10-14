import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, resetConversation, sendMessage } from "./api";

const fetchMock = vi.fn<typeof fetch>();
vi.stubGlobal("fetch", fetchMock);

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  fetchMock.mockReset();
  vi.useRealTimers();
});

describe("sendMessage", () => {
  it("posts the message and conversation ID as JSON and returns the reply", async () => {
    const reply = { conversation_id: "c1", reply: "Hi", properties: [], tool_calls: [], history_reset: false };
    fetchMock.mockResolvedValue(json(reply));

    await expect(sendMessage("3 bed in Ruiru", "c1")).resolves.toEqual(reply);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/chat$/);
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(String(init?.body))).toEqual({ message: "3 bed in Ruiru", conversation_id: "c1" });
  });

  it("shows the backend's detail message on an error status", async () => {
    fetchMock.mockResolvedValue(json({ detail: "You're sending messages too quickly." }, 429));
    await expect(sendMessage("hi", null)).rejects.toThrow(new ApiError("You're sending messages too quickly."));
  });

  it("falls back to the status code when the error body isn't JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502 }));
    await expect(sendMessage("hi", null)).rejects.toThrow("The server returned an error (502).");
  });

  it("ignores a non-string detail, such as a validation error list", async () => {
    fetchMock.mockResolvedValue(json({ detail: [{ msg: "field required" }] }, 422));
    await expect(sendMessage("hi", null)).rejects.toThrow("The server returned an error (422).");
  });

  it("reports an unreachable server", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(sendMessage("hi", null)).rejects.toThrow(/Can't reach the server/);
  });

  it("aborts and reports a timeout after 60 seconds", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        }),
    );

    const pending = sendMessage("hi", null);
    const assertion = expect(pending).rejects.toThrow("The request timed out. Please try again.");
    await vi.advanceTimersByTimeAsync(59_999);
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
  });
});

describe("resetConversation", () => {
  it("sends DELETE with the encoded ID and resolves on 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(resetConversation("abc_123")).resolves.toBeUndefined();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/chat\/abc_123$/);
    expect(init?.method).toBe("DELETE");
  });
});
