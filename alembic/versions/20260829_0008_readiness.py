"""Add operational readiness state.

Revision ID: 20260829_0008
Revises: 20260829_0007
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0008"
down_revision: Union[str, Sequence[str], None] = "20260829_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operational_readiness_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("overall_status", sa.String(length=20), nullable=False, server_default=sa.text("'NOT_READY'")),
        sa.Column("employment_status", sa.String(length=20), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("account_status", sa.String(length=20), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("attendance_status", sa.String(length=20), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("shift_status", sa.String(length=20), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("availability_status", sa.String(length=20), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("leave_status", sa.String(length=20), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("documents_status", sa.String(length=20), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("vehicle_compliance_status", sa.String(length=20), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("blockers", sa.Text()),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "courier_id", name="uq_readiness_state_tenant_courier"),
    )
    op.create_index("ix_readiness_states_tenant_id", "operational_readiness_states", ["tenant_id"])
    op.create_index("ix_readiness_state_tenant_status", "operational_readiness_states", ["tenant_id", "overall_status"])


def downgrade() -> None:
    op.drop_table("operational_readiness_states")
