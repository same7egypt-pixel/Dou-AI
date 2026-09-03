"""A city is a reference, not a string somebody typed.

Every rider and every branch carries both `city_id` — a GeoCity the tenant has
activated — and a legacy text field. `find_or_create_city` normalizes case and
whitespace, so "الرياض", "الرياض " and "  الرياض  " all resolve to one GeoCity.
The text does not: it is stored as typed.

The daily report filtered on the text with an exact match. Three riders in the
same city, whose work_city happened to be written three ways, were one city by
reference and three by string — and a supervisor filtering by city was shown one
of the three with nothing to say the other two existed. Measured before the fix:
1 of 3, then 1, then 0, depending on the spacing in the query.

Assigning a rider to a branch set the text and not the reference, so the
divergence came back on the next assignment even after the backfill in
db_maintenance had cleaned it up.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.entities import (
    Contract,
    ContractBranch,
    Country,
    Courier,
    CourierType,
    Project,
    CustomerType,
    Tenant,
    User,
    UserRole,
)
from app.routers.auth import create_token, hash_password
from app.services import entitlements
from app.services.operating_structure import (
    ensure_tenant_operating_city,
    find_or_create_city,
)


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    tenant = Tenant(
        name="شركة لوجستية",
        country=Country.SA,
        plan="PRO",
        subscription_status="ACTIVE",
        customer_type=CustomerType.LOGISTICS_OPERATOR.value,
        capabilities=entitlements.serialize(entitlements.LOGISTICS_DEFAULTS),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    user = User(
        phone="966590000001", name="مدير", role=UserRole.COMPANY_ADMIN,
        tenant_id=tenant.id, is_active=True, password_hash=hash_password("Pass12345!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    city = find_or_create_city(db, tenant, "الرياض")
    db.commit()
    ensure_tenant_operating_city(db, tenant, city)
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    yield {
        "db": db, "client": TestClient(app), "tenant": tenant, "user": user,
        "city": city, "H": {"Authorization": f"Bearer {create_token(user)}"},
    }
    app.dependency_overrides.clear()
    db.close()


# `city_id=None` has to mean "no city", which is the whole point of the rows the
# backfill could not resolve. Defaulting on `is not None` silently gave every
# such rider the tenant's city instead — and both tests that depend on a rider
# without one passed against a mutation that removed the behaviour they check.
_DEFAULT = object()


def _rider(env, index, work_city, city_id=_DEFAULT):
    rider = Courier(
        tenant_id=env["tenant"].id,
        name=f"مندوب {index}",
        phone=f"96659900000{index}",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
        city_id=env["city"].id if city_id is _DEFAULT else city_id,
        work_city=work_city,
    )
    env["db"].add(rider)
    env["db"].commit()
    env["db"].refresh(rider)
    return rider


def _report(env, **params):
    res = env["client"].get(
        "/hr/daily-report", params={"day": "2026-09-01", **params}, headers=env["H"]
    )
    assert res.status_code == 200, res.text
    body = res.json()
    return body.get("rows") or body.get("riders") or (body if isinstance(body, list) else [])


def test_one_city_written_three_ways_is_still_one_city(env):
    """Measured before the fix: 1 of 3, 1 of 3, then 0 of 3."""
    for i, spelling in enumerate(["الرياض", "الرياض ", " الرياض"]):
        _rider(env, i, spelling)

    assert len(_report(env)) == 3, "the fixture itself is wrong"
    for query in ("الرياض", "الرياض ", "  الرياض  "):
        assert len(_report(env, zone=query)) == 3, (
            f"filtering by {query!r} lost riders that share one canonical city"
        )


def test_a_rider_in_another_city_is_still_excluded(env):
    """Reading the reference must not turn the filter into a no-op."""
    jeddah = find_or_create_city(env["db"], env["tenant"], "جدة")
    env["db"].commit()
    ensure_tenant_operating_city(env["db"], env["tenant"], jeddah)
    env["db"].commit()

    _rider(env, 1, "الرياض")
    _rider(env, 2, "جدة", city_id=jeddah.id)

    riyadh = _report(env, zone="الرياض")
    assert len(riyadh) == 1
    assert riyadh[0].get("name") == "مندوب 1" or "مندوب 1" in str(riyadh[0])


def test_a_rider_the_backfill_could_not_resolve_is_still_found_by_text(env):
    """Rows with no reference yet must not disappear from the filter."""
    _rider(env, 1, "الرياض", city_id=None)
    assert len(_report(env, zone="الرياض")) == 1


def test_an_unknown_city_matches_nothing_rather_than_everything(env):
    """A filter is not a command. The resolver raises when a name matches no
    activated city, and reading the reference without catching that turned a
    report filtered by an unrecognised city into a 500."""
    _rider(env, 1, "الرياض")
    assert _report(env, zone="الدمام") == []


def _branch(env, city, text_city):
    contract = Contract(
        tenant_id=env["tenant"].id, name="عقد تجريبي", client_name="عميل",
        status="ACTIVE", start_date=date(2026, 1, 1),
    )
    env["db"].add(contract)
    env["db"].commit()
    env["db"].refresh(contract)
    project = Project(tenant_id=env["tenant"].id, name="مشروع", is_active=True)
    env["db"].add(project)
    env["db"].commit()
    env["db"].refresh(project)
    branch = ContractBranch(
        tenant_id=env["tenant"].id, contract_id=contract.id, project_id=project.id,
        city_id=city.id, city=text_city, branch_name="فرع", is_active=True,
    )
    env["db"].add(branch)
    env["db"].commit()
    env["db"].refresh(branch)
    return branch, project


def test_assigning_a_rider_to_a_branch_carries_the_reference(env):
    """Setting only the text is what re-created the divergence after every
    backfill: the rider ended up with the branch's spelling and no city_id."""
    rider = _rider(env, 1, "", city_id=None)
    branch, project = _branch(env, env["city"], "الرياض")

    res = env["client"].post(
        f"/hr/couriers/{rider.id}/transfer-project",
        json={"project_id": project.id},
        headers=env["H"],
    )
    assert res.status_code == 200, res.text

    env["db"].refresh(rider)
    assert rider.work_city == "الرياض"
    assert rider.city_id == env["city"].id, (
        "the rider got the branch's text and not its city reference"
    )


def test_a_branch_without_a_city_clears_the_riders_reference(env):
    """`branch.city_id or c.city_id` kept the *previous* city's reference while
    work_city moved to the new branch's text, so the rider read as Jeddah and
    filtered as Riyadh: absent from the report for where they work, present in
    the one for where they no longer do."""
    jeddah = find_or_create_city(env["db"], env["tenant"], "جدة")
    env["db"].commit()
    ensure_tenant_operating_city(env["db"], env["tenant"], jeddah)
    env["db"].commit()

    rider = _rider(env, 1, "الرياض")  # starts in Riyadh, with its reference
    assert rider.city_id == env["city"].id

    # A legacy branch in Jeddah, created before city normalization.
    branch, project = _branch(env, env["city"], "جدة")
    branch.city_id = None
    env["db"].commit()

    res = env["client"].post(
        f"/hr/couriers/{rider.id}/transfer-project",
        json={"project_id": project.id},
        headers=env["H"],
    )
    assert res.status_code == 200, res.text
    env["db"].refresh(rider)

    assert rider.work_city == "جدة"
    assert rider.city_id is None, (
        "the rider kept Riyadh's reference while working in Jeddah"
    )
    assert len(_report(env, zone="جدة")) == 1, "absent from where they work"
    assert _report(env, zone="الرياض") == [], "present in where they do not"
