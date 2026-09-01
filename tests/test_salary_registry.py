"""Salary structure tests — W1-E3."""
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import Country, Courier, CourierType, Tenant, User, UserRole
from app.models.salary import SalaryComponent, SalaryStructure, RiderSalaryAssignment
from app.routers.salary import (
    assign_rider_structure, create_structure, get_structure, list_structures,
    rider_assignments, rider_current_structure,
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


def make_user(db, tenant_id, phone):
    user = User(phone=phone, password_hash="x", role=UserRole.COMPANY, tenant_id=tenant_id)
    db.add(user); db.commit(); db.refresh(user)
    return user


def make_rider(db, tenant_id, suffix):
    rider = Courier(
        tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"700{suffix}",
        courier_type=CourierType.COMPANY, country=Country.SA,
    )
    db.add(rider); db.commit(); db.refresh(rider)
    return rider


def test_structure_code_unique_within_tenant(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000001")

    first = create_structure(
        type("Payload", (), {"code": "S1", "name_ar": "Basic", "name_en": "Basic", "description_ar": "", "description_en": "", "currency": "SAR", "cycle": "MONTHLY", "balance_period": False})(),
        user, db,
    )
    assert first["code"] == "S1"

    with pytest.raises(HTTPException) as error:
        create_structure(
            type("Payload", (), {"code": "S1", "name_ar": "Basic Again", "name_en": "Basic Again", "description_ar": "", "description_en": "", "currency": "SAR", "cycle": "MONTHLY", "balance_period": False})(),
            user, db,
        )
    assert error.value.status_code == 409


def test_structure_rejects_another_tenant_code(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000002")
    make_user(db, tenant2.id, "966500000003")

    create_structure(
        type("Payload", (), {"code": "S1", "name_ar": "S1", "name_en": "S1", "description_ar": "", "description_en": "", "currency": "SAR", "cycle": "MONTHLY", "balance_period": False})(),
        user1, db,
    )
    second = create_structure(
        type("Payload", (), {"code": "S1", "name_ar": "S1", "name_en": "S1", "description_ar": "", "description_en": "", "currency": "SAR", "cycle": "MONTHLY", "balance_period": False})(),
        make_user(db, tenant2.id, "966500000004"), db,
    )
    assert second["code"] == "S1"


def test_assignment_preserves_effective_date_and_rejects_cross_tenant_rider(db):
    tenant, user = (None, None)
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")
    rider1 = make_rider(db, tenant.id, "1")
    rider2 = make_rider(db, tenant.id, "2")
    structure = create_structure(
        type("Payload", (), {"code": "S2", "name_ar": "S2", "name_en": "S2", "description_ar": "", "description_en": "", "currency": "SAR", "cycle": "MONTHLY", "balance_period": False})(),
        user, db,
    )

    assign_rider_structure(
        rider1.id,
        type("Payload", (), {"courier_id": rider1.id, "salary_structure_id": structure["id"], "effective_from": date(2026, 1, 1)})(),
        user, db,
    )

    with pytest.raises(HTTPException) as error:
        assign_rider_structure(
            rider2.id,
            type("Payload", (), {"courier_id": rider1.id, "salary_structure_id": structure["id"], "effective_from": date(2026, 1, 1)})(),
            user, db,
        )
    assert error.value.status_code == 403


def test_current_structure_returns_active_assignment(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    rider = make_rider(db, tenant.id, "3")
    structure = create_structure(
        type("Payload", (), {"code": "S3", "name_ar": "S3", "name_en": "S3", "description_ar": "", "description_en": "", "currency": "SAR", "cycle": "MONTHLY", "balance_period": False})(),
        user, db,
    )
    assign_rider_structure(
        rider.id,
        type("Payload", (), {"courier_id": rider.id, "salary_structure_id": structure["id"], "effective_from": date(2026, 1, 1)})(),
        user, db,
    )

    current = rider_current_structure(rider.id, date(2026, 3, 1), user, db)
    assert current["as_of"] == "2026-03-01"
    assert current["salary_structure"]["id"] == structure["id"]


def test_assignments_include_history_when_requested(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    rider = make_rider(db, tenant.id, "4")
    structure = create_structure(
        type("Payload", (), {"code": "S4", "name_ar": "S4", "name_en": "S4", "description_ar": "", "description_en": "", "currency": "SAR", "cycle": "MONTHLY", "balance_period": False})(),
        user, db,
    )
    assign_rider_structure(
        rider.id,
        type("Payload", (), {"courier_id": rider.id, "salary_structure_id": structure["id"], "effective_from": date(2026, 1, 1)})(),
        user, db,
    )
    assign_rider_structure(
        rider.id,
        type("Payload", (), {"courier_id": rider.id, "salary_structure_id": structure["id"], "effective_from": date(2026, 3, 1)})(),
        user, db,
    )

    current_list = rider_assignments(rider.id, include_history=False, user=user, db=db)
    assert len(current_list) == 1

    full_list = rider_assignments(rider.id, include_history=True, user=user, db=db)
    assert len(full_list) == 2
    assert full_list[0]["effective_from"] == "2026-03-01"
    assert full_list[1]["effective_from"] == "2026-01-01"
