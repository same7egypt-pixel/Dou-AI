from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import Country, Courier, CourierType, RiderVehicleAssignment, Tenant, User, UserRole
from app.routers.vehicles import (
    VehicleAssignmentCreate, VehicleCreate, VehicleDocumentCreate, VehicleTransfer,
    add_vehicle_document, assign_vehicle, create_vehicle, rider_vehicle_readiness,
    transfer_rider_vehicle,
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


def setup_tenant(db, name, phone):
    tenant = Tenant(name=name, country=Country.SA, market_code="SA")
    db.add(tenant); db.flush()
    user = User(phone=phone, password_hash="x", role=UserRole.COMPANY, tenant_id=tenant.id)
    db.add(user); db.commit(); db.refresh(tenant); db.refresh(user)
    return tenant, user


def make_rider(db, tenant_id, suffix):
    row = Courier(tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"700{suffix}", courier_type=CourierType.COMPANY, country=Country.SA)
    db.add(row); db.commit(); db.refresh(row)
    return row


def test_plate_is_normalized_and_unique_within_market(db):
    _, user = setup_tenant(db, "Owner", "owner-1")
    first = create_vehicle(VehicleCreate(plate_number="ABC 123", vehicle_type="CAR"), user, db)
    assert first["plate_normalized"] == "ABC123"

    with pytest.raises(HTTPException) as error:
        create_vehicle(VehicleCreate(plate_number="abc-123", vehicle_type="CAR"), user, db)
    assert error.value.status_code == 409


def test_assignment_rejects_cross_tenant_rider(db):
    first, user = setup_tenant(db, "First", "owner-2")
    second, _ = setup_tenant(db, "Second", "owner-3")
    vehicle = create_vehicle(VehicleCreate(plate_number="SA 1", vehicle_type="BIKE"), user, db)
    foreign = make_rider(db, second.id, "2")

    with pytest.raises(HTTPException) as error:
        assign_vehicle(vehicle["id"], VehicleAssignmentCreate(courier_id=foreign.id, effective_from=date(2026, 1, 1)), user, db)
    assert error.value.status_code == 404


def test_exclusive_vehicle_assignments_cannot_overlap(db):
    tenant, user = setup_tenant(db, "Owner", "owner-4")
    vehicle = create_vehicle(VehicleCreate(plate_number="SA 2", vehicle_type="CAR", is_exclusive=True), user, db)
    first = make_rider(db, tenant.id, "3")
    second = make_rider(db, tenant.id, "4")
    assign_vehicle(vehicle["id"], VehicleAssignmentCreate(courier_id=first.id, effective_from=date(2026, 1, 1)), user, db)

    with pytest.raises(HTTPException) as error:
        assign_vehicle(vehicle["id"], VehicleAssignmentCreate(courier_id=second.id, effective_from=date(2026, 2, 1)), user, db)
    assert error.value.status_code == 409


def test_vehicle_transfer_preserves_history_and_readiness_explains_documents(db):
    tenant, user = setup_tenant(db, "Owner", "owner-5")
    old_vehicle = create_vehicle(VehicleCreate(plate_number="SA 3", vehicle_type="CAR"), user, db)
    new_vehicle = create_vehicle(VehicleCreate(plate_number="SA 4", vehicle_type="CAR"), user, db)
    rider = make_rider(db, tenant.id, "5")
    old = assign_vehicle(old_vehicle["id"], VehicleAssignmentCreate(courier_id=rider.id, effective_from=date(2026, 1, 1)), user, db)
    add_vehicle_document(new_vehicle["id"], VehicleDocumentCreate(document_type="REGISTRATION", expiry_date=date(2027, 1, 1)), user, db)

    new = transfer_rider_vehicle(rider.id, VehicleTransfer(vehicle_id=new_vehicle["id"], effective_on=date(2026, 3, 1)), user, db)
    previous = db.get(RiderVehicleAssignment, old["id"])
    readiness = rider_vehicle_readiness(rider.id, date(2026, 3, 2), user, db)

    assert previous.effective_to == date(2026, 2, 28)

