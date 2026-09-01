"""Tenant-safe notification creation, routing, deduplication and audit."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import config
from ..models import entities as ent
from ..models.intelligence import (
    AlertSourceMapping,
    Notification,
    NotificationAudit,
    WebhookReceipt,
)

ALLOWED_SEVERITIES = {"INFO", "WARNING", "CRITICAL"}
ALLOWED_TYPES = {
    "OPERATOR_PERFORMANCE",
    "ATTENDANCE",
    "IMPORT_FAILURE",
    "DOCUMENT_EXPIRY",
    "APPROVAL_REQUIRED",
    "SYSTEM_INTEGRATION",
    "ORDER_DECLINE",
}


def verify_webhook_signature(
    raw_body: bytes,
    signature: str | None,
    timestamp: str | None,
    nonce: str | None,
    source_instance: str | None,
    now: datetime | None = None,
) -> None:
    """Verify HMAC signature over timestamp + nonce + source_instance + body, with freshness checks."""
    if not config.NOTIFICATION_WEBHOOK_SECRET:
        raise HTTPException(503, "Analytical alert ingestion is not configured")
    if not signature:
        raise HTTPException(401, "Missing webhook signature")
    if not timestamp:
        raise HTTPException(401, "Missing webhook timestamp")
    if not nonce:
        raise HTTPException(401, "Missing webhook nonce")
    if len(nonce) < 8 or len(nonce) > 80:
        raise HTTPException(401, "Malformed webhook nonce")
    if not source_instance:
        raise HTTPException(401, "Missing webhook source instance")
    if len(source_instance) < 1 or len(source_instance) > 80:
        raise HTTPException(401, "Malformed webhook source instance")
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise HTTPException(401, "Malformed webhook timestamp")
    current = int((now or datetime.now(timezone.utc)).timestamp())
    age = current - ts
    if age > config.NOTIFICATION_WEBHOOK_MAX_AGE_SECONDS:
        raise HTTPException(401, "Webhook timestamp expired")
    if age < -config.NOTIFICATION_WEBHOOK_CLOCK_SKEW_SECONDS:
        raise HTTPException(401, "Webhook timestamp is in the future")
    supplied = signature.removeprefix("sha256=")
    message = f"{timestamp}.{nonce}.{source_instance}.".encode() + raw_body
    expected = hmac.new(
        config.NOTIFICATION_WEBHOOK_SECRET.encode(), message, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid webhook signature")


def check_webhook_replay(db: Session, nonce: str) -> None:
    """Reject exact transport replay using a persisted nonce."""
    now = datetime.now(timezone.utc)
    db.query(WebhookReceipt).filter(WebhookReceipt.expires_at < now).delete()
    existing = db.query(WebhookReceipt).filter(WebhookReceipt.nonce == nonce).first()
    if existing:
        raise HTTPException(409, "Webhook request replay rejected")
    receipt = WebhookReceipt(
        nonce=nonce,
        received_at=now,
        expires_at=now + timedelta(seconds=config.NOTIFICATION_WEBHOOK_MAX_AGE_SECONDS),
    )
    db.add(receipt)
    db.commit()


def verify_metabase_signature(raw_body: bytes, signature: str | None) -> None:
    if not config.METABASE_WEBHOOK_SECRET:
        raise HTTPException(503, "Analytical alert ingestion is not configured")
    if not signature:
        raise HTTPException(401, "Missing webhook signature")
    supplied = signature.removeprefix("sha256=")
    expected = hmac.new(
        config.METABASE_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid webhook signature")


def _role_value(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


def recipients_for_mapping(db: Session, mapping: AlertSourceMapping) -> list[ent.User]:
    try:
        roles = set(json.loads(mapping.recipient_roles_json or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        roles = set()
    if not roles:
        roles = {"COMPANY", "COMPANY_ADMIN", "OPERATIONS"}
    users = (
        db.query(ent.User)
        .filter(ent.User.tenant_id == mapping.tenant_id, ent.User.is_active.is_(True))
        .all()
    )
    return [u for u in users if _role_value(u.role) in roles]


def create_routed_notifications(
    db: Session,
    *,
    tenant_id: int,
    recipients: list[ent.User],
    notification_type: str,
    severity: str,
    title: str,
    message: str,
    source: str,
    source_reference: str | None,
    idempotency_key: str,
    dedupe_key: str,
    operator_id: int | None = None,
    supervisor_id: int | None = None,
    deep_link: str | None = None,
    context: dict | None = None,
) -> list[Notification]:
    if notification_type not in ALLOWED_TYPES or severity not in ALLOWED_SEVERITIES:
        raise HTTPException(422, "Unsupported notification classification")
    if not recipients:
        raise HTTPException(422, "No authorized recipients configured")
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        minutes=config.NOTIFICATION_DEDUPE_MINUTES
    )
    created = []
    for user in recipients:
        if user.tenant_id != tenant_id:
            raise HTTPException(403, "Cross-tenant notification routing denied")
        replay = (
            db.query(Notification)
            .filter(
                Notification.tenant_id == tenant_id,
                Notification.source == source,
                Notification.idempotency_key == idempotency_key,
                Notification.recipient_user_id == user.id,
            )
            .first()
        )
        if replay:
            created.append(replay)
            continue
        duplicate = (
            db.query(Notification)
            .filter(
                Notification.tenant_id == tenant_id,
                Notification.recipient_user_id == user.id,
                Notification.dedupe_key == dedupe_key,
                Notification.created_at >= cutoff,
                Notification.status.in_(["OPEN", "ACKNOWLEDGED"]),
            )
            .first()
        )
        if duplicate:
            created.append(duplicate)
            continue
        notification = Notification(
            tenant_id=tenant_id,
            recipient_user_id=user.id,
            recipient_role=_role_value(user.role),
            operator_id=operator_id,
            supervisor_id=supervisor_id,
            notification_type=notification_type,
            severity=severity,
            title=title[:180],
            message=message,
            source=source,
            source_reference=source_reference,
            idempotency_key=idempotency_key,
            dedupe_key=dedupe_key,
            deep_link=deep_link,
            context_json=json.dumps(context or {}, separators=(",", ":")),
        )
        db.add(notification)
        db.flush()
        db.add(
            NotificationAudit(
                tenant_id=tenant_id,
                notification_id=notification.id,
                actor_id=None,
                action="CREATED",
                to_status="OPEN",
            )
        )
        created.append(notification)
    db.commit()
    return created


def ingest_metabase_alert(
    db: Session, payload: dict, trusted_source_instance: str
) -> list[Notification]:
    """Resolve tenant from trusted source mapping, never from payload."""
    external_alert_id = str(payload.get("alert_id", "")).strip()
    event_id = str(payload.get("event_id", "")).strip()
    if not external_alert_id or not event_id:
        raise HTTPException(422, "alert_id and event_id are required")
    mapping = (
        db.query(AlertSourceMapping)
        .filter(
            AlertSourceMapping.source_instance == trusted_source_instance,
            AlertSourceMapping.source == "METABASE",
            AlertSourceMapping.external_alert_id == external_alert_id,
            AlertSourceMapping.is_active.is_(True),
        )
        .first()
    )
    if not mapping:
        raise HTTPException(403, "Alert source is not approved")
    payload_tenant_id = payload.get("tenant_id")
    if payload_tenant_id is not None:
        try:
            payload_tenant_id = int(payload_tenant_id)
        except (TypeError, ValueError):
            raise HTTPException(422, "tenant_id must be an integer")
        if payload_tenant_id != mapping.tenant_id:
            raise HTTPException(
                403, "Webhook payload tenant does not match trusted source mapping"
            )
    title = str(payload.get("title", "Analytical condition detected")).strip()[:180]
    message = str(
        payload.get("message", "An approved analytical alert condition was met.")
    ).strip()[:2000]
    if not title or not message:
        raise HTTPException(422, "Alert title and message are required")
    period = str(payload.get("period", "current"))[:30]
    dedupe_key = f"METABASE:{trusted_source_instance}:{mapping.tenant_id}:{external_alert_id}:{period}"
    recipients = recipients_for_mapping(db, mapping)
    return create_routed_notifications(
        db,
        tenant_id=mapping.tenant_id,
        recipients=recipients,
        notification_type=mapping.notification_type,
        severity=mapping.severity,
        title=title,
        message=message,
        source="METABASE",
        source_reference=external_alert_id,
        idempotency_key=event_id,
        dedupe_key=dedupe_key,
        operator_id=mapping.operator_id,
        deep_link=mapping.deep_link,
        context={
            "entity_type": "operator" if mapping.operator_id else "alert",
            "operator_id": mapping.operator_id,
            "period": period,
            "alert_id": external_alert_id,
            "source_instance": trusted_source_instance,
        },
    )


def transition(
    db: Session, notification: Notification, user: ent.User, action: str
) -> Notification:
    if (
        notification.tenant_id != user.tenant_id
        or notification.recipient_user_id != user.id
    ):
        raise HTTPException(404, "Notification not found")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = notification.status
    if action == "READ":
        notification.read_at = notification.read_at or now
    elif action == "ACKNOWLEDGE":
        if notification.status == "RESOLVED":
            raise HTTPException(409, "Resolved notification cannot be acknowledged")
        notification.status = "ACKNOWLEDGED"
        notification.acknowledged_at = now
        notification.acknowledged_by = user.id
        notification.read_at = notification.read_at or now
    elif action == "RESOLVE":
        notification.status = "RESOLVED"
        notification.resolved_at = now
        notification.resolved_by = user.id
        notification.read_at = notification.read_at or now
    else:
        raise HTTPException(422, "Invalid transition")
    db.add(
        NotificationAudit(
            tenant_id=user.tenant_id,
            notification_id=notification.id,
            actor_id=user.id,
            action=action,
            from_status=old,
            to_status=notification.status,
        )
    )
    db.commit()
    db.refresh(notification)
    return notification
