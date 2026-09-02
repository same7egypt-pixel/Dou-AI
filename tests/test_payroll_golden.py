"""Golden tests for the payroll engine.

Every case below is worked out by hand in its docstring. These are the tests that
have to fail loudly if anyone changes what a rider gets paid, so they assert
exact amounts rather than shapes, and they cover the paths that pay real money:
bonus plan resolution, TARGET_TIER vs FLAT_PER_ORDER pricing, accountant order
overrides, negative net with debt carry-forward, and finalized-month snapshots.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    BonusPlan,
    Contract,
    ContractBranch,
    Courier,
    CourierDebt,
    CourierType,
    Country,
    DailyLog,
    PayrollAdjustment,
    PayrollPeriod,
    Project,
    Tenant,
    User,
    UserRole,
)
from app.services.financial_calculations import (
    apply_debt_settlement,
    calculate_payroll_preview,
    calculate_payroll_previews,
    finalize_payroll_period,
    payroll_rows,
)

MONTH = "2026-05"
NEXT_MONTH = "2026-06"
IN_MONTH = date(2026, 5, 10)
IN_NEXT_MONTH = date(2026, 6, 10)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tenant(db):
    row = Tenant(name="Golden Logistics", country=Country.SA)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def actor(db, tenant):
    row = User(
        phone="966500000009",
        password_hash="x",
        role=UserRole.ACCOUNTANT,
        tenant_id=tenant.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_rider(db, tenant, *, base_salary=0.0, per_delivery_rate=0.0, name="Rider"):
    rider = Courier(
        tenant_id=tenant.id,
        name=name,
        phone=f"96650{db.query(Courier).count():07d}",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        base_salary=base_salary,
        per_delivery_rate=per_delivery_rate,
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)
    return rider


def log_orders(db, rider, count, when=IN_MONTH):
    db.add(
        DailyLog(courier_id=rider.id, log_date=when, orders_count=count)
    )
    db.commit()


def adjust(db, tenant, rider, kind, amount, month=MONTH):
    db.add(
        PayrollAdjustment(
            tenant_id=tenant.id,
            courier_id=rider.id,
            month=month,
            kind=kind,
            amount=amount,
            status="APPROVED",
        )
    )
    db.commit()


def preview(db, rider, month=MONTH):
    return calculate_payroll_previews(db, [rider], month)[0]


# ---------------------------------------------------------------- pricing


def test_target_tier_below_target_pays_below_rate_and_no_bonus(db, tenant):
    """80 orders against a 100 target.

    base 1000 + delivery 80x5=400 + bonus (below rate 2 x 80)=160 -> net 1560.
    """
    rider = make_rider(db, tenant, base_salary=1000, per_delivery_rate=5)
    db.add(
        BonusPlan(
            tenant_id=tenant.id,
            plan_type="TARGET_TIER",
            target_orders=100,
            bonus_amount=500,
            over_target_rate=3,
            below_target_rate=2,
            is_active=True,
            effective_from=date(2026, 1, 1),
        )
    )
    log_orders(db, rider, 80)

    row = preview(db, rider)

    assert row["bonus"]["achieved"] is False
    assert row["bonus"]["remaining_orders"] == 20
    assert row["delivery_pay"] == 400.0
    assert row["itemized_breakdown"]["target_bonus"] == 160.0
    assert row["gross_pay"] == 1560.0
    assert row["net_pay"] == 1560.0


def test_target_tier_above_target_pays_bonus_plus_over_rate(db, tenant):
    """120 orders against a 100 target.

    base 1000 + delivery 120x5=600 + bonus (500 + 20x3=60)=560 -> net 2160.
    """
    rider = make_rider(db, tenant, base_salary=1000, per_delivery_rate=5)
    db.add(
        BonusPlan(
            tenant_id=tenant.id,
            plan_type="TARGET_TIER",
            target_orders=100,
            bonus_amount=500,
            over_target_rate=3,
            below_target_rate=2,
            is_active=True,
            effective_from=date(2026, 1, 1),
        )
    )
    log_orders(db, rider, 120)

    row = preview(db, rider)

    assert row["bonus"]["achieved"] is True
    assert row["bonus"]["over_orders"] == 20
    assert row["delivery_pay"] == 600.0
    assert row["itemized_breakdown"]["target_bonus"] == 560.0
    assert row["net_pay"] == 2160.0


def test_flat_per_order_rate_replaces_profile_rate(db, tenant):
    """A FLAT_PER_ORDER plan prices the rider's orders; the profile rate is not added on top.

    base 2000 + 10 orders x plan rate 9 = 2090. The profile's own 6/order must not
    stack, or the same delivery would be paid twice.
    """
    rider = make_rider(db, tenant, base_salary=2000, per_delivery_rate=6)
    db.add(
        BonusPlan(
            tenant_id=tenant.id,
            plan_type="FLAT_PER_ORDER",
            flat_order_rate=9,
            is_active=True,
            effective_from=date(2026, 1, 1),
        )
    )
    log_orders(db, rider, 10)

    row = preview(db, rider)

    assert row["bonus"]["plan_type"] == "FLAT_PER_ORDER"
    assert row["delivery_pay"] == 90.0
    assert row["itemized_breakdown"]["target_bonus"] == 0.0
    assert row["gross_pay"] == 2090.0
    assert row["net_pay"] == 2090.0


def test_rider_without_plan_is_paid_from_profile_rate_only(db, tenant):
    """No bonus plan: base 800 + 30 orders x 7 = 1010."""
    rider = make_rider(db, tenant, base_salary=800, per_delivery_rate=7)
    log_orders(db, rider, 30)

    row = preview(db, rider)

    assert row["bonus"]["plan_type"] == "NONE"
    assert row["delivery_pay"] == 210.0
    assert row["net_pay"] == 1010.0


def test_rider_override_plan_wins_over_branch_plan(db, tenant):
    """Plan resolution order: an explicit rider plan beats the branch plan."""
    contract = Contract(tenant_id=tenant.id, name="HS", status="ACTIVE", scope_type="CONTRACT")
    db.add(contract)
    db.commit()
    db.refresh(contract)
    branch = ContractBranch(tenant_id=tenant.id, contract_id=contract.id, branch_name="Riyadh", city="Riyadh")
    db.add(branch)
    db.commit()
    db.refresh(branch)

    rider = make_rider(db, tenant, base_salary=0, per_delivery_rate=0)
    rider.contract_id = contract.id
    rider.contract_branch_id = branch.id
    db.commit()

    db.add(
        BonusPlan(
            tenant_id=tenant.id,
            contract_branch_id=branch.id,
            plan_type="FLAT_PER_ORDER",
            flat_order_rate=5,
            is_active=True,
            effective_from=date(2026, 1, 1),
        )
    )
    db.add(
        BonusPlan(
            tenant_id=tenant.id,
            courier_id=rider.id,
            plan_type="FLAT_PER_ORDER",
            flat_order_rate=11,
            is_active=True,
            effective_from=date(2026, 1, 1),
        )
    )
    log_orders(db, rider, 10)

    row = preview(db, rider)

    assert row["bonus"]["source"] == "rider_override"
    assert row["net_pay"] == 110.0


# ---------------------------------------------------------------- overrides


def test_accountant_order_override_drives_pay_not_driver_logged_orders(db, tenant, actor):
    """The rider logged 100 orders; the platform invoice approved 90.

    Pay follows the approved figure: base 1000 + 90 x 5 = 1450, and the row keeps
    the rider's own claim visible for the audit trail.
    """
    rider = make_rider(db, tenant, base_salary=1000, per_delivery_rate=5)
    log_orders(db, rider, 100)
    db.add(
        PayrollPeriod(
            tenant_id=tenant.id,
            month=MONTH,
            status="DRAFT",
            draft_overrides=f'{{"orders": {{"{rider.id}": 90}}}}',
        )
    )
    db.commit()

    rows, finalized = payroll_rows(db, tenant.id, MONTH)
    row = rows[0]

    assert finalized is False
    assert row["approved_orders"] == 90
    assert row["driver_orders"] == 100
    assert row["is_overridden"] is True
    assert row["net_pay"] == 1450.0


# ---------------------------------------------------------------- debt


def test_advances_beyond_earnings_pay_zero_and_carry_debt_forward(db, tenant, actor):
    """Earned 1000, took a 1500 advance.

    The rider is paid 0 rather than a negative amount, and the 500 shortfall is
    recorded as debt once the month is finalized.
    """
    rider = make_rider(db, tenant, base_salary=1000, per_delivery_rate=0)
    adjust(db, tenant, rider, "ADVANCE", 1500)

    row = preview(db, rider)
    assert row["gross_pay"] == 1000.0
    assert row["deductions"] == 1500.0
    assert row["net_before_debt"] == -500.0
    assert row["net_pay"] == 0.0
    assert row["debt_generated"] == 500.0
    assert row["is_in_debt"] is True

    # Preview must not write anything.
    assert db.query(CourierDebt).count() == 0

    finalize_payroll_period(db, tenant.id, MONTH, actor.id)
    debt = db.query(CourierDebt).one()
    assert (debt.origin_month, debt.amount, debt.remaining, debt.status) == (
        MONTH,
        500.0,
        500.0,
        "OPEN",
    )


def test_carried_debt_is_deducted_from_the_following_month(db, tenant, actor):
    """500 debt from May against 1200 earned in June -> paid 700, debt cleared."""
    rider = make_rider(db, tenant, base_salary=1000, per_delivery_rate=0)
    adjust(db, tenant, rider, "ADVANCE", 1500)
    finalize_payroll_period(db, tenant.id, MONTH, actor.id)

    rider.base_salary = 1200
    db.commit()
    log_orders(db, rider, 0, when=IN_NEXT_MONTH)

    row = preview(db, rider, NEXT_MONTH)
    assert row["carried_debt_total"] == 500.0
    assert row["carried_debt_applied"] == 500.0
    assert row["net_before_debt"] == 1200.0
    assert row["net_pay"] == 700.0
    assert row["debt_balance"] == 0.0
    assert row["is_in_debt"] is False

    finalize_payroll_period(db, tenant.id, NEXT_MONTH, actor.id)
    debt = db.query(CourierDebt).filter(CourierDebt.origin_month == MONTH).one()
    assert debt.status == "SETTLED"
    assert debt.remaining == 0.0
    assert debt.settled_month == NEXT_MONTH


def test_partial_debt_recovery_keeps_the_remainder_open(db, tenant, actor):
    """500 debt against only 200 earned next month -> paid 0, 300 still owed."""
    rider = make_rider(db, tenant, base_salary=1000, per_delivery_rate=0)
    adjust(db, tenant, rider, "ADVANCE", 1500)
    finalize_payroll_period(db, tenant.id, MONTH, actor.id)

    rider.base_salary = 200
    db.commit()

    row = preview(db, rider, NEXT_MONTH)
    assert row["carried_debt_applied"] == 200.0
    assert row["net_pay"] == 0.0
    assert row["debt_balance"] == 300.0

    finalize_payroll_period(db, tenant.id, NEXT_MONTH, actor.id)
    debt = db.query(CourierDebt).filter(CourierDebt.origin_month == MONTH).one()
    assert debt.status == "OPEN"
    assert debt.remaining == 300.0


def test_debt_settlement_arithmetic():
    """The split itself, independent of the database."""
    assert apply_debt_settlement(1200, 500)["net_pay"] == 700.0
    assert apply_debt_settlement(200, 500)["debt_balance"] == 300.0
    assert apply_debt_settlement(-500, 0)["debt_generated"] == 500.0
    # A negative month never consumes an existing debt.
    settled = apply_debt_settlement(-100, 400)
    assert settled["carried_debt_applied"] == 0.0
    assert settled["debt_balance"] == 500.0


# ---------------------------------------------------------------- one path


def test_single_rider_view_matches_the_payroll_sheet(db, tenant):
    """The rider profile and the payroll sheet must never disagree on net pay."""
    rider = make_rider(db, tenant, base_salary=2000, per_delivery_rate=6)
    db.add(
        BonusPlan(
            tenant_id=tenant.id,
            plan_type="FLAT_PER_ORDER",
            flat_order_rate=9,
            is_active=True,
            effective_from=date(2026, 1, 1),
        )
    )
    log_orders(db, rider, 10)

    single = calculate_payroll_preview(db, rider, MONTH)
    sheet, _ = payroll_rows(db, tenant.id, MONTH)

    assert single["net_pay"] == sheet[0]["net_pay"] == 2090.0


def test_finalized_month_is_read_from_the_snapshot_not_recomputed(db, tenant, actor):
    """After finalization, changing today's rates must not change what was paid."""
    rider = make_rider(db, tenant, base_salary=1000, per_delivery_rate=5)
    log_orders(db, rider, 10)
    finalize_payroll_period(db, tenant.id, MONTH, actor.id)

    rider.base_salary = 9999
    rider.per_delivery_rate = 99
    db.commit()

    single = calculate_payroll_preview(db, rider, MONTH)
    sheet, finalized = payroll_rows(db, tenant.id, MONTH)

    assert finalized is True
    assert single["net_pay"] == 1050.0
    assert sheet[0]["net_pay"] == 1050.0


def test_finalize_is_idempotent(db, tenant, actor):
    """Re-finalizing must not double-count debt or snapshots."""
    rider = make_rider(db, tenant, base_salary=1000, per_delivery_rate=0)
    adjust(db, tenant, rider, "ADVANCE", 1500)

    first = finalize_payroll_period(db, tenant.id, MONTH, actor.id)
    second = finalize_payroll_period(db, tenant.id, MONTH, actor.id)

    assert first["already_finalized"] is False
    assert second["already_finalized"] is True
    assert db.query(CourierDebt).count() == 1
    assert db.query(CourierDebt).one().remaining == 500.0


def test_tenant_scoping_rejects_a_mixed_batch(db, tenant):
    """A batch spanning two tenants is a programming error, not a silent merge."""
    other = Tenant(name="Other Co", country=Country.SA)
    db.add(other)
    db.commit()
    db.refresh(other)

    mine = make_rider(db, tenant, base_salary=100)
    theirs = make_rider(db, other, base_salary=100, name="Foreign")

    with pytest.raises(ValueError):
        calculate_payroll_previews(db, [mine, theirs], MONTH)
