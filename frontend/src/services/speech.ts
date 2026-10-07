export interface SpeechRecognitionAlternativeLike {
  transcript: string;
}

export interface SpeechRecognitionResultLike {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechRecognitionAlternativeLike;
}

export interface SpeechRecognitionResultEventLike {
  readonly resultIndex: number;
  readonly results: ArrayLike<SpeechRecognitionResultLike>;
}

export interface SpeechRecognitionErrorEventLike {
  readonly error: string;
}

export interface BrowserSpeechRecognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onstart: (() => void) | null;
  onresult: ((event: SpeechRecognitionResultEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

export interface BrowserSpeechRecognitionConstructor {
  new(): BrowserSpeechRecognition;
}

interface SpeechRecognitionWindow extends Window {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor;
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
}

export function getSpeechRecognitionConstructor():
  | BrowserSpeechRecognitionConstructor
  | undefined {
  if (typeof window === "undefined") return undefined;
  const speechWindow = window as SpeechRecognitionWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
}

export function getSpeechRecognitionErrorMessage(error: string): string {
  switch (error) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone permission was denied. Allow microphone access in your browser settings and try again.";
    case "no-speech":
      return "No speech was detected. Check your microphone and try again.";
    case "network":
      return "Speech recognition could not connect to the browser's speech service. Check your connection and try again.";
    case "aborted":
      return "Voice input was stopped.";
    case "audio-capture":
      return "No microphone is available. Connect or enable a microphone and try again.";
    case "language-not-supported":
      return "Speech recognition does not support the selected language in this browser.";
    default:
      return "Speech recognition encountered a problem. Please try again or use text input.";
  }
}

export interface SpeechSynthesisUtteranceLike {
  lang: string;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  text: string;
}

export interface SpeechSynthesisUtteranceConstructor {
  new(text?: string): SpeechSynthesisUtteranceLike;
}

export interface BrowserSpeechSynthesis {
  speaking: boolean;
  speak(utterance: SpeechSynthesisUtteranceLike): void;
  cancel(): void;
}

interface SpeechSynthesisWindow {
  speechSynthesis?: BrowserSpeechSynthesis;
  SpeechSynthesisUtterance?: SpeechSynthesisUtteranceConstructor;
}

export function getSpeechSynthesis(): BrowserSpeechSynthesis | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as SpeechSynthesisWindow).speechSynthesis;
}

export function getSpeechSynthesisUtteranceConstructor():
  | SpeechSynthesisUtteranceConstructor
  | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as SpeechSynthesisWindow).SpeechSynthesisUtterance;
}

export function isSpeechSynthesisSupported(): boolean {
  return Boolean(getSpeechSynthesis() && getSpeechSynthesisUtteranceConstructor());
}
