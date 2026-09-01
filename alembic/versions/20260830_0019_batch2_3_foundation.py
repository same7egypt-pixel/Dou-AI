"""Batch 2+3: capacity, attendance correction, data health.

Revision ID: 20260830_0019
Revises: 20260830_0018
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260830_0019"
down_revision: Union[str, Sequence[str], None] = "20260830_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("capacity_requirements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.Integer, nullable=False),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("shifts.id"), nullable=True, index=True),
        sa.Column("required_riders", sa.Integer, nullable=False, server_default="0"),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "scope_type", "scope_id", "shift_id", "effective_from",
                            name="uq_capacity_requirement"),
        sa.Index("ix_capacity_tenant_scope", "tenant_id", "scope_type", "scope_id"),
    )

    op.create_table("attendance_corrections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("attendance_id", sa.Integer, sa.ForeignKey("attendances.id"), nullable=False, index=True),
        sa.Column("courier_id", sa.Integer, sa.ForeignKey("couriers.id"), nullable=False, index=True),
        sa.Column("requested_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("original_check_in", sa.DateTime, nullable=True),
        sa.Column("original_check_out", sa.DateTime, nullable=True),
        sa.Column("corrected_check_in", sa.DateTime, nullable=True),
        sa.Column("corrected_check_out", sa.DateTime, nullable=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        sa.Column("review_note", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Index("ix_attendance_correction_status", "tenant_id", "status"),
    )

    op.create_table("data_health_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("last_successful_sync", sa.DateTime, nullable=True),
        sa.Column("last_failed_sync", sa.DateTime, nullable=True),
        sa.Column("last_sync_status", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("rows_processed", sa.Integer, nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("freshness_seconds", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source", name="uq_data_health_source"),
        sa.Index("ix_data_health_tenant_source", "tenant_id", "source"),
    )


def downgrade() -> None:
    op.drop_table("data_health_snapshots")
    op.drop_table("attendance_corrections")
    op.drop_table("capacity_requirements")
