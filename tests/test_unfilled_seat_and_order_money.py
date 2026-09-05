"""A contracted seat with nobody in it, and money on a branch order.

`dedicated_shift_bookings.rider_id` used to be NOT NULL, so one row was always
one staffed seat. A branch that contracted ten riders and is running with eight
could not say so, and an SLA shortfall you cannot record is one you cannot bill.

Making it nullable is only safe while an empty seat stays invisible to the
people who would act on it: the cashier must not be offered a rider who does not
exist, and no driver may ever see the seat as their shift. That is what these
tests hold.

`branch_dispatch_orders` separately carried no money at all, which is why the
rider could not be told whether to collect cash and the cashier could not clear
the rider's float. The defaults matter as much as the columns: an order that
predates the quick-entry form is `unknown`, never a guessed `cash`.
"""

import os
from datetime import date, datetime, time, timezone
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
    PaymentMethod,
    ShiftType,
)
from app.utils.security import hash_pin

TEST_DB_FILE = "./test_unfilled_seat.db"
engine = create_engine(
    f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

BRANCH_PIN = "4417"


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


def _branch(db, *, bid: int) -> MerchantBranch:
    account = MerchantAccount(
        id=bid,
        trade_name="مطعم الاختبار",
        billing_contact_email="ops@test.sa",
        billing_contact_phone="966500000000",
        payment_terms_days=30,
        is_active=True,
    )
    db.add(account)
    db.flush()
    branch = MerchantBranch(
        id=bid,
        merchant_account_id=account.id,
        branch_name="فرع السليمانية",
        city="الرياض",
        latitude=24.7136,
        longitude=46.6753,
        geofence_radius_meters=200,
        cashier_access_pin=hash_pin(BRANCH_PIN),
        is_active=True,
    )
    db.add(branch)
    db.flush()
    return branch


def _seat(db, branch_id: int, tenant_id: int, rider_id: int | None) -> DedicatedShiftBooking:
    booking = DedicatedShiftBooking(
        merchant_branch_id=branch_id,
        logistics_company_tenant_id=tenant_id,
        rider_id=rider_id,
        shift_type=ShiftType.peak_3h,
        shift_start_time=time(16, 0),
        shift_end_time=time(19, 0),
        effective_from=date.today(),
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("5500.00"),
        dou_margin=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    db.add(booking)
    db.flush()
    return booking


def test_a_contracted_seat_can_exist_with_nobody_in_it(db_session):
    """Ten seats bought, eight staffed — the other two have to be representable."""
    tenant = Tenant(name="أسطول الاختبار", country=Country.SA, subscription_status="ACTIVE")
    db_session.add(tenant)
    db_session.flush()
    branch = _branch(db_session, bid=701)

    seat = _seat(db_session, branch.id, tenant.id, rider_id=None)
    db_session.commit()

    assert seat.id is not None
    assert seat.rider_id is None
    # The money is contracted per seat, whether or not it is staffed. That is
    # exactly what an SLA deduction is later computed against.
    assert seat.monthly_fee_to_merchant == Decimal("7000.00")
    assert seat.dou_margin == Decimal("1500.00")


def test_the_cashier_is_never_offered_a_rider_who_does_not_exist(db_session, client):
    """An empty seat must not reach the screen a cashier dispatches from."""
    tenant = Tenant(name="أسطول الكاشير", country=Country.SA, subscription_status="ACTIVE")
    db_session.add(tenant)
    db_session.flush()
    branch = _branch(db_session, bid=702)

    rider = Courier(
        tenant_id=tenant.id,
        name="عمر حسن",
        phone="966500007777",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db_session.add(rider)
    db_session.flush()

    _seat(db_session, branch.id, tenant.id, rider_id=rider.id)
    _seat(db_session, branch.id, tenant.id, rider_id=None)
    db_session.commit()

    login = client.post(
        "/merchant/auth/login", json={"branch_id": branch.id, "pin": BRANCH_PIN}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    res = client.get(
        f"/merchant/branch/{branch.id}/riders/active",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text

    cards = res.json()
    # The card deliberately carries no rider id — the merchant sees a masked
    # name and never the logistics company's identifiers — so the seat count is
    # what proves the empty seat was dropped rather than rendered as a blank.
    assert len(cards) == 1, (
        f"two seats, one staffed, but {len(cards)} cards came back — "
        "an unstaffed seat reached the screen the cashier dispatches from"
    )
    assert cards[0]["rider_name"], "the one real rider came back without a name"
    assert cards[0]["shift_start"] == "16:00"


def test_an_order_defaults_to_unknown_payment_not_to_cash(db_session):
    """A rider must never be told to collect an amount the system guessed."""
    tenant = Tenant(name="أسطول الطلبات", country=Country.SA, subscription_status="ACTIVE")
    db_session.add(tenant)
    db_session.flush()
    branch = _branch(db_session, bid=703)

    order = BranchDispatchOrder(
        merchant_branch_id=branch.id,
        order_date=date.today(),
        customer_name="عميل",
        customer_phone="966511112222",
        delivery_address_text="حي النخيل",
        dispatched_at=datetime.now(timezone.utc),
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)

    assert order.payment_method == PaymentMethod.unknown
    assert Decimal(str(order.cod_amount)) == Decimal("0")
    assert order.order_amount is None
    assert order.cod_settled_at is None


def test_an_unsettled_cash_order_is_the_riders_open_float(db_session):
    """What the cashier's handover button and the rider's wallet both read."""
    tenant = Tenant(name="أسطول العهدة", country=Country.SA, subscription_status="ACTIVE")
    db_session.add(tenant)
    db_session.flush()
    branch = _branch(db_session, bid=704)
    rider = Courier(
        tenant_id=tenant.id,
        name="خالد",
        phone="966500008888",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db_session.add(rider)
    db_session.flush()

    for amount, method, settled in (
        (Decimal("85.00"), PaymentMethod.cash, None),
        (Decimal("40.00"), PaymentMethod.cash, datetime.now(timezone.utc)),
        (Decimal("60.00"), PaymentMethod.card, None),
    ):
        db_session.add(
            BranchDispatchOrder(
                merchant_branch_id=branch.id,
                rider_id=rider.id,
                order_date=date.today(),
                customer_name="عميل",
                customer_phone="966511113333",
                delivery_address_text="حي الملقا",
                order_amount=amount,
                payment_method=method,
                cod_amount=amount if method == PaymentMethod.cash else Decimal("0"),
                cod_settled_at=settled,
                dispatched_at=datetime.now(timezone.utc),
            )
        )
    db_session.commit()

    open_float = sum(
        Decimal(str(o.cod_amount))
        for o in db_session.query(BranchDispatchOrder)
        .filter(
            BranchDispatchOrder.rider_id == rider.id,
            BranchDispatchOrder.cod_settled_at.is_(None),
        )
        .all()
    )
    # Only the unsettled cash order counts: the settled one was handed over and
    # the card order was never cash in anyone's pocket.
    assert open_float == Decimal("85.00")
