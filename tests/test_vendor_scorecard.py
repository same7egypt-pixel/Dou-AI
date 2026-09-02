"""Vendor scorecard and compliance wall: the two screens a platform buys.

The platform product answers questions a logistics product cannot: which vendor
supplies riders who show up, and which vendor is about to put a rider with a
lapsed residency permit on the road. Both are computed from the platform's own
tenant, grouped by operator.

The access rule matters as much as the numbers. These screens are refused to a
logistics account in the API, not merely hidden from its menu.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Attendance,
    Country,
    Courier,
    CourierType,
    CustomerType,
    DailyLog,
    PlatformOperator,
    SourcePlatform,
    RiderAssignment,
    Tenant,
    User,
    UserRole,
)
from app.routers.reports import vendors_compliance, vendors_scorecard
from app.services.entitlements import default_capabilities, serialize
from app.services.vendor_scorecard import compliance_wall, horizon_from, vendor_scorecard

TODAY = date.today()
MONTH = TODAY.strftime("%Y-%m")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def make_tenant(db, name, customer_type):
    tenant = Tenant(
        name=name,
        country=Country.SA,
        customer_type=customer_type,
        capabilities=serialize(default_capabilities(customer_type)),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def make_rider(db, tenant, name, phone, **fields):
    rider = Courier(
        tenant_id=tenant.id,
        name=name,
        phone=phone,
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        **fields,
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)
    return rider


@pytest.fixture
def platform(db):
    """A platform with two vendors: one clean, one with a lapsed permit."""
    plat = make_tenant(db, "منصة", CustomerType.DELIVERY_PLATFORM.value)
    good = make_tenant(db, "مورّد ملتزم", CustomerType.LOGISTICS_OPERATOR.value)
    bad = make_tenant(db, "مورّد متأخر", CustomerType.LOGISTICS_OPERATOR.value)
    source = SourcePlatform(
        tenant_id=plat.id, code="HS", name_ar="هنقرستيشن", is_active=True
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    for vendor in (good, bad):
        db.add(
            PlatformOperator(
                tenant_id=plat.id,
                source_platform_id=source.id,
                operator_tenant_id=vendor.id,
                relationship_type="THREE_PL",
                is_active=True,
            )
        )
    db.commit()

    clean = make_rider(
        db, plat, "سالم", "966550000001",
        bonus_target=100, iqama_expiry=TODAY + timedelta(days=200),
    )
    lapsed = make_rider(
        db, plat, "ماجد", "966550000002",
        bonus_target=100, iqama_expiry=TODAY - timedelta(days=3),
    )
    soon = make_rider(
        db, plat, "فهد", "966550000003",
        bonus_target=100, license_expiry=TODAY + timedelta(days=10),
    )
    for rider, vendor in ((clean, good), (lapsed, bad), (soon, bad)):
        db.add(
            RiderAssignment(
                tenant_id=plat.id,
                courier_id=rider.id,
                operator_id=vendor.id,
                effective_from=TODAY - timedelta(days=30),
                status="ACTIVE",
            )
        )
    db.add(DailyLog(tenant_id=plat.id, courier_id=clean.id, log_date=TODAY, orders_count=80))
    db.add(Attendance(courier_id=clean.id, check_in=datetime.now()))
    db.commit()
    return {"platform": plat, "good": good, "bad": bad}


# ---------------------------------------------------------------- scorecard


def test_riders_are_grouped_under_their_vendor(db, platform):
    result = vendor_scorecard(db, platform["platform"].id, month=MONTH)
    by_name = {row["operator_name"]: row for row in result["rows"]}

    assert by_name["مورّد ملتزم"]["riders"] == 1
    assert by_name["مورّد متأخر"]["riders"] == 2
    assert result["vendors"] == 2


def test_compliance_counts_separate_lapsed_from_lapsing(db, platform):
    rows = {r["operator_name"]: r for r in vendor_scorecard(db, platform["platform"].id)["rows"]}

    late = rows["مورّد متأخر"]
    assert late["riders_expired"] == 1, "a permit that expired three days ago"
    assert late["riders_expiring"] == 1, "a licence expiring in ten days"
    assert late["compliance_rate"] == 0.0

    assert rows["مورّد ملتزم"]["compliance_rate"] == 100.0


def test_the_worst_vendor_is_listed_first(db, platform):
    """Sorted by risk, not by size: the row that can stop riders working leads."""
    rows = vendor_scorecard(db, platform["platform"].id)["rows"]
    assert rows[0]["operator_name"] == "مورّد متأخر"
    assert rows[0]["rank"] == 1


def test_attendance_and_orders_are_attributed_to_the_vendor(db, platform):
    rows = {r["operator_name"]: r for r in vendor_scorecard(db, platform["platform"].id, month=MONTH)["rows"]}
    good = rows["مورّد ملتزم"]
    assert good["present_today"] == 1
    assert good["attendance_rate"] == 100.0
    assert good["orders_month"] == 80
    assert good["target_achievement"] == 80.0


def test_a_rider_with_no_vendor_is_shown_rather_than_dropped(db, platform):
    """An unassigned rider is the platform's problem to notice, not to hide."""
    make_rider(db, platform["platform"], "بلا مورّد", "966550000009")
    rows = vendor_scorecard(db, platform["platform"].id)["rows"]
    orphan = [r for r in rows if r["operator_id"] is None]
    assert orphan and orphan[0]["riders"] == 1
    assert orphan[0]["is_linked"] is False


# ---------------------------------------------------------------- compliance wall


def test_the_wall_lists_soonest_expiry_first(db, platform):
    wall = compliance_wall(db, platform["platform"].id)
    days = [row["days_remaining"] for row in wall["rows"]]
    assert days == sorted(days)
    assert wall["rows"][0]["severity"] == "EXPIRED"


def test_each_lapse_names_the_vendor_responsible_for_fixing_it(db, platform):
    wall = compliance_wall(db, platform["platform"].id)
    assert all(row["operator_name"] for row in wall["rows"])
    assert wall["totals"]["expired"] == 1
    assert wall["totals"]["expiring"] == 1
    assert wall["totals"]["riders_affected"] == 2


def test_a_distant_expiry_is_not_raised_as_a_problem(db, platform):
    wall = compliance_wall(db, platform["platform"].id, horizon=30)
    assert "سالم" not in [row["rider_name"] for row in wall["rows"]]


def test_widening_the_horizon_surfaces_more(db, platform):
    near = compliance_wall(db, platform["platform"].id, horizon=5)
    far = compliance_wall(db, platform["platform"].id, horizon=365)
    assert len(far["rows"]) > len(near["rows"])


def test_the_horizon_is_clamped_to_something_serveable():
    assert horizon_from(None) == 30
    assert horizon_from("nonsense") == 30
    assert horizon_from(0) == 1
    assert horizon_from(99999) == 180


# ---------------------------------------------------------------- access


def test_a_logistics_account_is_refused_by_the_api(db, platform):
    """Not merely hidden from the menu. Hiding a screen is presentation."""
    vendor = platform["good"]
    owner = User(
        phone="966599999991",
        password_hash="x",
        role=UserRole.COMPANY_ADMIN,
        tenant_id=vendor.id,
    )
    db.add(owner)
    db.commit()

    for endpoint in (vendors_scorecard, vendors_compliance):
        with pytest.raises(HTTPException) as raised:
            endpoint(user=owner, db=db)
        assert raised.value.status_code == 403


def test_a_platform_account_is_allowed(db, platform):
    owner = User(
        phone="966599999992",
        password_hash="x",
        role=UserRole.COMPANY_ADMIN,
        tenant_id=platform["platform"].id,
    )
    db.add(owner)
    db.commit()

    assert vendors_scorecard(user=owner, db=db)["vendors"] == 2
    assert vendors_compliance(user=owner, db=db)["totals"]["expired"] == 1


def test_one_platform_never_sees_another_platforms_vendors(db, platform):
    other = make_tenant(db, "منصة أخرى", CustomerType.DELIVERY_PLATFORM.value)
    make_rider(db, other, "مندوب غريب", "966550000099")

    rows = vendor_scorecard(db, platform["platform"].id)["rows"]
    assert "مندوب غريب" not in str(rows)
    assert sum(r["riders"] for r in rows) == 3
