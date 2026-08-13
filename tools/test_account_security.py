"""Regression checks for production account and subscription controls."""
import os
os.environ.setdefault("ENABLE_PUBLIC_COMPANY_SIGNUP", "true")

from fastapi import HTTPException

from app.database import Base, SessionLocal, engine
from app.models.entities import Country, Courier, CourierType, Fleet, Tenant, User, UserRole
from app.routers.auth import create_token, get_current_user, hash_password
from app.routers.billing import billing_pay
from app.routers.fleet import delete_courier, fleet_update_user, update_courier
from app.routers.hr import update_supervisor


def denied(call, status=403):
    try:
        call()
    except HTTPException as exc:
        assert exc.status_code == status, exc
        return
    raise AssertionError("operation should have been denied")


Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
db = SessionLocal()
tenant = Tenant(name="Security tenant", country=Country.SA, subscription_status="ACTIVE")
db.add(tenant); db.flush()
db.add(Fleet(tenant_id=tenant.id, name="Fleet")); db.flush()
owner = User(phone="966500000001", name="Owner", password_hash=hash_password("OwnerPass9!"),
             role=UserRole.COMPANY, tenant_id=tenant.id, country=Country.SA, is_active=True)
supervisor = User(phone="966500000002", name="Supervisor", password_hash=hash_password("SupPass99!"),
                  role=UserRole.SUPERVISOR, tenant_id=tenant.id, country=Country.SA, is_active=True)
driver = Courier(tenant_id=tenant.id, name="Driver", phone="966500000003",
                 courier_type=CourierType.COMPANY, country=Country.SA, employment_status="ACTIVE")
db.add_all([owner, supervisor, driver]); db.flush()
driver_user = User(phone=driver.phone, name=driver.name, password_hash=hash_password("DriverPass9!"),
                   role=UserRole.COURIER, tenant_id=tenant.id, courier_id=driver.id,
                   country=Country.SA, is_active=True)
db.add(driver_user); db.commit()

denied(lambda: update_supervisor(supervisor.id, {"is_active": False}, supervisor, db))
denied(lambda: fleet_update_user(owner.id, {"is_active": False}, supervisor, db))
denied(lambda: update_courier(driver.id, {"employment_status": "SUSPENDED"}, supervisor, db))
denied(lambda: delete_courier(driver.id, supervisor, db))
denied(lambda: billing_pay(owner, db))

token = create_token(driver_user)
update_courier(driver.id, {"employment_status": "SUSPENDED"}, owner, db)
db.refresh(driver_user)
assert not driver_user.is_active and driver.employment_status == "SUSPENDED"
denied(lambda: get_current_user(token, db), 401)
update_courier(driver.id, {"employment_status": "ACTIVE"}, owner, db)
db.refresh(driver_user)
assert driver_user.is_active and driver.employment_status == "ACTIVE"

print("OK: admin-only deletion/deactivation, subscription payment protection, immediate session revocation")
db.close()
