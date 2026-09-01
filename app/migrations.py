"""Legacy Phase 1 compatibility migrations.

These operations run only once when ``tools/migrate.py`` adopts an unversioned
database into the Alembic baseline. All schema changes after baseline revision
``20260829_0001`` must be implemented as versioned Alembic revisions.
"""

from sqlalchemy import text

# الأعمدة الجديدة لكل جدول: {table: {column: "DDL TYPE"}}
MIGRATIONS = {
    "users": {
        "token_version": "INTEGER DEFAULT 0",
        "last_login_at": "TIMESTAMP",
        "custom_permissions": "TEXT",
        "managed_project_ids": "TEXT",
    },
    "couriers": {
        "base_salary": "FLOAT DEFAULT 0",
        "per_delivery_rate": "FLOAT DEFAULT 6",
        "bonus_target": "FLOAT DEFAULT 0",
        "employment_status": "VARCHAR(20) DEFAULT 'ACTIVE'",
        "hired_at": "TIMESTAMP",
        "bank_iban": "VARCHAR(34)",
        "nationality": "VARCHAR(60)",
        "iqama_number": "VARCHAR(40)",
        "emergency_name": "VARCHAR(120)",
        "emergency_phone": "VARCHAR(40)",
        "passport_number": "VARCHAR(40)",
        "passport_expiry": "DATE",
        "insurance_expiry": "DATE",
        "inspection_expiry": "DATE",
        "work_permit_expiry": "DATE",
        "supervisor_id": "INTEGER",
        "primary_project_id": "INTEGER",
        "contract_id": "INTEGER",
        "contract_branch_id": "INTEGER",
        "city_id": "INTEGER",
        "work_city": "VARCHAR(120)",
        "platform": "VARCHAR(60)",
        "platform_courier_id": "VARCHAR(60)",
        "iqama_expiry": "DATE",
        "license_expiry": "DATE",
        "vehicle_license_expiry": "DATE",
        "vehicle_type": "VARCHAR(60)",
        "vehicle_plate": "VARCHAR(40)",
        "zone": "VARCHAR(120)",
        "photo_url": "VARCHAR(300)",
        "is_on_leave": "BOOLEAN DEFAULT FALSE",
        "shift_started_at": "TIMESTAMP",
        "shift_preference": "VARCHAR(120)",
    },
    "bonus_plans": {
        "contract_branch_id": "INTEGER",
        "is_active": "BOOLEAN DEFAULT TRUE",
        "effective_from": "DATE",
        "effective_to": "DATE",
    },
    "contract_branches": {"city_id": "INTEGER"},
    "tenant_operating_cities": {"display_name": "VARCHAR(120)"},
    "contracts": {
        "start_date": "TIMESTAMP",
        "end_date": "TIMESTAMP",
        "project_id": "INTEGER",
        "scope_type": "VARCHAR(20) DEFAULT 'PROJECT'",
        "courier_ids": "TEXT",
        "client_name": "VARCHAR(120)",
        "client_rate_per_order": "FLOAT",
        "client_rate_effective_from": "DATE",
    },
    "projects": {"manager_id": "INTEGER"},
    "shifts": {
        "courier_ids": "TEXT",
    },
    "payroll_adjustments": {
        "source_type": "VARCHAR(40)",
        "source_id": "INTEGER",
        "idempotency_key": "VARCHAR(180)",
        "status": "VARCHAR(20) DEFAULT 'APPROVED'",
    },
    "attendances": {
        "check_out_lat": "FLOAT",
        "check_out_lng": "FLOAT",
    },
    "daily_logs": {
        "source_type": "VARCHAR(30) DEFAULT 'MANUAL'",
        "source_batch_id": "INTEGER",
        "source_row_key": "VARCHAR(180)",
    },
    "tenants": {
        "plan": "VARCHAR(20) DEFAULT 'PRO'",
        "monthly_fee": "FLOAT DEFAULT 0",
        "billing_day": "INTEGER DEFAULT 1",
        "due_date": "TIMESTAMP",
        "subscription_status": "VARCHAR(20) DEFAULT 'ACTIVE'",
        "last_paid_at": "TIMESTAMP",
        "last_activity_at": "TIMESTAMP",
        "market_code": "VARCHAR(2) DEFAULT 'SA'",
        "default_language": "VARCHAR(5) DEFAULT 'ar'",
        "currency": "VARCHAR(3) DEFAULT 'SAR'",
        "timezone": "VARCHAR(60) DEFAULT 'Asia/Riyadh'",
    },
    "subscription_plans": {
        "name_en": "VARCHAR(80)",
        "monthly_price_usd": "FLOAT DEFAULT 0",
        "features_ar": "TEXT",
        "features_en": "TEXT",
    },
    "subscription_payments": {"currency": "VARCHAR(3) DEFAULT 'SAR'"},
}


def run_migrations(engine):
    """يضيف أي عمود ناقص. آمن لإعادة التشغيل (IF NOT EXISTS)."""
    with engine.begin() as conn:
        for table, cols in MIGRATIONS.items():
            existing = set()
            for row in conn.execute(
                text(
                    f"PRAGMA table_info({table})"
                    if engine.dialect.name == "sqlite"
                    else f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'"
                )
            ).fetchall():
                existing.add(row[1] if engine.dialect.name == "sqlite" else row[0])
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    print(f"   ➕ migration: {table}.{col}")
        # أسعار دولية افتراضية للباقات الحالية؛ تظل قابلة للتعديل من إدارة DOU.
        for code, name_en, usd in (
            ("STARTER", "Starter", 149),
            ("GROWTH", "Growth", 269),
            ("BUSINESS", "Business", 499),
            ("ENTERPRISE", "Enterprise", 899),
        ):
            conn.execute(
                text(
                    "UPDATE subscription_plans SET name_en=:name WHERE code=:code AND (name_en IS NULL OR name_en='')"
                ),
                {"name": name_en, "code": code},
            )
            conn.execute(
                text(
                    "UPDATE subscription_plans SET monthly_price_usd=:usd WHERE code=:code AND (monthly_price_usd IS NULL OR monthly_price_usd=0)"
                ),
                {"usd": usd, "code": code},
            )
        # توسيع enum userrole بأدوار الشركة (PostgreSQL)
        if engine.dialect.name == "postgresql":
            for role in (
                "SUPERVISOR",
                "COMPANY_ADMIN",
                "OPERATIONS",
                "HR",
                "ACCOUNTANT",
                "VIEWER",
                "PROJECT_MANAGER",
            ):
                has = conn.execute(
                    text(
                        "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid "
                        f"WHERE t.typname='userrole' AND e.enumlabel='{role}'"
                    )
                ).first()
                if not has:
                    conn.execute(
                        text(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{role}'")
                    )
                    print(f"   ➕ migration: userrole enum + {role}")
        # توسيع عمود action في audit_logs إلى TEXT حتى يسع رسائل السجل الطويلة
        if engine.dialect.name == "postgresql":
            t = conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='audit_logs' AND column_name='action'"
                )
            ).scalar()
            if t and t != "text":
                conn.execute(
                    text("ALTER TABLE audit_logs ALTER COLUMN action TYPE TEXT")
                )
                print("   ➕ migration: audit_logs.action -> TEXT")
        # خطط البونص على مستوى المشروع: courier_id اختياري (NULL = خطة مشروع عامة)
        if engine.dialect.name == "postgresql":
            nn = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name='bonus_plans' AND column_name='courier_id'"
                )
            ).scalar()
            if nn == "NO":
                conn.execute(
                    text(
                        "ALTER TABLE bonus_plans ALTER COLUMN courier_id DROP NOT NULL"
                    )
                )
                print("   ➕ migration: bonus_plans.courier_id nullable")
            # فهرس فريد: خطة مشروع عامة واحدة لكل (tenant, project) — بدلاً من القيد القديم
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_bonus_project "
                    "ON bonus_plans (tenant_id, project_id) WHERE courier_id IS NULL"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_adjustment_idempotency "
                    "ON payroll_adjustments (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
                )
            )
            for ddl in (
                "CREATE INDEX IF NOT EXISTS ix_couriers_tenant_city ON couriers (tenant_id, city_id)",
                "CREATE INDEX IF NOT EXISTS ix_couriers_tenant_supervisor ON couriers (tenant_id, supervisor_id)",
                "CREATE INDEX IF NOT EXISTS ix_branches_tenant_city ON contract_branches (tenant_id, city_id)",
                "CREATE INDEX IF NOT EXISTS ix_daily_logs_courier_date_project ON daily_logs (courier_id, log_date, project_id)",
                "CREATE INDEX IF NOT EXISTS ix_attendances_courier_checkin ON attendances (courier_id, check_in)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_event_idempotency ON attendance_events (tenant_id, idempotency_key)",
                "CREATE INDEX IF NOT EXISTS ix_attendance_event_tenant_status_date ON attendance_events (tenant_id, status, event_date)",
                "CREATE INDEX IF NOT EXISTS ix_attendance_policy_tenant_event_active ON attendance_deduction_policies (tenant_id, event_type, is_active)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_operational_import_fingerprint ON operational_import_batches (tenant_id, import_type, fingerprint)",
                "CREATE INDEX IF NOT EXISTS ix_operational_import_tenant_type_status ON operational_import_batches (tenant_id, import_type, status)",
                "CREATE INDEX IF NOT EXISTS ix_daily_logs_tenant_source_batch ON daily_logs (tenant_id, source_batch_id)",
                "CREATE INDEX IF NOT EXISTS ix_daily_logs_tenant_date_project ON daily_logs (tenant_id, log_date, project_id)",
                "CREATE INDEX IF NOT EXISTS ix_payroll_snapshot_tenant_period_branch ON payroll_snapshots (tenant_id, payroll_period_id, contract_branch_id)",
                "CREATE INDEX IF NOT EXISTS ix_financial_snapshot_tenant_period_project ON operational_financial_snapshots (tenant_id, payroll_period_id, project_id)",
            ):
                conn.execute(text(ddl))
            print("   ➕ migration: Phase 1 operational relationship indexes")
