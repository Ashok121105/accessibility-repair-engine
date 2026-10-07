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

  emitResult(transcript: string, isFinal = true) {
    const result: SpeechRecognitionResultLike = Object.assign(
      [{ transcript }],
      { isFinal, length: 1 },
    );
    this.onresult?.({ resultIndex: 0, results: [result] });
  }
}

function installSpeechRecognition() {
  FakeSpeechRecognition.instances = [];
  vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
}

describe("useSpeechRecognition", () => {
  afterEach(() => {
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

    expect(FakeSpeechRecognition.instances[0].stop).toHaveBeenCalledOnce();
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
