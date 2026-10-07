import { describe, expect, it } from "vitest";
import {
  appendCaptionHistory,
  createCaptionEntry,
  MAX_CAPTION_HISTORY,
} from "./captions";

describe("caption history", () => {
  it("redacts credential values from microphone captions", () => {
    const caption = createCaptionEntry({
      source: "microphone",
      text: "Your one-time password is 123456",
    });

    expect(caption.text).toBe("Your [REDACTED]");
  });

  it("keeps the newest captions within the bounded history limit", () => {
    const history = Array.from({ length: MAX_CAPTION_HISTORY + 1 }, (_, index) =>
      createCaptionEntry({ source: "microphone", text: `Caption ${index}` }),
    );
    let boundedHistory: ReturnType<typeof createCaptionEntry>[] = [];
    for (const caption of history) {
      boundedHistory = appendCaptionHistory(boundedHistory, caption);
    }

    expect(boundedHistory).toHaveLength(MAX_CAPTION_HISTORY);
    expect(boundedHistory[0].text).toBe("Caption 1");
    expect(boundedHistory[boundedHistory.length - 1].text).toBe("Caption 100");
  });
});
