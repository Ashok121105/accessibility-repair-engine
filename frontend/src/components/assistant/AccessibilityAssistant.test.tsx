import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sendAgentCommand, startAgent, stopAgent } from "../../services/api";
import type {
  BrowserSpeechRecognition,
  SpeechRecognitionResultEventLike,
  SpeechRecognitionResultLike,
  BrowserSpeechSynthesis,
  SpeechSynthesisUtteranceLike,
} from "../../services/speech";
import AccessibilityAssistant from "./AccessibilityAssistant";

vi.mock("../../services/api", () => ({
  sendAgentCommand: vi.fn(),
  startAgent: vi.fn(),
  stopAgent: vi.fn().mockResolvedValue({ status: "stopped" }),
}));

const startedSession = {
  success: true,
  session_id: "session-1",
  status: "started" as const,
  message: "Accessibility Assistant browser session started.",
};

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

  emitResult(transcript: string) {
    const result: SpeechRecognitionResultLike = Object.assign(
      [{ transcript }],
      { isFinal: true, length: 1 },
    );
    this.onresult?.({ resultIndex: 0, results: [result] });
  }
}

class FakeSpeechSynthesisUtterance implements SpeechSynthesisUtteranceLike {
  lang = "";
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  constructor(public text = "") {}
}

class FakeSpeechSynthesis implements BrowserSpeechSynthesis {
  speaking = false;
  utterances: SpeechSynthesisUtteranceLike[] = [];
  speak = vi.fn((utterance: SpeechSynthesisUtteranceLike) => {
    this.utterances.push(utterance);
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

describe("AccessibilityAssistant", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("renders the assistant workspace and accessible language and mode controls", () => {
    render(<AccessibilityAssistant />);

    expect(screen.getByRole("region", { name: "Accessibility Assistant workspace" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Interaction mode" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Preferred language" })).toHaveValue("en");
    expect(screen.getByRole("textbox", { name: "Text command" })).toBeDisabled();
    const websiteInput = screen.getByRole("textbox", { name: "Flipkart website URL" });
    expect(websiteInput).toHaveAttribute("type", "url");
    expect(websiteInput).toHaveValue("https://www.flipkart.com/");
    expect(screen.getByText(/Use the Accessibility Repair Engine to scan other websites/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset Demo" })).toBeInTheDocument();
  });

  it("selects Blind Mode and displays honest voice placeholders", async () => {
    FakeSpeechRecognition.instances = [];
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));

    expect(screen.getByRole("radio", { name: /Blind Mode/ })).toBeChecked();
    expect(screen.getByRole("heading", { name: "Voice interaction" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start Voice Input/ })).toBeInTheDocument();
    expect(screen.getByText(/Automatic language detection is not enabled/)).toBeInTheDocument();
  });

  it("selects Hearing Mode and displays the live-caption placeholder and text command", async () => {
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);
    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    await user.click(screen.getByRole("radio", { name: /Hearing Mode/ }));

    expect(screen.getByRole("radio", { name: /Hearing Mode/ })).toBeChecked();
    expect(screen.getByRole("heading", { name: "Live captions" })).toBeInTheDocument();
    expect(
      screen.getByText("Live captions will appear here when audio/caption processing is enabled."),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Text command" })).toBeInTheDocument();
  });

  it.each([
    ["English", "en"],
    ["Telugu", "te"],
    ["Tamil", "ta"],
    ["Hindi", "hi"],
  ])("selects %s and reports the manual language preference", async (name, code) => {
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.selectOptions(screen.getByRole("combobox", { name: "Preferred language" }), code);

    expect(screen.getByRole("combobox", { name: "Preferred language" })).toHaveValue(code);
    expect(screen.getByRole("status", { name: "Preferred language status" })).toHaveTextContent(
      `Language: ${name} · Source: Manual`,
    );
  });

  it("allows mode and language changes during the same active browser session", async () => {
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    expect(await screen.findByText("session-1")).toBeInTheDocument();
    expect(screen.getByText("flipkart.com")).toBeInTheDocument();
    expect(screen.getByText("Website opened. Assistant session is ready.")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Preferred language" }), "ta");
    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));

    expect(screen.getByText("session-1")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Preferred language" })).toHaveValue("ta");
    expect(screen.getByRole("radio", { name: /Blind Mode/ })).toBeChecked();
    expect(screen.getByRole("status", { name: "Preferred language status" })).toHaveTextContent(
      "Language: Tamil · Source: Manual",
    );
  });

  it("preserves the selected mode while sending a command and displays the Open Flipkart response", async () => {
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "open_website",
      website: "Flipkart",
      url: "https://www.flipkart.com/",
      message: "Flipkart is open.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "Open Flipkart");
    await user.click(screen.getByRole("button", { name: "Send Command" }));

    expect(sendAgentCommand).toHaveBeenCalledWith("session-1", "Open Flipkart", {
      preferred_language: "en",
      language_locked: false,
    });
    expect(await screen.findByText("Open Flipkart")).toBeInTheDocument();
    expect((await screen.findAllByText("Flipkart is open.")).length).toBeGreaterThan(0);
    expect(screen.getByRole("radio", { name: /Blind Mode/ })).toBeChecked();
  });

  it("clears the active session when Stop Assistant succeeds", async () => {
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(stopAgent).mockResolvedValue({ status: "stopped" });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await user.click(await screen.findByRole("button", { name: "Stop Assistant" }));

    expect(stopAgent).toHaveBeenCalledWith("session-1");
    expect(screen.queryByText("session-1")).not.toBeInTheDocument();
    expect(screen.getByText("Assistant stopped.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop Assistant" })).not.toBeInTheDocument();
  });

  it("shows the authentication state returned when the browser session starts", async () => {
    vi.mocked(startAgent).mockResolvedValue({
      ...startedSession,
      authentication: { status: "SIGNED_OUT", website: "flipkart" },
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));

    expect(await screen.findByText("Signed out")).toBeInTheDocument();
  });

  it("speaks safe login handoff instructions without blocking credential field names", async () => {
    const synthesis = installSpeechSynthesis();
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "login",
      message: "Please enter your mobile number or email and password directly into the form.",
      page_url: "https://www.flipkart.com/account/login",
      details: {
        authentication: { status: "SIGNED_OUT", website: "flipkart" },
        account_fields: ["mobile_email", "password"],
      },
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "Login");
    await user.click(screen.getByRole("button", { name: "Send Command" }));

    expect((await screen.findAllByText(/Please enter your mobile number or email/)).length).toBeGreaterThan(0);
    expect(synthesis.speak).toHaveBeenCalledOnce();
    expect(screen.getByText("Signed out")).toBeInTheDocument();
  });

  it("omits conversational password values from assistant history", async () => {
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: false,
      action: "unsupported",
      message: "I can't process or repeat sensitive information.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "My password is very-secret");
    await user.click(screen.getByRole("button", { name: "Send Command" }));

    expect(await screen.findByText("Sensitive information omitted from command history.")).toBeInTheDocument();
    expect(screen.queryByText("very-secret")).not.toBeInTheDocument();
  });

  it("shows a useful error when the agent API fails", async () => {
    vi.mocked(startAgent).mockRejectedValue(new Error("Assistant backend is unavailable."));
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Assistant backend is unavailable.");
  });

  it("replaces raw technical exceptions with a clear user-facing error", async () => {
    vi.mocked(startAgent).mockRejectedValue(new Error("TypeError: Cannot read properties of undefined"));
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not start the assistant. Check the website URL and backend, then try again.",
    );
    expect(screen.queryByText(/TypeError/)).not.toBeInTheDocument();
  });

  it("resets only transient assistant demo state and stops the active browser session", async () => {
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "open_website",
      message: "Flipkart is open.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    vi.mocked(stopAgent).mockResolvedValue({ status: "stopped" });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "Open Flipkart");
    await user.click(screen.getByRole("button", { name: "Send Command" }));
    expect(await screen.findAllByText("Flipkart is open.")).not.toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Reset Demo" }));

    expect(stopAgent).toHaveBeenCalledWith("session-1");
    expect(screen.queryByText("session-1")).not.toBeInTheDocument();
    expect(screen.queryAllByText("Flipkart is open.")).toHaveLength(0);
    expect(screen.getByText("Demo reset. Saved scans and certificates are unchanged.")).toBeInTheDocument();
  });

  it("sends only the finished voice transcript through the existing command pipeline", async () => {
    FakeSpeechRecognition.instances = [];
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "open_website",
      website: "Flipkart",
      url: "https://www.flipkart.com/",
      message: "Flipkart is open.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.click(screen.getByRole("button", { name: /Start Voice Input/ }));

    const recognition = FakeSpeechRecognition.instances[0];
    expect(recognition.lang).toBe("en-IN");
    expect(screen.getByText("Listening…")).toBeInTheDocument();
    act(() => recognition.emitResult("Open Flipkart"));
    expect(sendAgentCommand).not.toHaveBeenCalled();
    act(() => recognition.onend?.());

    expect(await screen.findByText("Open Flipkart", { selector: ".assistant-voice-transcript" })).toBeInTheDocument();
    expect(sendAgentCommand).toHaveBeenCalledWith("session-1", "Open Flipkart", {
      preferred_language: "en",
      language_locked: false,
    });
    expect(await screen.findByText("Flipkart is open.")).toBeInTheDocument();
  });

  it("does not start a microphone in Hearing Mode", async () => {
    FakeSpeechRecognition.instances = [];
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    render(<AccessibilityAssistant />);

    expect(screen.getByRole("heading", { name: "Live captions" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start Voice Input/ })).not.toBeInTheDocument();
    expect(FakeSpeechRecognition.instances).toHaveLength(0);
  });

  it("explains when voice input is unsupported", async () => {
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", undefined);
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Voice input is not supported in this browser. Please use a supported browser or switch to Hearing Mode.",
    );
    expect(screen.queryByRole("button", { name: /Start Voice Input/ })).not.toBeInTheDocument();
  });

  it.each([
    ["en", "en-IN"],
    ["te", "te-IN"],
    ["ta", "ta-IN"],
    ["hi", "hi-IN"],
  ] as const)("speaks a successful Blind Mode response in %s (%s)", async (language, locale) => {
    const synthesis = installSpeechSynthesis();
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "open_website",
      website: "Flipkart",
      url: "https://www.flipkart.com/",
      message: "Flipkart is open.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    if (language !== "en") {
      await user.selectOptions(screen.getByRole("combobox", { name: "Preferred language" }), language);
    }
    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "Open Flipkart");
    await user.click(screen.getByRole("button", { name: "Send Command" }));

    expect(await screen.findByText("Flipkart is open.")).toBeInTheDocument();
    expect(synthesis.speak).toHaveBeenCalledOnce();
    expect(synthesis.utterances[0].text).toBe("Flipkart is open.");
    expect(synthesis.utterances[0].lang).toBe(locale);
    expect(screen.getByRole("status", { name: "Speech output status" })).toHaveTextContent("Assistant is speaking.");
    expect(screen.getByRole("button", { name: "Stop speaking" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Stop speaking" }));
    expect(synthesis.cancel).toHaveBeenCalled();
  });

  it("does not speak responses in Hearing Mode", async () => {
    const synthesis = installSpeechSynthesis();
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "open_website",
      website: "Flipkart",
      url: "https://www.flipkart.com/",
      message: "Flipkart is open.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "Open Flipkart");
    await user.click(screen.getByRole("button", { name: "Send Command" }));

    expect((await screen.findAllByText("Flipkart is open.")).length).toBeGreaterThan(0);
    expect(synthesis.speak).not.toHaveBeenCalled();
  });

  it("stops speech immediately when switching from Blind Mode to Hearing Mode", async () => {
    const synthesis = installSpeechSynthesis();
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "open_website",
      website: "Flipkart",
      url: "https://www.flipkart.com/",
      message: "Flipkart is open.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "Open Flipkart");
    await user.click(screen.getByRole("button", { name: "Send Command" }));
    await screen.findByText("Flipkart is open.");
    expect(synthesis.speak).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("radio", { name: /Hearing Mode/ }));
    expect(synthesis.cancel).toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Live captions" })).toBeInTheDocument();
  });

  it("does not speak empty or interim recognition text", async () => {
    const synthesis = installSpeechSynthesis();
    FakeSpeechRecognition.instances = [];
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "unsupported",
      message: "",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.click(screen.getByRole("button", { name: /Start Voice Input/ }));
    const recognition = FakeSpeechRecognition.instances[0];
    act(() => {
      const interim: SpeechRecognitionResultLike = Object.assign([{ transcript: "Open Flipkart" }], {
        isFinal: false,
        length: 1,
      });
      recognition.onresult?.({ resultIndex: 0, results: [interim] });
    });
    expect(synthesis.speak).not.toHaveBeenCalled();
    act(() => recognition.onend?.());
    expect(sendAgentCommand).not.toHaveBeenCalled();
    expect(synthesis.speak).not.toHaveBeenCalled();
  });

  it("keeps the response readable and reports unavailable TTS without crashing", async () => {
    vi.stubGlobal("speechSynthesis", undefined);
    vi.stubGlobal("SpeechSynthesisUtterance", undefined);
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "open_website",
      website: "Flipkart",
      url: "https://www.flipkart.com/",
      message: "Flipkart is open.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    expect(screen.getByText("Voice output is unavailable in this browser. Text response is still available.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "Open Flipkart");
    await user.click(screen.getByRole("button", { name: "Send Command" }));

    expect(await screen.findByText("Flipkart is open.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop speaking" })).toBeDisabled();
  });

  it("does not read aloud a response containing an OTP", async () => {
    const synthesis = installSpeechSynthesis();
    vi.mocked(startAgent).mockResolvedValue(startedSession);
    vi.mocked(sendAgentCommand).mockResolvedValue({
      success: true,
      action: "blocked",
      message: "A one-time password was requested.",
      page_url: "https://www.flipkart.com/",
      details: {},
      session_active: true,
    });
    const user = userEvent.setup();
    render(<AccessibilityAssistant />);

    await user.click(screen.getByRole("radio", { name: /Blind Mode/ }));
    await user.click(screen.getByRole("button", { name: "Start Assistant" }));
    await screen.findByText("session-1");
    await user.type(screen.getByRole("textbox", { name: "Text command" }), "Open Flipkart");
    await user.click(screen.getByRole("button", { name: "Send Command" }));

    expect(await screen.findByText("A one-time password was requested.")).toBeInTheDocument();
    expect(synthesis.speak).not.toHaveBeenCalled();
  });
});
