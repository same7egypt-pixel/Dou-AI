"""Negative tests: one company's payroll must never reach another's.

The financial engine reads and writes several tables keyed by tenant_id
(couriers, adjustments, bonus plans, payroll periods, snapshots, and now
courier debts). Each test below sets up two companies with deliberately
identical-looking data and asserts the second one is invisible, so a dropped
tenant filter fails here rather than in a customer's payroll.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    BonusPlan,
    Country,
    Courier,
    CourierDebt,
    CourierType,
    DailyLog,
    PayrollAdjustment,
    PayrollPeriod,
    PayrollSnapshot,
    Tenant,
    User,
    UserRole,
)
from app.services.financial_calculations import (
    calculate_payroll_previews,
    courier_financial_rows,
    finalize_payroll_period,
    open_debts_for,
    payroll_rows,
)

MONTH = "2026-05"
IN_MONTH = date(2026, 5, 10)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def make_company(db, name, phone_seed):
    """A company with one rider, one bonus plan, orders, and an advance."""
    tenant = Tenant(name=name, country=Country.SA)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    actor = User(
        phone=f"9665{phone_seed}0000",
        password_hash="x",
        role=UserRole.ACCOUNTANT,
        tenant_id=tenant.id,
    )
    rider = Courier(
        tenant_id=tenant.id,
        name=f"{name} rider",
        phone=f"9665{phone_seed}1111",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        base_salary=1000,
        per_delivery_rate=5,
    )
    db.add_all([actor, rider])
    db.commit()
    db.refresh(actor)
    db.refresh(rider)

    db.add(
        BonusPlan(
            tenant_id=tenant.id,
            plan_type="TARGET_TIER",
            target_orders=50,
            bonus_amount=300,
            over_target_rate=2,
            is_active=True,
            effective_from=date(2026, 1, 1),
        )
    )
    db.add(DailyLog(courier_id=rider.id, log_date=IN_MONTH, orders_count=60))
    db.commit()
    return tenant, actor, rider


@pytest.fixture
def two_companies(db):
    a = make_company(db, "Company A", "1")
    b = make_company(db, "Company B", "2")
    return a, b


def test_payroll_sheet_only_returns_the_requesting_company(db, two_companies):
    (tenant_a, _, rider_a), (_, _, rider_b) = two_companies

    rows, _ = payroll_rows(db, tenant_a.id, MONTH)

    assert [row["courier_id"] for row in rows] == [rider_a.id]
    assert rider_b.id not in {row["courier_id"] for row in rows}


def test_rider_financial_report_only_returns_the_requesting_company(db, two_companies):
    (tenant_a, _, rider_a), (_, _, rider_b) = two_companies

    rows, _ = courier_financial_rows(db, tenant_a.id, MONTH)

    assert [row["courier_id"] for row in rows] == [rider_a.id]
    assert rider_b.id not in {row["courier_id"] for row in rows}


def test_another_companys_adjustments_do_not_reduce_this_companys_pay(
    db, two_companies
):
    """A deduction filed against company B must not touch company A's rider."""
    (tenant_a, _, rider_a), (tenant_b, _, rider_b) = two_companies
    db.add(
        PayrollAdjustment(
            tenant_id=tenant_b.id,
            courier_id=rider_b.id,
            month=MONTH,
            kind="ADVANCE",
            amount=5000,
            status="APPROVED",
        )
    )
    db.commit()

    row = calculate_payroll_previews(db, [rider_a], MONTH)[0]

    # base 1000 + 60 orders x 5 = 300 delivery + bonus (300 + 10 x 2) = 320
    assert row["deductions"] == 0.0
    assert row["net_pay"] == 1620.0


def test_finalizing_one_company_does_not_snapshot_or_bill_the_other(db, two_companies):
    (tenant_a, actor_a, rider_a), (tenant_b, _, rider_b) = two_companies

    finalize_payroll_period(db, tenant_a.id, MONTH, actor_a.id)

    snapshots = db.query(PayrollSnapshot).all()
    assert {row.courier_id for row in snapshots} == {rider_a.id}
    assert {row.tenant_id for row in snapshots} == {tenant_a.id}

    # Company B's own period is untouched and still unfinalized.
    assert (
        db.query(PayrollPeriod).filter(PayrollPeriod.tenant_id == tenant_b.id).count()
        == 0
    )
    rows_b, finalized_b = payroll_rows(db, tenant_b.id, MONTH)
    assert finalized_b is False
    assert [row["courier_id"] for row in rows_b] == [rider_b.id]


def test_debt_lookup_is_scoped_to_the_owning_company(db, two_companies):
    """Debt recorded for company B must not be deducted from company A."""
    (tenant_a, _, rider_a), (tenant_b, _, rider_b) = two_companies
    db.add(
        CourierDebt(
            tenant_id=tenant_b.id,
            courier_id=rider_b.id,
            origin_month="2026-04",
            amount=800,
            remaining=800,
            status="OPEN",
        )
    )
    db.commit()

    assert open_debts_for(db, tenant_a.id, [rider_a.id, rider_b.id], MONTH) == {}

    row = calculate_payroll_previews(db, [rider_a], MONTH)[0]
    assert row["carried_debt_total"] == 0.0
    assert row["net_pay"] == 1620.0


def test_a_batch_mixing_two_companies_is_rejected(db, two_companies):
    (_, _, rider_a), (_, _, rider_b) = two_companies

    with pytest.raises(ValueError):
        calculate_payroll_previews(db, [rider_a, rider_b], MONTH)
