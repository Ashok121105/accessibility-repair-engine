export type CaptionSource = "assistant" | "website" | "video" | "system" | "payment" | "navigation";
export type CaptionSeverity = "info" | "success" | "warning" | "error";

export interface CaptionEntry {
  id: string;
  timestamp: string;
  source: CaptionSource;
  text: string;
  language: string;
  translated: boolean;
  severity: CaptionSeverity;
}

export const MAX_CAPTION_HISTORY = 100;

const SENSITIVE_CAPTION_PATTERNS = [
  /\bOTP\b[\s:=-]*\d+/i,
  /\b(?:CVV|CVC|security code|verification code)\b[\s:=-]*\d+/i,
  /\bUPI PIN\b[\s:=-]*\d+/i,
  /\bpassword\b[\s:=-]*[A-Za-z0-9!@#$%^&*()_+=-]+/i,
  /\bcard number\b[\s:=-]*\d[\d -]{8,}\d/i,
];

export function sanitizeCaptionText(text: string): string {
  let sanitized = text.trim();
  for (const pattern of SENSITIVE_CAPTION_PATTERNS) {
    sanitized = sanitized.replace(pattern, "[REDACTED]");
  }
  return sanitized;
}

export function createCaptionEntry({
  source,
  text,
  language = "en",
  translated = false,
  severity = "info",
}: {
  source: CaptionSource;
  text: string;
  language?: string;
  translated?: boolean;
  severity?: CaptionSeverity;
}): CaptionEntry {
  return {
    id: `${source}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    timestamp: new Date().toLocaleTimeString([], { hour12: false }),
    source,
    text: sanitizeCaptionText(text),
    language,
    translated,
    severity,
  };
}

export function appendCaptionHistory(history: CaptionEntry[], entry: CaptionEntry): CaptionEntry[] {
  return [...history.slice(-(MAX_CAPTION_HISTORY - 1)), entry].slice(-MAX_CAPTION_HISTORY);
}

export function detectVideoCaptionTracks(html: string): { captionsAvailable: boolean; captionTracks: Array<{ language: string; label: string; kind: string }> } {
  const matches = html.matchAll(/<track\b(?=[^>]*\bkind=['"]?(?:captions|subtitles)['"]?)[^>]*>/gi);
  const captionTracks: Array<{ language: string; label: string; kind: string }> = [];
  const seen = new Set<string>();

  for (const match of matches) {
    const tag = match[0];
    const language = /\b(?:srclang|lang)=['"]?([^'"\s>]+)/i.exec(tag)?.[1] ?? "en";
    const label = /\blabel=['"]?([^'"\s>]+)/i.exec(tag)?.[1] ?? "English";
    const kind = /\bkind=['"]?([^'"\s>]+)/i.exec(tag)?.[1] ?? "captions";
    const key = `${language}:${label}:${kind}`;
    if (seen.has(key)) continue;
    seen.add(key);
    captionTracks.push({ language, label, kind: kind.toLowerCase() });
  }

  return { captionsAvailable: captionTracks.length > 0, captionTracks };
}

export function extractPaymentStatus(text: string): { visible: boolean; status: string; paymentDetected: boolean } {
  const lower = sanitizeCaptionText(text).toLowerCase();
  if (lower.includes("payment successful") || lower.includes("paid successfully")) {
    return { visible: true, status: "successful", paymentDetected: true };
  }
  if (lower.includes("payment failed") || lower.includes("payment declined")) {
    return { visible: true, status: "failed", paymentDetected: true };
  }
  if (lower.includes("waiting for confirmation") || lower.includes("pending confirmation")) {
    return { visible: true, status: "waiting_for_confirmation", paymentDetected: true };
  }
  if (/[\w\s]*(upi|credit|net banking|cash on delivery)/i.test(lower)) {
    return { visible: true, status: "available", paymentDetected: true };
  }
  return { visible: false, status: "unknown", paymentDetected: false };
}

export function detectAccessibleStatusAnnouncements(text: string): string[] {
  const patterns = [
    "payment successful",
    "payment failed",
    "order confirmed",
    "cart updated",
    "validation error",
    "modal opened",
    "alert",
    "payment method selected",
  ];
  return patterns.filter((pattern) => new RegExp(pattern, "i").test(sanitizeCaptionText(text)));
}

export function isSensitiveCaptionText(text: string): boolean {
  return SENSITIVE_CAPTION_PATTERNS.some((pattern) => pattern.test(text));
}
