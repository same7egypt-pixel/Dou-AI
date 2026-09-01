"""DOU AI and W11-lite notification persistence models."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from ..database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (Index("ix_ai_conversation_tenant_user", "tenant_id", "user_id"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(160))
    context_json = Column(Text, default="{}", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        Index("ix_ai_message_conversation_created", "conversation_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    conversation_id = Column(
        Integer, ForeignKey("ai_conversations.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(12), nullable=False)  # USER / ASSISTANT
    content = Column(Text, nullable=False)
    structured_json = Column(Text)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class AIRequestLog(Base):
    """Prompt-free operational telemetry. Never stores question or response content."""

    __tablename__ = "ai_request_logs"
    __table_args__ = (Index("ix_ai_request_tenant_created", "tenant_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("ai_conversations.id"))
    route = Column(String(40), nullable=False)
    source = Column(String(40), nullable=False)
    model_identifier = Column(String(100))
    latency_ms = Column(Integer, nullable=False)
    success = Column(Boolean, nullable=False)
    error_category = Column(String(40))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class AlertSourceMapping(Base):
    """Admin-controlled mapping; webhook bodies cannot choose tenant scope."""

    __tablename__ = "alert_source_mappings"
    __table_args__ = (
        UniqueConstraint(
            "source_instance",
            "source",
            "external_alert_id",
            name="uq_alert_source_external",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_instance = Column(String(80), nullable=False, default="default")
    source = Column(String(30), nullable=False, default="METABASE")
    external_alert_id = Column(String(100), nullable=False)
    operator_id = Column(Integer, ForeignKey("tenants.id"), index=True)
    notification_type = Column(String(40), nullable=False)
    recipient_roles_json = Column(Text, default="[]", nullable=False)
    severity = Column(String(12), default="WARNING", nullable=False)
    deep_link = Column(String(300))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source",
            "idempotency_key",
            "recipient_user_id",
            name="uq_notification_source_idempotency",
        ),
        Index(
            "ix_notification_recipient_unread",
            "tenant_id",
            "recipient_user_id",
            "read_at",
        ),
        Index("ix_notification_scope_status", "tenant_id", "operator_id", "status"),
        Index("ix_notification_dedupe", "tenant_id", "dedupe_key", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    recipient_user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    recipient_role = Column(String(30), nullable=False)
    operator_id = Column(Integer, ForeignKey("tenants.id"), index=True)
    supervisor_id = Column(Integer, ForeignKey("users.id"), index=True)
    notification_type = Column(String(40), nullable=False)
    severity = Column(String(12), nullable=False, default="INFO")
    title = Column(String(180), nullable=False)
    message = Column(Text, nullable=False)
    source = Column(String(30), nullable=False)  # METABASE / NATIVE
    source_reference = Column(String(180))
    idempotency_key = Column(String(180), nullable=False)
    dedupe_key = Column(String(180), nullable=False)
    deep_link = Column(String(300))
    context_json = Column(Text, default="{}", nullable=False)
    status = Column(String(20), default="OPEN", nullable=False)
    read_at = Column(DateTime)
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(Integer, ForeignKey("users.id"))
    resolved_at = Column(DateTime)
    resolved_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class NotificationAudit(Base):
    __tablename__ = "notification_audits"
    __table_args__ = (
        Index("ix_notification_audit_notification", "notification_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    notification_id = Column(
        Integer, ForeignKey("notifications.id"), nullable=False, index=True
    )
    actor_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String(30), nullable=False)
    from_status = Column(String(20))
    to_status = Column(String(20))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class WebhookReceipt(Base):
    """Transport-level replay protection for signed webhook requests."""

    __tablename__ = "webhook_receipts"
    __table_args__ = (UniqueConstraint("nonce", name="uq_webhook_nonce"),)

    id = Column(Integer, primary_key=True)
    nonce = Column(String(80), nullable=False, index=True)
    received_at = Column(DateTime, default=utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class AnalyticsRefreshState(Base):
    """Tracks freshness of materialized analytics tables."""

    __tablename__ = "analytics_refresh_states"
    __table_args__ = (
        UniqueConstraint("table_name", name="uq_analytics_refresh_table"),
    )

    id = Column(Integer, primary_key=True)
    table_name = Column(String(80), nullable=False)
    last_refresh_started_at = Column(DateTime)
    last_refresh_succeeded_at = Column(DateTime)
    last_refresh_failed_at = Column(DateTime)
    last_error = Column(Text)
    row_count = Column(Integer)
    status = Column(String(20), default="UNKNOWN", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
