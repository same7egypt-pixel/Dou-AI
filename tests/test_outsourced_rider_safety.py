"""A rider the tenant does not pay must not break the screens that read payroll.

The hybrid-employment change excluded OUTSOURCED_3PL riders from payroll, which
is right, but did it by raising ValueError from `calculate_payroll_preview` —
a function four call sites use without catching anything, two of them inside a
loop over a whole fleet. Measured before this fix: the rider profile answered
500 for any outsourced rider, and one outsourced rider took both report
endpoints down with it, not just its own row.

It also filtered in SQL with `employment_model != 'OUTSOURCED_3PL'`. In SQL a
NULL column makes that predicate NULL, and a NULL predicate is not true, so
every rider whose model was never set vanished from the payroll sheet in
silence. The migration created the column nullable while the model declares it
NOT NULL, so production can hold NULLs that the test database cannot — verified
on the production schema: `is_nullable = YES`.

A rider missing from payroll must never be the result of an unset flag.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.entities import (
    Country,
    Courier,
    CourierType,
    CustomerType,
    Tenant,
    User,
    UserRole,
)
from app.routers.auth import create_token, hash_password
from app.services import entitlements
from app.services.financial_calculations import (
    calculate_payroll_preview,
    calculate_payroll_previews,
    payroll_rows,
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

    def rider(name, phone, model="DIRECT_HIRE"):
        c = Courier(
            tenant_id=tenant.id, name=name, phone=phone,
            courier_type=CourierType.COMPANY, country=Country.SA,
            employment_status="ACTIVE", employment_model=model, base_salary=3000.0,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return c

    app.dependency_overrides[get_db] = lambda: db
    yield {
        "db": db, "tenant": tenant, "rider": rider,
        "client": TestClient(app, raise_server_exceptions=False),
        "H": {"Authorization": f"Bearer {create_token(user)}"},
    }
    app.dependency_overrides.clear()
    db.close()


def _allow_null_employment_model(db):
    """Reproduce the production schema, where the column is nullable."""
    db.execute(text("ALTER TABLE couriers RENAME TO couriers_old"))
    ddl = db.execute(
        text("SELECT sql FROM sqlite_master WHERE name='couriers_old'")
    ).scalar()
    db.execute(text(
        ddl.replace("couriers_old", "couriers")
        .replace("employment_model VARCHAR(30) NOT NULL", "employment_model VARCHAR(30)")
    ))
    db.execute(text("INSERT INTO couriers SELECT * FROM couriers_old"))
    db.execute(text("DROP TABLE couriers_old"))
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# An outsourced rider does not take a screen down
# ─────────────────────────────────────────────────────────────────────────────


def test_the_profile_of_an_outsourced_rider_still_opens(env):
    """Measured before the fix: 500."""
    direct = env["rider"]("مندوب مباشر", "966599000001")
    outsourced = env["rider"]("مندوب خارجي", "966599000002", "OUTSOURCED_3PL")

    assert env["client"].get(
        f"/fleet/couriers/{direct.id}", headers=env["H"]
    ).status_code == 200
    res = env["client"].get(f"/fleet/couriers/{outsourced.id}", headers=env["H"])
    assert res.status_code == 200, (
        "the rider the new feature creates is the rider whose profile it breaks"
    )


def test_the_zeroed_row_has_the_full_shape_at_every_depth(env):
    """A hand-built row missed `bonus["earned"]` and turned the 500 into a
    KeyError, which is why the row is computed and then zeroed instead."""
    direct = env["rider"]("مندوب مباشر", "966599000001")
    outsourced = env["rider"]("مندوب خارجي", "966599000002", "OUTSOURCED_3PL")

    real = calculate_payroll_preview(env["db"], direct, "2026-09")
    zeroed = calculate_payroll_preview(env["db"], outsourced, "2026-09")

    missing = set(real) - set(zeroed)
    assert not missing, f"the zeroed row is missing keys a caller may read: {missing}"
    assert set(real["bonus"]) <= set(zeroed["bonus"]), (
        "the shape has to match at every depth, not only at the top level"
    )
    assert zeroed["net_pay"] == 0
    assert zeroed["gross_pay"] == 0
    assert zeroed["compensation_source"] == "OUTSOURCED_3PL"


def test_an_outsourced_rider_is_still_never_paid(env):
    """The point of the exclusion must survive the fix."""
    env["rider"]("مندوب مباشر", "966599000001")
    env["rider"]("مندوب خارجي", "966599000002", "OUTSOURCED_3PL")

    rows, _ = payroll_rows(env["db"], env["tenant"].id, "2026-09")
    names = {r["courier_id"] for r in rows}
    outsourced = env["db"].query(Courier).filter(
        Courier.employment_model == "OUTSOURCED_3PL"
    ).one()
    assert outsourced.id not in names, "an outsourced rider reached the payroll sheet"
    assert len(rows) == 1


def test_one_outsourced_rider_does_not_take_the_whole_batch_down(env):
    """Two call sites loop over a fleet; a raise there loses everyone's row."""
    direct = env["rider"]("مندوب مباشر", "966599000001")
    outsourced = env["rider"]("مندوب خارجي", "966599000002", "OUTSOURCED_3PL")

    rows = calculate_payroll_previews(env["db"], [direct, outsourced], "2026-09")
    assert [r["courier_id"] for r in rows] == [direct.id]


# ─────────────────────────────────────────────────────────────────────────────
# An unset flag never removes a rider from payroll
# ─────────────────────────────────────────────────────────────────────────────


def test_a_rider_with_no_employment_model_is_still_paid(env):
    """`col != 'X'` is NULL for a NULL column, and a NULL predicate is not true."""
    direct = env["rider"]("مندوب مباشر", "966599000001")
    _allow_null_employment_model(env["db"])
    env["db"].execute(text(
        "INSERT INTO couriers (tenant_id,name,phone,courier_type,country,"
        "employment_status,employment_model,base_salary) VALUES "
        "(:t,'مندوب بلا تصنيف','966599000003','COMPANY','SA','ACTIVE',NULL,3000.0)"
    ), {"t": env["tenant"].id})
    env["db"].commit()
    unset_id = env["db"].execute(
        text("SELECT id FROM couriers WHERE phone='966599000003'")
    ).scalar()

    rows, _ = payroll_rows(env["db"], env["tenant"].id, "2026-09")
    paid = {r["courier_id"] for r in rows}
    assert direct.id in paid
    assert unset_id in paid, (
        "a rider vanished from payroll because a flag was never set — silently, "
        "with no error anywhere"
    )


def test_python_and_sql_agree_about_an_unset_flag(env):
    """They disagreed: the Python filter's default kept NULL, SQL dropped it."""
    _allow_null_employment_model(env["db"])
    env["db"].execute(text(
        "INSERT INTO couriers (tenant_id,name,phone,courier_type,country,"
        "employment_status,employment_model,base_salary) VALUES "
        "(:t,'مندوب بلا تصنيف','966599000004','COMPANY','SA','ACTIVE',NULL,3000.0)"
    ), {"t": env["tenant"].id})
    env["db"].commit()
    unset = env["db"].query(Courier).filter(Courier.phone == "966599000004").one()

    via_python = calculate_payroll_previews(env["db"], [unset], "2026-09")
    rows, _ = payroll_rows(env["db"], env["tenant"].id, "2026-09")
    via_sql = {r["courier_id"] for r in rows}

    assert bool(via_python) is (unset.id in via_sql), (
        "the two filters disagree about a NULL, so which one runs decides "
        "whether this rider is paid"
    )
