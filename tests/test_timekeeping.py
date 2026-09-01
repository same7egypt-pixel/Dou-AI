"""Timekeeping and attendance corrections tests — W1-E4."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    AttendanceCorrectionRequest, Courier, CourierType, Country,
    Overtime, ShiftOccurrence, ShiftTemplate, Tenant, User, UserRole,
    WorkSession,
)
from app.routers.timekeeping import (
    CorrectionDecision, CorrectionRequestCreate, GenerateOccurrences,
    OvertimeCreate, OvertimeDecision, ShiftTemplateCreate, ShiftTemplateUpdate,
    WorkSessionEnd, WorkSessionStart,
    create_correction, create_overtime, create_template, decide_correction,
    decide_overtime, end_session, generate_occurrences, list_corrections,
    list_overtime, list_templates, start_session, update_template,
    _generate_occurrences,
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


# ---------- shift templates ----------

def test_create_template_within_tenant(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000001")
    result = create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", name_en="Morning", start_time="08:00", end_time="16:00", required_couriers=5),
        user, db,
    )
    assert result["code"] == "T1"


def test_template_code_unique_within_tenant(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", start_time="08:00", end_time="16:00"),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_template(
            ShiftTemplateCreate(code="T1", name_ar="Evening", start_time="16:00", end_time="23:00"),
            user, db,
        )
    assert error.value.status_code == 409


def test_template_rejects_cross_tenant_code(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000003")
    user2 = make_user(db, tenant2.id, "966500000004")
    create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", start_time="08:00", end_time="16:00"),
        user1, db,
    )
    result = create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", start_time="08:00", end_time="16:00"),
        user2, db,
    )
    assert result["code"] == "T1"


def test_list_templates_filters_by_tenant(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000005")
    user2 = make_user(db, tenant2.id, "966500000006")
    create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", start_time="08:00", end_time="16:00"),
        user1, db,
    )
    create_template(
        ShiftTemplateCreate(code="T2", name_ar="Evening", start_time="16:00", end_time="23:00"),
        user2, db,
    )
    templates = list_templates(active_only=False, user=user1, db=db)
    assert len(templates) == 1
    assert templates[0]["code"] == "T1"


def test_update_template(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    created = create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", start_time="08:00", end_time="16:00"),
        user, db,
    )
    updated = update_template(
        created["id"],
        ShiftTemplateUpdate(name_ar="Updated Morning", start_time="09:00"),
        user, db,
    )
    assert updated["name_ar"] == "Updated Morning"


# ---------- shift occurrences ----------

def test_generate_occurrences(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000008")
    template = create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", start_time="08:00", end_time="16:00"),
        user, db,
    )
    result = generate_occurrences(
        template["id"],
        GenerateOccurrences(from_date=date(2026, 9, 1), to_date=date(2026, 9, 3)),
        user, db,
    )
    assert result["generated"] == 3


def test_generate_occurrences_idempotent(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000009")
    template = create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", start_time="08:00", end_time="16:00"),
        user, db,
    )
    payload = GenerateOccurrences(from_date=date(2026, 9, 1), to_date=date(2026, 9, 2))
    first = generate_occurrences(template["id"], payload, user, db)
    second = generate_occurrences(template["id"], payload, user, db)
    assert first["generated"] == 2
    assert second["generated"] == 0


def test_generate_occurrences_overnight(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000010")
    template = create_template(
        ShiftTemplateCreate(code="T1", name_ar="Night", start_time="22:00", end_time="06:00"),
        user, db,
    )
    result = generate_occurrences(
        template["id"],
        GenerateOccurrences(from_date=date(2026, 9, 1), to_date=date(2026, 9, 1)),
        user, db,
    )
    assert result["generated"] == 1
    occ = db.query(ShiftOccurrence).first()
    assert occ.end_datetime > occ.start_datetime  # End is next day


# ---------- work sessions ----------

def test_start_session(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000011")
    rider = make_rider(db, tenant.id, "1")
    result = start_session(
        WorkSessionStart(courier_id=rider.id, session_type="WORK"),
        user, db,
    )
    assert result["session_type"] == "WORK"
    assert result["courier_id"] == rider.id


def test_start_session_rejects_duplicate_open(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000012")
    rider = make_rider(db, tenant.id, "2")
    start_session(
        WorkSessionStart(courier_id=rider.id, session_type="WORK"),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        start_session(
            WorkSessionStart(courier_id=rider.id, session_type="BREAK"),
            user, db,
        )
    assert error.value.status_code == 409


def test_end_session(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000013")
    rider = make_rider(db, tenant.id, "3")
    started = start_session(
        WorkSessionStart(courier_id=rider.id, session_type="WORK"),
        user, db,
    )
    ended = end_session(
        WorkSessionEnd(session_id=started["id"]),
        user, db,
    )
    assert ended["duration_minutes"] >= 0


def test_end_session_rejects_double_end(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000014")
    rider = make_rider(db, tenant.id, "4")
    started = start_session(
        WorkSessionStart(courier_id=rider.id, session_type="WORK"),
        user, db,
    )
    end_session(WorkSessionEnd(session_id=started["id"]), user, db)
    with pytest.raises(HTTPException) as error:
        end_session(WorkSessionEnd(session_id=started["id"]), user, db)
    assert error.value.status_code == 409


# ---------- attendance correction requests ----------

def test_create_correction_request(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000015")
    rider = make_rider(db, tenant.id, "5")
    result = create_correction(
        CorrectionRequestCreate(
            courier_id=rider.id,
            requested_check_in=datetime(2026, 9, 1, 8, 0),
            reason="Forgot to check in",
        ),
        user, db,
    )
    assert result["status"] == "PENDING"
    assert result["courier_id"] == rider.id


def test_create_correction_rejects_empty_reason(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000016")
    rider = make_rider(db, tenant.id, "6")
    with pytest.raises(HTTPException) as error:
        create_correction(
            CorrectionRequestCreate(courier_id=rider.id, reason="   "),
            user, db,
        )
    assert error.value.status_code == 400


def test_decide_correction_approved(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000017")
    rider = make_rider(db, tenant.id, "7")
    created = create_correction(
        CorrectionRequestCreate(courier_id=rider.id, reason="Forgot to check in"),
        user, db,
    )
    result = decide_correction(
        created["id"],
        CorrectionDecision(decision="APPROVED", note="Approved"),
        user, db,
    )
    assert result["status"] == "APPROVED"
    assert result["decided_by"] == user.id


def test_decide_correction_rejects_invalid_decision(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000018")
    rider = make_rider(db, tenant.id, "8")
    created = create_correction(
        CorrectionRequestCreate(courier_id=rider.id, reason="Forgot to check in"),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        decide_correction(
            created["id"],
            CorrectionDecision(decision="MAYBE"),
            user, db,
        )
    assert error.value.status_code == 400


def test_decide_correction_rejects_double_decision(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000019")
    rider = make_rider(db, tenant.id, "9")
    created = create_correction(
        CorrectionRequestCreate(courier_id=rider.id, reason="Forgot to check in"),
        user, db,
    )
    decide_correction(
        created["id"],
        CorrectionDecision(decision="APPROVED"),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        decide_correction(
            created["id"],
            CorrectionDecision(decision="REJECTED"),
            user, db,
        )
    assert error.value.status_code == 409


def test_list_corrections_filters_by_status(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000020")
    rider = make_rider(db, tenant.id, "10")
    c1 = create_correction(
        CorrectionRequestCreate(courier_id=rider.id, reason="Reason 1"),
        user, db,
    )
    create_correction(
        CorrectionRequestCreate(courier_id=rider.id, reason="Reason 2"),
        user, db,
    )
    decide_correction(
        c1["id"],
        CorrectionDecision(decision="APPROVED"),
        user, db,
    )
    pending = list_corrections(status_filter="PENDING", user=user, db=db)
    assert len(pending) == 1
    approved = list_corrections(status_filter="APPROVED", user=user, db=db)
    assert len(approved) == 1


# ---------- overtime ----------

def test_create_overtime(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000021")
    rider = make_rider(db, tenant.id, "11")
    result = create_overtime(
        OvertimeCreate(
            courier_id=rider.id,
            overtime_date=date(2026, 9, 1),
            requested_minutes=60,
        ),
        user, db,
    )
    assert result["status"] == "PENDING"
    assert result["requested_minutes"] == 60


def test_create_overtime_rejects_zero_minutes(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000022")
    rider = make_rider(db, tenant.id, "12")
    with pytest.raises(HTTPException) as error:
        create_overtime(
            OvertimeCreate(
                courier_id=rider.id,
                overtime_date=date(2026, 9, 1),
                requested_minutes=0,
            ),
            user, db,
        )
    assert error.value.status_code == 400


def test_decide_overtime_approved(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000023")
    rider = make_rider(db, tenant.id, "13")
    created = create_overtime(
        OvertimeCreate(
            courier_id=rider.id,
            overtime_date=date(2026, 9, 1),
            requested_minutes=60,
        ),
        user, db,
    )
    result = decide_overtime(
        created["id"],
        OvertimeDecision(decision="APPROVED", approved_minutes=45),
        user, db,
    )
    assert result["status"] == "APPROVED"
    assert result["approved_minutes"] == 45


def test_decide_overtime_rejected(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000024")
    rider = make_rider(db, tenant.id, "14")
    created = create_overtime(
        OvertimeCreate(
            courier_id=rider.id,
            overtime_date=date(2026, 9, 1),
            requested_minutes=60,
        ),
        user, db,
    )
    result = decide_overtime(
        created["id"],
        CorrectionDecision(decision="REJECTED"),
        user, db,
    )
    assert result["status"] == "REJECTED"
    assert result["approved_minutes"] == 0


def test_decide_overtime_rejects_double_decision(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000025")
    rider = make_rider(db, tenant.id, "15")
    created = create_overtime(
        OvertimeCreate(
            courier_id=rider.id,
            overtime_date=date(2026, 9, 1),
            requested_minutes=60,
        ),
        user, db,
    )
    decide_overtime(
        created["id"],
        OvertimeDecision(decision="APPROVED", approved_minutes=30),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        decide_overtime(
            created["id"],
            CorrectionDecision(decision="REJECTED"),
            user, db,
        )
    assert error.value.status_code == 409


def test_list_overtime_filters_by_status(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000026")
    rider = make_rider(db, tenant.id, "16")
    o1 = create_overtime(
        OvertimeCreate(courier_id=rider.id, overtime_date=date(2026, 9, 1), requested_minutes=30),
        user, db,
    )
    create_overtime(
        OvertimeCreate(courier_id=rider.id, overtime_date=date(2026, 9, 2), requested_minutes=60),
        user, db,
    )
    decide_overtime(
        o1["id"],
        OvertimeDecision(decision="APPROVED", approved_minutes=30),
        user, db,
    )
    pending = list_overtime(status_filter="PENDING", user=user, db=db)
    assert len(pending) == 1
    approved = list_overtime(status_filter="APPROVED", user=user, db=db)
    assert len(approved) == 1


# ---------- tenant isolation ----------

def test_cross_tenant_correction_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000027")
    rider2 = make_rider(db, tenant2.id, "17")
    with pytest.raises(HTTPException) as error:
        create_correction(
            CorrectionRequestCreate(courier_id=rider2.id, reason="Test"),
            user1, db,
        )
    assert error.value.status_code == 404


def test_cross_tenant_overtime_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000028")
    rider2 = make_rider(db, tenant2.id, "18")
    with pytest.raises(HTTPException) as error:
        create_overtime(
            OvertimeCreate(courier_id=rider2.id, overtime_date=date(2026, 9, 1), requested_minutes=30),
            user1, db,
        )
    assert error.value.status_code == 404


def test_cross_tenant_template_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000029")
    template = create_template(
        ShiftTemplateCreate(code="T1", name_ar="Morning", start_time="08:00", end_time="16:00"),
        user1, db,
    )
    user2 = make_user(db, tenant2.id, "966500000030")
    with pytest.raises(HTTPException) as error:
        update_template(
            template["id"],
            ShiftTemplateUpdate(name_ar="Hacked"),
            user2, db,
        )
    assert error.value.status_code == 404
