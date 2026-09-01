# DOU Upgraded Phase 1 — Execution Roadmap

## Planning assumptions

- `dou-server` remains the active product repository.
- The current workforce product is retained and evolved; no full rewrite.
- Delivery marketplace/dispatch is not part of this roadmap.
- Every release is multi-tenant, bilingual, migration-safe, observable, and covered by acceptance tests.
- Production deployment, Neon schema changes, and external integration activation require explicit owner approval.

## Delivery gates

Each epic passes these gates before merge/deploy:

1. Product acceptance criteria agreed.
2. Tenant/RBAC policy documented.
3. Migration upgrade and recovery approach tested.
4. Unit/domain/API tests pass.
5. Cross-tenant denial tests pass.
6. Arabic/English UX checked.
7. Audit events and observability included.
8. No sensitive values in responses/logs.
9. Independent review passes.

## Wave 0 — Stabilization and engineering control

### W0-E1 Security and tenant boundaries

**Scope**

- Production secret fail-closed.
- Legacy order mutation disabled by default.
- Legacy courier fleet ownership validation.
- DOU internal roles separated from company tenant routes.
- No password echo in rider creation.
- Tenant-setting orphan prevention.

**Acceptance**

- Automated tests prove denial paths.
- No legacy order mutation is available when feature flag is off.
- Internal DOU user cannot write tenant settings without an explicit tenant context.

### W0-E2 Test and CI foundation

**Scope**

- Safe `tests/` collection only.
- Compile, tests, dashboard syntax, lint baseline, migration checks, and container build CI.
- Remove tracked local virtual environment.

**Acceptance**

- `pytest` cannot collect destructive scripts under `tools/`.
- CI is a required branch check after repository-owner approval.

### W0-E3 Versioned migrations and readiness

**Scope**

- Explicit migration command.
- Alembic adoption baseline.
- No DB mutation on import or web startup.
- PostgreSQL migration advisory lock.
- Database readiness endpoint.
- Backup/rollback runbook.

**Acceptance**

- Empty isolated DB migrates successfully.
- Second migration run is safe.
- `alembic current` is head and `alembic check` is clean.
- Existing production adoption is rehearsed on a disposable Neon branch before approval.

### W0-E4 Dependencies and container hardening

**Scope**

- Upgrade vulnerable framework dependencies.
- Remove vulnerable/unneeded crypto dependency.
- Run container as non-root.
- Docker health check uses readiness.
- Dependency audit in CI after all findings are resolved or explicitly risk-accepted.

**Acceptance**

- Clean environment installs exact pins.
- Full test suite passes on production Python version.
- Dependency audit has no unreviewed applicable high/critical finding.
- Built container starts, migrates an isolated DB, becomes healthy, and serves smoke routes.

## Wave 1 — Workforce domain completion

### W1-E1 Teams and zones

**Models**

- `OperatingZone`
- `WorkforceTeam`
- `TeamMembership`
- `TeamSupervisorAssignment`

**Key rules**

- Every row has tenant ownership.
- Memberships are effective-dated.
- A rider may have one primary active team per operating context unless business rules explicitly allow more.
- Supervisor scope derives from assignments, never UI payload alone.

**Acceptance**

- Company can create and manage zones/teams.
- Rider history remains queryable after transfer.
- Cross-tenant IDs return not found.
- Dashboard and report filters include team/zone.

### W1-E2 Vehicle registry and assignments

**Models**

- `Vehicle`
- `VehicleDocument`
- `RiderVehicleAssignment`

**Key rules**

- Plate uniqueness is tenant/market aware.
- Assignment dates cannot overlap for exclusive vehicles.
- Vehicle operational and compliance statuses are separate.

**Acceptance**

- Add/import vehicles, assign/unassign riders, track history/documents/expiry.
- Rider readiness explains vehicle blockers.

### W1-E3 Salary structures

**Models**

- `SalaryStructure`
- `SalaryComponent`
- `RiderSalaryAssignment`

**Key rules**

- Effective-dated and versioned.
- Supports base, per-order, allowance, overtime, incentive, deduction references.
- Closed payroll snapshots never recalculate silently.

**Acceptance**

- Payroll preview identifies the exact structure/version used.
- Date overlap and conflicting assignment tests exist.

### W1-E4 Timekeeping and attendance corrections

**Models/workflows**

- Shift template vs dated shift occurrence.
- Work session/break records.
- Attendance correction request and decision.
- Approved overtime.

**Acceptance**

- Timezone/overnight calculations tested.
- Missing checkout, late, absence, early leave, and correction flows produce traceable events.
- Payroll input uses approved facts only.

### W1-E5 Leave policy

**Models/workflows**

- Leave types/policies.
- Entitlement/balance where required.
- Request, approval, cancellation, and payroll impact.

**Acceptance**

- Overlap validation and supervisor scope are server enforced.
- Approved leave reconciles with attendance events.

### W1-E6 Documents and KYC pipeline

**Scope**

- Object-storage adapter.
- File metadata and signed access.
- MIME/content validation and scan status.
- Requirement matrix by market/rider/vehicle.
- KYC workflow states without false external-verification claims.

**Acceptance**

- Binary data is no longer stored as Data URI in PostgreSQL for new uploads.
- Unauthorized tenant/user cannot access file metadata or content.

### W1-E7 Operational readiness state

**Scope**

- Separate state dimensions: employment, account, attendance, shift, availability, leave, rider docs, vehicle compliance.
- Derived readiness with reason codes.

**Acceptance**

- API returns state components and deterministic blockers.
- No overloaded boolean drives unrelated decisions.

## Wave 2 — Order and raw-data foundation

### W2-E1 Source/platform registry

- Source platform.
- Tenant connection/import configuration.
- Project/contract mapping.
- Credential reference only; secrets stay in secret storage.

### W2-E2 Raw ingestion

- Import batch.
- Immutable raw row or object reference.
- Schema/version, checksum, source timestamps, status, validation issues.
- Preview/confirm/reprocess controls.

### W2-E3 Rider identity mapping

- Source rider identifier mapping.
- Effective dates and status.
- Confidence/match method and review queue.
- No phone-only silent merge.

### W2-E4 Normalized delivery facts

- Tenant-owned delivery fact independent of legacy `Order`.
- Source ID/idempotency.
- Rider/project/branch/team linkage as-of event time.
- Completed/cancelled/failed facts, timestamps, distance, monetary fields where approved.
- Provenance to raw row.

### W2-E5 Reconciliation and data quality

- Source totals vs accepted facts.
- Duplicate/unmapped/invalid/missing metrics.
- Exception ownership and resolution.
- Replay with versioned normalization.

**Wave 2 acceptance**

- Importing the same source twice does not double count.
- Every normalized fact resolves to tenant and source lineage.
- Unmapped rider rows do not affect KPI/payroll until approved.
- Legacy global order tables are not queried by new Phase 1 analytics.

## Wave 3 — Rules, payroll lineage, dashboards

### W3-E1 KPI catalogue

- Versioned KPI definitions.
- Inputs, filters, numerator/denominator, unit, source trust, effective dates.
- Materialized result with calculation version.

### W3-E2 Targets and rules

- Targets by tenant/platform/project/branch/team/rider.
- Incentive and deduction rule versions.
- Precedence/conflict policy.
- Explanation output.

### W3-E3 Payroll-input ledger

- Unified approved input records from attendance, leave, delivery facts, rules, and manual adjustments.
- Reversal rather than destructive edits.
- Closed-period protection.

### W3-E4 Dashboards and reports

- Executive, operations, workforce, timekeeping, payroll, compliance, vehicles, platform/order, and data-quality dashboards.
- Common filter model and metric catalogue.
- Drill-down to approved fact and raw source where authorized.

**Wave 3 acceptance**

- A payroll number can be traced to salary version, inputs, normalized facts, and raw source.
- KPI and target values show definition and freshness.
- Exports obey the same tenant/RBAC filters as UI.

## Wave 4 — Delivery-platform enterprise readiness

### W4-E1 Platform and contracted-operator governance

- Explicit platform/operator relationship.
- Delegated scopes without tenant-boundary bypass.
- Aggregated reporting only through approved relationship and role.

### W4-E2 Partner integration API

- Versioned API.
- Scoped credentials, rotation, rate limits, idempotency.
- Signed inbound/outbound webhooks.
- Integration audit and replay.

### W4-E3 Enterprise security and operations

- MFA/SSO decision and implementation for sensitive roles.
- Structured logging, request IDs, Sentry/error monitoring, metrics, alerts.
- Staging, branch protection, backup/restore drill, incident runbooks.
- Data residency implementation after legal/technical decision.

### W4-E4 Scale and acceptance

- Load profiles for platform file/API volumes.
- Large import streaming/batching.
- Query/index verification.
- SLA/SLO and support model.

## Cross-cutting backlog

- Replace legacy schema `Config` classes with current Pydantic configuration.
- Remove broad local token storage after a secure session/cookie migration design.
- Centralize permission parsing and invalid JSON handling.
- Central audit-event service.
- Structured error catalogue and i18n.
- Remove dead legacy delivery code only after dependency and data review.

## Release strategy

Each wave is delivered as small vertical slices. A recommended slice includes model/migration, service, API, authorization, audit, tests, and minimal UI together. Avoid creating all tables first and postponing behavior/testing.

No Phase 2 marketplace work starts merely because order facts exist. The decision requires separate approval after upgraded Phase 1 passes operational acceptance.
