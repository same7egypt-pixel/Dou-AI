"""W11-lite operational Notification Center and signed analytical webhooks."""

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from ..models.intelligence import AlertSourceMapping, Notification
from ..services.notifications import (
    ALLOWED_SEVERITIES,
    ALLOWED_TYPES,
    check_webhook_replay,
    create_routed_notifications,
    ingest_metabase_alert,
    transition,
    verify_webhook_signature,
)
from .auth import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])
ADMIN_ROLES = {ent.UserRole.COMPANY, ent.UserRole.COMPANY_ADMIN}


class AlertMappingCreate(BaseModel):
    source_instance: str = Field("default", min_length=1, max_length=80)
    external_alert_id: str = Field(..., min_length=1, max_length=100)
    operator_id: int | None = None
    notification_type: str
    recipient_roles: list[str] = Field(default_factory=list)
    severity: str = "WARNING"
    deep_link: str | None = Field(None, max_length=300)

    @field_validator("deep_link")
    @classmethod
    def internal_link(cls, value):
        if value and not value.startswith("/app/"):
            raise ValueError("deep_link must be an internal DOU route")
        return value


class NativeNotificationCreate(BaseModel):
    notification_type: str
    severity: str = "INFO"
    title: str = Field(..., min_length=1, max_length=180)
    message: str = Field(..., min_length=1, max_length=2000)
    recipient_roles: list[str] = Field(default_factory=list)
    operator_id: int | None = None
    supervisor_id: int | None = None
    source_reference: str | None = Field(None, max_length=180)
    idempotency_key: str = Field(..., min_length=1, max_length=180)
    dedupe_key: str = Field(..., min_length=1, max_length=180)
    deep_link: str | None = Field(None, max_length=300)
    context: dict = Field(default_factory=dict)

    @field_validator("deep_link")
    @classmethod
    def internal_link(cls, value):
        if value and not value.startswith("/app/"):
            raise ValueError("deep_link must be an internal DOU route")
        return value


def serialize(n: Notification) -> dict:
    try:
        context = json.loads(n.context_json or "{}")
    except (TypeError, json.JSONDecodeError):
        context = {}
    return {
        "id": n.id,
        "type": n.notification_type,
        "severity": n.severity,
        "title": n.title,
        "message": n.message,
        "source": n.source,
        "source_reference": n.source_reference,
        "operator_id": n.operator_id,
        "status": n.status,
        "read_at": n.read_at,
        "acknowledged_at": n.acknowledged_at,
        "resolved_at": n.resolved_at,
        "created_at": n.created_at,
        "deep_link": n.deep_link,
        "ai_context": context,
    }


@router.get("")
def list_notifications(
    unread_only: bool = False,
    status: str | None = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Notification).filter(
        Notification.tenant_id == user.tenant_id,
        Notification.recipient_user_id == user.id,
    )
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    if status:
        query = query.filter(Notification.status == status)
    rows = query.order_by(Notification.created_at.desc()).limit(100).all()
    unread = (
        db.query(Notification)
        .filter(
            Notification.tenant_id == user.tenant_id,
            Notification.recipient_user_id == user.id,
            Notification.read_at.is_(None),
        )
        .count()
    )
    return {"unread_count": unread, "notifications": [serialize(r) for r in rows]}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(Notification, notification_id)
    if not row:
        raise HTTPException(404, "Notification not found")
    return serialize(transition(db, row, user, "READ"))


@router.post("/{notification_id}/acknowledge")
def acknowledge(
    notification_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(Notification, notification_id)
    if not row:
        raise HTTPException(404, "Notification not found")
    return serialize(transition(db, row, user, "ACKNOWLEDGE"))


@router.post("/{notification_id}/resolve")
def resolve(
    notification_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(Notification, notification_id)
    if not row:
        raise HTTPException(404, "Notification not found")
    return serialize(transition(db, row, user, "RESOLVE"))


@router.post("/alert-mappings")
def create_mapping(
    payload: AlertMappingCreate,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(403, "Admin role required")
    if (
        payload.notification_type not in ALLOWED_TYPES
        or payload.severity not in ALLOWED_SEVERITIES
    ):
        raise HTTPException(422, "Unsupported notification classification")
    if payload.operator_id:
        linked = (
            db.query(ent.PlatformOperator.id)
            .filter(
                ent.PlatformOperator.tenant_id == user.tenant_id,
                ent.PlatformOperator.operator_tenant_id == payload.operator_id,
                ent.PlatformOperator.is_active.is_(True),
            )
            .first()
        )
        if not linked:
            raise HTTPException(403, "Operator is outside tenant platform scope")
    roles = payload.recipient_roles or ["COMPANY", "COMPANY_ADMIN", "OPERATIONS"]
    mapping = AlertSourceMapping(
        tenant_id=user.tenant_id,
        source_instance=payload.source_instance,
        external_alert_id=payload.external_alert_id,
        notification_type=payload.notification_type,
        operator_id=payload.operator_id,
        recipient_roles_json=json.dumps(roles),
        severity=payload.severity,
        deep_link=payload.deep_link,
    )
    db.add(mapping)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "Alert mapping already exists")
    db.refresh(mapping)
    return {"id": mapping.id, "external_alert_id": mapping.external_alert_id}


@router.post("/native")
def create_native(
    payload: NativeNotificationCreate,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ADMIN_ROLES:
        raise HTTPException(403, "Admin role required")
    if payload.operator_id:
        linked = (
            db.query(ent.PlatformOperator.id)
            .filter(
                ent.PlatformOperator.tenant_id == user.tenant_id,
                ent.PlatformOperator.operator_tenant_id == payload.operator_id,
                ent.PlatformOperator.is_active.is_(True),
            )
            .first()
        )
        if not linked:
            raise HTTPException(403, "Operator is outside tenant platform scope")
    if payload.supervisor_id:
        supervisor = (
            db.query(ent.User.id)
            .filter(
                ent.User.id == payload.supervisor_id,
                ent.User.tenant_id == user.tenant_id,
                ent.User.role == ent.UserRole.SUPERVISOR,
                ent.User.is_active.is_(True),
            )
            .first()
        )
        if not supervisor:
            raise HTTPException(403, "Supervisor is outside tenant scope")
    roles = set(payload.recipient_roles or ["COMPANY", "COMPANY_ADMIN", "OPERATIONS"])
    recipients = [
        u
        for u in db.query(ent.User)
        .filter(ent.User.tenant_id == user.tenant_id, ent.User.is_active.is_(True))
        .all()
        if (u.role.value if hasattr(u.role, "value") else str(u.role)) in roles
    ]
    rows = create_routed_notifications(
        db,
        tenant_id=user.tenant_id,
        recipients=recipients,
        notification_type=payload.notification_type,
        severity=payload.severity,
        title=payload.title,
        message=payload.message,
        source="NATIVE",
        source_reference=payload.source_reference,
        idempotency_key=payload.idempotency_key,
        dedupe_key=payload.dedupe_key,
        operator_id=payload.operator_id,
        supervisor_id=payload.supervisor_id,
        deep_link=payload.deep_link,
        context=payload.context,
    )
    return {"created_or_existing": len(rows), "ids": [r.id for r in rows]}


@webhook_router.post("/metabase/alerts")
async def metabase_alert(
    request: Request,
    x_dou_signature: str | None = Header(None),
    x_dou_timestamp: str | None = Header(None),
    x_dou_nonce: str | None = Header(None),
    x_dou_source_instance: str | None = Header(None),
    db: Session = Depends(get_db),
):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 65536:
                raise HTTPException(413, "Webhook payload too large")
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length")
    raw = await request.body()
    if len(raw) > 65536:
        raise HTTPException(413, "Webhook payload too large")
    verify_webhook_signature(
        raw, x_dou_signature, x_dou_timestamp, x_dou_nonce, x_dou_source_instance
    )
    check_webhook_replay(db, x_dou_nonce or "")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(422, "Malformed JSON payload")
    if not isinstance(payload, dict):
        raise HTTPException(422, "Webhook payload must be an object")
    rows = ingest_metabase_alert(db, payload, x_dou_source_instance or "default")
    return {"accepted": True, "notifications": len(rows)}
