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

