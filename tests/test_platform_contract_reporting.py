from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import entities as ent
from app.routers import reports


CSV_TEXT = """Created Date,City Name,Contract Name,# Riders,Shifts Done,Planned Hours,Actual Working Hours,Break Hours,Acceptance Rate,Contact Rate,No Shows,Notified Deliveries,Completed Deliveries,Accepted Deliveries,Stacked Deliveries,Declined Deliveries,Cancelled Deliveries,Deduction Deliveries,Not Accepted Deliveries
2026-09-01,Riyadh,external_platform_code,8,23,100,90,4,0.98,0.01,1,160,150,157,5,2,1,0,0
"""


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def tenant_user_contract(db, suffix="one"):
    tenant = ent.Tenant(name=f"Tenant {suffix}", country=ent.Country.SA)
    db.add(tenant)
    db.flush()
    user = ent.User(
        phone=f"96650000{tenant.id:04d}",
        password_hash="x",
        role=ent.UserRole.COMPANY_ADMIN,
        tenant_id=tenant.id,
    )
    contract = ent.Contract(
        tenant_id=tenant.id,
        name=f"Ninja Riyadh {suffix}",
        status="ACTIVE",
    )
    db.add_all([user, contract])
    db.commit()
    return tenant, user, contract


def test_platform_upload_requires_contract(db):
    _, user, _ = tenant_user_contract(db)
    with pytest.raises(HTTPException) as exc:
        reports.upload_platform_delivery_facts(
            payload={"csv_text": CSV_TEXT}, user=user, db=db
        )
    assert exc.value.status_code == 400


def test_platform_upload_links_rows_to_selected_tenant_contract(db):
    tenant, user, contract = tenant_user_contract(db)
    result = reports.upload_platform_delivery_facts(
        payload={"csv_text": CSV_TEXT, "contract_id": contract.id},
        user=user,
        db=db,
    )
    fact = db.query(ent.PlatformDeliveryFact).one()
    assert result["contract"] == {"id": contract.id, "name": contract.name}
    assert fact.tenant_id == tenant.id
    assert fact.contract_id == contract.id
    assert fact.contract_name == contract.name
    assert fact.created_date == date(2026, 9, 1)


def test_platform_upload_rejects_contract_from_another_tenant(db):
    _, user, _ = tenant_user_contract(db, "first")
    _, _, other_contract = tenant_user_contract(db, "second")
    with pytest.raises(HTTPException) as exc:
        reports.upload_platform_delivery_facts(
            payload={"csv_text": CSV_TEXT, "contract_id": other_contract.id},
            user=user,
            db=db,
        )
    assert exc.value.status_code == 404


def test_platform_summary_filters_by_contract_id(db):
    _, user, first = tenant_user_contract(db, "primary")
    second = ent.Contract(tenant_id=user.tenant_id, name="Ninja Jeddah", status="ACTIVE")
    db.add(second)
    db.commit()
    reports.upload_platform_delivery_facts(
        payload={"csv_text": CSV_TEXT, "contract_id": first.id}, user=user, db=db
    )
    reports.upload_platform_delivery_facts(
        payload={"csv_text": CSV_TEXT, "contract_id": second.id}, user=user, db=db
    )
    result = reports.get_platform_delivery_facts(
        contract_id=second.id,
        contract_name=None,
        month=None,
        user=user,
        db=db,
    )
    assert result["summary"]["total_records"] == 1
    assert result["rows"][0]["contract_id"] == second.id
    assert result["rows"][0]["contract_name"] == second.name
