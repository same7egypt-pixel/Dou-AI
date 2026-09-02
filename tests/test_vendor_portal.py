"""The vendor portal: a vendor reads its own slice of a platform's account.

Nothing is copied. The platform's rider data stays in the platform's tenant and
the vendor is granted read access to the rows describing its own riders, so
revoking is instant and leaves nothing behind.

Three properties matter more than the numbers, and each is tested from the
attacker's side rather than the happy path:

  * a vendor with no grant sees nothing
  * a vendor never sees another vendor's rows, name, or identity
  * ranking tells a vendor where it stands without naming a peer
"""

from datetime import date, datetime, timedelta

import pytest
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
    DelegatedScope,
    PlatformOperator,
    RiderAssignment,
    SourcePlatform,
    Tenant,
)
from app.services.entitlements import VENDOR_PORTAL, default_capabilities, serialize
from app.services.vendor_portal import (
    grants_for_vendor,
    vendor_compliance,
    vendor_standing,
)

TODAY = date.today()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def make_tenant(db, name, customer_type, extra_caps=()):
    caps = default_capabilities(customer_type) + list(extra_caps)
    tenant = Tenant(
        name=name,
        country=Country.SA,
        customer_type=customer_type,
        capabilities=serialize(caps),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def world(db):
    """A platform with the portal paid for, and two vendors under it."""
    platform = make_tenant(
        db, "منصة", CustomerType.DELIVERY_PLATFORM.value, [VENDOR_PORTAL]
    )
    alpha = make_tenant(db, "مورّد ألفا", CustomerType.LOGISTICS_OPERATOR.value)
    beta = make_tenant(db, "مورّد بيتا", CustomerType.LOGISTICS_OPERATOR.value)

    source = SourcePlatform(tenant_id=platform.id, code="HS", name_ar="هنقر", is_active=True)
    db.add(source)
    db.commit()
    db.refresh(source)

    links = {}
    for vendor in (alpha, beta):
        link = PlatformOperator(
            tenant_id=platform.id,
            source_platform_id=source.id,
            operator_tenant_id=vendor.id,
            relationship_type="THREE_PL",
            is_active=True,
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        links[vendor.id] = link

    # alpha: 2 clean riders, plenty of orders. beta: 1 rider with a lapsed permit.
    plan = [(alpha, 2, 120, False), (beta, 1, 20, True)]
    counter = 0
    for vendor, count, orders, lapsed in plan:
        for index in range(count):
            counter += 1
            fields = (
                {"iqama_expiry": TODAY - timedelta(days=4)}
                if lapsed
                else {"iqama_expiry": TODAY + timedelta(days=300)}
            )
            rider = Courier(
                tenant_id=platform.id,
                name=f"{vendor.name} مندوب {index + 1}",
                phone=f"96653{counter:07d}",
                courier_type=CourierType.COMPANY,
                country=Country.SA,
                bonus_target=100,
                **fields,
            )
            db.add(rider)
            db.commit()
            db.refresh(rider)
            db.add(
                RiderAssignment(
                    tenant_id=platform.id,
                    courier_id=rider.id,
                    operator_id=vendor.id,
                    effective_from=TODAY - timedelta(days=30),
                    status="ACTIVE",
                )
            )
            db.add(
                DailyLog(
                    tenant_id=platform.id,
                    courier_id=rider.id,
                    log_date=TODAY,
                    orders_count=orders // count,
                )
            )
            db.add(Attendance(courier_id=rider.id, check_in=datetime.now()))
    db.commit()
    return {"platform": platform, "alpha": alpha, "beta": beta, "links": links}


def grant(db, world, vendor, valid_from=None, valid_to=None):
    db.add(
        DelegatedScope(
            tenant_id=world["platform"].id,
            platform_operator_id=world["links"][vendor.id].id,
            scope_type="OPERATOR",
            scope_id=vendor.id,
            permissions='["READ_OWN_SLICE", "READ_OWN_RANKING"]',
            valid_from=valid_from or TODAY,
            valid_to=valid_to,
        )
    )
    db.commit()


# ---------------------------------------------------------------- the grant gates it


def test_without_a_grant_a_vendor_sees_nothing(db, world):
    result = vendor_standing(db, world["alpha"].id)
    assert result["granted"] is False
    assert result["standing"] is None


def test_a_grant_opens_the_view(db, world):
    grant(db, world, world["alpha"])
    result = vendor_standing(db, world["alpha"].id)
    assert result["granted"] is True
    assert result["standing"]["riders"] == 2


def test_an_expired_grant_closes_it_again(db, world):
    grant(db, world, world["alpha"], valid_to=TODAY - timedelta(days=1))
    assert vendor_standing(db, world["alpha"].id)["granted"] is False


def test_a_future_grant_is_not_yet_active(db, world):
    grant(db, world, world["alpha"], valid_from=TODAY + timedelta(days=5))
    assert grants_for_vendor(db, world["alpha"].id) == []


def test_the_platform_must_still_be_paying_for_the_portal(db, world):
    """Withdrawing the capability closes every vendor's view at once, without
    touching a single grant row or any data."""
    grant(db, world, world["alpha"])
    assert vendor_standing(db, world["alpha"].id)["granted"] is True

    platform = world["platform"]
    platform.capabilities = serialize(
        [c for c in default_capabilities(CustomerType.DELIVERY_PLATFORM.value)]
    )
    db.commit()

    assert vendor_standing(db, world["alpha"].id)["granted"] is False


def test_deactivating_the_operator_link_closes_the_view(db, world):
    grant(db, world, world["alpha"])
    world["links"][world["alpha"].id].is_active = False
    db.commit()
    assert vendor_standing(db, world["alpha"].id)["granted"] is False


# ---------------------------------------------------------------- one slice only


def test_a_vendor_sees_only_its_own_riders(db, world):
    grant(db, world, world["alpha"])
    grant(db, world, world["beta"])

    alpha = vendor_standing(db, world["alpha"].id)["standing"]
    beta = vendor_standing(db, world["beta"].id)["standing"]

    assert alpha["riders"] == 2
    assert beta["riders"] == 1
    assert alpha["orders_month"] == 120
    assert beta["orders_month"] == 20


def test_a_vendors_compliance_never_includes_another_vendors_rider(db, world):
    grant(db, world, world["alpha"])
    grant(db, world, world["beta"])

    alpha = vendor_compliance(db, world["alpha"].id, horizon=365)
    beta = vendor_compliance(db, world["beta"].id, horizon=365)

    assert alpha["totals"]["expired"] == 0
    assert beta["totals"]["expired"] == 1
    assert all("بيتا" not in row["rider_name"] for row in alpha["rows"])


def test_a_grant_from_one_platform_does_not_open_another(db, world):
    """A second platform with its own riders stays invisible."""
    other = make_tenant(
        db, "منصة أخرى", CustomerType.DELIVERY_PLATFORM.value, [VENDOR_PORTAL]
    )
    db.add(
        Courier(
            tenant_id=other.id,
            name="مندوب منصة أخرى",
            phone="966539999999",
            courier_type=CourierType.COMPANY,
            country=Country.SA,
        )
    )
    db.commit()
    grant(db, world, world["alpha"])

    result = vendor_standing(db, world["alpha"].id)
    assert result["platform_tenant_id"] == world["platform"].id
    assert "منصة أخرى" not in str(result)


# ---------------------------------------------------------------- anonymous ranking


def test_ranking_places_the_vendor_without_naming_a_peer(db, world):
    grant(db, world, world["alpha"])
    standing = vendor_standing(db, world["alpha"].id)["standing"]

    assert standing["of"] == 2
    assert standing["rank"] in (1, 2)
    assert "بيتا" not in str(standing), "a peer's name crossed the boundary"


def test_peer_statistics_carry_values_but_no_identities(db, world):
    grant(db, world, world["beta"])
    peers = vendor_standing(db, world["beta"].id)["standing"]["peers"]

    assert peers["attendance"]["best"] is not None
    assert peers["compliance"]["median"] is not None
    assert "operator_id" not in str(peers)
    assert "ألفا" not in str(peers)


def test_the_vendor_and_the_platform_read_the_same_numbers(db, world):
    """Two different figures for the same month would defeat the portal."""
    from app.services.vendor_scorecard import vendor_scorecard

    grant(db, world, world["alpha"])
    mine = vendor_standing(db, world["alpha"].id)["standing"]
    board = vendor_scorecard(db, world["platform"].id)
    theirs = next(r for r in board["rows"] if r["operator_id"] == world["alpha"].id)

    for field in ("riders", "orders_month", "attendance_rate", "compliance_rate"):
        assert mine[field] == theirs[field]
