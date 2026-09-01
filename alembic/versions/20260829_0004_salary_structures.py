"""Add salary structures, components, and rider assignments.

Revision ID: 20260829_0004
Revises: 20260829_0003
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0004"
down_revision: Union[str, Sequence[str], None] = "20260829_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "salary_structures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("description_ar", sa.Text()),
        sa.Column("description_en", sa.Text()),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'SAR'")),
        sa.Column("cycle", sa.String(length=20), nullable=False, server_default=sa.text("'MONTHLY'")),
        sa.Column("balance_period", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.String(length=20), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_salary_structure_tenant_code"),
    )
    op.create_index("ix_salary_structures_tenant_id", "salary_structures", ["tenant_id"])
    op.create_index("ix_salary_structure_tenant_active", "salary_structures", ["tenant_id", "is_active"])

    op.create_table(
        "salary_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("salary_structure_id", sa.Integer(), sa.ForeignKey("salary_structures.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("category", sa.String(length=30), nullable=False, server_default=sa.text("'BASE'")),
        sa.Column("calculation", sa.String(length=30), nullable=False, server_default=sa.text("'FLAT'")),
        sa.Column("amount", sa.Float(), nullable=False, server_default=sa.text("'0.0'")),
        sa.Column("cap_amount", sa.Float()),
        sa.Column("conditions", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "salary_structure_id", "code", name="uq_salary_component_code"),
    )
    op.create_index("ix_salary_components_tenant_id", "salary_components", ["tenant_id"])
    op.create_index("ix_salary_components_structure_id", "salary_components", ["salary_structure_id"])

    op.create_table(
        "rider_salary_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("salary_structure_id", sa.Integer(), sa.ForeignKey("salary_structures.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("courier_id", "salary_structure_id", "effective_from", name="uq_rider_salary_start"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_rider_salary_dates"),
    )
    op.create_index("ix_rider_salary_tenant_id", "rider_salary_assignments", ["tenant_id"])
    op.create_index("ix_rider_salary_courier_id", "rider_salary_assignments", ["courier_id"])
    op.create_index("ix_rider_salary_structure_id", "rider_salary_assignments", ["salary_structure_id"])
    op.create_index("ix_rider_salary_tenant_courier", "rider_salary_assignments", ["tenant_id", "courier_id"])
    op.create_index("ix_rider_salary_structure_dates", "rider_salary_assignments", ["salary_structure_id", "effective_from", "effective_to"])


def downgrade() -> None:
    op.drop_table("rider_salary_assignments")
    op.drop_table("salary_components")
    op.drop_table("salary_structures")
