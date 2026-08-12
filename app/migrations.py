"""Migrations خفيفة تلقائية — تضيف أعمدة جديدة للجداول الموجودة
دون فقدان البيانات. تُنفذ عند تشغيل التطبيق."""
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
    "contracts": {
        "end_date": "TIMESTAMP",
        "project_id": "INTEGER",
    },
    "projects": {"manager_id": "INTEGER"},
    "attendances": {
        "check_out_lat": "FLOAT",
        "check_out_lng": "FLOAT",
    },
    "tenants": {
        "plan": "VARCHAR(20) DEFAULT 'PRO'",
        "monthly_fee": "FLOAT DEFAULT 0",
        "billing_day": "INTEGER DEFAULT 1",
        "due_date": "TIMESTAMP",
        "subscription_status": "VARCHAR(20) DEFAULT 'ACTIVE'",
        "last_paid_at": "TIMESTAMP",
        "last_activity_at": "TIMESTAMP",
    },
}


def run_migrations(engine):
    """يضيف أي عمود ناقص. آمن لإعادة التشغيل (IF NOT EXISTS)."""
    with engine.begin() as conn:
        for table, cols in MIGRATIONS.items():
            existing = set()
            for row in conn.execute(text(
                f"PRAGMA table_info({table})" if engine.dialect.name == "sqlite"
                else f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'"
            )).fetchall():
                existing.add(row[1] if engine.dialect.name == "sqlite" else row[0])
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}'))
                    print(f"   ➕ migration: {table}.{col}")
        # توسيع enum userrole بأدوار الشركة (PostgreSQL)
        if engine.dialect.name == "postgresql":
            for role in ("SUPERVISOR", "COMPANY_ADMIN", "OPERATIONS", "HR", "ACCOUNTANT", "VIEWER", "PROJECT_MANAGER"):
                has = conn.execute(text(
                    "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid "
                    f"WHERE t.typname='userrole' AND e.enumlabel='{role}'"
                )).first()
                if not has:
                    conn.execute(text(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{role}'"))
                    print(f"   ➕ migration: userrole enum + {role}")
        # توسيع عمود action في audit_logs إلى TEXT حتى يسع رسائل السجل الطويلة
        if engine.dialect.name == "postgresql":
            t = conn.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name='audit_logs' AND column_name='action'"
            )).scalar()
            if t and t != "text":
                conn.execute(text("ALTER TABLE audit_logs ALTER COLUMN action TYPE TEXT"))
                print("   ➕ migration: audit_logs.action -> TEXT")
        # خطط البونص على مستوى المشروع: courier_id اختياري (NULL = خطة مشروع عامة)
        if engine.dialect.name == "postgresql":
            nn = conn.execute(text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='bonus_plans' AND column_name='courier_id'"
            )).scalar()
            if nn == "NO":
                conn.execute(text("ALTER TABLE bonus_plans ALTER COLUMN courier_id DROP NOT NULL"))
                print("   ➕ migration: bonus_plans.courier_id nullable")
            # فهرس فريد: خطة مشروع عامة واحدة لكل (tenant, project) — بدلاً من القيد القديم
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_bonus_project "
                "ON bonus_plans (tenant_id, project_id) WHERE courier_id IS NULL"
            ))
            print("   ➕ migration: uq_bonus_project index")
