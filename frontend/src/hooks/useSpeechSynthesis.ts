import { useCallback, useEffect, useRef, useState } from "react";
import type { AssistantLanguageCode } from "../components/assistant/language";
import { getRecognitionLocale } from "../components/assistant/language";
import {
  getSpeechSynthesis,
  getSpeechSynthesisUtteranceConstructor,
  isSpeechSynthesisSupported,
  type SpeechSynthesisUtteranceLike,
} from "../services/speech";

interface UseSpeechSynthesisOptions {
  enabled: boolean;
  language: AssistantLanguageCode;
}

export function useSpeechSynthesis({ enabled, language }: UseSpeechSynthesisOptions) {
  const [supported] = useState(isSpeechSynthesisSupported);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Assistant is not speaking.");
  const utteranceRef = useRef<SpeechSynthesisUtteranceLike | null>(null);
  const utteranceIdRef = useRef(0);
  const enabledRef = useRef(enabled);
  const previousEnabledRef = useRef(enabled);
  const previousLanguageRef = useRef(language);
  enabledRef.current = enabled;

  const stop = useCallback(() => {
    utteranceIdRef.current += 1;
    const hadActiveUtterance = utteranceRef.current !== null;
    utteranceRef.current = null;
    if (hadActiveUtterance) {
      try {
        getSpeechSynthesis()?.cancel();
      } catch {
        setError("Voice output could not be stopped in this browser.");
      }
    }
    setIsSpeaking(false);
    setStatus("Assistant is not speaking.");
  }, []);

  const speak = useCallback((text: string, responseLanguage: AssistantLanguageCode): boolean => {
    const spokenText = text.trim();
    if (!spokenText) return false;
    if (!enabledRef.current) return false;

    const synthesis = getSpeechSynthesis();
    const Utterance = getSpeechSynthesisUtteranceConstructor();
    if (!synthesis || !Utterance) {
      const message = "Voice output is unavailable in this browser. Text response is still available.";
      setError(message);
      setStatus(message);
      return false;
    }

    utteranceIdRef.current += 1;
    const utteranceId = utteranceIdRef.current;
    try {
      if (utteranceRef.current) synthesis.cancel();
      const utterance = new Utterance(spokenText);
      utterance.lang = getRecognitionLocale(responseLanguage);
      utteranceRef.current = utterance;
      utterance.onstart = () => {
        if (utteranceId !== utteranceIdRef.current) return;
        setIsSpeaking(true);
        setError("");
        setStatus("Assistant is speaking.");
      };
      utterance.onend = () => {
        if (utteranceId !== utteranceIdRef.current) return;
        utteranceRef.current = null;
        setIsSpeaking(false);
        setStatus("Assistant is not speaking.");
      };
      utterance.onerror = (event) => {
        if (utteranceId !== utteranceIdRef.current) return;
        utteranceRef.current = null;
        setIsSpeaking(false);
        if (event.error === "canceled" || event.error === "interrupted") {
          setStatus("Assistant is not speaking.");
          return;
        }
        const message = "Voice output could not be played in this browser. Text response is still available.";
        setError(message);
        setStatus(message);
      };
      setError("");
      setStatus("Preparing voice response…");
      synthesis.speak(utterance);
      return true;
    } catch {
      utteranceRef.current = null;
      setIsSpeaking(false);
      const message = "Voice output could not be played in this browser. Text response is still available.";
      setError(message);
      setStatus(message);
      return false;
    }
  }, []);

  useEffect(() => {
    if (previousEnabledRef.current && !enabled) stop();
    previousEnabledRef.current = enabled;
  }, [enabled, stop]);

  useEffect(() => {
    if (previousLanguageRef.current === language) return;
    previousLanguageRef.current = language;
    stop();
  }, [language, stop]);

  useEffect(() => () => {
    utteranceIdRef.current += 1;
    utteranceRef.current = null;
    try {
      getSpeechSynthesis()?.cancel();
    } catch {
      // The component is unmounting; there is no UI left to report a cancellation failure to.
    }
  }, []);

  return { supported, isSpeaking, error, status, speak, stop };
}
