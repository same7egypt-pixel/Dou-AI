"""Add leave management: types, policies, entitlements.

Revision ID: 20260829_0006
Revises: 20260829_0005
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0006"
down_revision: Union[str, Sequence[str], None] = "20260829_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leave_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("description_ar", sa.String(length=300)),
        sa.Column("description_en", sa.String(length=300)),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_days_per_year", sa.Integer()),
        sa.Column("requires_document", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_leave_type_tenant_code"),
    )
    op.create_index("ix_leave_types_tenant_id", "leave_types", ["tenant_id"])
    op.create_index("ix_leave_type_tenant_active", "leave_types", ["tenant_id", "is_active"])

    op.create_table(
        "leave_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("leave_type_id", sa.Integer(), sa.ForeignKey("leave_types.id"), nullable=False),
        sa.Column("entitlement_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("carryover_limit", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_consecutive_days", sa.Integer()),
        sa.Column("min_days_notice", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("accrual_frequency", sa.String(length=20), nullable=False, server_default=sa.text("'YEARLY'")),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "leave_type_id", name="uq_leave_policy_tenant_type"),
    )
    op.create_index("ix_leave_policies_tenant_id", "leave_policies", ["tenant_id"])
    op.create_index("ix_leave_policy_tenant_active", "leave_policies", ["tenant_id", "is_active"])

    op.create_table(
        "leave_entitlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("leave_type_id", sa.Integer(), sa.ForeignKey("leave_types.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("entitled_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("carried_over_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("used_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("pending_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "courier_id", "leave_type_id", "year", name="uq_leave_entitlement"),
    )
    op.create_index("ix_leave_entitlements_tenant_id", "leave_entitlements", ["tenant_id"])
    op.create_index("ix_leave_entitlement_tenant_courier", "leave_entitlements", ["tenant_id", "courier_id"])

    # Add leave_type_id to existing leave_requests table
    op.add_column("leave_requests", sa.Column("leave_type_id", sa.Integer(), sa.ForeignKey("leave_types.id")))
    op.create_index("ix_leave_requests_leave_type_id", "leave_requests", ["leave_type_id"])


def downgrade() -> None:
    op.drop_index("ix_leave_requests_leave_type_id", table_name="leave_requests")
    op.drop_column("leave_requests", "leave_type_id")
    op.drop_table("leave_entitlements")
    op.drop_table("leave_policies")
    op.drop_table("leave_types")
