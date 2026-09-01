"""Add Wave 3: KPI, targets, incentive rules, payroll inputs, dashboards.

Revision ID: 20260829_0010
Revises: 20260829_0009
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0010"
down_revision: Union[str, Sequence[str], None] = "20260829_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kpi_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("description", sa.String(length=300)),
        sa.Column("category", sa.String(length=30), nullable=False, server_default=sa.text("'OPERATIONS'")),
        sa.Column("numerator_expression", sa.Text(), nullable=False),
        sa.Column("denominator_expression", sa.Text()),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default=sa.text("'COUNT'")),
        sa.Column("source_trust_level", sa.String(length=20), nullable=False, server_default=sa.text("'MEDIUM'")),
        sa.Column("version", sa.String(length=20), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", "version", name="uq_kpi_definition_version"),
    )
    op.create_index("ix_kpi_definitions_tenant_id", "kpi_definitions", ["tenant_id"])
    op.create_index("ix_kpi_definition_tenant_active", "kpi_definitions", ["tenant_id", "is_active"])

    op.create_table(
        "kpi_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("kpi_definition_id", sa.Integer(), sa.ForeignKey("kpi_definitions.id"), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("numerator_value", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("denominator_value", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("result_value", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("calculation_version", sa.String(length=20), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("freshness_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "kpi_definition_id", "scope_type", "scope_id", "period", name="uq_kpi_result"),
    )
    op.create_index("ix_kpi_results_tenant_id", "kpi_results", ["tenant_id"])
    op.create_index("ix_kpi_result_tenant_period", "kpi_results", ["tenant_id", "period"])

    op.create_table(
        "targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("actual_value", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("achievement_percentage", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "scope_type", "scope_id", "target_type", "period", name="uq_target"),
    )
    op.create_index("ix_targets_tenant_id", "targets", ["tenant_id"])
    op.create_index("ix_target_tenant_period", "targets", ["tenant_id", "period"])

    op.create_table(
        "incentive_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("description", sa.String(length=300)),
        sa.Column("rule_type", sa.String(length=30), nullable=False, server_default=sa.text("'BONUS'")),
        sa.Column("calculation_expression", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("precedence_policy", sa.String(length=20), nullable=False, server_default=sa.text("'HIGHEST_WINS'")),
        sa.Column("version", sa.String(length=20), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", "version", name="uq_incentive_rule_version"),
    )
    op.create_index("ix_incentive_rules_tenant_id", "incentive_rules", ["tenant_id"])
    op.create_index("ix_incentive_rule_tenant_active", "incentive_rules", ["tenant_id", "is_active"])

    op.create_table(
        "payroll_input_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Integer()),
        sa.Column("input_type", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("description", sa.String(length=300)),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'APPROVED'")),
        sa.Column("reversal_of_id", sa.Integer(), sa.ForeignKey("payroll_input_records.id")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "courier_id", "month", "source_type", "source_id", name="uq_payroll_input"),
    )
    op.create_index("ix_payroll_input_records_tenant_id", "payroll_input_records", ["tenant_id"])
    op.create_index("ix_payroll_input_tenant_month", "payroll_input_records", ["tenant_id", "month"])

    op.create_table(
        "dashboard_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("description", sa.String(length=300)),
        sa.Column("category", sa.String(length=30), nullable=False, server_default=sa.text("'OPERATIONS'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_dashboard_definition"),
    )
    op.create_index("ix_dashboard_definitions_tenant_id", "dashboard_definitions", ["tenant_id"])
    op.create_index("ix_dashboard_definition_tenant_active", "dashboard_definitions", ["tenant_id", "is_active"])

    op.create_table(
        "dashboard_widgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("dashboard_definition_id", sa.Integer(), sa.ForeignKey("dashboard_definitions.id"), nullable=False),
        sa.Column("kpi_definition_id", sa.Integer(), sa.ForeignKey("kpi_definitions.id")),
        sa.Column("widget_type", sa.String(length=30), nullable=False, server_default=sa.text("'METRIC'")),
        sa.Column("title_ar", sa.String(length=120), nullable=False),
        sa.Column("title_en", sa.String(length=120)),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("config", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_dashboard_widgets_tenant_id", "dashboard_widgets", ["tenant_id"])
    op.create_index("ix_dashboard_widget_dashboard", "dashboard_widgets", ["dashboard_definition_id"])


def downgrade() -> None:
    op.drop_table("dashboard_widgets")
    op.drop_table("dashboard_definitions")
    op.drop_table("payroll_input_records")
    op.drop_table("incentive_rules")
    op.drop_table("targets")
    op.drop_table("kpi_results")
    op.drop_table("kpi_definitions")
