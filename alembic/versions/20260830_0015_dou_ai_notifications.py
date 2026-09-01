"""DOU AI core and W11-lite notifications.

Revision ID: 20260830_0015
Revises: 20260829_0014
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260830_0015"
down_revision: Union[str, Sequence[str], None] = "20260829_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("ai_conversations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("title", sa.String(160)), sa.Column("context_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()))
    op.create_index("ix_ai_conversation_tenant_user", "ai_conversations", ["tenant_id", "user_id"])
    op.create_table("ai_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("conversation_id", sa.Integer, sa.ForeignKey("ai_conversations.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(12), nullable=False), sa.Column("content", sa.Text, nullable=False),
        sa.Column("structured_json", sa.Text), sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()))
    op.create_index("ix_ai_message_conversation_created", "ai_messages", ["conversation_id", "created_at"])
    op.create_table("ai_request_logs",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer, sa.ForeignKey("ai_conversations.id")),
        sa.Column("route", sa.String(40), nullable=False), sa.Column("source", sa.String(40), nullable=False),
        sa.Column("model_identifier", sa.String(100)), sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False), sa.Column("error_category", sa.String(40)),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()))
    op.create_index("ix_ai_request_tenant_created", "ai_request_logs", ["tenant_id", "created_at"])
    op.create_table("alert_source_mappings",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="METABASE"),
        sa.Column("external_alert_id", sa.String(100), nullable=False),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("tenants.id"), index=True),
        sa.Column("notification_type", sa.String(40), nullable=False), sa.Column("recipient_roles_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("severity", sa.String(12), nullable=False, server_default="WARNING"), sa.Column("deep_link", sa.String(300)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source", "external_alert_id", name="uq_alert_source_external"))
    op.create_table("notifications",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("recipient_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True), sa.Column("recipient_role", sa.String(30), nullable=False),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("tenants.id"), index=True), sa.Column("supervisor_id", sa.Integer, sa.ForeignKey("users.id"), index=True),
        sa.Column("notification_type", sa.String(40), nullable=False), sa.Column("severity", sa.String(12), nullable=False, server_default="INFO"),
        sa.Column("title", sa.String(180), nullable=False), sa.Column("message", sa.Text, nullable=False), sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_reference", sa.String(180)), sa.Column("idempotency_key", sa.String(180), nullable=False), sa.Column("dedupe_key", sa.String(180), nullable=False),
        sa.Column("deep_link", sa.String(300)), sa.Column("context_json", sa.Text, nullable=False, server_default="{}"), sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("read_at", sa.DateTime), sa.Column("acknowledged_at", sa.DateTime), sa.Column("acknowledged_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("resolved_at", sa.DateTime), sa.Column("resolved_by", sa.Integer, sa.ForeignKey("users.id")), sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source", "idempotency_key", "recipient_user_id", name="uq_notification_source_idempotency"))
    op.create_index("ix_notification_recipient_unread", "notifications", ["tenant_id", "recipient_user_id", "read_at"])
    op.create_index("ix_notification_scope_status", "notifications", ["tenant_id", "operator_id", "status"])
    op.create_index("ix_notification_dedupe", "notifications", ["tenant_id", "dedupe_key", "created_at"])
    op.create_table("notification_audits",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("notification_id", sa.Integer, sa.ForeignKey("notifications.id"), nullable=False, index=True),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id")), sa.Column("action", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20)), sa.Column("to_status", sa.String(20)), sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()))
    op.create_index("ix_notification_audit_notification", "notification_audits", ["notification_id", "created_at"])


def downgrade() -> None:
    for table in ["notification_audits", "notifications", "alert_source_mappings", "ai_request_logs", "ai_messages", "ai_conversations"]:
        op.drop_table(table)
