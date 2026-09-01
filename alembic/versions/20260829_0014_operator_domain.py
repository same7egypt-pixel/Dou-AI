"""W10.5: Operator domain and commercial settlement tables.

Revision ID: 20260829_0014
Revises: 20260829_0013
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0014"
down_revision: Union[str, Sequence[str], None] = "20260829_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add customer_type and capabilities to tenants
    op.add_column("tenants", sa.Column("customer_type", sa.String(30), server_default="LOGISTICS_OPERATOR", nullable=True))
    op.add_column("tenants", sa.Column("capabilities", sa.Text, server_default="[]", nullable=True))
    
    # External operator identity
    op.create_table(
        "external_operator_identities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("source_platform_id", sa.Integer, sa.ForeignKey("source_platforms.id"), nullable=False, index=True),
        sa.Column("external_operator_id", sa.String(80), nullable=False),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("status", sa.String(20), default="ACTIVE"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source_platform_id", "external_operator_id", name="uq_external_operator"),
    )
    
    # Rider assignment history
    op.create_table(
        "rider_assignments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("courier_id", sa.Integer, sa.ForeignKey("couriers.id"), nullable=False, index=True),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("supervisor_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id")),
        sa.Column("contract_branch_id", sa.Integer, sa.ForeignKey("contract_branches.id")),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
        sa.Column("status", sa.String(20), default="ACTIVE"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Operator agreement
    op.create_table(
        "operator_agreements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("compensation_model", sa.String(30), nullable=False),
        sa.Column("rate", sa.Numeric(18, 2), nullable=False, default=0),
        sa.Column("currency", sa.String(3), default="SAR"),
        sa.Column("eligible_metric", sa.String(30), default="COMPLETED_ORDERS"),
        sa.Column("bonus_threshold", sa.Numeric(18, 2), default=0),
        sa.Column("bonus_rate", sa.Numeric(18, 2), default=0),
        sa.Column("penalty_threshold", sa.Numeric(18, 2), default=0),
        sa.Column("penalty_rate", sa.Numeric(18, 2), default=0),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
        sa.Column("status", sa.String(20), default="ACTIVE"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Commercial settlement
    op.create_table(
        "commercial_settlements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("agreement_id", sa.Integer, sa.ForeignKey("operator_agreements.id")),
        sa.Column("period_month", sa.String(7), nullable=False),
        sa.Column("eligible_orders", sa.Integer, default=0),
        sa.Column("base_amount", sa.Numeric(18, 2), default=0),
        sa.Column("bonus_amount", sa.Numeric(18, 2), default=0),
        sa.Column("penalty_amount", sa.Numeric(18, 2), default=0),
        sa.Column("manual_adjustment", sa.Numeric(18, 2), default=0),
        sa.Column("adjustment_reason", sa.String(300)),
        sa.Column("net_amount", sa.Numeric(18, 2), default=0),
        sa.Column("currency", sa.String(3), default="SAR"),
        sa.Column("status", sa.String(20), default="DRAFT"),
        sa.Column("calculation_data", sa.Text),
        sa.Column("reversal_of_id", sa.Integer, sa.ForeignKey("commercial_settlements.id")),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("approved_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "operator_id", "period_month", name="uq_commercial_settlement_period"),
    )
    
    # Commercial settlement line
    op.create_table(
        "commercial_settlement_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("settlement_id", sa.Integer, sa.ForeignKey("commercial_settlements.id"), nullable=False, index=True),
        sa.Column("line_type", sa.String(30), nullable=False),
        sa.Column("description", sa.String(300)),
        sa.Column("quantity", sa.Integer, default=0),
        sa.Column("rate", sa.Numeric(18, 2), default=0),
        sa.Column("amount", sa.Numeric(18, 2), default=0),
        sa.Column("source_reference", sa.String(100)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("commercial_settlement_lines")
    op.drop_table("commercial_settlements")
    op.drop_table("operator_agreements")
    op.drop_table("rider_assignments")
    op.drop_table("external_operator_identities")
    op.drop_column("tenants", "customer_type")
    op.drop_column("tenants", "capabilities")
