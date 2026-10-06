import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AccessibilityCertificate,
  DashboardSummary,
  HindsightSummary,
} from "../../types/api";
import DashboardPanel from "./DashboardPanel";

afterEach(cleanup);

const emptySummary: DashboardSummary = {
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
  workflow: ["Scan", "Detect", "AI propose", "Verify", "Apply", "Re-scan", "Certificate", "Hindsight"].map(
    (name) => ({ name, status: "Pending" }),
  ),
  verification_checks: [],
};

const appliedSummary: DashboardSummary = {
  ...emptySummary,
  website: "https://example.com/",
  state: "applied",
  before: {
    total_violations: 2,
    critical: 1,
    serious: 1,
    moderate: 0,
    minor: 0,
    other: 0,
    score: 70,
    score_explanation: "Transparent test calculation.",
  },
  after: {
    total_violations: 1,
    critical: 0,
    serious: 1,
    moderate: 0,
    minor: 0,
    other: 0,
    score: 90,
    score_explanation: "Transparent test calculation.",
  },
  comparison: {
    status: "improved",
    resolved: [{
      rule_id: "image-alt",
      impact: "critical",
      wcag_criterion: "1.1.1 Non-text Content",
      description: "Images need alternative text.",
      affected_elements: [{ selector: "img.hero", html: '<img class="hero">' }],
    }],
    remaining: [{
      rule_id: "button-name",
      impact: "serious",
      wcag_criterion: "4.1.2 Name, Role, Value",
      description: "Buttons need discernible names.",
      affected_elements: [{ selector: "button.submit", html: "<button></button>" }],
    }],
    new: [],
  },
  repair: {
    proposed: 2,
    verified: 1,
    applied: 1,
    regressions_detected: 0,
    success_verified: 1,
    success_proposed: 2,
  },
  certificate: {
    generated: true,
    certificate_id: "certificate-123",
    rule_id: "image-alt",
    verification_status: "VERIFIED",
    issued_at: "2026-10-06T12:00:00Z",
    evidence_hash: "a".repeat(64),
    scope: "Supplied fragment and configured checks.",
  },
  workflow: ["Scan", "Detect", "AI propose", "Verify", "Apply", "Re-scan", "Certificate", "Hindsight"].map(
    (name, index) => ({ name, status: index <= 7 ? "Completed" : "Pending" }),
  ),
};

const certificate: AccessibilityCertificate = {
  certificate_id: "certificate-123",
  issued_at: "2026-10-06T12:00:00Z",
  website: "https://example.com/",
  scan_timestamp: "2026-10-06T11:00:00Z",
  rule_id: "image-alt",
  wcag_criterion: "1.1.1 Non-text Content",
  wcag_level: "A",
  verification_status: "VERIFIED",
  scope: "Supplied fragment and configured checks.",
  checks: [],
  evidence: {
    original_violation: "Image missing alt.",
    repair_proposal: {
      repair_type: "add_alt",
      explanation: "Adds alternative text.",
      original_html: '<img class="hero">',
      proposed_html: '<img class="hero" alt="Landscape">',
      confidence: 0.9,
      reasoning_summary: "Small scoped change.",
    },
    affected_selector: "img.hero",
    affected_html: '<img class="hero">',
    repaired_html: '<img class="hero" alt="Landscape">',
    verification_result: {
      verification_id: "verify-123",
      status: "verified",
      rule_id: "image-alt",
      original_violation_present: true,
      repaired_violation_present: false,
      new_violations: [],
      scope_safe: true,
      message: "Verified.",
      checks: [],
    },
  },
  limitations: ["Not universal WCAG conformance."],
  certificate_statement: "Configured checks passed in an isolated test.",
  evidence_hash: "a".repeat(64),
};

const hindsightSummary: HindsightSummary = {
  status: "insufficient_history",
  explanation: "Run additional scans to identify recurring accessibility patterns.",
  total_scans_analyzed: 0,
  total_issues_analyzed: 0,
  recurring_issues: [],
  new_issues: [],
  successful_repairs: 0,
  failed_repairs: 0,
  returned_after_repair: 0,
};

function renderDashboard(
  summary: DashboardSummary | null,
  onViewCertificate = vi.fn(),
  loadedCertificate: AccessibilityCertificate | null = null,
) {
  return render(
    <DashboardPanel
      summary={summary}
      error=""
      isLoading={false}
      certificate={loadedCertificate}
      certificateError=""
      isCertificateLoading={false}
      hindsightSummary={hindsightSummary}
      hindsightError=""
      isHindsightLoading={false}
      onRefresh={vi.fn()}
      onViewCertificate={onViewCertificate}
    />,
  );
}

describe("evidence dashboard", () => {
  it("shows the explicit no-scan empty state", () => {
    renderDashboard(emptySummary);
    expect(screen.getByText("No accessibility scan has been completed yet.")).toBeInTheDocument();
  });

  it("shows scan-only state and actual zero count as distinct from missing data", () => {
    renderDashboard({
      ...emptySummary,
      state: "scan_only",
      before: {
        total_violations: 0,
        critical: 0,
        serious: 0,
        moderate: 0,
        minor: 0,
        other: 0,
        score: 100,
        score_explanation: "No violations detected.",
      },
    });
    expect(screen.getByText("Scan completed. No verified repair comparison is available yet.")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("No detected violations from the supported scan/rules in this scan.")).toBeInTheDocument();
    expect(screen.getByText("No completed repair comparison yet.")).toBeInTheDocument();
  });

  it("renders comparison metrics, real violation breakdowns, summary, timeline, and charts", async () => {
    renderDashboard(appliedSummary);
    expect(screen.getByText("70")).toBeInTheDocument();
    expect(screen.getByText("90")).toBeInTheDocument();
    expect(screen.getAllByText("Critical").length).toBeGreaterThan(0);
    expect(screen.getByText("Resolved violations")).toBeInTheDocument();
    expect(screen.getByText("img.hero")).toBeInTheDocument();
    expect(screen.getByText("button.submit")).toBeInTheDocument();
    expect(screen.getByText("Repairs proposed")).toBeInTheDocument();
    expect(screen.getByText("1 verified / 2 proposed")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Repair workflow timeline" })).toBeInTheDocument();
    expect(screen.getByText("Hindsight")).toBeInTheDocument();
    expect(screen.getByText("Loading actual scan charts…")).toBeInTheDocument();
  });

  it("shows verified-not-applied state and certificate retrieval action", async () => {
    const onView = vi.fn();
    const user = userEvent.setup();
    renderDashboard(
      {
        ...appliedSummary,
        state: "verified_not_applied",
        after: null,
        certificate: {
          ...appliedSummary.certificate,
          generated: false,
          certificate_id: null,
          verification_status: null,
        },
      },
      onView,
    );
    expect(screen.getByText("Repair verified. Apply the verified repair to generate a before/after comparison.")).toBeInTheDocument();
    expect(screen.getByText("NOT GENERATED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View Certificate" })).not.toBeInTheDocument();

    renderDashboard(appliedSummary, onView, certificate);
    await user.click(screen.getByRole("button", { name: "View Certificate" }));
    expect(onView).toHaveBeenCalledOnce();
    expect(screen.getAllByText("certificate-123").length).toBeGreaterThan(0);
    expect(screen.getByText(certificate.certificate_statement)).toBeInTheDocument();
    expect(screen.getAllByText("a".repeat(64)).length).toBeGreaterThan(0);
    expect(certificate.verification_status).toBe("VERIFIED");
  });
});
