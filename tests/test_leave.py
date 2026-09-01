"""Leave policy tests — W1-E5."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Courier, CourierType, Country, LeaveEntitlement, LeavePolicy,
    LeaveRequest, LeaveType, Tenant, User, UserRole,
)
from app.routers.leave import (
    LeaveDecision, LeavePolicyCreate, LeaveRequestCreate, LeaveTypeCreate,
    LeaveTypeUpdate, LeavePolicyUpdate,
    create_leave_type, update_leave_type, list_leave_types,
    create_leave_policy, list_leave_policies, update_leave_policy,
    create_leave_request, list_leave_requests, supervisor_decide, admin_decide,
    get_entitlements,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def make_tenant(db, name):
    tenant = Tenant(name=name, country=Country.SA)
    db.add(tenant); db.commit(); db.refresh(tenant)
    return tenant


def make_user(db, tenant_id, phone, role=UserRole.COMPANY):
    user = User(phone=phone, password_hash="x", role=role, tenant_id=tenant_id)
    db.add(user); db.commit(); db.refresh(user)
    return user


def make_rider(db, tenant_id, suffix):
    rider = Courier(
        tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"700{suffix}",
        courier_type=CourierType.COMPANY, country=Country.SA,
    )
    db.add(rider); db.commit(); db.refresh(rider)
    return rider


# ---------- leave types ----------

def test_create_leave_type(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000001")
    result = create_leave_type(
        LeaveTypeCreate(code="ANNUAL", name_ar="سنوية", name_en="Annual", is_paid=True, max_days_per_year=30),
        user, db,
    )
    assert result["code"] == "ANNUAL"


def test_leave_type_code_unique_within_tenant(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    with pytest.raises(HTTPException) as error:
        create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية 2"), user, db)
    assert error.value.status_code == 409


def test_leave_type_rejects_cross_tenant_code(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000003")
    user2 = make_user(db, tenant2.id, "966500000004")
    create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user1, db)
    result = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user2, db)
    assert result["code"] == "ANNUAL"


def test_update_leave_type(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")
    created = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    updated = update_leave_type(created["id"], LeaveTypeUpdate(name_ar="سنوية محددة"), user, db)
    assert updated["name_ar"] == "سنوية محددة"


# ---------- leave policies ----------

def test_create_leave_policy(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    result = create_leave_policy(
        LeavePolicyCreate(leave_type_id=lt["id"], entitlement_days=30, effective_from=date(2026, 1, 1)),
        user, db,
    )
    assert result["entitlement_days"] == 30


def test_leave_policy_unique_per_type(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    create_leave_policy(
        LeavePolicyCreate(leave_type_id=lt["id"], entitlement_days=30, effective_from=date(2026, 1, 1)),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_leave_policy(
            LeavePolicyCreate(leave_type_id=lt["id"], entitlement_days=25, effective_from=date(2026, 6, 1)),
            user, db,
        )
    assert error.value.status_code == 409


# ---------- leave requests ----------

def test_create_leave_request(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000008")
    rider = make_rider(db, tenant.id, "1")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    create_leave_policy(
        LeavePolicyCreate(leave_type_id=lt["id"], entitlement_days=30, effective_from=date(2026, 1, 1)),
        user, db,
    )
    # Create entitlement
    db.add(LeaveEntitlement(
        tenant_id=tenant.id, courier_id=rider.id, leave_type_id=lt["id"],
        year=2026, entitled_days=30,
    ))
    db.commit()
    result = create_leave_request(
        LeaveRequestCreate(
            courier_id=rider.id, leave_type_id=lt["id"],
            from_date=date(2026, 9, 1), to_date=date(2026, 9, 5),
            reason="Vacation",
        ),
        user, db,
    )
    assert result["status"] == "PENDING"
    assert result["days"] == 5


def test_leave_request_overlap_rejected(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000009")
    rider = make_rider(db, tenant.id, "2")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    db.add(LeaveEntitlement(
        tenant_id=tenant.id, courier_id=rider.id, leave_type_id=lt["id"],
        year=2026, entitled_days=30,
    ))
    db.commit()
    create_leave_request(
        LeaveRequestCreate(
            courier_id=rider.id, leave_type_id=lt["id"],
            from_date=date(2026, 9, 1), to_date=date(2026, 9, 5),
        ),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_leave_request(
            LeaveRequestCreate(
                courier_id=rider.id, leave_type_id=lt["id"],
                from_date=date(2026, 9, 3), to_date=date(2026, 9, 7),
            ),
            user, db,
        )
    assert error.value.status_code == 409


def test_leave_request_insufficient_balance(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000010")
    rider = make_rider(db, tenant.id, "3")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    db.add(LeaveEntitlement(
        tenant_id=tenant.id, courier_id=rider.id, leave_type_id=lt["id"],
        year=2026, entitled_days=5,
    ))
    db.commit()
    with pytest.raises(HTTPException) as error:
        create_leave_request(
            LeaveRequestCreate(
                courier_id=rider.id, leave_type_id=lt["id"],
                from_date=date(2026, 9, 1), to_date=date(2026, 9, 10),
            ),
            user, db,
        )
    assert error.value.status_code == 400


# ---------- leave workflow ----------

def test_supervisor_approves_leave(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000011")
    rider = make_rider(db, tenant.id, "4")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    db.add(LeaveEntitlement(
        tenant_id=tenant.id, courier_id=rider.id, leave_type_id=lt["id"],
        year=2026, entitled_days=30,
    ))
    db.commit()
    req = create_leave_request(
        LeaveRequestCreate(courier_id=rider.id, leave_type_id=lt["id"],
                          from_date=date(2026, 9, 1), to_date=date(2026, 9, 5)),
        user, db,
    )
    result = supervisor_decide(req["id"], LeaveDecision(decision="APPROVED"), user, db)
    assert result["status"] == "SUPERVISOR_APPROVED"


def test_admin_approves_leave(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000012")
    rider = make_rider(db, tenant.id, "5")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    db.add(LeaveEntitlement(
        tenant_id=tenant.id, courier_id=rider.id, leave_type_id=lt["id"],
        year=2026, entitled_days=30,
    ))
    db.commit()
    req = create_leave_request(
        LeaveRequestCreate(courier_id=rider.id, leave_type_id=lt["id"],
                          from_date=date(2026, 9, 1), to_date=date(2026, 9, 5)),
        user, db,
    )
    supervisor_decide(req["id"], LeaveDecision(decision="APPROVED"), user, db)
    result = admin_decide(req["id"], LeaveDecision(decision="APPROVED"), user, db)
    assert result["status"] == "APPROVED"
    # Check entitlement used_days updated
    ent = db.query(LeaveEntitlement).first()
    assert ent.used_days == 5
    assert ent.pending_days == 0


def test_reject_leave_releases_days(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000013")
    rider = make_rider(db, tenant.id, "6")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    db.add(LeaveEntitlement(
        tenant_id=tenant.id, courier_id=rider.id, leave_type_id=lt["id"],
        year=2026, entitled_days=30,
    ))
    db.commit()
    req = create_leave_request(
        LeaveRequestCreate(courier_id=rider.id, leave_type_id=lt["id"],
                          from_date=date(2026, 9, 1), to_date=date(2026, 9, 5)),
        user, db,
    )
    result = supervisor_decide(req["id"], LeaveDecision(decision="REJECTED", note="Rejected"), user, db)
    assert result["status"] == "REJECTED"
    # Check pending days released
    ent = db.query(LeaveEntitlement).first()
    assert ent.pending_days == 0


def test_double_decision_rejected(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000014")
    rider = make_rider(db, tenant.id, "7")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user, db)
    db.add(LeaveEntitlement(
        tenant_id=tenant.id, courier_id=rider.id, leave_type_id=lt["id"],
        year=2026, entitled_days=30,
    ))
    db.commit()
    req = create_leave_request(
        LeaveRequestCreate(courier_id=rider.id, leave_type_id=lt["id"],
                          from_date=date(2026, 9, 1), to_date=date(2026, 9, 5)),
        user, db,
    )
    supervisor_decide(req["id"], LeaveDecision(decision="APPROVED"), user, db)
    with pytest.raises(HTTPException) as error:
        supervisor_decide(req["id"], LeaveDecision(decision="APPROVED"), user, db)
    assert error.value.status_code == 409


# ---------- tenant isolation ----------

def test_cross_tenant_leave_type_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000015")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user1, db)
    user2 = make_user(db, tenant2.id, "966500000016")
    with pytest.raises(HTTPException) as error:
        update_leave_type(lt["id"], LeaveTypeUpdate(name_ar="Hacked"), user2, db)
    assert error.value.status_code == 404


def test_cross_tenant_leave_request_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000017")
    rider2 = make_rider(db, tenant2.id, "8")
    lt = create_leave_type(LeaveTypeCreate(code="ANNUAL", name_ar="سنوية"), user1, db)
    user2 = make_user(db, tenant2.id, "966500000018")
    with pytest.raises(HTTPException) as error:
        create_leave_request(
            LeaveRequestCreate(courier_id=rider2.id, leave_type_id=lt["id"],
                              from_date=date(2026, 9, 1), to_date=date(2026, 9, 5)),
            user2, db,
        )
    assert error.value.status_code in (403, 404)
