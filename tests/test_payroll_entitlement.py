"""A platform account cannot reach payroll just by typing the URL.

`Tenant.capabilities` decides what an account buys, and the fleet sidebar reads
it: a DELIVERY_PLATFORM account has no RIDER_PAYROLL, so the Payroll nav item is
not rendered. That was the whole enforcement. `GET /hr/payroll` returned 200 for
that same account, and so did finalize, status, overrides, the rider statement
and the WPS bank export.

CLAUDE.md states the rule this broke: the backend is the only authority on
access, and hiding something in the frontend is not authorization. It matters
commercially as well as technically — the two business lines are priced by
capability, so a capability enforced only in the browser is not sold, it is
suggested.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.entities import Capability, Country, CustomerType, Tenant, User, UserRole
from app.routers.auth import create_token, hash_password
from app.services import entitlements

# Every payroll surface, not just the one the screen calls. A guard on the read
# and not the write would let a platform finalize a month it cannot see.
PAYROLL_READS = [
    "/hr/payroll?month=2026-09",
    # The analytics payroll router is a second money surface with its own
    # chokepoint; it checked role and not entitlement.
    "/analytics/payroll/summary?period=2026-09",
    "/analytics/payroll/ledger?period=2026-09",
    "/analytics/payroll/incentives?period=2026-09",
    "/analytics/payroll/cost-summary?period=2026-09",
    "/hr/payroll/rider/1/statement?month=2026-09",
    "/hr/payroll/wps-export?month=2026-09",
]
PAYROLL_WRITES = [
    ("/hr/payroll/status", {"month": "2026-09", "status": "APPROVED"}),
    ("/hr/payroll/finalize", {"month": "2026-09"}),
    ("/hr/payroll/override-orders", {"month": "2026-09", "overrides": []}),
    (
        "/hr/payroll/corrections",
        {
            "courier_id": 1,
            "original_month": "2026-08",
            "target_month": "2026-09",
            "amount": 100,
        },
    ),
]


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()

    def account(name, customer_type, capabilities, phone):
        tenant = Tenant(
            name=name,
            country=Country.SA,
            plan="PRO",
            subscription_status="ACTIVE",
            customer_type=customer_type.value,
            capabilities=entitlements.serialize(capabilities),
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        user = User(
            phone=phone,
            name=name,
            role=UserRole.COMPANY_ADMIN,
            tenant_id=tenant.id,
            is_active=True,
            password_hash=hash_password("Pass12345!"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"tenant": tenant, "token": create_token(user)}

    platform = account(
        "Ninja KSA",
        CustomerType.DELIVERY_PLATFORM,
        entitlements.PLATFORM_DEFAULTS,
        "966590000001",
    )
    logistics = account(
        "Al-Rowad Logistics",
        CustomerType.LOGISTICS_OPERATOR,
        entitlements.LOGISTICS_DEFAULTS,
        "966590000002",
    )

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield {"client": client, "platform": platform, "logistics": logistics, "db": db}
    app.dependency_overrides.clear()
    db.close()


def _auth(account):
    return {"Authorization": f"Bearer {account['token']}"}


def test_the_platform_defaults_really_exclude_payroll(env):
    """If this ever changes, every assertion below becomes meaningless."""
    caps = entitlements.capabilities_for(env["platform"]["tenant"])
    assert Capability.RIDER_PAYROLL.value not in caps


@pytest.mark.parametrize("path", PAYROLL_READS)
def test_a_platform_account_cannot_read_payroll(env, path):
    res = env["client"].get(path, headers=_auth(env["platform"]))
    assert res.status_code == 403, (
        f"{path} answered {res.status_code} for an account with no RIDER_PAYROLL; "
        "the sidebar hides the screen but the endpoint served it"
    )


@pytest.mark.parametrize("path,payload", PAYROLL_WRITES)
def test_a_platform_account_cannot_write_payroll(env, path, payload):
    res = env["client"].post(path, json=payload, headers=_auth(env["platform"]))
    assert res.status_code == 403, (
        f"{path} answered {res.status_code}; a platform account could act on a "
        "payroll it is not entitled to"
    )


def test_a_logistics_account_is_unaffected(env):
    """The guard must not cost the accounts that do buy payroll."""
    res = env["client"].get("/hr/payroll?month=2026-09", headers=_auth(env["logistics"]))
    assert res.status_code == 200, res.text


# ─────────────────────────────────────────────────────────────────────────────
# The mirror image: vendor settlements belong to the platform line
# ─────────────────────────────────────────────────────────────────────────────

# operator_id and period_month are query parameters, so they go in the URL —
# a malformed request 422s before the guard and would prove nothing.
VENDOR_SETTLEMENT_SURFACES = [
    ("GET", "/analytics/operators/settlements", None),
    ("POST", "/analytics/operators/settlement/calculate?operator_id=1&period_month=2026-09", None),
    ("POST", "/analytics/operators/settlement/save?operator_id=1&period_month=2026-09", {}),
]


@pytest.mark.parametrize("method,path,payload", VENDOR_SETTLEMENT_SURFACES)
def test_a_logistics_account_cannot_reach_vendor_settlements(env, method, path, payload):
    """A logistics company buys neither MANAGE_OPERATORS nor OPERATOR_SETTLEMENTS.

    /analytics/operators checked role and not entitlement, exactly as payroll
    did, so a logistics account could calculate, save and approve the B2B
    settlements that belong to the platform business line.
    """
    client, headers = env["client"], _auth(env["logistics"])
    res = (
        client.get(path, headers=headers)
        if method == "GET"
        else client.post(path, json=payload, headers=headers)
    )
    assert res.status_code == 403, (
        f"{method} {path} answered {res.status_code} for an account with no "
        "OPERATOR_SETTLEMENTS capability"
    )


def test_a_platform_account_still_reaches_vendor_settlements(env):
    res = env["client"].get(
        "/analytics/operators/settlements", headers=_auth(env["platform"])
    )
    assert res.status_code == 200, res.text


def test_a_tenant_predating_capabilities_keeps_payroll(env):
    """An empty capabilities column falls back to the account type's defaults.

    Tenants created before capabilities existed have the column NULL. Reading
    that as "no capabilities" would take payroll away from every existing
    customer the moment this guard shipped.
    """
    tenant = env["logistics"]["tenant"]
    for stored in (None, "", "[]"):
        # Every live tenant on production holds "[]" in this column, not NULL,
        # and an empty list must read as "not set" rather than "nothing allowed".
        tenant.capabilities = stored
        tenant.customer_type = None
        env["db"].commit()
        res = env["client"].get(
            "/hr/payroll?month=2026-09", headers=_auth(env["logistics"])
        )
        assert res.status_code == 200, f"capabilities={stored!r}: {res.text}"
