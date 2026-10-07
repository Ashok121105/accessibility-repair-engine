import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getHindsightWebsiteHistory,
  getHindsightWebsites,
} from "../../services/api";
import type { WebsiteHistoryDetail, WebsiteHistorySummary } from "../../types/api";
import WebsiteHindsight from "./WebsiteHindsight";

vi.mock("../../services/api", () => ({
  getHindsightWebsites: vi.fn(),
  getHindsightWebsiteHistory: vi.fn(),
}));

const sites: WebsiteHistorySummary[] = [
  {
    website_id: "a".repeat(64),
    domain: "example.com",
    scan_count: 2,
    latest_scanned_at: "2026-10-07T10:00:00Z",
    latest_total_issues: 3,
  },
  {
    website_id: "b".repeat(64),
    domain: "another.example",
    scan_count: 1,
    latest_scanned_at: "2026-10-06T10:00:00Z",
    latest_total_issues: 0,
  },
];

const detail: WebsiteHistoryDetail = {
  website_id: sites[0].website_id,
  domain: "example.com",
  scans: [
    {
      scan_id: "scan-one",
      original_url: "https://example.com",
      website_url: "https://example.com/",
      domain: "example.com",
      scanned_at: "2026-10-06T10:00:00Z",
      total_issues: 8,
      critical: 2,
      serious: 4,
      moderate: 2,
      minor: 0,
      detected_rule_ids: ["image-alt"],
      issues: [{
        fingerprint: "issue-fingerprint",
        rule_id: "image-alt",
        impact: "critical",
        wcag_criterion: null,
        affected_node_count: 4,
      }],
      repairs: [{
        rule_id: "image-alt",
        repair_type: "add_alt_attribute",
        verification_status: "verified",
        verification_at: "2026-10-06T10:05:00Z",
        original_violation_present: true,
        repaired_violation_present: false,
        verification_new_violation_count: 0,
        verification_checks_passed: 1,
        verification_checks_total: 1,
        application_status: "improved",
        before_violation_count: 1,
        after_violation_count: 0,
        certificate_status: "VERIFIED",
        certificate_id: "certificate-id",
        evidence_hash: "c".repeat(64),
      }],
    },
    {
      scan_id: "scan-two",
      original_url: "https://example.com/",
      website_url: "https://example.com/",
      domain: "example.com",
      scanned_at: "2026-10-07T10:00:00Z",
      total_issues: 3,
      critical: 0,
      serious: 1,
      moderate: 2,
      minor: 0,
      detected_rule_ids: ["button-name"],
      issues: [{
        fingerprint: "new-issue-fingerprint",
        rule_id: "button-name",
        impact: "serious",
        wcag_criterion: null,
        affected_node_count: 2,
      }],
      repairs: [],
    },
  ],
  comparison: {
    previous_scan: {
      scan_id: "scan-one",
      original_url: "https://example.com",
      website_url: "https://example.com/",
      domain: "example.com",
      scanned_at: "2026-10-06T10:00:00Z",
      total_issues: 8,
      critical: 2,
      serious: 4,
      moderate: 2,
      minor: 0,
      detected_rule_ids: ["image-alt"],
      issues: [],
      repairs: [],
    },
    current_scan: {
      scan_id: "scan-two",
      original_url: "https://example.com/",
      website_url: "https://example.com/",
      domain: "example.com",
      scanned_at: "2026-10-07T10:00:00Z",
      total_issues: 3,
      critical: 0,
      serious: 1,
      moderate: 2,
      minor: 0,
      detected_rule_ids: ["button-name"],
      issues: [],
      repairs: [],
    },
    resolved: [{
      fingerprint: "resolved-id",
      rule_id: "image-alt",
      impact: "critical",
    }],
    still_present: [],
    reappeared: [],
    new: [{
      fingerprint: "new-id",
      rule_id: "button-name",
      impact: "serious",
    }],
  },
  insights: [
    "1 issue is no longer present compared with the previous example.com scan.",
    "1 issue appeared in the latest example.com scan and was not in the previous scan.",
  ],
};

describe("Website Hindsight", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders stored website history, comparison, insights, and repair evidence", async () => {
    vi.mocked(getHindsightWebsites).mockResolvedValue(sites);
    vi.mocked(getHindsightWebsiteHistory).mockResolvedValue(detail);
    render(<WebsiteHindsight />);

    expect(await screen.findByRole("heading", { name: "Scan history for example.com" })).toBeInTheDocument();
    expect(document.querySelector('time[datetime="2026-10-06T10:00:00Z"]')).toBeInTheDocument();
    const scanList = document.querySelector(".website-history-list");
    expect(scanList).toHaveTextContent("8 issues");
    expect(scanList).toHaveTextContent("3 issues");
    expect(screen.getByText("Resolved", { selector: "dt" })).toBeInTheDocument();
    expect(screen.getByText("Reappeared", { selector: "dt" })).toBeInTheDocument();
    expect(screen.getByText("1 issue is no longer present compared with the previous example.com scan.")).toBeInTheDocument();
    expect(screen.getByText(/Certificate: VERIFIED/)).toBeInTheDocument();
    expect(screen.getByText("Evidence hash:")).toBeInTheDocument();
    expect(screen.getByText(/Verified before\/after evidence/)).toBeInTheDocument();
    expect(screen.getByText("Verification checks: 1/1 passed")).toBeInTheDocument();
    expect(screen.queryByText(/raw json/i)).not.toBeInTheDocument();
  });

  it("shows an honest empty-history state", async () => {
    vi.mocked(getHindsightWebsites).mockResolvedValue([]);
    render(<WebsiteHindsight />);

    expect(await screen.findByRole("heading", { name: "No website scan history yet" })).toBeInTheDocument();
    expect(getHindsightWebsiteHistory).not.toHaveBeenCalled();
  });

  it("announces website history loading and provides an accessible loading error", async () => {
    vi.mocked(getHindsightWebsites).mockResolvedValue(sites);
    let finishRequest: ((value: WebsiteHistoryDetail) => void) | undefined;
    vi.mocked(getHindsightWebsiteHistory).mockReturnValue(
      new Promise((resolve) => {
        finishRequest = resolve;
      }),
    );
    render(<WebsiteHindsight />);

    expect(await screen.findByText("Loading recorded scans and comparison…")).toBeInTheDocument();
    finishRequest?.(detail);
    expect(await screen.findByRole("heading", { name: "Latest comparison" })).toBeInTheDocument();
  });

  it("supports keyboard selection between known website histories", async () => {
    vi.mocked(getHindsightWebsites).mockResolvedValue(sites);
    vi.mocked(getHindsightWebsiteHistory).mockImplementation(async (websiteId) => (
      websiteId === sites[0].website_id
        ? detail
        : { ...detail, website_id: sites[1].website_id, domain: sites[1].domain, comparison: null }
    ));
    const user = userEvent.setup();
    render(<WebsiteHindsight />);

    const picker = await screen.findByRole("combobox", { name: "Website" });
    await user.tab();
    expect(picker).toHaveFocus();
    expect(within(picker).getByRole("option", { name: "another.example" })).toBeInTheDocument();
    await user.selectOptions(picker, sites[1].website_id);

    expect(await screen.findByRole("heading", { name: "Scan history for another.example" })).toBeInTheDocument();
  });

  it("displays a clear error if website history cannot be retrieved", async () => {
    vi.mocked(getHindsightWebsites).mockRejectedValue(new Error("Website history unavailable"));
    render(<WebsiteHindsight />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Website history unavailable");
  });
});
