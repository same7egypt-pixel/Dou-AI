"""Add tenant-owned vehicles, documents, and rider assignments.

Revision ID: 20260829_0003
Revises: 20260829_0002
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0003"
down_revision: Union[str, Sequence[str], None] = "20260829_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("market_code", sa.String(length=2), nullable=False),
        sa.Column("plate_number", sa.String(length=40), nullable=False),
        sa.Column("plate_normalized", sa.String(length=40), nullable=False),
        sa.Column("vehicle_type", sa.String(length=30), nullable=False),
        sa.Column("make", sa.String(length=60)),
        sa.Column("model", sa.String(length=60)),
        sa.Column("model_year", sa.Integer()),
        sa.Column("operational_status", sa.String(length=30), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("compliance_status", sa.String(length=30), nullable=False, server_default=sa.text("'MISSING'")),
        sa.Column("is_exclusive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "market_code", "plate_normalized", name="uq_vehicle_tenant_market_plate"),
    )
    op.create_index("ix_vehicles_tenant_id", "vehicles", ["tenant_id"])
    op.create_index("ix_vehicle_tenant_operational", "vehicles", ["tenant_id", "operational_status"])

    op.create_table(
        "vehicle_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("document_number", sa.String(length=80)),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'VALID'")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Index("ix_vehicle_document_tenant_vehicle", "tenant_id", "vehicle_id"),
    )

    op.create_table(
        "rider_vehicle_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vehicle_id", "courier_id", "effective_from", name="uq_rider_vehicle_start"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_rider_vehicle_dates"),
    )
    op.create_index("ix_rider_vehicle_assignments_tenant_id", "rider_vehicle_assignments", ["tenant_id"])
    op.create_index("ix_rider_vehicle_assignments_vehicle_id", "rider_vehicle_assignments", ["vehicle_id"])
    op.create_index("ix_rider_vehicle_assignments_courier_id", "rider_vehicle_assignments", ["courier_id"])
    op.create_index("ix_rider_vehicle_tenant_rider", "rider_vehicle_assignments", ["tenant_id", "courier_id"])
    op.create_index("ix_rider_vehicle_vehicle_dates", "rider_vehicle_assignments", ["vehicle_id", "effective_from", "effective_to"])


def downgrade() -> None:
    op.drop_table("rider_vehicle_assignments")
    op.drop_table("vehicle_documents")
    op.drop_table("vehicles")
