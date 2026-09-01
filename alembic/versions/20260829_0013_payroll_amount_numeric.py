"""Convert PayrollInputRecord.amount to Numeric(18,2) for exact monetary arithmetic.

Revision ID: 20260829_0013
Revises: 20260829_0012
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0013"
down_revision: Union[str, Sequence[str], None] = "20260829_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert amount from Float to Numeric(18,2) for exact monetary arithmetic
    # Use dialect-specific casting for PostgreSQL/Neon vs SQLite
    dialect = op.get_context().dialect.name
    
    if dialect == "postgresql":
        op.alter_column(
            "payroll_input_records",
            "amount",
            existing_type=sa.Float(),
            type_=sa.Numeric(18, 2),
            existing_nullable=False,
            postgresql_using="amount::numeric(18,2)",
        )
    elif dialect == "sqlite":
        # SQLite: recreate column with new type
        # This is safe for development/test databases
        op.execute("ALTER TABLE payroll_input_records RENAME TO payroll_input_records_old")
        op.execute("""
            CREATE TABLE payroll_input_records (
                id INTEGER NOT NULL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id),
                courier_id INTEGER NOT NULL REFERENCES couriers(id),
                month VARCHAR(7) NOT NULL,
                source_type VARCHAR(30) NOT NULL,
                source_id INTEGER,
                input_type VARCHAR(20) NOT NULL,
                amount NUMERIC(18, 2) NOT NULL,
                description VARCHAR(300),
                status VARCHAR(20) DEFAULT 'APPROVED',
                reversal_of_id INTEGER REFERENCES payroll_input_records(id),
                created_by INTEGER REFERENCES users(id),
                created_at DATETIME NOT NULL,
                updated_at DATETIME
            )
        """)
        op.execute("""
            INSERT INTO payroll_input_records 
            SELECT id, tenant_id, courier_id, month, source_type, source_id, input_type, 
                   CAST(amount AS NUMERIC(18,2)), description, status, reversal_of_id, 
                   created_by, created_at, updated_at 
            FROM payroll_input_records_old
        """)
        op.execute("DROP TABLE payroll_input_records_old")
    else:
        # Generic fallback
        op.alter_column(
            "payroll_input_records",
            "amount",
            existing_type=sa.Float(),
            type_=sa.Numeric(18, 2),
            existing_nullable=False,
        )


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    
    if dialect == "postgresql":
        op.alter_column(
            "payroll_input_records",
            "amount",
            existing_type=sa.Numeric(18, 2),
            type_=sa.Float(),
            existing_nullable=False,
            postgresql_using="amount::float",
        )
    elif dialect == "sqlite":
        op.execute("ALTER TABLE payroll_input_records RENAME TO payroll_input_records_old")
        op.execute("""
            CREATE TABLE payroll_input_records (
                id INTEGER NOT NULL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id),
                courier_id INTEGER NOT NULL REFERENCES couriers(id),
                month VARCHAR(7) NOT NULL,
                source_type VARCHAR(30) NOT NULL,
                source_id INTEGER,
                input_type VARCHAR(20) NOT NULL,
                amount FLOAT NOT NULL,
                description VARCHAR(300),
                status VARCHAR(20) DEFAULT 'APPROVED',
                reversal_of_id INTEGER REFERENCES payroll_input_records(id),
                created_by INTEGER REFERENCES users(id),
                created_at DATETIME NOT NULL,
                updated_at DATETIME
            )
        """)
        op.execute("""
            INSERT INTO payroll_input_records 
            SELECT id, tenant_id, courier_id, month, source_type, source_id, input_type, 
                   CAST(amount AS FLOAT), description, status, reversal_of_id, 
                   created_by, created_at, updated_at 
            FROM payroll_input_records_old
        """)
        op.execute("DROP TABLE payroll_input_records_old")
    else:
        op.alter_column(
            "payroll_input_records",
            "amount",
            existing_type=sa.Numeric(18, 2),
            type_=sa.Float(),
            existing_nullable=False,
        )
