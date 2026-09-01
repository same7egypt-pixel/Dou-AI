# DOU Upgraded Phase 1 — Product Scope

## Product definition

DOU Phase 1 is a bilingual, multi-tenant **Fleet and Rider Workforce Management Operating System** for:

1. Logistics and delivery companies operating their own or contracted rider workforces.
2. Delivery platforms such as Jahez, HungerStation, Ninja, and similar operators that need a dedicated fleet-management layer for internal fleets, contracted operators, or both.

Phase 1 manages the complete rider workforce and uses order/raw operational data to measure performance, calculate payroll inputs, reconcile platform records, and support operational decisions.

## Explicit boundary

Order data in Phase 1 does **not** make DOU a consumer delivery marketplace.

Phase 1 includes:

- Ingesting order/delivery facts from files, APIs, webhooks, or controlled manual entry.
- Linking facts to tenant, platform, project, branch, team/zone, supervisor, and rider.
- KPI, target, incentive, deduction, payroll-input, reconciliation, dashboard, and reporting use cases.

Phase 1 excludes unless separately approved:

- Consumer ordering application.
- Merchant marketplace and catalogue.
- Cross-company smart dispatch.
- Freelancer delivery network.
- Customer live tracking.
- Payment collection or settlement execution.
- Carrier marketplace.

These remain later delivery-network/marketplace capabilities. Legacy `Order` and `Merchant` models are not the foundation for the Phase 1 order/raw-data layer because they lack the required tenant boundary.

## Tenant and operating hierarchy

Every operational record must resolve to one tenant. The target hierarchy is:

```text
Tenant / Operating Company or Platform
  └── Country / Market
      └── Operating City
          └── Branch
              └── Project / Platform Contract
                  └── Team / Zone
                      └── Supervisor
                          └── Rider
```

A platform tenant may additionally manage contracted operating companies. This relationship must be explicit; it must not weaken tenant isolation or create implicit global access.

## Phase 1 capability domains

### 1. Rider lifecycle

- Create, import, update, activate, suspend, terminate, and archive riders.
- Identity, contact, nationality, employment, emergency, bank, and platform identifiers.
- Assignment history across branches, projects, teams/zones, supervisors, and vehicles.
- Operational availability and employment status as separate states.
- Rider self-service for approved profile, document, leave, attendance, payroll, and performance functions.

### 2. Supervisors and organization

- Supervisors, project managers, company administrators, operations, HR, payroll/accounting, and read-only roles.
- Branch, city, team/zone, project, and contract scopes.
- Temporary delegation and reassignment with audit history.
- Server-enforced scope; UI restrictions alone are never authorization.

### 3. Branches, cities, teams, and zones

- Tenant-owned operating cities and branches.
- Teams/zones as first-class entities rather than free-text rider fields.
- Effective-dated assignments and capacity/coverage metadata.
- Cross-branch reporting without cross-tenant leakage.

### 4. Shifts, attendance, and working hours

- Shift templates, scheduled shifts, assignments, capacity, and status.
- GPS check-in/check-out with recorded coordinates and timestamps.
- Late arrival, early departure, absence, incomplete checkout, overtime, and exceptions.
- Working-hour calculation with timezone and overnight-shift handling.
- Attendance correction workflow with approver, reason, before/after values, and audit event.
- Future geofence/anti-spoofing support without claiming it is currently live.

### 5. Leave

- Leave types, balances or entitlement policy, requests, approvals/rejections, attachments, and overlap checks.
- Attendance/payroll impact policy.
- Supervisor and HR workflow with tenant and team scope.

### 6. Contracts

- Commercial platform/client contracts.
- Contract branches and projects.
- Rider employment/engagement terms where required for operations.
- Effective dates, rates, targets, service rules, and assignment history.
- Distinguish commercial contracts from legal employment-contract document management.

### 7. Salary structures and payroll inputs

- Effective-dated salary structures by rider/group/project/contract.
- Base salary, per-delivery rates, allowances, overtime, incentives, deductions, and adjustments.
- Attendance, order facts, KPI results, approved leave, and manual adjustments as traceable inputs.
- Preview, approval, close, immutable snapshot, and export.
- Phase 1 prepares payroll; it does not execute bank/WPS transfers or act as a general ledger.

### 8. Incentives, deductions, KPIs, and targets

- Versioned rules with effective periods and priority/scope.
- Rider, team, branch, project, platform, and tenant targets.
- Inputs traceable to normalized facts and source rows.
- Calculation version, explanation, override workflow, and audit trail.
- No silent retroactive recalculation of closed payroll periods.

### 9. Documents and KYC

- Document types, requirements by market/role/vehicle, expiry, submission, review, rejection, and renewal.
- File metadata stored separately from binary object storage.
- MIME/content validation, size limits, malware scanning integration point, and signed access.
- KYC status is a workflow state; governmental verification must not be claimed until integrated.

### 10. Vehicles

- Tenant-owned vehicle registry, type, plate, market, status, ownership/lease metadata, and documents.
- Effective-dated rider assignments and assignment history.
- Vehicle operational availability and compliance status.
- Full maintenance/asset-accounting workflows are separate unless approved into Phase 1.

### 11. Operational status

- Separate states for employment, account access, shift activity, attendance presence, operational availability, document compliance, and leave.
- A derived readiness status with explicit reasons.
- No single overloaded boolean may represent all rider states.

### 12. Order and raw operational data

- Source platform and connection/import configuration.
- Immutable import batch metadata and raw rows.
- Normalized delivery/order facts with tenant ownership.
- Source identifiers and idempotency keys.
- Rider/platform identity mapping and review queue.
- Validation, duplicate detection, errors, warnings, reconciliation, and controlled reprocessing.
- Traceability from every KPI/payroll input to normalized fact and raw source row.
- Retention and masking rules for customer personal data.

### 13. Dashboards and reporting

- Executive, operations, workforce, attendance, performance, payroll, finance, compliance, vehicle, and data-quality views.
- Linked filters: period, city, branch, contract, project/platform, team/zone, supervisor, rider, and status.
- Detail drill-down, pagination, export, and metric-definition visibility.
- Platform/operator rollups must remain permission- and tenant-scoped.

### 14. Audit logs

- Actor, tenant, role, action, entity, entity ID, timestamp, request/correlation ID, and structured change metadata.
- Before/after values for sensitive administrative changes where safe.
- Immutable retention policy and restricted access.
- Coverage for authentication/session actions, assignments, attendance corrections, documents, payroll, rules, imports, and support impersonation.

## Data ingestion modes

Phase 1 supports these modes in order of trust and automation:

1. Signed API/webhook integration.
2. Scheduled SFTP/object-storage file ingestion.
3. CSV/XLSX preview and confirm.
4. Controlled manual input with source type and audit record.

Every mode must produce the same normalized facts and provenance fields. Manual and imported data must never be presented as independently verified platform events unless verification exists.

## Core non-functional requirements

- Server-side tenant isolation on every read and write.
- Explicit role and scope authorization.
- Versioned Alembic migrations.
- No schema mutation during module import or web startup.
- CI tests for cross-tenant denial and migration drift.
- Structured logs, request IDs, error monitoring, and readiness checks.
- Encryption in transit and appropriate encryption/secret storage at rest.
- Market-aware timezone, currency, language, and retention policy.
- Backup, restore, and rollback rehearsal before production migrations.

## Release sequence

1. **Stabilization:** security, isolation, safe migrations, tests, CI, observability.
2. **Workforce completion:** organization/teams, vehicles, salary structures, attendance/working hours, documents, audit coverage.
3. **Order/raw-data foundation:** sources, batches, raw rows, normalized facts, identity mapping, reconciliation.
4. **Derived operations:** KPI/targets, incentives/deductions, payroll inputs, dashboards.
5. **Platform readiness:** contracted-operator hierarchy, integration controls, scale, SLAs, and enterprise governance.

Phase 2 delivery-network capabilities start only after this Phase 1 operating system is stable, measurable, and commercially validated.
