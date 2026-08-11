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
