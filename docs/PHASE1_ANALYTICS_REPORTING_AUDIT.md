# Phase 1 Analytics & Reporting Audit

**Scope:** This audit covers only reporting and analytics in the current DOU Phase 1 head. It precedes implementation and does not alter rider operations, payroll rules, bonus formulas, contracts, cities, assignments, legacy delivery routes, or any live environment.

## Current reporting experience

The company dashboard currently has one **Reports Center** in `static/fleet.html`. It presents three table-oriented modes: daily rider report, document report, and bonus report. The page already has date presets, CSV export, a contract-to-branch selector cascade, and several advanced daily filters. However, it is not a unified analytics product: it has no separate Executive, Operations, Financial, or Workforce experiences; it loads report rows into the browser without report pagination; the city filter relies on legacy display text; and the filter options are populated from full lists rather than an ID-scoped reporting filter API.

| Existing view or API | Current responsibility | Reusable part | Reporting gap |
|---|---|---|---|
| `static/fleet.html` Reports Center | Daily, documents, and bonus tables | Existing navigation, CSV download pattern, date presets, report-state styling | No four-report navigation, no shared canonical filters, no protected financial view, no server-side report pagination. |
| `GET /hr/daily-report` | DailyLog, attendance, target, and bonus row report | Existing team scoping and date filters | Row assembly is per courier and uses legacy `zone` display filtering. It is not suitable as a 5,000-rider aggregate dashboard primitive. |
| `GET /fleet/reports` | Documents and bonus report tables | Bonus consumes `calculate_payroll_preview` | Full in-memory courier traversal and no pagination. |
| `GET /hr/payroll` | Monthly payroll detail and totals | `payroll_rows`, including finalized snapshots | Monthly-only. It cannot replace operational date-range analysis. |
| `GET /hr/financial/branches` | Branch-level commercial economics | `financial_rows`, including financial snapshots | Monthly-only and company-only, which is appropriate for commercial sensitivity. |
| `GET /fleet/overview` | Current month/today summary | Payroll and financial service reuse, supervisor scope | Mixes legacy order/task indicators with Phase 1 operational metrics and does not accept report filters. |
| `GET /fleet/needs-attention` | Existing actionable attention counts | Correct existing attention logic | Not filterable by a canonical report filter set. |
| `GET /fleet/couriers/paged` | SQL-backed paged rider list | Tenant/team scope and ID filters | A strong reusable primitive for report filter choices and detailed paged tables. |

## Authoritative source-of-truth map

| Reporting metric area | Authoritative source | Reporting treatment required |
|---|---|---|
| Eligible orders | `DailyLog` | Aggregate by reporting date and normalized rider/project/branch relationships. Do not use legacy `Order` totals as commercial revenue. |
| Attendance and worked hours | `Attendance` and `Shift` | Aggregate recorded check-in/out values; do not create attendance or deduction events while reading a report. |
| Target and bonus | `BonusPlan` through `calculate_courier_bonus` / `calculate_payroll_preview` | Reuse the centralized service. No frontend bonus formula. |
| Rider compensation | `calculate_payroll_preview` and `payroll_rows` | Use monthly preview for open periods and `PayrollSnapshot` for finalized periods. |
| Client revenue and operational margin | `financial_rows` / `branch_financial_preview` | Use `Contract.client_rate_per_order` only through the existing financial service. |
| Closed-period finance | `PayrollSnapshot` and `OperationalFinancialSnapshot` | Closed payroll reports read snapshots, never recalculate historical financial outcomes. |
| City / branch / supervisor assignment | `TenantOperatingCity`, `ContractBranch`, `Courier.supervisor_id`, `Courier.contract_branch_id` | IDs and relationships are the filter source. Legacy city display text remains presentation-only. |
| Actionable alerts | `GET /fleet/needs-attention` | Reuse the endpoint and do not duplicate its logic. |

## Current RBAC behavior

The existing permission matrix grants `reports` to Company, Company Admin, HR, Accountant, and Supervisor accounts, while export is separately controlled. Server-side tenant scope is established in Fleet routes and supervisor scope is applied by `_supervisor_courier_scope` / `_courier_ids`. `GET /hr/financial/branches` is restricted to `COMPANY_ROLES`, so commercial client rate, client revenue, and margin do not currently reach a Supervisor. This restriction must be preserved by any new analytics API and frontend tab visibility.

| Role | Existing reporting capability | Required treatment in the new module |
|---|---|---|
| Company / Company Admin | Tenant report and financial access | Full allowed tenant scope; commercial analytics permitted. |
| HR | Operational/workforce/payroll/reports permissions | No new commercial revenue or margin exposure. |
| Accountant | Payroll/reports/export permissions | Financial report only when existing financial role policy explicitly permits it; otherwise deny. |
| Operations | Existing operational permission model | Operational analytics only within current permission policy. |
| Supervisor | Team-scoped reports | Force existing server-side team predicate after every requested filter; hide and deny commercial metrics. |

## Confirmed duplication and design risks

The current summary routes already reuse the financial engine for payroll and branch economics. The principal report gap is not a missing formula; it is a missing read-only aggregation layer that composes existing sources consistently. Creating JavaScript totals or another financial engine would violate the current architecture.

There are clear scale risks in the legacy report center: `/hr/couriers`, `/fleet/couriers`, `/hr/daily-report`, and `/fleet/reports` can build full in-memory lists. The reusable `/fleet/couriers/paged` route demonstrates the intended pattern for detailed tables. `DailyLog` is unique by `(courier_id, log_date, project_id)` and migration already adds `ix_daily_logs_courier_date_project`, but high-volume analytics will benefit from a tenant/project/date reporting index. Attendance has a courier/check-in index. Snapshot tables have FK indexes but no explicit tenant/month/project/branch aggregation index. Any schema change must be additive, targeted, and introduced only if benchmarked report queries require it.

## Exact expected implementation scope

The expected implementation is limited to the following files, unless the audit discovers a small read-only integration correction:

| File | Expected change |
|---|---|
| `app/services/reporting.py` | New read-only report composition service built exclusively on the authoritative sources listed above. |
| `app/routers/fleet.py` | Protected reporting filters, executive/operations/workforce endpoints, and existing permission reuse. |
| `app/routers/hr.py` | Only if a company-only financial analytics wrapper is needed around `financial_rows`; no payroll rule change. |
| `app/models/entities.py` and `app/migrations.py` | Only additive report indexes if query plans or acceptance scale tests establish a need. |
| `static/fleet.html` | Reporting-only navigation, shared filter bar, report tables/charts, empty/error states, and CSV buttons using protected APIs. |
| `static/i18n.js` | Translation entries for new report UI only. |
| `tools/test_analytics_reporting.py` | Isolated acceptance: filters, reconciliation, RBAC, snapshots, pagination, and exports. |
| `docs/PHASE1_ANALYTICS_REPORTING_*.md` | Audit, implementation report, and acceptance matrix. |

## Audit decision

Proceed with one read-only reporting composition layer and one reporting-only frontend module. Reuse existing payroll and financial services exactly as they are. Preserve Supervisor isolation by applying it inside every reporting query rather than trusting frontend cascades. Do not modify any non-reporting behavior.
