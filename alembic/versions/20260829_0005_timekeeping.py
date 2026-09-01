"""Add timekeeping: shift templates, occurrences, work sessions, correction requests, overtime.

Revision ID: 20260829_0005
Revises: 20260829_0004
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0005"
down_revision: Union[str, Sequence[str], None] = "20260829_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("zone", sa.String(length=120)),
        sa.Column("start_time", sa.String(length=8), nullable=False),
        sa.Column("end_time", sa.String(length=8), nullable=False),
        sa.Column("required_couriers", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_shift_template_tenant_code"),
    )
    op.create_index("ix_shift_templates_tenant_id", "shift_templates", ["tenant_id"])
    op.create_index("ix_shift_template_tenant_active", "shift_templates", ["tenant_id", "is_active"])

    op.create_table(
        "shift_occurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("shift_template_id", sa.Integer(), sa.ForeignKey("shift_templates.id"), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("start_datetime", sa.DateTime(), nullable=False),
        sa.Column("end_datetime", sa.DateTime(), nullable=False),
        sa.Column("required_couriers", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'SCHEDULED'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("shift_template_id", "occurrence_date", name="uq_shift_occurrence_date"),
    )
    op.create_index("ix_shift_occurrences_tenant_id", "shift_occurrences", ["tenant_id"])
    op.create_index("ix_shift_occurrence_tenant_date", "shift_occurrences", ["tenant_id", "occurrence_date"])

    op.create_table(
        "work_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("shift_occurrence_id", sa.Integer(), sa.ForeignKey("shift_occurrences.id")),
        sa.Column("session_type", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime()),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_work_sessions_tenant_id", "work_sessions", ["tenant_id"])
    op.create_index("ix_work_session_tenant_courier", "work_sessions", ["tenant_id", "courier_id"])
    op.create_index("ix_work_session_shift", "work_sessions", ["shift_occurrence_id"])

    op.create_table(
        "attendance_correction_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("attendance_id", sa.Integer(), sa.ForeignKey("attendances.id")),
        sa.Column("requested_check_in", sa.DateTime()),
        sa.Column("requested_check_out", sa.DateTime()),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime()),
        sa.Column("decision_note", sa.String(length=300)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_attendance_correction_tenant_id", "attendance_correction_requests", ["tenant_id"])
    op.create_index("ix_attendance_correction_tenant_status", "attendance_correction_requests", ["tenant_id", "status"])
    op.create_index("ix_attendance_correction_courier", "attendance_correction_requests", ["courier_id"])

    op.create_table(
        "overtimes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("shift_occurrence_id", sa.Integer(), sa.ForeignKey("shift_occurrences.id")),
        sa.Column("overtime_date", sa.Date(), nullable=False),
        sa.Column("requested_minutes", sa.Integer(), nullable=False),
        sa.Column("approved_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_overtimes_tenant_id", "overtimes", ["tenant_id"])
    op.create_index("ix_overtime_tenant_courier", "overtimes", ["tenant_id", "courier_id"])
    op.create_index("ix_overtime_tenant_date", "overtimes", ["tenant_id", "overtime_date"])


def downgrade() -> None:
    op.drop_table("overtimes")
    op.drop_table("attendance_correction_requests")
    op.drop_table("work_sessions")
    op.drop_table("shift_occurrences")
    op.drop_table("shift_templates")
