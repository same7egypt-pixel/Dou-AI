import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.entities import Country, Fleet, Tenant, User, UserRole
from app.routers.couriers import create_courier
from app.schemas.dou import CourierCreate


def test_company_cannot_create_courier_in_another_tenants_fleet():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        own_tenant = Tenant(name="Own tenant", country=Country.SA)
        other_tenant = Tenant(name="Other tenant", country=Country.SA)
        session.add_all([own_tenant, other_tenant])
        session.flush()
        other_fleet = Fleet(tenant_id=other_tenant.id, name="Other fleet")
        session.add(other_fleet)
        session.commit()

        company_user = User(
            phone="966500000001",
            name="Company admin",
            password_hash="not-used",
            role=UserRole.COMPANY,
            tenant_id=own_tenant.id,
            country=Country.SA,
            is_active=True,
        )
        payload = CourierCreate(
            name="Cross-tenant courier",
            phone="966500000002",
            courier_type="COMPANY",
            country="SA",
            fleet_id=other_fleet.id,
        )

        with pytest.raises(HTTPException) as error:
            create_courier(payload, company_user, session)

        assert error.value.status_code == 404
    finally:
        session.close()


def test_company_can_create_courier_in_its_own_fleet():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        tenant = Tenant(name="Own tenant", country=Country.SA)
        session.add(tenant)
        session.flush()
        fleet = Fleet(tenant_id=tenant.id, name="Own fleet")
        session.add(fleet)
        session.commit()

        company_user = User(
            phone="966500000003",
            name="Company admin",
            password_hash="not-used",
            role=UserRole.COMPANY,
            tenant_id=tenant.id,
            country=Country.SA,
            is_active=True,
        )
        payload = CourierCreate(
            name="Own courier",
            phone="966500000004",
            courier_type="COMPANY",
            country="SA",
            fleet_id=fleet.id,
        )

        courier = create_courier(payload, company_user, session)

        assert courier.tenant_id == tenant.id
        assert courier.fleet_id == fleet.id
    finally:
        session.close()
