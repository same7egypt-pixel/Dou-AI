"""Negative and regression tests for Super Admin Portal (Step 3: لوحة السوبر أدمن).

Covers:
1. test_backup_status_measures_reality_not_static_string
2. test_unified_monthly_revenue_combines_subscriptions_and_flex_margin
3. test_finance_summary_totals_by_currency_matches_api
4. test_unconfigured_company_billing_surfaced_as_alert
5. test_bulk_contract_seats_creates_n_vacant_bookings
6. test_settlement_ledger_lifecycle_and_immutability
7. test_finance_six_months_trend_history
"""

import os
import shutil
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import SECRET_KEY
from app.database import Base, get_db
from app.main import app
from app.models.entities import Country, Courier, CourierType, SubscriptionPayment, Tenant, User, UserRole
from app.models.merchant import (
    BookingStatus,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    MonthlySettlementLedger,
    SettlementStatus,
    ShiftType,
)
from app.utils.security import hash_pin

TEST_DB_FILE = "./test_superadmin_portal.db"
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

    # Seed Admin user
    db = TestingSessionLocal()
    admin_user = User(
        id=777,
        tenant_id=1,
        name="Super Admin",
        phone="+966500000777",
        password_hash="testhash",
        role=UserRole.DOU_ADMIN,
        is_active=True,
        token_version=0,
    )
    db.merge(admin_user)
    db.commit()
    db.close()

    yield

    app.dependency_overrides.pop(get_db, None)
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)


def make_admin_token() -> str:
    payload = {
        "sub": "777",
        "tenant_id": 1,
        "role": "DOU_ADMIN",
        "ver": 0,
        "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


client = TestClient(app)


# ─── 1. Backup Status Reality Check ───────────────────────────────────────────

def test_backup_status_measures_reality_not_static_string(monkeypatch):
    """Backup status must never return static 'MANAGED_EXTERNALLY'.
    It must inspect BACKUP_DIR, report last backup timestamp, size, destination,
    and return NO_BACKUPS_FOUND if directory is empty."""
    headers = {"Authorization": f"Bearer {make_admin_token()}"}

    tmp_dir = tempfile.mkdtemp()
    try:
        monkeypatch.setenv("BACKUP_DIR", tmp_dir)
        monkeypatch.delenv("BACKUP_S3_BUCKET", raising=False)

        # 1. When empty -> NO_BACKUPS_FOUND
        res = client.get("/admin/system-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["backup_status"] != "MANAGED_EXTERNALLY", "Must not be hardcoded static text"
        assert data["backup_status"] == "NO_BACKUPS_FOUND"
        assert data["backup_details"]["has_backups"] is False

        # 2. When a dump exists -> measured size, mtime, and LOCAL_ONLY
        fake_dump = os.path.join(tmp_dir, "dou_postgres_20260905_120000.dump")
        with open(fake_dump, "wb") as f:
            f.write(b"0" * 2048)  # 2 KB dummy dump

        res = client.get("/admin/system-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["backup_status"] == "LOCAL_ONLY_WARNING"
        assert data["backup_details"]["has_backups"] is True
        assert data["backup_details"]["last_backup_file"] == "dou_postgres_20260905_120000.dump"
        assert data["backup_details"]["size_bytes"] == 2048
        assert data["backup_details"]["storage_destination"] == "LOCAL_ONLY"
        assert data["backup_details"]["is_offsite"] is False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── 2. Unified Monthly Revenue ───────────────────────────────────────────────

def test_unified_monthly_revenue_combines_subscriptions_and_flex_margin():
    """GET /admin/dashboard must return total unified revenue = subscriptions + flex margins."""
    db = TestingSessionLocal()
    tenant = Tenant(
        id=10,
        name="Logistics One",
        country=Country.SA,
        market_code="SA",
        subscription_status="ACTIVE",
        monthly_fee=1500.0,
        currency="SAR",
    )
    db.merge(tenant)

    # Subscription payment this month
    now = datetime.utcnow()
    sp = SubscriptionPayment(
        tenant_id=10,
        amount=1500.0,
        currency="SAR",
        paid_at=now,
        receipt_number="RCP-UNIFIED-01",
        payment_method="BANK_TRANSFER",
    )
    db.add(sp)

    # Merchant + Branch + Active dedicated booking with 1500 SAR margin
    merchant = MerchantAccount(
        id=101,
        trade_name="Burger House",
        billing_contact_email="bh@test.com",
        billing_contact_phone="0500000101",
        is_active=True,
    )
    db.merge(merchant)
    from app.models.entities import GeoCity, GeoCountry, TenantOperatingCity
    country = db.query(GeoCountry).filter(GeoCountry.code == "SA").first()
    if not country:
        country = GeoCountry(name="المملكة العربية السعودية", code="SA", flag="🇸🇦", active=True)
        db.add(country)
        db.flush()
    city1 = db.query(GeoCity).filter(GeoCity.id == 1).first()
    if not city1:
        city1 = GeoCity(id=1, country_id=country.id, name="الرياض", active=True)
        db.add(city1)
        db.flush()
    top1 = db.query(TenantOperatingCity).filter(TenantOperatingCity.tenant_id == 10, TenantOperatingCity.geo_city_id == 1).first()
    if not top1:
        top1 = TenantOperatingCity(tenant_id=10, geo_city_id=1, is_active=True)
        db.add(top1)
        db.flush()

    branch = MerchantBranch(
        id=101,
        merchant_account_id=101,
        branch_name="Malaz",
        city="الرياض",
        city_id=1,
        latitude=Decimal("24.7136"),
        longitude=Decimal("46.6753"),
        cashier_access_pin=hash_pin("1234"),
        is_active=True,
    )
    db.merge(branch)

    booking = DedicatedShiftBooking(
        id=101,
        merchant_branch_id=101,
        logistics_company_tenant_id=10,
        rider_id=None,
        shift_type=ShiftType.full_day_8h,
        shift_start_time=datetime.strptime("12:00", "%H:%M").time(),
        shift_end_time=datetime.strptime("20:00", "%H:%M").time(),
        effective_from=date.today(),
        monthly_fee_to_merchant=Decimal("7000.00"),
        monthly_payout_to_logistics=Decimal("5500.00"),
        dou_margin=Decimal("1500.00"),
        status=BookingStatus.active,
    )
    db.merge(booking)
    db.commit()
    db.close()

    headers = {"Authorization": f"Bearer {make_admin_token()}"}
    res = client.get("/admin/dashboard", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # Subscriptions (1500) + Flex margin (1500) = 3000
    assert "subscription_revenue" in data
    assert "flex_margin_revenue" in data
    assert data["subscription_revenue"] == 1500.0
    assert data["flex_margin_revenue"] == 1500.0
    assert data["monthly_revenue"] == 3000.0


# ─── 3. Collections Totals By Currency Fix ───────────────────────────────────

def test_finance_summary_totals_by_currency_matches_api():
    """GET /admin/finance/summary must return totals_by_currency matching frontend expectations."""
    headers = {"Authorization": f"Bearer {make_admin_token()}"}
    res = client.get("/admin/finance/summary", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert "totals_by_currency" in data, "Frontend platform.js expects data.totals_by_currency"
    sar_totals = data["totals_by_currency"].get("SAR", {})
    assert "expected" in sar_totals
    assert "collected" in sar_totals
    assert "overdue" in sar_totals
    assert sar_totals["expected"] >= 1500.0


# ─── 4. Unconfigured Billing Detection ───────────────────────────────────────

def test_unconfigured_company_billing_surfaced_as_alert():
    """Tenants with due_date=None must be counted in unconfigured_companies and flagged."""
    db = TestingSessionLocal()
    unconf_tenant = Tenant(
        id=20,
        name="Demo Logistics No Due Date",
        country=Country.SA,
        subscription_status="ACTIVE",
        monthly_fee=999.0,
        due_date=None,  # Unconfigured!
        currency="SAR",
    )
    db.merge(unconf_tenant)
    db.commit()
    db.close()

    headers = {"Authorization": f"Bearer {make_admin_token()}"}
    res = client.get("/admin/finance/summary", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert "unconfigured_companies" in data
    assert data["unconfigured_companies"] >= 1
    unconf_row = next((r for r in data["rows"] if r["tenant_id"] == 20), None)
    assert unconf_row is not None
    assert unconf_row["collection_status"] == "UNCONFIGURED"


# ─── 5. Bulk Contract Seats & Vacant Seats ───────────────────────────────────

def test_bulk_contract_seats_creates_n_vacant_bookings():
    """POST /admin/dedicated/bookings accepts seats_count and creates N vacant seats with rider_id=None."""
    headers = {"Authorization": f"Bearer {make_admin_token()}"}
    payload = {
        "merchant_branch_id": 101,
        "logistics_company_tenant_id": 10,
        "seats_count": 4,
        "shift_type": "full_day_8h",
        "monthly_fee_to_merchant": 7000.0,
        "monthly_payout_to_logistics": 5500.0,
    }
    res = client.post("/admin/dedicated/bookings", json=payload, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["ok"] is True
    assert data.get("created_count") == 4
    assert len(data.get("booking_ids", [])) == 4

    # Verify listings show rider_id is None
    list_res = client.get("/admin/dedicated/bookings", headers=headers)
    assert list_res.status_code == 200
    b_rows = list_res.json()
    created_rows = [b for b in b_rows if b["id"] in data["booking_ids"]]
    assert len(created_rows) == 4
    for b in created_rows:
        assert b["rider_id"] is None
        assert b["rider_name"] is None


# ─── 6. Settlement Ledger Lifecycle & Immutability ───────────────────────────

def _seed_billable_merchant(merchant_id: int):
    """A merchant with one branch and one active seat — enough to settle a month.

    This test used to read merchant 101, which is seeded inside
    test_unified_monthly_revenue. It therefore passed only when that test had
    already run, and failed on its own — a guard that depends on execution
    order is not guarding anything, and what this one guards is an issued
    settlement's immutability, which is money. It seeds its own merchant now.
    """
    db = TestingSessionLocal()
    db.merge(
        MerchantAccount(
            id=merchant_id,
            trade_name="Settlement Test Co",
            billing_contact_email="settle@test.com",
            billing_contact_phone="0500000102",
            is_active=True,
        )
    )
    db.merge(
        MerchantBranch(
            id=merchant_id,
            merchant_account_id=merchant_id,
            branch_name="Settlement Branch",
            city="الرياض",
            latitude=Decimal("24.7136"),
            longitude=Decimal("46.6753"),
            cashier_access_pin=hash_pin("1234"),
            is_active=True,
        )
    )
    db.merge(
        DedicatedShiftBooking(
            id=merchant_id,
            merchant_branch_id=merchant_id,
            logistics_company_tenant_id=10,
            rider_id=None,
            shift_type=ShiftType.full_day_8h,
            shift_start_time=datetime.strptime("12:00", "%H:%M").time(),
            shift_end_time=datetime.strptime("20:00", "%H:%M").time(),
            effective_from=date.today().replace(day=1),
            monthly_fee_to_merchant=Decimal("7000.00"),
            monthly_payout_to_logistics=Decimal("5500.00"),
            dou_margin=Decimal("1500.00"),
            status=BookingStatus.active,
        )
    )
    db.commit()
    db.close()


def test_settlement_ledger_lifecycle_and_immutability():
    """Covers: generate (draft) -> issue (locks record) -> pay (records reference)."""
    headers = {"Authorization": f"Bearer {make_admin_token()}"}
    month_str = date.today().strftime("%Y-%m")
    _seed_billable_merchant(102)

    # 1. Generate / Retrieve Draft Settlements
    gen_res = client.post(
        "/admin/dedicated/settlements/generate",
        json={"month": month_str, "merchant_id": 102},
        headers=headers,
    )
    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    assert len(gen_data["settlements"]) >= 1
    st = gen_data["settlements"][0]
    settlement_id = st["id"]
    assert st["settlement_status"] == "draft"
    assert st["gross_fee_charged_to_merchant"] > 0
    assert st["total_payout_to_logistics"] > 0
    assert st["dou_net_margin"] > 0

    # 2. Issue Settlement (Transitions from draft -> issued, stamped)
    issue_res = client.post(
        f"/admin/dedicated/settlements/{settlement_id}/issue",
        headers=headers,
    )
    assert issue_res.status_code == 200
    issued_data = issue_res.json()
    assert issued_data["settlement_status"] == "issued"
    assert issued_data["issued_at"] is not None

    # 3. Rule 6 Immutability: Re-issuing or regenerating over issued record must not alter it
    reissue_res = client.post(
        f"/admin/dedicated/settlements/{settlement_id}/issue",
        headers=headers,
    )
    assert reissue_res.status_code == 400

    # 4. Pay Settlement (Transitions from issued -> paid with reference)
    pay_res = client.post(
        f"/admin/dedicated/settlements/{settlement_id}/pay",
        json={"bank_transfer_reference": "SAR-TRANSFER-99214"},
        headers=headers,
    )
    assert pay_res.status_code == 200
    paid_data = pay_res.json()
    assert paid_data["settlement_status"] == "paid"
    assert paid_data["paid_at"] is not None
    assert paid_data["bank_transfer_reference"] == "SAR-TRANSFER-99214"


# ─── 7. 6-Month Historical Revenue Trend ──────────────────────────────────────

def test_finance_six_months_trend_history():
    """GET /admin/finance/summary must return 6 months history (collected vs expected)."""
    headers = {"Authorization": f"Bearer {make_admin_token()}"}
    res = client.get("/admin/finance/summary", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert "history" in data, "Must return historical time horizon"
    history = data["history"]
    assert len(history) == 6, "Must provide exactly the last 6 months for trajectory"
    for item in history:
        assert "month" in item
        assert "collected" in item
        assert "expected" in item
