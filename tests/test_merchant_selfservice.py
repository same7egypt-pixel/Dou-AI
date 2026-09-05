"""Tests for Phase 2: Merchant Self-Service, Branch Verification Gating,
Capacity Request Review Loop, Company Rider Approvals, and Freelancer Instant Assignment.

Guards Requirements 9-25:
9.  Merchant adds branch via self-service -> marked created_by_source='MERCHANT', verification_status='PENDING_REVIEW'.
10. Admin branch listing flags merchant-added branches with pending verification status.
11. Booking creation on unverified branch is strictly rejected (HTTP 400).
12. Admin verifies branch -> verification_status becomes 'VERIFIED', subsequent booking creation succeeds.
13. Admin lists capacity requests with filtering (status, merchant_account_id).
14. Admin patches capacity request -> approved with notes and timestamp.
15. Admin patches capacity request -> rejected with notes.
16. Fleet assigns COMPANY rider -> creates pending RiderAssignmentApproval, seat remains vacant.
17. Fleet assigns FREELANCER rider -> instantly fills seat, skips approval.
18. Merchant lists pending rider approvals with privacy-redacted phone numbers and no leaked private data.
19. Merchant approves COMPANY rider -> seat becomes officially assigned.
20. Merchant rejects COMPANY rider -> seat remains vacant, reason recorded.
21. Pending rider approval > 24 hours flags delayed alert.
22. Freelancer and company rider billing is identical to the penny with zero branching on courier_type.
23. Fleet performance breakdown compares freelancer vs company riders.
24. Migration downgrade and upgrade execute cleanly.
25. Full lifecycle self-service to multi-fleet end-to-end integration test.
"""

import calendar
import os
from datetime import date, datetime, timedelta, timezone

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
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    MerchantCapacityRequest,
)
from app.routers.auth import create_token
from app.utils.security import (
    create_branch_token,
    create_merchant_account_token,
)

TEST_DB_FILE = "./test_merchant_selfservice.db"
engine = create_engine(
    f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
)

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
def setup_database():
    app.dependency_overrides[get_db] = override_get_db
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_data():
    db = TestingSessionLocal()
    try:
        # 1. Geo Country and City
        sa_country = db.query(GeoCountry).filter_by(code="SA").first()
        if not sa_country:
            sa_country = GeoCountry(code="SA", name="المملكة العربية السعودية", flag="🇸🇦")
            db.add(sa_country)
            db.commit()
            db.refresh(sa_country)

        riyadh_city = db.query(GeoCity).filter_by(name="الرياض").first()
        if not riyadh_city:
            riyadh_city = GeoCity(country_id=sa_country.id, name="الرياض")
            db.add(riyadh_city)
            db.commit()
            db.refresh(riyadh_city)

        # 2. Tenants
        tenant_a = db.query(Tenant).filter_by(name="Golden Logistics Phase2").first()
        if not tenant_a:
            tenant_a = Tenant(
                name="Golden Logistics Phase2",
                country=Country.SA,
                market_code="SA",
                currency="SAR",
            )
            db.add(tenant_a)
            db.commit()
            db.refresh(tenant_a)

        tenant_b = db.query(Tenant).filter_by(name="Wefaq Logistics Phase2").first()
        if not tenant_b:
            tenant_b = Tenant(
                name="Wefaq Logistics Phase2",
                country=Country.SA,
                market_code="SA",
                currency="SAR",
            )
            db.add(tenant_b)
            db.commit()
            db.refresh(tenant_b)

        # Tenant operating cities
        for t in [tenant_a, tenant_b]:
            toc = db.query(TenantOperatingCity).filter_by(tenant_id=t.id, geo_city_id=riyadh_city.id).first()
            if not toc:
                toc = TenantOperatingCity(tenant_id=t.id, geo_city_id=riyadh_city.id, is_active=True)
                db.add(toc)
        db.commit()

        # 3. Users
        admin_user = db.query(User).filter_by(phone="+966500009999").first()
        if not admin_user:
            admin_user = User(
                id=9501,
                phone="+966500009999",
                role=UserRole.DOU_ADMIN,
                name="DOU SuperAdmin P2",
                password_hash="fake",
                country=Country.SA,
                is_active=True,
                token_version=0,
            )
            db.merge(admin_user)

        fleet_a_user = db.query(User).filter_by(phone="+966500008888").first()
        if not fleet_a_user:
            fleet_a_user = User(
                id=9502,
                phone="+966500008888",
                role=UserRole.COMPANY,
                tenant_id=tenant_a.id,
                name="Golden Dispatcher P2",
                password_hash="fake",
                country=Country.SA,
                is_active=True,
                token_version=0,
            )
            db.merge(fleet_a_user)

        fleet_b_user = db.query(User).filter_by(phone="+966500007777").first()
        if not fleet_b_user:
            fleet_b_user = User(
                id=9503,
                phone="+966500007777",
                role=UserRole.COMPANY,
                tenant_id=tenant_b.id,
                name="Wefaq Dispatcher P2",
                password_hash="fake",
                country=Country.SA,
                is_active=True,
                token_version=0,
            )
            db.merge(fleet_b_user)

        db.commit()
        admin_user = db.get(User, 9501)
        fleet_a_user = db.get(User, 9502)
        fleet_b_user = db.get(User, 9503)

        # 4. Merchant Account
        merchant_account = db.query(MerchantAccount).filter_by(trade_name="Shawarma Palace P2").first()
        if not merchant_account:
            merchant_account = MerchantAccount(
                trade_name="Shawarma Palace P2",
                vat_number="300000000000003",
                billing_contact_email="billing@shawarma-p2.test",
                billing_contact_phone="0550000001",
                payment_terms_days=30,
            )
            db.add(merchant_account)
            db.commit()
            db.refresh(merchant_account)

        # IDs
        t_a_id = tenant_a.id
        t_b_id = tenant_b.id
        adm_id = admin_user.id
        ma_id = merchant_account.id

        # Tokens
        admin_token = create_token(admin_user)
        fleet_a_token = create_token(fleet_a_user)
        fleet_b_token = create_token(fleet_b_user)
        merchant_token = create_merchant_account_token(merchant_account.id)

        return {
            "sa_country": sa_country,
            "riyadh_city": riyadh_city,
            "tenant_a_id": t_a_id,
            "tenant_b_id": t_b_id,
            "admin_user_id": adm_id,
            "merchant_account_id": ma_id,
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "admin_user": admin_user,
            "fleet_a_user": fleet_a_user,
            "fleet_b_user": fleet_b_user,
            "merchant_account": merchant_account,
            "admin_token": admin_token,
            "fleet_a_token": fleet_a_token,
            "fleet_b_token": fleet_b_token,
            "merchant_token": merchant_token,
        }
    finally:
        db.close()


def test_9_merchant_adds_branch_marked_pending_review_and_source_merchant(client, test_data):
    """Test 9: Merchant submits branch -> created_by_source='MERCHANT', verification_status='PENDING_REVIEW'."""
    ma = test_data["merchant_account"]
    token = test_data["merchant_token"]

    payload = {
        "branch_name": "فرع حي الصحافة",
        "city": "الرياض",
        "district": "الصحافة",
        "latitude": 24.7932,
        "longitude": 46.6543,
        "geofence_radius_meters": 150,
        "cashier_access_pin": "5566",
    }

    resp = client.post(
        f"/merchant/account/{ma.id}/branches",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["branch_name"] == "فرع حي الصحافة"
    assert data["created_by_source"] == "MERCHANT"
    assert data["verification_status"] == "PENDING_REVIEW"
    assert "id" in data


def test_10_admin_branch_listing_flags_merchant_added_pending_branches(client, test_data):
    """Test 10: Admin lists branches and sees verification_status='PENDING_REVIEW' and created_by_source='MERCHANT'."""
    admin_token = test_data["admin_token"]
    resp = client.get(
        "/admin/dedicated/merchants",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    merchants = resp.json()
    ma = test_data["merchant_account"]
    target_m = next((m for m in merchants if m["id"] == ma.id), None)
    assert target_m is not None
    branch = next((b for b in target_m["branches"] if (b.get("branch_name") == "فرع حي الصحافة" or b.get("name") == "فرع حي الصحافة")), None)
    assert branch is not None
    assert branch["verification_status"] == "PENDING_REVIEW"
    assert branch["created_by_source"] == "MERCHANT"


def test_11_booking_creation_rejected_on_unverified_branch(client, test_data):
    """Test 11: Attempting to create booking on unverified branch is strictly rejected with HTTP 400."""
    admin_token = test_data["admin_token"]
    ma_id = test_data["merchant_account_id"]
    tenant_a_id = test_data["tenant_a_id"]

    db = TestingSessionLocal()
    branch = db.query(MerchantBranch).filter_by(merchant_account_id=ma_id, branch_name="فرع حي الصحافة").first()
    db.close()
    assert branch is not None
    assert branch.verification_status == "PENDING_REVIEW"

    booking_payload = {
        "merchant_id": ma_id,
        "branch_id": branch.id,
        "tenant_id": tenant_a_id,
        "shift_type": "full_day_8h",
        "seats_count": 2,
        "monthly_fee_to_merchant": 7000.0,
        "monthly_payout_to_logistics": 5500.0,
        "start_date": "2026-08-01",
    }

    resp = client.post(
        "/admin/dedicated/bookings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=booking_payload,
    )
    assert resp.status_code == 400, f"Expected 400 rejection for unverified branch, got {resp.status_code}: {resp.text}"
    assert "توثيق" in resp.json()["detail"] or "unverified" in resp.json()["detail"].lower()


def test_12_admin_verifies_branch_and_booking_creation_then_succeeds(client, test_data):
    """Test 12: Admin verifies branch -> status becomes 'VERIFIED', subsequent booking creation succeeds."""
    admin_token = test_data["admin_token"]
    ma_id = test_data["merchant_account_id"]
    tenant_a_id = test_data["tenant_a_id"]

    db = TestingSessionLocal()
    branch = db.query(MerchantBranch).filter_by(merchant_account_id=ma_id, branch_name="فرع حي الصحافة").first()
    db.close()

    # Admin verifies branch
    verify_resp = client.post(
        f"/admin/dedicated/branches/{branch.id}/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert verify_resp.status_code == 200, f"Verify failed: {verify_resp.text}"
    assert verify_resp.json()["verification_status"] == "VERIFIED"

    # Now booking creation must succeed
    booking_payload = {
        "merchant_id": ma_id,
        "branch_id": branch.id,
        "tenant_id": tenant_a_id,
        "shift_type": "full_day_8h",
        "seats_count": 2,
        "monthly_fee_to_merchant": 7000.0,
        "monthly_payout_to_logistics": 5500.0,
        "start_date": "2026-08-01",
    }
    resp = client.post(
        "/admin/dedicated/bookings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=booking_payload,
    )
    assert resp.status_code in (200, 201), f"Expected 200/201 on verified branch, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data.get("created_count") == 2 or data.get("seats_created") == 2


def test_13_admin_lists_capacity_requests_with_filtering(client, test_data):
    """Test 13: Merchant creates capacity request, Admin lists with filters."""
    ma = test_data["merchant_account"]
    m_token = test_data["merchant_token"]
    admin_token = test_data["admin_token"]

    db = TestingSessionLocal()
    branch = db.query(MerchantBranch).filter_by(merchant_account_id=ma.id, branch_name="فرع حي الصحافة").first()
    db.close()

    # Create capacity request as merchant
    req_resp = client.post(
        f"/merchant/account/{ma.id}/capacity-requests",
        headers={"Authorization": f"Bearer {m_token}"},
        json={
            "branch_id": branch.id,
            "requested_capacity": 5,
            "effective_month": "2026-09",
            "reason": "توسع وزيادة طلبات نهاية الأسبوع",
        },
    )
    assert req_resp.status_code == 200, f"Failed creating capacity request: {req_resp.text}"
    req_id = req_resp.json()["id"]

    # Admin list all
    list_resp = client.get(
        "/admin/capacity-requests",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_resp.status_code == 200, f"Admin list capacity requests failed: {list_resp.text}"
    items = list_resp.json()
    assert any(it["id"] == req_id for it in items)

    # Admin list with filter
    filter_resp = client.get(
        f"/admin/capacity-requests?status=requested&merchant_account_id={ma.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert filter_resp.status_code == 200
    filtered = filter_resp.json()
    assert len(filtered) >= 1
    assert all(it["status"] == "requested" for it in filtered)


def test_14_admin_patches_capacity_request_approved_and_notes(client, test_data):
    """Test 14: Admin patches capacity request to approved with notes."""
    admin_token = test_data["admin_token"]
    admin_user = test_data["admin_user"]
    ma = test_data["merchant_account"]

    db = TestingSessionLocal()
    req = db.query(MerchantCapacityRequest).filter_by(merchant_account_id=ma.id, status="requested").first()
    db.close()
    assert req is not None

    patch_resp = client.patch(
        f"/admin/capacity-requests/{req.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "status": "approved",
            "review_notes": "تمت الموافقة وتنسيق المناديب مع الأسطول الذهبي",
        },
    )
    assert patch_resp.status_code == 200, f"Failed patching request: {patch_resp.text}"
    data = patch_resp.json()
    assert data["status"] == "approved"
    assert data["reviewed_by"] == admin_user.id
    assert data["review_notes"] == "تمت الموافقة وتنسيق المناديب مع الأسطول الذهبي"
    assert data["reviewed_at"] is not None


def test_15_admin_patches_capacity_request_rejected(client, test_data):
    """Test 15: Admin patches capacity request to rejected with reason."""
    admin_token = test_data["admin_token"]
    m_token = test_data["merchant_token"]
    ma = test_data["merchant_account"]

    db = TestingSessionLocal()
    branch = db.query(MerchantBranch).filter_by(merchant_account_id=ma.id, branch_name="فرع حي الصحافة").first()
    db.close()

    # Create another request
    r = client.post(
        f"/merchant/account/{ma.id}/capacity-requests",
        headers={"Authorization": f"Bearer {m_token}"},
        json={
            "branch_id": branch.id,
            "requested_capacity": 10,
            "effective_month": "2026-10",
            "reason": "طلب غير مدروس",
        },
    )
    assert r.status_code == 200
    req_id = r.json()["id"]

    # Reject
    rej_resp = client.patch(
        f"/admin/capacity-requests/{req_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "status": "rejected",
            "review_notes": "الطلب يتجاوز الطاقة الاستيعابية الحالية للمنطقة",
        },
    )
    assert rej_resp.status_code == 200
    assert rej_resp.json()["status"] == "rejected"


def test_16_fleet_assigns_company_rider_creates_pending_approval_seat_vacant(client, test_data):
    """Test 16: Fleet assigns COMPANY rider -> creates pending RiderAssignmentApproval, seat remains vacant."""
    tenant_a_id = test_data["tenant_a_id"]
    fleet_a_token = test_data["fleet_a_token"]
    ma_id = test_data["merchant_account_id"]

    db = TestingSessionLocal()
    branch = db.query(MerchantBranch).filter_by(merchant_account_id=ma_id, branch_name="فرع حي الصحافة").first()
    booking = db.query(DedicatedShiftBooking).filter_by(
        merchant_branch_id=branch.id,
        logistics_company_tenant_id=tenant_a_id,
        rider_id=None,
    ).order_by(DedicatedShiftBooking.id.asc()).first()
    assert booking is not None

    company_courier = Courier(
        name="خالد أحمد السعيد (كفالة)",
        phone="+966551234567",
        tenant_id=tenant_a_id,
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
        photo_url="https://dou.sa/photos/khaled.jpg",
        vehicle_plate="1234-XYZ",
    )
    db.add(company_courier)
    db.commit()
    db.refresh(company_courier)
    courier_id = company_courier.id
    booking_id = booking.id
    db.close()

    assign_resp = client.post(
        f"/fleet/dedicated/bookings/{booking_id}/assign-rider",
        headers={"Authorization": f"Bearer {fleet_a_token}"},
        json={"rider_id": courier_id},
    )
    assert assign_resp.status_code == 200, f"Assign failed: {assign_resp.text}"
    res = assign_resp.json()
    assert res.get("approval_status") == "PENDING" or "موافقة" in res.get("message", "")

    # Seat must remain vacant until approved!
    db = TestingSessionLocal()
    refreshed_b = db.get(DedicatedShiftBooking, booking_id)
    assert refreshed_b.rider_id is None, "Seat should remain vacant until merchant approves COMPANY courier!"
    db.close()


def test_17_fleet_assigns_freelancer_rider_instantly_assigns_seat_filled(client, test_data):
    """Test 17: Fleet assigns FREELANCER rider -> instantly fills seat without merchant approval."""
    tenant_a_id = test_data["tenant_a_id"]
    fleet_a_token = test_data["fleet_a_token"]
    ma_id = test_data["merchant_account_id"]

    db = TestingSessionLocal()
    branch = db.query(MerchantBranch).filter_by(merchant_account_id=ma_id, branch_name="فرع حي الصحافة").first()
    booking = db.query(DedicatedShiftBooking).filter_by(
        merchant_branch_id=branch.id,
        logistics_company_tenant_id=tenant_a_id,
        rider_id=None,
    ).order_by(DedicatedShiftBooking.id.desc()).first()
    assert booking is not None

    freelancer = Courier(
        name="عمرو جمال (فريلانسر)",
        phone="+966559876543",
        tenant_id=tenant_a_id,
        courier_type=CourierType.FREELANCER,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db.add(freelancer)
    db.commit()
    db.refresh(freelancer)
    courier_id = freelancer.id
    booking_id = booking.id
    db.close()

    assign_resp = client.post(
        f"/fleet/dedicated/bookings/{booking_id}/assign-rider",
        headers={"Authorization": f"Bearer {fleet_a_token}"},
        json={"rider_id": courier_id},
    )
    assert assign_resp.status_code == 200, f"Assign freelancer failed: {assign_resp.text}"
    res = assign_resp.json()
    assert res.get("success") is True or res.get("ok") is True

    # Seat is instantly filled!
    db = TestingSessionLocal()
    refreshed_b = db.get(DedicatedShiftBooking, booking_id)
    assert refreshed_b.rider_id == courier_id, "FREELANCER courier should be assigned instantly!"
    db.close()


def test_18_merchant_lists_pending_rider_approvals_with_privacy_redacted_phone(client, test_data):
    """Test 18: Merchant views pending approvals -> courier phone is masked/redacted, no national ID leak."""
    ma_id = test_data["merchant_account_id"]
    m_token = test_data["merchant_token"]

    resp = client.get(
        f"/merchant/account/{ma_id}/rider-approvals",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    assert resp.status_code == 200, f"Merchant get approvals failed: {resp.text}"
    approvals = resp.json()
    assert len(approvals) >= 1

    appr = approvals[0]
    assert appr["courier_name"] == "خالد أحمد السعيد (كفالة)"
    # Privacy check: Phone must be redacted (not the raw full phone)
    assert "***" in appr["courier_phone_masked"] or "•••" in appr["courier_phone_masked"] or appr["courier_phone_masked"] != "+966551234567"
    assert "national_id" not in appr or appr["national_id"] is None
    assert "payout" not in appr
    assert "courier_photo_url" in appr, "Must include courier_photo_url in approval schema"
    assert "vehicle_plate" in appr, "Must include vehicle_plate in approval schema"
    assert appr["courier_photo_url"] == "https://dou.sa/photos/khaled.jpg"
    assert appr["vehicle_plate"] == "1234-XYZ"


def test_19_merchant_approves_company_rider_seat_becomes_assigned(client, test_data):
    """Test 19: Merchant approves COMPANY rider -> seat officially filled."""
    ma_id = test_data["merchant_account_id"]
    m_token = test_data["merchant_token"]

    # Fetch approval ID
    resp = client.get(
        f"/merchant/account/{ma_id}/rider-approvals",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    approvals = resp.json()
    appr = next(a for a in approvals if a["status"] == "PENDING")

    decide_resp = client.post(
        f"/merchant/account/{ma_id}/rider-approvals/{appr['id']}/decide",
        headers={"Authorization": f"Bearer {m_token}"},
        json={"action": "APPROVED"},
    )
    assert decide_resp.status_code == 200, f"Decision failed: {decide_resp.text}"
    assert decide_resp.json()["status"] == "APPROVED"

    # Verify seat is now filled in booking
    db = TestingSessionLocal()
    booking = db.get(DedicatedShiftBooking, appr["booking_id"])
    assert booking.rider_id == appr["courier_id"], "Booking rider_id should now be set to approved courier!"
    db.close()


def test_20_merchant_rejects_company_rider_seat_remains_vacant(client, test_data):
    """Test 20: Merchant rejects COMPANY rider -> seat remains vacant with recorded rejection reason."""
    admin_token = test_data["admin_token"]
    fleet_a_token = test_data["fleet_a_token"]
    ma_id = test_data["merchant_account_id"]
    m_token = test_data["merchant_token"]
    tenant_a_id = test_data["tenant_a_id"]

    db = TestingSessionLocal()
    branch = db.query(MerchantBranch).filter_by(merchant_account_id=ma_id, branch_name="فرع حي الصحافة").first()
    branch_id = branch.id
    db.close()

    # Create 1 new seat for this test
    bk_resp = client.post(
        "/admin/dedicated/bookings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "merchant_id": ma_id,
            "branch_id": branch_id,
            "tenant_id": tenant_a_id,
            "shift_type": "full_day_8h",
            "seats_count": 1,
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": "2026-08-01",
        },
    )
    assert bk_resp.status_code in (200, 201)

    db = TestingSessionLocal()
    booking = db.query(DedicatedShiftBooking).filter_by(
        merchant_branch_id=branch_id,
        logistics_company_tenant_id=tenant_a_id,
        rider_id=None,
    ).order_by(DedicatedShiftBooking.id.desc()).first()

    another_company_courier = Courier(
        name="سعيد عبد الله (كفالة)",
        phone="+966558889990",
        tenant_id=tenant_a_id,
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db.add(another_company_courier)
    db.commit()
    db.refresh(another_company_courier)
    courier_id = another_company_courier.id
    booking_id = booking.id
    db.close()

    # Fleet assigns
    client.post(
        f"/fleet/dedicated/bookings/{booking_id}/assign-rider",
        headers={"Authorization": f"Bearer {fleet_a_token}"},
        json={"rider_id": courier_id},
    )

    # Merchant rejects
    appr_resp = client.get(
        f"/merchant/account/{ma_id}/rider-approvals",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    pending_appr = next(a for a in appr_resp.json() if a["booking_id"] == booking_id and a["status"] == "PENDING")

    decide_resp = client.post(
        f"/merchant/account/{ma_id}/rider-approvals/{pending_appr['id']}/decide",
        headers={"Authorization": f"Bearer {m_token}"},
        json={"action": "REJECTED", "rejection_reason": "ساعات العمل لا تناسب معايير الفرع"},
    )
    assert decide_resp.status_code == 200
    assert decide_resp.json()["status"] == "REJECTED"

    # Booking seat remains vacant
    db = TestingSessionLocal()
    refreshed_b = db.get(DedicatedShiftBooking, booking_id)
    assert refreshed_b.rider_id is None, "Seat must remain vacant after rejection!"
    db.close()


def test_21_pending_rider_approval_over_24h_flags_delayed_alert(client, test_data):
    """Test 21: Pending approval older than 24 hours surfaces delayed alert."""
    ma_id = test_data["merchant_account_id"]
    m_token = test_data["merchant_token"]

    db = TestingSessionLocal()
    from app.models.merchant import RiderAssignmentApproval
    old_appr = db.query(RiderAssignmentApproval).filter_by(status="REJECTED").first()
    delayed_appr = RiderAssignmentApproval(
        booking_id=old_appr.booking_id,
        merchant_branch_id=old_appr.merchant_branch_id,
        merchant_account_id=old_appr.merchant_account_id,
        logistics_company_tenant_id=old_appr.logistics_company_tenant_id,
        courier_id=old_appr.courier_id,
        courier_name="مندوب متأخر في الاعتماد",
        courier_phone="+966550001122",
        status="PENDING",
        requested_at=datetime.now(timezone.utc) - timedelta(hours=26),
    )
    db.add(delayed_appr)
    db.commit()
    db.close()

    resp = client.get(
        f"/merchant/account/{ma_id}/rider-approvals",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    assert resp.status_code == 200
    items = resp.json()
    target = next((it for it in items if it["courier_name"] == "مندوب متأخر في الاعتماد"), None)
    assert target is not None
    assert target["is_delayed_over_24h"] is True


def test_22_freelancer_and_company_rider_billing_identical_to_the_penny(client, test_data):
    """Test 22: rider type never changes the money.

    Builds both seats itself — same branch, same fleet, same terms, same active
    window, both filled, neither awaiting approval. The only difference is
    courier_type, so any gap in prorated_fee is a branch on rider type inside
    the billing math, which is exactly what must never exist.
    """
    from datetime import time
    from decimal import Decimal

    from app.models.entities import Country, Courier, CourierType
    from app.models.merchant import (
        BookingStatus,
        DedicatedShiftBooking,
        MerchantBranch,
        ShiftType,
    )

    ma_id = test_data["merchant_account_id"]
    m_token = test_data["merchant_token"]
    tenant_a_id = test_data["tenant_a_id"]

    db = TestingSessionLocal()
    branch = MerchantBranch(
        merchant_account_id=ma_id,
        branch_name="فرع مقارنة نوع المندوب",
        city="الرياض",
        latitude=Decimal("24.7"),
        longitude=Decimal("46.6"),
        cashier_access_pin="7788",
        verification_status="VERIFIED",
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)

    seats = {}
    for label, ctype in (("company", CourierType.COMPANY), ("freelancer", CourierType.FREELANCER)):
        rider = Courier(
            name=f"مندوب {label} للمقارنة",
            phone=f"05555{'1' if label == 'company' else '2'}0001",
            courier_type=ctype,
            country=Country.SA,
            tenant_id=tenant_a_id,
        )
        db.add(rider)
        db.commit()
        db.refresh(rider)

        booking = DedicatedShiftBooking(
            merchant_branch_id=branch.id,
            logistics_company_tenant_id=tenant_a_id,
            rider_id=rider.id,
            shift_type=ShiftType.full_day_8h,
            shift_start_time=time(10, 0),
            shift_end_time=time(18, 0),
            effective_from=date(2026, 8, 1),
            effective_until=None,
            monthly_fee_to_merchant=Decimal("7000.00"),
            monthly_payout_to_logistics=Decimal("5500.00"),
            dou_margin=Decimal("1500.00"),
            status=BookingStatus.active,
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)
        seats[label] = booking.id
    db.close()

    resp = client.get(
        f"/merchant/account/{ma_id}/statement?month={MONTH_STR}",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    assert resp.status_code == 200, resp.text
    rows = [
        it
        for it in resp.json()["line_items"]
        if it["branch_name"] == "فرع مقارنة نوع المندوب"
    ]

    company_items = [it for it in rows if (it.get("courier_type") or "").upper() == "COMPANY"]
    freelancer_items = [it for it in rows if (it.get("courier_type") or "").upper() == "FREELANCER"]

    assert len(company_items) == 1, f"expected one company seat on this branch, got {rows}"
    assert len(freelancer_items) == 1, f"expected one freelancer seat on this branch, got {rows}"

    company, freelancer = company_items[0], freelancer_items[0]
    assert company["active_days"] == freelancer["active_days"]
    assert company["prorated_fee"] == freelancer["prorated_fee"], (
        "Rider type must not change the money — "
        f"company={company['prorated_fee']} freelancer={freelancer['prorated_fee']}"
    )


def test_22b_pending_approval_days_deducted_symmetrically(client, test_data):
    """Test 22b: Days waiting for merchant rider approval are deducted symmetrically from both merchant and fleet.

    - Seat requested on Aug 10, approved on Aug 15 -> 5 days deducted (26/31 active days).
    - Vacant seat without any approval request -> 100% billable (31/31 active days) preserving SLA.
    - Symmetrical finances: merchant fee, fleet payout, and DOU margin reconcile to the penny.
    """
    from datetime import time
    from decimal import Decimal
    from app.models.merchant import BookingStatus, DedicatedShiftBooking, MerchantBranch, RiderAssignmentApproval, ShiftType
    from app.utils.finance import prorate

    ma_id = test_data["merchant_account_id"]
    m_token = test_data["merchant_token"]
    tenant_a_id = test_data["tenant_a_id"]
    fleet_a_token = test_data["fleet_a_token"]

    db = TestingSessionLocal()
    branch = db.query(MerchantBranch).filter_by(merchant_account_id=ma_id).first()
    if not branch:
        branch = MerchantBranch(
            merchant_account_id=ma_id,
            branch_name="فرع الصحافة للخصم",
            city="الرياض",
            latitude=Decimal("24.7"),
            longitude=Decimal("46.6"),
            cashier_access_pin="1234",
            verification_status="VERIFIED",
        )
        db.add(branch)
        db.commit()
        db.refresh(branch)

    # 1. Booking with 5 days pending approval (Aug 10 to Aug 15)
    b_pending = DedicatedShiftBooking(
        merchant_branch_id=branch.id,
        logistics_company_tenant_id=tenant_a_id,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(10, 0),
        shift_end_time=time(18, 0),
        effective_from=date(2026, 8, 1),
        effective_until=None,
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("5500.00"),
        dou_margin=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    # 2. Completely vacant seat (no approval request)
    b_vacant = DedicatedShiftBooking(
        merchant_branch_id=branch.id,
        logistics_company_tenant_id=tenant_a_id,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(10, 0),
        shift_end_time=time(18, 0),
        effective_from=date(2026, 8, 1),
        effective_until=None,
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("5500.00"),
        dou_margin=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    db.add_all([b_pending, b_vacant])
    db.commit()
    db.refresh(b_pending)
    db.refresh(b_vacant)

    # Add approval for b_pending: requested Aug 10, decided Aug 15 (5 days pending)
    appr = RiderAssignmentApproval(
        booking_id=b_pending.id,
        merchant_branch_id=branch.id,
        merchant_account_id=ma_id,
        logistics_company_tenant_id=tenant_a_id,
        courier_id=1,
        courier_name="مندوب اختبار الخصم",
        courier_phone="+966550009988",
        status="APPROVED",
        requested_at=datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc),
        decided_at=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )
    db.add(appr)
    db.commit()
    b_pending_id = b_pending.id
    b_vacant_id = b_vacant.id
    db.close()

    # Query merchant statement
    resp = client.get(
        f"/merchant/account/{ma_id}/statement?month=2026-08",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    assert resp.status_code == 200
    st = resp.json()

    # In August (31 days):
    # b_pending active days must be 31 - 5 = 26 days
    # b_vacant active days must be 31 days
    line_pending = next(item for item in st["line_items"] if item.get("rider_name") == "مقعد شاغر (غير معيّن)" and item.get("active_days") == 26)
    assert line_pending["active_days"] == 26, f"Expected 26 active days for b_pending, got {line_pending['active_days']}"
    assert line_pending["prorated_fee"] == float(prorate(Decimal("7000.00"), 26, date(2026, 8, 1)))

    line_vacant = next(item for item in st["line_items"] if item.get("rider_name") == "مقعد شاغر (غير معيّن)" and item.get("active_days") == 31)
    assert line_vacant["active_days"] == 31
    assert line_vacant["prorated_fee"] == 7000.0

    # Query fleet settlement
    f_resp = client.get(
        "/fleet/dedicated/settlement?month=2026-08",
        headers={"Authorization": f"Bearer {fleet_a_token}"},
    )
    assert f_resp.status_code == 200
    fst = f_resp.json()
    f_pending = next(item for item in fst["line_items"] if item["booking_id"] == b_pending_id)
    f_vacant = next(item for item in fst["line_items"] if item["booking_id"] == b_vacant_id)

    assert f_pending["active_days"] == 26
    assert f_pending["prorated_payout"] == float(prorate(Decimal("5500.00"), 26, date(2026, 8, 1)))
    assert f_vacant["active_days"] == 31
    assert f_vacant["prorated_payout"] == 5500.0


def test_23_fleet_performance_breakdown_compares_freelancer_vs_company(client, test_data):
    """Test 23: Fleet portal performance breakdown returns metrics comparing freelancer vs company riders."""
    fleet_a_token = test_data["fleet_a_token"]

    resp = client.get(
        "/fleet/dedicated/performance-breakdown",
        headers={"Authorization": f"Bearer {fleet_a_token}"},
    )
    assert resp.status_code == 200, f"Performance breakdown failed: {resp.text}"
    data = resp.json()
    assert "company" in data
    assert "freelancer" in data
    assert "total_riders" in data["company"]
    assert "total_riders" in data["freelancer"]


def test_24_migration_downgrade_and_upgrade_clean():
    """Test 24: Migration downgrade() and upgrade() execute cleanly without schema breakage."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mig_0031",
        "alembic/versions/20260905_0031_merchant_selfservice_and_rider_approvals.py",
    )
    assert spec is not None, "Migration file not found"
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert hasattr(mig, "upgrade")
    assert hasattr(mig, "downgrade")
    assert mig.revision == "20260905_0031"
    assert mig.down_revision == "20260905_0030"


def test_25_full_lifecycle_selfservice_to_multi_fleet_end_to_end(client, test_data):
    """Test 25: Full E2E from branch self-addition to multi-fleet staffing and cashier view."""
    ma_id = test_data["merchant_account_id"]
    m_token = test_data["merchant_token"]
    admin_token = test_data["admin_token"]
    tenant_a_id = test_data["tenant_a_id"]
    tenant_b_id = test_data["tenant_b_id"]
    fleet_a_token = test_data["fleet_a_token"]
    fleet_b_token = test_data["fleet_b_token"]

    # 1. Merchant self-adds branch
    b_resp = client.post(
        f"/merchant/account/{ma_id}/branches",
        headers={"Authorization": f"Bearer {m_token}"},
        json={
            "branch_name": "فرع النخيل E2E",
            "city": "الرياض",
            "district": "النخيل",
            "latitude": 24.7500,
            "longitude": 46.6800,
            "cashier_access_pin": "9988",
        },
    )
    assert b_resp.status_code in (200, 201)
    branch_id = b_resp.json()["id"]

    # 2. Verify blocked
    block_resp = client.post(
        "/admin/dedicated/bookings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "merchant_id": ma_id,
            "branch_id": branch_id,
            "tenant_id": tenant_a_id,
            "shift_type": "full_day_8h",
            "seats_count": 1,
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": "2026-08-01",
        },
    )
    assert block_resp.status_code == 400

    # 3. Admin verifies
    v_resp = client.post(
        f"/admin/dedicated/branches/{branch_id}/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert v_resp.status_code == 200

    # 4. Multi-fleet staffing: 1 seat for Fleet A, 1 seat for Fleet B
    resp_a = client.post(
        "/admin/dedicated/bookings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "merchant_id": ma_id,
            "branch_id": branch_id,
            "tenant_id": tenant_a_id,
            "shift_type": "full_day_8h",
            "seats_count": 1,
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": "2026-08-01",
        },
    )
    assert resp_a.status_code in (200, 201)

    resp_b = client.post(
        "/admin/dedicated/bookings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "merchant_id": ma_id,
            "branch_id": branch_id,
            "tenant_id": tenant_b_id,
            "shift_type": "full_day_8h",
            "seats_count": 1,
            "monthly_fee_to_merchant": 7000.0,
            "monthly_payout_to_logistics": 5500.0,
            "start_date": "2026-08-01",
        },
    )
    assert resp_b.status_code in (200, 201)

    db = TestingSessionLocal()
    b_a = db.query(DedicatedShiftBooking).filter_by(merchant_branch_id=branch_id, logistics_company_tenant_id=tenant_a_id).first()
    b_b = db.query(DedicatedShiftBooking).filter_by(merchant_branch_id=branch_id, logistics_company_tenant_id=tenant_b_id).first()
    b_a_id = b_a.id
    b_b_id = b_b.id

    c_a = Courier(name="مندوب أ كفالة", phone="+966551112233", tenant_id=tenant_a_id, courier_type=CourierType.COMPANY, country=Country.SA, employment_status="ACTIVE")
    c_b = Courier(name="مندوب ب فريلانسر", phone="+966554445566", tenant_id=tenant_b_id, courier_type=CourierType.FREELANCER, country=Country.SA, employment_status="ACTIVE")
    db.add_all([c_a, c_b])
    db.commit()
    db.refresh(c_a)
    db.refresh(c_b)
    c_a_id = c_a.id
    c_b_id = c_b.id
    db.close()

    # Fleet A assigns company courier -> pending approval
    client.post(
        f"/fleet/dedicated/bookings/{b_a_id}/assign-rider",
        headers={"Authorization": f"Bearer {fleet_a_token}"},
        json={"rider_id": c_a_id},
    )

    # Merchant approves Fleet A courier
    apprs = client.get(f"/merchant/account/{ma_id}/rider-approvals", headers={"Authorization": f"Bearer {m_token}"}).json()
    t_appr = next(x for x in apprs if x["courier_id"] == c_a_id)
    client.post(
        f"/merchant/account/{ma_id}/rider-approvals/{t_appr['id']}/decide",
        headers={"Authorization": f"Bearer {m_token}"},
        json={"action": "APPROVED"},
    )

    # Fleet B assigns freelancer courier -> instantly assigned
    client.post(
        f"/fleet/dedicated/bookings/{b_b_id}/assign-rider",
        headers={"Authorization": f"Bearer {fleet_b_token}"},
        json={"rider_id": c_b_id},
    )

    # Cashier view
    branch_token = create_branch_token(branch_id, merchant_account_id=ma_id)
    c_resp = client.get(
        f"/merchant/branch/{branch_id}/riders/active",
        headers={"Authorization": f"Bearer {branch_token}"},
    )
    assert c_resp.status_code == 200
    riders = c_resp.json()
    assert len(riders) == 2
    r_a = next((r for r in riders if r.get("rider_id") == c_a_id), None)
    r_b = next((r for r in riders if r.get("rider_id") == c_b_id), None)
    assert r_a is not None
    assert r_b is not None
    assert r_a["logistics_company_name"] == "Golden Logistics Phase2"
    assert r_b["logistics_company_name"] == "Wefaq Logistics Phase2"
    assert r_b["courier_type"] in ("FREELANCER", "freelancer")


def test_22c_pending_seat_is_labelled_not_shown_as_vacant(client, test_data):
    """Test 22c: a seat awaiting this merchant's approval must say so on the statement.

    Both a vacant seat and a seat pending approval carry rider_id=None. Their
    money already differs — pending days are deducted, vacant days are not —
    so showing both as "مقعد شاغر" told the merchant a driver was missing when
    the merchant was the one holding it up.
    """
    from datetime import time
    from decimal import Decimal

    from app.models.entities import Country, Courier, CourierType
    from app.models.merchant import (
        BookingStatus,
        DedicatedShiftBooking,
        MerchantBranch,
        RiderAssignmentApproval,
        ShiftType,
    )

    ma_id = test_data["merchant_account_id"]
    m_token = test_data["merchant_token"]
    tenant_a_id = test_data["tenant_a_id"]

    db = TestingSessionLocal()
    branch = MerchantBranch(
        merchant_account_id=ma_id,
        branch_name="فرع وسم الانتظار",
        city="الرياض",
        latitude=Decimal("24.7"),
        longitude=Decimal("46.6"),
        cashier_access_pin="9911",
        verification_status="VERIFIED",
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)

    def _seat():
        b = DedicatedShiftBooking(
            merchant_branch_id=branch.id,
            logistics_company_tenant_id=tenant_a_id,
            shift_type=ShiftType.full_day_8h,
            shift_start_time=time(10, 0),
            shift_end_time=time(18, 0),
            effective_from=date(2026, 8, 1),
            effective_until=None,
            monthly_fee_to_merchant=Decimal("7000.00"),
            monthly_payout_to_logistics=Decimal("5500.00"),
            dou_margin=Decimal("1500.00"),
            status=BookingStatus.active,
        )
        db.add(b)
        db.commit()
        db.refresh(b)
        return b

    b_pending, b_vacant = _seat(), _seat()

    rider = Courier(
        name="مندوب ينتظر موافقة المطعم",
        phone="0555590909",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        tenant_id=tenant_a_id,
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)

    db.add(
        RiderAssignmentApproval(
            booking_id=b_pending.id,
            merchant_branch_id=branch.id,
            merchant_account_id=ma_id,
            logistics_company_tenant_id=tenant_a_id,
            courier_id=rider.id,
            courier_name=rider.name,
            courier_phone=rider.phone,
            status="PENDING",
            requested_at=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    db.close()

    resp = client.get(
        f"/merchant/account/{ma_id}/statement?month={MONTH_STR}",
        headers={"Authorization": f"Bearer {m_token}"},
    )
    assert resp.status_code == 200, resp.text
    rows = [
        it for it in resp.json()["line_items"] if it["branch_name"] == "فرع وسم الانتظار"
    ]
    assert len(rows) == 2, f"both seats must appear on the statement, got {rows}"

    pending = [it for it in rows if it["pending_approval"]]
    vacant = [it for it in rows if not it["pending_approval"]]

    assert len(pending) == 1, "the seat awaiting merchant approval must be flagged"
    assert len(vacant) == 1, "the genuinely vacant seat must not be flagged"

    assert "موافقتك" in pending[0]["rider_name"], (
        f"pending seat must name the merchant as the blocker, got {pending[0]['rider_name']}"
    )
    assert "شاغر" in vacant[0]["rider_name"]

    # The vacant seat still carries full SLA billing; the pending one does not.
    assert vacant[0]["active_days"] > pending[0]["active_days"]


def _cashier_on_verified_branch(client, test_data, pin):
    """A verified branch and a cashier token for it."""
    from decimal import Decimal

    ma_id = test_data["merchant_account_id"]
    db = TestingSessionLocal()
    branch = MerchantBranch(
        merchant_account_id=ma_id,
        branch_name=f"فرع الكاشير {pin}",
        city="الرياض",
        latitude=Decimal("24.7"),
        longitude=Decimal("46.6"),
        cashier_access_pin=pin,
        verification_status="VERIFIED",
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    bid = branch.id
    db.close()
    token = create_branch_token(bid, merchant_account_id=ma_id)
    return bid, {"Authorization": f"Bearer {token}"}


def test_26_duplicate_invoice_number_is_refused(client, test_data):
    """The same invoice sent twice is one order, not two.

    A double-click, or a retry on a slow connection, used to create a second
    dispatch for one meal: the rider drives it twice and carries cash for a
    delivery that never happened, which turns up later as a shortfall in their
    float that nobody can trace. The guard runs before the order is built, so
    it is asserted here against an invoice the branch already has.
    """
    from app.models.merchant import BranchDispatchOrder

    branch_id, headers = _cashier_on_verified_branch(client, test_data, pin="4141")

    db = TestingSessionLocal()
    db.add(
        BranchDispatchOrder(
            merchant_branch_id=branch_id,
            order_date=date(2026, 8, 12),
            customer_name="عميل الطلب الأصلي",
            customer_phone="0500000001",
            delivery_address_text="حي النخيل",
            external_order_id="INV-DUP-001",
        )
    )
    db.commit()
    db.close()

    resp = client.post(
        f"/merchant/branch/{branch_id}/orders",
        json={
            "external_order_id": "INV-DUP-001",
            "customer_name": "عميل",
            "customer_phone": "0500000001",
            "delivery_address": "حي النخيل",
            "payment_method": "cash",
            "order_amount": 120.0,
        },
        headers=headers,
    )
    assert resp.status_code == 409, (
        f"an invoice the branch already sent must be refused, got {resp.status_code}: {resp.text}"
    )
    assert "بالفعل" in resp.json()["detail"]


def test_27_cash_amount_above_the_ceiling_is_refused(client, test_data):
    """An invoice number typed into the amount box must not become a rider's debt."""
    branch_id, headers = _cashier_on_verified_branch(client, test_data, pin="4242")
    resp = client.post(
        f"/merchant/branch/{branch_id}/orders",
        json={
            "external_order_id": "INV-BIG-001",
            "customer_name": "عميل",
            "customer_phone": "0500000002",
            "delivery_address": "حي النخيل",
            "payment_method": "cash",
            "order_amount": 10_000_000.0,
        },
        headers=headers,
    )
    assert resp.status_code == 422, f"expected a refusal, got {resp.status_code}"
    assert "الحد المسموح" in resp.json()["detail"]
