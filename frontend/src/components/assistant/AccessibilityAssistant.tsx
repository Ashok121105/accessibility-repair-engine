import { useEffect, useRef, useState, type FormEvent } from "react";
import { Globe2, Mic, MicOff, Send, Volume2 } from "lucide-react";
import { useSpeechRecognition } from "../../hooks/useSpeechRecognition";
import { useSpeechSynthesis } from "../../hooks/useSpeechSynthesis";
import {
  sendAgentCommand,
  startAgent,
  stopAgent,
} from "../../services/api";
import {
  ASSISTANT_LANGUAGES,
  getLanguageName,
  INITIAL_ASSISTANT_LANGUAGE_STATE,
  type AssistantInteractionMode,
  type AssistantLanguageCode,
  type AssistantLanguageSource,
} from "./language";
import {
  appendCaptionHistory,
  createCaptionEntry,
  type CaptionEntry,
} from "../../services/captions";
import type { ShoppingProductSummary } from "../../types/api";

interface ConversationEntry {
  id: number;
  speaker: "You" | "Assistant";
  message: string;
  action?: string;
}

type AuthenticationStatus = "SIGNED_IN" | "SIGNED_OUT" | "UNKNOWN";

const SENSITIVE_CREDENTIAL_VALUE = /\b(?:otp|one[- ]time password|password|passcode|cvv|cvc|upi pin|payment pin|security code|verification code)\b(?:\s+(?:is|equals))?\s*(?:[:=]\s*|\s+)(?!field\b|directly\b|into\b|on\b|please\b|to\b|was\b|requested\b|required\b)([^\n,;.!?]+)/i;
const SENSITIVE_CONTACT_VALUE = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b(?:mobile|phone)(?: number)?\b\s*(?:is\s*)?(?::|=)?\s*\+?[\d][\d -]{7,}\d/i;

function containsSensitiveCredentialValue(text: string): boolean {
  return SENSITIVE_CREDENTIAL_VALUE.test(text) ||
    SENSITIVE_CONTACT_VALUE.test(text) ||
    /^\s*(?:\+?\d[\d -]{7,}\d)\s*$/.test(text);
}

function sanitizeAssistantText(text: string): string {
  if (!containsSensitiveCredentialValue(text)) return text;
  return "Sensitive information was removed from the assistant response.";
}

function userFacingAssistantError(message: string, fallback: string): string {
  if (/\b(?:traceback|stack trace|internal server error|HTTP\s*\d{3}|\w+Error:|at\s+[\w./\\:-]+\s*\()/i.test(message)) {
    return fallback;
  }
  return sanitizeAssistantText(message) || fallback;
}

function websiteLabel(value: string): string {
  try {
    return new URL(value).hostname.replace(/^www\./i, "");
  } catch {
    return "Website session active";
  }
}

function authenticationStatusFrom(value: unknown): AuthenticationStatus | null {
  if (typeof value !== "object" || value === null || !("status" in value)) return null;
  const status = value.status;
  return status === "SIGNED_IN" || status === "SIGNED_OUT" || status === "UNKNOWN"
    ? status
    : null;
}

function isMissingSessionError(message: string): boolean {
  return /session (?:is not active|expired|is no longer active|no longer active)|start the agent again/i.test(message);
}

function isAssistantLanguageCode(value: unknown): value is AssistantLanguageCode {
  return ASSISTANT_LANGUAGES.some(({ code }) => code === value);
}

export default function AccessibilityAssistant() {
  const [agentUrl, setAgentUrl] = useState("https://www.flipkart.com/");
  const [agentSessionId, setAgentSessionId] = useState("");
  const [currentWebsite, setCurrentWebsite] = useState("");
  const [assistantLanguage, setAssistantLanguage] = useState(INITIAL_ASSISTANT_LANGUAGE_STATE);
  const [agentStatus, setAgentStatus] = useState("Agent not started.");
  const [authenticationStatus, setAuthenticationStatus] = useState<AuthenticationStatus>("UNKNOWN");
  const [shoppingResults, setShoppingResults] = useState<ShoppingProductSummary[]>([]);
  const [selectedProductPosition, setSelectedProductPosition] = useState<number | null>(null);
  const [shoppingAnnouncement, setShoppingAnnouncement] = useState("");
  const [agentError, setAgentError] = useState("");
  const [command, setCommand] = useState("");
  const [conversation, setConversation] = useState<ConversationEntry[]>([]);
  const [captions, setCaptions] = useState<CaptionEntry[]>([]);
  const [captionFontScale, setCaptionFontScale] = useState(1);
  const [highContrastCaptions, setHighContrastCaptions] = useState(false);
  const [captionsPaused, setCaptionsPaused] = useState(false);
  const [isStartingAgent, setIsStartingAgent] = useState(false);
  const [isStoppingAgent, setIsStoppingAgent] = useState(false);
  const [isCaptionCaptureActive, setIsCaptionCaptureActive] = useState(false);
  const [isSendingCommand, setIsSendingCommand] = useState(false);
  const [isResettingDemo, setIsResettingDemo] = useState(false);
  const [latestAssistantResponse, setLatestAssistantResponse] = useState("");
  const agentSessionIdRef = useRef("");
  const startPendingRef = useRef(false);
  const stopPendingRef = useRef(false);
  const resetPendingRef = useRef(false);
  const commandPendingRef = useRef(false);
  const mountedRef = useRef(false);
  const captionsPausedRef = useRef(captionsPaused);
  const captionCaptureActiveRef = useRef(false);
  const captionPanelRef = useRef<HTMLDivElement>(null);
  const followCaptionsRef = useRef(true);
  const conversationIdRef = useRef(0);
  const assistantLanguageRef = useRef(assistantLanguage);
  assistantLanguageRef.current = assistantLanguage;
  captionsPausedRef.current = captionsPaused;

  const {
    supported: speechOutputSupported,
    isSpeaking,
    error: speechOutputError,
    status: speechOutputStatus,
    speak: speakResponse,
    stop: stopSpeaking,
  } = useSpeechSynthesis({
    enabled: assistantLanguage.interaction_mode === "blind",
    language: assistantLanguage.active_language,
  });

  function handleModeChange(interactionMode: AssistantInteractionMode) {
    if (assistantLanguageRef.current.interaction_mode === interactionMode) return;
    captionCaptureActiveRef.current = false;
    setIsCaptionCaptureActive(false);
    stopVoiceInput();
    setCaptionsPaused(false);
    setAssistantLanguage((current) => ({ ...current, interaction_mode: interactionMode }));
  }

  function handleLanguageChange(languageCode: string) {
    const language = ASSISTANT_LANGUAGES.find(({ code }) => code === languageCode);
    if (!language) return;
    setAssistantLanguage((current) => ({
      ...current,
      preferred_language: language.code,
      active_language: language.code,
      voice_response_language: language.code,
      language_source: "manual",
      language_confidence: 1,
    }));
  }

  function addConversationEntry(
    speaker: ConversationEntry["speaker"],
    message: string,
    action?: string,
  ) {
    conversationIdRef.current += 1;
    const entry = { id: conversationIdRef.current, speaker, message, action };
    setConversation((current) => [...current, entry]);
  }

  function addCaptionEntry(
    source: CaptionEntry["source"],
    text: string,
    options?: { language?: string; translated?: boolean; severity?: CaptionEntry["severity"] },
  ) {
    if (captionsPausedRef.current) return;
    const entry = createCaptionEntry({
      source,
      text,
      language: options?.language ?? assistantLanguageRef.current.active_language,
      translated: options?.translated ?? false,
      severity: options?.severity ?? "info",
    });
    setCaptions((current) => appendCaptionHistory(current, entry));
  }

  async function handleStartAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (resetPendingRef.current || startPendingRef.current || agentSessionIdRef.current) return;
    const trimmedUrl = agentUrl.trim();
    startPendingRef.current = true;
    setIsStartingAgent(true);
    setAgentError("");
    setAgentStatus("Opening website…");
    try {
      const result = await startAgent(trimmedUrl || agentUrl);
      if (!result.success || !result.session_id) {
        throw new Error(result.message || "The assistant session could not be started.");
      }
      if (!mountedRef.current) {
        try {
          await stopAgent(result.session_id);
        } catch (stopError: unknown) {
          console.error("Could not stop the assistant session created after the page was closed.", stopError);
        }
        return;
      }
      agentSessionIdRef.current = result.session_id;
      setAgentSessionId(result.session_id);
      setCurrentWebsite(websiteLabel(trimmedUrl));
      setAuthenticationStatus(authenticationStatusFrom(result.authentication) ?? "UNKNOWN");
      setAgentStatus("Website opened. Assistant session is ready.");
      const message = result.message;
      addConversationEntry("Assistant", message);
      if (assistantLanguageRef.current.interaction_mode === "hearing") {
        addCaptionEntry("system", message, { severity: "info" });
      }
    } catch (startError: unknown) {
      if (!mountedRef.current) return;
      const message = startError instanceof Error
        ? startError.message
        : "Could not start the assistant. Check that the backend is running and try again.";
      setAgentStatus("Assistant could not be started.");
      setAgentError(userFacingAssistantError(
        message,
        "Could not start the assistant. Check the website URL and backend, then try again.",
      ));
    } finally {
      startPendingRef.current = false;
      if (mountedRef.current) setIsStartingAgent(false);
    }
  }

  async function handleAgentCommand(rawCommand: string) {
    const submittedCommand = rawCommand.trim();
    const activeSessionId = agentSessionIdRef.current;
    if (
      !submittedCommand ||
      !activeSessionId ||
      commandPendingRef.current ||
      resetPendingRef.current ||
      stopPendingRef.current
    ) return;
    commandPendingRef.current = true;
    setIsSendingCommand(true);
    setAgentError("");
    setAgentStatus("Processing command…");
    addConversationEntry(
      "You",
      containsSensitiveCredentialValue(submittedCommand)
        ? "Sensitive information omitted from command history."
        : submittedCommand,
    );
    try {
      const result = await sendAgentCommand(activeSessionId, submittedCommand, {
        preferred_language: assistantLanguageRef.current.preferred_language,
        language_locked: assistantLanguageRef.current.language_source === "manual",
      });
      if (!mountedRef.current) return;
      const safeMessage = sanitizeAssistantText(result.message);
      const details = result.details;
      if (result.session_active && /^https?:\/\//i.test(result.page_url)) {
        setCurrentWebsite(websiteLabel(result.page_url));
      }
      if (typeof details === "object" && details !== null && "authentication" in details) {
        setAuthenticationStatus(authenticationStatusFrom(details.authentication) ?? "UNKNOWN");
      }
      const rawProducts = typeof details === "object" && details !== null && "products" in details
        ? details.products
        : null;
      if (Array.isArray(rawProducts)) {
        setShoppingResults(rawProducts.filter((item): item is ShoppingProductSummary =>
          typeof item === "object" &&
          item !== null &&
          "position" in item &&
          typeof item.position === "number" &&
          "name" in item &&
          typeof item.name === "string",
        ));
        setSelectedProductPosition(null);
      }
      if (typeof details === "object" && details !== null && "position" in details &&
          typeof details.position === "number") {
        setSelectedProductPosition(details.position);
      } else if (result.action === "select_second") {
        setSelectedProductPosition(2);
      }
      const languageMetadata = (
        typeof details === "object" &&
        details !== null &&
        "language" in details &&
        typeof details.language === "object" &&
        details.language !== null
      ) ? details.language : null;
      let responseLanguage = assistantLanguageRef.current.active_language;
      if (languageMetadata) {
        const metadata = languageMetadata as Record<string, unknown>;
        const preferredLanguage = isAssistantLanguageCode(metadata.preferred_language)
          ? metadata.preferred_language
          : assistantLanguageRef.current.preferred_language;
        const activeLanguage = isAssistantLanguageCode(metadata.active_language)
          ? metadata.active_language
          : assistantLanguageRef.current.active_language;
        const languageSource: AssistantLanguageSource =
          metadata.language_source === "manual" ||
          metadata.language_source === "detected" ||
          metadata.language_source === "fallback"
            ? metadata.language_source
            : assistantLanguageRef.current.language_source;
        const languageConfidence = typeof metadata.language_confidence === "number"
          ? metadata.language_confidence
          : assistantLanguageRef.current.language_confidence;
        responseLanguage = activeLanguage;
        setAssistantLanguage((current) => ({
          ...current,
          preferred_language: preferredLanguage,
          active_language: activeLanguage,
          voice_response_language: activeLanguage,
          language_source: languageSource,
          language_confidence: languageConfidence,
        }));
      }
      addConversationEntry("Assistant", safeMessage, result.action);
      if (result.action === "search" || result.action.startsWith("select_") ||
          result.action === "add_to_cart" || result.action === "product_details") {
        setShoppingAnnouncement(safeMessage);
      }
      if (assistantLanguageRef.current.interaction_mode === "hearing" && safeMessage.trim()) {
        addCaptionEntry("assistant", safeMessage, {
          language: responseLanguage,
          translated: responseLanguage !== assistantLanguageRef.current.preferred_language,
          severity: result.success ? "success" : "warning",
        });
      }
      setLatestAssistantResponse(safeMessage);
      if (assistantLanguageRef.current.interaction_mode === "blind" && safeMessage.trim()) {
        const mentionsCredential = /\b(?:otps?|one[- ]time passwords?|verification codes?|security codes?|cvv|card numbers?|passwords?|payment pins?)\b/i.test(safeMessage);
        const safeHandoff = /\b(?:please\s+)?enter\b.{0,100}\bdirectly\b/i.test(safeMessage);
        if ((!mentionsCredential || safeHandoff) && !safeMessage.includes("[REDACTED]")) {
          const speakableMessage = safeMessage.length > 420
            ? `${safeMessage.slice(0, 400)}. For more details, review the on-screen response.`
            : safeMessage;
          speakResponse(speakableMessage, responseLanguage);
        }
      }
      setAgentStatus(result.session_active
        ? (result.success ? "Assistant ready for another command." : "Command was not completed.")
        : "Assistant session stopped because the page requires attention.");
      if (!result.session_active) {
        captionCaptureActiveRef.current = false;
        setIsCaptionCaptureActive(false);
        captionsPausedRef.current = false;
        setCaptionsPaused(false);
        stopVoiceInput();
        agentSessionIdRef.current = "";
        setAgentSessionId("");
        setCurrentWebsite("");
      }
    } catch (commandError: unknown) {
      if (!mountedRef.current) return;
      const message = commandError instanceof Error
        ? commandError.message
        : "The assistant could not process that command. Please try again.";
      setAgentStatus("Command failed.");
      const sessionMissing = isMissingSessionError(message);
      const userMessage = sessionMissing
        ? "Your assistant session is no longer active. Start the assistant again."
        : message;
      if (sessionMissing) {
        captionCaptureActiveRef.current = false;
        setIsCaptionCaptureActive(false);
        captionsPausedRef.current = false;
        setCaptionsPaused(false);
        stopVoiceInput();
        agentSessionIdRef.current = "";
        setAgentSessionId("");
        setCurrentWebsite("");
        setAgentStatus("Assistant session ended. Start Assistant again.");
      }
      const safeError = userFacingAssistantError(
        userMessage,
        "The assistant could not complete that action. Check the website and try again.",
      );
      setAgentError(safeError);
      addConversationEntry("Assistant", safeError);
    } finally {
      commandPendingRef.current = false;
      if (mountedRef.current) {
        setIsSendingCommand(false);
        setCommand("");
      }
    }
  }

  function handleSubmitCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleAgentCommand(command);
  }

  async function handleStopAgent() {
    const activeSessionId = agentSessionIdRef.current;
    if (!activeSessionId || resetPendingRef.current || stopPendingRef.current || commandPendingRef.current) return;
    stopPendingRef.current = true;
    captionCaptureActiveRef.current = false;
    setIsCaptionCaptureActive(false);
    captionsPausedRef.current = false;
    setCaptionsPaused(false);
    stopVoiceInput();
    setIsStoppingAgent(true);
    setAgentError("");
    setAgentStatus("Stopping assistant…");
    try {
      await stopAgent(activeSessionId);
      if (!mountedRef.current) return;
      agentSessionIdRef.current = "";
      setAgentSessionId("");
      setCurrentWebsite("");
      setAgentStatus("Assistant stopped.");
      const message = "Assistant session stopped.";
      addConversationEntry("Assistant", message);
      if (assistantLanguageRef.current.interaction_mode === "hearing") {
        addCaptionEntry("system", message, { severity: "warning" });
      }
    } catch (stopError: unknown) {
      if (!mountedRef.current) return;
      const message = stopError instanceof Error
        ? stopError.message
        : "Could not stop the assistant. Please try again.";
      if (isMissingSessionError(message)) {
        agentSessionIdRef.current = "";
        setAgentSessionId("");
        setCurrentWebsite("");
        setAgentStatus("Assistant session is already closed.");
        setAgentError("The assistant session was already closed. Start Assistant again to reconnect.");
      } else {
        setAgentStatus("Assistant could not be stopped.");
        setAgentError(userFacingAssistantError(
          message,
          "Could not stop the assistant. Please try again.",
        ));
      }
    } finally {
      stopPendingRef.current = false;
      if (mountedRef.current) setIsStoppingAgent(false);
    }
  }

  async function handleResetDemo() {
    if (startPendingRef.current || commandPendingRef.current || resetPendingRef.current || stopPendingRef.current) return;
    const activeSessionId = agentSessionIdRef.current;
    resetPendingRef.current = true;
    captionCaptureActiveRef.current = false;
    setIsCaptionCaptureActive(false);
    captionsPausedRef.current = false;
    setCaptionsPaused(false);
    stopVoiceInput();
    setIsResettingDemo(true);
    setAgentError("");
    setAgentStatus("Resetting demo…");
    try {
      if (activeSessionId) {
        await stopAgent(activeSessionId);
      }
      if (!mountedRef.current) return;
      agentSessionIdRef.current = "";
      setAgentSessionId("");
      setCurrentWebsite("");
      setAuthenticationStatus("UNKNOWN");
      setShoppingResults([]);
      setSelectedProductPosition(null);
      setShoppingAnnouncement("");
      setCommand("");
      setConversation([]);
      setCaptions([]);
      followCaptionsRef.current = true;
      setLatestAssistantResponse("");
      stopSpeaking();
      setAgentStatus("Demo reset. Saved scans and certificates are unchanged.");
    } catch (resetError: unknown) {
      if (!mountedRef.current) return;
      const message = resetError instanceof Error
        ? resetError.message
        : "Could not reset the demo. Please try again.";
      if (isMissingSessionError(message)) {
        agentSessionIdRef.current = "";
        setAgentSessionId("");
        setCurrentWebsite("");
        setAuthenticationStatus("UNKNOWN");
        setShoppingResults([]);
        setSelectedProductPosition(null);
        setShoppingAnnouncement("");
        setCommand("");
        setConversation([]);
        setCaptions([]);
        followCaptionsRef.current = true;
        setLatestAssistantResponse("");
        stopSpeaking();
        setAgentStatus("Demo reset. Saved scans and certificates are unchanged.");
      } else {
        setAgentStatus("Demo could not be reset.");
        setAgentError(userFacingAssistantError(
          message,
          "Could not reset the demo. Please try again.",
        ));
      }
    } finally {
      resetPendingRef.current = false;
      if (mountedRef.current) setIsResettingDemo(false);
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const activeSessionId = agentSessionIdRef.current;
      if (activeSessionId) {
        void stopAgent(activeSessionId).catch((stopError: unknown) => {
          console.error("Could not stop the assistant during page cleanup.", stopError);
        });
      }
    };
  }, []);

  const {
    supported: speechSupported,
    isListening: isVoiceListening,
    transcript: voiceTranscript,
    error: voiceError,
    status: voiceStatus,
    start: startVoiceInput,
    stop: stopVoiceInput,
  } = useSpeechRecognition({
    language: assistantLanguage.active_language,
    enabled: assistantLanguage.interaction_mode === "blind"
      ? Boolean(agentSessionId)
      : isCaptionCaptureActive,
    continuous: assistantLanguage.interaction_mode === "hearing",
    onFinalTranscript: (transcript) => {
      if (assistantLanguageRef.current.interaction_mode === "hearing") {
        if (captionCaptureActiveRef.current) {
          addCaptionEntry("microphone", transcript, {
            language: assistantLanguageRef.current.active_language,
          });
        }
        return;
      }
      setCommand(transcript);
      void handleAgentCommand(transcript);
    },
  });

  function startCaptionCapture() {
    if (!speechSupported || captionsPausedRef.current) return;
    captionCaptureActiveRef.current = true;
    setIsCaptionCaptureActive(true);
  }

  function stopCaptionCapture() {
    captionCaptureActiveRef.current = false;
    setIsCaptionCaptureActive(false);
    captionsPausedRef.current = false;
    setCaptionsPaused(false);
    stopVoiceInput();
  }

  function toggleCaptionsPaused() {
    if (!captionsPausedRef.current) {
      captionsPausedRef.current = true;
      setCaptionsPaused(true);
      captionCaptureActiveRef.current = false;
      stopVoiceInput();
      return;
    }

    captionsPausedRef.current = false;
    setCaptionsPaused(false);
    if (assistantLanguageRef.current.interaction_mode === "hearing") {
      captionCaptureActiveRef.current = true;
      startVoiceInput();
    } else {
      captionCaptureActiveRef.current = false;
    }
  }

  function clearCaptions() {
    followCaptionsRef.current = true;
    setCaptions([]);
  }

  useEffect(() => {
    if (isCaptionCaptureActive && assistantLanguage.interaction_mode === "hearing") {
      startVoiceInput();
    }
  }, [assistantLanguage.interaction_mode, isCaptionCaptureActive, startVoiceInput]);

  useEffect(() => {
    const panel = captionPanelRef.current;
    if (panel && followCaptionsRef.current) panel.scrollTop = panel.scrollHeight;
  }, [captions]);

  function handleReplayResponse() {
    if (assistantLanguage.interaction_mode !== "blind" || !latestAssistantResponse.trim()) return;
    speakResponse(latestAssistantResponse, assistantLanguage.active_language);
  }

  return (
    <section aria-label="Accessibility Assistant workspace" className="assistant-panel">
      {agentError && <div className="assistant-error" role="alert">{agentError}</div>}

      <section aria-labelledby="assistant-preferences-title" className="assistant-card assistant-preferences-card">
        <div className="assistant-card-heading">
          <div>
            <span className="panel-kicker">ACCESSIBLE INTERACTION</span>
            <h2 id="assistant-preferences-title">Choose how to interact</h2>
          </div>
          <p aria-live="polite" className="assistant-agent-status" role="status">
            Mode: {assistantLanguage.interaction_mode === "blind" ? "Blind Mode" : "Hearing Mode"}.
            {" "}Language: {getLanguageName(assistantLanguage.active_language)}.
            {" "}Source: {assistantLanguage.language_source === "manual"
              ? "Manual"
              : assistantLanguage.language_source === "detected"
                ? "Automatically detected"
                : "Fallback"}.
          </p>
        </div>

        <fieldset className="assistant-mode-selector">
          <legend>Interaction mode</legend>
          <label className={assistantLanguage.interaction_mode === "blind" ? "selected" : ""}>
            <input
              checked={assistantLanguage.interaction_mode === "blind"}
              name="assistant-interaction-mode"
              onChange={() => handleModeChange("blind")}
              type="radio"
              value="blind"
            />
            <span aria-hidden="true" className="assistant-mode-emoji">👁️</span>
            <span><strong>Blind Mode</strong><small>Voice-first accessibility interaction</small></span>
          </label>
          <label className={assistantLanguage.interaction_mode === "hearing" ? "selected" : ""}>
            <input
              checked={assistantLanguage.interaction_mode === "hearing"}
              name="assistant-interaction-mode"
              onChange={() => handleModeChange("hearing")}
              type="radio"
              value="hearing"
            />
            <span aria-hidden="true" className="assistant-mode-emoji">👂</span>
            <span><strong>Hearing Mode</strong><small>Text and caption-first interaction</small></span>
          </label>
        </fieldset>

        <div className="assistant-language-controls">
          <label htmlFor="assistant-preferred-language">Preferred language</label>
          <select
            id="assistant-preferred-language"
            disabled={isVoiceListening || isCaptionCaptureActive}
            onChange={(event) => handleLanguageChange(event.target.value)}
            value={assistantLanguage.preferred_language}
          >
            {ASSISTANT_LANGUAGES.map(({ code, name }) => (
              <option key={code} value={code}>{name}</option>
            ))}
          </select>
          <p aria-label="Preferred language status" aria-live="polite" className="assistant-language-state" role="status">
            Language: {getLanguageName(assistantLanguage.active_language)}
            {" "}· Source: {assistantLanguage.language_source === "manual"
              ? "Manual"
              : assistantLanguage.language_source === "detected"
                ? "Automatically detected"
                : "Fallback"}
          </p>
        </div>

        {assistantLanguage.interaction_mode === "blind" ? (
          <section aria-labelledby="assistant-voice-interaction-title" className="assistant-mode-detail">
            <h3 id="assistant-voice-interaction-title">Voice interaction</h3>
            <p>Speech recognition and voice responses use {getLanguageName(assistantLanguage.active_language)}. You can also choose a preferred language.</p>
            <p>Automatic language detection is not enabled in Blind Mode; the selected preferred language is used for voice input and TTS.</p>
            {!speechSupported ? (
              <p className="assistant-voice-error" role="alert">
                Voice input is not supported in this browser. Use text input instead.
              </p>
            ) : (
              <div className="assistant-voice-controls">
                <div aria-live="polite" className="assistant-voice-status" role="status">
                  {isVoiceListening && <span aria-hidden="true" className="assistant-listening-indicator" />}
                  {isVoiceListening ? "Listening…" : voiceStatus || "Microphone ready."}
                </div>
                {voiceError && <p className="assistant-voice-error" role="alert">{voiceError}</p>}
                <div className="assistant-controls">
                  <button
                    className="primary-button"
                    disabled={!agentSessionId || isVoiceListening || isSendingCommand || isStartingAgent}
                    onClick={startVoiceInput}
                    type="button"
                  >
                    <Mic aria-hidden="true" size={16} /> Start Voice Input
                  </button>
                  {isVoiceListening && (
                    <button className="assistant-secondary-button" onClick={stopVoiceInput} type="button">
                      <MicOff aria-hidden="true" size={16} /> Stop Voice Input
                    </button>
                  )}
                </div>
                {!agentSessionId && <p>Start the assistant session before using voice input.</p>}
                {voiceTranscript && (
                  <p aria-live="polite" className="assistant-voice-transcript" role="status">
                    <strong>Transcript:</strong> {sanitizeAssistantText(voiceTranscript)}
                  </p>
                )}
              </div>
            )}
            <div className="assistant-tts-controls">
              <p aria-label="Speech output status" aria-live="polite" className="assistant-tts-status" role="status">
                {isSpeaking ? "Assistant is speaking." : speechOutputStatus}
              </p>
              {!speechOutputSupported && (
                <p className="assistant-voice-error" role="status">
                  Voice output is unavailable in this browser. Text response is still available.
                </p>
              )}
              {speechOutputError && speechOutputSupported && (
                <p className="assistant-voice-error" role="status">{speechOutputError}</p>
              )}
              <div className="assistant-controls">
                <button
                  aria-label="Stop speaking"
                  className="assistant-secondary-button"
                  disabled={!isSpeaking}
                  onClick={stopSpeaking}
                  type="button"
                >
                  Stop speaking
                </button>
                {latestAssistantResponse.trim() && (
                  <button
                    aria-busy={isResettingDemo}
                    className="assistant-secondary-button"
                    disabled={!speechOutputSupported}
                    onClick={handleReplayResponse}
                    type="button"
                  >
                    <Volume2 aria-hidden="true" size={16} /> Replay response
                  </button>
                )}
              </div>
            </div>
          </section>
        ) : (
          <section aria-labelledby="assistant-live-captions-title" className="assistant-mode-detail">
            <div className="assistant-caption-header">
              <h3 id="assistant-live-captions-title">Live captions</h3>
              <div className="assistant-caption-controls" role="group" aria-label="Caption controls">
                <button
                  className="assistant-secondary-button"
                  disabled={!isCaptionCaptureActive && !captionsPaused}
                  onClick={toggleCaptionsPaused}
                  type="button"
                >
                  {captionsPaused ? "Resume captions" : "Pause captions"}
                </button>
                <button
                  className="assistant-secondary-button"
                  onClick={clearCaptions}
                  type="button"
                >
                  Clear captions
                </button>
                <button
                  aria-label="Increase caption text size"
                  className="assistant-secondary-button"
                  onClick={() => setCaptionFontScale((current) => Math.min(1.5, Number((current + 0.1).toFixed(1))))}
                  type="button"
                >
                  A+
                </button>
                <button
                  aria-label="Decrease caption text size"
                  className="assistant-secondary-button"
                  onClick={() => setCaptionFontScale((current) => Math.max(0.9, Number((current - 0.1).toFixed(1))))}
                  type="button"
                >
                  A-
                </button>
                <label className="caption-toggle">
                  <input
                    checked={highContrastCaptions}
                    onChange={() => setHighContrastCaptions((current) => !current)}
                    type="checkbox"
                  />
                  High contrast
                </label>
              </div>
            </div>
            <p aria-live="polite" role="status">
              {captionsPaused
                ? "Captions paused. Microphone capture is stopped."
                : isVoiceListening
                  ? "Listening for speech from your microphone."
                  : isCaptionCaptureActive
                    ? voiceStatus || "Microphone captions are ready."
                    : "Microphone captions are stopped."}
            </p>
            <p>
              Microphone captions use the selected language and browser speech-recognition service. They do not capture website or system audio, or translate speech.
            </p>
            {!speechSupported ? (
              <p className="assistant-voice-error" role="status">
                Live microphone captions are not supported in this browser.
              </p>
            ) : (
              <div className="assistant-controls">
                {!isCaptionCaptureActive ? (
                  <button
                    className="primary-button"
                    disabled={isStoppingAgent || isResettingDemo}
                    onClick={startCaptionCapture}
                    type="button"
                  >
                    <Mic aria-hidden="true" size={16} /> Start Live Captions
                  </button>
                ) : (
                  <button
                    className="assistant-secondary-button"
                    onClick={stopCaptionCapture}
                    type="button"
                  >
                    <MicOff aria-hidden="true" size={16} /> Stop Live Captions
                  </button>
                )}
                {isCaptionCaptureActive && voiceError && (
                  <button
                    className="assistant-secondary-button"
                    onClick={startVoiceInput}
                    type="button"
                  >
                    Retry Live Captions
                  </button>
                )}
              </div>
            )}
            {voiceError && speechSupported && <p className="assistant-voice-error" role="alert">{voiceError}</p>}
            <div
              aria-live="polite"
              aria-relevant="additions text"
              className={`assistant-caption-panel ${highContrastCaptions ? "high-contrast" : ""}`}
              onScroll={(event) => {
                const panel = event.currentTarget;
                followCaptionsRef.current =
                  panel.scrollHeight - panel.scrollTop - panel.clientHeight <= 24;
              }}
              ref={captionPanelRef}
              role="log"
              style={{ fontSize: `${captionFontScale}rem` }}
              tabIndex={0}
              aria-label="Caption history"
            >
              {captions.length === 0 ? (
                <p>Captured speech and assistant responses will appear here.</p>
              ) : (
                captions.map((entry) => (
                  <div className={`caption-entry caption-${entry.severity}`} key={entry.id}>
                    <div className="caption-meta">
                      <span className="caption-time">[{entry.timestamp}]</span>
                      <span className="caption-source">{entry.source.toUpperCase()}</span>
                      <span className="caption-language">{entry.language}</span>
                    </div>
                    <p>{entry.text}</p>
                  </div>
                ))
              )}
            </div>
            {shoppingResults.length > 0 && (
              <section aria-label="Shopping search results" className="assistant-shopping-results">
                <h4>Search results</h4>
                <ol>
                  {shoppingResults.map((product) => (
                    <li key={`${product.position}-${product.url ?? product.name}`}>
                      <article aria-label={`Product ${product.position}: ${product.name}`}>
                        <h5>{product.position}. {product.name}</h5>
                        {product.price !== null && (
                          <p>
                            {product.currency === "INR" ? "₹" : ""}
                            {product.price.toLocaleString()}
                          </p>
                        )}
                        {product.rating !== null && <p>Rating: {product.rating}</p>}
                        {product.review_count !== null && <p>Reviews: {product.review_count.toLocaleString()}</p>}
                        <button
                          aria-pressed={selectedProductPosition === product.position}
                          className="assistant-secondary-button"
                          onClick={() => void handleAgentCommand(`Select product ${product.position}`)}
                          type="button"
                        >
                          {selectedProductPosition === product.position
                            ? `Selected product ${product.position}`
                            : `Open product ${product.position}`}
                        </button>
                      </article>
                    </li>
                  ))}
                </ol>
              </section>
            )}
            <p>Typed commands can be automatically detected when the selected language has not been manually locked.</p>
          </section>
        )}
      </section>

      <section aria-labelledby="assistant-agent-title" className="assistant-card assistant-agent-card">
        <div className="assistant-card-heading">
          <div>
            <span className="panel-kicker">ASSISTANT SESSION</span>
            <h2 id="assistant-agent-title">Interact with a website</h2>
          </div>
          <span aria-live="polite" className="assistant-agent-status" role="status">
            {agentStatus}
          </span>
        </div>
        <p className="assistant-help">
          Start a Flipkart browser session for accessible interaction, page inspection, and shopping guidance.
          You stay in control of account and checkout steps. The assistant never reads or stores passwords,
          OTPs, CVVs, card numbers, or UPI PINs, and never bypasses CAPTCHA or security checks. Use the
          Accessibility Repair Engine to scan other websites.
        </p>
        <form className="assistant-agent-start-form" onSubmit={(event) => void handleStartAgent(event)}>
          <label htmlFor="assistant-agent-url">Flipkart website URL</label>
          <div className="assistant-agent-url-entry">
            <Globe2 aria-hidden="true" size={16} />
            <input
              aria-describedby="assistant-agent-url-help"
              autoComplete="url"
              id="assistant-agent-url"
              onChange={(event) => setAgentUrl(event.target.value)}
              placeholder="https://www.flipkart.com/"
              required
              type="url"
              value={agentUrl}
            />
            <button
              className="primary-button"
              disabled={isStartingAgent || isStoppingAgent || isResettingDemo || Boolean(agentSessionId)}
              type="submit"
            >
              {isStartingAgent ? "Starting…" : "Start Assistant"}
            </button>
          </div>
          <p id="assistant-agent-url-help" className="assistant-help">
            Start the controlled browser on Flipkart, then use voice or text commands such as “Open AJIO” to navigate to public websites.
          </p>
        </form>
        {agentSessionId && (
          <dl aria-label="Assistant session details" className="assistant-agent-session">
            <div><dt>Connection</dt><dd>Connected</dd></div>
            <div><dt>Website</dt><dd>{currentWebsite || "Website session active"}</dd></div>
            <div><dt>Session ID</dt><dd><code>{agentSessionId}</code></dd></div>
            <div>
              <dt>Flipkart authentication</dt>
              <dd aria-live="polite" role="status">
                {authenticationStatus === "SIGNED_IN"
                  ? "Signed in"
                  : authenticationStatus === "SIGNED_OUT"
                    ? "Signed out"
                    : "Unknown"}
              </dd>
            </div>
          </dl>
        )}
        {shoppingAnnouncement && (
          <p aria-live="polite" className="assistant-shopping-status" role="status">
            {shoppingAnnouncement}
          </p>
        )}
        <div className="assistant-agent-controls">
          <form className="assistant-agent-command-form" onSubmit={handleSubmitCommand}>
            <label htmlFor="assistant-agent-command">Text command</label>
            <div className="assistant-text-entry">
              <input
                disabled={!agentSessionId || isSendingCommand || isStoppingAgent || isResettingDemo}
                id="assistant-agent-command"
                onChange={(event) => setCommand(event.target.value)}
                placeholder="Open Flipkart"
                value={command}
              />
              <button
                className="primary-button"
                disabled={!command.trim() || !agentSessionId || isSendingCommand || isStartingAgent || isStoppingAgent || isResettingDemo}
                type="submit"
              >
                <Send size={15} /> {isSendingCommand ? "Sending…" : "Send Command"}
              </button>
            </div>
            {!agentSessionId && <p className="assistant-help">Start Assistant to enable text commands.</p>}
          </form>
          {agentSessionId && (
            <button
              className="assistant-secondary-button"
              disabled={isSendingCommand || isStartingAgent || isStoppingAgent || isResettingDemo}
              onClick={() => void handleStopAgent()}
              type="button"
            >
              {isStoppingAgent ? "Stopping…" : "Stop Assistant"}
            </button>
          )}
          <button
            className="assistant-secondary-button"
            disabled={isSendingCommand || isStartingAgent || isStoppingAgent || isResettingDemo}
            onClick={() => void handleResetDemo()}
            type="button"
          >
            {isResettingDemo ? "Resetting demo…" : "Reset Demo"}
          </button>
        </div>
        <section aria-label="Assistant conversation" className="assistant-agent-history">
          {conversation.length === 0 ? (
            <p className="assistant-transcript-placeholder">Commands and browser actions will appear here.</p>
          ) : (
            <ol
              aria-label="Assistant conversation"
              aria-live="polite"
              aria-relevant="additions"
              role="log"
            >
              {conversation.map((entry) => (
                <li
                  className={`assistant-conversation-entry ${entry.speaker.toLowerCase()}`}
                  key={entry.id}
                >
                  <strong>{entry.speaker}</strong>
                  <p>{entry.message}</p>
                  {entry.action && (
                    <span className="assistant-action-label">
                      Action: {entry.action.replace(/_/g, " ")}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          )}
        </section>
      </section>

    </section>
  );
}
