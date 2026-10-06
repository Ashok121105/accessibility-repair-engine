import type {
  HealthResponse,
  AccessibilityCertificate,
  CertificateRequest,
  DashboardSummary,
  HindsightIssueHistory,
  HindsightSummary,
  ProjectAnalysisResponse,
  RepairProposal,
  RepairProposalRequest,
  RepairApplicationRequest,
  RepairApplicationResult,
  ScanRequest,
  ScanResponse,
  VerificationRequest,
  VerificationResult,
} from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/health`);
  if (!response.ok) {
    throw new Error(`Health check failed (${response.status})`);
  }
  return (await response.json()) as HealthResponse;
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const response = await fetch(`${API_BASE_URL}/api/dashboard/summary`);
  if (!response.ok) {
    throw new Error(`Dashboard summary failed (${response.status})`);
  }
  return (await response.json()) as DashboardSummary;
}

export async function getHindsightSummary(): Promise<HindsightSummary> {
  const response = await fetch(`${API_BASE_URL}/api/hindsight/summary`);
  if (!response.ok) {
    throw new Error(`Hindsight summary failed (${response.status})`);
  }
  return (await response.json()) as HindsightSummary;
}

export async function getHindsightIssueHistory(
  ruleId: string,
): Promise<HindsightIssueHistory> {
  const response = await fetch(
    `${API_BASE_URL}/api/hindsight/issues/${encodeURIComponent(ruleId)}`,
  );
  if (!response.ok) {
    throw new Error(`Issue history retrieval failed (${response.status})`);
  }
  return (await response.json()) as HindsightIssueHistory;
}

export async function analyzeDeveloperProject(
  file: File,
): Promise<ProjectAnalysisResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE_URL}/api/project/analyze`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    let detail = `Project analysis failed (${response.status})`;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        detail = body.detail;
      }
    } catch {
      // Keep the HTTP status message when the API response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as ProjectAnalysisResponse;
}

export async function getCertificate(
  certificateId: string,
): Promise<AccessibilityCertificate> {
  const response = await fetch(
    `${API_BASE_URL}/api/certificates/${encodeURIComponent(certificateId)}`,
  );
  if (!response.ok) {
    throw new Error(`Certificate retrieval failed (${response.status})`);
  }
  return (await response.json()) as AccessibilityCertificate;
}

export async function scanWebsite(url: string): Promise<ScanResponse> {
  const request: ScanRequest = { url };
  const response = await fetch(`${API_BASE_URL}/api/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    let detail = `Scan failed (${response.status})`;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        detail = body.detail;
      } else if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        Array.isArray(body.detail)
      ) {
        const messages = body.detail.flatMap((issue: unknown) => {
          if (
            typeof issue === "object" &&
            issue !== null &&
            "msg" in issue &&
            typeof issue.msg === "string"
          ) {
            return [issue.msg];
          }
          return [];
        });
        if (messages.length > 0) detail = messages.join(". ");
      }
    } catch {
      // Keep the HTTP status message when the server does not return JSON.
    }
    throw new Error(detail);
  }

  return (await response.json()) as ScanResponse;
}

export async function proposeRepair(
  request: RepairProposalRequest,
): Promise<RepairProposal> {
  const response = await fetch(`${API_BASE_URL}/api/repair/propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    let detail = `Repair proposal failed (${response.status})`;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        detail = body.detail;
      }
    } catch {
      // Keep the HTTP status message if the API response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as RepairProposal;
}

export async function verifyRepair(
  request: VerificationRequest,
): Promise<VerificationResult> {
  const response = await fetch(`${API_BASE_URL}/api/repair/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    let detail = `Repair verification failed (${response.status})`;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        detail = body.detail;
      }
    } catch {
      // Keep the HTTP status message if the API response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as VerificationResult;
}

export async function applyVerifiedRepair(
  request: RepairApplicationRequest,
): Promise<RepairApplicationResult> {
  const response = await fetch(`${API_BASE_URL}/api/repair/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    let detail = `Repair application failed (${response.status})`;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        detail = body.detail;
      }
    } catch {
      // Keep the HTTP status message if the API response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as RepairApplicationResult;
}

export async function generateCertificate(
  request: CertificateRequest,
): Promise<AccessibilityCertificate> {
  const response = await fetch(`${API_BASE_URL}/api/certificates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    let detail = `Certificate generation failed (${response.status})`;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        detail = body.detail;
      }
    } catch {
      // Keep the HTTP status message if the API response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as AccessibilityCertificate;
}
