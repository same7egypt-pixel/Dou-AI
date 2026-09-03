"""Wave 4 router — platform governance, integration, security, scale."""

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from ..models.entities import Capability
from ..services.entitlements import VENDOR_PORTAL, capabilities_for
from .auth import get_current_user

router = APIRouter(prefix="/enterprise", tags=["enterprise"])

MANAGE_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
}
ADMIN_ROLES = {ent.UserRole.COMPANY_ADMIN, ent.UserRole.DOU_ADMIN, ent.UserRole.DOU_OPS}
READ_ROLES = MANAGE_ROLES | {
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.VIEWER,
    ent.UserRole.PROJECT_MANAGER,
}


def _tenant_id(user: ent.User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Enterprise access required")
    return user.tenant_id


def _same_tenant(db, model, record_id: int, tenant_id: int):
    row = (
        db.query(model)
        .filter(model.id == record_id, model.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


# ---------- schemas ----------


class PlatformOperatorCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_platform_id: int
    operator_tenant_id: int
    relationship_type: str = "OPERATOR"


class PlatformOperatorUpdate(BaseModel):
    relationship_type: Optional[str] = None
    is_active: Optional[bool] = None


class DelegatedScopeCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    platform_operator_id: int
    scope_type: str
    scope_id: int
    permissions: Optional[str] = None
    valid_from: date
    valid_to: Optional[date] = None


class PartnerCredentialCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    partner_name: str
    scopes: Optional[str] = None
    rate_limit_per_minute: int = 60
    idempotency_window_seconds: int = 300
    expires_at: Optional[datetime] = None


class PartnerCredentialUpdate(BaseModel):
    scopes: Optional[str] = None
    rate_limit_per_minute: Optional[int] = None
    idempotency_window_seconds: Optional[int] = None
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None


class WebhookEndpointCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    url: str
    event_type: str
    is_inbound: bool = True


class WebhookEndpointUpdate(BaseModel):
    url: Optional[str] = None
    event_type: Optional[str] = None
    is_active: Optional[bool] = None


class IntegrationAuditCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    credential_id: Optional[int] = None
    webhook_endpoint_id: Optional[int] = None
    direction: str
    event_type: Optional[str] = None
    method: Optional[str] = None
    url: Optional[str] = None
    status_code: Optional[int] = None
    request_body: Optional[str] = None
    response_body: Optional[str] = None
    idempotency_key: Optional[str] = None
    ip_address: Optional[str] = None


class MFASettingCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role: str
    mfa_required: bool = False
    allowed_methods: Optional[str] = None


class MFASettingUpdate(BaseModel):
    mfa_required: Optional[bool] = None
    allowed_methods: Optional[str] = None
    is_active: Optional[bool] = None


class SecurityAuditCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None


class DataResidencyCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    data_type: str
    required_region: str = "SA"


class DataResidencyUpdate(BaseModel):
    required_region: Optional[str] = None
    is_active: Optional[bool] = None


class SLASettingCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    metric_name: str
    target_value: float
    unit: Optional[str] = None
    measurement_window: str = "MONTHLY"


class SLASettingUpdate(BaseModel):
    target_value: Optional[float] = None
    unit: Optional[str] = None
    measurement_window: Optional[str] = None
    is_active: Optional[bool] = None


# ---------- platform operators ----------


def _source_platforms(db, tenant_id: int) -> list:
    """The tenant's active source platforms, creating a default on first use.

    Shared by the listing and the link endpoint so that linking never depends on
    the browser having called the listing first — an ordering assumption is not
    a contract.
    """
    rows = (
        db.query(ent.SourcePlatform)
        .filter(
            ent.SourcePlatform.tenant_id == tenant_id,
            ent.SourcePlatform.is_active.is_(True),
        )
        .order_by(ent.SourcePlatform.id)
        .all()
    )
    if rows:
        return rows
    tenant = db.get(ent.Tenant, tenant_id)
    default = ent.SourcePlatform(
        tenant_id=tenant_id,
        code="DEFAULT",
        name_ar=(tenant.name if tenant else "المنصة"),
        name_en=(tenant.name if tenant else "Platform"),
        is_active=True,
    )
    db.add(default)
    db.commit()
    db.refresh(default)
    return [default]


@router.get("/source-platforms")
def list_source_platforms(
    user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """The platform's own source platforms.

    Linking a vendor needs a source_platform_id and nothing exposed one, so
    POST /operators could not be called from a browser at all — the vendor
    screen had no way to obtain either id the endpoint requires.
    """
    tenant_id = _tenant_id(user)
    return [
        {"id": r.id, "code": r.code, "name": r.name_ar or r.name_en}
        for r in _source_platforms(db, tenant_id)
    ]


class OperatorLinkByPhone(BaseModel):
    """Link a vendor the platform already works with, addressed by its login."""

    admin_phone: str
    source_platform_id: Optional[int] = None
    relationship_type: str = "OPERATOR"


@router.post("/operators/link", status_code=201)
def link_operator_by_phone(
    payload: OperatorLinkByPhone,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Link an existing DOU company as this platform's operator.

    A platform is never handed a list of every company on DOU — that is a
    tenant-enumeration oracle. It supplies the phone the vendor's own admin
    signs in with, which it knows from the commercial relationship, and every
    failure answers the same 404 so the endpoint cannot be used to discover who
    is or is not a DOU customer.

    Companies are created by DOU administration. This only records that two
    accounts which already exist work together.
    """
    tenant_id = _tenant_id(user, manage=True)
    tenant = db.get(ent.Tenant, tenant_id)
    if Capability.MANAGE_OPERATORS.value not in capabilities_for(tenant):
        raise HTTPException(403, "This account is not entitled to MANAGE_OPERATORS")

    not_found = HTTPException(404, "لا توجد شركة مسجّلة بهذا الجوال قابلة للربط")

    phone = (payload.admin_phone or "").strip()
    if not phone:
        raise not_found
    owner = db.query(ent.User).filter(ent.User.phone == phone).first()
    if not owner or not owner.tenant_id or not owner.is_active:
        raise not_found
    vendor = db.get(ent.Tenant, owner.tenant_id)
    if not vendor or vendor.id == tenant_id:
        raise not_found
    # A platform links logistics companies, not other platforms.
    if (vendor.customer_type or "").upper() == "DELIVERY_PLATFORM":
        raise not_found

    source_platform_id = payload.source_platform_id
    if source_platform_id is not None:
        _same_tenant(db, ent.SourcePlatform, source_platform_id, tenant_id)
    else:
        source_platform_id = _source_platforms(db, tenant_id)[0].id

    existing = (
        db.query(ent.PlatformOperator)
        .filter(
            ent.PlatformOperator.tenant_id == tenant_id,
            ent.PlatformOperator.operator_tenant_id == vendor.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "هذه الشركة مرتبطة بالمنصة بالفعل")

    row = ent.PlatformOperator(
        tenant_id=tenant_id,
        source_platform_id=source_platform_id,
        operator_tenant_id=vendor.id,
        relationship_type=payload.relationship_type,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "operator_tenant_id": vendor.id,
        "name": vendor.name,
        "relationship_type": row.relationship_type,
    }


@router.post("/operators", status_code=201)
def create_operator(
    payload: PlatformOperatorCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.SourcePlatform, payload.source_platform_id, tenant_id)
    # H2 FIX: Validate operator_tenant_id exists
    if (
        not db.query(ent.Tenant)
        .filter(ent.Tenant.id == payload.operator_tenant_id)
        .first()
    ):
        raise HTTPException(400, "Invalid operator tenant")
    existing = (
        db.query(ent.PlatformOperator)
        .filter(
            ent.PlatformOperator.tenant_id == tenant_id,
            ent.PlatformOperator.source_platform_id == payload.source_platform_id,
            ent.PlatformOperator.operator_tenant_id == payload.operator_tenant_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Platform operator relationship already exists")
    row = ent.PlatformOperator(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "operator_tenant_id": row.operator_tenant_id}


@router.get("/operators")
def list_operators(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.PlatformOperator).filter(
        ent.PlatformOperator.tenant_id == tenant_id
    )
    if active_only:
        q = q.filter(ent.PlatformOperator.is_active.is_(True))
    results = []
    for r in q.order_by(ent.PlatformOperator.created_at).all():
        op_tenant = db.get(ent.Tenant, r.operator_tenant_id)
        results.append(
            {
                "id": r.id,
                "source_platform_id": r.source_platform_id,
                "operator_tenant_id": r.operator_tenant_id,
                "name": op_tenant.name
                if op_tenant
                else f"مشغل #{r.operator_tenant_id}",
                "operator_name": op_tenant.name
                if op_tenant
                else f"مشغل #{r.operator_tenant_id}",
                "relationship_type": r.relationship_type,
                "is_active": r.is_active,
            }
        )
    return results


@router.patch("/operators/{operator_id}")
def update_operator(
    operator_id: int,
    payload: PlatformOperatorUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.PlatformOperator, operator_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "operator_tenant_id": row.operator_tenant_id}


# ---------- delegated scopes ----------


@router.post("/delegated-scopes", status_code=201)
def create_delegated_scope(
    payload: DelegatedScopeCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.PlatformOperator, payload.platform_operator_id, tenant_id)
    existing = (
        db.query(ent.DelegatedScope)
        .filter(
            ent.DelegatedScope.tenant_id == tenant_id,
            ent.DelegatedScope.platform_operator_id == payload.platform_operator_id,
            ent.DelegatedScope.scope_type == payload.scope_type,
            ent.DelegatedScope.scope_id == payload.scope_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Delegated scope already exists")
    row = ent.DelegatedScope(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "scope_type": row.scope_type, "scope_id": row.scope_id}


@router.get("/delegated-scopes")
def list_delegated_scopes(
    platform_operator_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.DelegatedScope).filter(ent.DelegatedScope.tenant_id == tenant_id)
    if platform_operator_id:
        q = q.filter(ent.DelegatedScope.platform_operator_id == platform_operator_id)
    return [
        {
            "id": r.id,
            "platform_operator_id": r.platform_operator_id,
            "scope_type": r.scope_type,
            "scope_id": r.scope_id,
            "permissions": r.permissions,
            "valid_from": r.valid_from.isoformat(),
            "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        }
        for r in q.order_by(ent.DelegatedScope.created_at).all()
    ]


# ---------- partner credentials ----------


@router.post("/operators/{operator_id}/portal", status_code=200)
def set_operator_portal(
    operator_id: int,
    payload: dict,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Open or close the vendor portal for one operator.

    A single call rather than making the platform hand-craft a delegated scope:
    opening is what the platform is paying for, and it should not require
    knowing the scope vocabulary. Closing expires the grant rather than deleting
    it, so the audit trail survives and nothing has to be cleaned up - the
    vendor's access stops because the read resolves to nothing, not because data
    moved.
    """
    tenant_id = _tenant_id(user)
    tenant = db.get(ent.Tenant, tenant_id)
    caps = capabilities_for(tenant)
    if Capability.MANAGE_OPERATORS.value not in caps:
        raise HTTPException(403, "هذه العملية متاحة لحسابات منصات التوصيل فقط")
    if VENDOR_PORTAL not in caps:
        raise HTTPException(
            402, "بوابة المورّدين إضافة مدفوعة غير مفعّلة على باقة حسابك"
        )

    link = (
        db.query(ent.PlatformOperator)
        .filter(
            ent.PlatformOperator.id == operator_id,
            ent.PlatformOperator.tenant_id == tenant_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(404, "المشغّل غير موجود ضمن حسابك")

    today = date.today()
    enable = bool(payload.get("enabled", True))
    existing = (
        db.query(ent.DelegatedScope)
        .filter(
            ent.DelegatedScope.tenant_id == tenant_id,
            ent.DelegatedScope.platform_operator_id == link.id,
        )
        .order_by(ent.DelegatedScope.valid_from.desc())
        .first()
    )

    if not enable:
        if existing and (existing.valid_to is None or existing.valid_to >= today):
            existing.valid_to = today - timedelta(days=1)
            db.commit()
        return {"ok": True, "operator_id": link.id, "portal": "CLOSED"}

    permissions = json.dumps(["READ_OWN_SLICE", "READ_OWN_RANKING"], ensure_ascii=False)
    if existing and (existing.valid_to is None or existing.valid_to >= today):
        existing.permissions = permissions
        existing.valid_to = payload.get("valid_to") or None
    else:
        db.add(
            ent.DelegatedScope(
                tenant_id=tenant_id,
                platform_operator_id=link.id,
                scope_type="OPERATOR",
                scope_id=link.operator_tenant_id,
                permissions=permissions,
                valid_from=today,
                valid_to=payload.get("valid_to") or None,
            )
        )
    db.commit()
    return {"ok": True, "operator_id": link.id, "portal": "OPEN"}


@router.post("/credentials", status_code=201)
def create_credential(
    payload: PartnerCredentialCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    # H6 FIX: Use 16-char prefix with retry loop for collision safety
    for _ in range(5):
        raw_key = secrets.token_urlsafe(32)
        key_prefix = raw_key[:16]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        existing = (
            db.query(ent.PartnerCredential)
            .filter(
                ent.PartnerCredential.tenant_id == tenant_id,
                ent.PartnerCredential.key_prefix == key_prefix,
            )
            .first()
        )
        if not existing:
            break
    else:
        raise HTTPException(
            500, "Unable to generate unique key prefix after 5 attempts"
        )
    row = ent.PartnerCredential(
        tenant_id=tenant_id,
        partner_name=payload.partner_name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=payload.scopes,
        rate_limit_per_minute=payload.rate_limit_per_minute,
        idempotency_window_seconds=payload.idempotency_window_seconds,
        expires_at=payload.expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "partner_name": row.partner_name,
        "api_key": raw_key,
        "key_prefix": row.key_prefix,
    }


@router.get("/credentials")
def list_credentials(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.PartnerCredential).filter(
        ent.PartnerCredential.tenant_id == tenant_id
    )
    if active_only:
        q = q.filter(ent.PartnerCredential.is_active.is_(True))
    return [
        {
            "id": r.id,
            "partner_name": r.partner_name,
            "key_prefix": r.key_prefix,
            "scopes": r.scopes,
            "rate_limit_per_minute": r.rate_limit_per_minute,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.PartnerCredential.partner_name).all()
    ]


@router.post("/credentials/{credential_id}/rotate", status_code=200)
def rotate_credential(
    credential_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.PartnerCredential, credential_id, tenant_id)
    # H6 FIX: Generate new key with 16-char prefix
    raw_key = secrets.token_urlsafe(32)
    key_prefix = raw_key[:16]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    row.key_prefix = key_prefix
    row.key_hash = key_hash
    row.last_rotated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "api_key": raw_key,
        "key_prefix": row.key_prefix,
        "last_rotated_at": row.last_rotated_at.isoformat(),
    }


@router.patch("/credentials/{credential_id}")
def update_credential(
    credential_id: int,
    payload: PartnerCredentialUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.PartnerCredential, credential_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "partner_name": row.partner_name,
        "key_prefix": row.key_prefix,
    }


# ---------- webhook endpoints ----------


@router.post("/webhooks", status_code=201)
def create_webhook(
    payload: WebhookEndpointCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.WebhookEndpoint)
        .filter(
            ent.WebhookEndpoint.tenant_id == tenant_id,
            ent.WebhookEndpoint.url == payload.url,
            ent.WebhookEndpoint.event_type == payload.event_type,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Webhook endpoint already exists")
    # Generate secret
    secret = secrets.token_urlsafe(32)
    secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    row = ent.WebhookEndpoint(
        tenant_id=tenant_id,
        url=payload.url,
        event_type=payload.event_type,
        secret_hash=secret_hash,
        is_inbound=payload.is_inbound,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "url": row.url,
        "event_type": row.event_type,
        "secret": secret,
    }


@router.get("/webhooks")
def list_webhooks(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.WebhookEndpoint).filter(ent.WebhookEndpoint.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ent.WebhookEndpoint.is_active.is_(True))
    return [
        {
            "id": r.id,
            "url": r.url,
            "event_type": r.event_type,
            "is_inbound": r.is_inbound,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.WebhookEndpoint.created_at).all()
    ]


@router.patch("/webhooks/{webhook_id}")
def update_webhook(
    webhook_id: int,
    payload: WebhookEndpointUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.WebhookEndpoint, webhook_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "url": row.url, "event_type": row.event_type}


# ---------- integration audit ----------
# M1 FIX: Removed user-facing audit creation endpoint.
# Audit logs should be created internally by system operations (credential usage, logins, etc.)
# not by direct user API calls.
def list_integration_audit(
    credential_id: Optional[int] = Query(None),
    direction: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.IntegrationAuditLog).filter(
        ent.IntegrationAuditLog.tenant_id == tenant_id
    )
    if credential_id:
        q = q.filter(ent.IntegrationAuditLog.credential_id == credential_id)
    if direction:
        q = q.filter(ent.IntegrationAuditLog.direction == direction)
    return [
        {
            "id": r.id,
            "credential_id": r.credential_id,
            "direction": r.direction,
            "event_type": r.event_type,
            "status_code": r.status_code,
            "timestamp": r.timestamp.isoformat(),
        }
        for r in q.order_by(ent.IntegrationAuditLog.timestamp.desc()).all()
    ]


# ---------- MFA settings ----------


@router.post("/mfa-settings", status_code=201)
def create_mfa_setting(
    payload: MFASettingCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.MFASetting)
        .filter(
            ent.MFASetting.tenant_id == tenant_id,
            ent.MFASetting.role == payload.role,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "MFA setting already exists for this role")
    row = ent.MFASetting(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "role": row.role, "mfa_required": row.mfa_required}


@router.get("/mfa-settings")
def list_mfa_settings(user: ent.User = Depends(get_current_user), db=Depends(get_db)):
    tenant_id = _tenant_id(user)
    q = db.query(ent.MFASetting).filter(ent.MFASetting.tenant_id == tenant_id)
    return [
        {
            "id": r.id,
            "role": r.role,
            "mfa_required": r.mfa_required,
            "allowed_methods": r.allowed_methods,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.MFASetting.role).all()
    ]


@router.patch("/mfa-settings/{mfa_id}")
def update_mfa_setting(
    mfa_id: int,
    payload: MFASettingUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.MFASetting, mfa_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "role": row.role, "mfa_required": row.mfa_required}


# ---------- security audit ----------
# M1 FIX: Removed user-facing audit creation endpoint.
# Security audit logs should be created internally by system operations (logins, MFA changes, etc.)
def list_security_audit(
    action: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.SecurityAuditLog).filter(
        ent.SecurityAuditLog.tenant_id == tenant_id
    )
    if action:
        q = q.filter(ent.SecurityAuditLog.action == action)
    return [
        {
            "id": r.id,
            "actor_id": r.actor_id,
            "actor_role": r.actor_role,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "timestamp": r.timestamp.isoformat(),
        }
        for r in q.order_by(ent.SecurityAuditLog.timestamp.desc()).all()
    ]


# ---------- data residency ----------


@router.post("/data-residency", status_code=201)
def create_data_residency(
    payload: DataResidencyCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.DataResidencyRule)
        .filter(
            ent.DataResidencyRule.tenant_id == tenant_id,
            ent.DataResidencyRule.data_type == payload.data_type,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            409, "Data residency rule already exists for this data type"
        )
    row = ent.DataResidencyRule(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "data_type": row.data_type,
        "required_region": row.required_region,
    }


@router.get("/data-residency")
def list_data_residency(user: ent.User = Depends(get_current_user), db=Depends(get_db)):
    tenant_id = _tenant_id(user)
    q = db.query(ent.DataResidencyRule).filter(
        ent.DataResidencyRule.tenant_id == tenant_id
    )
    return [
        {
            "id": r.id,
            "data_type": r.data_type,
            "required_region": r.required_region,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.DataResidencyRule.data_type).all()
    ]


@router.patch("/data-residency/{rule_id}")
def update_data_residency(
    rule_id: int,
    payload: DataResidencyUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.DataResidencyRule, rule_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "data_type": row.data_type,
        "required_region": row.required_region,
    }


# ---------- SLA settings ----------


@router.post("/sla-settings", status_code=201)
def create_sla_setting(
    payload: SLASettingCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.SLASetting)
        .filter(
            ent.SLASetting.tenant_id == tenant_id,
            ent.SLASetting.metric_name == payload.metric_name,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "SLA setting already exists for this metric")
    row = ent.SLASetting(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "metric_name": row.metric_name,
        "target_value": row.target_value,
    }


@router.get("/sla-settings")
def list_sla_settings(user: ent.User = Depends(get_current_user), db=Depends(get_db)):
    tenant_id = _tenant_id(user)
    q = db.query(ent.SLASetting).filter(ent.SLASetting.tenant_id == tenant_id)
    return [
        {
            "id": r.id,
            "metric_name": r.metric_name,
            "target_value": r.target_value,
            "unit": r.unit,
            "measurement_window": r.measurement_window,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.SLASetting.metric_name).all()
    ]


@router.patch("/sla-settings/{sla_id}")
def update_sla_setting(
    sla_id: int,
    payload: SLASettingUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.SLASetting, sla_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "metric_name": row.metric_name,
        "target_value": row.target_value,
    }
