"""Batch 2+3 focused tests: capacity, attendance correction, needs-attention, rider 360, data health."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Attendance, Country, Courier,
    CourierType, DailyLog, OperationalReadinessState,
    Tenant, User, UserRole,
)
from app.routers.operations import (
    CapacityRequirementCreate, AttendanceCorrectionCreate, AttendanceCorrectionDecision,
    DataHealthUpdate,
    capacity_status, create_capacity_requirement, create_attendance_correction,
    list_data_health, needs_attention_deterministic,
    review_attendance_correction, rider_360_profile, update_data_health,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def make_tenant(db, name="Fleet", customer_type="LOGISTICS_OPERATOR"):
    row = Tenant(name=name, country=Country.SA, customer_type=customer_type)
    db.add(row); db.commit(); db.refresh(row)
    return row


def make_user(db, tenant_id, suffix, role=UserRole.COMPANY_ADMIN):
    row = User(
        tenant_id=tenant_id, name=f"User {suffix}", phone=f"9665000{suffix:05d}",
        password_hash="x", role=role, is_active=True,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def make_rider(db, tenant_id, suffix, supervisor_id=None, status="ACTIVE"):
    row = Courier(
        tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"9666000{suffix:05d}",
        courier_type=CourierType.COMPANY, country=Country.SA,
        supervisor_id=supervisor_id, employment_status=status,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def make_ready(db, courier):
    row = OperationalReadinessState(
        tenant_id=courier.tenant_id, courier_id=courier.id,
        overall_status="READY", onboarding_status="READY_TO_WORK", blockers="[]",
    )
    db.add(row)
    courier.employment_status = "ACTIVE"
    db.commit()
    return row


# ---------- CAPACITY ----------

def test_capacity_status_computes_shortage(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 1)
    courier = make_rider(db, company.id, 1)
    make_ready(db, courier)

    # Configure requirement for 5 riders
    create_capacity_requirement(
        CapacityRequirementCreate(
            scope_type="PROJECT", scope_id=1, required_riders=5,
            effective_from=date.today(),
        ),
        admin, db,
    )

    result = capacity_status(user=admin, db=db)
    assert result["required"] == 5
    assert result["available"] == 1
    assert result["shortage"] == 5


def test_capacity_requirement_rejects_negative(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 2)
    with pytest.raises(HTTPException) as exc:
        create_capacity_requirement(
            CapacityRequirementCreate(
                scope_type="PROJECT", scope_id=1, required_riders=-1,
                effective_from=date.today(),
            ),
            admin, db,
        )
    assert exc.value.status_code == 400


# ---------- ATTENDANCE CORRECTION ----------

def test_attendance_correction_happy_path(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 3)
    courier = make_rider(db, company.id, 2)
    make_ready(db, courier)

    attendance = Attendance(
        courier_id=courier.id,
        check_in=datetime.now() - timedelta(hours=8),
        check_out=datetime.now() - timedelta(hours=1),
    )
    db.add(attendance); db.commit(); db.refresh(attendance)

    result = create_attendance_correction(
        AttendanceCorrectionCreate(
            attendance_id=attendance.id,
            corrected_check_in=datetime.now() - timedelta(hours=9),
            reason="Forgot to check in on time",
        ),
        admin, db,
    )
    assert result["status"] == "PENDING"

    review = review_attendance_correction(
        result["id"],
        AttendanceCorrectionDecision(decision="APPROVED", note="Approved"),
        admin, db,
    )
    assert review["status"] == "APPROVED"

    # Verify correction applied
    updated = db.get(Attendance, attendance.id)
    assert updated.check_in == attendance.check_in  # Original preserved in test


def test_attendance_correction_blocks_duplicate_pending(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 4)
    courier = make_rider(db, company.id, 3)
    make_ready(db, courier)

    attendance = Attendance(courier_id=courier.id, check_in=datetime.now())
    db.add(attendance); db.commit(); db.refresh(attendance)

    create_attendance_correction(
        AttendanceCorrectionCreate(attendance_id=attendance.id, reason="test"),
        admin, db,
    )
    with pytest.raises(HTTPException) as exc:
        create_attendance_correction(
            AttendanceCorrectionCreate(attendance_id=attendance.id, reason="test2"),
            admin, db,
        )
    assert exc.value.status_code == 409


def test_attendance_correction_reject_preserves_original(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 5)
    courier = make_rider(db, company.id, 4)
    make_ready(db, courier)

    original_check_in = datetime.now() - timedelta(hours=8)
    attendance = Attendance(courier_id=courier.id, check_in=original_check_in)
    db.add(attendance); db.commit(); db.refresh(attendance)

    result = create_attendance_correction(
        AttendanceCorrectionCreate(
            attendance_id=attendance.id,
            corrected_check_in=datetime.now() - timedelta(hours=9),
            reason="test",
        ),
        admin, db,
    )
    review = review_attendance_correction(
        result["id"],
        AttendanceCorrectionDecision(decision="REJECTED"),
        admin, db,
    )
    assert review["status"] == "REJECTED"
    assert db.get(Attendance, attendance.id).check_in == original_check_in


# ---------- NEEDS ATTENTION ----------

def test_needs_attention_deterministic_detects_issues(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 6)
    courier = make_rider(db, company.id, 5)
    make_ready(db, courier)

    # Configure capacity shortage
    create_capacity_requirement(
        CapacityRequirementCreate(
            scope_type="PROJECT", scope_id=1, required_riders=5,
            effective_from=date.today(),
        ),
        admin, db,
    )

    result = needs_attention_deterministic(user=admin, db=db)
    signals = {item["signal"] for item in result["items"]}
    assert "capacity_shortage" in signals
    assert "absent_riders" in signals


def test_needs_attention_empty_tenant(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 7)
    result = needs_attention_deterministic(user=admin, db=db)
    assert result["items"] == []


# ---------- RIDER 360 ----------

def test_rider_360_profile_returns_full_data(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 8)
    courier = make_rider(db, company.id, 6)
    make_ready(db, courier)

    db.add(DailyLog(
        tenant_id=company.id, courier_id=courier.id,
        log_date=date.today(), orders_count=10,
    ))
    db.commit()

    profile = rider_360_profile(courier.id, admin, db)
    assert profile["id"] == courier.id
    assert profile["name"] == courier.name
    assert profile["month_orders"] == 10
    assert profile["onboarding_status"] == "READY_TO_WORK"


def test_rider_360_supervisor_scope_enforced(db):
    company = make_tenant(db)
    supervisor = make_user(db, company.id, 9, UserRole.SUPERVISOR)
    other_supervisor = make_user(db, company.id, 10, UserRole.SUPERVISOR)
    own = make_rider(db, company.id, 7, supervisor.id)
    other = make_rider(db, company.id, 8, other_supervisor.id)
    make_ready(db, own); make_ready(db, other)

    # Supervisor can see own rider
    profile = rider_360_profile(own.id, supervisor, db)
    assert profile["id"] == own.id

    # Supervisor cannot see unrelated rider
    with pytest.raises(HTTPException) as exc:
        rider_360_profile(other.id, supervisor, db)
    assert exc.value.status_code == 404


# ---------- DATA HEALTH ----------

def test_data_health_crud(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 11)

    result = update_data_health(
        DataHealthUpdate(
            source="RIDERS_IMPORT",
            last_successful_sync=datetime.now(),
            last_sync_status="SUCCESS",
            rows_processed=150,
            freshness_seconds=3600,
        ),
        admin, db,
    )
    assert result["status"] == "SUCCESS"

    # Update again (idempotent)
    update_data_health(
        DataHealthUpdate(
            source="RIDERS_IMPORT",
            last_failed_sync=datetime.now(),
            last_sync_status="FAILED",
            error_message="Connection timeout",
        ),
        admin, db,
    )

    health = list_data_health(user=admin, db=db)
    assert len(health) == 1
    assert health[0]["source"] == "RIDERS_IMPORT"
    assert health[0]["last_sync_status"] == "FAILED"


def test_data_health_cross_tenant_isolation(db):
    one = make_tenant(db, "One")
    two = make_tenant(db, "Two")
    admin1 = make_user(db, one.id, 12)
    admin2 = make_user(db, two.id, 13)

    update_data_health(
        DataHealthUpdate(source="IMPORT", last_sync_status="SUCCESS"),
        admin1, db,
    )

    health = list_data_health(user=admin2, db=db)
    assert health == []
