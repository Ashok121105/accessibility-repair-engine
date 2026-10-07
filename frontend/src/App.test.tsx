import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

async function openNewScan(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("Backend connected");
  await user.click(screen.getByRole("link", { name: "New scan" }));
  expect(await screen.findByRole("heading", { name: "Accessibility Repair Engine" })).toBeInTheDocument();
}

async function openIssueDetails(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "View Details" }));
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
        if (String(input).endsWith("/api/repair/verification-support")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              rule_ids: [
                "image-alt",
                "input-image-alt",
                "button-name",
                "link-name",
                "label",
                "region",
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
        if (String(input).endsWith("/api/hindsight/websites")) {
          return Promise.resolve({ ok: true, json: async () => [] });
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
    expect(screen.getByRole("heading", { level: 1, name: /accessibility repair/i })).toBeInTheDocument();
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

  it("offers separate scanner and assistant journeys from the overview", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Backend connected");

    expect(screen.getByRole("heading", { name: "Accessibility Repair Engine" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Accessibility Assistant" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /Start a website scan/ }));
    expect(screen.getByRole("heading", { name: "Accessibility Repair Engine" })).toBeVisible();
    await user.click(screen.getByRole("link", { name: "Overview" }));
    await user.click(screen.getByRole("link", { name: /Open the Accessibility Assistant/ }));
    expect(screen.getByRole("heading", { name: "Accessibility Assistant" })).toBeVisible();
  });

  it("switches all five navigation items to their matching content", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Backend connected");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { level: 1, name: /accessibility repair/i })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "New scan" }));
    expect(screen.getByRole("link", { name: "New scan" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "Accessibility Repair Engine" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Website URL or Website Name" })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "Certificates" }));
    expect(screen.getByRole("link", { name: "Certificates" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "No certificates yet" })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "Scan history" }));
    expect(screen.getByRole("link", { name: "Scan history" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "No scan history yet" })).toBeVisible();
    expect(await screen.findByRole("heading", { name: "No website scan history yet" })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "Overview" }));
    expect(screen.getByRole("heading", { level: 1, name: /accessibility repair/i })).toBeVisible();

    await user.click(screen.getByRole("link", { name: "Accessibility Assistant" }));
    expect(screen.getByRole("link", { name: "Accessibility Assistant" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "Accessibility Assistant" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Accessibility Assistant workspace" })).toBeVisible();
  });

  it("restores the selected screen from the URL hash on page load", async () => {
    window.history.replaceState(null, "", "/#history");
    render(<App />);

    expect(screen.getByRole("link", { name: "Scan history" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "No scan history yet" })).toBeVisible();
  });

  it("restores the Accessibility Assistant route after a page refresh", async () => {
    window.history.replaceState(null, "", "/#assistant");
    render(<App />);

    expect(screen.getByRole("link", { name: "Accessibility Assistant" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: "Accessibility Assistant" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Accessibility Assistant workspace" })).toBeVisible();
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
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));

    expect(await screen.findByRole("heading", { name: "1 Issue Found" })).toBeInTheDocument();
    const scanCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/scan"));
    expect(scanCall).toBeDefined();
    expect(JSON.parse(String(scanCall?.[1]?.body))).toEqual({ url: "https://example.com" });
    expect(screen.getByText("Images must have alternative text")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Problems Found/ })).toBeInTheDocument();
    expect(screen.getByText("1 affected element")).toBeInTheDocument();
    await openIssueDetails(user);
    const detailPanel = screen.getByRole("region", { name: "Details for issue 1" });
    expect(within(detailPanel).getAllByText("img.hero")).toHaveLength(2);
    expect(within(detailPanel).getByText(/wcag111/)).toBeInTheDocument();
    expect(within(detailPanel).getByText(/WCAG 1\.1\.1 Non-text Content/)).toBeInTheDocument();
    expect(within(detailPanel).getByText("People using screen readers need text alternatives.")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Filter violations by impact" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /serious/i }));
    expect(screen.getByText("No serious impact violations in this scan.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /critical/i }));
    expect(screen.getByText("Images must have alternative text")).toBeInTheDocument();
  });

  it("announces scan progress and advances the pipeline only after scan evidence returns", async () => {
    let finishScan: ((response: Response) => void) | undefined;
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith("/api/scan")) {
        return new Promise<Response>((resolve) => {
          finishScan = resolve;
        });
      }
      return originalImplementation!(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "Flipkart");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));

    expect(screen.getByRole("heading", { name: "Scanning website..." })).toBeInTheDocument();
    expect(screen.getByText("Running accessibility checks")).toBeInTheDocument();
    expect(screen.getAllByText("Waiting for scan result")).toHaveLength(2);
    const pipeline = screen.getByRole("region", { name: "Scan and repair pipeline" });
    expect(within(pipeline).getByText("SCAN").closest("li")).toHaveClass("active");
    expect(within(pipeline).getByText("DETECT").closest("li")).toHaveClass("not-started");

    finishScan?.(new Response(JSON.stringify({
      url: "https://www.flipkart.com/",
      final_url: "https://www.flipkart.com/",
      page_title: "Flipkart",
      scanned_at: "2026-10-06T16:00:00Z",
      total_violations: 0,
      violations: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    expect(await screen.findByRole("heading", { name: /No supported accessibility violations detected/ })).toBeInTheDocument();
    expect(within(pipeline).getByText("SCAN").closest("li")).toHaveClass("completed");
    expect(within(pipeline).getByText("DETECT").closest("li")).toHaveClass("completed");
    const scanCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/api/scan"));
    expect(JSON.parse(String(scanCall?.[1]?.body))).toEqual({ url: "Flipkart" });
  });

  it("shows actual severity totals and WCAG-unavailable fallback with keyboard-operable details", async () => {
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (!String(input).endsWith("/api/scan")) return originalImplementation(input, init);
      const response = await originalImplementation(input, init);
      const payload = await response.json();
      const firstViolation = payload.violations[0];
      const cloneViolation = (id: string, impact: string) => ({
        ...firstViolation,
        id,
        rule_id: id,
        impact,
        severity: impact,
        wcag_criterion: "WCAG mapping unavailable",
        wcag_level: "WCAG mapping unavailable",
        affected_node_count: 2,
        affected_nodes: [],
        css_selectors: [],
        affected_html_selectors: [],
      });
      payload.total_violations = 3;
      payload.violations = [
        firstViolation,
        cloneViolation("button-name", "serious"),
        cloneViolation("color-contrast", "moderate"),
      ];
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "3 Issues Found" });

    expect(screen.getByText("CRITICAL").closest("article")).toHaveTextContent("1");
    expect(screen.getByText("SERIOUS").closest("article")).toHaveTextContent("1");
    expect(screen.getByText("MODERATE").closest("article")).toHaveTextContent("1");
    const viewDetails = screen.getAllByRole("button", { name: "View Details" })[1];
    viewDetails.focus();
    await user.keyboard("{Enter}");
    expect(viewDetails).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("WCAG mapping unavailable").length).toBeGreaterThan(1);
    expect(screen.getByRole("heading", { name: "AI Repair" })).toBeInTheDocument();
  });

  it.each([
    ["rejected", "✕ REJECTED", "The proposed repair did not pass verification."],
    ["verification_failed", "⚠ VERIFICATION FAILED", "The repair could not be safely verified."],
  ] as const)("presents a %s verification response without claiming success", async (status, heading, explanation) => {
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith("/api/repair/verify")) {
        return Promise.resolve(new Response(JSON.stringify({
          verification_id: "verification-test-id",
          status,
          rule_id: "image-alt",
          original_violation_present: true,
          repaired_violation_present: true,
          new_violations: [],
          scope_safe: true,
          message: "The backend returned a non-verified outcome.",
          checks: [{ name: "repair_resolves_violation", passed: false, message: "The original finding remains." }],
        }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      return originalImplementation(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    expect(screen.getByRole("link", { name: /Open the Accessibility Assistant/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review website history" })).toBeInTheDocument();
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));

    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByText(explanation, { exact: false })).toBeInTheDocument();
    const pipeline = screen.getByRole("region", { name: "Scan and repair pipeline" });
    expect(within(pipeline).getByText("VERIFY").closest("li")).toHaveClass("completed");
    expect(within(pipeline).getByText("CERTIFY").closest("li")).toHaveClass("not-started");
  });

  it("shows a repair proposal and labels it not verified", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });

    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));

    expect(await screen.findByText("AI PROPOSAL — NOT YET VERIFIED")).toBeInTheDocument();
    expect(screen.getByText('<img class="hero" alt="Mountain at sunrise">')).toBeInTheDocument();
    expect(screen.getByText("Repair type")).toBeInTheDocument();
    expect(screen.getByText("Rationale")).toBeInTheDocument();
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

  it("blocks a region proposal when the scan has no safe container evidence", async () => {
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/api/scan")) {
        const response = await originalImplementation(input, init);
        const payload = await response.json();
        payload.violations[0] = {
          ...payload.violations[0],
          id: "region",
          rule_id: "region",
          description: "Some page content is not contained by landmarks.",
          affected_nodes: [{
            selectors: ['p[lang="en"]'],
            html: '<p lang="en">Some unlandmarked content from the scan.</p>',
          }],
        };
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return originalImplementation(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This scan did not identify one safe content container. Run a new scan to refresh landmark evidence; no proposal was requested.",
    );
    expect(fetchMock.mock.calls.some(([input]) => (
      String(input).endsWith("/api/repair/propose")
    ))).toBe(false);
  });

  it("sends the scanner-selected region container instead of an affected paragraph", async () => {
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation()!;
    const targetHtml =
      '<div class="translation-content"><h2>Translations</h2><p lang="en">Existing English text for visitors.</p></div>';
    const contextHtml =
      `<header><h2>Site name</h2></header><section class="article-wrapper">${targetHtml}</section><footer>Contact</footer>`;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/api/scan")) {
        const response = await originalImplementation(input, init);
        const payload = await response.json();
        payload.violations[0] = {
          ...payload.violations[0],
          id: "region",
          rule_id: "region",
          description: "Some page content is not contained by landmarks.",
          affected_nodes: [{
            selectors: ['p[lang="en"]'],
            html: '<p lang="en">Existing English text for visitors.</p>',
            repair_target_html: targetHtml,
            repair_target_selector: "div.translation-content",
            repair_context_html: contextHtml,
          }],
        };
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return originalImplementation(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");

    const repairCall = fetchMock.mock.calls.find(([input]) => (
      String(input).endsWith("/api/repair/propose")
    ));
    expect(JSON.parse(String(repairCall?.[1]?.body))).toMatchObject({
      violation_rule_id: "region",
      affected_html: targetHtml,
      css_selector: "div.translation-content",
      context_html: contextHtml,
    });
  });

  it("shows independent verification results after a proposal", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");

    expect(screen.getByRole("button", { name: "Verify Repair" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));

    expect(await screen.findByText("✓ VERIFIED")).toBeInTheDocument();
    expect(screen.getByText("Original violation")).toBeInTheDocument();
    expect(screen.getByText("Original violation: resolved")).toBeInTheDocument();
    expect(screen.getByText("repair resolves violation")).toBeInTheDocument();
    expect(screen.getByText("This is not a formal proof.", { exact: false })).toBeInTheDocument();
    const verifyCall = vi.mocked(fetch).mock.calls.find(([input]) => (
      String(input).endsWith("/api/repair/verify")
    ));
    expect(verifyCall).toBeDefined();
    expect(JSON.parse(String(verifyCall?.[1]?.body))).toMatchObject({
      rule_id: "image-alt",
      wcag_criterion: "1.1.1 Non-text Content",
    });
  });

  it("verifies landmark-one-main with the scanner-selected page target and context", async () => {
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation()!;
    const targetHtml =
      '<div id="main-content"><h1>Welcome</h1><p>This is meaningful existing page content for visitors.</p></div>';
    const contextHtml =
      `<header><h2>Example site</h2></header>${targetHtml}<footer>Contact information</footer>`;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/scan")) {
        const response = await originalImplementation(input, init);
        const payload = await response.json();
        payload.violations[0] = {
          ...payload.violations[0],
          id: "landmark-one-main",
          rule_id: "landmark-one-main",
          description: "The page does not have a main landmark.",
          affected_nodes: [{
            selectors: ["html"],
            html: "<html>",
            repair_target_html: targetHtml,
            repair_target_selector: "#main-content",
            repair_context_html: contextHtml,
          }],
        };
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/api/repair/verification-support")) {
        const response = await originalImplementation(input, init);
        const payload = await response.json();
        payload.rule_ids.push("landmark-one-main");
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/api/repair/propose")) {
        return new Response(JSON.stringify({
          repair_type: "landmark_addition",
          explanation: "Wrap the existing main content container.",
          original_html: targetHtml,
          proposed_html: `<main>${targetHtml}</main>`,
          confidence: 0.9,
          reasoning_summary: "Only the existing content container is wrapped.",
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("/api/repair/verify")) {
        return new Response(JSON.stringify({
          verification_id: "landmark-verification-id",
          status: "verified",
          rule_id: "landmark-one-main",
          original_violation_present: true,
          repaired_violation_present: false,
          new_violations: [],
          scope_safe: true,
          message: "All configured automated sandbox checks passed.",
          checks: [{ name: "repair_resolves_violation", passed: true, message: "Resolved." }],
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return originalImplementation(input, init);
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");
    expect(screen.getByRole("button", { name: "Verify Repair" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Verify Repair" }));

    expect(await screen.findByText("✓ VERIFIED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply Verified Repair" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Generate Certificate" })).toBeEnabled();
    const verifyCall = fetchMock.mock.calls.find(([input]) => (
      String(input).endsWith("/api/repair/verify")
    ));
    expect(verifyCall).toBeDefined();
    expect(JSON.parse(String(verifyCall?.[1]?.body))).toMatchObject({
      rule_id: "landmark-one-main",
      selector: "#main-content",
      context_html: contextHtml,
    });
  });

  it("disables verification and explains unsupported rules without sending a request", async () => {
    const fetchMock = vi.mocked(fetch);
    const originalImplementation = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (!String(input).endsWith("/api/scan")) {
        return originalImplementation(input, init);
      }
      const response = await originalImplementation(input, init);
      const payload = await response.json();
      payload.violations[0] = {
        ...payload.violations[0],
        id: "landmark-one-main",
        rule_id: "landmark-one-main",
      };
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");

    expect(screen.getByRole("button", { name: "Verify Repair" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Automated verification is not currently supported for this accessibility rule. The issue can still be reviewed, but it cannot be safely verified or applied automatically.",
    );
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));

    expect(fetchMock.mock.calls.some(([input]) => (
      String(input).endsWith("/api/repair/verify")
    ))).toBe(false);
    expect(screen.queryByRole("button", { name: "Apply Verified Repair" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate Certificate" })).not.toBeInTheDocument();
    expect(screen.queryByText("⚠ VERIFICATION FAILED")).not.toBeInTheDocument();
    expect(screen.queryByText("Unsafe / unconfirmed")).not.toBeInTheDocument();
    expect(screen.queryByText("Inconclusive")).not.toBeInTheDocument();
    expect(screen.getByText("AI PROPOSAL — NOT YET VERIFIED")).toBeInTheDocument();
  });

  it("applies only the verified repair to an isolated copy and displays before/after findings", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✓ VERIFIED");

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
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✓ VERIFIED");

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
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✓ VERIFIED");
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
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✓ VERIFIED");

    await user.click(screen.getByRole("button", { name: "Generate Certificate" }));

    expect(await screen.findByRole("heading", { name: "📜 Verified Accessibility Certificate" })).toBeInTheDocument();
    expect(screen.getByText("certificate-test-id")).toBeInTheDocument();
    expect(screen.getByText(`aaaaaaaaaaaa…${"a".repeat(8)}`)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View Certificate" }));
    expect(screen.getByRole("button", { name: "Copy certificate JSON" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeInTheDocument();
    expect(screen.getAllByText(/Not universal WCAG conformance/)).toHaveLength(1);
    const certificateCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/certificates"));
    expect(certificateCall).toBeDefined();
    expect(JSON.parse(String(certificateCall?.[1]?.body))).toMatchObject({
      rule_id: "image-alt",
      verification_id: "a3c64561-9180-4a81-9e37-4fa2e6093995",
      website: "https://example.com/",
      affected_selector: "img.hero",
    });
  });

  it("certifies the evidence-backed selector used for a landmark repair", async () => {
    const fetchMock = vi.mocked(fetch);
    const defaultFetch = fetchMock.getMockImplementation();
    const jsonResponse = (body: unknown) =>
      new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
      });
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith("/api/scan")) {
        return Promise.resolve(
          jsonResponse({
            url: "https://example.com",
            final_url: "https://example.com/",
            page_title: "Example site",
            scanned_at: "2026-10-06T16:00:00Z",
            total_violations: 1,
            violations: [
              {
                id: "landmark-one-main",
                rule_id: "landmark-one-main",
                impact: "moderate",
                severity: "moderate",
                tags: ["best-practice"],
                wcag_tags: [],
                wcag_criterion: "WCAG mapping unavailable",
                wcag_level: "WCAG mapping unavailable",
                category: "Landmarks",
                description: "Document must have one main landmark",
                explanation: "A main landmark is needed.",
                help: "Add one main landmark.",
                affected_html_selectors: ["html"],
                affected_html_elements: ["<html>"],
                css_selectors: ["html"],
                affected_node_count: 1,
                affected_nodes: [
                  {
                    selectors: ["html"],
                    html: "<html><body><article id='main-content'><h1>News</h1></article></body></html>",
                    failure_summary: "No main landmark exists.",
                    repair_target_html: '<article id="main-content"><h1>News</h1></article>',
                    repair_target_selector: "#main-content",
                    repair_context_html: '<body><article id="main-content"><h1>News</h1></article></body>',
                  },
                ],
              },
            ],
          }),
        );
      }
      if (String(input).endsWith("/api/repair/verification-support")) {
        return Promise.resolve(jsonResponse({ rule_ids: ["landmark-one-main"] }));
      }
      if (String(input).endsWith("/api/repair/propose")) {
        return Promise.resolve(
          jsonResponse({
            repair_type: "add_main_landmark",
            explanation: "Use the existing article as the main landmark.",
            original_html: '<article id="main-content"><h1>News</h1></article>',
            proposed_html: '<main id="main-content"><h1>News</h1></main>',
            confidence: 0.9,
            reasoning_summary: "The existing article content is retained.",
          }),
        );
      }
      if (String(input).endsWith("/api/repair/verify")) {
        return Promise.resolve(
          jsonResponse({
            verification_id: "a3c64561-9180-4a81-9e37-4fa2e6093995",
            status: "verified",
            rule_id: "landmark-one-main",
            original_violation_present: true,
            repaired_violation_present: false,
            new_violations: [],
            scope_safe: true,
            message: "All configured automated sandbox checks passed.",
            checks: [{ name: "axe", passed: true, message: "Rule resolved." }],
          }),
        );
      }
      return defaultFetch!(input, init);
    });

    const user = userEvent.setup();
    render(<App />);
    await openNewScan(user);
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await screen.findByText("AI PROPOSAL — NOT YET VERIFIED");
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    await screen.findByText("✓ VERIFIED");
    await user.click(screen.getByRole("button", { name: "Generate Certificate" }));
    await screen.findByRole("heading", { name: "📜 Verified Accessibility Certificate" });

    const certificateCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/api/certificates"));
    expect(certificateCall).toBeDefined();
    expect(JSON.parse(String(certificateCall?.[1]?.body))).toMatchObject({
      rule_id: "landmark-one-main",
      affected_selector: "#main-content",
      affected_html: '<article id="main-content"><h1>News</h1></article>',
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
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
    await user.click(screen.getByRole("button", { name: /^scan website$/i }));
    await screen.findByRole("heading", { name: "1 Issue Found" });
    await openIssueDetails(user);
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
    await user.type(screen.getByRole("textbox", { name: "Website URL or Website Name" }), "https://example.com");
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

  it("recovers from a transient startup fetch failure without requiring a refresh", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));

    render(<App />);

    expect(await screen.findByText("Backend connected", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByText("Backend unavailable")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/api/health"))).toHaveLength(2);
  });
});
