"""Operational readiness state tests — W1-E7."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Attendance, Courier, CourierType, Country, KYCStatus, LeaveRequest, Shift,
    OperationalReadinessState, Tenant, User, UserRole,
)
from app.routers.readiness import (
    get_readiness, recompute_readiness, list_readiness,
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


def make_rider(db, tenant_id, suffix, employment_status="ACTIVE"):
    rider = Courier(
        tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"700{suffix}",
        courier_type=CourierType.COMPANY, country=Country.SA,
        employment_status=employment_status,
    )
    db.add(rider); db.commit(); db.refresh(rider)
    return rider


def test_get_readiness_computes_state(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000001")
    rider = make_rider(db, tenant.id, "1")
    result = get_readiness(rider.id, user, db)
    assert result["courier_id"] == rider.id
    assert "overall_status" in result
    assert "dimensions" in result
    assert "blockers" in result


def test_get_readiness_has_separate_dimensions(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    rider = make_rider(db, tenant.id, "2")
    result = get_readiness(rider.id, user, db)
    dims = result["dimensions"]
    assert "employment" in dims
    assert "account" in dims
    assert "attendance" in dims
    assert "shift" in dims
    assert "availability" in dims
    assert "leave" in dims
    assert "documents" in dims
    assert "vehicle_compliance" in dims


def test_get_readiness_not_ready_for_inactive_courier(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000003")
    rider = make_rider(db, tenant.id, "3", employment_status="SUSPENDED")
    result = get_readiness(rider.id, user, db)
    assert result["overall_status"] == "NOT_READY"
    assert any("employment:SUSPENDED" in b for b in result["blockers"])


def test_recompute_readiness(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000004")
    rider = make_rider(db, tenant.id, "4")
    result = recompute_readiness(rider.id, user, db)
    assert result["courier_id"] == rider.id
    assert "overall_status" in result


def test_list_readiness_filters_by_status(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")
    rider1 = make_rider(db, tenant.id, "5")
    rider2 = make_rider(db, tenant.id, "6", employment_status="SUSPENDED")
    get_readiness(rider1.id, user, db)
    get_readiness(rider2.id, user, db)
    all_states = list_readiness(status_filter=None, user=user, db=db)
    assert len(all_states) == 2


def test_list_readiness_with_status_filter(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    rider1 = make_rider(db, tenant.id, "7")
    rider2 = make_rider(db, tenant.id, "8", employment_status="SUSPENDED")
    get_readiness(rider1.id, user, db)
    get_readiness(rider2.id, user, db)
    not_ready = list_readiness(status_filter="NOT_READY", user=user, db=db)
    assert len(not_ready) >= 1


def test_readiness_on_leave_blocker(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    rider = make_rider(db, tenant.id, "9")
    # Create approved leave for today
    db.add(LeaveRequest(
        tenant_id=tenant.id,
        courier_id=rider.id,
        from_date=date.today(),
        to_date=date.today() + timedelta(days=5),
        status="APPROVED",
    ))
    db.commit()
    result = get_readiness(rider.id, user, db)
    assert any("availability:ON_LEAVE" in b for b in result["blockers"])


def test_readiness_kyc_verified(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000008")
    rider = make_rider(db, tenant.id, "10")
    # Set KYC as verified
    db.add(KYCStatus(
        tenant_id=tenant.id,
        courier_id=rider.id,
        status="VERIFIED",
    ))
    db.commit()
    result = get_readiness(rider.id, user, db)
    assert result["dimensions"]["documents"] == "VERIFIED"


def test_readiness_attendance_compliant(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000009")
    rider = make_rider(db, tenant.id, "11")
    # Create attendance for today
    db.add(Attendance(
        courier_id=rider.id,
        check_in=datetime.now(),
        check_in_lat=24.7,
        check_in_lng=46.7,
    ))
    db.commit()
    result = get_readiness(rider.id, user, db)
    assert result["dimensions"]["attendance"] == "COMPLIANT"


def test_readiness_shift_assigned(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000010")
    rider = make_rider(db, tenant.id, "12")
    import json
    db.add(Shift(
        tenant_id=tenant.id,
        name="Morning Shift",
        start_time="08:00",
        end_time="16:00",
        courier_ids=json.dumps([rider.id]),
    ))
    db.commit()
    result = get_readiness(rider.id, user, db)
    assert result["dimensions"]["shift"] == "ASSIGNED"


def test_cross_tenant_readiness_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000011")
    rider2 = make_rider(db, tenant2.id, "13")
    with pytest.raises(HTTPException) as error:
        get_readiness(rider2.id, user1, db)
    assert error.value.status_code == 404
