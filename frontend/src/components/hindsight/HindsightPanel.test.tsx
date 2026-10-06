import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HindsightIssueHistory, HindsightSummary } from "../../types/api";
import HindsightPanel from "./HindsightPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const issue = {
  website: "example.com",
  rule_id: "image-alt",
  wcag_criterion: "1.1.1 Non-text Content",
  occurrences: 2,
  previously_repaired: true,
  reappeared_after_repair: true,
  status: "RECURRING_AFTER_REPAIR" as const,
  likely_cause: "A repeated component is a possible cause, not a confirmed root cause.",
  prevention_recommendation: "Require meaningful image components to provide alternative text.",
};

const summary: HindsightSummary = {
  status: "available",
  explanation: "Analysis uses previously recorded scan and workflow evidence.",
  total_scans_analyzed: 3,
  total_issues_analyzed: 4,
  recurring_issues: [issue],
  new_issues: [],
  successful_repairs: 1,
  failed_repairs: 1,
  returned_after_repair: 1,
};

const history: HindsightIssueHistory = {
  status: "available",
  rule_id: "image-alt",
  occurrences: [
    {
      scan_id: "scan-one",
      scanned_at: "2026-10-06T10:00:00Z",
      website: "https://example.com/",
      domain: "example.com",
      rule_id: "image-alt",
      impact: "critical",
      wcag_criterion: "1.1.1 Non-text Content",
      selectors: ["img.hero"],
      verification_status: "verified",
      application_status: "improved",
      regression_detected: false,
      before_violation_count: 1,
      after_violation_count: 0,
      timeline: [
        {
          stage: "detection",
          status: "detected",
          occurred_at: "2026-10-06T10:00:00Z",
          message: "image-alt was detected.",
        },
        {
          stage: "rescan",
          status: "resolved",
          occurred_at: "2026-10-06T10:02:00Z",
          message: "Isolated axe scan resolved it.",
        },
      ],
    },
  ],
};

function renderPanel(data: HindsightSummary | null) {
  render(<HindsightPanel summary={data} error="" isLoading={false} />);
}

describe("Accessibility Hindsight panel", () => {
  it("shows the evidence-based empty state", () => {
    renderPanel({
      status: "insufficient_history",
      explanation: "Run additional scans to identify recurring accessibility patterns.",
      total_scans_analyzed: 0,
      total_issues_analyzed: 0,
      recurring_issues: [],
      new_issues: [],
      successful_repairs: 0,
      failed_repairs: 0,
      returned_after_repair: 0,
    });

    expect(screen.getByText("Not enough historical data yet.")).toBeInTheDocument();
    expect(screen.getByText(/does not confirm root cause or guarantee prevention/i)).toBeInTheDocument();
  });

  it("renders historical summary, recurrence status, recommendation, and hypothesis", () => {
    renderPanel(summary);

    expect(screen.getByText("Accessibility Hindsight")).toBeInTheDocument();
    expect(screen.getByText("Scans analyzed")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("RECURRING AFTER REPAIR")).toBeInTheDocument();
    expect(screen.getByText(/possible cause, not a confirmed root cause/i)).toBeInTheDocument();
    expect(screen.getByText(issue.prevention_recommendation)).toBeInTheDocument();
    expect(screen.getByText("Failed or unresolved repair attempts")).toBeInTheDocument();
  });

  it("loads and displays the selected rule's event timeline", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => history,
      }),
    );
    renderPanel(summary);

    await user.click(screen.getByRole("button", { name: "View issue history" }));

    expect(await screen.findByRole("region", { name: "image-alt issue history" })).toBeInTheDocument();
    expect(screen.getByText("Scan #1")).toBeInTheDocument();
    expect(screen.getByText("rescan · resolved")).toBeInTheDocument();
    expect(screen.getByText("Isolated axe-core rescan: 1 before → 0 after.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/hindsight/issues/image-alt");
  });

  it("shows first recorded rules and handles unknown recommendation mappings", () => {
    renderPanel({
      ...summary,
      recurring_issues: [],
      new_issues: [{ ...issue, status: "NEW", occurrences: 1, previously_repaired: false, reappeared_after_repair: false, prevention_recommendation: null }],
    });

    expect(screen.getByText("First recorded occurrences")).toBeInTheDocument();
    expect(screen.getByText("NEW")).toBeInTheDocument();
    expect(screen.getByText("No mapped prevention recommendation is available for the recorded rules.")).toBeInTheDocument();
  });
});
