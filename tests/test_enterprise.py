"""Wave 4 tests — platform governance, integration, security, scale."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Courier, CourierType, Country, DataResidencyRule, DelegatedScope,
    IntegrationAuditLog, MFASetting, PartnerCredential,
    PlatformOperator, SecurityAuditLog, SLASetting,
    SourcePlatform, Tenant, User, UserRole, WebhookEndpoint,
)
from app.routers.enterprise import (
    DataResidencyCreate, DataResidencyUpdate,
    DelegatedScopeCreate,
    MFASettingCreate, MFASettingUpdate,
    PartnerCredentialCreate, PartnerCredentialUpdate,
    PlatformOperatorCreate, PlatformOperatorUpdate,
    SLASettingCreate, SLASettingUpdate,
    WebhookEndpointCreate, WebhookEndpointUpdate,
    create_operator, update_operator, list_operators,
    create_delegated_scope, list_delegated_scopes,
    create_credential, list_credentials, rotate_credential, update_credential,
    create_webhook, list_webhooks, update_webhook,
    list_integration_audit,
    create_mfa_setting, list_mfa_settings, update_mfa_setting,
    list_security_audit,
    create_data_residency, list_data_residency, update_data_residency,
    create_sla_setting, list_sla_settings, update_sla_setting,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def make_tenant(db, name):
    tenant = Tenant(name=name, country=Country.SA)
    db.add(tenant); db.commit(); db.refresh(tenant)
    return tenant


def make_user(db, tenant_id, phone, role=UserRole.COMPANY):
    user = User(phone=phone, password_hash="x", role=role, tenant_id=tenant_id)
    db.add(user); db.commit(); db.refresh(user)
    return user


# ---------- platform operators ----------

def test_create_operator(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000001")
    sp = SourcePlatform(tenant_id=tenant.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    result = create_operator(
        PlatformOperatorCreate(source_platform_id=sp.id, operator_tenant_id=tenant.id),
        user, db,
    )
    assert result["operator_tenant_id"] == tenant.id


def test_operator_unique(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    sp = SourcePlatform(tenant_id=tenant.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    create_operator(PlatformOperatorCreate(source_platform_id=sp.id, operator_tenant_id=tenant.id), user, db)
    with pytest.raises(HTTPException) as error:
        create_operator(PlatformOperatorCreate(source_platform_id=sp.id, operator_tenant_id=tenant.id), user, db)
    assert error.value.status_code == 409


# ---------- delegated scopes ----------

def test_create_delegated_scope(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000003")
    sp = SourcePlatform(tenant_id=tenant.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    op = create_operator(PlatformOperatorCreate(source_platform_id=sp.id, operator_tenant_id=tenant.id), user, db)
    result = create_delegated_scope(
        DelegatedScopeCreate(
            platform_operator_id=op["id"], scope_type="PROJECT", scope_id=1,
            valid_from=date(2026, 1, 1),
        ),
        user, db,
    )
    assert result["scope_type"] == "PROJECT"


# ---------- partner credentials ----------

def test_create_credential(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000004")
    result = create_credential(PartnerCredentialCreate(partner_name="Test Partner"), user, db)
    assert result["partner_name"] == "Test Partner"
    assert "api_key" in result
    assert "key_prefix" in result


def test_rotate_credential(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")
    cred = create_credential(PartnerCredentialCreate(partner_name="Test Partner"), user, db)
    old_prefix = cred["key_prefix"]
    result = rotate_credential(cred["id"], user, db)
    assert "api_key" in result
    assert result["key_prefix"] != old_prefix


# ---------- webhook endpoints ----------

def test_create_webhook(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    result = create_webhook(
        WebhookEndpointCreate(url="https://example.com/webhook", event_type="ORDER_CREATED"),
        user, db,
    )
    assert result["url"] == "https://example.com/webhook"
    assert "secret" in result


def test_webhook_unique_url_event(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    create_webhook(WebhookEndpointCreate(url="https://example.com/webhook", event_type="ORDER_CREATED"), user, db)
    with pytest.raises(HTTPException) as error:
        create_webhook(WebhookEndpointCreate(url="https://example.com/webhook", event_type="ORDER_CREATED"), user, db)
    assert error.value.status_code == 409


# ---------- integration audit ----------
# M1 FIX: Integration audit creation endpoint removed (system-only)

# ---------- MFA settings ----------

def test_create_mfa_setting(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000009")
    result = create_mfa_setting(
        MFASettingCreate(role="COMPANY_ADMIN", mfa_required=True, allowed_methods='["TOTP", "SMS"]'),
        user, db,
    )
    assert result["mfa_required"] is True


def test_mfa_unique_per_role(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000010")
    create_mfa_setting(MFASettingCreate(role="COMPANY_ADMIN", mfa_required=True), user, db)
    with pytest.raises(HTTPException) as error:
        create_mfa_setting(MFASettingCreate(role="COMPANY_ADMIN", mfa_required=False), user, db)
    assert error.value.status_code == 409


# ---------- security audit ----------
# M1 FIX: Security audit creation endpoint removed (system-only)


# ---------- data residency ----------

def test_create_data_residency(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000012")
    result = create_data_residency(
        DataResidencyCreate(data_type="PERSONAL", required_region="SA"),
        user, db,
    )
    assert result["data_type"] == "PERSONAL"
    assert result["required_region"] == "SA"


def test_data_residency_unique_per_type(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000013")
    create_data_residency(DataResidencyCreate(data_type="PERSONAL", required_region="SA"), user, db)
    with pytest.raises(HTTPException) as error:
        create_data_residency(DataResidencyCreate(data_type="PERSONAL", required_region="EU"), user, db)
    assert error.value.status_code == 409


# ---------- SLA settings ----------

def test_create_sla_setting(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000014")
    result = create_sla_setting(
        SLASettingCreate(metric_name="UPTIME", target_value=99.9, unit="PERCENTAGE"),
        user, db,
    )
    assert result["metric_name"] == "UPTIME"
    assert result["target_value"] == 99.9


def test_sla_unique_per_metric(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000015")
    create_sla_setting(SLASettingCreate(metric_name="UPTIME", target_value=99.9), user, db)
    with pytest.raises(HTTPException) as error:
        create_sla_setting(SLASettingCreate(metric_name="UPTIME", target_value=99.5), user, db)
    assert error.value.status_code == 409


# ---------- tenant isolation ----------

def test_cross_tenant_operator_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000016")
    sp = SourcePlatform(tenant_id=tenant1.id, code="HS", name_ar="هنقرستيشن")
    db.add(sp); db.commit()
    op = create_operator(PlatformOperatorCreate(source_platform_id=sp.id, operator_tenant_id=tenant1.id), user1, db)
    user2 = make_user(db, tenant2.id, "966500000017")
    with pytest.raises(HTTPException) as error:
        update_operator(op["id"], PlatformOperatorUpdate(relationship_type="FRANCHISE"), user2, db)
    assert error.value.status_code == 404


def test_cross_tenant_credential_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000018")
    cred = create_credential(PartnerCredentialCreate(partner_name="Test"), user1, db)
    user2 = make_user(db, tenant2.id, "966500000019")
    with pytest.raises(HTTPException) as error:
        rotate_credential(cred["id"], user2, db)
    assert error.value.status_code == 404
