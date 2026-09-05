from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import Courier, DailyLog, Tenant, Country, CourierType
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
    from app.routers.merchant import dispatch_order, DispatchOrderRequest

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
    from fastapi import HTTPException
    from app.models.entities import SubscriptionPlan
    from app.routers.admin import add_courier, CourierIn

    db = TestingSession()
    try:
        plan = SubscriptionPlan(
            code="CAP1",
            name="Cap 1 Rider",
            monthly_price=100.0,
            max_couriers=1,
        )
        db.add(plan)
        db.flush()

        tenant = Tenant(name="Small Fleet", country=Country.SA, plan="CAP1")
        db.add(tenant)
        db.commit()

        # First courier should succeed
        c1 = add_courier(
            payload=CourierIn(
                name="Rider One",
                phone="966500000011",
                tenant_id=tenant.id,
            ),
            db=db,
        )
        assert c1["id"] is not None

        # Non-existent tenant must raise 404
        with pytest.raises(HTTPException) as exc_info404:
            add_courier(
                payload=CourierIn(
                    name="Rider Ghost",
                    phone="966500000099",
                    tenant_id=999999,
                ),
                db=db,
            )
        assert exc_info404.value.status_code == 404

        # Second courier must raise 422 because cap is 1
        with pytest.raises(HTTPException) as exc_info:
            add_courier(
                payload=CourierIn(
                    name="Rider Two",
                    phone="966500000012",
                    tenant_id=tenant.id,
                ),
                db=db,
            )
        assert exc_info.value.status_code in (422, 400)
        assert "الأقصى" in exc_info.value.detail
    finally:
        db.close()


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
        from app.routers.billing import billing_admin_subscribe, SubscriptionPayload
        from app.models.entities import User, UserRole
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
    from app.routers.admin_dedicated import create_booking_admin, CreateBookingPayload

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
    from app.routers.merchant import _build_statement_line_items
    from app.routers.admin_dedicated import (
        generate_settlements_admin,
        GenerateSettlementsPayload,
    )

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
    from app.routers.readiness import get_readiness
    from app.routers.documents import get_kyc_status

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
    finally:
        db.close()




