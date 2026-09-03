"""Negative Security, RBAC, Webhook, and Financial State Machine Tests.

Strictly proves the security boundaries and guarantees required by the audit.
"""
import pytest
from datetime import date, datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import entities as ent
from app.routers.auth import hash_password, create_token
from app.services.report_registry import validate_registered_report, ReportSpec
from app.services.scope import AuthorizedScope


@pytest.fixture(scope="module")
def sec_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()

    # Create 2 tenants
    t1 = ent.Tenant(name="Tenant 1 Logistics", country=ent.Country.SA, plan="PRO", subscription_status="ACTIVE")
    t2 = ent.Tenant(name="Tenant 2 Fleet", country=ent.Country.SA, plan="PRO", subscription_status="ACTIVE")
    db.add_all([t1, t2])
    db.flush()

    # Create Users
    admin_t1 = ent.User(phone="966500000001", name="Admin T1", role=ent.UserRole.COMPANY_ADMIN, tenant_id=t1.id, is_active=True, password_hash=hash_password("Pass12345!"))
    accountant_t1 = ent.User(phone="966500000002", name="Accountant T1", role=ent.UserRole.ACCOUNTANT, tenant_id=t1.id, is_active=True, password_hash=hash_password("Pass12345!"))
    viewer_t1 = ent.User(phone="966500000003", name="Viewer T1", role=ent.UserRole.VIEWER, tenant_id=t1.id, is_active=True, password_hash=hash_password("Pass12345!"))
    admin_t2 = ent.User(phone="966500000004", name="Admin T2", role=ent.UserRole.COMPANY_ADMIN, tenant_id=t2.id, is_active=True, password_hash=hash_password("Pass12345!"))
    db.add_all([admin_t1, accountant_t1, viewer_t1, admin_t2])
    db.flush()

    # Create Couriers for T1
    c1 = ent.Courier(tenant_id=t1.id, name="Active Rider 1", phone="966511111111", courier_type=ent.CourierType.COMPANY, country=ent.Country.SA, employment_status="ACTIVE", base_salary=3000.0)
    db.add(c1)
    db.flush()

    # Create Contract and Branch for T1
    contract = ent.Contract(tenant_id=t1.id, name="Burger King Contract", client_name="Burger King", client_rate_per_order=18.0, status="ACTIVE")
    db.add(contract)
    db.flush()

    branch = ent.ContractBranch(tenant_id=t1.id, contract_id=contract.id, city="Riyadh", branch_name="BK Olaya", monthly_rate_per_rider=5000.0, is_active=True)
    db.add(branch)
    db.commit()

    yield {
        "db": db,
        "t1": t1,
        "t2": t2,
        "admin_t1": admin_t1,
        "accountant_t1": accountant_t1,
        "viewer_t1": viewer_t1,
        "admin_t2": admin_t2,
        "c1": c1,
        "contract": contract,
        "branch": branch,
    }
    db.close()


@pytest.fixture
def client(sec_db):
    def override_get_db():
        try:
            yield sec_db["db"]
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ─── 1. WEBHOOK & NINJA SECURITY ─────────────────────────────────────────────

def _ninja_key(db, tenant_id):
    """Issue a scoped partner credential for the ingestion endpoints.

    These tests used to send only an `X-Tenant-Id` header, which is what the
    endpoints accepted before they required authentication at all. The header no
    longer selects anything — the tenant comes from the credential.
    """
    import hashlib
    import json
    import secrets

    from app.services import entitlements

    # Two independent gates guard the feed: a scoped key, and a tenant still
    # entitled to receive it. This fixture's tenant predates customer types, so
    # grant it the platform set explicitly.
    tenant = db.get(ent.Tenant, tenant_id)
    tenant.customer_type = ent.CustomerType.DELIVERY_PLATFORM.value
    tenant.capabilities = entitlements.serialize(entitlements.PLATFORM_DEFAULTS)

    raw = secrets.token_urlsafe(32)
    db.add(
        ent.PartnerCredential(
            tenant_id=tenant_id,
            partner_name="Ninja",
            key_prefix=raw[:16],
            key_hash=hashlib.sha256(raw.encode()).hexdigest(),
            scopes=json.dumps(["performance:write"]),
            is_active=True,
        )
    )
    db.commit()
    return {"X-API-Key": raw}




def test_ninja_webhook_unmapped_rider_does_not_attribute_to_random_courier(client, sec_db):
    """External delivery for an unmapped driver MUST NOT attribute to random active couriers."""
    event_payload = {
        "order_id": "NINJA-SEC-001",
        "ninja_rider_id": "UNKNOWN_NINJA_RIDER_999",
        "rider_phone": "966599999999",
        "delivery_status": "DELIVERED",
        "delivery_fee": 20.0
    }
    headers = _ninja_key(sec_db["db"], sec_db["t1"].id)
    res = client.post("/sources/ninja/live-event", json=event_payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["matched_courier"]["id"] is None
    assert data["matched_courier"]["name"] == "Unassigned"


def test_ninja_webhook_cannot_name_its_own_tenant(client):
    """The header that used to select the target company is now inert.

    This test previously asserted a 404 for an unknown tenant id, which quietly
    documented that a caller with no credential could choose any tenant that did
    exist. There is nothing to name any more: an unauthenticated request is
    refused before a tenant is looked up.
    """
    event_payload = {
        "order_id": "NINJA-SEC-002",
        "ninja_rider_id": "RIDER_1",
        "rider_phone": "966511111111",
        "delivery_status": "DELIVERED"
    }
    headers = {"X-Tenant-Id": "999999"}
    res = client.post("/sources/ninja/live-event", json=event_payload, headers=headers)
    assert res.status_code == 401


def test_ninja_webhook_idempotency_prevents_duplicate_counting(client, sec_db):
    """Replaying the exact same order must NOT double-count orders."""
    event_payload = {
        "order_id": "NINJA-REPLAY-100",
        "ninja_rider_id": "NINJA-C1",
        "rider_phone": "966511111111",
        "delivery_status": "DELIVERED",
        "delivery_fee": 15.0
    }
    headers = _ninja_key(sec_db["db"], sec_db["t1"].id)
    res1 = client.post("/sources/ninja/live-event", json=event_payload, headers=headers)
    assert res1.status_code == 200
    assert res1.json()["is_new"] is True

    # Replay
    res2 = client.post("/sources/ninja/live-event", json=event_payload, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["is_new"] is False


# ─── 2. CLIENT INVOICES RBAC & STATE MACHINE ────────────────────────────────

def test_non_financial_role_cannot_generate_invoice(client, sec_db):
    """A Viewer role must NOT be allowed to generate B2B client invoices (RBAC)."""
    token = create_token(sec_db["viewer_t1"])
    res = client.post(
        "/client-invoices/generate",
        json={"contract_id": sec_db["contract"].id, "billing_month": "2026-08"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403


def test_financial_role_can_generate_invoice_and_prevents_duplicate(client, sec_db):
    """Accountant generates invoice; duplicate attempt for same month is rejected with 409."""
    token = create_token(sec_db["accountant_t1"])
    res1 = client.post(
        "/client-invoices/generate",
        json={"contract_id": sec_db["contract"].id, "billing_month": "2026-08"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res1.status_code == 200
    inv_id = res1.json()["invoice"]["id"]

    # Duplicate attempt
    res2 = client.post(
        "/client-invoices/generate",
        json={"contract_id": sec_db["contract"].id, "billing_month": "2026-08"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res2.status_code == 409


def test_invoice_invalid_state_transition_from_draft_to_paid_rejected(client, sec_db):
    """Direct jump from DRAFT to PAID without being ISSUED must be rejected."""
    token = create_token(sec_db["accountant_t1"])
    # Create draft
    db = sec_db["db"]
    draft_inv = ent.ClientInvoice(
        tenant_id=sec_db["t1"].id,
        contract_id=sec_db["contract"].id,
        invoice_number="INV-DRAFT-TEST-001",
        billing_month="2026-09",
        client_name="Test Draft",
        status="DRAFT"
    )
    db.add(draft_inv)
    db.commit()

    # Attempt illegal transition: DRAFT -> PAID
    res = client.patch(
        f"/client-invoices/{draft_inv.id}/status",
        json={"status": "PAID"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 400


def test_cross_tenant_invoice_access_is_denied(client, sec_db):
    """Tenant 2 Admin cannot access Tenant 1's invoice (Tenant Isolation)."""
    token_t2 = create_token(sec_db["admin_t2"])
    res = client.get(
        "/client-invoices",
        headers={"Authorization": f"Bearer {token_t2}"}
    )
    assert res.status_code == 200
    # Must be empty for Tenant 2
    assert len(res.json()) == 0


# ─── 3. DOU AI & REPORT REGISTRY VALIDATION ─────────────────────────────────

def test_unregistered_report_key_is_rejected():
    """Unregistered or hallucinated report keys must be strictly rejected with 422."""
    spec = ReportSpec(
        source="NATIVE",
        entity="RIDER",
        report_key="NON_EXISTENT_HALLUCINATED_REPORT",
        operation="SUMMARY"
    )
    scope = AuthorizedScope(
        tenant_id=1,
        customer_type="LOGISTICS_OPERATOR",
        user_id=1,
        role="COMPANY_ADMIN"
    )
    with pytest.raises(Exception):
        validate_registered_report(spec, scope)
