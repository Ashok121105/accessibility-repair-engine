import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

async function openNewScan(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("Backend connected");
  await user.click(screen.getByRole("link", { name: "New scan" }));
  expect(await screen.findByRole("heading", { name: "Scan a real website" })).toBeInTheDocument();
}

describe("dashboard", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input).endsWith("/api/scan")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              url: "https://example.com",
              final_url: "https://example.com/",
              page_title: "Example site",
              scanned_at: "2026-10-06T16:00:00Z",
              total_violations: 1,
              violations: [
                {
                  id: "image-alt",
                  rule_id: "image-alt",
                  impact: "critical",
                  severity: "critical",
                  tags: ["wcag2a", "wcag111"],
                  wcag_tags: ["wcag2a", "wcag111"],
                  wcag_criterion: "1.1.1 Non-text Content",
                  wcag_level: "A",
                  category: "Images without alternative text",
                  description: "Images must have alternative text",
                  explanation: "People using screen readers need text alternatives.",
                  help: "Add alt text to images",
                  help_url: "https://example.com/help",
                  affected_html_selectors: ["img.hero"],
                  affected_html_elements: ['<img class="hero">'],
                  css_selectors: ["img.hero"],
                  affected_node_count: 1,
                  affected_nodes: [
                    {
                      selectors: ["img.hero"],
                      html: '<img class="hero">',
                      failure_summary: "Fix the image alternative text.",
                    },
                  ],
                },
              ],
            }),
          });
        }
        if (String(input).endsWith("/api/repair/propose")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              repair_type: "add_alt_attribute",
              explanation: "Add a descriptive alternative text attribute.",
              original_html: '<img class="hero">',
              proposed_html: '<img class="hero" alt="Mountain at sunrise">',
              confidence: 0.86,
              reasoning_summary: "Only the missing alternative text is added.",
            }),
          });
        }
        if (String(input).endsWith("/api/repair/verify")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              verification_id: "a3c64561-9180-4a81-9e37-4fa2e6093995",
              status: "verified",
              rule_id: "image-alt",
              original_violation_present: true,
              repaired_violation_present: false,
              new_violations: [],
              scope_safe: true,
              message: "All configured automated sandbox checks passed. This is not a formal proof.",
              checks: [
                { name: "html_syntax", passed: true, message: "Both fragments are well formed." },
                { name: "original_violation", passed: true, message: "The requested axe rule is present before repair." },
                { name: "repair_resolves_violation", passed: true, message: "The requested axe rule is absent after repair." },
              ],
            }),
          });
        }
        if (String(input).endsWith("/api/certificates")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              certificate_id: "certificate-test-id",
              issued_at: "2026-10-06T16:01:00Z",
              website: "https://example.com/",
              scan_timestamp: "2026-10-06T16:00:00Z",
              rule_id: "image-alt",
              wcag_criterion: "1.1.1 Non-text Content",
              wcag_level: "A",
              verification_status: "VERIFIED",
              scope: "Supplied fragment only.",
              checks: [
                { name: "html_syntax", passed: true, message: "Well formed." },
                { name: "axe", passed: true, message: "Rule resolved." },
              ],
              evidence: {
                original_violation: "Images must have alternative text",
                repair_proposal: {},
                affected_selector: "img.hero",
                affected_html: '<img class="hero">',
                repaired_html: '<img class="hero" alt="Mountain at sunrise">',
                verification_result: {},
              },
              limitations: ["Not universal WCAG conformance."],
              certificate_statement: "Configured automated checks passed.",
              evidence_hash: "a".repeat(64),
            }),
          });
        }
        if (String(input).endsWith("/api/repair/apply")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: "improved",
              before: {
                total_violations: 1,
                violations: [{
                  rule_id: "image-alt",
                  impact: "critical",
                  description: "Images must have alternative text",
                  affected_elements: [{ selector: "img.hero", html: '<img class="hero">' }],
                }],
              },
              after: { total_violations: 0, violations: [] },
              resolved: [{
                rule_id: "image-alt",
                impact: "critical",
                description: "Images must have alternative text",
                affected_elements: [{ selector: "img.hero", html: '<img class="hero">' }],
              }],
              remaining: [],
              new_violations: [],
              message: "The isolated rescan resolved one axe-core violation.",
              safety_label: "Applied to isolated copy — original website unchanged.",
            }),
          });
        }
        if (String(input).endsWith("/api/dashboard/summary")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              website: null,
              state: "no_scan",
              before: null,
              after: null,
              comparison: { status: null, resolved: [], remaining: [], new: [] },
              repair: {
                proposed: 0,
                verified: 0,
                applied: 0,
                regressions_detected: 0,
                success_verified: 0,
                success_proposed: 0,
              },
              certificate: {
                generated: false,
                certificate_id: null,
                rule_id: null,
                verification_status: null,
                issued_at: null,
                evidence_hash: null,
                scope: null,
              },
              workflow: ["Scan", "Detect", "AI propose", "Verify", "Apply", "Re-scan", "Certificate", "Hindsight"].map((name) => ({
                name,
                status: "Pending",
              })),
              verification_checks: [],
            }),
          });
        }
        if (String(input).endsWith("/api/hindsight/summary")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: "insufficient_history",
              explanation: "Run additional scans to identify recurring accessibility patterns.",
              total_scans_analyzed: 0,
              total_issues_analyzed: 0,
              recurring_issues: [],
              new_issues: [],
              successful_repairs: 0,
              failed_repairs: 0,
              returned_after_repair: 0,
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: "ok",
            service: "Accessibility Repair Engine",
          }),
        });
      }),
    );
  });

  it("shows the detection-only workflow and initial scan state", async () => {
    render(<App />);

    expect(
      await screen.findByText("Backend connected"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /accessibility repair/i })).toBeInTheDocument();
    const workflow = screen.getByRole("region", { name: "Accessibility workflow" });
    expect(workflow.querySelectorAll(".step-label")).toHaveLength(7);
    expect(workflow.querySelectorAll(".step-label")[0]).toHaveTextContent("Scan");
    expect(workflow.querySelectorAll(".step-label")[1]).toHaveTextContent("Detect");
    expect(workflow.querySelectorAll(".step-label")[2]).toHaveTextContent("Propose");
    expect(workflow.querySelectorAll(".step-label")[3]).toHaveTextContent("Verify");
    expect(workflow.querySelectorAll(".step-label")[4]).toHaveTextContent("Apply");
    expect(workflow.querySelectorAll(".step-label")[5]).toHaveTextContent("Re-scan");
    expect(workflow.querySelectorAll(".step-label")[6]).toHaveTextContent("Hindsight");
    expect(screen.getByText("EVIDENCE-BASED RECURRENCE ANALYSIS")).toBeInTheDocument();
    expect(await screen.findByText("No accessibility scan has been completed yet.")).toBeInTheDocument();
  });

  it("switches all four navigation items to their matching content", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Backend connected");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: /accessibility repair/i })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "New scan" }));
    expect(screen.getByRole("link", { name: "New scan" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "Scan a real website" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: /private/i })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "Certificates" }));
    expect(screen.getByRole("link", { name: "Certificates" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "No certificates yet" })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "Scan history" }));
    expect(screen.getByRole("link", { name: "Scan history" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "No scan history yet" })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "Overview" }));
    expect(screen.getByRole("heading", { name: /accessibility repair/i })).toBeVisible();
  });

  it("restores the selected screen from the URL hash on page load", async () => {
    window.history.replaceState(null, "", "/#history");
    render(<App />);

    expect(screen.getByRole("link", { name: "Scan history" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "No scan history yet" })).toBeVisible();
  });

  it("retrieves and displays the available backend certificate", async () => {
    const fetchMock = vi.mocked(fetch);
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/api/dashboard/summary")) {
        return {
          ok: true,
          json: async () => ({
            website: null,
            state: "no_scan",
            before: null,
            after: null,
            comparison: { status: null, resolved: [], remaining: [], new: [] },
            repair: {
              proposed: 0, verified: 0, applied: 0, regressions_detected: 0,
              success_verified: 0, success_proposed: 0,
            },
            certificate: {
              generated: true, certificate_id: "stored-certificate-1",
              rule_id: "image-alt", verification_status: "VERIFIED",
              issued_at: "2026-10-06T16:00:00Z", evidence_hash: "actual-hash",
              scope: "Supplied fragment only.",
            },
            workflow: [],
            verification_checks: [],
          }),
        } as Response;
      }
      if (String(input).endsWith("/api/certificates/stored-certificate-1")) {
        return {
          ok: true,
          json: async () => ({
            certificate_id: "stored-certificate-1",
            issued_at: "2026-10-06T16:00:00Z",
            website: "https://example.com/",
            rule_id: "image-alt",
            wcag_criterion: "1.1.1 Non-text Content",
            wcag_level: "A",
            verification_status: "VERIFIED",
            checks: [{ name: "axe", passed: true, message: "The finding resolved." }],
            limitations: ["Automated checks only."],
            scope: "Supplied fragment only.",
            evidence_hash: "actual-hash",
            certificate_statement: "Backend-recorded verification checks passed.",
          }),
        } as Response;
      }
      return fallback(input, init);
    });

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Backend connected");
    await user.click(screen.getByRole("link", { name: "Certificates" }));

    expect(await screen.findByRole("heading", { name: "stored-certificate-1" })).toBeInTheDocument();
    expect(screen.getByText("1.1.1 Non-text Content · Level A")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/certificates/stored-certificate-1"))).toBe(true);
  });

  it("loads scan history from persisted Hindsight occurrence data", async () => {
    const fetchMock = vi.mocked(fetch);
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith("/api/hindsight/summary")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: "available",
            explanation: "Analysis uses persisted scan evidence.",
            total_scans_analyzed: 1,
            total_issues_analyzed: 1,
            recurring_issues: [],
            new_issues: [{
              website: "https://example.com/",
              rule_id: "image-alt",
              wcag_criterion: "1.1.1 Non-text Content",
              occurrences: 1,
              previously_repaired: false,
              reappeared_after_repair: false,
              status: "NEW",
              likely_cause: "Missing alternative text.",
              prevention_recommendation: null,
            }],
            successful_repairs: 0,
            failed_repairs: 0,
            returned_after_repair: 0,
          }),
        } as Response);
      }
      if (String(input).endsWith("/api/hindsight/issues/image-alt")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: "available",
            rule_id: "image-alt",
            occurrences: [{
              scan_id: "persisted-scan-1",
              scanned_at: "2026-10-06T16:00:00Z",
              website: "https://example.com/",
              domain: "example.com",
              rule_id: "image-alt",
              impact: "critical",
              wcag_criterion: "1.1.1 Non-text Content",
              selectors: ["img.hero"],
              verification_status: null,
              application_status: null,
              regression_detected: false,
              before_violation_count: null,
              after_violation_count: null,
              timeline: [],
            }],
          }),
        } as Response);
      }
      return fallback(input, init);
    });

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Backend connected");
    await user.click(screen.getByRole("link", { name: "Scan history" }));

    const historyPanel = screen.getByRole("region", { name: "Recorded scans" });
    expect(await within(historyPanel).findByText("persisted-scan-1")).toBeInTheDocument();
    expect(within(historyPanel).getByText("image-alt", { exact: true })).toBeInTheDocument();
    expect(within(historyPanel).getByText("img.hero")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/hindsight/issues/image-alt"))).toBe(true);
  });

  it("submits the URL and displays real-shaped violation details", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));

    expect(await screen.findByRole("heading", { name: "1 violation found" })).toBeInTheDocument();
    const scanCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/scan"));
    expect(scanCall).toBeDefined();
    expect(JSON.parse(String(scanCall?.[1]?.body))).toEqual({ url: "https://example.com" });
    expect(screen.getByText("Images must have alternative text")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText("img.hero")).toBeInTheDocument();
    expect(screen.getByText("wcag111")).toBeInTheDocument();
    expect(screen.getByText("1.1.1 Non-text Content")).toBeInTheDocument();
    expect(screen.getByText("People using screen readers need text alternatives.")).toBeInTheDocument();
    expect(screen.getAllByText("AFFECTED ELEMENTS")).toHaveLength(2);
    expect(screen.getByRole("group", { name: "Filter violations by impact" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /serious/i }));
    expect(screen.getByText("No serious impact violations in this scan.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /critical/i }));
    expect(screen.getByText("Images must have alternative text")).toBeInTheDocument();
  });

  it("shows a repair proposal and labels it not verified", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 violation found" });

    await user.click(screen.getByRole("button", { name: "Propose Repair" }));

    expect(await screen.findByText("AI PROPOSAL — NOT VERIFIED")).toBeInTheDocument();
    expect(screen.getByText('<img class="hero" alt="Mountain at sunrise">')).toBeInTheDocument();
    expect(screen.getByText("86% confidence")).toBeInTheDocument();
    expect(screen.getByText("This is a suggestion only. It has not been applied to the website.")).toBeInTheDocument();
    const fetchMock = vi.mocked(fetch);
    const repairCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/api/repair/propose"));
    expect(repairCall).toBeDefined();
    expect(JSON.parse(String(repairCall?.[1]?.body))).toMatchObject({
      violation_rule_id: "image-alt",
      css_selector: "img.hero",
      page_url: "https://example.com/",
    });
  });

  it("shows independent verification results after a proposal", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 violation found" });
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT VERIFIED");

    await user.click(screen.getByRole("button", { name: "Verify Repair" }));

    expect(await screen.findByText("✅ VERIFIED REPAIR")).toBeInTheDocument();
    expect(screen.getByText("Original violation")).toBeInTheDocument();
    expect(screen.getByText("Resolved")).toBeInTheDocument();
    expect(screen.getByText("repair resolves violation")).toBeInTheDocument();
    expect(screen.getByText("This is not a formal proof.", { exact: false })).toBeInTheDocument();
  });

  it("applies only the verified repair to an isolated copy and displays before/after findings", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 violation found" });
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✅ VERIFIED REPAIR");

    await user.click(screen.getByRole("button", { name: "Apply Verified Repair" }));

    expect(await screen.findByRole("heading", { name: "✅ Verified repair improved the isolated scan" })).toBeInTheDocument();
    expect(screen.getByText("Applied to isolated copy — original website unchanged.")).toBeInTheDocument();
    expect(screen.getByText("BEFORE — 1 violation(s)")).toBeInTheDocument();
    expect(screen.getByText("AFTER — 0 violation(s)")).toBeInTheDocument();
    expect(screen.getByText("Resolved (1)")).toBeInTheDocument();
    const applyCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/repair/apply"));
    expect(applyCall).toBeDefined();
    expect(JSON.parse(String(applyCall?.[1]?.body))).toMatchObject({
      verification_id: "a3c64561-9180-4a81-9e37-4fa2e6093995",
      rule_id: "image-alt",
      original_html: '<img class="hero">',
      proposed_html: '<img class="hero" alt="Mountain at sunrise">',
      selector: "img.hero",
    });
  });

  it("shows the apply loading state and reports an isolated rescan failure", async () => {
    let finishApply: ((response: Response) => void) | undefined;
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith("/api/repair/apply")) {
        return new Promise<Response>((resolve) => {
          finishApply = resolve;
        });
      }
      return originalImplementation!(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 violation found" });
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✅ VERIFIED REPAIR");

    await user.click(screen.getByRole("button", { name: "Apply Verified Repair" }));
    expect(screen.getByRole("button", { name: "🔄 Applying and re-scanning…" })).toBeDisabled();
    finishApply?.(
      new Response(
        JSON.stringify({ detail: "The isolated before/after accessibility rescan could not complete" }),
        { status: 502, headers: { "Content-Type": "application/json" } },
      ),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The isolated before/after accessibility rescan could not complete",
    );
  });

  it("clearly flags newly introduced violations as a regression", async () => {
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith("/api/repair/apply")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              status: "regression",
              before: { total_violations: 1, violations: [] },
              after: {
                total_violations: 1,
                violations: [{
                  rule_id: "button-name",
                  impact: "serious",
                  description: "Buttons must have discernible text.",
                  affected_elements: [{ selector: "button.submit", html: "<button></button>" }],
                }],
              },
              resolved: [],
              remaining: [],
              new_violations: [{
                rule_id: "button-name",
                impact: "serious",
                description: "Buttons must have discernible text.",
                affected_elements: [{ selector: "button.submit", html: "<button></button>" }],
              }],
              message: "The isolated rescan found newly introduced axe-core violations.",
              safety_label: "Applied to isolated copy — original website unchanged.",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return originalImplementation!(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 violation found" });
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✅ VERIFIED REPAIR");
    await user.click(screen.getByRole("button", { name: "Apply Verified Repair" }));

    const results = await screen.findByRole("region", { name: "Before and after scan results" });
    expect(results).toHaveTextContent("⚠️ Regression detected");
    expect(results).toHaveTextContent("button-name");
    expect(results).toHaveTextContent("button.submit");
  });

  it("generates and displays a verified certificate with JSON actions", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 violation found" });
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✅ VERIFIED REPAIR");

    await user.click(screen.getByRole("button", { name: "Generate Certificate" }));

    expect(await screen.findByRole("heading", { name: "✅ Verified Repair" })).toBeInTheDocument();
    expect(screen.getByText("certificate-test-id")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy certificate JSON" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeInTheDocument();
    expect(screen.getAllByText(/Not universal WCAG conformance/)).toHaveLength(2);
    const certificateCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/certificates"));
    expect(certificateCall).toBeDefined();
    expect(JSON.parse(String(certificateCall?.[1]?.body))).toMatchObject({
      rule_id: "image-alt",
      verification_id: "a3c64561-9180-4a81-9e37-4fa2e6093995",
      website: "https://example.com/",
    });
  });

  it("shows the proposal loading state and Gemini errors", async () => {
    const user = userEvent.setup();
    let finishRepair:
      | ((response: {
          ok: boolean;
          status: number;
          json: () => Promise<{ detail: string }>;
        }) => void)
      | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input).endsWith("/api/scan")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              url: "https://example.com",
              final_url: "https://example.com/",
              page_title: "Example site",
              total_violations: 1,
              violations: [
                {
                  id: "image-alt",
                  rule_id: "image-alt",
                  impact: "critical",
                  severity: "critical",
                  tags: ["wcag2a", "wcag111"],
                  wcag_tags: ["wcag2a", "wcag111"],
                  wcag_criterion: "1.1.1 Non-text Content",
                  wcag_level: "A",
                  category: "Images without alternative text",
                  description: "Images must have alternative text",
                  explanation: "People using screen readers need text alternatives.",
                  help: "Add alt text to images",
                  help_url: null,
                  affected_html_selectors: ["img.hero"],
                  affected_html_elements: ['<img class="hero">'],
                  css_selectors: ["img.hero"],
                  affected_node_count: 1,
                  affected_nodes: [{ selectors: ["img.hero"], html: '<img class="hero">', failure_summary: null }],
                },
              ],
            }),
          });
        }
        if (String(input).endsWith("/api/repair/propose")) {
          return new Promise((resolve) => {
            finishRepair = resolve;
          });
        }
        if (String(input).endsWith("/api/dashboard/summary")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              website: null,
              state: "no_scan",
              before: null,
              after: null,
              comparison: { status: null, resolved: [], remaining: [], new: [] },
              repair: {
                proposed: 0, verified: 0, applied: 0, regressions_detected: 0,
                success_verified: 0, success_proposed: 0,
              },
              certificate: {
                generated: false, certificate_id: null, rule_id: null,
                verification_status: null, issued_at: null, evidence_hash: null, scope: null,
              },
              workflow: [],
              verification_checks: [],
            }),
          });
        }
        if (String(input).endsWith("/api/hindsight/summary")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: "insufficient_history",
              explanation: "Run additional scans to identify recurring accessibility patterns.",
              total_scans_analyzed: 0,
              total_issues_analyzed: 0,
              recurring_issues: [],
              new_issues: [],
              successful_repairs: 0,
              failed_repairs: 0,
              returned_after_repair: 0,
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: "ok", service: "Accessibility Repair Engine" }),
        });
      }),
    );
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 violation found" });

    await user.click(screen.getByRole("button", { name: "Propose Repair" }));

    expect(screen.getByRole("button", { name: "Generating proposal…" })).toBeDisabled();
    finishRepair?.({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Gemini is unavailable because GEMINI_API_KEY is not configured" }),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("GEMINI_API_KEY is not configured");
  });

  it("shows scanner errors returned by the API", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input).endsWith("/api/scan")) {
          return Promise.resolve({
            ok: false,
            status: 502,
            json: async () => ({ detail: "The website could not be reached" }),
          });
        }
        if (String(input).endsWith("/api/dashboard/summary")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              website: null,
              state: "no_scan",
              before: null,
              after: null,
              comparison: { status: null, resolved: [], remaining: [], new: [] },
              repair: {
                proposed: 0, verified: 0, applied: 0, regressions_detected: 0,
                success_verified: 0, success_proposed: 0,
              },
              certificate: {
                generated: false, certificate_id: null, rule_id: null,
                verification_status: null, issued_at: null, evidence_hash: null, scope: null,
              },
              workflow: [],
              verification_checks: [],
            }),
          });
        }
        if (String(input).endsWith("/api/hindsight/summary")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              status: "insufficient_history",
              explanation: "Run additional scans to identify recurring accessibility patterns.",
              total_scans_analyzed: 0,
              total_issues_analyzed: 0,
              recurring_issues: [],
              new_issues: [],
              successful_repairs: 0,
              failed_repairs: 0,
              returned_after_repair: 0,
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: "ok",
            service: "Accessibility Repair Engine",
          }),
        });
      }),
    );
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: /private/i }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The website could not be reached",
    );
  });

  it("shows an explicit error when the backend cannot be reached", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network unavailable")),
    );

    render(<App />);

    expect(await screen.findByText("Start the API and refresh to retry.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Backend unavailable")).toBeInTheDocument();
  });
});
