# DOU Upgraded Phase 1 — Current-State Gap Analysis

## Assessment rule

This document compares the upgraded Phase 1 target with the current `dou-server` implementation. Status means:

- **Strong base:** usable current capability; still subject to stabilization and customer validation.
- **Partial:** meaningful implementation exists but does not yet satisfy the upgraded scope.
- **Rework:** current structure should not be the foundation of the target capability.
- **Missing:** no adequate first-class implementation was verified.

The assessment does not convert roadmap items into live-product claims.

## Executive result

The current platform is a strong base for rider workforce administration, organizational assignments, attendance, performance import, payroll preparation, and reporting. It is not yet a complete enterprise Fleet Management OS for large delivery platforms.

The largest upgraded-scope gaps are:

1. First-class teams/zones and assignment history.
2. First-class vehicle registry and vehicle assignments.
3. Effective-dated salary structures and rule governance.
4. Complete working-hours and attendance-correction workflow.
5. Enterprise KYC/file storage and verification controls.
6. Comprehensive immutable audit coverage.
7. A new tenant-owned order/raw-data foundation with source lineage and reconciliation.
8. Platform-to-contracted-operator hierarchy and enterprise integration governance.
9. Production observability, data residency decision, staging, and SLA readiness.

## Capability matrix

| Capability | Current evidence | Status | Required decision/work | Priority |
|---|---|---:|---|---:|
| Tenant/company | `Tenant`, tenant IDs across core workforce models, auth and fleet scopes | Strong base | Add automated cross-tenant policy tests for every new resource; define platform/operator hierarchy | P0/P1 |
| Riders | `Courier`, `/fleet/couriers`, rider import, rider self-service | Strong base | Normalize overloaded profile; assignment history; archive lifecycle; stronger uniqueness/identity rules | P1 |
| Supervisors | supervisor roles, HR supervisor routes, direct/branch/project scope | Strong base | Delegation/history, substitute supervisor, bulk reassignment, explicit scope policy tests | P1 |
| Branches | `ContractBranch`, contract/project linkage | Partial | Separate organizational branch from commercial contract branch where needed; effective-dated assignments | P1 |
| Operating cities | geo city + tenant operating-city structures | Partial/strong | Finish normalization and eliminate remaining free-text city dependence | P1 |
| Teams/zones | `Fleet.zone`, `Courier.zone`, supervisor/project relationships | Rework | Create tenant-owned Team and Zone entities, memberships, capacity, manager, effective dates | P1 |
| Shift templates/schedules | `Shift`, assignment IDs, status/capacity | Partial | Separate templates from dated occurrences; recurrence, timezone, overnight, publish/lock workflow | P1 |
| Attendance | GPS check-in/out, `Attendance`, `AttendanceEvent`, policies | Partial/strong | Correction/approval workflow, missing checkout, absence generation, geofence/anti-spoofing roadmap | P1 |
| Working hours | derived hours in attendance/report logic | Partial | Persist approved work sessions/timesheets; breaks, overtime, overnight rules, corrections | P1 |
| Leave | `LeaveRequest`, rider/company flows | Partial | Leave types, balances/entitlements, overlap/policy checks, attendance/payroll impact | P1 |
| Commercial contracts | `Contract`, `ContractBranch`, projects and client rates | Partial/strong | Effective versions, SLAs, multiple rate rules, platform/operator relationship | P1 |
| Employment contracts | rider employment fields and documents only | Missing/partial | Decide legal scope; implement terms/history/document workflow only if approved | P2 |
| Salary structure | base/per-delivery/bonus fields on rider and contract | Rework | Effective-dated salary structures, assignment hierarchy, currencies, allowances, rule versions | P1 |
| Payroll inputs | attendance events, daily logs, adjustments, calculations | Strong base | Unified provenance model, approval state, correction/reversal workflow | P1 |
| Payroll preparation | periods, snapshots, financial snapshots, exports | Strong base | Multi-step approval, audit completeness, reconciliation, no bank/WPS claim | P1 |
| Incentives | bonus plans, targets and snapshots | Partial | Generic effective-dated rule engine with explainability and precedence | P1 |
| Deductions | attendance policies and payroll adjustments | Partial | Generic policy types, caps, approvals, reversals, dispute workflow | P1 |
| KPIs | daily performance/order counts and analytics | Partial | KPI definition/version entity, numerator/denominator lineage, source trust level | P1/P2 |
| Targets | centralized targets/bonus logic | Partial | Scope hierarchy and effective periods; lock calculation version in payroll snapshots | P1 |
| Documents | rider document fields/submissions/expiry | Partial | Object storage, MIME/content checks, malware scanning, requirements matrix, signed access | P1 |
| KYC | document review status | Missing as verified KYC | Create workflow states; integrate external verification before claiming verified KYC | P2 |
| Vehicles | rider vehicle type/plate/license fields | Rework | First-class Vehicle, documents, status, owner/lease, effective rider assignment history | P1 |
| Operational status | employment, active user, online, available, shift, leave, docs flags | Rework | Separate state dimensions and add derived readiness with reason codes | P1 |
| Dashboard | company/rider/admin dashboards and analytics | Strong base | Extend filters and drill-down; metric catalogue; data freshness/trust indicators | P1/P2 |
| Reporting | executive/operations/financial/workforce, CSV details | Strong base | Complete export coverage, scheduled exports, vehicle/data-quality reports | P1/P2 |
| Audit logs | `AuditLog`, admin audit, selected `_audit` calls | Partial | Central audit service/middleware, structured changes, correlation IDs, immutable retention | P0/P1 |
| Raw data ingestion | import batch stores normalized payload JSON | Rework | Immutable raw rows/object references, schemas, validation results, replay and retention | P1 |
| Normalized order facts | `DailyLog` aggregate; legacy `Order` global | Missing/rework | New tenant-owned delivery fact; never reuse legacy global `Order` | P1 |
| Source/platform registry | `Project` often represents platform | Partial/rework | First-class operational data source/platform connection and mapping | P1 |
| Rider identity mapping | phone/platform courier ID fields | Partial | Mapping table per source with confidence, effective dates, and review queue | P1 |
| Reconciliation | duplicate fingerprints and preview/confirm | Partial | Source totals vs normalized totals vs payroll inputs; exception resolution | P1/P2 |
| Integration APIs | internal REST and file imports | Partial | Versioned partner API, credentials/scopes, webhooks, idempotency, rate limits | P2 |
| Platform/operator hierarchy | ordinary tenants only | Missing | Model contracted operator relationship without weakening tenant boundaries | P2 |
| Arabic/English | bilingual dashboard/rider surfaces | Strong base | Move server/API error catalogue and all new UI copy into maintained i18n | P1 |
| Security/RBAC | JWT, token version, tenant helpers, permissions | Partial/strong | Central policy layer, refresh/session design, MFA for sensitive roles, audit | P0/P2 |
| Migrations | Alembic adoption baseline and explicit command on hardening branch | In progress locally | Validate on production-like PostgreSQL branch; do not stamp production without backup/approval | P0 |
| Tests/CI | isolated pytest suite and backend workflow on hardening branch | In progress locally | Expand domain/tenant matrix; branch protection and required checks after approval | P0/P1 |
| Observability | basic server logs and readiness | Partial | Structured logs, request IDs, Sentry/error monitoring, metrics, alerts | P0/P1 |
| File security | Data URI in PostgreSQL | Rework | Object storage and content pipeline | P1 |
| Data residency | current Render service observed in Oregon | Open risk | Legal/technical decision for Saudi data, database and file regions | Executive/P0 |

## Retain, harden, extend, rebuild

### Retain and harden

- Tenant model and most workforce tenant IDs.
- Rider/supervisor core records.
- Commercial operating hierarchy concepts.
- Preview/confirm import pattern and fingerprints.
- Payroll periods and immutable snapshots.
- Existing analytics/reporting service structure.
- Rider self-service surface.

### Extend

- Attendance into full timekeeping.
- Leave into entitlement/policy workflow.
- Contracts into versioned commercial rules.
- Targets/bonuses/deductions into a generic rule model.
- Audit logs into comprehensive structured events.
- Dashboard/report filters and drill-down.

### Rebuild or create new foundations

- Team/zone domain.
- Vehicle domain.
- Salary structure domain.
- Operational readiness state model.
- Document storage/KYC pipeline.
- Source platform and rider identity mapping.
- Raw ingestion and normalized order/delivery facts.
- Platform-to-contracted-operator governance.

## Recommended implementation order

### Wave 0 — Stabilization

Security, tenant isolation, safe migrations, tests, CI, repository cleanup, readiness, dependency audit, observability foundation.

### Wave 1 — Workforce model completion

Teams/zones, vehicles, assignment history, salary structures, attendance/timekeeping, leave policies, document pipeline, operational readiness.

### Wave 2 — Raw and order facts

Source registry, import batches, immutable raw rows, identity mapping, normalized facts, validation and reconciliation.

### Wave 3 — Derived operations

KPI definitions, targets, incentives, deductions, payroll-input lineage, dashboards and data-quality reporting.

### Wave 4 — Platform enterprise readiness

Contracted operators, partner APIs/webhooks, SSO/MFA/governance, scale, SLAs, staging/DR, residency implementation.

## Acceptance gate for “complete upgraded Phase 1”

Phase 1 should not be called complete until:

- Every listed domain has a tenant-owned model and server authorization policy.
- Every payroll/KPI number can be traced to approved inputs and source facts.
- Raw imports are replayable and reconciled.
- Order facts do not depend on the legacy global order model.
- Vehicles, teams/zones, salary structures, and working hours are first-class.
- Audit coverage includes all sensitive state changes.
- Migration, backup/restore, monitoring, and tenant-isolation suites are proven on staging.
- At least one logistics-company workflow and one delivery-platform/operator workflow pass end-to-end acceptance with real approved sample data.
