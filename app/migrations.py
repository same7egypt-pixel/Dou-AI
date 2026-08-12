"""Migrations خفيفة تلقائية — تضيف أعمدة جديدة للجداول الموجودة
دون فقدان البيانات. تُنفذ عند تشغيل التطبيق."""
from sqlalchemy import text

# الأعمدة الجديدة لكل جدول: {table: {column: "DDL TYPE"}}
MIGRATIONS = {
    "couriers": {
        "base_salary": "FLOAT DEFAULT 0",
        "per_delivery_rate": "FLOAT DEFAULT 6",
        "bonus_target": "FLOAT DEFAULT 0",
        "employment_status": "VARCHAR(20) DEFAULT 'ACTIVE'",
        "hired_at": "TIMESTAMP",
        "bank_iban": "VARCHAR(34)",
        "supervisor_id": "INTEGER",
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
    },
    "contracts": {
        "end_date": "TIMESTAMP",
    },
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
        # توسيع enum userrole بقيمة SUPERVISOR إن لم تكن موجودة (PostgreSQL)
        if engine.dialect.name == "postgresql":
            has = conn.execute(text(
                "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid "
                "WHERE t.typname='userrole' AND e.enumlabel='SUPERVISOR'"
            )).first()
            if not has:
                conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'SUPERVISOR'"))
                print("   ➕ migration: userrole enum + SUPERVISOR")
        # توسيع عمود action في audit_logs إلى TEXT حتى يسع رسائل السجل الطويلة
        if engine.dialect.name == "postgresql":
            t = conn.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name='audit_logs' AND column_name='action'"
            )).scalar()
            if t and t != "text":
                conn.execute(text("ALTER TABLE audit_logs ALTER COLUMN action TYPE TEXT"))
                print("   ➕ migration: audit_logs.action -> TEXT")
