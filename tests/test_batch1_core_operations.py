"""Batch 1 core operations: onboarding, shift assignment, supervisor scope."""
import json
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Attendance, Country, Courier, CourierType, DailyLog,
    OperationalReadinessState, PlatformOperator, RiderAssignment,
    Shift, SourcePlatform, Tenant, User, UserRole,
)
from app.routers.readiness import (
    ReadinessTransition, get_readiness, transition_readiness,
)
from app.routers.shifts_assignment import (
    ShiftAssignmentIn, assign_rider, list_rider_shifts, list_shift_riders, remove_rider,
)
from app.routers.supervisor import (
    supervisor_attendance, supervisor_needs_attention, supervisor_overview,
    supervisor_performance, supervisor_riders,
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


def make_rider(db, tenant_id, suffix, supervisor_id=None, status="ONBOARDING"):
    row = Courier(
        tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"9666000{suffix:05d}",
        courier_type=CourierType.COMPANY, country=Country.SA,
        supervisor_id=supervisor_id, employment_status=status,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def make_ready(db, courier):
    """Mark a courier as employment-active and create a READY_TO_WORK onboarding state."""
    row = OperationalReadinessState(
        tenant_id=courier.tenant_id, courier_id=courier.id,
        overall_status="READY", onboarding_status="READY_TO_WORK", blockers="[]",
    )
    db.add(row)
    courier.employment_status = "ACTIVE"
    db.commit()
    return row


def make_shift(db, tenant_id, name="Morning", start="08:00", end="16:00"):
    row = Shift(
        tenant_id=tenant_id, name=name, start_time=start, end_time=end,
        courier_ids="[]",
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


# ---------- ONBOARDING ----------

def test_onboarding_happy_path_new_to_ready_to_work(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 1)
    supervisor = make_user(db, company.id, 3, UserRole.SUPERVISOR)
    courier = make_rider(db, company.id, 1, supervisor_id=supervisor.id)

    initial = get_readiness(courier.id, admin, db)
    assert initial["onboarding_status"] in {"NEW", "INCOMPLETE"}

    submitted = transition_readiness(
        courier.id, ReadinessTransition(action="SUBMIT_FOR_REVIEW"), admin, db
    )
    assert submitted["onboarding_status"] == "READY_FOR_REVIEW"

    activated = transition_readiness(
        courier.id, ReadinessTransition(action="ACTIVATE"), admin, db
    )
    assert activated["onboarding_status"] == "READY_TO_WORK"
    assert db.get(Courier, courier.id).employment_status == "ACTIVE"


def test_missing_supervisor_blocks_submission(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 2)
    courier = make_rider(db, company.id, 2)

    with pytest.raises(HTTPException) as exc:
        transition_readiness(courier.id, ReadinessTransition(action="SUBMIT_FOR_REVIEW"), admin, db)
    assert exc.value.status_code == 409
    assert "supervisor" in str(exc.value.detail)


def test_invalid_readiness_transition_rejected(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 4)
    courier = make_rider(db, company.id, 3)
    with pytest.raises(HTTPException) as exc:
        transition_readiness(courier.id, ReadinessTransition(action="ACTIVATE"), admin, db)
    assert exc.value.status_code == 409


def test_cross_tenant_and_unauthorized_onboarding_rejected(db):
    one, two = make_tenant(db, "One"), make_tenant(db, "Two")
    admin = make_user(db, one.id, 5)
    outsider = make_rider(db, two.id, 4)
    with pytest.raises(HTTPException) as exc:
        transition_readiness(outsider.id, ReadinessTransition(action="SUBMIT_FOR_REVIEW"), admin, db)
    assert exc.value.status_code == 404

    viewer = make_user(db, two.id, 6, UserRole.VIEWER)
    with pytest.raises(HTTPException) as exc:
        transition_readiness(outsider.id, ReadinessTransition(action="SUBMIT_FOR_REVIEW"), viewer, db)
    assert exc.value.status_code == 403


def test_delivery_platform_requires_operator_but_logistics_does_not(db):
    logistics = make_tenant(db, "Logistics")
    platform = make_tenant(db, "Platform", "DELIVERY_PLATFORM")
    logistics_admin = make_user(db, logistics.id, 7)
    platform_admin = make_user(db, platform.id, 8)
    logistics_supervisor = make_user(db, logistics.id, 8, UserRole.SUPERVISOR)
    platform_supervisor = make_user(db, platform.id, 9, UserRole.SUPERVISOR)
    logistics_rider = make_rider(db, logistics.id, 5, supervisor_id=logistics_supervisor.id)
    platform_rider = make_rider(db, platform.id, 6, supervisor_id=platform_supervisor.id)

    # Logistics: no operator needed
    assert transition_readiness(
        logistics_rider.id, ReadinessTransition(action="SUBMIT_FOR_REVIEW"), logistics_admin, db
    )["onboarding_status"] == "READY_FOR_REVIEW"

    # Platform: operator required
    with pytest.raises(HTTPException) as exc:
        transition_readiness(
            platform_rider.id, ReadinessTransition(action="SUBMIT_FOR_REVIEW"), platform_admin, db
        )
    assert "operator" in str(exc.value.detail)


# ---------- SHIFT ASSIGNMENT ----------

def test_assign_remove_and_list_shift_rider(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 9)
    supervisor = make_user(db, company.id, 10, UserRole.SUPERVISOR)
    courier = make_rider(db, company.id, 7, supervisor_id=supervisor.id)
    make_ready(db, courier)
    work_shift = make_shift(db, company.id)

    result = assign_rider(work_shift.id, ShiftAssignmentIn(courier_id=courier.id), admin, db)
    assert result["assigned"] is True
    assert [r["id"] for r in list_shift_riders(work_shift.id, admin, db)] == [courier.id]
    assert [s["id"] for s in list_rider_shifts(courier.id, admin, db)] == [work_shift.id]

    removed = remove_rider(work_shift.id, ShiftAssignmentIn(courier_id=courier.id), admin, db)
    assert removed["assigned"] is False
    assert list_shift_riders(work_shift.id, admin, db) == []


def test_shift_assignment_security_and_eligibility(db):
    one, two = make_tenant(db, "One"), make_tenant(db, "Two")
    admin = make_user(db, one.id, 10)
    supervisor = make_user(db, one.id, 11, UserRole.SUPERVISOR)
    own = make_rider(db, one.id, 8, supervisor.id)
    unrelated = make_rider(db, one.id, 9)
    outsider = make_rider(db, two.id, 10)
    for row in (own, unrelated, outsider):
        make_ready(db, row)
    work_shift = make_shift(db, one.id)

    # Cross-tenant
    with pytest.raises(HTTPException) as exc:
        assign_rider(work_shift.id, ShiftAssignmentIn(courier_id=outsider.id), admin, db)
    assert exc.value.status_code == 404

    # Supervisor cannot assign outside scope
    with pytest.raises(HTTPException) as exc:
        assign_rider(work_shift.id, ShiftAssignmentIn(courier_id=unrelated.id), supervisor, db)
    assert exc.value.status_code == 404

    # Supervisor can assign own rider
    assign_rider(work_shift.id, ShiftAssignmentIn(courier_id=own.id), supervisor, db)

    # Not-ready rider rejected
    not_ready = make_rider(db, one.id, 11, status="ONBOARDING")
    with pytest.raises(HTTPException) as exc:
        assign_rider(work_shift.id, ShiftAssignmentIn(courier_id=not_ready.id), admin, db)
    assert exc.value.status_code == 409


def test_overlapping_shift_rejected(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 12)
    courier = make_rider(db, company.id, 12)
    make_ready(db, courier)
    first = make_shift(db, company.id, "Morning", "08:00", "16:00")
    overlap = make_shift(db, company.id, "Overlap", "15:00", "20:00")
    assign_rider(first.id, ShiftAssignmentIn(courier_id=courier.id), admin, db)
    with pytest.raises(HTTPException) as exc:
        assign_rider(overlap.id, ShiftAssignmentIn(courier_id=courier.id), admin, db)
    assert exc.value.status_code == 409
    assert "overlap" in str(exc.value.detail).lower()


def test_cross_operator_shift_assignment_rejected(db):
    """Supervisor with riders from multiple operators cannot assign across operators."""
    platform = make_tenant(db, "Platform", "DELIVERY_PLATFORM")
    operator_a, operator_b = make_tenant(db, "A"), make_tenant(db, "B")
    source = SourcePlatform(tenant_id=platform.id, code="SRC", name_ar="Source", is_active=True)
    db.add(source); db.commit(); db.refresh(source)
    admin = make_user(db, platform.id, 13)
    supervisor = make_user(db, platform.id, 14, UserRole.SUPERVISOR)
    # Both riders in supervisor's scope, but different operators
    first = make_rider(db, platform.id, 13, supervisor_id=supervisor.id)
    second = make_rider(db, platform.id, 14, supervisor_id=supervisor.id)
    for row in (first, second):
        make_ready(db, row)
    db.add_all([
        PlatformOperator(tenant_id=platform.id, operator_tenant_id=operator_a.id, source_platform_id=source.id, is_active=True),
        PlatformOperator(tenant_id=platform.id, operator_tenant_id=operator_b.id, source_platform_id=source.id, is_active=True),
        RiderAssignment(tenant_id=platform.id, courier_id=first.id, operator_id=operator_a.id, effective_from=date.today(), status="ACTIVE"),
        RiderAssignment(tenant_id=platform.id, courier_id=second.id, operator_id=operator_b.id, effective_from=date.today(), status="ACTIVE"),
    ])
    db.commit()
    work_shift = make_shift(db, platform.id)
    assign_rider(work_shift.id, ShiftAssignmentIn(courier_id=first.id), admin, db)
    with pytest.raises(HTTPException) as exc:
        assign_rider(work_shift.id, ShiftAssignmentIn(courier_id=second.id), supervisor, db)
    assert exc.value.status_code == 409


# ---------- SUPERVISOR ----------

def test_supervisor_operational_endpoints_are_scoped(db):
    company = make_tenant(db)
    supervisor = make_user(db, company.id, 14, UserRole.SUPERVISOR)
    other_supervisor = make_user(db, company.id, 15, UserRole.SUPERVISOR)
    own = make_rider(db, company.id, 15, supervisor.id)
    other = make_rider(db, company.id, 16, other_supervisor.id)
    make_ready(db, own)
    make_ready(db, other)
    db.add_all([
        Attendance(courier_id=own.id, check_in=datetime.now()),
        Attendance(courier_id=other.id, check_in=datetime.now()),
        DailyLog(tenant_id=company.id, courier_id=own.id, log_date=date.today(), orders_count=7),
        DailyLog(tenant_id=company.id, courier_id=other.id, log_date=date.today(), orders_count=99),
    ])
    work_shift = make_shift(db, company.id)
    work_shift.courier_ids = json.dumps([own.id, other.id])
    db.commit()

    riders = supervisor_riders(search=None, status=None, user=supervisor, db=db)
    assert [row["id"] for row in riders] == [own.id]

    overview = supervisor_overview(user=supervisor, db=db)
    assert overview["assigned_riders"] == 1
    assert overview["attendance_today"] == 1

    attendance = supervisor_attendance(user=supervisor, db=db)
    assert [row["courier_id"] for row in attendance] == [own.id]

    performance = supervisor_performance(period=None, user=supervisor, db=db)
    assert [row["courier_id"] for row in performance["riders"]] == [own.id]
    assert performance["riders"][0]["completed_orders"] == 7

    attention = supervisor_needs_attention(user=supervisor, db=db)
    assert all(item.get("courier_id") in (None, own.id) for item in attention["items"])


def test_non_supervisor_cannot_use_supervisor_workspace(db):
    company = make_tenant(db)
    admin = make_user(db, company.id, 16)
    with pytest.raises(HTTPException) as exc:
        supervisor_overview(user=admin, db=db)
    assert exc.value.status_code == 403
