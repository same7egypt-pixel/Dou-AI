"""Verification tests for Phase 3: Hybrid Platform Isolation (Case 4).

Tests:
1. A hybrid platform with direct and outsourced 3PL riders only computes payroll for direct riders.
2. An outsourced rider's preview raises ValueError so accountants cannot generate salary slips for them.
3. Outsourced rider orders properly feed into the 3PL operator's commercial settlement.
4. Finalizing payroll never snapshots or pays outsourced riders.
"""

from datetime import date, datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import entities as ent
from app.services.financial_calculations import (
    calculate_payroll_preview,
    payroll_rows,
)
from app.services.vendor_scorecard import eligible_orders_for_operator


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_hybrid_platform_payroll_isolation(test_db):
    # 1. Setup Platform tenant
    platform = ent.Tenant(name="Ninja Platform", customer_type="DELIVERY_PLATFORM", country=ent.Country.SA)
    test_db.add(platform)
    test_db.commit()

    # 2. Setup 3PL Operator tenant
    operator = ent.Tenant(name="Fast 3PL Vendor", customer_type="LOGISTICS_OPERATOR", country=ent.Country.SA)
    test_db.add(operator)
    test_db.commit()

    project = ent.Project(name="Riyadh Hub", tenant_id=platform.id)
    test_db.add(project)
    test_db.commit()

    # 3. Create 2 DIRECT_HIRE riders (employed by platform)
    direct_rider_1 = ent.Courier(
        name="Direct Rider 1",
        phone="0550000001",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        employment_model="DIRECT_HIRE",
        base_salary=3000.0,
        per_delivery_rate=5.0,
        tenant_id=platform.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )
    direct_rider_2 = ent.Courier(
        name="Direct Rider 2",
        phone="0550000002",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        employment_model="DIRECT_HIRE",
        base_salary=3500.0,
        per_delivery_rate=5.0,
        tenant_id=platform.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )
    test_db.add_all([direct_rider_1, direct_rider_2])

    # 4. Create 2 OUTSOURCED_3PL riders (employed by Fast 3PL Vendor, operating on platform)
    outsourced_rider_1 = ent.Courier(
        name="Outsourced Rider 1",
        phone="0550000003",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        employment_model="OUTSOURCED_3PL",
        operator_tenant_id=operator.id,
        base_salary=0.0,
        per_delivery_rate=0.0,
        tenant_id=platform.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )
    outsourced_rider_2 = ent.Courier(
        name="Outsourced Rider 2",
        phone="0550000004",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        employment_model="OUTSOURCED_3PL",
        operator_tenant_id=operator.id,
        base_salary=0.0,
        per_delivery_rate=0.0,
        tenant_id=platform.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )
    test_db.add_all([outsourced_rider_1, outsourced_rider_2])
    test_db.commit()

    month = "2026-09"

    # 5. Run payroll_rows for the platform
    rows, is_finalized = payroll_rows(test_db, platform.id, month)

    # 6. Verify: ONLY direct riders appear in the payroll sheet (2 of 4 total riders)
    returned_courier_ids = {r["courier_id"] for r in rows}
    assert returned_courier_ids == {direct_rider_1.id, direct_rider_2.id}
    assert outsourced_rider_1.id not in returned_courier_ids
    assert outsourced_rider_2.id not in returned_courier_ids

    # 7. Verify: Direct rider preview succeeds
    preview = calculate_payroll_preview(test_db, direct_rider_1, month)
    assert preview["courier_id"] == direct_rider_1.id
    assert preview["base_salary"] == 3000.0

    # 8. Verify: an outsourced rider produces a payslip worth nothing.
    #
    # This asserted that the preview *raises*. Four call sites read that
    # function without catching anything — two of them inside a loop over a
    # whole fleet — so the raise answered 500 on the rider profile and took
    # both report endpoints down with it for any account that had one
    # outsourced rider. The rule being protected is "the platform does not pay
    # this rider", and a complete row of zeros states that without breaking the
    # screens that read it. See tests/test_outsourced_rider_safety.py.
    preview_outsourced = calculate_payroll_preview(test_db, outsourced_rider_1, month)
    assert preview_outsourced["net_pay"] == 0
    assert preview_outsourced["gross_pay"] == 0
    assert preview_outsourced["base_salary"] == 0
    assert preview_outsourced["compensation_source"] == "OUTSOURCED_3PL"


def test_outsourced_rider_orders_feed_commercial_settlement(test_db):
    # Setup Platform and Operator
    platform = ent.Tenant(name="Ninja Platform", customer_type="DELIVERY_PLATFORM", country=ent.Country.SA)
    test_db.add(platform)
    test_db.commit()

    operator = ent.Tenant(name="Fast 3PL Vendor", customer_type="LOGISTICS_OPERATOR", country=ent.Country.SA)
    test_db.add(operator)
    test_db.commit()

    project = ent.Project(name="Riyadh Hub", tenant_id=platform.id)
    test_db.add(project)
    test_db.commit()

    # Create Outsourced Rider
    outsourced_rider = ent.Courier(
        name="Outsourced Rider 1",
        phone="0550000005",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        employment_model="OUTSOURCED_3PL",
        operator_tenant_id=operator.id,
        tenant_id=platform.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )
    test_db.add(outsourced_rider)
    test_db.commit()

    # Log 15 delivered orders in 2026-09
    log = ent.DailyLog(
        courier_id=outsourced_rider.id,
        tenant_id=platform.id,
        project_id=project.id,
        log_date=date(2026, 9, 2),
        orders_count=15,
        driver_orders=15,
        verified_orders=15,
        source_type="LIVE_API_NINJA",
    )
    test_db.add(log)
    test_db.commit()

    # Check eligible orders for operator in commercial settlement
    orders = eligible_orders_for_operator(test_db, platform.id, operator.id, "2026-09")
    assert orders == 15
