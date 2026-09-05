"""Tests for Driver Portal Features (Step 4: تطبيق وبوابة السائق).

Covers:
1. Active branch orders expose financial fields (order_amount, payment_method, cod_amount, currency, external_order_id).
2. Driver float endpoint (/driver/float) matches cashier portal open float exactly (single source of truth).
3. 'unknown' payment method is excluded from cash collect and does not add to float.
4. 'card' or 'prepaid' payment methods yield 0 float.
5. Settled order (cod_settled_at IS NOT NULL) is excluded from driver's float.
6. Driver submits attendance correction (POST /timekeeping/corrections) and fleet review queue sees it.
7. Driver cannot submit attendance correction for another driver (HTTP 403).
8. Driver submits leave request (POST /hr/me/leave) and retrieves it.
"""

import os
from datetime import date, datetime, time, timezone
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import SECRET_KEY
from app.database import Base, get_db
from app.main import app
from app.models.entities import Country, Courier, CourierType, Tenant, User, UserRole
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
from app.routers.auth import create_token, hash_password
from app.utils.security import hash_pin

TEST_DB_FILE = "./test_driver_portal.db"
engine = create_engine(
    f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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


def _seed_branch_and_tenant(db, bid: int = 901) -> tuple[MerchantBranch, Tenant]:
    account = MerchantAccount(
        id=bid,
        trade_name="مطاعم سحاب",
        billing_contact_email="finance@sahab.sa",
        billing_contact_phone="966500000000",
        payment_terms_days=30,
        is_active=True,
    )
    db.add(account)
    db.flush()

    branch = MerchantBranch(
        id=bid,
        merchant_account_id=account.id,
        branch_name="فرع التخصصي",
        city="الرياض",
        latitude=24.7136,
        longitude=46.6753,
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("1234"),
        is_active=True,
    )
    db.add(branch)
    db.flush()

    tenant = Tenant(name="شركة فاست لوجستيكس", country=Country.SA, currency="SAR", subscription_status="ACTIVE")
    db.add(tenant)
    db.flush()

    return branch, tenant


def _seed_rider_and_user(db, tenant_id: int, name: str, phone: str) -> tuple[Courier, User, str]:
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

    user = User(
        phone=phone,
        name=name,
        password_hash=hash_password("secret123"),
        role=UserRole.COURIER,
        courier_id=rider.id,
        tenant_id=tenant_id,
        is_active=True,
        token_version=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user)
    return rider, user, token


def _seed_fleet_manager(db, tenant_id: int, phone: str = "966599999999") -> tuple[User, str]:
    user = User(
        phone=phone,
        name="مدير الأسطول",
        password_hash=hash_password("admin123"),
        role=UserRole.OPERATIONS,
        tenant_id=tenant_id,
        is_active=True,
        token_version=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user)
    return user, token


def _seed_booking(db, branch_id: int, tenant_id: int, rider_id: int) -> DedicatedShiftBooking:
    booking = DedicatedShiftBooking(
        merchant_branch_id=branch_id,
        logistics_company_tenant_id=tenant_id,
        rider_id=rider_id,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(10, 0),
        shift_end_time=time(18, 0),
        effective_from=date.today(),
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("5500.00"),
        dou_margin=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    db.add(booking)
    db.flush()
    return booking


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_active_branch_orders_financial_fields(db_session, client):
    """Active branch orders must expose order_amount, payment_method, cod_amount, currency."""
    branch, tenant = _seed_branch_and_tenant(db_session, bid=910)
    rider, _, token = _seed_rider_and_user(db_session, tenant.id, "أحمد علي", "966511111111")
    _seed_booking(db_session, branch.id, tenant.id, rider.id)

    order = BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="خالد التميمي",
        customer_phone="966555555555",
        delivery_address_text="حي النرجس",
        status=OrderStatus.pending,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("85.50"),
        cod_amount=Decimal("85.50"),
        external_order_id="POS-1001",
    )
    db_session.add(order)
    db_session.commit()

    resp = client.get(
        "/driver/orders/branch/active",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    orders = resp.json()
    assert len(orders) >= 1
    target = next((o for o in orders if o["order_id"] == order.id), None)
    assert target is not None

    assert target["payment_method"] == "cash"
    assert target["order_amount"] == 85.50
    assert target["cod_amount"] == 85.50
    assert target["external_order_id"] == "POS-1001"
    assert target["currency"] == "SAR"


def test_driver_float_matches_cashier_portal_and_single_source(db_session, client):
    """Driver float must match the cashier portal open float exactly."""
    branch, tenant = _seed_branch_and_tenant(db_session, bid=911)
    rider, _, token = _seed_rider_and_user(db_session, tenant.id, "فهد الدوسري", "966522222222")
    booking = _seed_booking(db_session, branch.id, tenant.id, rider.id)

    # Rider is checked in
    db_session.add(ShiftAttendanceLog(
        dedicated_shift_booking_id=booking.id,
        rider_id=rider.id,
        log_date=date.today(),
        checkin_at=datetime.now(timezone.utc),
        checkin_lat=24.7136,
        checkin_lng=46.6753,
        geofence_validated=True,
    ))

    # Delivered Cash order: 120.00 -> should be in float
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل 1",
        customer_phone="966500000001",
        delivery_address_text="العليا",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("120.00"),
        cod_amount=Decimal("120.00"),
    ))
    # Undelivered Cash order: 50.00 -> NOT in float
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل 2",
        customer_phone="966500000002",
        delivery_address_text="الملقا",
        status=OrderStatus.en_route,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("50.00"),
        cod_amount=Decimal("50.00"),
    ))
    db_session.commit()

    # Cashier portal check
    from app.utils.security import create_branch_token
    branch_token = create_branch_token(branch.id, branch.merchant_account_id)
    c_resp = client.get(
        f"/merchant/branch/{branch.id}/riders/active",
        headers={"Authorization": f"Bearer {branch_token}"},
    )
    assert c_resp.status_code == 200
    c_cards = c_resp.json()
    rider_card = next(c for c in c_cards if c["rider_id"] == rider.id)
    cashier_float = rider_card["open_float"]
    assert cashier_float == 120.00

    # Driver float check
    d_resp = client.get(
        "/driver/float",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert d_resp.status_code == 200, d_resp.text
    d_data = d_resp.json()
    assert d_data["unsettled_amount"] == cashier_float == 120.00
    assert d_data["delivered_orders_count"] == 1
    assert d_data["currency"] == "SAR"


def test_unknown_payment_method_excluded_from_float(db_session, client):
    """'unknown' payment method must NEVER add to float or be treated as cash collect."""
    branch, tenant = _seed_branch_and_tenant(db_session, bid=912)
    rider, _, token = _seed_rider_and_user(db_session, tenant.id, "سامي خليل", "966533333333")
    _seed_booking(db_session, branch.id, tenant.id, rider.id)

    # Delivered order with 'unknown' payment method
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل مجهول",
        customer_phone="966500000003",
        delivery_address_text="الياسمين",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.unknown,
        order_amount=Decimal("95.00"),
        cod_amount=Decimal("0.00"),
    ))
    db_session.commit()

    resp = client.get(
        "/driver/float",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["unsettled_amount"] == 0.0
    assert data["delivered_orders_count"] == 0


def test_card_prepaid_payment_method_zero_float(db_session, client):
    """'card' and 'prepaid' orders must yield 0 float."""
    branch, tenant = _seed_branch_and_tenant(db_session, bid=913)
    rider, _, token = _seed_rider_and_user(db_session, tenant.id, "منصور العتيبي", "966544444444")
    _seed_booking(db_session, branch.id, tenant.id, rider.id)

    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل بطاقة",
        customer_phone="966500000004",
        delivery_address_text="الصحافة",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.card,
        order_amount=Decimal("150.00"),
        cod_amount=Decimal("0.00"),
    ))
    db_session.add(BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل مسبق",
        customer_phone="966500000005",
        delivery_address_text="الربيع",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.prepaid,
        order_amount=Decimal("200.00"),
        cod_amount=Decimal("0.00"),
    ))
    db_session.commit()

    resp = client.get(
        "/driver/float",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["unsettled_amount"] == 0.0
    assert data["delivered_orders_count"] == 0


def test_settled_order_excluded_from_float(db_session, client):
    """When cashier settles COD, driver's float zeroes out immediately."""
    branch, tenant = _seed_branch_and_tenant(db_session, bid=914)
    rider, _, token = _seed_rider_and_user(db_session, tenant.id, "تركي الحربي", "966566666666")
    _seed_booking(db_session, branch.id, tenant.id, rider.id)

    order = BranchDispatchOrder(
        merchant_branch_id=branch.id,
        rider_id=rider.id,
        order_date=date.today(),
        customer_name="عميل تسوية",
        customer_phone="966500000006",
        delivery_address_text="النخيل",
        status=OrderStatus.delivered,
        payment_method=PaymentMethod.cash,
        order_amount=Decimal("75.00"),
        cod_amount=Decimal("75.00"),
    )
    db_session.add(order)
    db_session.commit()

    # Before settlement
    resp1 = client.get("/driver/float", headers={"Authorization": f"Bearer {token}"})
    assert resp1.status_code == 200
    assert resp1.json()["unsettled_amount"] == 75.00

    # Cashier settles it
    from app.utils.security import create_branch_token
    b_token = create_branch_token(branch.id, branch.merchant_account_id)
    s_resp = client.post(
        f"/merchant/branch/{branch.id}/riders/{rider.id}/settle-cod",
        headers={"Authorization": f"Bearer {b_token}"},
    )
    assert s_resp.status_code == 200

    # After settlement -> must be 0
    resp2 = client.get("/driver/float", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
    assert resp2.json()["unsettled_amount"] == 0.0
    assert resp2.json()["delivered_orders_count"] == 0


def test_driver_submits_attendance_correction_and_fleet_reviews(db_session, client):
    """Driver submits correction and fleet manager sees it in review queue."""
    branch, tenant = _seed_branch_and_tenant(db_session, bid=915)
    rider, user, token = _seed_rider_and_user(db_session, tenant.id, "يوسف الشهري", "966577777777")
    fleet_mgr, fleet_token = _seed_fleet_manager(db_session, tenant.id, phone="966599999991")

    # Driver submits correction
    req_body = {
        "reason": "نسيت تسجيل الخروج بسبب عطل في الشبكة",
        "requested_check_in": "2026-09-05T08:00:00",
        "requested_check_out": "2026-09-05T16:00:00",
    }
    submit_resp = client.post(
        "/timekeeping/corrections",
        json=req_body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert submit_resp.status_code == 201, submit_resp.text
    corr_id = submit_resp.json()["id"]

    # Fleet manager lists corrections
    fleet_resp = client.get(
        "/timekeeping/corrections",
        headers={"Authorization": f"Bearer {fleet_token}"},
    )
    assert fleet_resp.status_code == 200
    queue = fleet_resp.json()
    item = next((c for c in queue if c["id"] == corr_id), None)
    assert item is not None
    assert item["courier_id"] == rider.id
    assert item["reason"] == "نسيت تسجيل الخروج بسبب عطل في الشبكة"
    assert item["status"] == "PENDING"

    # Driver lists own corrections
    rider_list_resp = client.get(
        "/timekeeping/corrections",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rider_list_resp.status_code == 200
    r_items = rider_list_resp.json()
    assert any(c["id"] == corr_id for c in r_items)


def test_driver_cannot_submit_correction_for_another_driver(db_session, client):
    """A courier cannot submit a correction on behalf of a different courier_id."""
    _, tenant = _seed_branch_and_tenant(db_session, bid=916)
    rider1, _, token1 = _seed_rider_and_user(db_session, tenant.id, "سائق 1", "966588888881")
    rider2, _, _ = _seed_rider_and_user(db_session, tenant.id, "سائق 2", "966588888882")

    resp = client.post(
        "/timekeeping/corrections",
        json={
            "courier_id": rider2.id,  # Trying to submit for rider 2
            "reason": "محاولة غير مصرح بها",
        },
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"


def test_driver_submits_leave_and_retrieves(db_session, client):
    """Driver submits leave request via /hr/me/leave and retrieves via /hr/me/leaves."""
    _, tenant = _seed_branch_and_tenant(db_session, bid=917)
    rider, _, token = _seed_rider_and_user(db_session, tenant.id, "جمال إبراهيم", "966599999993")

    resp = client.post(
        "/hr/me/leave",
        json={
            "from_date": "2026-09-10",
            "to_date": "2026-09-15",
            "reason": "إجازة سنوية اعتيادية",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("ok") is True

    get_resp = client.get(
        "/hr/me/leaves",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 200
    leaves = get_resp.json()
    assert len(leaves) >= 1
    assert leaves[0]["reason"] == "إجازة سنوية اعتيادية"
    assert leaves[0]["status"] == "PENDING"
