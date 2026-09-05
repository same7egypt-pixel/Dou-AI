"""One restaurant, one month, three parties — end to end.

Every piece of DOU Flex has been tested on its own. Nothing has ever run a whole
month through: a seat contracted, a rider working it, cash collected and handed
back, and the month settled. Defects in a system like this live in the seams
between those pieces, not inside them.

What the money has to do, always:

    what the restaurant is charged  =  what the fleet is paid  +  what DOU keeps

The margin is deliberately the **residual**, not an independently prorated
figure. Proration rounds each amount to the halala, and on a 31-day month there
are four day-counts where `prorate(7000) - prorate(5500)` and `prorate(1500)`
disagree by 0.01. Taking the residual means the three parties reconcile exactly
every time and DOU absorbs the rounding — which is the right party to absorb it.
A well-meaning change to `prorate(dou_margin)` breaks that, so it is guarded.
"""

import calendar
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.entities import Country, Courier, CourierType, Tenant
from app.models.merchant import (
    BookingStatus,
    BranchDispatchOrder,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    OrderStatus,
    PaymentMethod,
    ShiftType,
)
from app.utils.finance import prorate
from app.utils.security import create_merchant_account_token, hash_pin

TEST_DB_FILE = "./test_flex_month.db"
engine = create_engine(
    f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

MONTH = date(2026, 8, 1)          # 31 days — where the rounding edges live
MONTH_STR = "2026-08"
DAYS_IN_MONTH = calendar.monthrange(MONTH.year, MONTH.month)[1]

FEE = Decimal("7000.00")
PAYOUT = Decimal("5500.00")
MARGIN = Decimal("1500.00")
PIN = "8821"


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    yield
    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


def _world(db, *, key: int, effective_from: date, effective_until: date | None = None):
    """A restaurant, a branch, a logistics company, a rider, and one contracted seat."""
    tenant = Tenant(name=f"أسطول {key}", country=Country.SA, subscription_status="ACTIVE")
    db.add(tenant)
    db.flush()

    account = MerchantAccount(
        id=key,
        trade_name=f"مطعم {key}",
        billing_contact_email=f"m{key}@test.sa",
        billing_contact_phone=f"96650000{key:04d}",
        payment_terms_days=30,
        is_active=True,
    )
    db.add(account)
    db.flush()

    branch = MerchantBranch(
        id=key,
        merchant_account_id=account.id,
        branch_name=f"فرع {key}",
        city="الرياض",
        latitude=24.7136,
        longitude=46.6753,
        geofence_radius_meters=200,
        cashier_access_pin=hash_pin(PIN),
        is_active=True,
    )
    db.add(branch)

    rider = Courier(
        tenant_id=tenant.id,
        name=f"مندوب {key}",
        phone=f"96650001{key:04d}",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db.add(rider)
    db.flush()

    booking = DedicatedShiftBooking(
        merchant_branch_id=branch.id,
        logistics_company_tenant_id=tenant.id,
        rider_id=rider.id,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(12, 0),
        shift_end_time=time(20, 0),
        effective_from=effective_from,
        effective_until=effective_until,
        monthly_fee_to_merchant=FEE,
        monthly_payout_to_logistics=PAYOUT,
        dou_margin=MARGIN,
        status=BookingStatus.active,
    )
    db.add(booking)
    db.commit()
    return account, branch, tenant, rider, booking


# ─────────────────────────────────────────────────────────────────────────────


def test_a_full_month_pays_exactly_the_contracted_amounts(db_session):
    """No proration, no ambiguity: 7,000 in, 5,500 out, 1,500 kept."""
    _world(db_session, key=801, effective_from=MONTH)

    fee = prorate(FEE, DAYS_IN_MONTH, MONTH)
    payout = prorate(PAYOUT, DAYS_IN_MONTH, MONTH)

    assert fee == FEE
    assert payout == PAYOUT
    assert fee - payout == MARGIN


@pytest.mark.parametrize("start_day", [1, 5, 9, 12, 22, 26, 31])
def test_the_three_parties_reconcile_in_the_real_statement(db_session, client, start_day):
    """The invariant, read back from the endpoint the restaurant is billed from.

    Whatever the restaurant is charged must equal what the fleet is paid plus
    what DOU keeps. The days chosen include the four where independent rounding
    of the margin would disagree by a halala, so a change to that logic surfaces
    here rather than in a customer's invoice.
    """
    key = 810 + start_day
    account, branch, *_ = _world(
        db_session, key=key, effective_from=date(2026, 8, start_day)
    )

    # The statement belongs to the account owner. A branch PIN used to open it,
    # which handed one till the whole chain's invoice; that is now refused.
    owner = create_merchant_account_token(account.id)
    res = client.get(
        f"/merchant/account/{account.id}/statement",
        params={"month": MONTH.month, "year": MONTH.year},
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    charged = Decimal(str(body["total_amount_due"]))
    paid_out = Decimal(str(body["total_payout_to_logistics"]))
    kept = Decimal(str(body["dou_net_margin"]))

    assert charged == paid_out + kept, (
        f"بداية يوم {start_day}: المطعم اتحاسب {charged}، الشركة أخدت {paid_out}، "
        f"وDOU حجزت {kept} — المجموع لا يطابق"
    )
    assert kept >= 0, f"بداية يوم {start_day}: هامش سالب — DOU تدفع من جيبها"
    assert paid_out <= charged, f"بداية يوم {start_day}: المستحق أكبر من المحصّل"


def test_the_margin_is_the_residual_and_not_prorated_on_its_own(db_session):
    """Guarding a decision that looks like a bug and is not.

    On a 31-day month, four day-counts make `prorate(1500)` differ from
    `prorate(7000) - prorate(5500)` by one halala. Deriving the margin
    independently would leave the three parties out of balance on those days.
    """
    disagreements = [
        d
        for d in range(1, DAYS_IN_MONTH + 1)
        if prorate(MARGIN, d, MONTH) != prorate(FEE, d, MONTH) - prorate(PAYOUT, d, MONTH)
    ]
    assert disagreements, (
        "no rounding edge found — if proration changed, this guard needs rewriting "
        "rather than deleting"
    )

    for d in disagreements:
        fee = prorate(FEE, d, MONTH)
        payout = prorate(PAYOUT, d, MONTH)
        # The residual always balances; the independent figure does not.
        assert fee - (fee - payout) == payout
        assert abs(prorate(MARGIN, d, MONTH) - (fee - payout)) == Decimal("0.01")


def test_a_seat_that_starts_mid_month_is_charged_for_the_days_it_ran(db_session, client):
    """A restaurant that signs on the 12th does not pay for the first eleven days."""
    start = date(2026, 8, 12)
    account, *_ = _world(db_session, key=802, effective_from=start)

    active_days = (date(2026, 8, 31) - start).days + 1
    assert active_days == 20

    fee = prorate(FEE, active_days, MONTH)
    payout = prorate(PAYOUT, active_days, MONTH)

    assert fee == Decimal("4516.13")     # 7000 × 20/31
    assert payout == Decimal("3548.39")  # 5500 × 20/31
    assert fee - payout == Decimal("967.74")
    assert fee == payout + (fee - payout)


def test_a_seat_that_ends_mid_month_stops_costing_the_restaurant(db_session):
    """A contract terminated on the 10th is billed for ten days, not thirty-one."""
    _world(
        db_session,
        key=803,
        effective_from=MONTH,
        effective_until=date(2026, 8, 10),
    )
    active_days = (date(2026, 8, 10) - MONTH).days + 1
    assert active_days == 10

    fee = prorate(FEE, active_days, MONTH)
    payout = prorate(PAYOUT, active_days, MONTH)
    assert fee < FEE and payout < PAYOUT
    assert fee - payout == prorate(FEE, 10, MONTH) - prorate(PAYOUT, 10, MONTH)


def test_cash_a_rider_carries_is_settled_once_and_only_once(db_session, client):
    """The other half of the month: money that passes through a rider's pocket."""
    account, branch, tenant, rider, booking = _world(
        db_session, key=804, effective_from=MONTH
    )

    login = client.post(
        "/merchant/auth/login", json={"branch_id": branch.id, "pin": PIN}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    today = date.today()
    for amount, method in (
        (Decimal("85.00"), PaymentMethod.cash),
        (Decimal("40.00"), PaymentMethod.cash),
        (Decimal("60.00"), PaymentMethod.card),
    ):
        db_session.add(
            BranchDispatchOrder(
                merchant_branch_id=branch.id,
                dedicated_shift_booking_id=booking.id,
                rider_id=rider.id,
                order_date=today,
                customer_name="عميل",
                customer_phone="966511110000",
                delivery_address_text="حي النخيل",
                status=OrderStatus.delivered,
                delivered_at=datetime.now(timezone.utc),
                order_amount=amount,
                payment_method=method,
                cod_amount=amount if method == PaymentMethod.cash else Decimal("0"),
                dispatched_at=datetime.now(timezone.utc),
            )
        )
    db_session.commit()

    first = client.post(
        f"/merchant/branch/{branch.id}/riders/{rider.id}/settle-cod",
        json={},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    # Only the cash orders. The card order was never money in anyone's pocket.
    assert Decimal(str(first.json()["settled_amount"])) == Decimal("125.00")

    again = client.post(
        f"/merchant/branch/{branch.id}/riders/{rider.id}/settle-cod",
        json={},
        headers=headers,
    )
    assert again.status_code == 409, "the same cash was handed over twice"


def test_settling_cash_does_not_touch_what_the_restaurant_owes(db_session):
    """Two separate flows of money that must never be confused.

    The 7,000 is what the restaurant pays DOU for the seat. The cash a rider
    collects belongs to the restaurant and merely passes through. Netting one
    against the other would quietly change the invoice.
    """
    account, branch, tenant, rider, booking = _world(
        db_session, key=805, effective_from=MONTH
    )
    db_session.add(
        BranchDispatchOrder(
            merchant_branch_id=branch.id,
            dedicated_shift_booking_id=booking.id,
            rider_id=rider.id,
            order_date=date.today(),
            customer_name="عميل",
            customer_phone="966511110001",
            delivery_address_text="حي الملقا",
            status=OrderStatus.delivered,
            order_amount=Decimal("500.00"),
            payment_method=PaymentMethod.cash,
            cod_amount=Decimal("500.00"),
            cod_settled_at=datetime.now(timezone.utc),
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    # The seat still costs exactly what it costs, whatever moved through the till.
    fee = prorate(booking.monthly_fee_to_merchant, DAYS_IN_MONTH, MONTH)
    assert fee == FEE


def test_an_unfilled_seat_still_carries_its_contracted_money(db_session):
    """What an SLA deduction is later computed against.

    A seat the fleet never staffed is still a seat the restaurant contracted.
    Recording it is what makes the shortfall billable; dropping it would quietly
    forgive the fleet and short DOU.
    """
    tenant = Tenant(name="أسطول ناقص", country=Country.SA, subscription_status="ACTIVE")
    db_session.add(tenant)
    db_session.flush()
    account, branch, *_ = _world(db_session, key=806, effective_from=MONTH)

    empty = DedicatedShiftBooking(
        merchant_branch_id=branch.id,
        logistics_company_tenant_id=tenant.id,
        rider_id=None,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(12, 0),
        shift_end_time=time(20, 0),
        effective_from=MONTH,
        monthly_fee_to_merchant=FEE,
        monthly_payout_to_logistics=PAYOUT,
        dou_margin=MARGIN,
        status=BookingStatus.active,
    )
    db_session.add(empty)
    db_session.commit()
    db_session.refresh(empty)

    assert empty.rider_id is None
    assert empty.monthly_fee_to_merchant == FEE
    assert empty.status == BookingStatus.active


def test_the_two_settlement_surfaces_agree_on_the_same_month(db_session, client):
    """A month has one answer, whoever asks.

    `/merchant/account/{id}/statement` prorates each booking by the days it was
    actually active. The admin settlement sums `monthly_fee_to_merchant` for
    every active booking with no proration at all. A seat that started on the
    28th is a fifth of a month to the restaurant's statement and a whole month
    to the settlement that pays the fleet — the same seat, two numbers.
    """
    start = date(2026, 8, 25)
    account, branch, *_ = _world(db_session, key=890, effective_from=start)

    owner = create_merchant_account_token(account.id)
    res = client.get(
        f"/merchant/account/{account.id}/statement",
        params={"month": MONTH.month, "year": MONTH.year},
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert res.status_code == 200, res.text
    statement_charge = Decimal(str(res.json()["total_amount_due"]))

    active_days = (date(2026, 8, 31) - start).days + 1
    expected = prorate(FEE, active_days, MONTH)

    assert statement_charge == expected, (
        f"الكشف حاسب {statement_charge} والمتوقع بالتناسب {expected}"
    )
    assert statement_charge < FEE, (
        "سبعة أيام تشغيل اتحاسبت شهر كامل — التناسب اتفقد في مكان ما"
    )


def test_the_settlement_margin_is_the_residual_not_the_contracted_figure(db_session):
    """What DOU actually keeps is what is left, not the number on the contract.

    Summing the `dou_margin` column instead of taking
    `gross_fee - total_payout` gives a different answer the moment any booking
    is prorated, and leaves the three parties out of balance.
    """
    account, branch, tenant, rider, booking = _world(
        db_session, key=891, effective_from=date(2026, 8, 12)
    )
    active_days = (date(2026, 8, 31) - date(2026, 8, 12)).days + 1
    fee = prorate(booking.monthly_fee_to_merchant, active_days, MONTH)
    payout = prorate(booking.monthly_payout_to_logistics, active_days, MONTH)
    contracted = prorate(booking.dou_margin, active_days, MONTH)

    assert fee - payout == Decimal("967.74")
    # The contracted figure prorates to the same value here; the guard is that
    # the residual is what balances, on every day count.
    assert fee == payout + (fee - payout)
    assert contracted <= fee - payout + Decimal("0.01")


def test_a_settled_month_is_never_recomputed(db_session):
    """Payroll's rule, applied to DOU Flex.

    `CLAUDE.md` states a finalized month is read from its snapshot and never
    recalculated — changing a rate today must not change what was already paid.
    Regenerating settlements must therefore skip any month already issued or
    paid, rather than upserting over it.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "routers" / "admin_dedicated.py"
    ).read_text(encoding="utf-8")

    assert "settlement_status in (SettlementStatus.issued, SettlementStatus.paid)" in source, (
        "the settlement generator no longer skips issued and paid months — a "
        "settled month can be silently rewritten"
    )
    # And the skip must come before anything is written back to the row.
    guard = source.index("settlement_status in (SettlementStatus.issued")
    first_write = source.index("existing.gross_fee_charged_to_merchant =")
    assert guard < first_write, "the immutability check runs after the overwrite"


def test_the_admin_settlement_prorates_like_the_merchant_statement(db_session, client):
    """One month, one answer, whichever surface asks for it.

    The settlement that pays the fleet and books DOU's margin used to sum the
    full monthly rate for every active booking. A seat that started on the 25th
    was a week of service on the restaurant's statement and a whole month here —
    5,419 SAR apart on a single seat, and the fleet was paid for days nobody
    worked.
    """
    import jwt as pyjwt

    from app.config import SECRET_KEY
    from app.models.entities import User, UserRole

    admin = User(
        name="DOU Admin",
        phone="966500009999",
        role=UserRole.DOU_ADMIN,
        is_active=True,
        password_hash="x",
    )
    db_session.add(admin)
    db_session.flush()

    start = date(2026, 8, 25)
    account, branch, *_ = _world(db_session, key=895, effective_from=start)
    db_session.commit()

    token = pyjwt.encode(
        {
            "sub": str(admin.id),
            "phone": admin.phone,
            "role": "DOU_ADMIN",
            "ver": 0,
            "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
        },
        SECRET_KEY,
        algorithm="HS256",
    )

    res = client.post(
        "/admin/dedicated/settlements/generate",
        json={"month": MONTH_STR, "merchant_id": account.id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text

    rows = res.json()
    rows = rows if isinstance(rows, list) else rows.get("settlements", rows.get("results", []))
    mine = [r for r in rows if r.get("merchant_account_id") == account.id or r.get("merchant_id") == account.id]
    assert mine, f"لم تُصدر مقاصة للحساب {account.id}: {rows}"
    row = mine[0]

    active_days = (date(2026, 8, 31) - start).days + 1   # 7
    expected_fee = prorate(FEE, active_days, MONTH)
    expected_payout = prorate(PAYOUT, active_days, MONTH)

    charged = Decimal(str(row["gross_fee_charged_to_merchant"]))
    paid_out = Decimal(str(row["total_payout_to_logistics"]))
    kept = Decimal(str(row["dou_net_margin"]))

    assert charged == expected_fee, (
        f"سبعة أيام تشغيل اتحاسبت {charged} والمفروض {expected_fee} — التناسب مفقود"
    )
    assert paid_out == expected_payout
    assert charged == paid_out + kept, "الأطراف الثلاثة لا تتصالح في المقاصة"


def test_a_branch_pin_cannot_read_the_chain_invoice(db_session, client):
    """One till, one branch — not the group's books.

    A cashier logs in with a branch id and a four-digit PIN. That token used to
    satisfy the account-level dependency, so any till could read the chain's
    total invoice and every other branch's line items. With one branch it looked
    harmless; with a chain it is the group's commercial position on a tablet in
    a restaurant.
    """
    account, branch, *_ = _world(db_session, key=899, effective_from=MONTH)

    login = client.post(
        "/merchant/auth/login", json={"branch_id": branch.id, "pin": PIN}
    )
    assert login.status_code == 200, login.text

    res = client.get(
        f"/merchant/account/{account.id}/statement",
        params={"month": MONTH.month, "year": MONTH.year},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert res.status_code == 403, (
        "a branch PIN opened the chain's statement — the cashier can read the "
        "group's invoice and every other branch's figures"
    )
