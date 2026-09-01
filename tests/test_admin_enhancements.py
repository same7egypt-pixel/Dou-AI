"""Tests for DOU Super Admin Portal enhancements: Company 360, Operators, Usage, Health, Integrations, DOU Team."""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

os.environ["ADMIN_KEY"] = "test-admin-key"

from app.main import app
from app.database import Base, get_db
from app.models.entities import (
    Tenant, User, UserRole, Courier, CourierType, Country, SubscriptionPlan,
    PlatformOperator, WebhookEndpoint,
    DataHealthSnapshot, SourcePlatform,
)
from app.routers.auth import hash_password

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_admin_enhancements.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    # Create admin user
    admin = User(
        name="Admin", phone="966500000001", password_hash=hash_password("admin123456"),
        role=UserRole.DOU_ADMIN, is_active=True,
    )
    db.add(admin)
    # Create plans
    plans = [
        SubscriptionPlan(code="STARTER", name="Starter", name_en="Starter", monthly_price=499, monthly_price_usd=149, max_couriers=10),
        SubscriptionPlan(code="GROWTH", name="Growth", name_en="Growth", monthly_price=999, monthly_price_usd=269, max_couriers=75),
    ]
    db.add_all(plans)
    db.commit()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)


def auth_headers():
    return {"X-Admin-Key": "test-admin-key"}


def test_tenant_profile_returns_company_360(setup_db):
    db = setup_db
    tenant = Tenant(
        name="Test Logistics", country=Country.SA, market_code="SA",
        default_language="ar", currency="SAR", timezone="Asia/Riyadh",
        plan="STARTER", monthly_fee=499, billing_day=1,
        due_date=datetime.utcnow() + timedelta(days=15),
        subscription_status="ACTIVE",
    )
    db.add(tenant)
    db.flush()
    # Add couriers
    for i in range(3):
        db.add(Courier(tenant_id=tenant.id, name=f"Courier {i}", phone=f"96650000001{i}",
                        courier_type=CourierType.COMPANY,
                        employment_status="ACTIVE", country=Country.SA))
    # Add supervisor
    db.add(User(name="Supervisor", phone="966500000020", password_hash=hash_password("pass123456"),
                role=UserRole.SUPERVISOR, tenant_id=tenant.id, is_active=True))
    db.commit()
    resp = client.get(f"/admin/tenants/{tenant.id}/profile", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Logistics"
    assert data["plan"] == "STARTER"
    assert data["subscription_status"] == "ACTIVE"
    assert data["usage"]["couriers"] == 3
    assert data["usage"]["supervisors"] == 1
    assert data["usage"]["max_couriers"] == 10
    assert data["usage"]["usage_pct"] == 30.0
    assert data["days_to_due"] >= 14


def test_tenant_profile_not_found(setup_db):
    resp = client.get("/admin/tenants/99999/profile", headers=auth_headers())
    assert resp.status_code == 404


def test_list_tenant_operators(setup_db):
    db = setup_db
    tenant = Tenant(name="Platform Co", country=Country.SA, market_code="SA",
                    plan="GROWTH", monthly_fee=999)
    db.add(tenant)
    db.flush()
    source = SourcePlatform(tenant_id=tenant.id, code="test", name_ar="Test Platform")
    db.add(source)
    db.flush()
    op = PlatformOperator(tenant_id=tenant.id, source_platform_id=source.id,
                          operator_tenant_id=999, is_active=True)
    db.add(op)
    db.commit()
    resp = client.get(f"/admin/tenants/{tenant.id}/operators", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["operator_tenant_id"] == 999
    assert data[0]["is_active"] is True


def test_operators_health(setup_db):
    db = setup_db
    tenant = Tenant(name="Platform Co", country=Country.SA, plan="GROWTH", monthly_fee=999)
    db.add(tenant)
    db.flush()
    source = SourcePlatform(tenant_id=tenant.id, code="test", name_ar="Test Platform")
    db.add(source)
    db.flush()
    db.add(PlatformOperator(tenant_id=tenant.id, source_platform_id=source.id,
                            operator_tenant_id=1, is_active=True))
    db.add(PlatformOperator(tenant_id=tenant.id, source_platform_id=source.id,
                            operator_tenant_id=2, is_active=False))
    db.commit()
    resp = client.get("/admin/operators/health", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_operators"] == 2
    assert data["active_operators"] == 1
    assert data["inactive_operators"] == 1


def test_usage_summary(setup_db):
    db = setup_db
    for i in range(2):
        t = Tenant(name=f"Tenant {i}", country=Country.SA, plan="STARTER", monthly_fee=499,
                   subscription_status="ACTIVE" if i == 0 else "SUSPENDED")
        db.add(t)
        db.flush()
        for j in range(3):
            db.add(Courier(tenant_id=t.id, name=f"C{i}-{j}", phone=f"9665000001{i}{j}",
                            courier_type=CourierType.COMPANY,
                            employment_status="ACTIVE", country=Country.SA))
    db.commit()
    resp = client.get("/admin/usage/summary", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tenants"] == 2
    assert data["active_tenants"] == 1
    assert data["suspended_tenants"] == 1
    assert data["total_couriers"] == 6


def test_health_detailed(setup_db):
    db = setup_db
    tenant = Tenant(name="T1", country=Country.SA, plan="STARTER", monthly_fee=499)
    db.add(tenant)
    db.flush()
    snap = DataHealthSnapshot(tenant_id=tenant.id, source="import_riders", last_sync_status="SUCCESS", rows_processed=100)
    db.add(snap)
    db.commit()
    resp = client.get("/admin/health/detailed", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["database"] == "ONLINE"
    assert isinstance(data["data_health"], list)


def test_list_integrations(setup_db):
    db = setup_db
    tenant = Tenant(name="T1", country=Country.SA, plan="STARTER", monthly_fee=499)
    db.add(tenant)
    db.flush()
    db.add(WebhookEndpoint(tenant_id=tenant.id, url="https://example.com/webhook", event_type="alert", is_inbound=True))
    db.commit()
    resp = client.get("/admin/integrations", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["url"] == "https://example.com/webhook"
    assert data[0]["event_type"] == "alert"


def test_dou_team_list_and_invite(setup_db):
    db = setup_db
    member = User(name="Ops Member", phone="966500000050", password_hash=hash_password("pass123456"),
                  role=UserRole.DOU_OPS, is_active=True)
    db.add(member)
    db.commit()
    # List - should include admin + member
    resp = client.get("/admin/dou-team", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1  # at least the member we just added
    names = [u["name"] for u in data]
    assert "Ops Member" in names
    # Invite
    invite = {"name": "New Ops", "phone": "966500000060", "role": "DOU_OPS", "password": "newpass123456"}
    resp = client.post("/admin/dou-team", json=invite, headers=auth_headers())
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "New Ops"
    assert data["role"] == "DOU_OPS"
    # Duplicate phone
    resp = client.post("/admin/dou-team", json=invite, headers=auth_headers())
    assert resp.status_code == 400


def test_dou_team_invite_invalid_role(setup_db):
    invite = {"name": "Bad", "phone": "966500000070", "role": "COMPANY", "password": "pass123456"}
    resp = client.post("/admin/dou-team", json=invite, headers=auth_headers())
    assert resp.status_code == 400


def test_dou_team_invite_short_password(setup_db):
    invite = {"name": "Short", "phone": "966500000080", "role": "DOU_OPS", "password": "short"}
    resp = client.post("/admin/dou-team", json=invite, headers=auth_headers())
    assert resp.status_code == 400
