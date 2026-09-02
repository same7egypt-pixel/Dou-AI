"""Settlement and the scorecard must count the same orders.

The platform pays each vendor for delivered orders, and the vendor sees the same
month on its own portal. Three views of one number, so any disagreement is a
dispute rather than a rounding difference.

Settlement previously counted rows in NormalizedDeliveryFact filtered to the
*operator's* tenant. That was wrong twice over: a read across a tenant boundary
with no grant behind it, and a table nothing populates, so every settlement
computed zero while the scorecard beside it showed real orders. It now reads the
platform's own data through the same helper the scorecard uses.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Country,
    Courier,
    CourierType,
    CustomerType,
    DailyLog,
    PlatformOperator,
    RiderAssignment,
    SourcePlatform,
    Tenant,
)
from app.services.entitlements import default_capabilities, serialize
from app.services.vendor_scorecard import (
    eligible_orders_for_operator,
    vendor_scorecard,
)

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


@pytest.fixture
def world(db):
    platform = make_tenant(db, "منصة", CustomerType.DELIVERY_PLATFORM.value)
    alpha = make_tenant(db, "ألفا", CustomerType.LOGISTICS_OPERATOR.value)
    beta = make_tenant(db, "بيتا", CustomerType.LOGISTICS_OPERATOR.value)
    source = SourcePlatform(tenant_id=platform.id, code="HS", name_ar="هنقر", is_active=True)
    db.add(source)
    db.commit()
    db.refresh(source)
    for vendor in (alpha, beta):
        db.add(
            PlatformOperator(
                tenant_id=platform.id,
                source_platform_id=source.id,
                operator_tenant_id=vendor.id,
                relationship_type="THREE_PL",
                is_active=True,
            )
        )
    db.commit()

    counter = 0
    for vendor, riders, per_rider in ((alpha, 2, 50), (beta, 1, 30)):
        for _ in range(riders):
            counter += 1
            rider = Courier(
                tenant_id=platform.id,
                name=f"{vendor.name} {counter}",
                phone=f"96654{counter:07d}",
                courier_type=CourierType.COMPANY,
                country=Country.SA,
            )
            db.add(rider)
            db.commit()
            db.refresh(rider)
            db.add(
                RiderAssignment(
                    tenant_id=platform.id,
                    courier_id=rider.id,
                    operator_id=vendor.id,
                    effective_from=TODAY - timedelta(days=20),
                    status="ACTIVE",
                )
            )
            db.add(
                DailyLog(
                    tenant_id=platform.id,
                    courier_id=rider.id,
                    log_date=TODAY,
                    orders_count=per_rider,
                )
            )
    db.commit()
    return {"platform": platform, "alpha": alpha, "beta": beta}


def test_settlement_counts_what_the_scorecard_shows(db, world):
    """The number the platform pays on and the number it reports must be one."""
    board = vendor_scorecard(db, world["platform"].id, month=MONTH)
    for row in board["rows"]:
        if row["operator_id"] is None:
            continue
        billable = eligible_orders_for_operator(
            db, world["platform"].id, row["operator_id"], MONTH
        )
        assert billable == row["orders_month"], (
            f"{row['operator_name']} would be paid for {billable} orders while "
            f"the scorecard reports {row['orders_month']}"
        )


def test_each_operator_is_counted_separately(db, world):
    assert eligible_orders_for_operator(db, world["platform"].id, world["alpha"].id, MONTH) == 100
    assert eligible_orders_for_operator(db, world["platform"].id, world["beta"].id, MONTH) == 30


def test_orders_are_read_from_the_platform_not_the_vendor_tenant(db, world):
    """A vendor's own operational data must not reach the platform's billing.

    The vendor logs orders in its own tenant for its own payroll. Those are a
    different population from what the platform delivered under its contract,
    and letting them into settlement would be a cross-tenant read as well as a
    wrong number.
    """
    rider = Courier(
        tenant_id=world["alpha"].id,
        name="مندوب داخلي",
        phone="966549999999",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)
    db.add(
        DailyLog(
            tenant_id=world["alpha"].id,
            courier_id=rider.id,
            log_date=TODAY,
            orders_count=9999,
        )
    )
    db.commit()

    assert eligible_orders_for_operator(db, world["platform"].id, world["alpha"].id, MONTH) == 100


def test_a_month_with_no_work_bills_nothing(db, world):
    past = (TODAY.replace(day=1) - timedelta(days=40)).strftime("%Y-%m")
    assert eligible_orders_for_operator(db, world["platform"].id, world["alpha"].id, past) == 0


def test_an_unlinked_operator_bills_nothing(db, world):
    stranger = make_tenant(db, "غريب", CustomerType.LOGISTICS_OPERATOR.value)
    assert eligible_orders_for_operator(db, world["platform"].id, stranger.id, MONTH) == 0


def test_settlement_no_longer_reads_the_normalized_fact_table():
    """Pin the fix: that table is empty and lives in the wrong tenant."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "routers" / "operators.py"
    ).read_text(encoding="utf-8")
    block = source[source.index("def calculate_operator_settlement(") :]
    block = block[: block.index("\n@router")]
    assert "NormalizedDeliveryFact" not in block, (
        "settlement is counting the operator's own tenant again"
    )
    assert "eligible_orders_for_operator" in block
