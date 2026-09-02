-- Analytics view layer for embedded BI (Metabase).
--
-- Metabase never queries the operational tables directly. It sees only these
-- views, for two reasons:
--
--   1. Tenant isolation. Every view exposes tenant_id, and the embed token
--      locks a dashboard filter to one tenant. A view without tenant_id cannot
--      be filtered and must not exist here.
--
--   2. One source of truth for money. A dashboard that recomputes payroll in
--      SQL will drift from app/services/financial_calculations.py, and the
--      report will disagree with the payroll screen. analytics_payroll
--      therefore reads finalized snapshots -- what the engine actually paid --
--      instead of deriving pay again.
--
-- Loaded by app/analytics_views.py during migration. Two dialect seams are
-- marked with {{...}} placeholders and substituted there; keep them if you edit
-- this file, and do not add new SQLite-only functions.

-- ============================================================
-- WORKFORCE: the rider roster, joined to its operating structure
-- ============================================================
CREATE VIEW analytics_workforce AS
SELECT
    c.id                AS rider_id,
    c.tenant_id,
    c.name              AS rider_name,
    c.phone,
    c.employment_status,
    c.courier_type,
    c.city_id,
    c.work_city,
    c.contract_branch_id,
    cb.branch_name,
    cb.city             AS branch_city,
    c.contract_id,
    ct.name             AS contract_name,
    c.primary_project_id,
    p.name              AS project_name,
    c.supervisor_id,
    u.name              AS supervisor_name,
    c.documents_valid,
    c.is_online,
    c.shift_active,
    c.hired_at,
    c.created_at
FROM couriers c
LEFT JOIN contract_branches cb ON cb.id = c.contract_branch_id
LEFT JOIN contracts        ct ON ct.id = c.contract_id
LEFT JOIN projects          p ON p.id = c.primary_project_id
LEFT JOIN users             u ON u.id = c.supervisor_id;

-- ============================================================
-- ATTENDANCE: check-ins with worked hours
-- attendances has no tenant_id of its own; it inherits through the rider.
-- ============================================================
CREATE VIEW analytics_attendance AS
SELECT
    a.id                AS attendance_id,
    c.tenant_id,
    a.courier_id        AS rider_id,
    c.name              AS rider_name,
    c.contract_branch_id,
    cb.branch_name,
    c.supervisor_id,
    a.shift_id,
    a.check_in,
    a.check_out,
    {{HOURS_BETWEEN:a.check_in:a.check_out}} AS worked_hours,
    a.is_late,
    CASE WHEN a.check_out IS NULL THEN 1 ELSE 0 END AS still_open
FROM attendances a
JOIN couriers c          ON c.id = a.courier_id
LEFT JOIN contract_branches cb ON cb.id = c.contract_branch_id;

-- ============================================================
-- RIDER PERFORMANCE: daily order counts as recorded operationally
-- ============================================================
CREATE VIEW analytics_rider_performance AS
SELECT
    dl.id               AS log_id,
    dl.tenant_id,
    dl.courier_id       AS rider_id,
    c.name              AS rider_name,
    c.courier_type,
    c.contract_branch_id,
    cb.branch_name,
    cb.city             AS branch_city,
    c.supervisor_id,
    u.name              AS supervisor_name,
    dl.project_id,
    dl.log_date,
    dl.orders_count,
    dl.source_type,
    c.bonus_target      AS monthly_target
FROM daily_logs dl
JOIN couriers c          ON c.id = dl.courier_id
LEFT JOIN contract_branches cb ON cb.id = c.contract_branch_id
LEFT JOIN users             u ON u.id = c.supervisor_id;

-- ============================================================
-- PAYROLL: finalized snapshots only.
-- Deliberately not a recomputation. A finalized month is what was paid, and
-- reading the snapshot is the only way BI and the payroll screen can agree.
-- ============================================================
CREATE VIEW analytics_payroll AS
SELECT
    ps.id               AS snapshot_id,
    ps.tenant_id,
    pp.month            AS payroll_month,
    pp.status           AS period_status,
    pp.finalized_at,
    ps.courier_id       AS rider_id,
    c.name              AS rider_name,
    c.courier_type,
    ps.contract_branch_id,
    cb.branch_name,
    cb.city             AS branch_city,
    ps.project_id,
    c.supervisor_id,
    ps.base_salary,
    ps.delivery_pay,
    ps.bonus_pay,
    ps.additions,
    ps.deductions,
    ps.net_pay
FROM payroll_snapshots ps
JOIN payroll_periods pp  ON pp.id = ps.payroll_period_id
JOIN couriers c          ON c.id = ps.courier_id
LEFT JOIN contract_branches cb ON cb.id = ps.contract_branch_id;

-- ============================================================
-- DOCUMENTS: compliance and expiry, the platform-facing risk view
-- ============================================================
CREATE VIEW analytics_documents AS
SELECT
    d.id                AS document_id,
    d.tenant_id,
    d.owner_type,
    d.owner_id,
    d.document_type_id,
    dt.code             AS document_type_code,
    dt.name_ar          AS document_type_ar,
    dt.name_en          AS document_type_en,
    dt.category         AS document_category,
    d.status,
    d.scan_status,
    d.expiry_date,
    d.reviewed_at,
    d.created_at
FROM documents d
LEFT JOIN document_types dt ON dt.id = d.document_type_id;

-- ============================================================
-- VEHICLES: fleet registry and compliance
-- ============================================================
CREATE VIEW analytics_vehicles AS
SELECT
    v.id                AS vehicle_id,
    v.tenant_id,
    v.plate_number,
    v.vehicle_type,
    v.make,
    v.model,
    v.model_year,
    v.operational_status,
    v.compliance_status,
    v.is_exclusive,
    v.created_at
FROM vehicles v;

-- ============================================================
-- IMPORT HEALTH: are the platform feeds landing cleanly?
-- ============================================================
CREATE VIEW analytics_import_health AS
SELECT
    b.id                AS batch_id,
    b.tenant_id,
    b.import_type,
    b.status,
    b.file_name,
    b.source_label,
    b.total_rows,
    b.valid_rows,
    b.invalid_rows,
    b.warning_rows,
    b.confirmed_at,
    b.created_at
FROM operational_import_batches b;

-- ============================================================
-- RECONCILIATION: source counts against accepted counts
-- ============================================================
CREATE VIEW analytics_reconciliation AS
SELECT
    r.id                AS reconciliation_id,
    r.tenant_id,
    r.source_platform_id,
    sp.code             AS source_platform_code,
    sp.name_ar          AS source_platform_ar,
    r.reconciliation_date,
    r.source_total_count,
    r.accepted_count,
    r.rejected_count,
    r.duplicate_count,
    r.unmapped_count,
    r.missing_count,
    r.total_revenue_source,
    r.total_revenue_accepted,
    r.status,
    r.created_at
FROM reconciliation_results r
LEFT JOIN source_platforms sp ON sp.id = r.source_platform_id;

-- ============================================================
-- PLATFORM FACTS: the daily aggregate each delivery platform reports
-- ============================================================
CREATE VIEW analytics_platform_facts AS
SELECT
    f.id                AS fact_id,
    f.tenant_id,
    f.contract_id,
    f.contract_name,
    f.created_date,
    f.city_name,
    f.riders_count,
    f.shifts_done,
    f.planned_hours,
    f.actual_working_hours,
    f.break_hours,
    f.acceptance_rate,
    f.notified_deliveries,
    f.accepted_deliveries,
    f.completed_deliveries,
    f.declined_deliveries,
    f.cancelled_deliveries,
    f.no_shows,
    f.source_type
FROM platform_delivery_facts f;
