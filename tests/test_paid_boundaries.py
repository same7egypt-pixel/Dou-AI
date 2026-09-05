"""What the pricing page promises must be what the API enforces.

Two boundaries are sold and were previously decorative:

1. The plan's rider cap. `create_rider_record` enforced it, but the older
   `POST /couriers` route built a `Courier` straight from the payload, so a
   customer on a ten-rider plan could add two hundred through the API.

2. Suspension for non-payment. This one turned out to be already enforced, but
   not where you would look for it: `get_current_user` calls `check_active` on
   every authenticated request, so the two literal call sites in `fleet.py` and
   `auth.py` are not the coverage — the shared auth dependency is. Counting the
   string `check_active` inside the router files reads 2 of ~164 and is wrong.

The suspension test walks one endpoint per operational router. It is pinned to
the observable behaviour, not to the mechanism: delete the call in
`get_current_user` and five of these six go red (fleet has its own second check
inside `_scope`), which is what makes it a guard rather than a restatement.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import entities as ent
from app.routers.auth import create_token, hash_password


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _company(db, *, status="ACTIVE", plan="STARTER", max_couriers=None, seed="1"):
    """A tenant, its plan, and a company admin holding a valid token."""
    if max_couriers is not None:
        db.add(ent.SubscriptionPlan(code=plan, name=plan, max_couriers=max_couriers))
    tenant = ent.Tenant(
        name=f"شركة {seed}",
        country=ent.Country.SA,
        plan=plan,
        subscription_status=status,
    )
    db.add(tenant)
    db.flush()
    user = ent.User(
        phone=f"96650000{seed:0>4}",
        name="مدير",
        role=ent.UserRole.COMPANY_ADMIN,
        tenant_id=tenant.id,
        is_active=True,
        password_hash=hash_password("Pass12345!"),
    )
    db.add(user)
    db.commit()
    token = create_token(user)
    return tenant, user, {"Authorization": f"Bearer {token}"}


# ─── 1. the plan's rider cap ─────────────────────────────────────────────────


def test_the_rider_cap_is_enforced_on_the_couriers_route(db, client):
    """A plan capped at one rider must refuse the second one."""
    tenant, _, headers = _company(db, plan="CAP1", max_couriers=1)

    first = client.post(
        "/couriers",
        json={
            "name": "مندوب أول",
            "phone": "966511111111",
            "courier_type": "COMPANY",
            "country": "SA",
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/couriers",
        json={
            "name": "مندوب ثانٍ",
            "phone": "966511111112",
            "courier_type": "COMPANY",
            "country": "SA",
        },
        headers=headers,
    )
    assert second.status_code == 422, (
        "the second rider was created past a one-rider plan; the cap is "
        f"decorative ({second.status_code})"
    )
    assert db.query(ent.Courier).filter(ent.Courier.tenant_id == tenant.id).count() == 1


def test_a_plan_without_a_cap_still_creates_riders(db, client):
    """max_couriers of 0 means unlimited, and must not become a wall."""
    _, _, headers = _company(db, plan="UNCAPPED", max_couriers=0, seed="2")
    for i, phone in enumerate(("966522222221", "966522222222")):
        res = client.post(
            "/couriers",
            json={
                "name": f"مندوب {i}",
                "phone": phone,
                "courier_type": "COMPANY",
                "country": "SA",
            },
            headers=headers,
        )
        assert res.status_code == 200, res.text


# ─── 2. suspension for non-payment ───────────────────────────────────────────

# One live GET per gated router. A router-level dependency covers every route
# it carries, so one representative proves the declaration is still there.
GATED = [
    "/fleet/overview",
    "/hr/supervisors",
    "/couriers",
    "/shifts",
    "/salary/structures",
    "/analytics/payroll/summary",
]


@pytest.mark.parametrize("path", GATED)
def test_a_suspended_company_is_refused_on_every_operational_router(db, client, path):
    _, _, headers = _company(db, status="SUSPENDED", seed="3")
    res = client.get(path, headers=headers)
    assert res.status_code == 403, (
        f"{path} served a suspended company ({res.status_code}); suspension is "
        "not enforced on this router"
    )


@pytest.mark.parametrize("path", GATED)
def test_an_active_company_is_not_refused(db, client, path):
    """The gate must refuse only the suspended — an over-broad dependency that
    403s everyone would pass the test above and break every customer."""
    _, _, headers = _company(db, status="ACTIVE", seed="4")
    res = client.get(path, headers=headers)
    assert res.status_code != 403, f"{path} refused a paying company"
