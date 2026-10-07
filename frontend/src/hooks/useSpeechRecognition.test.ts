import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getRecognitionLocale } from "../components/assistant/language";
import { useSpeechRecognition } from "./useSpeechRecognition";
import type {
  BrowserSpeechRecognition,
  SpeechRecognitionResultEventLike,
  SpeechRecognitionResultLike,
} from "../services/speech";

class FakeSpeechRecognition implements BrowserSpeechRecognition {
  static instances: FakeSpeechRecognition[] = [];
  lang = "";
  interimResults = false;
  continuous = true;
  onstart: (() => void) | null = null;
  onresult: ((event: SpeechRecognitionResultEventLike) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn(() => this.onstart?.());
  stop = vi.fn();
  abort = vi.fn();

  constructor() {
    FakeSpeechRecognition.instances.push(this);
  }

  emitResult(transcript: string, isFinal = true, resultIndex = 0) {
    const results = Array.from({ length: resultIndex + 1 }, (_, index) =>
      Object.assign(
        [{ transcript: index === resultIndex ? transcript : "" }],
        { isFinal: index !== resultIndex || isFinal, length: 1 },
      ) as SpeechRecognitionResultLike);
    this.onresult?.({ resultIndex, results });
  }
}

function installSpeechRecognition() {
  FakeSpeechRecognition.instances = [];
  vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
}

describe("useSpeechRecognition", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("detects when native speech recognition is available", () => {
    installSpeechRecognition();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript: vi.fn(),
    }));

    expect(result.current.supported).toBe(true);
  });

  it("detects the WebKit-prefixed browser implementation", () => {
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", FakeSpeechRecognition);
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript: vi.fn(),
    }));

    expect(result.current.supported).toBe(true);
    act(() => result.current.start());
    expect(FakeSpeechRecognition.instances[0].start).toHaveBeenCalledOnce();
  });

  it("starts recognition, reports listening state, captures final transcript, then handles end", () => {
    installSpeechRecognition();
    const onFinalTranscript = vi.fn();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript,
    }));

    act(() => result.current.start());
    expect(FakeSpeechRecognition.instances[0].start).toHaveBeenCalledOnce();
    expect(result.current.isListening).toBe(true);
    act(() => FakeSpeechRecognition.instances[0].emitResult("Open Flipkart"));
    expect(result.current.transcript).toBe("Open Flipkart");
    expect(onFinalTranscript).not.toHaveBeenCalled();

    act(() => FakeSpeechRecognition.instances[0].onend?.());

    expect(result.current.isListening).toBe(false);
    expect(onFinalTranscript).toHaveBeenCalledWith("Open Flipkart");
  });

  it("handles recognition errors with a human-readable message", () => {
    installSpeechRecognition();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript: vi.fn(),
    }));

    act(() => result.current.start());
    act(() => FakeSpeechRecognition.instances[0].onerror?.({ error: "not-allowed" }));

    expect(result.current.isListening).toBe(false);
    expect(result.current.error).toMatch(/Microphone permission was denied/);
  });

  it("reports no speech when recognition ends without a final transcript", () => {
    installSpeechRecognition();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript: vi.fn(),
    }));

    act(() => result.current.start());
    act(() => FakeSpeechRecognition.instances[0].onend?.());

    expect(result.current.error).toMatch(/No speech was detected/);
  });

  it("stops listening on request", () => {
    installSpeechRecognition();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript: vi.fn(),
    }));

    act(() => result.current.start());
    act(() => result.current.stop());

    expect(FakeSpeechRecognition.instances[0].abort).toHaveBeenCalledOnce();
    expect(result.current.isListening).toBe(false);
  });

  it("discards final and late recognition events after Stop", () => {
    installSpeechRecognition();
    const onFinalTranscript = vi.fn();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript,
    }));

    act(() => result.current.start());
    const recognition = FakeSpeechRecognition.instances[0];
    const lateResult = recognition.onresult;
    const lateEnd = recognition.onend;
    act(() => result.current.stop());
    act(() => {
      lateResult?.({
        resultIndex: 0,
        results: [Object.assign([{ transcript: "Open Flipkart" }], { isFinal: true, length: 1 })],
      });
      lateEnd?.();
    });

    expect(onFinalTranscript).not.toHaveBeenCalled();
    expect(result.current.transcript).toBe("");
    expect(result.current.isListening).toBe(false);
  });

  it("allows an immediate restart and ignores events from the stopped recognizer", () => {
    installSpeechRecognition();
    const onFinalTranscript = vi.fn();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript,
    }));

    act(() => result.current.start());
    const oldRecognition = FakeSpeechRecognition.instances[0];
    const lateResult = oldRecognition.onresult;
    act(() => {
      result.current.stop();
      result.current.start();
    });

    expect(FakeSpeechRecognition.instances).toHaveLength(2);
    act(() => {
      lateResult?.({
        resultIndex: 0,
        results: [Object.assign([{ transcript: "Old command" }], { isFinal: true, length: 1 })],
      });
      FakeSpeechRecognition.instances[1].emitResult("New command");
      FakeSpeechRecognition.instances[1].onend?.();
    });

    expect(onFinalTranscript).toHaveBeenCalledOnce();
    expect(onFinalTranscript).toHaveBeenCalledWith("New command");
  });

  it("streams continuous final captions, reconnects after natural end, and stops without restarting", () => {
    vi.useFakeTimers();
    installSpeechRecognition();
    const onFinalTranscript = vi.fn();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      continuous: true,
      onFinalTranscript,
    }));

    act(() => result.current.start());
    const firstRecognition = FakeSpeechRecognition.instances[0];
    expect(firstRecognition.continuous).toBe(true);
    act(() => {
      firstRecognition.emitResult("Hello", true, 0);
      firstRecognition.emitResult("Hello", true, 0);
    });
    expect(onFinalTranscript).toHaveBeenCalledTimes(1);
    expect(onFinalTranscript).toHaveBeenCalledWith("Hello");

    act(() => firstRecognition.onend?.());
    act(() => vi.advanceTimersByTime(300));
    expect(FakeSpeechRecognition.instances).toHaveLength(2);
    expect(result.current.isListening).toBe(true);

    act(() => result.current.stop());
    act(() => vi.advanceTimersByTime(500));
    expect(FakeSpeechRecognition.instances).toHaveLength(2);
    expect(FakeSpeechRecognition.instances[1].abort).toHaveBeenCalledOnce();
  });

  it("does not restart continuous recognition after a fatal browser error", () => {
    vi.useFakeTimers();
    installSpeechRecognition();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      continuous: true,
      onFinalTranscript: vi.fn(),
    }));

    act(() => result.current.start());
    const recognition = FakeSpeechRecognition.instances[0];
    act(() => {
      recognition.onerror?.({ error: "not-allowed" });
      recognition.onend?.();
      vi.advanceTimersByTime(500);
    });

    expect(result.current.error).toMatch(/Microphone permission was denied/);
    expect(FakeSpeechRecognition.instances).toHaveLength(1);
  });

  it("aborts and invalidates recognition when the hook is disabled or unmounted", () => {
    installSpeechRecognition();
    const onFinalTranscript = vi.fn();
    const { result, rerender, unmount } = renderHook(
      ({ enabled }: { enabled: boolean }) => useSpeechRecognition({
        language: "en",
        enabled,
        onFinalTranscript,
      }),
      { initialProps: { enabled: true } },
    );

    act(() => result.current.start());
    const disabledRecognition = FakeSpeechRecognition.instances[0];
    const lateResult = disabledRecognition.onresult;
    rerender({ enabled: false });
    expect(disabledRecognition.abort).toHaveBeenCalledOnce();
    act(() => {
      lateResult?.({
        resultIndex: 0,
        results: [Object.assign([{ transcript: "Disabled input" }], { isFinal: true, length: 1 })],
      });
      result.current.start();
    });
    expect(FakeSpeechRecognition.instances).toHaveLength(1);
    expect(onFinalTranscript).not.toHaveBeenCalled();

    rerender({ enabled: true });
    act(() => result.current.start());
    const unmountedRecognition = FakeSpeechRecognition.instances[1];
    const unmountLateResult = unmountedRecognition.onresult;
    unmount();
    expect(unmountedRecognition.abort).toHaveBeenCalledOnce();
    unmountLateResult?.({
      resultIndex: 0,
      results: [Object.assign([{ transcript: "Unmounted input" }], { isFinal: true, length: 1 })],
    });
    expect(onFinalTranscript).not.toHaveBeenCalled();
  });

  it.each([
    ["en", "en-IN"],
    ["te", "te-IN"],
    ["ta", "ta-IN"],
    ["hi", "hi-IN"],
  ] as const)("maps %s to browser locale %s", (language, locale) => {
    installSpeechRecognition();
    const { result } = renderHook(() => useSpeechRecognition({
      language,
      enabled: true,
      onFinalTranscript: vi.fn(),
    }));

    act(() => result.current.start());

    expect(FakeSpeechRecognition.instances[0].lang).toBe(locale);
    expect(getRecognitionLocale(language)).toBe(locale);
  });

  it("uses a newly selected language for the next recognition session", () => {
    installSpeechRecognition();
    const { result, rerender } = renderHook(
      ({ language }: { language: "en" | "te" }) => useSpeechRecognition({
        language,
        enabled: true,
        onFinalTranscript: vi.fn(),
      }),
      { initialProps: { language: "en" as "en" | "te" } },
    );

    act(() => result.current.start());
    act(() => FakeSpeechRecognition.instances[0].onend?.());
    rerender({ language: "te" });
    act(() => result.current.start());

    expect(FakeSpeechRecognition.instances[1].lang).toBe("te-IN");
  });

  it.each([
    ["network", /could not connect to the browser's speech service/],
    ["aborted", /Voice input was stopped/],
    ["audio-capture", /No microphone is available/],
  ])("shows a useful message for the %s recognition error", (code, expectedMessage) => {
    installSpeechRecognition();
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript: vi.fn(),
    }));

    act(() => result.current.start());
    act(() => FakeSpeechRecognition.instances[0].onerror?.({ error: code }));

    expect(result.current.error).toMatch(expectedMessage);
  });

  it("reports unsupported recognition without throwing", () => {
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", undefined);
    const { result } = renderHook(() => useSpeechRecognition({
      language: "en",
      enabled: true,
      onFinalTranscript: vi.fn(),
    }));

    expect(result.current.supported).toBe(false);
    act(() => result.current.start());
    expect(result.current.error).toMatch(/not supported in this browser/);
  });
});
