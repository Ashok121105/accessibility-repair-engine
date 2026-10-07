import { afterEach, describe, expect, it, vi } from "vitest";

import { scanWebsite } from "./api";

describe("scanWebsite error messages", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    [422, { detail: [{ msg: "raw validation internals" }] }, "Invalid website URL. Please check the URL."],
    [502, { detail: "Website could not be found. Please check the domain." }, "Website could not be found. Please check the domain."],
    [502, { detail: "Website could not be reached." }, "Website could not be reached."],
    [504, { detail: "Website took too long to respond." }, "Website took too long to respond."],
    [404, { detail: "The requested page was not found." }, "The requested page was not found."],
    [502, { detail: "The website returned a server error." }, "The website returned a server error."],
    [500, { detail: "The website was reachable, but accessibility scanning could not be completed." }, "The website was reachable, but accessibility scanning could not be completed."],
  ])("shows the safe message for HTTP %s", async (status, body, expected) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(scanWebsite("https://example.com/")).rejects.toThrow(expected);
  });

  it("does not expose a raw browser fetch error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(scanWebsite("https://example.com/")).rejects.toThrow(
      "Could not connect to the scan service. Please try again.",
    );
  });

  it("does not display raw backend exception details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "raw Playwright stack trace and host details" }), {
          status: 502,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(scanWebsite("https://example.com/")).rejects.toThrow(
      "Website could not be reached.",
    );
  });
});
