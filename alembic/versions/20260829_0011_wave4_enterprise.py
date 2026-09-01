"""Add Wave 4: platform governance, integration, security, scale.

Revision ID: 20260829_0011
Revises: 20260829_0010
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0011"
down_revision: Union[str, Sequence[str], None] = "20260829_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_operators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_platform_id", sa.Integer(), sa.ForeignKey("source_platforms.id"), nullable=False),
        sa.Column("operator_tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("relationship_type", sa.String(length=30), nullable=False, server_default=sa.text("'OPERATOR'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source_platform_id", "operator_tenant_id", name="uq_platform_operator"),
    )
    op.create_index("ix_platform_operators_tenant_id", "platform_operators", ["tenant_id"])
    op.create_index("ix_platform_operator_tenant_active", "platform_operators", ["tenant_id", "is_active"])

    op.create_table(
        "delegated_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("platform_operator_id", sa.Integer(), sa.ForeignKey("platform_operators.id"), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("permissions", sa.Text()),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "platform_operator_id", "scope_type", "scope_id", name="uq_delegated_scope"),
    )
    op.create_index("ix_delegated_scopes_tenant_id", "delegated_scopes", ["tenant_id"])
    op.create_index("ix_delegated_scope_tenant_operator", "delegated_scopes", ["tenant_id", "platform_operator_id"])

    op.create_table(
        "partner_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("partner_name", sa.String(length=120), nullable=False),
        sa.Column("key_prefix", sa.String(length=8), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("scopes", sa.Text()),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("idempotency_window_seconds", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("last_rotated_at", sa.DateTime()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "partner_name", "key_prefix", name="uq_partner_credential"),
    )
    op.create_index("ix_partner_credentials_tenant_id", "partner_credentials", ["tenant_id"])
    op.create_index("ix_partner_credential_tenant_active", "partner_credentials", ["tenant_id", "is_active"])

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("url", sa.String(length=300), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("secret_hash", sa.String(length=128)),
        sa.Column("is_inbound", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "url", "event_type", name="uq_webhook_endpoint"),
    )
    op.create_index("ix_webhook_endpoints_tenant_id", "webhook_endpoints", ["tenant_id"])
    op.create_index("ix_webhook_endpoint_tenant_active", "webhook_endpoints", ["tenant_id", "is_active"])

    op.create_table(
        "integration_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("credential_id", sa.Integer(), sa.ForeignKey("partner_credentials.id")),
        sa.Column("webhook_endpoint_id", sa.Integer(), sa.ForeignKey("webhook_endpoints.id")),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("event_type", sa.String(length=40)),
        sa.Column("method", sa.String(length=10)),
        sa.Column("url", sa.String(length=300)),
        sa.Column("status_code", sa.Integer()),
        sa.Column("request_body", sa.Text()),
        sa.Column("response_body", sa.Text()),
        sa.Column("idempotency_key", sa.String(length=180)),
        sa.Column("ip_address", sa.String(length=45)),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_integration_audit_logs_tenant_id", "integration_audit_logs", ["tenant_id"])
    op.create_index("ix_integration_audit_tenant_timestamp", "integration_audit_logs", ["tenant_id", "timestamp"])
    op.create_index("ix_integration_audit_tenant_credential", "integration_audit_logs", ["tenant_id", "credential_id"])

    op.create_table(
        "mfa_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("mfa_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_methods", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "role", name="uq_mfa_setting"),
    )
    op.create_index("ix_mfa_settings_tenant_id", "mfa_settings", ["tenant_id"])
    op.create_index("ix_mfa_setting_tenant_active", "mfa_settings", ["tenant_id", "is_active"])

    op.create_table(
        "security_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("actor_role", sa.String(length=30)),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=30)),
        sa.Column("entity_id", sa.Integer()),
        sa.Column("details", sa.Text()),
        sa.Column("ip_address", sa.String(length=45)),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_security_audit_logs_tenant_id", "security_audit_logs", ["tenant_id"])
    op.create_index("ix_security_audit_tenant_timestamp", "security_audit_logs", ["tenant_id", "timestamp"])

    op.create_table(
        "data_residency_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("data_type", sa.String(length=30), nullable=False),
        sa.Column("required_region", sa.String(length=20), nullable=False, server_default=sa.text("'SA'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "data_type", name="uq_data_residency_rule"),
    )
    op.create_index("ix_data_residency_rules_tenant_id", "data_residency_rules", ["tenant_id"])
    op.create_index("ix_data_residency_rule_tenant_active", "data_residency_rules", ["tenant_id", "is_active"])

    op.create_table(
        "sla_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("metric_name", sa.String(length=40), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=20)),
        sa.Column("measurement_window", sa.String(length=20), nullable=False, server_default=sa.text("'MONTHLY'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "metric_name", name="uq_sla_setting"),
    )
    op.create_index("ix_sla_settings_tenant_id", "sla_settings", ["tenant_id"])
    op.create_index("ix_sla_setting_tenant_active", "sla_settings", ["tenant_id", "is_active"])


def downgrade() -> None:
    op.drop_table("sla_settings")
    op.drop_table("data_residency_rules")
    op.drop_table("security_audit_logs")
    op.drop_table("mfa_settings")
    op.drop_table("integration_audit_logs")
    op.drop_table("webhook_endpoints")
    op.drop_table("partner_credentials")
    op.drop_table("delegated_scopes")
    op.drop_table("platform_operators")
