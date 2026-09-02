"""Rider debt carry-forward, and adopt the payroll draft_overrides column.

``payroll_periods.draft_overrides`` used to be added by an ALTER TABLE inside the
FastAPI startup event. That hid a schema change from Alembic, so this revision
adopts it: the column is only added when it is missing, which makes the
revision safe on databases that already received it from the old startup hook.

Revision ID: 20260902_0021
Revises: 20260902_0020
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0021"
down_revision: Union[str, Sequence[str], None] = "20260902_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("payroll_periods", "draft_overrides"):
        with op.batch_alter_table("payroll_periods") as batch_op:
            batch_op.add_column(sa.Column("draft_overrides", sa.Text(), nullable=True))

    op.create_table(
        "courier_debts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("courier_id", sa.Integer(), nullable=False),
        sa.Column("origin_month", sa.String(length=7), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("remaining", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="OPEN"
        ),
        sa.Column("settled_month", sa.String(length=7), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["courier_id"], ["couriers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "courier_id", "origin_month", name="uq_courier_debt_origin"
        ),
    )
    op.create_index(
        "ix_courier_debts_tenant_id", "courier_debts", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_courier_debts_courier_id", "courier_debts", ["courier_id"], unique=False
    )
    op.create_index(
        "ix_courier_debt_open",
        "courier_debts",
        ["tenant_id", "courier_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_courier_debt_open", table_name="courier_debts")
    op.drop_index("ix_courier_debts_courier_id", table_name="courier_debts")
    op.drop_index("ix_courier_debts_tenant_id", table_name="courier_debts")
    op.drop_table("courier_debts")
