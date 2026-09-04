from datetime import date, datetime, time, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import ADMIN_KEY, SECRET_KEY
from app.database import Base, get_db
from app.main import app
from app.models.entities import Country, Courier, CourierType, Tenant, User, UserRole
from app.models.merchant import (
    BookingStatus,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    ShiftAttendanceLog,
    ShiftType,
)
from app.utils.security import generate_merchant_api_key, hash_pin
import jwt

# ─── Test Database & Fixtures ─────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///./test_phase4_fleet_admin.db"
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


def make_user_token(user_id: int, tenant_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "role": role,
        "ver": 0,
        "exp": int((datetime.now(timezone.utc)).timestamp()) + 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


@pytest.fixture(scope="module", autouse=True)
def setup_phase4_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Clear prior data
    db.query(ShiftAttendanceLog).delete()
    db.query(DedicatedShiftBooking).delete()
    db.query(MerchantBranch).delete()
    db.query(MerchantAccount).delete()
    db.query(User).filter(User.id.in_([201, 202, 299])).delete()
    db.query(Courier).filter(Courier.id.in_([301, 302, 303])).delete()
    db.query(Tenant).filter(Tenant.id.in_([10, 20])).delete()
    db.commit()

    # 1. Tenants: Tenant 10 (FastFleet), Tenant 20 (RivalLogistics)
    t1 = Tenant(id=10, name="FastFleet Logistics", country=Country.SA, subscription_status="ACTIVE")
    t2 = Tenant(id=20, name="Rival Logistics", country=Country.SA, subscription_status="ACTIVE")
    db.add_all([t1, t2])
    db.flush()

    # 2. Couriers:
    # 301, 302 in Tenant 10
    c1 = Courier(id=301, tenant_id=10, name="Ali Salem", phone="0550000301", courier_type=CourierType.FREELANCER, country=Country.SA, employment_status="ACTIVE")
    c2 = Courier(id=302, tenant_id=10, name="Khaled Fahad", phone="0550000302", courier_type=CourierType.FREELANCER, country=Country.SA, employment_status="ACTIVE")
    # 303 in Tenant 20
    c3 = Courier(id=303, tenant_id=20, name="Omar Rival", phone="0550000303", courier_type=CourierType.FREELANCER, country=Country.SA, employment_status="ACTIVE")
    db.add_all([c1, c2, c3])
    db.flush()

    # 3. Users:
    # User 201: Fleet Manager for Tenant 10
    u1 = User(id=201, phone="0550000201", name="Manager FastFleet", password_hash="test", role=UserRole.COMPANY, tenant_id=10, is_active=True, token_version=0)
    # User 202: Fleet Manager for Tenant 20
    u2 = User(id=202, phone="0550000202", name="Manager Rival", password_hash="test", role=UserRole.COMPANY, tenant_id=20, is_active=True, token_version=0)
    # User 299: DOU Super Admin
    u_admin = User(id=299, phone="0550000299", name="DOU Super Admin", password_hash="test", role=UserRole.DOU_ADMIN, tenant_id=None, is_active=True, token_version=0)
    db.add_all([u1, u2, u_admin])
    db.flush()

    # 4. Merchant Account & Branch
    raw_key, prefix, hash_key = generate_merchant_api_key("shawarmatest")
    merchant = MerchantAccount(
        id=10,
        trade_name="Shawarma Supreme",
        billing_contact_email="pilot@supreme.sa",
        billing_contact_phone="0551112233",
        payment_terms_days=30,
        api_key_prefix=prefix,
        api_key_hash=hash_key,
        is_active=True,
    )
    db.add(merchant)
    db.flush()

    branch = MerchantBranch(
        id=10,
        merchant_account_id=10,
        branch_name="Sulimaniyah Branch",
        city="Riyadh",
        district="Sulimaniyah",
        latitude=Decimal("24.7085000"),
        longitude=Decimal("46.6970000"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("2026"),
        is_active=True,
    )
    db.add(branch)
    db.flush()

    # 5. Dedicated Booking: Tenant 10 assigned, rider 301
    today = date.today()
    booking = DedicatedShiftBooking(
        id=10,
        merchant_branch_id=10,
        logistics_company_tenant_id=10,
        rider_id=301,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(12, 0),
        shift_end_time=time(20, 0),
        effective_from=today,
        contract_value_monthly=Decimal("7000.00"),
        dou_commission_monthly=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    db.add(booking)
    db.commit()
    db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)


# ─── TESTS: Fleet Dedicated Endpoints ─────────────────────────────────────────

def test_fleet_bookings_tenant_isolation_and_commercial_privacy():
    """Fleet company can only view their bookings with contract value and DOU commission."""
    token_t10 = make_user_token(201, 10, "COMPANY")
    res = client.get("/fleet/dedicated/bookings", headers={"Authorization": f"Bearer {token_t10}"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    item = data[0]
    assert item["id"] == 10
    assert item["branch_name"] == "Sulimaniyah Branch"
    assert item["contract_value_monthly"] == 7000.0
    assert item["dou_commission_monthly"] == 1500.0
    # Commercial privacy: legacy fields not exposed
    assert "monthly_fee_to_merchant" not in item
    assert "dou_margin" not in item
    assert item["rider"]["rider_name"] == "Ali Salem"

    # Tenant 20 (Rival) must see 0 bookings
    token_t20 = make_user_token(202, 20, "COMPANY")
    res2 = client.get("/fleet/dedicated/bookings", headers={"Authorization": f"Bearer {token_t20}"})
    assert res2.status_code == 200
    assert len(res2.json()) == 0


def test_fleet_eligible_riders_scoped_to_tenant():
    """Fleet manager only sees their own active riders."""
    token_t10 = make_user_token(201, 10, "COMPANY")
    res = client.get("/fleet/dedicated/eligible-riders", headers={"Authorization": f"Bearer {token_t10}"})
    assert res.status_code == 200
    riders = res.json()
    ids = [r["id"] for r in riders]
    assert 301 in ids
    assert 302 in ids
    assert 303 not in ids  # Rider 303 belongs to Tenant 20


def test_fleet_assign_rider_cross_tenant_forbidden():
    """Fleet manager cannot assign a rider belonging to another tenant or to another tenant's booking."""
    token_t10 = make_user_token(201, 10, "COMPANY")

    # Try assigning Rider 303 (Tenant 20) to Booking 10 (Tenant 10) -> Must fail 400
    res = client.post(
        "/fleet/dedicated/bookings/10/assign-rider",
        json={"rider_id": 303},
        headers={"Authorization": f"Bearer {token_t10}"},
    )
    assert res.status_code == 400
    assert "غير مسجل" in res.json()["detail"] or "لا يتبع" in res.json()["detail"] or "does not belong" in res.json()["detail"].lower()

    # Successful assignment of Rider 302 (same tenant)
    res_ok = client.post(
        "/fleet/dedicated/bookings/10/assign-rider",
        json={"rider_id": 302},
        headers={"Authorization": f"Bearer {token_t10}"},
    )
    assert res_ok.status_code in (200, 201)
    assert res_ok.json()["success"] is True
    assert res_ok.json()["rider_name"] == "Khaled Fahad"


def test_fleet_monthly_settlement_calculation():
    """Fleet settlement calculates DOU SaaS commission statement."""
    token_t10 = make_user_token(201, 10, "COMPANY")
    res = client.get("/fleet/dedicated/settlement?month=9&year=2026", headers={"Authorization": f"Bearer {token_t10}"})
    assert res.status_code == 200
    data = res.json()
    assert data["tenant_name"] == "FastFleet Logistics"
    assert data["total_commission_due"] > 0
    assert "dou_margin" not in data
    assert len(data["line_items"]) == 1
    assert data["line_items"][0]["contract_value_monthly"] == 7000.0
    assert data["line_items"][0]["dou_commission_monthly"] == 1500.0


# ─── TESTS: Super Admin Endpoints ─────────────────────────────────────────────

def test_admin_metrics_and_margin_calculations():
    """Super admin sees total contracts volume and total DOU commissions."""
    admin_token = make_user_token(299, 1, "DOU_ADMIN")
    res = client.get("/admin/dedicated/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    m = res.json()
    assert m["total_bookings"] >= 1
    assert m["active_bookings"] >= 1
    assert m["total_contracts_volume"] == 7000.0
    assert m["total_dou_commissions"] == 1500.0


def test_admin_create_booking_auto_margin():
    """Super admin creates new contract with contract value and fixed DOU commission."""
    admin_token = make_user_token(299, 1, "DOU_ADMIN")
    payload = {
        "merchant_id": 10,
        "branch_id": 10,
        "tenant_id": 20,
        "rider_id": 303,
        "shift_type": "peak_3h",
        "contract_value_monthly": 3500.0,
        "dou_commission_monthly": 1000.0,
        "start_date": "2026-09-01",
    }
    res = client.post("/admin/dedicated/bookings", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code in (200, 201)
    created = res.json()
    assert created["contract_value_monthly"] == 3500.0
    assert created["dou_commission_monthly"] == 1000.0


def test_admin_onboard_merchant_and_branch():
    """Super admin creates a merchant chain and branch with GPS geofence."""
    admin_token = make_user_token(299, 1, "DOU_ADMIN")

    # 1. Create Merchant
    m_res = client.post(
        "/admin/dedicated/merchants",
        json={
            "name": "Burger Spot Chain",
            "commercial_reg": "1010998877",
            "contact_phone": "0501239999",
            "contact_email": "ops@burgerspot.sa",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert m_res.status_code in (200, 201)
    merchant_data = m_res.json()
    assert merchant_data["trade_name"] == "Burger Spot Chain"
    assert merchant_data["api_key"].startswith("dou_live_")
    m_id = merchant_data["id"]

    # 2. Add Branch with Geofence
    b_res = client.post(
        f"/admin/dedicated/merchants/{m_id}/branches",
        json={
            "name": "Olaya Branch",
            "latitude": 24.7136,
            "longitude": 46.6753,
            "geofence_radius_meters": 150,
            "cashier_pin": "2026",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert b_res.status_code in (200, 201)
    branch_data = b_res.json()
    assert branch_data["branch_name"] == "Olaya Branch"
    assert branch_data["geofence_radius_meters"] == 150


def test_admin_endpoints_reject_unauthorized():
    """Ordinary company user cannot access admin dedicated endpoints."""
    token_t10 = make_user_token(201, 10, "COMPANY")
    res = client.get("/admin/dedicated/metrics", headers={"Authorization": f"Bearer {token_t10}"})
    assert res.status_code in (401, 403)
