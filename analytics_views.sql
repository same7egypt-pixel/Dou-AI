-- W10: Analytics Data Layer
-- SQL Views for Embedded Analytics (Metabase OSS)
-- These views enforce tenant isolation via parameterized queries
-- Tenant ID must be provided via Metabase variable or filter

-- ============================================================
-- WORKFORCE ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_workforce AS
SELECT
    c.id AS rider_id,
    c.tenant_id,
    c.name AS rider_name,
    c.phone,
    c.employment_status,
    c.courier_type,
    c.city_id,
    gc.name AS city_name,
    c.contract_branch_id,
    cb.city AS branch_city,
    cb.name AS branch_name,
    c.primary_project_id,
    COALESCE(p.name, c.platform) AS project_name,
    c.supervisor_id,
    u.name AS supervisor_name,
    c.is_online,
    c.created_at AS rider_since,
    c.iqama_expiry,
    c.license_expiry,
    c.vehicle_license_expiry,
    c.passport_expiry,
    c.insurance_expiry,
    c.inspection_expiry,
    c.work_permit_expiry,
    CASE
        WHEN NOT c.documents_valid THEN 'CRITICAL'
        WHEN c.iqama_expiry < date('now') OR c.license_expiry < date('now') OR c.vehicle_license_expiry < date('now') THEN 'EXPIRED'
        WHEN c.iqama_expiry <= date('now', '+30 days') OR c.license_expiry <= date('now', '+30 days') OR c.vehicle_license_expiry <= date('now', '+30 days') THEN 'EXPIRING_SOON'
        ELSE 'OK'
    END AS document_status
FROM couriers c
LEFT JOIN geo_cities gc ON c.city_id = gc.id
LEFT JOIN contract_branches cb ON c.contract_branch_id = cb.id
LEFT JOIN projects p ON c.primary_project_id = p.id
LEFT JOIN users u ON c.supervisor_id = u.id;


-- ============================================================
-- ATTENDANCE ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_attendance AS
SELECT
    a.id,
    a.tenant_id,
    a.courier_id,
    c.name AS rider_name,
    a.check_in,
    a.check_out,
    CASE WHEN a.check_out IS NOT NULL THEN
        ROUND((julianday(a.check_out) - julianday(a.check_in)) * 24, 2)
    ELSE 0 END AS worked_hours,
    a.is_late,
    a.shift_id,
    DATE(a.check_in) AS attendance_date,
    c.city_id,
    gc.name AS city_name,
    c.contract_branch_id,
    cb.city AS branch_city,
    c.primary_project_id,
    COALESCE(p.name, c.platform) AS project_name
FROM attendances a
JOIN couriers c ON a.courier_id = c.id
LEFT JOIN geo_cities gc ON c.city_id = gc.id
LEFT JOIN contract_branches cb ON c.contract_branch_id = cb.id
LEFT JOIN projects p ON c.primary_project_id = p.id;


-- ============================================================
-- RIDER PERFORMANCE ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_rider_performance AS
SELECT
    c.id AS rider_id,
    c.tenant_id,
    c.name AS rider_name,
    c.employment_status,
    c.city_id,
    gc.name AS city_name,
    c.contract_branch_id,
    cb.city AS branch_city,
    c.primary_project_id,
    COALESCE(p.name, c.platform) AS project_name,
    c.supervisor_id,
    u.name AS supervisor_name,
    dl.log_date,
    COALESCE(dl.orders_count, 0) AS orders_count,
    COALESCE(dl.delivery_fee, 0) AS delivery_fee
FROM couriers c
LEFT JOIN geo_cities gc ON c.city_id = gc.id
LEFT JOIN contract_branches cb ON c.contract_branch_id = cb.id
LEFT JOIN projects p ON c.primary_project_id = p.id
LEFT JOIN users u ON c.supervisor_id = u.id
LEFT JOIN daily_logs dl ON c.id = dl.courier_id;


-- ============================================================
-- PAYROLL ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_payroll AS
SELECT
    pir.id,
    pir.tenant_id,
    pir.courier_id,
    c.name AS rider_name,
    pir.month,
    pir.source_type,
    pir.source_id,
    pir.input_type,
    pir.amount,
    pir.description,
    pir.status,
    pir.reversal_of_id,
    CASE WHEN pir.reversal_of_id IS NOT NULL THEN 1 ELSE 0 END AS is_reversal,
    c.city_id,
    gc.name AS city_name,
    c.contract_branch_id,
    cb.city AS branch_city,
    c.primary_project_id,
    COALESCE(p.name, c.platform) AS project_name,
    c.supervisor_id,
    u.name AS supervisor_name
FROM payroll_input_records pir
JOIN couriers c ON pir.courier_id = c.id
LEFT JOIN geo_cities gc ON c.city_id = gc.id
LEFT JOIN contract_branches cb ON c.contract_branch_id = cb.id
LEFT JOIN projects p ON c.primary_project_id = p.id
LEFT JOIN users u ON c.supervisor_id = u.id;


-- ============================================================
-- DOCUMENTS ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_documents AS
SELECT
    c.id AS rider_id,
    c.tenant_id,
    c.name AS rider_name,
    c.employment_status,
    c.city_id,
    gc.name AS city_name,
    c.contract_branch_id,
    cb.city AS branch_city,
    c.primary_project_id,
    COALESCE(p.name, c.platform) AS project_name,
    c.supervisor_id,
    u.name AS supervisor_name,
    c.iqama_number,
    c.iqama_expiry,
    CASE WHEN c.iqama_expiry < date('now') THEN 'EXPIRED'
         WHEN c.iqama_expiry <= date('now', '+30 days') THEN 'EXPIRING_SOON'
         ELSE 'OK' END AS iqama_status,
    c.license_expiry,
    CASE WHEN c.license_expiry < date('now') THEN 'EXPIRED'
         WHEN c.license_expiry <= date('now', '+30 days') THEN 'EXPIRING_SOON'
         ELSE 'OK' END AS license_status,
    c.passport_expiry,
    c.vehicle_license_expiry,
    c.insurance_expiry,
    c.inspection_expiry,
    c.work_permit_expiry,
    c.documents_valid
FROM couriers c
LEFT JOIN geo_cities gc ON c.city_id = gc.id
LEFT JOIN contract_branches cb ON c.contract_branch_id = cb.id
LEFT JOIN projects p ON c.primary_project_id = p.id
LEFT JOIN users u ON c.supervisor_id = u.id;


-- ============================================================
-- VEHICLES ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_vehicles AS
SELECT
    v.id AS vehicle_id,
    v.tenant_id,
    v.plate_number,
    v.vehicle_type,
    v.make,
    v.model,
    v.year,
    v.color,
    v.insurance_expiry,
    v.registration_expiry,
    v.status,
    v.assigned_courier_id,
    c.name AS assigned_rider_name,
    c.phone AS assigned_rider_phone,
    c.city_id,
    gc.name AS city_name,
    c.contract_branch_id,
    cb.city AS branch_city
FROM vehicles v
LEFT JOIN couriers c ON v.assigned_courier_id = c.id
LEFT JOIN geo_cities gc ON c.city_id = gc.id
LEFT JOIN contract_branches cb ON c.contract_branch_id = cb.id;


-- ============================================================
-- IMPORT HEALTH ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_import_health AS
SELECT
    oib.id AS batch_id,
    oib.tenant_id,
    oib.batch_type,
    oib.file_name,
    oib.total_rows,
    oib.processed_rows,
    oib.valid_rows,
    oib.invalid_rows,
    oib.duplicate_rows,
    oib.status,
    oib.created_at,
    oib.created_by,
    u.name AS created_by_name,
    CASE WHEN oib.total_rows > 0 THEN
        ROUND(oib.valid_rows * 100.0 / oib.total_rows, 2)
    ELSE 0 END AS success_rate
FROM operational_import_batches oib
LEFT JOIN users u ON oib.created_by = u.id;


-- ============================================================
-- RECONCILIATION ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_reconciliation AS
SELECT
    rr.id,
    rr.tenant_id,
    rr.batch_id,
    rr.courier_id,
    c.name AS rider_name,
    rr.expected_amount,
    rr.actual_amount,
    CASE WHEN rr.actual_amount IS NOT NULL THEN
        ROUND(rr.actual_amount - rr.expected_amount, 2)
    ELSE NULL END AS difference,
    rr.status,
    rr.reconciled_at
FROM reconciliation_results rr
LEFT JOIN couriers c ON rr.courier_id = c.id;


-- ============================================================
-- OPERATIONAL ORDERS ANALYTICS
-- ============================================================
CREATE VIEW IF NOT EXISTS analytics_orders AS
SELECT
    o.id AS order_id,
    o.tenant_id,
    o.courier_id,
    c.name AS rider_name,
    o.order_number,
    o.status,
    o.total_amount,
    o.delivery_fee,
    o.distance,
    o.pickup_time,
    o.delivery_time,
    o.cancellation_reason,
    o.created_at,
    DATE(o.created_at) AS order_date,
    c.city_id,
    gc.name AS city_name,
    c.contract_branch_id,
    cb.city AS branch_city,
    c.primary_project_id,
    COALESCE(p.name, c.platform) AS project_name
FROM orders o
LEFT JOIN couriers c ON o.courier_id = c.id
LEFT JOIN geo_cities gc ON c.city_id = gc.id
LEFT JOIN contract_branches cb ON c.contract_branch_id = cb.id
LEFT JOIN projects p ON c.primary_project_id = p.id;
