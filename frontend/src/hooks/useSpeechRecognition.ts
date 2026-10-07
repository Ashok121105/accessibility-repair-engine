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
  onFinalTranscript: (transcript: string) => void;
}

export function useSpeechRecognition({
  language,
  enabled,
  onFinalTranscript,
}: UseSpeechRecognitionOptions) {
  const [supported] = useState(() => Boolean(getSpeechRecognitionConstructor()));
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const transcriptHandlerRef = useRef(onFinalTranscript);
  const userStoppedRef = useRef(false);

  transcriptHandlerRef.current = onFinalTranscript;

  const stop = useCallback(() => {
    const recognition = recognitionRef.current;
    if (!recognition) return;
    userStoppedRef.current = true;
    try {
      recognition.stop();
    } catch {
      recognitionRef.current = null;
      setIsListening(false);
      setStatus("Voice input stopped.");
    }
  }, []);

  const start = useCallback(() => {
    if (!supported) {
      setError("Voice input is not supported in this browser. Please use a supported browser or switch to Hearing Mode.");
      return;
    }
    if (!enabled) {
      setError("Start the assistant session before using voice input.");
      return;
    }
    if (recognitionRef.current) return;

    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) {
      setError("Voice input is not supported in this browser. Please use a supported browser or switch to Hearing Mode.");
      return;
    }

    setError("");
    setTranscript("");
    setStatus("Requesting microphone access…");
    let finalTranscript = "";
    let failed = false;
    userStoppedRef.current = false;
    const recognition = new Recognition();
    recognitionRef.current = recognition;
    recognition.lang = getRecognitionLocale(language);
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.onstart = () => {
      setIsListening(true);
      setStatus("Listening…");
    };
    recognition.onresult = (event) => {
      const interimParts: string[] = [];
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const resultText = result[0]?.transcript ?? "";
        if (result.isFinal) finalTranscript += resultText;
        else interimParts.push(resultText);
      }
      setTranscript(`${finalTranscript}${interimParts.join("")}`.trim());
    };
    recognition.onerror = (event) => {
      failed = true;
      const message = getSpeechRecognitionErrorMessage(event.error);
      setError(message);
      setStatus(message);
      setIsListening(false);
      recognitionRef.current = null;
    };
    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return;
      recognitionRef.current = null;
      setIsListening(false);
      const completedTranscript = finalTranscript.trim();
      if (!failed && completedTranscript) {
        setTranscript(completedTranscript);
        setStatus("Transcript ready. Sending command…");
        transcriptHandlerRef.current(completedTranscript);
      } else if (!failed && userStoppedRef.current) {
        setStatus("Voice input stopped.");
      } else if (!failed) {
        const message = "No speech was detected. Check your microphone and try again.";
        setError(message);
        setStatus(message);
      }
    };

    try {
      recognition.start();
    } catch {
      recognitionRef.current = null;
      setIsListening(false);
      const message = "Could not start voice input. Check microphone access and try again.";
      setError(message);
      setStatus(message);
    }
  }, [enabled, language, supported]);

  useEffect(() => {
    if (enabled) return;
    const recognition = recognitionRef.current;
    if (!recognition) return;
    recognitionRef.current = null;
    setIsListening(false);
    recognition.abort();
  }, [enabled]);

  useEffect(() => () => {
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    recognition?.abort();
  }, []);

  return { supported, isListening, transcript, error, status, start, stop };
}
