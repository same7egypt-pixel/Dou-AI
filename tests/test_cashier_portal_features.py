"""Tests for Cashier Portal Features (Step 2: بوابة الكاشير).

Covers:
1. Open float calculation (delivered + cash + unsettled only; card/prepaid/settled/undelivered excluded).
2. COD settlement sets cod_settled_at; second settlement attempt is rejected (idempotency/rejection).
3. Fair round-robin does not assign the same rider twice in a row when multiple are available.
4. Named rider dispatch assigns to selected rider directly.
5. Cashier fallback check-in is auditable and distinguished from GPS check-in in the database log.
6. Fast order entry creates orders with payment method, order amount, and auto-computed cod_amount.
7. Unstaffed/vacant seats render as vacant seat when requested, never as a nameless rider.
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
    OrderStatus,
    PaymentMethod,
    ShiftAttendanceLog,
    ShiftType,
)
from app.utils.security import create_branch_token, hash_pin

TEST_DB_FILE = "./test_cashier_portal.db"
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


def _seed_branch(db, bid: int = 801) -> tuple[MerchantBranch, Tenant]:
    account = MerchantAccount(
        id=bid,
        trade_name="سلسلة برجر المحطة",
        billing_contact_email="ops@burger.sa",
        billing_contact_phone="966500000000",
        payment_terms_days=30,
        is_active=True,
    )
    db.add(account)
    db.flush()

    branch = MerchantBranch(
        id=bid,
        merchant_account_id=account.id,
        branch_name="فرع العليا",
        city="الرياض",
        latitude=24.7136,
        longitude=46.6753,
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin(BRANCH_PIN),
        is_active=True,
    )
    db.add(branch)
    db.flush()

    tenant = Tenant(name="لوجستيات الرياض", country=Country.SA, subscription_status="ACTIVE")
    db.add(tenant)
    db.flush()

    return branch, tenant


def _seed_rider(db, tenant_id: int, name: str, phone: str) -> Courier:
    rider = Courier(
        tenant_id=tenant_id,
        name=name,
        phone=phone,
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db.add(rider)
    db.flush()
    return rider


def _seed_booking(db, branch_id: int, tenant_id: int, rider_id: int | None) -> DedicatedShiftBooking:
    booking = DedicatedShiftBooking(
        merchant_branch_id=branch_id,
        logistics_company_tenant_id=tenant_id,
        rider_id=rider_id,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(12, 0),
        shift_end_time=time(20, 0),
        effective_from=date.today(),
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("5500.00"),
        dou_margin=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    db.add(booking)
    db.flush()
    return booking


# ─── 1. Open Float Calculation & Filtering ─────────────────────────────────────

def test_open_float_counts_only_delivered_unsettled_cash(db_session, client):
    """Open float must include ONLY: status=delivered, payment_method=cash, cod_settled_at is NULL."""
    branch, tenant = _seed_branch(db_session, bid=802)
    rider = _seed_rider(db_session, tenant.id, "سعد فهد", "966500112233")
    booking = _seed_booking(db_session, branch.id, tenant.id, rider.id)

    # Set up check-in so rider is active
    log = ShiftAttendanceLog(
        dedicated_shift_booking_id=booking.id,
        rider_id=rider.id,
        log_date=date.today(),
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=24.7136,
        checkin_lng=46.6753,
        geofence_validated=True,
    )
    db_session.add(log)
    db_session.flush()

    # 1. Delivered Cash Unsettled -> SHOULD COUNT (100.00)
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل 1",
        customer_phone="966500000001",
        delivery_address_text="العليا",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("100.00"),
        cod_amount=Decimal("100.00"),
        cod_settled_at=None,
    ))

    # 2. Delivered Cash Settled -> EXCLUDED (already handed over)
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل 2",
        customer_phone="966500000002",
        delivery_address_text="العليا",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("45.00"),
        cod_amount=Decimal("45.00"),
        cod_settled_at=datetime.now(timezone.utc),
    ))

    # 3. Delivered Card Unsettled -> EXCLUDED (no cash collected)
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل 3",
        customer_phone="966500000003",
        delivery_address_text="العليا",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.card,
        order_amount=Decimal("80.00"),
        cod_amount=Decimal("0.00"),
        cod_settled_at=None,
    ))

    # 4. En-route Cash Unsettled -> EXCLUDED (rider hasn't delivered/collected yet)
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل 4",
        customer_phone="966500000004",
        delivery_address_text="العليا",
        status=OrderStatus.en_route,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("120.00"),
        cod_amount=Decimal("120.00"),
        cod_settled_at=None,
    ))

    # 5. Delivered with no amount -> EXCLUDED (zero float)
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل 5",
        customer_phone="966500000005",
        delivery_address_text="العليا",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.unknown,
        order_amount=None,
        cod_amount=Decimal("0.00"),
        cod_settled_at=None,
    ))

    db_session.commit()

    token = create_branch_token(branch.id)
    res = client.get(
        f"/merchant/branch/{branch.id}/riders/active",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    cards = res.json()
    assert len(cards) == 1
    rider_card = cards[0]

    assert "open_float" in rider_card, "ActiveRiderCard must expose open_float"
    assert Decimal(str(rider_card["open_float"])) == Decimal("100.00"), (
        f"Expected 100.00 SAR open float, got {rider_card['open_float']}"
    )


# ─── 2. COD Float Settlement & Re-settlement Rejection ─────────────────────────

def test_cod_settlement_lifecycle_and_rejection(db_session, client):
    """Cashier settles float; second settlement attempt is rejected."""
    branch, tenant = _seed_branch(db_session, bid=803)
    rider = _seed_rider(db_session, tenant.id, "أحمد ناصر", "966500223344")
    booking = _seed_booking(db_session, branch.id, tenant.id, rider.id)

    order1 = BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل أ",
        customer_phone="966500000010",
        delivery_address_text="السليمانية",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("50.00"),
        cod_amount=Decimal("50.00"),
        cod_settled_at=None,
    )
    order2 = BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل ب",
        customer_phone="966500000011",
        delivery_address_text="السليمانية",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("75.00"),
        cod_amount=Decimal("75.00"),
        cod_settled_at=None,
    )
    db_session.add_all([order1, order2])
    db_session.commit()

    token = create_branch_token(branch.id)

    # First settlement: should succeed and settle 125.00 SAR
    res_settle = client.post(
        f"/merchant/branch/{branch.id}/riders/{rider.id}/settle-cod",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_settle.status_code == 200, res_settle.text
    settle_data = res_settle.json()
    assert Decimal(str(settle_data["settled_amount"])) == Decimal("125.00")
    assert settle_data["orders_count"] == 2
    assert set(settle_data["order_ids"]) == {order1.id, order2.id}

    # Verify orders in DB are stamped with cod_settled_at
    db_session.refresh(order1)
    db_session.refresh(order2)
    assert order1.cod_settled_at is not None
    assert order2.cod_settled_at is not None

    # Second settlement attempt: must be rejected (idempotent / no open float)
    res_repeat = client.post(
        f"/merchant/branch/{branch.id}/riders/{rider.id}/settle-cod",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_repeat.status_code in (400, 409), (
        f"Repeated settlement must be rejected, got {res_repeat.status_code}"
    )


# ─── 3. Fair Round-Robin Dispatch ──────────────────────────────────────────────

def test_fair_round_robin_does_not_repeat_same_rider(db_session, client):
    """When multiple riders are available, round-robin must not assign twice to the same rider."""
    branch, tenant = _seed_branch(db_session, bid=804)
    rider1 = _seed_rider(db_session, tenant.id, "ماجد عبد الله", "966500334455")
    rider2 = _seed_rider(db_session, tenant.id, "سلطان العتيبي", "966500334456")

    booking1 = _seed_booking(db_session, branch.id, tenant.id, rider1.id)
    booking2 = _seed_booking(db_session, branch.id, tenant.id, rider2.id)

    # Both checked in
    today = date.today()
    log1 = ShiftAttendanceLog(
        dedicated_shift_booking_id=booking1.id,
        rider_id=rider1.id,
        log_date=today,
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=24.7136,
        checkin_lng=46.6753,
        geofence_validated=True,
    )
    log2 = ShiftAttendanceLog(
        dedicated_shift_booking_id=booking2.id,
        rider_id=rider2.id,
        log_date=today,
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=24.7136,
        checkin_lng=46.6753,
        geofence_validated=True,
    )
    db_session.add_all([log1, log2])
    db_session.commit()

    token = create_branch_token(branch.id)

    # Dispatch order 1
    res1 = client.post(
        f"/merchant/branch/{branch.id}/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"customer_name": "عميل 1", "customer_phone": "966511111111", "delivery_address": "حي النخيل"},
    )
    assert res1.status_code == 200, res1.text
    first_rider_name = res1.json()["assigned_rider_name"]

    # Dispatch order 2: MUST NOT be first_rider_name!
    res2 = client.post(
        f"/merchant/branch/{branch.id}/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"customer_name": "عميل 2", "customer_phone": "966522222222", "delivery_address": "حي الياسمين"},
    )
    assert res2.status_code == 200, res2.text
    second_rider_name = res2.json()["assigned_rider_name"]

    assert first_rider_name != second_rider_name, (
        f"Round-robin assigned {first_rider_name} twice in a row when {second_rider_name} was available!"
    )


# ─── 4. Named Rider Dispatch ───────────────────────────────────────────────────

def test_named_rider_dispatch_assigns_specified_rider(db_session, client):
    """Cashier selects specific rider by id."""
    branch, tenant = _seed_branch(db_session, bid=805)
    rider_a = _seed_rider(db_session, tenant.id, "خالد الشمري", "966500445566")
    rider_b = _seed_rider(db_session, tenant.id, "فهد الدوسري", "966500445567")

    booking_a = _seed_booking(db_session, branch.id, tenant.id, rider_a.id)
    booking_b = _seed_booking(db_session, branch.id, tenant.id, rider_b.id)

    today = date.today()
    log_a = ShiftAttendanceLog(
        dedicated_shift_booking_id=booking_a.id,
        rider_id=rider_a.id,
        log_date=today,
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=24.7136,
        checkin_lng=46.6753,
        geofence_validated=True,
    )
    log_b = ShiftAttendanceLog(
        dedicated_shift_booking_id=booking_b.id,
        rider_id=rider_b.id,
        log_date=today,
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=24.7136,
        checkin_lng=46.6753,
        geofence_validated=True,
    )
    db_session.add_all([log_a, log_b])
    db_session.commit()

    token = create_branch_token(branch.id)

    # Specifically request rider_b
    res = client.post(
        f"/merchant/branch/{branch.id}/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "customer_name": "عميل محدد",
            "customer_phone": "966533333333",
            "delivery_address": "حي الغدير",
            "rider_id": rider_b.id,
        },
    )
    assert res.status_code == 200, res.text
    assert "فهد" in res.json()["assigned_rider_name"]


# ─── 5. Cashier Fallback Check-in Distinguished from GPS ────────────────────────

def test_cashier_fallback_checkin_is_distinguished_in_log(db_session, client):
    """Cashier confirms indoor rider; log must record cashier confirmation (checkin_lat IS NULL)."""
    branch, tenant = _seed_branch(db_session, bid=806)
    rider = _seed_rider(db_session, tenant.id, "منصور العسيري", "966500556677")
    booking = _seed_booking(db_session, branch.id, tenant.id, rider.id)
    db_session.commit()

    token = create_branch_token(branch.id)

    # Cashier confirms check-in manually
    res = client.post(
        f"/merchant/branch/{branch.id}/riders/{rider.id}/cashier-checkin",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["checkin_source"] == "cashier"

    # Verify log row directly in database
    today = date.today()
    log = db_session.query(ShiftAttendanceLog).filter(
        ShiftAttendanceLog.dedicated_shift_booking_id == booking.id,
        ShiftAttendanceLog.rider_id == rider.id,
        ShiftAttendanceLog.log_date == today,
    ).first()

    assert log is not None
    assert log.checkin_at is not None
    # Strictly distinguish cashier check-in: no GPS coordinates!
    assert log.checkin_lat is None, "Cashier check-in must not fabricate GPS coordinates"
    assert log.checkin_lng is None, "Cashier check-in must not fabricate GPS coordinates"
    assert log.geofence_validated is False, "Geofence is not validated when GPS failed"

    # Verify active riders API shows checked_in and checkin_source == cashier
    res_cards = client.get(
        f"/merchant/branch/{branch.id}/riders/active",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_cards.status_code == 200
    card = res_cards.json()[0]
    assert card["checkin_status"] == "checked_in"
    assert card.get("checkin_source") == "cashier"

    # Now verify this rider can receive dispatches!
    res_dispatch = client.post(
        f"/merchant/branch/{branch.id}/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={"customer_name": "عميل الكاشير", "customer_phone": "966544444444", "delivery_address": "حي النزهة"},
    )
    assert res_dispatch.status_code == 200, res_dispatch.text
    assert "منصور" in res_dispatch.json()["assigned_rider_name"]


# ─── 6. Fast Order Entry & Optional Address ────────────────────────────────────

def test_fast_order_entry_optional_address_and_auto_cod(db_session, client):
    """Cashier enters order in 5s: Invoice + Amount + Cash; address/phone are optional with external_order_id."""
    branch, tenant = _seed_branch(db_session, bid=807)
    rider = _seed_rider(db_session, tenant.id, "إبراهيم الحربي", "966500667788")
    booking = _seed_booking(db_session, branch.id, tenant.id, rider.id)

    log = ShiftAttendanceLog(
        dedicated_shift_booking_id=booking.id,
        rider_id=rider.id,
        log_date=date.today(),
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=24.7136,
        checkin_lng=46.6753,
        geofence_validated=True,
    )
    db_session.add(log)
    db_session.commit()

    token = create_branch_token(branch.id)

    # 1. Cash order with invoice number and no address
    res_cash = client.post(
        f"/merchant/branch/{branch.id}/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "external_order_id": "POS-1001",
            "order_amount": 65.50,
            "payment_method": "cash",
        },
    )
    assert res_cash.status_code == 200, res_cash.text
    order_id = res_cash.json()["order_id"]

    order = db_session.get(BranchDispatchOrder, order_id)
    assert order.external_order_id == "POS-1001"
    assert order.payment_method == PaymentMethod.cash
    assert Decimal(str(order.order_amount)) == Decimal("65.50")
    assert Decimal(str(order.cod_amount)) == Decimal("65.50"), "Cash payment must set cod_amount equal to order_amount"

    # 2. Card order with invoice number
    res_card = client.post(
        f"/merchant/branch/{branch.id}/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "external_order_id": "POS-1002",
            "order_amount": 120.00,
            "payment_method": "card",
        },
    )
    assert res_card.status_code == 200, res_card.text
    card_order = db_session.get(BranchDispatchOrder, res_card.json()["order_id"])
    assert card_order.payment_method == PaymentMethod.card
    assert Decimal(str(card_order.cod_amount)) == Decimal("0.00"), "Card payment must set cod_amount to 0"


# ─── 7. Vacant Seats Representation ────────────────────────────────────────────

def test_vacant_seat_rendered_as_vacant_seat_not_blank_rider(db_session, client):
    """When requested with include_vacant=true, unfilled seat appears as 'مقعد شاغر'."""
    branch, tenant = _seed_branch(db_session, bid=808)
    _seed_booking(db_session, branch.id, tenant.id, rider_id=None)
    db_session.commit()

    token = create_branch_token(branch.id)

    # Default call still hides it (backwards compatible for existing contract)
    res_default = client.get(
        f"/merchant/branch/{branch.id}/riders/active",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert len(res_default.json()) == 0

    # Explicit query with include_vacant=true returns vacant seat card
    res_vacant = client.get(
        f"/merchant/branch/{branch.id}/riders/active?include_vacant=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_vacant.status_code == 200
    cards = res_vacant.json()
    assert len(cards) == 1
    assert cards[0]["is_vacant"] is True
    assert "شاغر" in cards[0]["rider_name"]
