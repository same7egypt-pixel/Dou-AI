"""Add tenant-owned workforce zones, teams, and effective assignments.

Revision ID: 20260829_0002
Revises: 20260829_0001
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0002"
down_revision: Union[str, Sequence[str], None] = "20260829_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operating_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("operating_city_id", sa.Integer(), sa.ForeignKey("tenant_operating_cities.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_operating_zone_tenant_code"),
    )
    op.create_index("ix_operating_zones_tenant_id", "operating_zones", ["tenant_id"])
    op.create_index("ix_operating_zones_operating_city_id", "operating_zones", ["operating_city_id"])
    op.create_index("ix_operating_zone_tenant_active", "operating_zones", ["tenant_id", "is_active"])

    op.create_table(
        "workforce_teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("operating_zones.id")),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_workforce_team_tenant_code"),
    )
    op.create_index("ix_workforce_teams_tenant_id", "workforce_teams", ["tenant_id"])
    op.create_index("ix_workforce_teams_zone_id", "workforce_teams", ["zone_id"])
    op.create_index("ix_workforce_team_tenant_active", "workforce_teams", ["tenant_id", "is_active"])

    op.create_table(
        "team_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("workforce_teams.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("team_id", "courier_id", "effective_from", name="uq_team_membership_start"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_team_membership_dates"),
    )
    op.create_index("ix_team_memberships_tenant_id", "team_memberships", ["tenant_id"])
    op.create_index("ix_team_memberships_team_id", "team_memberships", ["team_id"])
    op.create_index("ix_team_memberships_courier_id", "team_memberships", ["courier_id"])
    op.create_index("ix_team_membership_tenant_courier", "team_memberships", ["tenant_id", "courier_id"])
    op.create_index("ix_team_membership_team_dates", "team_memberships", ["team_id", "effective_from", "effective_to"])

    op.create_table(
        "team_supervisor_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("workforce_teams.id"), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("team_id", "supervisor_id", "effective_from", name="uq_team_supervisor_start"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_team_supervisor_dates"),
    )
    op.create_index("ix_team_supervisor_assignments_tenant_id", "team_supervisor_assignments", ["tenant_id"])
    op.create_index("ix_team_supervisor_assignments_team_id", "team_supervisor_assignments", ["team_id"])
    op.create_index("ix_team_supervisor_assignments_supervisor_id", "team_supervisor_assignments", ["supervisor_id"])
    op.create_index("ix_team_supervisor_tenant_user", "team_supervisor_assignments", ["tenant_id", "supervisor_id"])
    op.create_index("ix_team_supervisor_team_dates", "team_supervisor_assignments", ["team_id", "effective_from", "effective_to"])


def downgrade() -> None:
    op.drop_table("team_supervisor_assignments")
    op.drop_table("team_memberships")
    op.drop_table("workforce_teams")
    op.drop_table("operating_zones")
