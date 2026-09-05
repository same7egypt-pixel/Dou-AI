from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import Country, Courier, CourierType, DailyLog, Tenant
from app.routers.driver_dedicated import _record_delivery_to_daily_log

TEST_DB_URL = "sqlite:///./test_audit_db.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

def test_fix_1_record_delivery_increments_orders_count():
    db = TestingSession()
    try:
        tenant = Tenant(name="Test Fleet", country=Country.SA, plan="STARTER")
        db.add(tenant)
        db.flush()

        courier = Courier(
            tenant_id=tenant.id,
            name="Test Courier",
            phone="966500000001",
            courier_type=CourierType.COMPANY,
            country=Country.SA,
        )
        db.add(courier)
        db.flush()

        test_date = date(2026, 9, 5)
        daily_log = DailyLog(
            courier_id=courier.id,
            tenant_id=tenant.id,
            project_id=None,
            log_date=test_date,
            orders_count=20,
            driver_orders=20,
            verified_orders=0,
            variance=0,
            source_type="MANUAL",
        )
        db.add(daily_log)
        db.commit()

        class MockOrder:
            order_date = test_date

        # Rider delivers 1 branch dispatch order
        _record_delivery_to_daily_log(MockOrder(), courier, db)
        db.commit()
        db.refresh(daily_log)

        assert daily_log.verified_orders == 1
        assert daily_log.orders_count == 21, f"Expected orders_count to be 21, but got {daily_log.orders_count}"
        assert daily_log.variance == 1
    finally:
        db.close()


def test_fix_2_cash_order_requires_positive_amount():
    from fastapi import HTTPException

    from app.models.merchant import PaymentMethod
    from app.routers.merchant import DispatchOrderRequest, dispatch_order

    db = TestingSession()
    try:
        # Case 1: order_amount is None
        req1 = DispatchOrderRequest(
            delivery_address="Riyadh, Olaya",
            payment_method=PaymentMethod.cash,
            order_amount=None,
        )
        with pytest.raises(HTTPException) as exc_info1:
            dispatch_order(branch_id=1, payload=req1, db=db, branch_id_from_token=1)
        assert exc_info1.value.status_code == 422
        assert exc_info1.value.detail == "طلب الدفع كاش يلزمه مبلغ التحصيل — لا يمكن إرسال المندوب بمبلغ صفر."

        # Case 2: order_amount <= 0
        req2 = DispatchOrderRequest(
            delivery_address="Riyadh, Olaya",
            payment_method=PaymentMethod.cash,
            order_amount=Decimal("0.00"),
        )
        with pytest.raises(HTTPException) as exc_info2:
            dispatch_order(branch_id=1, payload=req2, db=db, branch_id_from_token=1)
        assert exc_info2.value.status_code == 422
        assert exc_info2.value.detail == "طلب الدفع كاش يلزمه مبلغ التحصيل — لا يمكن إرسال المندوب بمبلغ صفر."
    finally:
        db.close()


def test_fix_3_admin_add_courier_enforces_plan_cap():
    """The plan cap holds on the admin path, and a rider still needs a real branch.

    add_courier now goes through create_rider_record, so it needs the same
    operating structure the fleet path needs — a live contract branch is what
    gives a rider their supervisor, project and city. The cap itself is
    enforced inside that shared path.
    """
    from fastapi import HTTPException

    from app.models.entities import SubscriptionPlan
    from app.routers.admin import CourierIn, add_courier

    db, admin, tenant, contract, branch = _admin_ctx()
    try:
        db.add(
            SubscriptionPlan(
                code="CAP1", name="Cap 1 Rider", monthly_price=100.0, max_couriers=1
            )
        )
        tenant.plan = "CAP1"
        db.commit()

        def _payload(name, phone, tenant_id=None):
            return CourierIn(
                name=name,
                phone=phone,
                tenant_id=tenant_id or tenant.id,
                password="RiderPass123!",
                contract_id=contract.id,
                contract_branch_id=branch.id,
            )

        first = add_courier(payload=_payload("Rider One", "966500000011"), db=db, user=admin)
        db.commit()
        assert first["id"] is not None

        with pytest.raises(HTTPException) as ghost:
            add_courier(
                payload=_payload("Rider Ghost", "966500000099", tenant_id=999999),
                db=db,
                user=admin,
            )
        assert ghost.value.status_code == 404

        with pytest.raises(HTTPException) as capped:
            add_courier(payload=_payload("Rider Two", "966500000012"), db=db, user=admin)
        assert capped.value.status_code in (422, 400)
        assert "الأقصى" in capped.value.detail
    finally:
        db.close()

def test_fix_3b_courier_in_requires_tenant_id():
    """Verify tenant_id is strictly required on CourierIn and cannot be omitted to bypass plan caps."""
    from pydantic import ValidationError
    from app.routers.admin import CourierIn

    with pytest.raises(ValidationError) as exc_info:
        CourierIn(name="Orphan Rider", phone="966500000099")
    errors = exc_info.value.errors()
    assert any("tenant_id" in err["loc"] for err in errors), "tenant_id must be a required field"


def test_fix_4_subscription_null_due_date_surfaced_in_alerts():
    from app.routers.admin import subscription_alerts

    db = TestingSession()
    try:
        tenant = Tenant(
            name="Escape Due Date Co",
            country=Country.SA,
            plan="PRO",
            subscription_status="ACTIVE",
            due_date=None,
        )
        db.add(tenant)
        db.commit()

        alerts = subscription_alerts(db=db)
        alert_tenants = [a for a in alerts if a["tenant_id"] == tenant.id]

        assert len(alert_tenants) == 1, "Tenant with due_date=None must be surfaced in subscription_alerts"
        assert alert_tenants[0]["due_date"] is None
        assert alert_tenants[0]["badge"] == "بلا تاريخ استحقاق"

        # 2. list_tenants surfaces badge
        from app.routers.admin import list_tenants, usage_summary
        tenants_list = list_tenants(db=db)
        matched = [t for t in tenants_list if t["id"] == tenant.id]
        assert len(matched) == 1
        assert matched[0]["due_date_badge"] == "بلا تاريخ استحقاق"

        # 3. usage_summary counts tenants without due_date
        usage = usage_summary(db=db)
        assert usage["no_due_date_tenants"] >= 1

        # 4. billing subscription update ensures due_date is assigned
        from app.models.entities import User, UserRole
        from app.routers.billing import SubscriptionPayload, billing_admin_subscribe
        admin_user = User(name="Admin", role=UserRole.DOU_ADMIN, phone="966500000000")
        res = billing_admin_subscribe(
            tid=tenant.id,
            payload=SubscriptionPayload(plan="PRO", monthly_fee=500.0, set_active=False),
            user=admin_user,
            db=db,
        )
        assert res["ok"] is True
        assert res["due_date"] is not None
        db.refresh(tenant)
        assert tenant.due_date is not None
    finally:
        db.close()


def test_fix_5_branch_without_city_cannot_be_booked():
    from fastapi import HTTPException

    from app.models.entities import User, UserRole
    from app.models.merchant import MerchantAccount, MerchantBranch
    from app.routers.admin_dedicated import CreateBookingPayload, create_booking_admin

    db = TestingSession()
    try:
        tenant = Tenant(name="Fast Logistics", country=Country.SA, plan="GROWTH")
        db.add(tenant)
        db.flush()

        merchant = MerchantAccount(
            trade_name="Tasty Burger",
            billing_contact_email="test@burger.com",
            billing_contact_phone="966500000001",
        )
        db.add(merchant)
        db.flush()

        # Branch with city_id = None
        branch = MerchantBranch(
            merchant_account_id=merchant.id,
            branch_name="Unmapped Branch",
            city="Riyadh",
            latitude=24.7136,
            longitude=46.6753,
            cashier_access_pin="1234",
            city_id=None,
        )
        db.add(branch)
        db.commit()

        admin_user = User(name="Super Admin", role=UserRole.DOU_ADMIN, phone="966500000099")

        payload = CreateBookingPayload(
            merchant_branch_id=branch.id,
            logistics_company_tenant_id=tenant.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            create_booking_admin(payload=payload, db=db, _=admin_user)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "الفرع غير مرتبط بمدينة معتمدة — حدد مدينة الفرع قبل إسناد العقد."
    finally:
        db.close()


def test_fix_6_unified_billable_bookings_filter():
    from datetime import time

    from app.models.entities import User, UserRole
    from app.models.merchant import (
        BookingStatus,
        DedicatedShiftBooking,
        MerchantAccount,
        MerchantBranch,
        ShiftType,
    )
    from app.routers.admin_dedicated import (
        GenerateSettlementsPayload,
        generate_settlements_admin,
    )
    from app.routers.merchant import _build_statement_line_items

    db = TestingSession()
    try:
        tenant = Tenant(name="Logistics One", country=Country.SA, plan="GROWTH")
        db.add(tenant)
        db.flush()

        merchant = MerchantAccount(
            trade_name="Pizza House",
            billing_contact_email="pizza@house.com",
            billing_contact_phone="966500000002",
        )
        db.add(merchant)
        db.flush()

        branch = MerchantBranch(
            merchant_account_id=merchant.id,
            branch_name="Branch 1",
            city="Riyadh",
            latitude=24.7,
            longitude=46.6,
            cashier_access_pin="1234",
            city_id=1,
        )
        db.add(branch)
        db.flush()

        target_month = date(2026, 8, 1)

        booking = DedicatedShiftBooking(
            merchant_branch_id=branch.id,
            logistics_company_tenant_id=tenant.id,
            shift_type=ShiftType.full_day_8h,
            shift_start_time=time(10, 0),
            shift_end_time=time(18, 0),
            effective_from=target_month,
            effective_until=None,
            monthly_fee_to_merchant=Decimal("6000.00"),
            monthly_payout_to_logistics=Decimal("5000.00"),
            dou_margin=Decimal("1000.00"),
            status=BookingStatus.paused,
        )
        db.add(booking)
        db.commit()

        admin_user = User(name="Admin", role=UserRole.DOU_ADMIN, phone="966500000099")

        # Merchant statement query
        line_items, gross_fee, _ = _build_statement_line_items(db, merchant.id, target_month)

        # Admin settlements generator
        ledgers = generate_settlements_admin(
            payload=GenerateSettlementsPayload(month="2026-08"),
            db=db,
            _=admin_user,
        )

        # Both must treat billable bookings consistently through unified filter
        # On buggy code: merchant returns 1 item, admin returns 0 ledgers!
        assert len(line_items) == len(ledgers["settlements"]), (
            f"Divergence detected! Merchant statement found {len(line_items)} bookings, "
            f"but admin settlement found {len(ledgers['settlements'])} bookings for paused status."
        )
    finally:
        db.close()


def test_fix_7_claim_pool_order_enforces_tenant_isolation(monkeypatch):
    monkeypatch.setattr("app.routers.driver_dedicated.ENABLE_OPEN_POOL", True)
    from datetime import time

    from fastapi import HTTPException

    from app.models.merchant import (
        BookingStatus,
        BranchDispatchOrder,
        DedicatedShiftBooking,
        MerchantAccount,
        MerchantBranch,
        OrderStatus,
        ShiftType,
    )
    from app.routers.driver_dedicated import claim_pool_order

    db = TestingSession()
    try:
        tenant_a = Tenant(name="Fleet A", country=Country.SA, plan="GROWTH")
        tenant_b = Tenant(name="Fleet B", country=Country.SA, plan="GROWTH")
        db.add_all([tenant_a, tenant_b])
        db.flush()

        rider_a = Courier(
            tenant_id=tenant_a.id,
            name="Rider A (Fleet A)",
            phone="966500000031",
            courier_type=CourierType.COMPANY,
            country=Country.SA,
        )
        db.add(rider_a)
        db.flush()

        merchant = MerchantAccount(
            trade_name="Burger Joint",
            billing_contact_email="burger@joint.com",
            billing_contact_phone="966500000003",
        )
        db.add(merchant)
        db.flush()

        branch = MerchantBranch(
            merchant_account_id=merchant.id,
            branch_name="Branch Fleet B",
            city="Riyadh",
            latitude=24.7,
            longitude=46.6,
            cashier_access_pin="1234",
            city_id=1,
        )
        db.add(branch)
        db.flush()

        # Contract is exclusively with Fleet B
        booking_b = DedicatedShiftBooking(
            merchant_branch_id=branch.id,
            logistics_company_tenant_id=tenant_b.id,
            shift_type=ShiftType.full_day_8h,
            shift_start_time=time(10, 0),
            shift_end_time=time(18, 0),
            effective_from=date.today(),
            effective_until=None,
            monthly_fee_to_merchant=Decimal("6000.00"),
            monthly_payout_to_logistics=Decimal("5000.00"),
            dou_margin=Decimal("1000.00"),
            status=BookingStatus.active,
        )
        db.add(booking_b)
        db.flush()

        # Order created at Branch Fleet B
        order = BranchDispatchOrder(
            merchant_branch_id=branch.id,
            order_date=date.today(),
            customer_name="Customer 1",
            customer_phone="966599999999",
            delivery_address_text="Riyadh Street",
            status=OrderStatus.pending,
            order_source="quick_cashier",
            is_pool_eligible=True,
            rider_id=None,
        )
        db.add(order)
        db.commit()

        # Rider A from Fleet A attempts to claim Fleet B's pool order
        with pytest.raises(HTTPException) as exc_info:
            claim_pool_order(order_id=order.id, db=db, current_rider=rider_a)

        assert exc_info.value.status_code in (403, 404)
        assert "غير مصرح" in exc_info.value.detail or "شركة" in exc_info.value.detail
    finally:
        db.close()


def test_fix_8_get_endpoints_do_not_commit_db():
    from unittest.mock import MagicMock

    from app.models.entities import User, UserRole
    from app.routers.documents import get_kyc_status
    from app.routers.readiness import get_readiness

    db = TestingSession()
    try:
        tenant = Tenant(name="Fleet Read-Only Test", country=Country.SA, plan="GROWTH")
        db.add(tenant)
        db.flush()

        courier = Courier(
            tenant_id=tenant.id,
            name="Courier Readonly",
            phone="966500000088",
            courier_type=CourierType.COMPANY,
            country=Country.SA,
        )
        db.add(courier)
        db.flush()

        user = User(
            name="Admin User",
            phone="966500000089",
            password_hash="dummy_hash_12345",
            role=UserRole.COMPANY_ADMIN,
            tenant_id=tenant.id,
        )
        db.add(user)
        db.commit()

        # Intercept db.commit to verify GET endpoints do not commit transactions
        db.commit = MagicMock(side_effect=AssertionError("db.commit() was called inside a GET endpoint!"))

        # 1. GET /readiness/{courier_id}
        res_readiness = get_readiness(courier_id=courier.id, user=user, db=db)
        assert res_readiness["courier_id"] == courier.id

        # 2. GET /documents/kyc/{courier_id}
        res_kyc = get_kyc_status(courier_id=courier.id, user=user, db=db)
        assert res_kyc["courier_id"] == courier.id

        # 3. GET /account/{merchant_account_id}/statement
        from app.models.merchant import MerchantAccount
        from app.routers.merchant import get_monthly_statement

        merchant_acc = MerchantAccount(
            trade_name="Zero Commit Merchant",
            billing_contact_email="zerocommit@test.com",
            billing_contact_phone="966500000088",
        )
        # unmock temporarily for setup
        db.commit = MagicMock()
        db.add(merchant_acc)
        db.flush()
        db.commit = MagicMock(side_effect=AssertionError("db.commit() was called inside GET statement!"))

        res_stmt = get_monthly_statement(
            merchant_account_id=merchant_acc.id,
            billing_month="2026-08",
            db=db,
            auth_account_id=merchant_acc.id,
        )
        assert res_stmt.merchant_name == "Zero Commit Merchant"

        # 4. GET /daily-report/export
        from app.routers.hr import daily_report_export

        db.commit = MagicMock(side_effect=AssertionError("db.commit() was called inside GET daily report export!"))
        res_export = daily_report_export(user=user, db=db)
        assert res_export.status_code == 200

        # 5. GET /billing/current with past due tenant
        from datetime import datetime, timedelta
        from app.routers.billing import billing_status

        tenant.due_date = datetime.now() - timedelta(days=5)
        res_billing = billing_status(user=user, db=db)
        assert res_billing["status"] == "OVERDUE"

        # 6. Global AST audit across all router files verifying zero db.commit in all GET endpoints
        import ast
        import glob

        violations = []
        for fpath in sorted(glob.glob("app/routers/*.py")):
            with open(fpath) as f:
                tree = ast.parse(f.read(), filename=fpath)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_get = False
                    for dec in node.decorator_list:
                        if (
                            isinstance(dec, ast.Call)
                            and isinstance(dec.func, ast.Attribute)
                            and dec.func.attr == "get"
                        ):
                            is_get = True
                            break
                    if is_get:
                        for sub in ast.walk(node):
                            if (
                                isinstance(sub, ast.Call)
                                and isinstance(sub.func, ast.Attribute)
                                and sub.func.attr == "commit"
                            ):
                                violations.append(f"{fpath}:{sub.lineno} in {node.name}")

        assert len(violations) == 0, f"Found db.commit() calls inside GET endpoints: {violations}"
    finally:
        db.close()


def test_fix_9_issued_invoice_preserves_stamped_vat():
    from app.models.merchant import (
        MerchantAccount,
        MonthlySettlementLedger,
        SettlementStatus,
    )
    from app.routers.merchant import get_tax_invoice

    db = TestingSession()
    try:
        merchant = MerchantAccount(
            trade_name="Shawarma Palace",
            billing_contact_email="palace@shawarma.com",
            billing_contact_phone="966500000004",
        )
        db.add(merchant)
        db.flush()

        # Issued settlement with stamped historical VAT rate and amount
        target_month = date(2026, 7, 1)
        ledger = MonthlySettlementLedger(
            merchant_account_id=merchant.id,
            settlement_month=target_month,
            total_rider_shift_months=Decimal("1.0000"),
            gross_fee_charged_to_merchant=Decimal("10000.00"),
            total_payout_to_logistics=Decimal("8500.00"),
            dou_net_margin=Decimal("1500.00"),
            vat_rate=Decimal("0.15"),
            vat_amount=Decimal("1500.00"),
            settlement_status=SettlementStatus.issued,
        )
        db.add(ledger)
        db.commit()

        # No AppSetting for dou_vat_number exists in this test DB!
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_tax_invoice(
                merchant_account_id=merchant.id,
                billing_month="2026-07",
                settlement_id=ledger.id,
                month="2026-07",
                db=db,
                auth_account_id=merchant.id,
            )
        assert exc_info.value.status_code == 409
        assert "لا يوجد رقم تسجيل ضريبي مسجّل للمنصة" in exc_info.value.detail

        # Now when dou_vat_number IS configured, issuance succeeds with that number
        from app.models.entities import AppSetting
        db.add(AppSetting(key="dou_vat_number", value="311111111111113"))
        db.commit()

        invoice = get_tax_invoice(
            merchant_account_id=merchant.id,
            billing_month="2026-07",
            settlement_id=ledger.id,
            month="2026-07",
            db=db,
            auth_account_id=merchant.id,
        )
        assert invoice.is_tax_invoice is True
        assert invoice.seller.vat_number == "311111111111113"
        assert "300000000000003" not in str(invoice.dict())
        assert invoice.vat_rate == 0.15
        assert invoice.vat_amount == 1500.0
        assert invoice.total_amount == 11500.0
    finally:
        db.close()


def test_fix_10_courier_attendance_corrections_tracking():
    """Fix 10: static/courier.html must fetch GET /timekeeping/corrections and render
    a tracking card for courier attendance disputes showing PENDING / APPROVED / REJECTED
    with decision note/reason, and refresh after submission.
    """
    import pathlib
    from datetime import datetime

    from app.models.entities import (
        AttendanceCorrectionRequest,
        Courier,
        Tenant,
        User,
        UserRole,
    )
    from app.routers.timekeeping import list_corrections

    db = TestingSession()
    try:
        tenant = Tenant(name="Fleet Tenant 10", country=Country.SA, plan="GROWTH")
        db.add(tenant)
        db.flush()

        courier = Courier(
            tenant_id=tenant.id,
            name="Ahmad Courier",
            phone="966512345678",
            courier_type=CourierType.COMPANY,
            country=Country.SA,
        )
        db.add(courier)
        db.flush()

        user = User(
            tenant_id=tenant.id,
            courier_id=courier.id,
            phone=courier.phone,
            role=UserRole.COURIER,
            name=courier.name,
            password_hash="dummy_hash_12345",
        )
        db.add(user)
        db.flush()

        # 1. Backend: create correction request and verify courier can fetch it via GET
        req = AttendanceCorrectionRequest(
            tenant_id=tenant.id,
            courier_id=courier.id,
            reason="اعتراض على وقت الانصراف لتعطل التطبيق",
            status="PENDING",
            requested_check_in=datetime(2026, 8, 15, 9, 0),
            requested_check_out=datetime(2026, 8, 15, 17, 0),
        )
        db.add(req)
        db.commit()

        results = list_corrections(status_filter=None, user=user, db=db)
        assert len(results) == 1
        assert results[0]["id"] == req.id
        assert results[0]["status"] == "PENDING"
        assert results[0]["reason"] == "اعتراض على وقت الانصراف لتعطل التطبيق"

        # Update to APPROVED with decision note
        req.status = "APPROVED"
        req.decision_note = "تم التحقق واعتماد الوقت من الفرع"
        db.commit()

        results2 = list_corrections(status_filter=None, user=user, db=db)
        assert results2[0]["status"] == "APPROVED"
        assert results2[0]["decision_note"] == "تم التحقق واعتماد الوقت من الفرع"

        # 2. Frontend: verify static/courier.html fetches GET /timekeeping/corrections and renders tracking card
        html_path = pathlib.Path(__file__).parent.parent / "static" / "courier.html"
        html_content = html_path.read_text(encoding="utf-8")

        # Must call GET /timekeeping/corrections (not just POST)
        assert "api('/timekeeping/corrections')" in html_content or 'api("/timekeeping/corrections")' in html_content, (
            "static/courier.html must call GET /timekeeping/corrections to fetch corrections"
        )
        # Must track state.corrections
        assert "state.corrections" in html_content, "static/courier.html must maintain corrections in state"
        # Must render card with review status labels
        assert "تحت المراجعة" in html_content, "static/courier.html must display 'تحت المراجعة' for PENDING"
        assert "مقبول" in html_content, "static/courier.html must display 'مقبول' for APPROVED"
        assert "مرفوض" in html_content, "static/courier.html must display 'مرفوض' for REJECTED"
        assert "decision_note" in html_content, "static/courier.html must display decision note / reason"

    finally:
        db.close()


# ─── Codex field-trial findings ───────────────────────────────────────────────


def _admin_ctx():
    """A tenant with a real operating structure, plus the DOU admin acting on it.

    add_courier now goes through create_rider_record, which insists on a live
    contract branch — that branch is what gives a rider their supervisor,
    project and city. Reusing the import tests' builder keeps one definition of
    "a fully set up tenant" instead of a second one drifting here.
    """
    from tests.test_w6_imports import (
        make_branch,
        make_contract,
        make_country,
        make_city,
        make_operating_city,
        make_project,
        make_supervisor,
        make_tenant,
        make_admin,
    )

    db = TestingSession()
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    project = make_project(db, tenant_id=tenant.id)
    contract = make_contract(db, tenant_id=tenant.id)
    sup = make_supervisor(db, tenant_id=tenant.id)
    branch = make_branch(
        db,
        tenant_id=tenant.id,
        contract_id=contract.id,
        city_id=city.id,
        supervisor_id=sup.id,
        project_id=project.id,
    )
    return db, admin, tenant, contract, branch


def test_fix_11_admin_created_courier_can_actually_log_in():
    """A rider DOU support adds must be able to sign in to the driver app.

    add_courier used to insert a bare Courier row with no User, so every rider
    created from the admin console needed a hand-written SQL insert before they
    could work. It now goes through create_rider_record, the same path the fleet
    uses, which creates the courier and its login together.
    """
    from app.models.entities import User, UserRole
    from app.routers.admin import CourierIn, add_courier

    db, admin, tenant, contract, branch = _admin_ctx()
    payload = CourierIn(
        name="مندوب أنشأته الإدارة",
        phone="0555512340",
        courier_type="COMPANY",
        country="SA",
        tenant_id=tenant.id,
        password="RiderPass123!",
        contract_id=contract.id,
        contract_branch_id=branch.id,
        photo_url="https://cdn.example/r.jpg",
        vehicle_plate="ABC 1234",
    )
    created = add_courier(payload=payload, db=db, user=admin)
    db.commit()

    account = (
        db.query(User)
        .filter(User.courier_id == created["id"], User.role == UserRole.COURIER)
        .first()
    )
    assert account is not None, "a rider created by DOU admin has no login account"
    assert account.tenant_id == tenant.id
    db.close()


def test_fix_12_admin_courier_keeps_photo_and_plate():
    """The plate and photo the merchant approves against must survive creation."""
    from app.models.entities import Courier
    from app.routers.admin import CourierIn, add_courier

    db, admin, tenant, contract, branch = _admin_ctx()
    created = add_courier(
        payload=CourierIn(
            name="مندوب بصورة ولوحة",
            phone="0555512341",
            courier_type="COMPANY",
            country="SA",
            tenant_id=tenant.id,
            password="RiderPass123!",
            contract_id=contract.id,
            contract_branch_id=branch.id,
            photo_url="https://cdn.example/photo.jpg",
            vehicle_plate="XYZ 9876",
        ),
        db=db,
        user=admin,
    )
    db.commit()

    rider = db.get(Courier, created["id"])
    assert rider.photo_url == "https://cdn.example/photo.jpg"
    assert rider.vehicle_plate == "XYZ 9876"
    db.close()


def test_fix_13_duplicate_courier_phone_is_a_message_not_a_500():
    """A phone already on file must come back as a sentence, not an IntegrityError."""
    from fastapi import HTTPException

    from app.routers.admin import CourierIn, add_courier

    db, admin, tenant, contract, branch = _admin_ctx()
    base = dict(
        name="مندوب مكرر",
        courier_type="COMPANY",
        country="SA",
        tenant_id=tenant.id,
        password="RiderPass123!",
        contract_id=contract.id,
        contract_branch_id=branch.id,
    )
    add_courier(payload=CourierIn(phone="0555512342", **base), db=db, user=admin)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        add_courier(payload=CourierIn(phone="0555512342", **base), db=db, user=admin)
    assert exc.value.status_code == 422
    assert "مستخدم بالفعل" in str(exc.value.detail)
    db.close()
