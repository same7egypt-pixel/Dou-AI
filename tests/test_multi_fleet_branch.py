"""Tests for Phase 1: Multi-fleet branch capacity in DOU Fleet OS.

Guards the eight requirements of Phase 1:
1. Two contracts with two different tenants created on the same branch without rejection.
2. Admin branch listing returns both fleets with individual seats breakdown (3 and 3, not single 6).
3. Cashier rider cards report correct logistics_company_name for riders and vacant seats.
4. Merchant statement aggregates by branch -> fleet with exact matching subtotals and identical grand total.
5. Monthly settlements generate separate statement ledgers for each fleet with correct sums.
6. Fleet (A) query returns 0 rows belonging to Fleet (B) on the shared branch (P0 tenant isolation).
7. Fleet without operating city license is rejected while licensed fleet group succeeds.
8. Vacant seat from Fleet (A) does not diminish or affect payouts of Fleet (B).
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
from app.models.entities import (
    Country,
    Courier,
    CourierType,
    GeoCity,
    GeoCountry,
    Tenant,
    TenantOperatingCity,
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
from app.routers.auth import create_token
from app.utils.finance import prorate
from app.utils.security import (
    create_branch_token,
    create_merchant_account_token,
    hash_pin,
)

TEST_DB_FILE = "./test_multi_fleet_branch.db"
engine = create_engine(
    f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

TARGET_MONTH = date(2026, 8, 1)
MONTH_STR = "2026-08"
DAYS_IN_MONTH = calendar.monthrange(TARGET_MONTH.year, TARGET_MONTH.month)[1]


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

    # Seed Admin User
    db = TestingSessionLocal()
    admin_user = User(
        id=9001,
        tenant_id=1,
        name="Super Admin",
        phone="+966500009001",
        password_hash="testhash",
        role=UserRole.DOU_ADMIN,
        country=Country.SA,
        is_active=True,
        token_version=0,
    )
    db.merge(admin_user)
    db.commit()
    db.close()

    yield

    app.dependency_overrides.pop(get_db, None)
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


def make_admin_token() -> str:
    with TestingSessionLocal() as db:
        user = db.get(User, 9001)
        return create_token(user)


def make_fleet_token(user_id: int, tenant_id: int = 0) -> str:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        return create_token(user)


def _seed_branch_and_fleets(db, prefix_id: int = 8100):
    """Sets up a shared branch in Riyadh with two licensed fleets (Tenant A & Tenant B)

    and one unlicensed fleet (Tenant C).
    """
    # 1. Geo setup
    geo_country = db.query(GeoCountry).filter(GeoCountry.code == "SA").first()
    if not geo_country:
        geo_country = GeoCountry(id=prefix_id + 1, code="SA", name="المملكة العربية السعودية", flag="🇸🇦")
        db.add(geo_country)
        db.commit()

    geo_city = db.query(GeoCity).filter(GeoCity.name == "الرياض").first()
    if not geo_city:
        geo_city = GeoCity(id=prefix_id + 2, country_id=geo_country.id, name="الرياض")
        db.add(geo_city)
        db.commit()

    # 2. Tenants
    tenant_a = Tenant(
        id=prefix_id + 10,
        name=f"أسطول النقل السريع {prefix_id}",
        country=Country.SA,
        subscription_status="ACTIVE",
    )
    tenant_b = Tenant(
        id=prefix_id + 20,
        name=f"أسطول إكسبرس الفهد {prefix_id}",
        country=Country.SA,
        subscription_status="ACTIVE",
    )
    tenant_c = Tenant(
        id=prefix_id + 30,
        name=f"أسطول غير مرخص {prefix_id}",
        country=Country.SA,
        subscription_status="ACTIVE",
    )
    db.merge(tenant_a)
    db.merge(tenant_b)
    db.merge(tenant_c)
    db.commit()

    # 3. License Tenant A and Tenant B in Riyadh
    op_a = TenantOperatingCity(tenant_id=tenant_a.id, geo_city_id=geo_city.id, is_active=True)
    op_b = TenantOperatingCity(tenant_id=tenant_b.id, geo_city_id=geo_city.id, is_active=True)
    db.merge(op_a)
    db.merge(op_b)
    db.commit()

    # 4. Fleet Users
    user_a = User(
        id=prefix_id + 11,
        tenant_id=tenant_a.id,
        name=f"مدير أسطول أ {prefix_id}",
        phone=f"+96650{prefix_id}11",
        password_hash="hash",
        role=UserRole.COMPANY,
        country=Country.SA,
        is_active=True,
    )
    user_b = User(
        id=prefix_id + 21,
        tenant_id=tenant_b.id,
        name=f"مدير أسطول ب {prefix_id}",
        phone=f"+96650{prefix_id}21",
        password_hash="hash",
        role=UserRole.COMPANY,
        country=Country.SA,
        is_active=True,
    )
    db.merge(user_a)
    db.merge(user_b)
    db.commit()

    # 5. Merchant Account and Branch
    account = MerchantAccount(
        id=prefix_id + 50,
        trade_name=f"سلسلة برجر كلاسيك {prefix_id}",
        billing_contact_email=f"billing_{prefix_id}@burger.sa",
        billing_contact_phone=f"+96650{prefix_id}50",
        is_active=True,
    )
    db.merge(account)
    db.commit()

    branch = MerchantBranch(
        id=prefix_id + 60,
        merchant_account_id=account.id,
        branch_name=f"فرع السليمانية - الرياض {prefix_id}",
        city="الرياض",
        city_id=geo_city.id,
        country_id=geo_country.id,
        district="السليمانية",
        latitude=Decimal("24.7085000"),
        longitude=Decimal("46.6970000"),
        geofence_radius_meters=200,
        cashier_access_pin=hash_pin("2026"),
        is_active=True,
    )
    db.merge(branch)
    db.commit()

    return {
        "geo_city": geo_city,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "tenant_c": tenant_c,
        "user_a": user_a,
        "user_b": user_b,
        "account": account,
        "branch": branch,
    }


# ─── Test 1: Two contracts with two different tenants on same branch ───────────

def test_two_contracts_with_different_tenants_on_same_branch(client, db_session):
    """Test 1: Admin can create bookings for two different tenants on the same branch without rejection."""
    data = _seed_branch_and_fleets(db_session, prefix_id=8100)
    admin_token = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Contract 1: Tenant A (3 seats)
    payload_a = {
        "merchant_branch_id": data["branch"].id,
        "logistics_company_tenant_id": data["tenant_a"].id,
        "seats_count": 3,
        "shift_type": "full_day_8h",
        "monthly_fee_to_merchant": 7000.0,
        "monthly_payout_to_logistics": 5500.0,
        "start_date": str(TARGET_MONTH),
    }
    res_a = client.post("/admin/dedicated/bookings", json=payload_a, headers=headers)
    assert res_a.status_code == 201, f"Tenant A contract creation failed: {res_a.text}"
    body_a = res_a.json()
    assert body_a["ok"] is True
    assert body_a["created_count"] == 3

    # Contract 2: Tenant B (3 seats on the EXACT SAME BRANCH)
    payload_b = {
        "merchant_branch_id": data["branch"].id,
        "logistics_company_tenant_id": data["tenant_b"].id,
        "seats_count": 3,
        "shift_type": "full_day_8h",
        "monthly_fee_to_merchant": 7000.0,
        "monthly_payout_to_logistics": 5500.0,
        "start_date": str(TARGET_MONTH),
    }
    res_b = client.post("/admin/dedicated/bookings", json=payload_b, headers=headers)
    assert res_b.status_code == 201, f"Tenant B contract creation on same branch failed: {res_b.text}"
    body_b = res_b.json()
    assert body_b["ok"] is True
    assert body_b["created_count"] == 3

    # Total active bookings on this branch in DB is 6
    count = (
        db_session.query(DedicatedShiftBooking)
        .filter(
            DedicatedShiftBooking.merchant_branch_id == data["branch"].id,
            DedicatedShiftBooking.status == BookingStatus.active,
        )
        .count()
    )
    assert count == 6


# ─── Test 2: Admin branch listing returns both fleets breakdown ────────────────

def test_admin_branch_listing_returns_both_fleets_breakdown(client, db_session):
    """Test 2: GET /admin/dedicated/merchants returns branch with fleets breakdown (3 and 3, not single 6)."""
    data = _seed_branch_and_fleets(db_session, prefix_id=8200)
    admin_token = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create 3 seats for Tenant A and 3 seats for Tenant B
    for t_id in (data["tenant_a"].id, data["tenant_b"].id):
        res = client.post(
            "/admin/dedicated/bookings",
            json={
                "merchant_branch_id": data["branch"].id,
                "logistics_company_tenant_id": t_id,
                "seats_count": 3,
                "shift_type": "full_day_8h",
                "monthly_fee_to_merchant": 7000.0,
                "monthly_payout_to_logistics": 5500.0,
                "start_date": str(TARGET_MONTH),
            },
            headers=headers,
        )
        assert res.status_code == 201

    # Fetch admin branch list
    res = client.get("/admin/dedicated/merchants", headers=headers)
    assert res.status_code == 200, res.text
    merchants = res.json()

    target_m = next((m for m in merchants if m["id"] == data["account"].id), None)
    assert target_m is not None, "Merchant not found in admin merchants list"
    target_b = next((b for b in target_m["branches"] if b["id"] == data["branch"].id), None)
    assert target_b is not None, "Branch not found in merchant branches list"

    assert target_b["active_bookings_count"] == 6
    # Fleets breakdown requirement:
    assert "fleets" in target_b, "fleets summary missing in AdminBranchOut"
    fleets = target_b["fleets"]
    assert len(fleets) == 2, f"Expected 2 fleets for branch, got {len(fleets)}: {fleets}"

    fleet_a_summary = next((f for f in fleets if f["tenant_id"] == data["tenant_a"].id), None)
    fleet_b_summary = next((f for f in fleets if f["tenant_id"] == data["tenant_b"].id), None)

    assert fleet_a_summary is not None, "Fleet A summary missing"
    assert fleet_b_summary is not None, "Fleet B summary missing"

    assert fleet_a_summary["seats"] == 3
    assert fleet_a_summary["vacant"] == 3
    assert fleet_a_summary["filled"] == 0
    assert fleet_a_summary["tenant_name"] == data["tenant_a"].name

    assert fleet_b_summary["seats"] == 3
    assert fleet_b_summary["vacant"] == 3
    assert fleet_b_summary["filled"] == 0
    assert fleet_b_summary["tenant_name"] == data["tenant_b"].name


# ─── Test 3: Cashier rider cards report correct fleet names ───────────────────

def test_cashier_rider_cards_report_correct_fleet_names(client, db_session):
    """Test 3: GET /merchant/branch/{id}/riders/active reports correct logistics_company_name for riders & vacant seats."""
    data = _seed_branch_and_fleets(db_session, prefix_id=8300)
    admin_token = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create 2 seats for Fleet A, 2 seats for Fleet B
    res_a = client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_a"].id,
            "seats_count": 2,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(date.today()),
        },
        headers=headers,
    )
    b_ids_a = res_a.json()["booking_ids"]

    res_b = client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_b"].id,
            "seats_count": 2,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(date.today()),
        },
        headers=headers,
    )
    b_ids_b = res_b.json()["booking_ids"]

    # Assign one rider to Fleet A seat 0, and one rider to Fleet B seat 0
    rider_a = Courier(
        id=8301,
        tenant_id=data["tenant_a"].id,
        name="سائق أسطول النقل",
        phone="+966508301001",
        country=Country.SA,
        courier_type=CourierType.COMPANY,
        employment_status="ACTIVE",
    )
    rider_b = Courier(
        id=8302,
        tenant_id=data["tenant_b"].id,
        name="سائق أسطول الفهد",
        phone="+966508302002",
        country=Country.SA,
        courier_type=CourierType.COMPANY,
        employment_status="ACTIVE",
    )
    db_session.add(rider_a)
    db_session.add(rider_b)
    db_session.commit()

    booking_a0 = db_session.get(DedicatedShiftBooking, b_ids_a[0])
    booking_a0.rider_id = rider_a.id
    booking_b0 = db_session.get(DedicatedShiftBooking, b_ids_b[0])
    booking_b0.rider_id = rider_b.id
    db_session.commit()

    # Cashier fetches active riders with vacant seats
    cashier_token = create_branch_token(data["branch"].id, merchant_account_id=data["account"].id)
    c_headers = {"Authorization": f"Bearer {cashier_token}"}
    res = client.get(
        f"/merchant/branch/{data['branch'].id}/riders/active?include_vacant=true",
        headers=c_headers,
    )
    assert res.status_code == 200, res.text
    cards = res.json()
    assert len(cards) == 4, f"Expected 4 cards (2 assigned, 2 vacant), got {len(cards)}"

    # Check rider A card
    card_a = next((c for c in cards if c.get("rider_id") == rider_a.id), None)
    assert card_a is not None
    assert card_a.get("logistics_company_name") == data["tenant_a"].name

    # Check rider B card
    card_b = next((c for c in cards if c.get("rider_id") == rider_b.id), None)
    assert card_b is not None
    assert card_b.get("logistics_company_name") == data["tenant_b"].name

    # Check vacant seat cards
    vacant_cards = [c for c in cards if c.get("is_vacant") is True]
    assert len(vacant_cards) == 2
    fleet_names_in_vacant = {v.get("logistics_company_name") for v in vacant_cards}
    assert data["tenant_a"].name in fleet_names_in_vacant
    assert data["tenant_b"].name in fleet_names_in_vacant


# ─── Test 4: Merchant statement aggregates by branch -> fleet ──────────────────

def test_merchant_statement_groups_by_branch_then_fleet(client, db_session):
    """Test 4: Merchant statement aggregates by branch -> fleet with exact matching subtotals and identical grand total."""
    data = _seed_branch_and_fleets(db_session, prefix_id=8400)
    admin_token = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Contract 3 seats on Fleet A and 2 seats on Fleet B for the full month of August 2026
    client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_a"].id,
            "seats_count": 3,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )
    client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_b"].id,
            "seats_count": 2,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )

    owner_token = create_merchant_account_token(data["account"].id)
    o_headers = {"Authorization": f"Bearer {owner_token}"}

    res = client.get(
        f"/merchant/account/{data['account'].id}/statement?month={MONTH_STR}",
        headers=o_headers,
    )
    assert res.status_code == 200, res.text
    stmt = res.json()

    # Total seats = 5 -> 5 * 7000 = 35000.00
    expected_total = Decimal("35000.00")
    assert Decimal(str(stmt["total_amount_due"])) == expected_total
    assert Decimal(str(stmt["gross_fee_charged_to_merchant"])) == expected_total

    # Verify line items have logistics_company_name
    line_items = stmt["line_items"]
    assert len(line_items) == 5
    for item in line_items:
        assert item.get("logistics_company_name") in (data["tenant_a"].name, data["tenant_b"].name)

    # Verify branch groups (branch -> fleet grouping)
    assert "branch_groups" in stmt, "branch_groups aggregation missing in statement"
    groups = stmt["branch_groups"]
    assert len(groups) == 1
    br_group = groups[0]
    assert br_group["branch_name"] == data["branch"].branch_name
    assert Decimal(str(br_group["branch_total"])) == expected_total

    # Verify fleets under branch
    fleets_under_branch = br_group["fleets"]
    assert len(fleets_under_branch) == 2

    fleet_a_sub = next((f for f in fleets_under_branch if f["logistics_company_name"] == data["tenant_a"].name), None)
    fleet_b_sub = next((f for f in fleets_under_branch if f["logistics_company_name"] == data["tenant_b"].name), None)

    assert fleet_a_sub is not None
    assert fleet_b_sub is not None
    assert fleet_a_sub["seats_count"] == 3
    assert Decimal(str(fleet_a_sub["subtotal"])) == Decimal("21000.00")
    assert fleet_b_sub["seats_count"] == 2
    assert Decimal(str(fleet_b_sub["subtotal"])) == Decimal("14000.00")

    # Grand total matches sum of fleet subtotals down to the halala
    sum_subtotals = Decimal(str(fleet_a_sub["subtotal"])) + Decimal(str(fleet_b_sub["subtotal"]))
    assert sum_subtotals == expected_total


# ─── Test 5: Monthly settlements produce separate fleet statements ─────────────

def test_monthly_settlements_produce_separate_fleet_statements(client, db_session):
    """Test 5: Monthly settlements generate separate statement ledgers for each fleet with correct sums."""
    data = _seed_branch_and_fleets(db_session, prefix_id=8500)
    admin_token = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 3 seats on Fleet A (3 * 5,500 = 16,500), 2 seats on Fleet B (2 * 5,500 = 11,000)
    client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_a"].id,
            "seats_count": 3,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )
    client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_b"].id,
            "seats_count": 2,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )

    # Fleet A fetches settlement
    token_a = make_fleet_token(data["user_a"].id, data["tenant_a"].id)
    res_a = client.get(
        f"/fleet/dedicated/settlement?month={MONTH_STR}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a.status_code == 200, res_a.text
    settle_a = res_a.json()
    assert Decimal(str(settle_a["total_payout_due"])) == Decimal("16500.00")
    assert len(settle_a["line_items"]) == 3

    # Fleet B fetches settlement
    token_b = make_fleet_token(data["user_b"].id, data["tenant_b"].id)
    res_b = client.get(
        f"/fleet/dedicated/settlement?month={MONTH_STR}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 200, res_b.text
    settle_b = res_b.json()
    assert Decimal(str(settle_b["total_payout_due"])) == Decimal("11000.00")
    assert len(settle_b["line_items"]) == 2


# ─── Test 6: Fleet (A) query returns 0 rows belonging to Fleet (B) (P0) ─────────

def test_fleet_portal_strict_tenant_isolation_on_shared_branch(client, db_session):
    """Test 6: P0 Tenant Isolation: Fleet A query returns 0 rows belonging to Fleet B on the shared branch."""
    data = _seed_branch_and_fleets(db_session, prefix_id=8600)
    admin_token = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    res_a = client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_a"].id,
            "seats_count": 3,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )
    res_b = client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_b"].id,
            "seats_count": 4,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )
    b_ids_a = set(res_a.json()["booking_ids"])
    b_ids_b = set(res_b.json()["booking_ids"])

    # Fleet A queries bookings
    token_a = make_fleet_token(data["user_a"].id, data["tenant_a"].id)
    res_a_view = client.get(
        "/fleet/dedicated/bookings",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a_view.status_code == 200, res_a_view.text
    rows_a = res_a_view.json()
    assert len(rows_a) == 3
    retrieved_ids_a = {r["id"] for r in rows_a}
    assert retrieved_ids_a == b_ids_a
    # ZERO overlap with Fleet B's bookings
    assert retrieved_ids_a.isdisjoint(b_ids_b)

    # Fleet B queries bookings
    token_b = make_fleet_token(data["user_b"].id, data["tenant_b"].id)
    res_b_view = client.get(
        "/fleet/dedicated/bookings",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_view.status_code == 200, res_b_view.text
    rows_b = res_b_view.json()
    assert len(rows_b) == 4
    retrieved_ids_b = {r["id"] for r in rows_b}
    assert retrieved_ids_b == b_ids_b
    # ZERO overlap with Fleet A's bookings
    assert retrieved_ids_b.isdisjoint(b_ids_a)


# ─── Test 7: Fleet without operating city license is rejected ──────────────────

def test_unlicensed_fleet_in_city_rejected_while_licensed_succeeds(client, db_session):
    """Test 7: A fleet without operating city license in the branch's city is rejected with 400 Bad Request,

    while the licensed fleet group succeeds.
    """
    data = _seed_branch_and_fleets(db_session, prefix_id=8700)
    admin_token = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Tenant C has NO active operating city in Riyadh
    res_c = client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_c"].id,
            "seats_count": 2,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )
    assert res_c.status_code == 400, f"Unlicensed fleet should be rejected with 400, got: {res_c.status_code}"
    assert "لا تخدم مدينة هذا الفرع" in res_c.text or "تفعيل مدينة التشغيل" in res_c.text

    # Tenant A is licensed in Riyadh -> Succeeds
    res_a = client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_a"].id,
            "seats_count": 2,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )
    assert res_a.status_code == 201, f"Licensed fleet should succeed, got: {res_a.text}"


# ─── Test 8: Vacant seat from (A) does not affect payouts of (B) ───────────────

def test_vacant_seat_of_fleet_a_does_not_affect_fleet_b(client, db_session):
    """Test 8: Vacant seat from Fleet (A) does not diminish or affect payouts of Fleet (B).

    SLA accountability is strictly per contracted seat.
    """
    data = _seed_branch_and_fleets(db_session, prefix_id=8800)
    admin_token = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 3 seats on Fleet A, 3 seats on Fleet B
    res_a = client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_a"].id,
            "seats_count": 3,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )
    res_b = client.post(
        "/admin/dedicated/bookings",
        json={
            "merchant_branch_id": data["branch"].id,
            "logistics_company_tenant_id": data["tenant_b"].id,
            "seats_count": 3,
            "shift_type": "full_day_8h",
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": str(TARGET_MONTH),
        },
        headers=headers,
    )
    b_ids_a = res_a.json()["booking_ids"]
    b_ids_b = res_b.json()["booking_ids"]

    # In Fleet A: all 3 seats remain completely vacant (rider_id is None)
    # In Fleet B: 3 riders are assigned and active
    for i, b_id in enumerate(b_ids_b):
        rider = Courier(
            id=8850 + i,
            tenant_id=data["tenant_b"].id,
            name=f"مندوب الفهد {i}",
            phone=f"+96650885000{i}",
            country=Country.SA,
            courier_type=CourierType.COMPANY,
            employment_status="ACTIVE",
        )
        db_session.add(rider)
        db_session.commit()
        booking = db_session.get(DedicatedShiftBooking, b_id)
        booking.rider_id = rider.id
        db_session.commit()

    # Check settlements for Fleet B:
    # Fleet B has 3 contracted seats at 5500 each = 16,500 SAR
    token_b = make_fleet_token(data["user_b"].id, data["tenant_b"].id)
    res_b_settle = client.get(
        f"/fleet/dedicated/settlement?month={MONTH_STR}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_settle.status_code == 200, res_b_settle.text
    settle_b = res_b_settle.json()
    assert Decimal(str(settle_b["total_payout_due"])) == Decimal("16500.00"), (
        f"Fleet B payout should be exactly 16500.00 SAR regardless of Fleet A's vacancies, got: {settle_b['total_payout_due']}"
    )

    # Check settlements for Fleet A:
    # Fleet A contracted 3 seats at 5500 each = 16,500 SAR
    token_a = make_fleet_token(data["user_a"].id, data["tenant_a"].id)
    res_a_settle = client.get(
        f"/fleet/dedicated/settlement?month={MONTH_STR}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a_settle.status_code == 200, res_a_settle.text
    settle_a = res_a_settle.json()
    assert Decimal(str(settle_a["total_payout_due"])) == Decimal("16500.00")
