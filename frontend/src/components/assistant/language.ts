export const ASSISTANT_LANGUAGES = [
  { code: "en", name: "English", recognitionLocale: "en-IN", translationLocale: "en" },
  { code: "te", name: "Telugu", recognitionLocale: "te-IN", translationLocale: "te" },
  { code: "ta", name: "Tamil", recognitionLocale: "ta-IN", translationLocale: "ta" },
  { code: "hi", name: "Hindi", recognitionLocale: "hi-IN", translationLocale: "hi" },
] as const;

export type AssistantLanguageCode = (typeof ASSISTANT_LANGUAGES)[number]["code"];
export type AssistantInteractionMode = "blind" | "hearing";
export type AssistantLanguageSource = "manual" | "detected" | "fallback";

export interface AssistantLanguageState {
  interaction_mode: AssistantInteractionMode;
  preferred_language: AssistantLanguageCode;
  active_language: AssistantLanguageCode;
  voice_response_language: AssistantLanguageCode;
  language_source: AssistantLanguageSource;
  language_confidence: number;
}

export const INITIAL_ASSISTANT_LANGUAGE_STATE: AssistantLanguageState = {
  interaction_mode: "hearing",
  preferred_language: "en",
  active_language: "en",
  voice_response_language: "en",
  language_source: "fallback",
  language_confidence: 0,
};

export function getLanguageName(languageCode: AssistantLanguageCode): string {
  return ASSISTANT_LANGUAGES.find(({ code }) => code === languageCode)?.name ?? "English";
}

export function getRecognitionLocale(languageCode: AssistantLanguageCode): string {
  return ASSISTANT_LANGUAGES.find(({ code }) => code === languageCode)?.recognitionLocale ?? "en-IN";
}
