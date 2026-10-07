import { afterEach, describe, expect, it, vi } from "vitest";

import { sendAgentCommand, startAgent, stopAgent } from "./api";

describe("assistant API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the documented URL, session ID, and command payloads", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        session_id: "session-1",
        status: "started",
        message: "Session started.",
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        action: "open_website",
        website: "Flipkart",
        url: "https://www.flipkart.com/",
        message: "Flipkart is open.",
        page_url: "https://www.flipkart.com/",
        details: {},
        session_active: true,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "stopped" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await startAgent("https://www.flipkart.com/");
    await sendAgentCommand("session-1", "Open Flipkart");
    await stopAgent("session-1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/agent/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: "https://www.flipkart.com/" }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/agent/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: "session-1", command: "Open Flipkart" }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/agent/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: "session-1" }),
    });
  });

  it("returns a clear message when the backend cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(startAgent("https://www.flipkart.com/")).rejects.toThrow(
      "Could not reach the assistant backend. Check that the backend is running and try again.",
    );
  });
});
