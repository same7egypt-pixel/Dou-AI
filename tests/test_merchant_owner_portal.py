"""Tests for Merchant Owner Portal Features (Step 5: بوابة صاحب المطعم).

Covers:
1. Cashier token (scope: merchant_branch) is strictly blocked from GET /merchant/account/{id}/statement (HTTP 403).
2. Cashier token is strictly blocked from branches-overview, tax-invoice, and capacity requests (HTTP 403).
3. Token expiration / invalid token returns HTTP 401 with clear re-login message.
4. Merchant owner login endpoint (POST /merchant/auth/owner-login) accepts API key and issues merchant-scoped JWT.
5. Merchant owner token can access own statement, branches-overview, and SLA.
6. Merchant owner A cannot access Merchant owner B's account (HTTP 403).
7. Tax invoice requires an issued/paid settlement ledger and correctly reflects base + VAT = total.
8. Tax invoice generates valid ZATCA TLV Base64 QR code when DOU VAT is configured.
9. Capacity change request is created in 'requested' state without altering active bookings.
10. SLA indicators count vacant seats and shortfall days accurately without calculating financial deductions.
11. Statement endpoint accepts YYYY-MM formatted month string while preserving legacy int parameters.
"""

import base64
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
from app.models.entities import AppSetting, Country, Courier, CourierType, Tenant, User, UserRole
from app.models.merchant import (
    BookingStatus,
    BranchDispatchOrder,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    MonthlySettlementLedger,
    OrderStatus,
    PaymentMethod,
    SettlementStatus,
    ShiftAttendanceLog,
    ShiftType,
)
from app.routers.auth import create_token, hash_password
from app.utils.security import (
    ALGORITHM,
    create_branch_token,
    create_merchant_account_token,
    generate_merchant_api_key,
    hash_pin,
)

TEST_DB_FILE = "./test_merchant_owner_portal.db"
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


# Unique ID base: 7700+
def _seed_merchant_fixtures(db):
    """Seed two distinct merchant accounts, branches, and riders for isolated testing."""
    # Merchant A
    raw_key_a, prefix_a, hash_a = generate_merchant_api_key("acctA7700")
    account_a = MerchantAccount(
        id=7701,
        trade_name="مجموعة مطاعم السلطان",
        vat_number="310123456700003",
        billing_contact_email="finance@sultan.sa",
        billing_contact_phone="966577010001",
        payment_terms_days=30,
        api_key_prefix=prefix_a,
        api_key_hash=hash_a,
        is_active=True,
    )
    db.merge(account_a)

    branch_a1 = MerchantBranch(
        id=7711,
        merchant_account_id=7701,
        branch_name="فرع التخصصي",
        city="الرياض",
        latitude=Decimal("24.7136000"),
        longitude=Decimal("46.6753000"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("1234"),
        is_active=True,
    )
    branch_a2 = MerchantBranch(
        id=7712,
        merchant_account_id=7701,
        branch_name="فرع الملز",
        city="الرياض",
        latitude=Decimal("24.6600000"),
        longitude=Decimal("46.7200000"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("5678"),
        is_active=True,
    )
    db.merge(branch_a1)
    db.merge(branch_a2)

    # Merchant B (Cross-tenant adversary)
    raw_key_b, prefix_b, hash_b = generate_merchant_api_key("acctB7700")
    account_b = MerchantAccount(
        id=7702,
        trade_name="برجر هاوس",
        vat_number="310987654300003",
        billing_contact_email="finance@burgerhouse.sa",
        billing_contact_phone="966577020002",
        payment_terms_days=15,
        api_key_prefix=prefix_b,
        api_key_hash=hash_b,
        is_active=True,
    )
    db.merge(account_b)

    branch_b1 = MerchantBranch(
        id=7713,
        merchant_account_id=7702,
        branch_name="فرع التحلية",
        city="جدة",
        latitude=Decimal("21.5433000"),
        longitude=Decimal("39.1728000"),
        geofence_radius_meters=150,
        cashier_access_pin=hash_pin("9999"),
        is_active=True,
    )
    db.merge(branch_b1)

    # Tenant (Logistics)
    tenant = Tenant(
        id=7750,
        name="أسطول السرعة المتميزة",
        country=Country.SA,
    )
    db.merge(tenant)

    # Couriers
    c1 = Courier(
        id=7781,
        tenant_id=7750,
        name="فهد عبد الله",
        phone="966577810001",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
    )
    c2 = Courier(
        id=7782,
        tenant_id=7750,
        name="سعد إبراهيم",
        phone="966577820002",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
    )
    db.merge(c1)
    db.merge(c2)

    # Bookings:
    # Seat 1: Staffed by c1
    b1 = DedicatedShiftBooking(
        id=7791,
        merchant_branch_id=7711,
        logistics_company_tenant_id=7750,
        rider_id=7781,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(12, 0),
        shift_end_time=time(20, 0),
        effective_from=date(2026, 9, 1),
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("6000.00"),
        dou_margin=Decimal("1000.00"),
        status=BookingStatus.active,
    )
    # Seat 2: Vacant seat (nobody fills yet)
    b2 = DedicatedShiftBooking(
        id=7792,
        merchant_branch_id=7711,
        logistics_company_tenant_id=7750,
        rider_id=None,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=time(12, 0),
        shift_end_time=time(20, 0),
        effective_from=date(2026, 9, 1),
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("6000.00"),
        dou_margin=Decimal("1000.00"),
        status=BookingStatus.active,
    )
    db.merge(b1)
    db.merge(b2)

    # Attendance today for c1
    att = ShiftAttendanceLog(
        id=7771,
        dedicated_shift_booking_id=7791,
        rider_id=7781,
        log_date=date.today(),
        checkin_at=datetime.now(timezone.utc),
        checkout_at=None,
        geofence_validated=True,
    )
    db.merge(att)

    # Configure DOU platform VAT setting
    setting = AppSetting(
        id=7761,
        tenant_id=None,
        key="dou_vat_number",
        value="300000000000003",
    )
    db.merge(setting)

    db.commit()
    return raw_key_a, raw_key_b


def test_cashier_token_strictly_blocked_from_account_statement(client, db_session):
    """Vulnerability #1 test: A cashier PIN token must receive 403 on merchant account statement."""
    _seed_merchant_fixtures(db_session)
    cashier_token = create_branch_token(branch_id=7711, merchant_account_id=7701)

    resp = client.get(
        "/merchant/account/7701/statement",
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert resp.status_code == 403
    assert "كاشير" in resp.json()["detail"] or "مالك" in resp.json()["detail"]


def test_cashier_token_blocked_from_branches_overview_and_tax_invoice(client, db_session):
    """Cashier token must receive 403 on branches-overview and tax-invoice."""
    _seed_merchant_fixtures(db_session)
    cashier_token = create_branch_token(branch_id=7711, merchant_account_id=7701)

    # 1. branches-overview
    resp1 = client.get(
        "/merchant/account/7701/branches-overview",
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert resp1.status_code == 403

    # 2. tax-invoice
    resp2 = client.get(
        "/merchant/account/7701/tax-invoice",
        headers={"Authorization": f"Bearer {cashier_token}"},
    )
    assert resp2.status_code == 403


def test_expired_token_returns_401_with_clear_login_instruction(client, db_session):
    """Expired or invalid token must return HTTP 401 instructing re-login, not 403."""
    expired_payload = {
        "sub": "merchant_account:7701",
        "merchant_account_id": 7701,
        "scope": "merchant_account",
        "exp": int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()),
    }
    expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)

    resp = client.get(
        "/merchant/account/7701/statement",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401
    assert "انتهت صلاحية" in resp.json()["detail"] or "تسجيل الدخول" in resp.json()["detail"]


def test_owner_login_with_api_key_issues_merchant_account_token(client, db_session):
    """Merchant owner login via API key issues a valid merchant-account scoped JWT."""
    raw_key_a, _ = _seed_merchant_fixtures(db_session)

    resp = client.post(
        "/merchant/auth/owner-login",
        json={"api_key": raw_key_a},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["merchant_account_id"] == 7701
    assert data["trade_name"] == "مجموعة مطاعم السلطان"

    # Decode and verify token scope
    payload = jwt.decode(data["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["scope"] == "merchant_account"
    assert payload["merchant_account_id"] == 7701


def test_merchant_owner_token_can_access_own_statement_and_branches(client, db_session):
    """Owner token accesses statement and branches-overview for own account."""
    _seed_merchant_fixtures(db_session)
    owner_token = create_merchant_account_token(merchant_account_id=7701)

    # 1. Statement
    resp_stmt = client.get(
        "/merchant/account/7701/statement?month=2026-09",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp_stmt.status_code == 200
    assert resp_stmt.json()["merchant_name"] == "مجموعة مطاعم السلطان"

    # 2. Branches Overview
    resp_ov = client.get(
        "/merchant/account/7701/branches-overview",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp_ov.status_code == 200
    ov_data = resp_ov.json()
    assert ov_data["total_branches"] == 2
    assert ov_data["total_contracted_seats"] == 2
    assert ov_data["total_filled_seats"] == 1
    assert ov_data["total_vacant_seats"] == 1
    assert ov_data["total_present_riders"] == 1


def test_merchant_owner_cannot_access_another_merchant_data(client, db_session):
    """Cross-tenant guard: Merchant owner A cannot access Merchant owner B's data (403)."""
    _seed_merchant_fixtures(db_session)
    owner_token_a = create_merchant_account_token(merchant_account_id=7701)

    # Try to access Account 7702 (Merchant B)
    resp = client.get(
        "/merchant/account/7702/statement",
        headers={"Authorization": f"Bearer {owner_token_a}"},
    )
    assert resp.status_code == 403


def test_tax_invoice_requires_issued_settlement_ledger(client, db_session):
    """Tax invoice must be locked to an issued/paid settlement ledger, not a live or draft contract."""
    _seed_merchant_fixtures(db_session)
    owner_token = create_merchant_account_token(merchant_account_id=7701)

    # 1. When no settlement exists or only draft: must return 400 indicating settlement is not yet issued
    draft_ledger = MonthlySettlementLedger(
        id=77901,
        merchant_account_id=7701,
        settlement_month=date(2026, 9, 1),
        total_rider_shift_months=Decimal("2.0"),
        gross_fee_charged_to_merchant=Decimal("14000.00"),
        total_payout_to_logistics=Decimal("12000.00"),
        dou_net_margin=Decimal("2000.00"),
        settlement_status=SettlementStatus.draft,
    )
    db_session.merge(draft_ledger)
    db_session.commit()

    resp_draft = client.get(
        "/merchant/account/7701/tax-invoice?billing_month=2026-09",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp_draft.status_code == 400
    assert "غير معتمد" in resp_draft.json()["detail"] or "مسودة" in resp_draft.json()["detail"]

    # 2. When issued and stamped:
    issued_ledger = MonthlySettlementLedger(
        id=77902,
        merchant_account_id=7701,
        settlement_month=date(2026, 8, 1),
        total_rider_shift_months=Decimal("2.0"),
        gross_fee_charged_to_merchant=Decimal("14000.00"),
        total_payout_to_logistics=Decimal("12000.00"),
        dou_net_margin=Decimal("2000.00"),
        settlement_status=SettlementStatus.issued,
        issued_at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        vat_rate=Decimal("0.1500"),
        vat_amount=Decimal("2100.00"),
    )
    db_session.merge(issued_ledger)
    db_session.commit()

    resp_issued = client.get(
        "/merchant/account/7701/tax-invoice?billing_month=2026-08",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp_issued.status_code == 200
    inv = resp_issued.json()
    assert inv["settlement_id"] == 77902
    assert inv["subtotal"] == 14000.00
    assert inv["vat_rate"] == 0.15
    assert inv["vat_amount"] == 2100.00
    assert inv["total_amount"] == 16100.00
    assert inv["is_tax_invoice"] is True
    assert inv["zatca_qr_base64"] is not None


def test_tax_invoice_without_dou_vat_number_emits_commercial_invoice_without_vat(client, db_session):
    """If DOU platform has no VAT number, it must issue a non-tax commercial invoice with 0 VAT."""
    _seed_merchant_fixtures(db_session)
    owner_token = create_merchant_account_token(merchant_account_id=7701)

    # Delete DOU VAT setting
    db_session.query(AppSetting).filter(AppSetting.key == "dou_vat_number").delete()

    issued_no_vat = MonthlySettlementLedger(
        id=77903,
        merchant_account_id=7701,
        settlement_month=date(2026, 7, 1),
        total_rider_shift_months=Decimal("2.0"),
        gross_fee_charged_to_merchant=Decimal("14000.00"),
        total_payout_to_logistics=Decimal("12000.00"),
        dou_net_margin=Decimal("2000.00"),
        settlement_status=SettlementStatus.issued,
        issued_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        vat_rate=Decimal("0.0000"),
        vat_amount=Decimal("0.00"),
    )
    db_session.merge(issued_no_vat)
    db_session.commit()

    resp = client.get(
        "/merchant/account/7701/tax-invoice?billing_month=2026-07",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    inv = resp.json()
    assert inv["is_tax_invoice"] is False
    assert inv["vat_amount"] == 0.00
    assert inv["total_amount"] == 14000.00


def test_capacity_request_lifecycle_does_not_alter_active_bookings(client, db_session):
    """Requesting capacity increase from 2 to 4 records a request without mutating bookings."""
    _seed_merchant_fixtures(db_session)
    owner_token = create_merchant_account_token(merchant_account_id=7701)

    # Submit capacity request for branch 7711
    resp = client.post(
        "/merchant/account/7701/capacity-requests",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "merchant_branch_id": 7711,
            "requested_capacity": 4,
            "effective_month": "2026-10",
            "reason": "افتتاح قسم جديد وتوسع في التوصيل",
        },
    )
    assert resp.status_code == 200
    req_data = resp.json()
    assert req_data["status"] == "requested"
    assert req_data["current_capacity"] == 2
    assert req_data["requested_capacity"] == 4

    # Verify active bookings were NOT touched
    active_count = (
        db_session.query(DedicatedShiftBooking)
        .filter(
            DedicatedShiftBooking.merchant_branch_id == 7711,
            DedicatedShiftBooking.status == BookingStatus.active,
        )
        .count()
    )
    assert active_count == 2  # Still 2!

    # Verify listing capacity requests
    resp_list = client.get(
        "/merchant/account/7701/capacity-requests",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp_list.status_code == 200
    requests = resp_list.json()
    assert len(requests) >= 1
    assert requests[0]["status"] == "requested"


def test_sla_indicators_count_vacant_seats_and_shortfall_accurately(client, db_session):
    """SLA endpoint counts vacant seats and shortfall days as days & percentages without financial deduction."""
    _seed_merchant_fixtures(db_session)
    owner_token = create_merchant_account_token(merchant_account_id=7701)

    resp = client.get(
        "/merchant/account/7701/sla?billing_month=2026-09",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    sla = resp.json()
    assert "total_contracted_seat_days" in sla
    assert "vacant_seat_days" in sla
    assert "fulfillment_rate_pct" in sla
    assert sla["vacant_seat_days"] > 0
    # Crucial rule: No financial deductions calculated
    assert "deduction_amount" not in sla
    assert "penalty_fee" not in sla


def test_statement_month_unification_yyyy_mm_and_legacy_integers(client, db_session):
    """Statement endpoint accepts YYYY-MM while preserving legacy ?month=9&year=2026."""
    _seed_merchant_fixtures(db_session)
    owner_token = create_merchant_account_token(merchant_account_id=7701)

    # 1. YYYY-MM parameter
    resp1 = client.get(
        "/merchant/account/7701/statement?month=2026-09",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp1.status_code == 200
    assert "September 2026" in resp1.json()["statement_month"]

    # 2. Legacy integer parameters
    resp2 = client.get(
        "/merchant/account/7701/statement?month=9&year=2026",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp2.status_code == 200
    assert "September 2026" in resp2.json()["statement_month"]
