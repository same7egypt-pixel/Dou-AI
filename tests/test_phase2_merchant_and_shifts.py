from datetime import date, datetime, time, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import SECRET_KEY
from app.database import Base, get_db
from app.main import app
from app.models.entities import Country, Courier, CourierType, DailyLog, Tenant, User, UserRole
from app.models.merchant import (
    BookingStatus,
    BranchDispatchOrder,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    ShiftAttendanceLog,
    ShiftType,
)
from app.utils.security import (
    create_branch_token,
    create_merchant_account_token,
    generate_merchant_api_key,
    hash_pin,
)
import jwt


# ─── Test Database & Fixtures ─────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///./test_phase2_e2e.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def ensure_db_override():
    app.dependency_overrides[get_db] = override_get_db
    yield


client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Clear prior Phase 2 data
    db.query(BranchDispatchOrder).delete()
    db.query(ShiftAttendanceLog).delete()
    db.query(DedicatedShiftBooking).delete()
    db.query(MerchantBranch).delete()
    db.query(MerchantAccount).delete()
    db.query(User).filter(User.phone.in_(["0500000099", "0500000100", "0500000101"])).delete()
    db.query(Courier).filter(Courier.id.in_([99, 100, 101])).delete()
    db.query(Tenant).filter(Tenant.id.in_([1, 2])).delete()
    db.commit()

    # 1. Logistics Tenant
    tenant = Tenant(
        id=1,
        name="Test 3PL Logistics",
        country=Country.SA,
        subscription_status="ACTIVE",
    )
    db.add(tenant)
    db.flush()

    # 2. Couriers (Riders)
    # Rider 99: dedicated branch rider
    rider99 = Courier(
        id=99,
        tenant_id=1,
        name="Ahmed Mansour",
        phone="0500000099",
        courier_type=CourierType.FREELANCER,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    # Rider 100: peer rider (Jeddah or nearby)
    rider100 = Courier(
        id=100,
        tenant_id=1,
        name="Tariq Al-Harbi",
        phone="0500000100",
        courier_type=CourierType.FREELANCER,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    # Rider 101: second claimer
    rider101 = Courier(
        id=101,
        tenant_id=1,
        name="Saeed Al-Zahrani",
        phone="0500000101",
        courier_type=CourierType.FREELANCER,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db.add_all([rider99, rider100, rider101])
    db.flush()

    # 3. Fleet OS Users linked to Riders
    user99 = User(
        id=99,
        phone="0500000099",
        name="Ahmed Mansour",
        password_hash="test",
        role=UserRole.COURIER,
        courier_id=99,
        tenant_id=1,
        is_active=True,
    )
    user100 = User(
        id=100,
        phone="0500000100",
        name="Tariq Al-Harbi",
        password_hash="test",
        role=UserRole.COURIER,
        courier_id=100,
        tenant_id=1,
        is_active=True,
    )
    user101 = User(
        id=101,
        phone="0500000101",
        name="Saeed Al-Zahrani",
        password_hash="test",
        role=UserRole.COURIER,
        courier_id=101,
        tenant_id=1,
        is_active=True,
    )
    db.add_all([user99, user100, user101])
    db.flush()

    # 4. MerchantAccount 1
    raw_key, prefix, hash_key = generate_merchant_api_key(custom_prefix="testprefix01")
    account1 = MerchantAccount(
        id=1,
        trade_name="Test Burger Co.",
        billing_contact_email="finance@testburger.sa",
        billing_contact_phone="0501112233",
        payment_terms_days=30,
        api_key_prefix=prefix,
        api_key_hash=hash_key,
        is_active=True,
    )
    # MerchantAccount 2 (for foreign branch test 7.4)
    raw_key2, prefix2, hash_key2 = generate_merchant_api_key(custom_prefix="testprefix02")
    account2 = MerchantAccount(
        id=2,
        trade_name="Other Pizza Co.",
        billing_contact_email="finance@otherpizza.sa",
        billing_contact_phone="0504445566",
        payment_terms_days=30,
        api_key_prefix=prefix2,
        api_key_hash=hash_key2,
        is_active=True,
    )
    db.add_all([account1, account2])
    db.flush()

    # 5. Merchant Branches
    # Branch 1: Has dedicated booking and checked in rider
    branch1 = MerchantBranch(
        id=1,
        merchant_account_id=1,
        branch_name="Olaya Main Branch",
        city="Riyadh",
        district="Al Olaya",
        latitude=Decimal("24.7136000"),
        longitude=Decimal("46.6753000"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("1234"),
        is_active=True,
    )
    # Branch 2: Under Account 1, but no rider checked in
    branch2 = MerchantBranch(
        id=2,
        merchant_account_id=1,
        branch_name="Malaz Branch",
        city="Riyadh",
        district="Al Malaz",
        latitude=Decimal("24.6600000"),
        longitude=Decimal("46.7200000"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("5678"),
        is_active=True,
    )
    # Branch 99: Under Account 2
    branch99 = MerchantBranch(
        id=99,
        merchant_account_id=2,
        branch_name="Foreign Pizza Branch",
        city="Riyadh",
        district="Al Nakheel",
        latitude=Decimal("24.7500000"),
        longitude=Decimal("46.6200000"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("9999"),
        is_active=True,
    )
    db.add_all([branch1, branch2, branch99])
    db.flush()

    # 6. Dedicated Shift Booking: Branch 1, Rider 99
    today = date.today()
    booking1 = DedicatedShiftBooking(
        id=1,
        merchant_branch_id=1,
        logistics_company_tenant_id=1,
        rider_id=99,
        shift_type=ShiftType.peak_3h,
        shift_start_time=time(19, 0),
        shift_end_time=time(22, 0),
        effective_from=today,
        effective_until=None,
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("5500.00"),
        dou_margin=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    db.add(booking1)
    db.commit()
    db.close()

    yield {
        "valid_api_key": raw_key,
        "valid_api_key2": raw_key2,
    }

    # Teardown
    Base.metadata.drop_all(bind=test_engine)


def make_rider_token(rider_id: int) -> str:
    payload = {
        "sub": str(rider_id),
        "courier_id": rider_id,
        "exp": int((datetime.now(timezone.utc)).timestamp()) + 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


# ─── BLOCK 1 — Authentication & Token Isolation ───────────────────────────────

def test_1_1_cashier_login_success():
    res = client.post("/merchant/auth/login", json={"branch_id": 1, "pin": "1234"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["branch_id"] == 1
    assert data["token_type"] == "bearer"
    assert data["branch_name"] == "Olaya Main Branch"


def test_1_2_cashier_login_wrong_pin():
    res = client.post("/merchant/auth/login", json={"branch_id": 1, "pin": "0000"})
    assert res.status_code == 401
    detail = res.json().get("detail", "").lower()
    assert "branch" not in detail
    assert "pin" not in detail


def test_1_3_branch_token_rejected_on_fleet_os():
    token = create_branch_token(1)
    headers = {"Authorization": f"Bearer {token}"}
    res = client.get("/fleet/riders", headers=headers)
    assert res.status_code == 403


def test_1_4_fleet_os_token_rejected_on_merchant():
    rider_token = make_rider_token(99)
    headers = {"Authorization": f"Bearer {rider_token}"}
    res = client.get("/merchant/branch/1/riders/active", headers=headers)
    assert res.status_code == 403


# ─── BLOCK 2 — Active Riders (pre-checkin) ────────────────────────────────────

def test_2_1_active_riders_pre_checkin():
    branch_token = create_branch_token(1)
    headers = {"Authorization": f"Bearer {branch_token}"}
    res = client.get("/merchant/branch/1/riders/active", headers=headers)
    assert res.status_code == 200
    riders = res.json()
    assert len(riders) > 0
    rider = riders[0]
    assert rider["checkin_status"] == "not_yet"
    assert "•••••• 0099" in rider["rider_phone_masked"]
    # Sensitive fields absent
    assert "iqama" not in rider
    assert "salary" not in rider
    assert "logistics_company" not in rider
    assert "nationality" not in rider


def test_2_2_dispatch_order_rejected_when_rider_not_checked_in():
    branch_token = create_branch_token(1)
    headers = {"Authorization": f"Bearer {branch_token}"}
    res = client.post(
        "/merchant/branch/1/orders",
        headers=headers,
        json={
            "customer_name": "Ahmed Al-Rashidi",
            "customer_phone": "0501234567",
            "delivery_address": "Prince Sultan Road, Villa 12, Riyadh",
        },
    )
    assert res.status_code == 409
    assert "No rider is checked in" in res.json().get("detail", "")


# ─── BLOCK 3 — Rider Check-In ─────────────────────────────────────────────────

def test_3_1_rider_checkin_within_geofence():
    rider_token = make_rider_token(99)
    headers = {"Authorization": f"Bearer {rider_token}"}
    res = client.post(
        "/driver/shifts/dedicated/1/checkin",
        headers=headers,
        json={"lat": 24.7136, "lng": 46.6753},  # Exact coords of Branch 1
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validated"] is True
    assert data["distance_meters"] <= 150
    assert "attendance_log_id" in data


def test_3_2_rider_checkin_idempotency():
    rider_token = make_rider_token(99)
    headers = {"Authorization": f"Bearer {rider_token}"}
    res1 = client.post(
        "/driver/shifts/dedicated/1/checkin",
        headers=headers,
        json={"lat": 24.7136, "lng": 46.6753},
    )
    res2 = client.post(
        "/driver/shifts/dedicated/1/checkin",
        headers=headers,
        json={"lat": 24.7136, "lng": 46.6753},
    )
    assert res1.json()["attendance_log_id"] == res2.json()["attendance_log_id"]


def test_3_3_active_riders_shows_checked_in_after_checkin():
    branch_token = create_branch_token(1)
    headers = {"Authorization": f"Bearer {branch_token}"}
    res = client.get("/merchant/branch/1/riders/active", headers=headers)
    assert res.status_code == 200
    riders = res.json()
    assert riders[0]["checkin_status"] == "checked_in"


# ─── BLOCK 4 & 5 — Order Dispatch & Transitions ───────────────────────────────

order_id_holder = {}


def test_4_1_cashier_dispatches_order_success():
    branch_token = create_branch_token(1)
    headers = {"Authorization": f"Bearer {branch_token}"}
    res = client.post(
        "/merchant/branch/1/orders",
        headers=headers,
        json={
            "customer_name": "Sara Al-Qahtani",
            "customer_phone": "0509876543",
            "delivery_address": "King Fahd Road, Apt 5B, Riyadh",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "order_id" in data
    assert data["status"] == "pending"
    assert data["assigned_rider_name"]
    order_id_holder["id"] = data["order_id"]


def test_4_2_active_orders_visible_to_cashier_and_rider():
    branch_token = create_branch_token(1)
    rider_token = make_rider_token(99)

    # Cashier sees it
    res1 = client.get("/merchant/branch/1/orders/active", headers={"Authorization": f"Bearer {branch_token}"})
    assert res1.status_code == 200
    found1 = any(o["order_id"] == order_id_holder["id"] for o in res1.json())
    assert found1 is True

    # Rider sees it
    res2 = client.get("/driver/orders/branch/active", headers={"Authorization": f"Bearer {rider_token}"})
    assert res2.status_code == 200
    found2 = any(o["order_id"] == order_id_holder["id"] for o in res2.json())
    assert found2 is True


def test_5_1_rider_status_transitions():
    rider_token = make_rider_token(99)
    oid = order_id_holder["id"]

    # 1. pending -> en_route
    res = client.patch(
        f"/driver/orders/{oid}/status",
        headers={"Authorization": f"Bearer {rider_token}"},
        json={"status": "en_route"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "en_route"
    assert res.json()["acknowledged_at"] is not None

    # 2. invalid backward: en_route -> pending (returns 422)
    res_inv = client.patch(
        f"/driver/orders/{oid}/status",
        headers={"Authorization": f"Bearer {rider_token}"},
        json={"status": "pending"},
    )
    assert res_inv.status_code == 422

    # 3. en_route -> delivered
    res_del = client.patch(
        f"/driver/orders/{oid}/status",
        headers={"Authorization": f"Bearer {rider_token}"},
        json={"status": "delivered"},
    )
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "delivered"
    assert res_del.json()["delivered_at"] is not None

    # 4. Verify DailyLog synchronization for 3PL payroll and reporting
    db = TestingSessionLocal()
    daily_log = (
        db.query(DailyLog)
        .filter(
            DailyLog.courier_id == 99,
            DailyLog.log_date == date.today(),
        )
        .first()
    )
    assert daily_log is not None
    assert daily_log.orders_count == 1
    assert daily_log.verified_orders == 1
    assert daily_log.driver_orders == 1
    assert daily_log.source_type == "DEDICATED_BRANCH_DISPATCH"
    db.close()


def test_5_2_delivered_order_removed_from_active():
    rider_token = make_rider_token(99)
    res = client.get("/driver/orders/branch/active", headers={"Authorization": f"Bearer {rider_token}"})
    assert res.status_code == 200
    found = any(o["order_id"] == order_id_holder["id"] for o in res.json())
    assert found is False


def test_5_3_other_rider_cannot_update_order():
    other_rider_token = make_rider_token(100)
    oid = order_id_holder["id"]
    res = client.patch(
        f"/driver/orders/{oid}/status",
        headers={"Authorization": f"Bearer {other_rider_token}"},
        json={"status": "en_route"},
    )
    assert res.status_code == 403


# ─── BLOCK 6 — Monthly Statement & Proration ──────────────────────────────────

def test_6_1_monthly_statement_proration():
    token = create_merchant_account_token(1)
    headers = {"Authorization": f"Bearer {token}"}
    today = date.today()
    res = client.get(
        f"/merchant/account/1/statement?month={today.month}&year={today.year}",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["merchant_name"] == "Test Burger Co."
    assert len(data["line_items"]) > 0
    item = data["line_items"][0]
    assert item["days_in_month"] >= 28
    assert item["prorated_fee"] > 0
    # Symmetrical margin check
    margin = data["gross_fee_charged_to_merchant"] - data["total_payout_to_logistics"]
    assert abs(data["dou_net_margin"] - margin) < 0.01


# ─── BLOCK 7 — POS Ingestion, Dual-Routing & Concurrency ──────────────────────

def test_7_1_pos_ingestion_auth_and_dual_routing(setup_database, monkeypatch):
    key = setup_database["valid_api_key"]

    # 7.1: Missing key -> 422
    r_miss = client.post(
        "/merchant/api/v1/orders",
        json={
            "branch_id": 1,
            "external_order_id": "POS-001",
            "customer_name": "Test",
            "customer_phone": "055",
            "delivery_address_text": "Addr",
        },
    )
    assert r_miss.status_code == 422

    # 7.2: Invalid key -> 401
    r_bad = client.post(
        "/merchant/api/v1/orders",
        headers={"X-Merchant-Key": "dou_live_badprefix00_invalidsecret123456789012345678901234"},
        json={
            "branch_id": 1,
            "external_order_id": "POS-002",
            "customer_name": "Test",
            "customer_phone": "055",
            "delivery_address_text": "Addr",
        },
    )
    assert r_bad.status_code == 401

    # 7.3: Foreign branch -> 403
    r_foreign = client.post(
        "/merchant/api/v1/orders",
        headers={"X-Merchant-Key": key},
        json={
            "branch_id": 99,  # Branch 99 belongs to Account 2
            "external_order_id": "POS-003",
            "customer_name": "Test",
            "customer_phone": "055",
            "delivery_address_text": "Addr",
        },
    )
    assert r_foreign.status_code == 403

    # 7.4: Route A (Branch 1 has checked-in rider 99 with 0 active orders)
    r_route_a = client.post(
        "/merchant/api/v1/orders",
        headers={"X-Merchant-Key": key},
        json={
            "branch_id": 1,
            "external_order_id": "POS-ROUTE-A-1",
            "customer_name": "Noura Al-Dosari",
            "customer_phone": "0509998877",
            "delivery_address_text": "Prince Turki St, Riyadh",
        },
    )
    assert r_route_a.status_code == 200
    data_a = r_route_a.json()
    assert data_a["routing"] == "dedicated"
    assert data_a["assigned_rider_name"] is not None

    # 7.5: Idempotency (same external_order_id on same branch returns same order_id)
    r_idem = client.post(
        "/merchant/api/v1/orders",
        headers={"X-Merchant-Key": key},
        json={
            "branch_id": 1,
            "external_order_id": "POS-ROUTE-A-1",
            "customer_name": "Noura Al-Dosari",
            "customer_phone": "0509998877",
            "delivery_address_text": "Prince Turki St, Riyadh",
        },
    )
    assert r_idem.status_code == 200
    assert r_idem.json()["order_id"] == data_a["order_id"]

    # 7.6: Open pool is DISABLED by default (ENABLE_OPEN_POOL=false)
    # When Branch 2 has no rider, POS ingestion must reject with 409
    r_route_b_disabled = client.post(
        "/merchant/api/v1/orders",
        headers={"X-Merchant-Key": key},
        json={
            "branch_id": 2,
            "external_order_id": "POS-ROUTE-B-DISABLED",
            "customer_name": "Mohammed Al-Otaibi",
            "customer_phone": "0533445566",
            "delivery_address_text": "Sitteen St, Riyadh",
        },
    )
    assert r_route_b_disabled.status_code == 409
    assert "No dedicated rider is available" in r_route_b_disabled.json()["detail"]

    # Pool queries and claim endpoints must return 403 Forbidden
    rider100_token = make_rider_token(100)
    r_pool_disabled = client.get(
        "/driver/orders/pool/available?lat=24.6600&lng=46.7200&radius_km=5",
        headers={"Authorization": f"Bearer {rider100_token}"},
    )
    assert r_pool_disabled.status_code == 403
    assert "Open pool is disabled" in r_pool_disabled.json()["detail"]

    r_claim_disabled = client.patch(
        "/driver/orders/999/claim",
        headers={"Authorization": f"Bearer {rider100_token}"},
    )
    assert r_claim_disabled.status_code == 403
    assert "Open pool is disabled" in r_claim_disabled.json()["detail"]

    # 7.7: When ENABLE_OPEN_POOL=True is explicitly enabled, Route B falls back to pool
    import app.routers.merchant as merchant_router
    import app.routers.driver_dedicated as driver_router

    monkeypatch.setattr(merchant_router, "ENABLE_OPEN_POOL", True)
    monkeypatch.setattr(driver_router, "ENABLE_OPEN_POOL", True)

    r_route_b = client.post(
        "/merchant/api/v1/orders",
        headers={"X-Merchant-Key": key},
        json={
            "branch_id": 2,
            "external_order_id": "POS-ROUTE-B-1",
            "customer_name": "Mohammed Al-Otaibi",
            "customer_phone": "0533445566",
            "delivery_address_text": "Sitteen St, Riyadh",
        },
    )
    assert r_route_b.status_code == 200
    data_b = r_route_b.json()
    assert data_b["routing"] == "pool"
    assert data_b["assigned_rider_name"] is None
    pool_order_id = data_b["order_id"]

    # Pool orders query by nearby rider (lat: 24.66, lng: 46.72)
    r_pool = client.get(
        "/driver/orders/pool/available?lat=24.6600&lng=46.7200&radius_km=5",
        headers={"Authorization": f"Bearer {rider100_token}"},
    )
    assert r_pool.status_code == 200
    orders = r_pool.json()
    assert any(o["order_id"] == pool_order_id for o in orders)

    # Far away rider (Jeddah: 21.38, 39.85) cannot see it
    r_far = client.get(
        "/driver/orders/pool/available?lat=21.3891&lng=39.8579&radius_km=5",
        headers={"Authorization": f"Bearer {rider100_token}"},
    )
    assert r_far.status_code == 200
    assert not any(o["order_id"] == pool_order_id for o in r_far.json())

    # Claim pool order
    r_claim = client.patch(
        f"/driver/orders/{pool_order_id}/claim",
        headers={"Authorization": f"Bearer {rider100_token}"},
    )
    assert r_claim.status_code == 200
    assert r_claim.json()["claimed_by_rider_id"] == 100

    # Second claim fails with 409 (already claimed)
    rider101_token = make_rider_token(101)
    r_claim_again = client.patch(
        f"/driver/orders/{pool_order_id}/claim",
        headers={"Authorization": f"Bearer {rider101_token}"},
    )
    assert r_claim_again.status_code == 409
    assert "already claimed" in r_claim_again.json()["detail"].lower()

