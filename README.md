# Automated Accessibility Repair Engine

A foundation for a web accessibility workflow that detects issues, proposes repairs, tests those proposals in an isolated browser sandbox, and records the resulting evidence in an immutable certificate. Certificates describe only configured automated checks and never claim universal WCAG conformance or mathematical proof.

## Architecture

```text
frontend/     React dashboard and typed API client
backend/      FastAPI app, environment-backed settings, API routes, and evidence services
scanner/      Reserved for Playwright, axe-core, and custom WCAG rules
sample-sites/ Reserved for local test fixtures
backend/data/ SQLite store for workflow events, verification records, and immutable certificates
docs/         Design and implementation documentation
```

The backend is split into API, core configuration, models, scanning/accessibility, repair, verification, and certificate packages so later capabilities can be added without coupling them to the dashboard. The Vite development server proxies `/api` requests to FastAPI.

## Technology stack

- Frontend: React, TypeScript, Vite, Tailwind CSS, Recharts
- Backend: Python, FastAPI, Pydantic Settings
- Scanner: Playwright Chromium and axe-core via `axe-core-python`
- Tests: Vitest and Testing Library; pytest and FastAPI TestClient
- Persistence: local SQLite records for dashboard workflow evidence, verification runs, and certificates

## Development setup

Requirements: Node.js with npm, and Python 3.10 or newer.

Set `GEMINI_API_KEY` in `backend/.env` to enable proposal generation. The backend loads this file regardless of the working directory; process environment variables take precedence. The API key is read only by the backend and sent to Gemini in a request header. Never place it in frontend variables or commit an `.env` file. Scanning works without a Gemini key; proposal requests return a clear unavailable error.

### Run the backend

From the repository root:

```powershell
py -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python -m playwright install chromium
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check: `http://127.0.0.1:8000/api/health`

The scanner endpoint is `POST http://127.0.0.1:8000/api/scan` with JSON such as `{"url":"https://example.com"}`. It loads the public site in headless Chromium and returns axe-core violations with normalized rule IDs, WCAG criteria and levels when supported by axe tags or a deterministic rule mapping, impacts, affected nodes, selectors, and help links. Findings without a reliable mapping are labeled `WCAG mapping unavailable`. Private/local network targets are rejected.

The optional proposal endpoint is `POST http://127.0.0.1:8000/api/repair/propose`. It accepts an individual detected violation's rule/WCAG information, affected HTML, selector, available context, and page URL. It returns a structured proposal or `repair_not_safe`. Proposals are advisory only: this endpoint never edits a website or claims verification.

The verification endpoint is `POST http://127.0.0.1:8000/api/repair/verify`. It takes the original and proposed affected HTML, axe rule ID, selector, WCAG information, optional surrounding HTML, and the proposal. A fresh headless Chromium page receives only that supplied markup; all network requests are blocked. The endpoint compares axe-core findings before and after the proposed change and returns `verified`, `rejected`, or `verification_failed` with individual checks. Only a small set of deterministic attribute-only repairs is currently in scope; other rules fail closed. `verified` means the configured automated checks passed, not formal proof or a guarantee of full WCAG conformance.

After a successful verification, `POST http://127.0.0.1:8000/api/certificates` creates an evidence certificate. It accepts the scan metadata and evidence plus a verification ID returned by this backend; certificate evidence is checked against the server-recorded verification run before issuance. `GET /api/certificates/{certificate_id}` retrieves a saved certificate. Certificates are stored in SQLite under `backend/data/`, are immutable through the API/database triggers, and include a deterministic SHA-256 digest of canonicalized evidence. The digest is an integrity fingerprint, not a digital signature or proof against an attacker who can alter the database file.

`POST http://127.0.0.1:8000/api/repair/apply` accepts a verification ID and the exact repair evidence recorded by the backend. It rejects missing, non-verified, unsupported, or changed evidence. For accepted requests it creates a fresh local Playwright document, blocks network requests, scans the original fragment with axe-core, applies the verified fragment only in that temporary document, and scans again. The response includes actual before/after axe violations, resolved and remaining findings, new violations, and an `improved`, `unchanged`, or `regression` status. The scanned live website is never revisited or modified; this is an isolated-copy comparison, not a claim that the production site was changed or is fully accessible.

### Dashboard

`GET http://127.0.0.1:8000/api/dashboard/summary` reports persisted scan, proposal, verification, isolated-application, and certificate evidence for the latest scanned website. The dashboard provides:

- Before/after accessibility comparison and actual violation lists
- Critical, serious, moderate, and minor severity breakdowns
- A deterministic, impact-weighted score: start at 100, subtract 20 per critical, 10 per serious, 5 per moderate, 2 per minor, and 5 per unclassified axe-core violation, with a floor of 0
- Repair progress, verification status, and regression detection
- Status and retrieval of an existing verified certificate

A score of 100 means only: “No detected violations from the supported scan/rules in this scan.” The dashboard reports evidence from the supported scanner and verification pipeline. It does not claim universal WCAG conformance.

### Hindsight / Accessibility Learning

`GET http://127.0.0.1:8000/api/hindsight/summary` analyzes the existing persisted scan, proposal, verification, and isolated-application events. Issue totals count one rule occurrence per scan, grouped by axe rule and normalized website host; selectors are supporting evidence and are not treated as the identity of an issue. A rule is marked `RECURRING_AFTER_REPAIR` only when a recorded isolated rescan resolved that rule and a later recorded website scan detected it again.

`GET http://127.0.0.1:8000/api/hindsight/issues/{rule_id}` returns each recorded scan occurrence and its associated proposal, verification, isolated application, and rescan timeline. The dashboard displays first recorded occurrences, recurring patterns, prior repair outcomes, and deterministic prevention recommendations for supported rules. Unknown rules have no mapped recommendation. With no persisted scan history, the API returns `insufficient_history`; one scan can show first-recorded issues but cannot establish recurrence.

This feature provides historical evidence and recommendations. It does not guarantee prevention of future accessibility violations. Likely causes are hypotheses, and an isolated repair rescan does not mean the live website was changed.

### Developer Project Analysis

`POST http://127.0.0.1:8000/api/project/analyze` accepts one ZIP file in multipart field `file`. ZIPs are limited to 12 MB, 500 entries, and 50 MB expanded size; HTML pages are limited to 30 files and 1 MB each. The analyzer rejects path traversal, duplicate paths, symlinks/special files, encrypted entries, executable binaries, and excessive compression ratios. Upload bodies are additionally capped at 14 MB.

Static HTML is analyzed in a temporary directory using Playwright and the existing axe-core result parser/WCAG normalizer. Scripts, inline event handlers, frames, embedded objects, external resource references, stylesheet imports, and CSS URLs are removed; browser network requests are blocked. CSS files, project JavaScript, and remote assets are not loaded, so results concern the sanitized static markup and may not reflect styled or script-rendered behavior. Source lines are reported only when a unique matching source element is found; otherwise the response explicitly reports that source mapping is unavailable. Temporary project files are removed after analysis, and the uploaded source is never modified.

React and React + Vite manifests are detected, but building or executing uploaded React code is currently **analysis unavailable**. This environment has no Docker/Podman isolation, so the implementation does not run package installation, project scripts, or uploaded code on the host. React responses contain no scan results and use a null violation count rather than presenting an unscanned project as having zero issues. Angular, Vue, Next.js, Svelte, and unknown projects are not analyzed.

For completed static scans, developers can reuse the existing Gemini proposal, isolated verification/application, and certificate APIs from the project panel. A certificate includes the project ID and type in its evidence hash. These operations test the supplied HTML fragment in the existing isolated sandbox; they do not transform or patch the uploaded source. Patch generation reports unavailable. Project scans are stored in the existing workflow event store and are separately labeled as project evidence in Hindsight.

### Run the frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (normally `http://localhost:5173`). The dashboard requests `/api/health` through the Vite proxy. To use a different backend URL, set `VITE_API_BASE_URL` in a local frontend `.env` file; this variable is public and must never contain secrets.

### Checks

```powershell
# Backend (from repository root, with backend dependencies installed)
python -m pytest backend\tests

# Frontend (from frontend)
npm test
npm run build
```

## Current prototype scope

- The dashboard checks backend availability and can scan public HTTP(S) websites.
- Successful scans, safe proposals, verification outcomes, isolated application results, and certificates are recorded in the local SQLite database for the dashboard summary.
- The WCAG detection layer normalizes axe-core findings into rule/category, criterion/level, impact, explanation, affected element, selector, and node-count details. It does not infer issues beyond axe-core results.
- Gemini can propose a minimal repair for each detected violation when `GEMINI_API_KEY` is configured. Proposals are labeled `AI PROPOSAL — NOT VERIFIED` and are never automatically applied.
- The verifier uses a temporary isolated browser document, scope checks, and before/after axe-core results. It does not connect to or modify the original website.
- A general scan-history browser and automated React project build/runtime analysis are not implemented. Static HTML ZIP projects are supported; React and React + Vite are detected but report `analysis_status: unavailable` until secure container isolation is configured. Angular, Vue, Next.js, Svelte, and other framework projects are detected as unsupported. The Hindsight issue-history view is limited to rules found in persisted scans.
- The workflow is `SCAN → DETECT → PROPOSE → VERIFY → APPLY TO ISOLATED COPY → RE-SCAN → HINDSIGHT`; certificate status remains available separately on the dashboard. No proposal is published to the website.
- The health route is `GET /api/health` and returns `{"status":"ok","service":"Accessibility Repair Engine"}`.
- The scan route is `POST /api/scan` and validates URL syntax and public network destinations before navigating.

## Verification and limitations

AI proposals cannot decide their own acceptance and are never applied to the live website. Only supported, server-recorded verified proposals can be temporarily applied to the isolated copy for a new axe-core scan. The current sandbox gate evaluates only supported rules and restricted repairs. Certificates record the returned checks and their evidence, scope, and limitations; they are not formal mathematical proof or a guarantee of full WCAG conformance.

PDF reporting, repository cloning, safe containerized React build/runtime analysis, production-site modification, whole-site regression testing, formal proof, and a browsable historical scan archive are future extensions, not current features. Static HTML project ZIP scanning and framework detection are available with the constraints described above.
