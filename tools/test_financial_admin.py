"""Regression checks for DOU subscription receipts, revenue and arrears reporting."""
from datetime import datetime, timedelta

from fastapi import HTTPException

from app.database import Base, SessionLocal, engine
from app.models.entities import Country, Courier, CourierType, SubscriptionPayment, Tenant, User, UserRole
from app.routers.admin import finance_summary, list_couriers, list_tenants, record_subscription_payment, system_status
from app.routers.auth import hash_password


Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
db = SessionLocal()
now = datetime.utcnow()
admin = User(phone="966500009999", name="DOU Finance", password_hash=hash_password("Finance99!"),
             role=UserRole.DOU_ADMIN, country=Country.SA, is_active=True)
paid = Tenant(name="Paid Logistics", country=Country.SA, currency="SAR", monthly_fee=499,
              due_date=now + timedelta(days=3), subscription_status="ACTIVE")
late = Tenant(name="Late Logistics", country=Country.SA, currency="SAR", monthly_fee=999,
              due_date=now - timedelta(days=40), subscription_status="OVERDUE")
db.add_all([admin, paid, late]); db.flush()
courier = Courier(tenant_id=paid.id, name="Financial Driver", phone="966511119999",
                  courier_type=CourierType.COMPANY, country=Country.SA,
                  acceptance_rate=None, employment_status="SUSPENDED", is_available=False)
db.add(courier); db.commit()
courier.acceptance_rate = None; db.commit()

receipt = record_subscription_payment(paid.id, {
    "amount": 998, "payment_method": "BANK_TRANSFER", "paid_at": now.isoformat(),
    "period_months": 2, "reference": "BANK-QC-1", "notes": "اختبار مالي",
}, db, admin)
assert receipt["receipt_number"].startswith("DOU-")
assert receipt["amount"] == 998 and receipt["variance"] == 0
assert db.query(SubscriptionPayment).filter_by(tenant_id=paid.id).count() == 1

summary = finance_summary(now.strftime("%Y-%m"), db)
paid_row = next(row for row in summary["rows"] if row["tenant_id"] == paid.id)
late_row = next(row for row in summary["rows"] if row["tenant_id"] == late.id)
assert summary["actual_revenue"]["SAR"] == 998
assert summary["paid_companies"] == 1 and paid_row["paid_this_month"]
assert late_row["months_overdue"] == 2
assert late_row["outstanding_amount"] == 1998
assert summary["overdue_companies"] == 1

tenant_rows = list_tenants(db)
assert next(row for row in tenant_rows if row["id"] == paid.id)["paid_this_month_amount"] == 998

try:
    record_subscription_payment(paid.id, {"amount": 100, "period_months": 1}, db, admin)
except HTTPException as exc:
    assert exc.status_code == 400 and "المبلغ المتوقع" in exc.detail
else:
    raise AssertionError("A mismatched receipt amount must require an explicit variance approval")

courier_row = next(row for row in list_couriers(db) if row["id"] == courier.id)
assert courier_row["acceptance_rate"] is None and courier_row["is_active"] is False
status = system_status(db)
assert status["api"] == "ONLINE" and status["database"] == "ONLINE"
assert status["subscription_payments"] == "ADMIN_RECORDED"

print("OK: receipts feed actual revenue, monthly payment status, arrears and courier metrics")
db.close()
