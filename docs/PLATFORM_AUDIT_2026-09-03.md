# DOU Platform — Full Audit

**Date:** 3 September 2026
**Commit audited:** `16dfabb` (local `main`, clean tree, in sync with origin)
**Production:** `16dfabb`, container healthy, zero errors in log
**Method:** read-only. No source file, database, migration, environment variable, infrastructure resource or deployment was modified. No commit, push, rebuild, restart or deploy was performed.

---

## 1. Executive verdict

### CONDITIONAL PASS — pilot ready after the listed blockers

DOU is a genuinely capable Phase 1 fleet platform. The backend is substantial and correct where it matters most: payroll has one calculation path and I verified it numerically; tenant isolation held against every cross-tenant probe I threw at it; the entitlement model is enforced server-side. The failures I found are not architectural — they are a small number of specific defects, two of which would embarrass you in front of a customer and one of which puts your production data at risk.

**It cannot be piloted today** because of three things: backups exist only on the same host as the database, the dashboard is unusable on any screen under 960px, and a rider can read the company's DOU invoice. None of the three is hard to fix.

| Dimension | Score | Why |
|---|---|---|
| Backend engineering | **8/10** | 449 endpoints, clean layering, one payroll path, no N+1 on hot endpoints (query count constant across tenant sizes). Loses points for 233 orphaned endpoints and inconsistent error localisation. |
| Security | **7/10** | Tenant isolation and object-level authorization are strong — every cross-tenant probe returned 404, not 200. Login throttling is Redis-backed. Loses points for the billing role gap (P1), rate limiting that collapses all clients into one bucket (P2), and no IAM role. |
| Data integrity | **8/10** | Payroll immutability via snapshots, debt carry verified numerically, 22 migrations all with real downgrades, single head. Loses points for integrity rules that live only in service code rather than DB constraints. |
| Frontend engineering | **7/10** | 27 ES modules all parse, zero JS errors across every screen and role tested, honest empty/error states. Loses points for the unfinished responsive work. |
| UI quality | **7/10** | Coherent visual language, consistent components, good empty states, real RTL. Loses points for mobile being effectively broken and one dead-end permission screen. |
| UX coherence | **6/10** | The rider lifecycle now connects end to end. Loses points for supervisors being buried in a modal on Capacity Planning, no onboarding wizard, and a nav that offers a screen the role cannot use. |
| Feature completeness | **8/10** | 18 of 20 audited workflows are complete and usable. Loses points for vendor/operator management having no UI and analytics being unhosted. |
| Testing | **7/10** | 695 tests, all passing, mapped to real risks including tenant isolation and payroll golden amounts. Loses points for the CI pipeline never running and no automated E2E in CI. |
| Production readiness | **5/10** | Healthy deployment, verified nightly backups, clean rollback path. **Heavily penalised**: backups never leave the host, CI is not wired to GitHub, no Sentry DSN, no IAM role, deploys need a manual git bundle. |
| Pilot / sales readiness | **6/10** | Demonstrable today on desktop with real data. Loses points for mobile, the analytics promise the product cannot yet keep, and no seeded demo tenant. |

---

## 2. System map

**Applications**
- `/app` — Fleet dashboard (frontend-v2, vanilla ES modules, no build step), 9 screens
- `/admin` — DOU admin console (`static/admin.html`, single file)
- `/driver` — Rider PWA (`static/courier.html`, 4 languages, service worker, offline page)
- `android-driver/` — Android wrapper, `applicationId delivery.dou.driver`, APK 3.5 MB in `static/`
- `/` — marketing site (`static/index.html`, `index-en.html`)

**Services** — FastAPI 0.140 (uvicorn, 4 workers) · PostgreSQL 15 · Redis 5 · nginx (TLS termination) · Docker Compose on a single EC2 `t3.micro` in `eu-central-1b`

**Data** — 449 API endpoints across 31 routers; SQLAlchemy 2.0 models in `entities.py`, `intelligence.py`, `salary.py`; 22 Alembic migrations, single head `20260902_0022`

**Roles implemented (13)** — `CUSTOMER, MERCHANT, COURIER, COMPANY, COMPANY_ADMIN, OPERATIONS, HR, ACCOUNTANT, VIEWER, PROJECT_MANAGER, SUPERVISOR, DOU_OPS, DOU_ADMIN`

**Account types** — `LOGISTICS_OPERATOR` / `DELIVERY_PLATFORM`, driving capability sets (`RIDER_PAYROLL`, `MANAGE_OPERATORS`, `OPERATOR_SETTLEMENTS`, `VENDOR_PORTAL`, …)

**Data flow** — rider app and imports write facts → `DailyLog` / `PlatformDeliveryFact` → `financial_calculations.payroll_rows` → payroll sheet, rider statement, rider wallet (one engine) → `PayrollSnapshot` on finalize.

---

## 3. Feature traceability matrix

| Feature | Backend | Frontend | Nav | Permissions | Tests | Runtime | Verdict |
|---|---|---|---|---|---|---|---|
| Companies / operators | ✓ | admin console | ✓ | DOU_ADMIN | ✓ | 200 | Complete |
| Projects / branches | ✓ `/hr/contracts` | Capacity → Contracts | ✓ | COMPANY_ROLES | ✓ | 200 | Complete |
| Supervisors | ✓ `/hr/supervisors` | modal on Capacity | buried | COMPANY_ROLES | ✓ | 200 | Complete but difficult |
| Riders | ✓ `/fleet/couriers` | Riders | ✓ | role-gated | ✓ | 200 | Complete |
| Rider 360 | ✓ 8 sources | 8 tabs | via Riders | tenant-scoped | ✓ | 200 | Complete |
| Onboarding | ✓ readiness engine | across screens | — | ✓ | ✓ | 200 | Complete but difficult |
| Documents / KYC | ✓ | Rider360 → Documents | ✓ | tenant-scoped 404 | ✓ | 200 | Complete |
| Vehicles | ✓ `/vehicles` | Riders + Rider360 | ✓ | ✓ | ✓ | 200 | Complete |
| Shifts | ✓ `/fleet/shifts` | Shifts | ✓ | ✓ | ✓ | 200 | Complete |
| Attendance + corrections | ✓ | Shifts (2 tabs) | ✓ | ✓ | ✓ | 200 | Complete |
| Leave | ✓ `/leave` | Shifts + Rider360 | ✓ | ✓ | ✓ | 200 | Complete |
| Capacity | ✓ | Capacity | ✓ | ✓ | ✓ | 200 | Complete |
| Needs Attention | ✓ deterministic | Needs Attention | ✓ | ✓ | ✓ | 200 | Complete |
| Performance | ✓ | Reports | ✓ | ✓ | ✓ | 200 | Complete |
| Targets / incentives | ✓ `/analytics/targets`, `/hr/bonus` | Rider360, Payroll | partial | ✓ | ✓ | 200 | Partially implemented — no bulk target screen |
| Payroll | ✓ one engine | Payroll + Rider360 + rider app | ✓ | capability + role | ✓ golden | 200 | Complete |
| Imports / reconciliation | ✓ template/preview/confirm | Riders modals | ✓ | ✓ | ✓ | 200 | Complete |
| Reports | ✓ | Reports (2 of 3 tabs) | ✓ | ✓ | ✓ | 200 | Partially implemented — analytics unhosted |
| Notifications | ✓ `/notifications` | top-bar bell | ✓ | recipient-scoped | ✓ | 200 | Complete but difficult — no centre |
| DOU AI | ✓ deterministic | DOU AI + drawer | ✓ | tenant + capability | ✓ | 200 | Partially implemented |
| API keys / webhooks | ✓ `/enterprise/credentials` | — | — | ✓ | ✓ | — | **Backend only** |
| Vendor / operator mgmt | ✓ `/enterprise/operators` | read-only | ✓ | ✓ | ✓ | 200 | **Backend only** (0 POST calls from UI) |
| Billing | ✓ `/billing` | Settings → Subscription | ✓ | **none** | partial | 200 | Complete but insecure |
| Settings / users | ✓ `/fleet/users` | Settings | ✓ | role-gated | ✓ | 200 | Complete |

---

## 4. End-to-end workflow results

Twenty workflows evaluated. Verdicts:

**Complete and usable (15):** company structure · projects/branches · riders create & bulk import · documents upload+review · rider assignment (project/supervisor/vehicle) · shifts · attendance + corrections · leave · operational imports · performance · payroll calculation · payroll review/approve · dispute tracing · exports · needs-attention · capacity · access management (users)

**Complete but difficult (3):** supervisor creation (buried in a Capacity modal) · onboarding ordering (no wizard; first rider is rejected until a supervisor is attached to the branch from a different screen) · notifications (bell only)

**Partially implemented (1):** targets & incentives — per-rider only, no bulk screen

**Backend only (1):** API keys / webhooks / vendor-operator management — endpoints complete, zero UI

### Verified lifecycle trace (fresh empty tenant, tenant 7)
```
create contract + city   → 200, operating city auto-activated ([] → 1 active)
add rider (no supervisor)→ 400 "لهذا الفرع لا يوجد مشرف مسؤول نشط…" (names the screen)
create supervisor        → 200
attach supervisor        → 200
add rider                → 200
upload document          → 200 PENDING
approve document         → 200, kyc_status VERIFIED
readiness                → documents MISSING → VERIFIED, blocker cleared
payroll                  → consistent across 3 surfaces
```

### Payroll numeric verification (rider 2, محمد العتيبي, 2026-09)
| Surface | orders | gross | net |
|---|---|---|---|
| Company payroll sheet `/hr/payroll` | 45 | 270.00 | 270.00 |
| Staff rider statement | 45 | 270.00 | 270.00 |
| Rider app wallet | 45 | 270.00 | 270.00 |

**Debt-settlement rule** (`apply_debt_settlement`, exact values):

| net_before | carried | applied | **net_pay** | debt_balance | generated |
|---|---|---|---|---|---|
| 2000 | 0 | 0 | **2000.00** | 0 | 0 |
| 2000 | 500 | 500 | **1500.00** | 0 | 0 |
| 500 | 2000 | 500 | **0.00** | 1500 | 0 |
| 1234.567 | 0 | 0 | **1234.57** | 0 | 0 |
| −50 | 0 | 0 | **0.00** | 50 | 50 |

Net is never negative; the shortfall becomes carried debt; rounding is 2 dp. Matches the documented contract exactly.

**Determinism:** three consecutive reads of the same month produced byte-identical row signatures (`sha=5a2f0ca4f96e5a31`).

---

## 5. Findings register

### P0 — Critical
**None.** No tenant leak, no financial corruption, no data-loss path in the application, no impossible core workflow.

---

### P1-1 · Backups never leave the host
- **Severity** P1 · **Area** Production readiness · **Status** Confirmed
- **Affected** All tenants; disaster recovery
- **Evidence**
  - `docker compose exec -T app env` → `BACKUP_S3_BUCKET=[]` while `AWS_REGION=[me-central-1]` passes through
  - `/var/log/dou-backup.log` → `BACKUP_S3_BUCKET is not set; keeping the backup on this host only`
  - `.env` on host **does** contain `BACKUP_S3_BUCKET` (18 chars)
  - `docker-compose.yml` app `environment:` passes `S3_BUCKET`, `AWS_REGION`, `SENTRY_DSN` — **not** `BACKUP_S3_BUCKET`
  - `scripts/backup.py:28` reads `BACKUP_S3_BUCKET`; line 80 prints the fallback
  - `docs/PRODUCTION_RUNBOOK.md:98` claims *"Nightly backup, verified on write and uploaded to S3"*
  - Container has **no** AWS credentials (`AWS_ACCESS_KEY_ID` unset) and the instance has **no IAM role**
- **Expected** Nightly dump uploaded off-host, per the runbook
- **Actual** 6 dumps sit in `/opt/dou-fleet/backups` on the same EC2 instance as PostgreSQL
- **Impact** Instance loss destroys the database and every backup simultaneously. The runbook documents a guarantee the deployment does not deliver.
- **Root cause** Missing env passthrough + missing credentials path
- **Fix** Add `BACKUP_S3_BUCKET: ${BACKUP_S3_BUCKET:-}` to the app service; attach an EC2 instance role with `s3:PutObject` on the backup bucket (preferred over static keys per CLAUDE.md); re-run one backup and confirm the object lands.
- **Regression test** Assert `docker-compose.yml` passes every variable `scripts/backup.py` reads.

---

### P1-2 · Fleet dashboard is unusable below 960px
- **Severity** P1 · **Area** UI / UX · **Status** Confirmed
- **Affected** SUPERVISOR (most mobile role), OPERATIONS, all roles on tablet/phone
- **Evidence** — measured in-browser:
  | Viewport | Sidebar left | Nav visible | Content | Hamburger |
  |---|---|---|---|---|
  | 399 px | 375 | **12 px** per item | 375 | none |
  | 768 px | 768 | **0 px** | 768 | none |
  | 1280 px | 1032 | 224 px | 1032 | n/a |
  | 1440 px | 1192 | 224 px | 1192 | n/a |
  - `frontend-v2/shared/styles/main.css:890-897` — `@media (max-width: 960px) { .sidebar { transform: translateX(100%) } .sidebar.open { transform: translateX(0) } }`
  - `grep "app-sidebar" frontend-v2/**/*.js` → **1 match**, `shell.js:251`, the element's creation. Zero toggles.
  - The 7 `.open` matches all target `searchableSelect` dropdowns and the AI drawer — none the sidebar.
- **Expected** A menu control reveals navigation below 960px
- **Actual** At 768px navigation is entirely off-screen with no way to open it; at 399px a 12px sliver remains (touch targets should be ≥44px)
- **Impact** A field supervisor cannot use the product on the device they actually carry. No horizontal overflow and no console errors, so this fails silently.
- **Root cause** The responsive CSS hook was written; the toggle button that uses it was never built.
- **Fix** Add a menu button in the top bar toggling `.open` on `#app-sidebar` below 960px, plus a scrim and Escape-to-close.
- **Regression test** Assert a control exists that toggles `#app-sidebar`, and assert nav items exceed 44px at 375px.

---

### P1-3 · A rider can read the company's DOU invoice
- **Severity** P1 · **Area** Security / authorization · **Status** Confirmed
- **Affected** COURIER (least-privileged role) reading commercial data about their employer
- **Evidence** — probed with a real COURIER token (tenant 2):
  ```
  GET /billing/status  → 200 {"plan":"PRO","monthly_fee":499.0,"status":"ACTIVE","due_date":"…"}
  GET /billing/invoice → 200 {"invoice_no":"DOU-0002-202610","tenant":"دو فليت الرياض","amount":499.0,…}
  ```
  - `app/routers/billing.py` — `billing_status` and `billing_invoice` depend only on `get_current_user` + `_tenant_for(user, db)`. **No role check.** Every other financial endpoint gates on `COMPANY_ROLES`.
- **Attack path** Any rider with the app extracts their bearer token (or uses the app's own fetch) and calls the endpoint directly. No privilege escalation needed.
- **Impact** Commercially sensitive B2B contract value exposed to employees. Not a tenant leak — the data belongs to their own tenant — but a clear role-scoping defect.
- **Fix** Gate both endpoints on `COMPANY_ROLES` (and `ACCOUNTANT`).
- **Regression test** Assert COURIER and SUPERVISOR receive 403 on both.

---

### P1-4 · CI has never run
- **Severity** P1 · **Area** Testing / process · **Status** Confirmed
- **Evidence** `deploy/ci/ci.yml` defines lint + bandit + tests + migration checks. `.github/` **does not exist**; `git ls-files .github` → 0 files. The pipeline's own header comment reads *"An earlier copy of this pipeline lived in deploy/ci/ci.yml, where GitHub never picked it up, so nothing was actually enforced on a push."* — and it is still at that path.
- **Impact** Every guard the project relies on (tenant isolation, payroll golden amounts, schema integrity) runs only when someone runs it locally. A regression reaches `main` unchallenged.
- **Fix** Move to `.github/workflows/ci.yml`. Requires a token with `workflow` scope (`gh auth refresh -s workflow`).
- **Note** I ran the pipeline's checks manually — all pass (see §8).

---

### P2-1 · Rate limiting collapses every client into one bucket
- **Severity** P2 · **Area** Reliability / security · **Status** Confirmed
- **Evidence** `app/middleware/rate_limit.py` keys on `request.client.host`, in-memory, no Redis (0 references). `main.py:73` sets 300/min. `Dockerfile:44` runs `--workers 4` with no `--proxy-headers`. Production log source IPs: `127.0.0.1` (123×) and `172.18.0.1` (49×) — the nginx/docker bridge, never a real client.
- **Impact** Two consequences: no per-client limiting exists at all, and all customers share ~300 req/min per worker. Measured cost of one dashboard session: 4+2+2+2+6+6+3+3+3 = **31 API calls** for a nine-screen tour. Roughly ten concurrent users touring the product can trip 429s for everyone — a self-inflicted denial of service at pilot scale.
- **Fix** Run uvicorn with `--proxy-headers --forwarded-allow-ips`, and move the counter to Redis (login throttling already does this correctly — use it as the model).

---

### P2-2 · Supervisor sees a Payroll screen they can never use
- **Severity** P2 · **Area** UX / permissions · **Status** Confirmed
- **Evidence** SUPERVISOR sidebar renders `payroll`; `GET /hr/payroll?month=2026-09` → **403**. Screen renders full chrome then: *"⚠️ تعذر تحميل بيانات مسير الرواتب: Admin only"* with a retry button that can never succeed.
- **Secondary defect** The backend message `"Admin only"` is English and unlocalised, surfacing raw inside an Arabic UI.
- **Impact** Dead-end screen; the mirror of the defect fixed in `20cd2cd` (nav hid what the API allowed — here nav shows what the API denies).
- **Fix** Add `payroll: ['COMPANY','COMPANY_ADMIN','ACCOUNTANT']` to the shell's `ROLE_ONLY` map; localise the backend message.

---

### P2-3 · Fabricated KPI values shipped in the dashboards payload
- **Severity** P2 · **Area** Product integrity · **Status** Confirmed
- **Evidence** `app/routers/reports.py:963-980` returns hardcoded strings presented as metrics: `نسبة الحضور: "94%"`, `معدل الإنجاز: "98.2%"`, `جاهز للتشغيل: "85%"`, `وثائق مكتملة: "91%"`.
- **Mitigating** The dashboards tab is currently hidden (`status: NOT_CONFIGURED`), so these do not reach customers **today** — they will the moment Metabase is hosted.
- **Impact** Invented numbers in a business-intelligence surface destroy trust in every real number beside them.
- **Fix** Remove the `kpis` arrays or compute them from `analytics_views`.

---

### P2-4 · Admin console geography screen is dead
- **Severity** P2 · **Area** Frontend/backend contract · **Status** Confirmed
- **Evidence** `static/admin.html:957,982,990,1003` call `/geo/countries` and `/geo/cities`; both return **404** because `app/main.py:127` mounts the geo router only when `ENABLE_LEGACY_DELIVERY=true` (`app/config.py:23`, default false). The screen `#view-geo` (`admin.html:335`) renders "جارِ التحميل…" forever.
- **Fix** Either mount geo unconditionally or remove the screen.

---

### P2-5 · Vendor/operator management has no write UI
- **Severity** P2 · **Area** Feature completeness · **Status** Confirmed
- **Evidence** `grep "api.post('/enterprise"` across `frontend-v2/` → **0**. `POST /enterprise/operators` and `POST /enterprise/operators/{id}/portal` (which grants `VENDOR_PORTAL`) have no caller. The Vendors empty state instructs *"أضفهم من شاشة المشغّلين"* — a screen that does not exist in the sidebar.
- **Impact** The entire platform/vendor business line — including the vendor-portal plan now advertised on the marketing site — cannot be operated without a developer.

---

### P3 — Low
1. **Redundant failing call in the rider wallet.** `/hr/payroll/rider/{id}/statement` returns 403 for COURIER (guard predates this session — verified at `dee4e1b`) but the call is wrapped in `.catch(()=>null)` and the wallet populates correctly from `/hr/me/hr`. Cosmetic noise; remove the call.
2. **DOU AI fails a prompt it suggests.** "كم عدد السائقين الغائبين اليوم؟" — offered as a Command Center quick query — returns `Unsupported metric for COUNT: ABSENCE`, a raw English internal error. 3 of 4 suggested prompts work.
3. **DOU AI language mixing.** Arabic questions sometimes return English answers ("You have 5 riders in your authorized scope").
4. **DOU AI generic fallback.** Several distinct questions collapse to one canned summary rather than declining.
5. **`logout-all` accepts the admin key as a query parameter** (`app/routers/auth.py:215`) — logged in access logs, browser history and proxies. The header form exists and is correct.
6. **233 of 361 endpoints (64%) have no UI caller.** Mostly Phase 2 or legacy-gated, but it inflates the API surface and the audit burden.
7. **MD5 used as a cache key** (`app/services/cache.py:42`) — bandit HIGH, but not security-relevant. Add `usedforsecurity=False`.
8. **f-string SQL in `app/migrations.py:122,162`** — bandit MEDIUM; interpolated values are hardcoded literals, not user input. Not exploitable.
9. **No Sentry DSN configured** in production despite the SDK being installed and wired.
10. **846 lint errors in `tests/`** (not a CI gate; `app/` is clean).

---

## 6. UI / UX review

**Screen-by-screen** — all nine fleet screens loaded with **zero failed network calls and zero JavaScript errors** as COMPANY, and zero as SUPERVISOR except the P2-2 payroll 403.

| Screen | API calls | State quality |
|---|---|---|
| Command Center | 4 | Real workforce/attendance/readiness/compliance data. **No Phase 2 content** — verified clean of marketplace/merchant/network terms. |
| Riders | 2 | Search, filters, bulk import, template, history, broadcast |
| Shifts | 2 | 4 tabs, honest empty states |
| Capacity | 2 | Contracts + branches + supervisors modal |
| Needs Attention | 6 | Deterministic queue + rider request queue |
| Reports | 6 | 2 tabs; analytics tab correctly absent |
| Payroll | 3 | Stepper, ledger, adjustments, bonus plans |
| DOU AI | 3 | Chat + prompt chips |
| Settings | 3 | Users, security, subscription |

**Information architecture** — largely matches the intended structure. Deviations: supervisors live in a modal on Capacity Planning rather than under Workforce; Documents/Vehicles/Leave live inside Rider 360 rather than as first-class screens; there is no Onboarding screen (the lifecycle is spread across Riders and Rider 360).

**Arabic / RTL** — `dir=rtl lang=ar` correct; English mode flips to `ltr/en` cleanly. In English, the only Arabic remaining on screen is customer data (rider names, tenant names) — correct behaviour, verified across four screens.

**Responsive** — see P1-2. No horizontal overflow at any width; tables do not overflow. The single defect is navigation reachability.

**Accessibility** — focus states present; `Permissions-Policy` restricts camera/mic. Not audited for screen-reader semantics or full keyboard traversal — **verification gap**.

---

## 7. Security and tenant isolation

**Attack paths tested (all read-only, no destructive testing):**

| Test | Result |
|---|---|
| Cross-tenant object read — platform (T4) → T2 rider docs | **404** ✓ |
| Cross-tenant object read — T7 admin → T2 rider readiness | **404** ✓ |
| Cross-tenant object read — T7 admin → T2 rider profile | **404** ✓ |
| Cross-tenant payroll statement | **404** ✓ |
| Cross-tenant company users | not listed ✓ |
| Rider → another rider's record | **404** ✓ |
| Rider → `/fleet/couriers`, `/hr/payroll` | **403** ✓ |
| Anonymous → every protected endpoint (13 tested) | **401** ✓ |
| Platform → payroll (capability) | **403** ✓ |
| Logistics → vendor settlements (capability) | **403** ✓ |
| DOU AI → payroll for an unentitled account | **403** ✓ |
| DOU AI → injected `sql` / `question_id` fields | ignored ✓ |
| Unauthenticated Ninja ingestion | **401** ✓ |
| Rider → `/billing/invoice` | **200 ✗ (P1-3)** |

404-not-403 on cross-tenant objects is the right choice — it does not confirm existence.

**Coverage gaps (not tested):** CSRF (token-in-header design makes it low risk), SSRF, path traversal on uploads, dependency CVE scan (no scanner configured), webhook replay windows, session fixation.

---

## 8. Test and command log

| # | Command | Result |
|---|---|---|
| 1 | `pytest tests/ -q` | **695 passed, 0 failed, 0 skipped**, 96.3 s |
| 2 | `ruff check app/ --select E,F,I,W --ignore E501` | **All checks passed** |
| 3 | `pytest --collect-only` | 695 collected |
| 4 | `ruff check tests/` | 846 errors (not a gate) |
| 5 | `pytest tests/test_frontend_modules_parse.py` | 27 passed (all ES modules parse) |
| 6 | `pytest` structural guards (schema, startup, deploy, image, deps) | 26 passed |
| 7 | `alembic heads` | single head `20260902_0022`, 22 revisions |
| 8 | downgrade coverage scan | 0 of 22 irreversible |
| 9 | `uvx bandit -r app/ -ll` | 3 findings, all triaged non-exploitable |
| 10 | `pytest -k "snapshot or finalize"` | 5 passed |
| 11 | `pytest test_payroll_golden test_payroll_tenant_isolation` | 20 passed |
| 12 | Query-count instrumentation, 2 tenants | constant with rider count — **no N+1** |
| 13 | Browser sweep, 9 screens × 2 roles | 0 failed calls, 0 JS errors |
| 14 | Responsive measurement, 4 widths | P1-2 |
| 15 | Authorization matrix, 6 actors × 13 endpoints | P1-3 only |
| 16 | Production health + smoke | healthy, 0 errors |

**Not run (verification gaps):** dependency CVE scan (no scanner configured; venv has no pip) · Playwright E2E in `e2e/` (47 scripts, not executed — would write data) · load/scale testing at 100–500 riders · screen-reader accessibility · Android release build.

---

## 9. Pilot-blocker checklist

**Must fix before any production use**
- P1-1 Backups off-host

**Must fix before customer pilot**
- P1-2 Mobile navigation
- P1-3 Billing role gap
- P2-1 Rate limiting

**Must fix before sales demo**
- P2-2 Supervisor payroll dead end
- P2-3 Fabricated KPIs (before enabling analytics)

**Can fix after pilot**
- P1-4 CI wiring · P2-4 admin geo · P2-5 vendor UI · all P3

---

## 10. Prioritised remediation plan

### Batch A — Data safety (do first)
- **Covers** P1-1
- **Files** `docker-compose.yml`; AWS IAM (instance role)
- **Migration** No · **Deployment change** Yes (compose + IAM)
- **Acceptance** A dump appears in the S3 bucket within one nightly cycle; restore drill from the S3 copy succeeds
- **Risk** Low
- **Test** Assert compose passes every variable `scripts/backup.py` reads

### Batch B — Authorization and abuse
- **Covers** P1-3, P2-1, P2-2, P3-5
- **Files** `app/routers/billing.py`, `app/middleware/rate_limit.py`, `Dockerfile`, `frontend-v2/fleet/shell.js`, `app/routers/auth.py`
- **Migration** No · **Deployment** Yes (uvicorn flags)
- **Acceptance** COURIER/SUPERVISOR → 403 on billing; rate limit keys on the real client IP and shares state across workers; supervisor no longer sees Payroll
- **Risk** Low–medium (proxy-header trust must be scoped to the nginx IP)

### Batch C — Mobile
- **Covers** P1-2
- **Files** `frontend-v2/fleet/shell.js`, `frontend-v2/shared/styles/main.css`
- **Migration** No · **Deployment** No
- **Acceptance** At 375/768px a menu control opens the sidebar; nav targets ≥44px; Escape and scrim close it
- **Risk** Low

### Batch D — Product integrity
- **Covers** P2-3, P2-4, P3-1, P3-2/3/4
- **Files** `app/routers/reports.py`, `app/main.py` or `static/admin.html`, `static/courier.html`, `app/services/dou_ai.py`
- **Risk** Low

### Batch E — Process and reach
- **Covers** P1-4, P2-5
- **Needs** `workflow` token scope; a new operators screen
- **Risk** Medium (new UI surface)

---

## 11. Final sellability answer

**Can DOU be demonstrated today?**
Yes — on a desktop browser, with the `دو فليت الرياض` account (5 riders, real payroll). Do not demo on a phone or tablet, and do not open the Reports → Analytics tab (correctly hidden).

**Can it be piloted with one company?**
Not until Batch A and B ship. Backups on the same host as the database is not a risk to accept with a customer's payroll data, and a rider reading the company's invoice will surface in the first week.

**Can it safely manage real riders?**
Yes. The lifecycle connects end to end, tenant isolation held against every probe, and readiness gating works.

**Can it safely calculate real payroll?**
Yes — with more confidence than any other part of the system. One engine, three surfaces agreeing to the fils, determinism verified across repeated reads, net never negative, snapshots immutable, 20 golden tests.

**Is it ready for a company like Ninja?**
Not yet, for a specific reason: Ninja is a `DELIVERY_PLATFORM`, and that line **cannot be operated from the UI** — a platform cannot add a vendor or grant a vendor portal without a developer (P2-5). The logistics line is far closer to ready than the platform line.

**Exact remaining blockers:** P1-1 backups · P1-2 mobile navigation · P1-3 billing role gap · P2-1 rate limiting. Add P2-5 if the first customer is a platform rather than a fleet operator.

---

*Audit performed read-only. No source file, database, migration, environment variable, infrastructure resource or deployment was modified. Working tree clean at `16dfabb` before and after.*
