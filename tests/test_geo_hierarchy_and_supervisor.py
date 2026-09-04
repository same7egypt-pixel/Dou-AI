"""Tests for Phase 1: Geo hierarchy (city_id, country_id on branches) and supervisor on bookings."""
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
from app.models.entities import (
    Country,
    Courier,
    CourierType,
    GeoCity,
    GeoCountry,
    Tenant,
    User,
    UserRole,
)
from app.models.merchant import (
    BookingStatus,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    ShiftType,
)
from app.routers.auth import hash_password
from app.utils.security import hash_pin

TEST_DB_FILE = "./test_phase1_geo.db"
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def make_user_token(user_id: int, tenant_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "role": role,
        "ver": 0,
        "exp": int((datetime.now(timezone.utc)).timestamp()) + 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


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


def test_merchant_branch_geo_columns(db_session):
    country = GeoCountry(name="المملكة العربية السعودية", code="SA", flag="🇸🇦", active=True)
    db_session.add(country)
    db_session.flush()

    city = GeoCity(country_id=country.id, name="الرياض", active=True)
    db_session.add(city)
    db_session.flush()

    account = MerchantAccount(
        trade_name="مطعم البرجر",
        billing_contact_email="burger@test.com",
        billing_contact_phone="0501111111",
        api_key_prefix="dou_m_test",
        api_key_hash="hash",
    )
    db_session.add(account)
    db_session.flush()

    branch = MerchantBranch(
        merchant_account_id=account.id,
        branch_name="فرع العليا",
        city="الرياض",
        city_id=city.id,
        country_id=country.id,
        district="العليا",
        latitude=Decimal("24.7136000"),
        longitude=Decimal("46.6753000"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("1234"),
    )
    db_session.add(branch)
    db_session.commit()
    db_session.refresh(branch)

    assert branch.city_id == city.id
    assert branch.country_id == country.id
    assert branch.geo_city.name == "الرياض"
    assert branch.geo_country.code == "SA"


def test_dedicated_shift_booking_supervisor_column(db_session):
    tenant = Tenant(name="شركة التوصيل السريع", country=Country.SA, monthly_fee=1000)
    db_session.add(tenant)
    db_session.flush()

    supervisor = User(
        name="أحمد المشرف",
        phone="0509998877",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SUPERVISOR,
        tenant_id=tenant.id,
    )
    db_session.add(supervisor)
    db_session.flush()

    courier = Courier(
        tenant_id=tenant.id,
        name="خالد المندوب",
        phone="0503332211",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
    )
    db_session.add(courier)
    db_session.flush()

    branch = db_session.query(MerchantBranch).first()

    booking = DedicatedShiftBooking(
        merchant_branch_id=branch.id,
        logistics_company_tenant_id=tenant.id,
        rider_id=courier.id,
        supervisor_id=supervisor.id,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(12, 0),
        shift_end_time=time(20, 0),
        effective_from=date.today(),
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("5500.00"),
        dou_margin=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    db_session.add(booking)
    db_session.commit()
    db_session.refresh(booking)

    assert booking.supervisor_id == supervisor.id
    assert booking.supervisor.name == "أحمد المشرف"


def test_admin_api_branch_and_booking_with_geo_and_supervisor(client, db_session):
    admin_user = User(
        name="سوبر أدمن",
        phone="0500001122",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.DOU_ADMIN,
    )
    db_session.add(admin_user)
    db_session.commit()
    token = make_user_token(admin_user.id, 1, "DOU_ADMIN")
    headers = {"Authorization": f"Bearer {token}"}

    account = db_session.query(MerchantAccount).first()
    city = db_session.query(GeoCity).first()

    # Create branch with city_id via API
    res = client.post(
        f"/admin/dedicated/merchants/{account.id}/branches",
        headers=headers,
        json={
            "branch_name": "فرع النخيل",
            "city_id": city.id,
            "district": "النخيل",
            "latitude": 24.7500,
            "longitude": 46.6500,
            "geofence_radius_meters": 150,
            "cashier_pin": "5566",
        },
    )
    assert res.status_code == 201
    branch_id = res.json()["branch_id"]

    created_branch = db_session.get(MerchantBranch, branch_id)
    assert created_branch.city_id == city.id
    assert created_branch.country_id == city.country_id

    # 1. Activate operating city for tenant
    from app.models.entities import TenantOperatingCity
    tenant = db_session.query(Tenant).first()
    op_city = TenantOperatingCity(tenant_id=tenant.id, geo_city_id=city.id, is_active=True)
    db_session.add(op_city)
    db_session.commit()

    courier = db_session.query(Courier).first()
    supervisor = db_session.query(User).filter(User.role == UserRole.SUPERVISOR).first()

    # 2. Create valid booking with supervisor_id via API
    booking_res = client.post(
        "/admin/dedicated/bookings",
        headers=headers,
        json={
            "merchant_branch_id": branch_id,
            "logistics_company_tenant_id": tenant.id,
            "rider_id": courier.id,
            "supervisor_id": supervisor.id,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
        },
    )
    assert booking_res.status_code == 201

    # Check list bookings in admin
    list_res = client.get("/admin/dedicated/bookings", headers=headers)
    assert list_res.status_code == 200
    bookings = list_res.json()
    new_b = next(b for b in bookings if b["branch_id"] == branch_id)
    assert new_b["supervisor_id"] == supervisor.id
    assert new_b["supervisor_name"] == supervisor.name

    # Check list bookings in fleet
    fleet_token = make_user_token(supervisor.id, tenant.id, "COMPANY")
    fleet_headers = {"Authorization": f"Bearer {fleet_token}"}
    fleet_res = client.get("/fleet/dedicated/bookings", headers=fleet_headers)
    assert fleet_res.status_code == 200
    fleet_bookings = fleet_res.json()
    target_fb = next(b for b in fleet_bookings if b["branch_name"] == "فرع النخيل")
    assert target_fb["supervisor_id"] == supervisor.id
    assert target_fb["supervisor_name"] == supervisor.name


def test_booking_rejected_when_tenant_does_not_serve_city(client, db_session):
    """Rule 1: Booking is rejected if tenant has no active TenantOperatingCity in branch city."""
    admin_user = db_session.query(User).filter(User.role == UserRole.DOU_ADMIN).first()
    token = make_user_token(admin_user.id, 1, "DOU_ADMIN")
    headers = {"Authorization": f"Bearer {token}"}

    account = db_session.query(MerchantAccount).first()
    country = db_session.query(GeoCountry).first()

    # Create Jeddah city
    jeddah = GeoCity(name="جدة", country_id=country.id, active=True)
    db_session.add(jeddah)
    db_session.commit()

    # Create branch in Jeddah
    branch = MerchantBranch(
        merchant_account_id=account.id,
        branch_name="فرع التحلية - جدة",
        city="جدة",
        city_id=jeddah.id,
        country_id=country.id,
        latitude=Decimal("21.5433"),
        longitude=Decimal("39.1728"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("7788"),
    )
    db_session.add(branch)
    db_session.commit()

    tenant = db_session.query(Tenant).first()
    courier = db_session.query(Courier).filter(Courier.tenant_id == tenant.id).first()

    # Attempt to book: tenant does NOT have Jeddah in active TenantOperatingCity
    res = client.post(
        "/admin/dedicated/bookings",
        headers=headers,
        json={
            "merchant_branch_id": branch.id,
            "logistics_company_tenant_id": tenant.id,
            "rider_id": courier.id,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
        },
    )
    assert res.status_code == 400
    assert "الشركة اللوجستية لا تخدم مدينة هذا الفرع" in res.json()["detail"]


def test_booking_rejected_when_supervisor_from_another_tenant(client, db_session):
    """Rule 2: Supervisor from another tenant must be rejected with 403 Forbidden (cross-tenant leak)."""
    admin_user = db_session.query(User).filter(User.role == UserRole.DOU_ADMIN).first()
    token = make_user_token(admin_user.id, 1, "DOU_ADMIN")
    headers = {"Authorization": f"Bearer {token}"}

    # Create Rival Tenant
    rival_tenant = Tenant(name="شركة منافسة", country=Country.SA, monthly_fee=1000)
    db_session.add(rival_tenant)
    db_session.commit()

    rival_supervisor = User(
        name="مشرف منافس",
        phone="0504445566",
        password_hash=hash_password("Pass123!"),
        role=UserRole.SUPERVISOR,
        tenant_id=rival_tenant.id,
    )
    db_session.add(rival_supervisor)
    db_session.commit()

    tenant = db_session.query(Tenant).filter(Tenant.id != rival_tenant.id).first()
    branch = db_session.query(MerchantBranch).filter(MerchantBranch.branch_name == "فرع النخيل").first()
    courier = db_session.query(Courier).filter(Courier.tenant_id == tenant.id).first()

    # Attempt booking with rival supervisor
    res = client.post(
        "/admin/dedicated/bookings",
        headers=headers,
        json={
            "merchant_branch_id": branch.id,
            "logistics_company_tenant_id": tenant.id,
            "rider_id": courier.id,
            "supervisor_id": rival_supervisor.id,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
        },
    )
    assert res.status_code == 403
    assert "لا ينتمي إلى هذه الشركة اللوجستية" in res.json()["detail"]


def test_booking_rejected_when_user_is_not_supervisor(client, db_session):
    """Rule 2: User without SUPERVISOR role cannot be assigned as supervisor."""
    admin_user = db_session.query(User).filter(User.role == UserRole.DOU_ADMIN).first()
    token = make_user_token(admin_user.id, 1, "DOU_ADMIN")
    headers = {"Authorization": f"Bearer {token}"}

    tenant = db_session.query(Tenant).first()
    branch = db_session.query(MerchantBranch).filter(MerchantBranch.branch_name == "فرع النخيل").first()
    courier = db_session.query(Courier).filter(Courier.tenant_id == tenant.id).first()

    # Create user with COMPANY role (not SUPERVISOR)
    regular_user = User(
        name="موظف عادي",
        phone="0507778899",
        password_hash=hash_password("Pass123!"),
        role=UserRole.COMPANY,
        tenant_id=tenant.id,
    )
    db_session.add(regular_user)
    db_session.commit()

    res = client.post(
        "/admin/dedicated/bookings",
        headers=headers,
        json={
            "merchant_branch_id": branch.id,
            "logistics_company_tenant_id": tenant.id,
            "rider_id": courier.id,
            "supervisor_id": regular_user.id,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
        },
    )
    assert res.status_code == 400
    assert "ليس له صلاحية مشرف" in res.json()["detail"]


def test_migration_backfill_resolves_sulimaniyah_riyadh():
    """Verify migration 20260904_0028 backfill resolves legacy branch with city='الرياض'."""
    from alembic.config import Config
    from alembic import command
    import tempfile
    import sqlite3

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        conn = sqlite3.connect(temp_db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE geo_countries (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                code VARCHAR(10) NOT NULL,
                flag VARCHAR(10),
                active BOOLEAN DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE geo_cities (
                id INTEGER PRIMARY KEY,
                country_id INTEGER NOT NULL REFERENCES geo_countries(id),
                name VARCHAR(100) NOT NULL,
                active BOOLEAN DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE tenants (
                id INTEGER PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                country VARCHAR(10) DEFAULT 'SA'
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                tenant_id INTEGER REFERENCES tenants(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE merchant_accounts (
                id INTEGER PRIMARY KEY,
                trade_name VARCHAR(255) NOT NULL,
                billing_contact_email VARCHAR(255),
                billing_contact_phone VARCHAR(20),
                payment_terms_days INTEGER DEFAULT 30,
                is_active BOOLEAN DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE merchant_branches (
                id INTEGER PRIMARY KEY,
                merchant_account_id INTEGER NOT NULL REFERENCES merchant_accounts(id),
                branch_name VARCHAR(255) NOT NULL,
                city VARCHAR(100) NOT NULL,
                district VARCHAR(100),
                latitude NUMERIC(10, 7) NOT NULL,
                longitude NUMERIC(10, 7) NOT NULL,
                geofence_radius_meters INTEGER DEFAULT 150,
                cashier_access_pin VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE dedicated_shift_bookings (
                id INTEGER PRIMARY KEY,
                merchant_branch_id INTEGER NOT NULL REFERENCES merchant_branches(id),
                logistics_company_tenant_id INTEGER NOT NULL REFERENCES tenants(id),
                rider_id INTEGER NOT NULL,
                monthly_fee_to_merchant NUMERIC(10, 2) NOT NULL,
                monthly_payout_to_logistics NUMERIC(10, 2) NOT NULL,
                dou_margin NUMERIC(10, 2) NOT NULL
            )
            """
        )
        # Pre-seed Saudi Arabia and Riyadh
        cur.execute("INSERT INTO geo_countries (id, name, code, active) VALUES (1, 'Saudi Arabia', 'SA', 1)")
        cur.execute("INSERT INTO geo_cities (id, country_id, name, active) VALUES (1, 1, 'الرياض', 1)")
        cur.execute("INSERT INTO tenants (id, name, country) VALUES (1, 'FastFleet', 'SA')")

        # Insert legacy merchant branch with city="الرياض"
        cur.execute(
            """
            INSERT INTO merchant_accounts (id, trade_name, billing_contact_email, billing_contact_phone, payment_terms_days, is_active)
            VALUES (1, 'مطعم الرياض', 'billing@riyadh.sa', '0500000000', 30, 1)
            """
        )
        cur.execute(
            """
            INSERT INTO merchant_branches (id, merchant_account_id, branch_name, city, latitude, longitude, geofence_radius_meters, cashier_access_pin, is_active)
            VALUES (1, 1, 'فرع السليمانية - الرياض', 'الرياض', 24.7085, 46.6970, 150, 'hash', 1)
            """
        )
        conn.commit()
        conn.close()

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{temp_db_path}")

        # Stamp 0027 so alembic knows current state
        command.stamp(alembic_cfg, "20260904_0027")

        # Upgrade to 20260904_0028
        command.upgrade(alembic_cfg, "20260904_0028")

        # Check that city_id and country_id were resolved and are NOT NULL
        conn = sqlite3.connect(temp_db_path)
        cur = conn.cursor()
        cur.execute("SELECT branch_name, city, city_id, country_id FROM merchant_branches WHERE id = 1")
        row = cur.fetchone()
        assert row is not None
        branch_name, city_name, city_id, country_id = row
        assert branch_name == "فرع السليمانية - الرياض"
        assert city_id == 1
        assert country_id == 1

        # Verify downgrade cleans up cleanly
        command.downgrade(alembic_cfg, "20260904_0027")
        cur.execute("PRAGMA table_info(merchant_branches)")
        columns = [c[1] for c in cur.fetchall()]
        assert "city_id" not in columns
        assert "country_id" not in columns
        conn.close()
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
