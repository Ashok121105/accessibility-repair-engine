import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { DashboardMetrics } from "../../types/api";
import BeforeAfterComparison from "./BeforeAfterComparison";
import ViolationBreakdown from "./ViolationBreakdown";

afterEach(cleanup);

const metrics: DashboardMetrics = {
  total_violations: 1,
  critical: 1,
  serious: 0,
  moderate: 0,
  minor: 0,
  other: 0,
  score: 80,
  score_explanation: "Real test fixture counts.",
};

describe("dashboard charts", () => {
  it("renders the before/after chart from actual totals", () => {
    render(<BeforeAfterComparison before={metrics} after={{ ...metrics, total_violations: 0, critical: 0 }} />);
    expect(screen.getByRole("region", { name: "Before and after violation count chart" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Before 1; after 0 actual violations" })).toBeInTheDocument();
  });

  it("renders severity distribution from actual severity counts", () => {
    render(<ViolationBreakdown before={metrics} after={{ ...metrics, total_violations: 0, critical: 0 }} />);
    expect(screen.getByRole("region", { name: "Severity distribution chart" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Actual critical, serious, moderate, and minor violations before and after" })).toBeInTheDocument();
  });
});
