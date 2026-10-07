import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSpeechSynthesis } from "./useSpeechSynthesis";
import type {
  BrowserSpeechSynthesis,
  SpeechSynthesisUtteranceLike,
} from "../services/speech";

class FakeSpeechSynthesisUtterance implements SpeechSynthesisUtteranceLike {
  lang = "";
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  constructor(public text = "") {}
}

class FakeSpeechSynthesis implements BrowserSpeechSynthesis {
  speaking = false;
  speak = vi.fn((utterance: SpeechSynthesisUtteranceLike) => {
    this.speaking = true;
    utterance.onstart?.();
  });
  cancel = vi.fn(() => {
    this.speaking = false;
  });
}

function installSpeechSynthesis() {
  const synthesis = new FakeSpeechSynthesis();
  vi.stubGlobal("speechSynthesis", synthesis);
  vi.stubGlobal("SpeechSynthesisUtterance", FakeSpeechSynthesisUtterance);
  return synthesis;
}

describe("useSpeechSynthesis", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it.each([
    ["en", "en-IN"],
    ["te", "te-IN"],
    ["ta", "ta-IN"],
    ["hi", "hi-IN"],
  ] as const)("speaks in the selected %s locale (%s)", (language, locale) => {
    const synthesis = installSpeechSynthesis();
    const { result } = renderHook(() => useSpeechSynthesis({ enabled: true, language }));

    act(() => {
      expect(result.current.speak("Assistant response", language)).toBe(true);
    });

    expect(synthesis.speak).toHaveBeenCalledOnce();
    const utterance = synthesis.speak.mock.calls[0][0] as FakeSpeechSynthesisUtterance;
    expect(utterance.text).toBe("Assistant response");
    expect(utterance.lang).toBe(locale);
    expect(result.current.isSpeaking).toBe(true);
  });

  it("cancels active speech when stopped", () => {
    const synthesis = installSpeechSynthesis();
    const { result } = renderHook(() => useSpeechSynthesis({ enabled: true, language: "en" }));

    act(() => result.current.speak("Hello", "en"));
    act(() => result.current.stop());

    expect(synthesis.cancel).toHaveBeenCalled();
    expect(result.current.isSpeaking).toBe(false);
    expect(result.current.status).toBe("Assistant is not speaking.");
  });

  it("does not speak an empty response", () => {
    const synthesis = installSpeechSynthesis();
    const { result } = renderHook(() => useSpeechSynthesis({ enabled: true, language: "en" }));

    act(() => {
      expect(result.current.speak("  ", "en")).toBe(false);
    });

    expect(synthesis.speak).not.toHaveBeenCalled();
  });

  it("cancels current speech when Blind Mode is disabled", () => {
    const synthesis = installSpeechSynthesis();
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useSpeechSynthesis({ enabled, language: "en" }),
      { initialProps: { enabled: true } },
    );

    act(() => result.current.speak("Hello", "en"));
    rerender({ enabled: false });

    expect(synthesis.cancel).toHaveBeenCalled();
    expect(result.current.isSpeaking).toBe(false);
  });

  it("cancels current speech when the preferred language changes", () => {
    const synthesis = installSpeechSynthesis();
    const { result, rerender } = renderHook(
      ({ language }: { language: "en" | "te" }) =>
        useSpeechSynthesis({ enabled: true, language }),
      { initialProps: { language: "en" as "en" | "te" } },
    );

    act(() => result.current.speak("Hello", "en"));
    rerender({ language: "te" });

    expect(synthesis.cancel).toHaveBeenCalled();
    expect(result.current.isSpeaking).toBe(false);
  });

  it("handles an unavailable browser implementation without throwing", () => {
    vi.stubGlobal("speechSynthesis", undefined);
    vi.stubGlobal("SpeechSynthesisUtterance", undefined);
    const { result } = renderHook(() => useSpeechSynthesis({ enabled: true, language: "en" }));

    expect(result.current.supported).toBe(false);
    act(() => {
      expect(result.current.speak("Text response", "en")).toBe(false);
    });

    expect(result.current.error).toMatch(/Voice output is unavailable/);
  });

  it("cancels an earlier response before speaking a rapid subsequent response", () => {
    const synthesis = installSpeechSynthesis();
    const { result } = renderHook(() => useSpeechSynthesis({ enabled: true, language: "en" }));

    act(() => result.current.speak("First response", "en"));
    act(() => result.current.speak("Second response", "en"));

    expect(synthesis.cancel).toHaveBeenCalled();
    expect(synthesis.speak).toHaveBeenCalledTimes(2);
  });
});
