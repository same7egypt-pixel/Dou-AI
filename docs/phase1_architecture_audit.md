# DOU Phase 1 Architecture Audit

## Scope and live paths

Phase 1 serves the company dashboard at `/app` and the rider application at `/driver`. The core live routers are `fleet`, `hr`, `shifts`, `couriers`, and authentication. Legacy delivery, global analytics, orders, and geo routes are feature-flagged behind `ENABLE_LEGACY_DELIVERY`; they are not a valid operational or financial source of truth for the normal Phase 1 company workflow.

## Current source map

| Entity or value | Persisted source today | Current consumer or calculation | Audit finding |
|---|---|---|---|
| Company | `Tenant` | Auth and all company-scoped routes | Correct tenant boundary exists. |
| Managed geographic reference | `GeoCity` and `GeoDistrict` | Legacy DOU-admin-only geo API | Not tenant-operational and not connected to Phase 1 riders, branches, or reports. |
| Operational city | `Courier.work_city`, `Courier.zone`, `ContractBranch.city` | HR, fleet, reports, and forms | Free text is the active source and causes duplicate or contradictory values. |
| Operational branch | `ContractBranch` | Rider assignment, supervisor scope, project link | Correct existing concept; city must become a relationship rather than free text. |
| Project or operating scope | `Project`, usually referenced by `Courier.primary_project_id` and `ContractBranch.project_id` | Daily logs and bonus plans | Reusable but project names are generated from contract/city/supervisor and therefore contain duplicated display data. |
| Rider operational assignment | `Courier.contract_branch_id`, `primary_project_id`, `supervisor_id`, `contract_id` | HR and fleet routes | The branch is the most complete current scope; duplicated city/platform text must be treated as legacy display values. |
| Supervisor ownership | `Courier.supervisor_id`, with branch/project fallback | Server-side `_supervisor_courier_scope` in HR and fleet | Server-side protection is present and must be retained. |
| Shift and attendance | `Shift`, `Attendance.shift_id`, timestamps | `shifts` router | Timing is calculated server-side, but assignees are stored as JSON and attendance deductions are absent. |
| Eligible performance orders | `DailyLog.orders_count` by project and month | HR bonus calculation | This is the Phase 1 payroll/bonus source today. Legacy order/task completion is not linked to it. |
| Bonus | `BonusPlan` at branch/project scope with optional rider override | `calculate_target_bonus` and selected HR endpoints | Formula is correct but no plan status/effective dating/final snapshot exists. Fleet and profile endpoints recompute different bonus estimates. |
| Payroll | Courier compensation fields, contract compensation fields, `PayrollAdjustment`, `DailyLog`, and `BonusPlan` | `hr_payroll` | The closest authoritative calculation is `/hr/payroll`, but it lacks payroll periods, finalization, and snapshots. |
| Client revenue | Legacy `Order.total` or `Order.delivery_fee` | Fleet overview and legacy analytics | Not connected to commercial contract terms; must not be presented as contract revenue. |
| Operational margin | None | None | Not currently calculable from authoritative commercial revenue and rider cost data. |

## Confirmed architectural problems

The active Phase 1 workflow uses three independent free-text city fields: rider work city, rider zone, and contract-branch city. A global `GeoCity` model exists but is isolated in a legacy router. As a result, the application cannot enforce that a rider, branch, contract, and supervisor share a valid operating city.

The `Contract` record mixes a commercial scope with rider-compensation fields (`base_salary` and `per_delivery_rate`). This means it cannot safely represent both a client agreement and a rider pay rule. `Order.total` is an end-customer order value, not a client contract rate, and it must not be used as Phase 1 commercial revenue.

Bonus calculation itself has a usable authoritative formula in `calculate_target_bonus`, based on `DailyLog` monthly order counts. However, fleet reports, courier profile output, payroll, payouts, and leaderboard contain separate compensation calculations or fallback values. The duplicate paths are inconsistent.

Attendance records are linked to scheduled shifts and compute timing server-side. They currently do not create deductions, which is appropriate because no configurable deduction policy exists. `PayrollAdjustment` has no idempotency key or linkage to attendance, and there is no finalized payroll period or financial snapshot. Creating automatic absence or late deductions now would risk duplicate entries and invent a business rule.

The active fleet overview is tenant-scoped, but it calculates payroll as fixed salaries only and labels legacy order totals as revenue. Legacy analytics is global and uses hardcoded courier pay assumptions. Neither should be used for Phase 1 financial reporting.

## Smallest safe normalization path

1. Reuse `GeoCity` as the canonical city catalog and add a tenant-scoped operating-city activation table. This avoids a duplicate City model while allowing each company to activate only its own cities.
2. Link `ContractBranch` to canonical city IDs. Keep its existing free-text `city` as a populated legacy display field during migration.
3. Link riders to the same canonical city through their branch. Keep `work_city` and `zone` as legacy display fields and backfill only unambiguous case-insensitive city matches.
4. Keep `Project` as the operational scope. Link an active branch to a project and validate all rider/supervisor/bonus relationships through the branch.
5. Add commercial fields to `Contract` with unambiguous names: client name and client rate per eligible order. Preserve existing rider compensation fields as legacy compensation configuration and stop using them for client revenue.
6. Normalize `BonusPlan` lifecycle with status, effective date, and safe deactivation. Keep the existing branch-level plan and rider override relationship; do not delete plans used by historical or active records.
7. Extract one backend calculation service for monthly eligible orders, bonus, payroll preview, client revenue, and operational contribution. Make the dashboard and reports display that service output instead of reimplementing formulas.
8. Do not create attendance deductions until the company defines an explicit configurable deduction policy. This remains a required business decision.
9. Do not claim historical payroll integrity is complete until payroll periods/snapshots or equivalent finalization semantics exist. The smallest safe Phase 1 correction is a read-only finalized monthly snapshot that prevents silent recomputation.

## Business rules that are not defined

| Required decision | Why implementation must not guess |
|---|---|
| Attendance deduction policy | No configured rate or threshold exists for absence, lateness, or early departure. |
| Eligible completed order source for commercial revenue | `DailyLog` is currently rider-entered operational volume; legacy orders are not contract-scoped. |
| Contract client rate effective-dating policy | A historical client rate change requires either a finalized financial snapshot or an effective date. |
| Allowance categories and treatment | Existing adjustments support overtime/deductions but no clear allowance policy. |
| Payroll finalization authority and period | Existing payroll is a live preview, not a finalized accounting record. |

## Implementation boundary

The next implementation will normalize the existing Phase 1 live path without enabling legacy routers or changing the FastAPI stack. Automatic financial deductions and finalized-history claims will remain explicitly unsupported until their business rules are provided.
