import { useCallback, useEffect, useRef, useState } from "react";
import type { AssistantLanguageCode } from "../components/assistant/language";
import { getRecognitionLocale } from "../components/assistant/language";
import {
  getSpeechRecognitionConstructor,
  getSpeechRecognitionErrorMessage,
  type BrowserSpeechRecognition,
} from "../services/speech";

interface UseSpeechRecognitionOptions {
  language: AssistantLanguageCode;
  enabled: boolean;
  continuous?: boolean;
  onFinalTranscript: (transcript: string) => void;
}

const RESTART_DELAY_MS = 300;

export function useSpeechRecognition({
  language,
  enabled,
  continuous = false,
  onFinalTranscript,
}: UseSpeechRecognitionOptions) {
  const [supported] = useState(() => Boolean(getSpeechRecognitionConstructor()));
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const transcriptHandlerRef = useRef(onFinalTranscript);
  const sessionIdRef = useRef(0);
  const runningRef = useRef(false);
  const restartTimeoutRef = useRef<number | null>(null);

  transcriptHandlerRef.current = onFinalTranscript;

  const stop = useCallback(() => {
    if (
      !runningRef.current &&
      !recognitionRef.current &&
      restartTimeoutRef.current === null
    ) return;
    sessionIdRef.current += 1;
    runningRef.current = false;
    if (restartTimeoutRef.current !== null) {
      window.clearTimeout(restartTimeoutRef.current);
      restartTimeoutRef.current = null;
    }

    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (recognition) {
      recognition.onstart = null;
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      try {
        recognition.abort();
      } catch {
        try {
          recognition.stop();
        } catch {
          setError("Could not stop microphone capture. Check your browser microphone permissions.");
        }
      }
    }

    setIsListening(false);
    setStatus("Voice input stopped.");
  }, []);

  const start = useCallback(() => {
    if (!supported) {
      setError("Voice input is not supported in this browser. Use text input instead.");
      return;
    }
    if (!enabled) {
      setError("Start the assistant session before using voice input.");
      return;
    }
    if (runningRef.current) return;

    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) {
      setError("Voice input is not supported in this browser. Use text input instead.");
      return;
    }

    const sessionId = sessionIdRef.current + 1;
    sessionIdRef.current = sessionId;
    runningRef.current = true;
    setError("");
    setTranscript("");
    setStatus("Requesting microphone access…");

    const beginRecognition = () => {
      if (!runningRef.current || sessionIdRef.current !== sessionId) return;

      let recognition: BrowserSpeechRecognition;
      try {
        recognition = new Recognition();
      } catch {
        runningRef.current = false;
        setIsListening(false);
        const message = "Could not start voice input. Check microphone access and try again.";
        setError(message);
        setStatus(message);
        return;
      }
      recognitionRef.current = recognition;
      recognition.lang = getRecognitionLocale(language);
      recognition.interimResults = true;
      recognition.continuous = continuous;

      let finalTranscript = "";
      let failed = false;
      const emittedFinalIndexes = new Set<number>();

      const isCurrentRecognition = () =>
        recognitionRef.current === recognition &&
        runningRef.current &&
        sessionIdRef.current === sessionId;

      recognition.onstart = () => {
        if (!isCurrentRecognition()) return;
        setIsListening(true);
        setStatus("Listening…");
      };
      recognition.onresult = (event) => {
        if (!isCurrentRecognition()) return;
        const interimParts: string[] = [];
        const continuousFinals: string[] = [];
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          const resultText = result[0]?.transcript?.trim() ?? "";
          if (!resultText) continue;
          if (result.isFinal) {
            if (emittedFinalIndexes.has(index)) continue;
            emittedFinalIndexes.add(index);
            if (continuous) {
              continuousFinals.push(resultText);
            } else {
              finalTranscript = `${finalTranscript}${resultText}`;
            }
          } else {
            interimParts.push(resultText);
          }
        }

        if (continuous) {
          setTranscript([...continuousFinals.slice(-1), ...interimParts].filter(Boolean).join(" ").trim());
          continuousFinals.forEach((finalPart) => transcriptHandlerRef.current(finalPart));
        } else {
          setTranscript(`${finalTranscript}${interimParts.join("")}`.trim());
        }
      };
      recognition.onerror = (event) => {
        if (!isCurrentRecognition()) return;
        if (continuous && event.error === "no-speech") return;

        failed = true;
        runningRef.current = false;
        recognitionRef.current = null;
        recognition.onstart = null;
        recognition.onresult = null;
        recognition.onerror = null;
        recognition.onend = null;
        const message = getSpeechRecognitionErrorMessage(event.error);
        setError(message);
        setStatus(message);
        setIsListening(false);
      };
      recognition.onend = () => {
        if (!isCurrentRecognition()) return;
        recognitionRef.current = null;
        recognition.onstart = null;
        recognition.onresult = null;
        recognition.onerror = null;
        recognition.onend = null;
        setIsListening(false);

        if (continuous && !failed) {
          setStatus("Reconnecting microphone…");
          restartTimeoutRef.current = window.setTimeout(() => {
            restartTimeoutRef.current = null;
            beginRecognition();
          }, RESTART_DELAY_MS);
          return;
        }

        runningRef.current = false;
        const completedTranscript = finalTranscript.trim();
        if (!failed && completedTranscript) {
          setTranscript(completedTranscript);
          setStatus("Transcript ready. Sending command…");
          transcriptHandlerRef.current(completedTranscript);
        } else if (!failed) {
          const message = "No speech was detected. Check your microphone and try again.";
          setError(message);
          setStatus(message);
        }
      };

      try {
        recognition.start();
      } catch {
        recognition.onstart = null;
        recognition.onresult = null;
        recognition.onerror = null;
        recognition.onend = null;
        if (recognitionRef.current === recognition) recognitionRef.current = null;
        runningRef.current = false;
        setIsListening(false);
        const message = "Could not start voice input. Check microphone access and try again.";
        setError(message);
        setStatus(message);
      }
    };

    beginRecognition();
  }, [continuous, enabled, language, supported]);

  useEffect(() => {
    if (enabled) return;
    stop();
  }, [enabled, stop]);

  useEffect(() => () => {
    sessionIdRef.current += 1;
    runningRef.current = false;
    if (restartTimeoutRef.current !== null) {
      window.clearTimeout(restartTimeoutRef.current);
      restartTimeoutRef.current = null;
    }
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (!recognition) return;
    recognition.onstart = null;
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    try {
      recognition.abort();
    } catch (error: unknown) {
      console.error("Could not stop browser speech recognition during cleanup.", error);
    }
  }, []);

  return { supported, isListening, transcript, error, status, start, stop };
}
