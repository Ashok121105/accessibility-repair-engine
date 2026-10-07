import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HindsightSummary, ProjectAnalysisResponse } from "../../types/api";
import ProjectAnalysisPanel from "./ProjectAnalysisPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const projectResult: ProjectAnalysisResponse = {
  project_id: "project-123",
  project_type: "html",
  framework: "Static HTML",
  language: "HTML",
  supported: true,
  analysis_status: "completed",
  explanation: "Static pages scanned without scripts or network.",
  files_analyzed: 2,
  pages_analyzed: 1,
  violations_found: 1,
  scan_timestamp: "2026-10-06T10:00:00Z",
  project_url: "https://project-project-123.invalid/",
  aggregate_scan: null,
  pages: [{
    file: "index.html",
    title: "Catalog",
    total_violations: 1,
    violations: [{
      rule_id: "image-alt",
      impact: "critical",
      wcag_criterion: "1.1.1 Non-text Content",
      wcag_level: "A",
      description: "Images need alternative text.",
      explanation: "Screen-reader users need an image description.",
      help: "Add suitable alternative text.",
      help_url: null,
      affected_node_count: 1,
      affected_elements: [{
        selector: "img.hero",
        html: '<img class="hero">',
        source_file: "index.html",
        source_line: 12,
        source_mapping_message: "Mapped by exact rendered HTML match in uploaded source.",
      }],
    }],
  }],
};

const projectHindsight: HindsightSummary = {
  status: "available",
  explanation: "Historical project scans.",
  total_scans_analyzed: 2,
  total_issues_analyzed: 2,
  recurring_issues: [{
    website: "Uploaded project",
    source_type: "project",
    project_id: "project-123",
    project_type: "html",
    rule_id: "image-alt",
    wcag_criterion: "1.1.1",
    occurrences: 2,
    previously_repaired: false,
    reappeared_after_repair: false,
    status: "RECURRING",
    likely_cause: "A repeated template is possible, not confirmed.",
    prevention_recommendation: "Require meaningful image components to provide alt text.",
  }],
  new_issues: [],
  successful_repairs: 0,
  failed_repairs: 0,
  returned_after_repair: 0,
};

function uploadResponse(onWorkflowUpdate = vi.fn()) {
  return render(
    <ProjectAnalysisPanel
      hindsight={projectHindsight}
      supportedVerificationRuleIds={[
        "image-alt",
        "input-image-alt",
        "button-name",
        "link-name",
        "label",
        "region",
        "landmark-one-main",
      ]}
      verificationSupportError=""
      onWorkflowUpdate={onWorkflowUpdate}
    />,
  );
}

describe("developer project analysis", () => {
  it("uploads a ZIP and shows detected project type, actual scan metrics, and source mapping", async () => {
    const user = userEvent.setup();
    const update = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => projectResult,
      }),
    );
    uploadResponse(update);

    await user.upload(
      screen.getByLabelText("Upload developer project ZIP"),
      new File(["archive"], "static-site.zip", { type: "application/zip" }),
    );

    expect(await screen.findAllByText("1", { selector: ".project-identity strong" })).toHaveLength(2);
    expect(screen.getByText("Static HTML")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(update).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith(
      "/api/project/analyze",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );

    await user.click(screen.getByRole("button", { name: "Violations" }));
    expect(screen.getByText("image-alt")).toBeInTheDocument();
    expect(screen.getByText("index.html:12")).toBeInTheDocument();
  });

  it("supports a project repair proposal, verification, isolated apply, and certificate metadata", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/project/analyze")) {
        return Promise.resolve({ ok: true, json: async () => projectResult });
      }
      if (url.endsWith("/api/repair/propose")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            repair_type: "add_alt",
            explanation: "Adds a concise alternative text.",
            original_html: '<img class="hero">',
            proposed_html: '<img class="hero" alt="Mountain landscape">',
            confidence: 0.91,
            reasoning_summary: "Adds only the missing attribute.",
          }),
        });
      }
      if (url.endsWith("/api/repair/verify")) {
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
            message: "Configured checks passed in the isolated sandbox.",
            checks: [{ name: "axe_rule", passed: true, message: "Rule resolved." }],
          }),
        });
      }
      if (url.endsWith("/api/repair/apply")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: "improved",
            before: { total_violations: 1, violations: [] },
            after: { total_violations: 0, violations: [] },
            resolved: [{ rule_id: "image-alt", impact: "critical", description: "Resolved.", affected_elements: [] }],
            remaining: [],
            new_violations: [],
            message: "Isolated copy was rescanned.",
            safety_label: "Applied to isolated copy — original website unchanged.",
          }),
        });
      }
      if (url.endsWith("/api/certificates")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            certificate_id: "project-certificate-1",
            issued_at: "2026-10-06T10:05:00Z",
            website: projectResult.project_url,
            scan_timestamp: projectResult.scan_timestamp,
            rule_id: "image-alt",
            wcag_criterion: "1.1.1 Non-text Content",
            wcag_level: "A",
            verification_status: "VERIFIED",
            scope: "Isolated fragment and configured checks.",
            checks: [],
            evidence: {},
            limitations: ["Not universal conformance."],
            certificate_statement: "Configured automated checks passed.",
            evidence_hash: "f".repeat(64),
            project_id: projectResult.project_id,
            project_type: projectResult.project_type,
          }),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);
    uploadResponse();

    await user.upload(
      screen.getByLabelText("Upload developer project ZIP"),
      new File(["archive"], "static-site.zip", { type: "application/zip" }),
    );
    await screen.findByText("completed");
    await user.click(screen.getByRole("button", { name: "Violations" }));
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await user.click(screen.getByRole("button", { name: "Repair Proposals" }));
    await screen.findByText("AI proposal · not verified");
    const proposalCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/api/repair/propose"));
    expect(JSON.parse(String(proposalCall?.[1]?.body))).toMatchObject({
      page_url: projectResult.project_url,
      css_selector: "img.hero",
      context: expect.stringContaining("Source file: index.html."),
    });
    await user.click(screen.getByRole("button", { name: "Verification" }));
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    expect(await screen.findByText("VERIFIED · ISOLATED SCOPE")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Apply Verified Repair" }));
    expect(await screen.findByText("Applied to isolated copy — original website unchanged.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate Certificate" }));

    expect(await screen.findByText("Evidence certificate: project-certificate-1")).toBeInTheDocument();
    const certificateCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/api/certificates"));
    expect(certificateCall).toBeDefined();
    expect(JSON.parse(String(certificateCall?.[1]?.body))).toMatchObject({
      project_id: "project-123",
      project_type: "html",
      rule_id: "image-alt",
      verification_id: "a3c64561-9180-4a81-9e37-4fa2e6093995",
    });
  });

  it("proposes and verifies a landmark repair using the scanned article evidence", async () => {
    const user = userEvent.setup();
    const targetHtml =
      "<article><h1>Community Accessibility Update</h1><p>This existing article contains the primary content and can be placed inside a main landmark without inventing or changing its content.</p></article>";
    const contextHtml = targetHtml;
    const landmarkProject: ProjectAnalysisResponse = {
      ...projectResult,
      pages: [{
        ...projectResult.pages[0],
        violations: [{
          ...projectResult.pages[0].violations[0],
          rule_id: "landmark-one-main",
          impact: "moderate",
          wcag_criterion: "1.3.1 Info and Relationships",
          description: "The page does not have a main landmark.",
          affected_elements: [{
            selector: "html",
            html: "<html lang=\"en\">",
            source_file: "index.html",
            source_line: 1,
            source_mapping_message: "Mapped to uploaded source.",
            repair_target_html: targetHtml,
            repair_target_selector: "article",
            repair_context_html: contextHtml,
          }],
        }],
      }],
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/project/analyze")) {
        return Promise.resolve({ ok: true, json: async () => landmarkProject });
      }
      if (url.endsWith("/api/repair/propose")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            repair_type: "landmark_addition",
            explanation: "Wrap the existing article in main.",
            original_html: targetHtml,
            proposed_html: `<main>${targetHtml}</main>`,
            confidence: 0.9,
            reasoning_summary: "The existing article is preserved unchanged.",
          }),
        });
      }
      if (url.endsWith("/api/repair/verify")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            verification_id: "landmark-article-verification",
            status: "verified",
            rule_id: "landmark-one-main",
            original_violation_present: true,
            repaired_violation_present: false,
            new_violations: [],
            scope_safe: true,
            message: "Configured checks passed in the isolated context.",
            checks: [{ name: "repair_resolves_violation", passed: true, message: "Resolved." }],
          }),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);
    uploadResponse();

    await user.upload(
      screen.getByLabelText("Upload developer project ZIP"),
      new File(["archive"], "landmark-demo.zip", { type: "application/zip" }),
    );
    await screen.findByText("completed");
    await user.click(screen.getByRole("button", { name: "Violations" }));
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await user.click(screen.getByRole("button", { name: "Repair Proposals" }));
    await screen.findByText("AI proposal · not verified");

    const proposalCall = fetchMock.mock.calls.find(([input]) => (
      String(input).endsWith("/api/repair/propose")
    ));
    expect(JSON.parse(String(proposalCall?.[1]?.body))).toMatchObject({
      violation_rule_id: "landmark-one-main",
      affected_html: targetHtml,
      css_selector: "article",
      context_html: contextHtml,
    });

    await user.click(screen.getByRole("button", { name: "Verification" }));
    await user.click(screen.getByRole("button", { name: "Verify Repair" }));
    expect(await screen.findByText("VERIFIED · ISOLATED SCOPE")).toBeInTheDocument();
    const verifyCall = fetchMock.mock.calls.find(([input]) => (
      String(input).endsWith("/api/repair/verify")
    ));
    expect(JSON.parse(String(verifyCall?.[1]?.body))).toMatchObject({
      rule_id: "landmark-one-main",
      original_html: targetHtml,
      selector: "article",
      context_html: contextHtml,
    });
  });

  it("blocks verification, apply, and certificates for unsupported project rules", async () => {
    const user = userEvent.setup();
    const unsupportedProject: ProjectAnalysisResponse = {
      ...projectResult,
      pages: projectResult.pages.map((page) => ({
        ...page,
        violations: page.violations.map((violation) => ({
          ...violation,
          rule_id: "heading-order",
        })),
      })),
    };
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/project/analyze")) {
        return Promise.resolve({ ok: true, json: async () => unsupportedProject });
      }
      if (String(input).endsWith("/api/repair/propose")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            repair_type: "landmark_addition",
            explanation: "Add a main landmark.",
            original_html: '<img class="hero">',
            proposed_html: '<main><img class="hero"></main>',
            confidence: 0.8,
            reasoning_summary: "Wrap existing content.",
          }),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);
    uploadResponse();

    await user.upload(
      screen.getByLabelText("Upload developer project ZIP"),
      new File(["archive"], "static-site.zip", { type: "application/zip" }),
    );
    await screen.findByText("completed");
    await user.click(screen.getByRole("button", { name: "Violations" }));
    await user.click(screen.getByRole("button", { name: "Propose Repair" }));
    await user.click(screen.getByRole("button", { name: "Repair Proposals" }));
    await screen.findByText("AI proposal · not verified");
    await user.click(screen.getByRole("button", { name: "Verification" }));

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
  });

  it("distinguishes unavailable React analysis from a zero-violation completed scan", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          ...projectResult,
          project_type: "react_vite",
          framework: "React + Vite",
          language: "TypeScript",
          supported: true,
          analysis_status: "unavailable",
          explanation: "No secure container runtime is configured.",
          pages_analyzed: 0,
          violations_found: null,
          pages: [],
          aggregate_scan: null,
        }),
      }),
    );
    uploadResponse();

    await user.upload(
      screen.getByLabelText("Upload developer project ZIP"),
      new File(["archive"], "react-project.zip", { type: "application/zip" }),
    );

    expect(await screen.findByText("React + Vite")).toBeInTheDocument();
    expect(screen.getByText("unavailable")).toBeInTheDocument();
    expect(screen.getByText("No secure container runtime is configured.")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    const violationsMetric = screen.getByText("Violations found").parentElement;
    expect(violationsMetric).toHaveTextContent("—");
  });

  it("shows project recurrence from the shared Hindsight history", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => projectResult,
      }),
    );
    uploadResponse();

    await user.upload(
      screen.getByLabelText("Upload developer project ZIP"),
      new File(["archive"], "static-site.zip", { type: "application/zip" }),
    );
    await screen.findByText("completed");
    await user.click(screen.getByRole("button", { name: "Hindsight" }));

    expect(screen.getByText("RECURRING · 2 occurrence(s)")).toBeInTheDocument();
    expect(screen.getByText(/possible, not confirmed/i)).toBeInTheDocument();
  });

  it("shows an explicit error when the project analysis request fails", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({ detail: "The uploaded archive is not a valid ZIP file." }),
      }),
    );
    uploadResponse();

    await user.upload(
      screen.getByLabelText("Upload developer project ZIP"),
      new File(["not a zip"], "broken.zip", { type: "application/zip" }),
    );

    expect(
      await screen.findByText("The uploaded archive is not a valid ZIP file."),
    ).toBeInTheDocument();
  });
});
