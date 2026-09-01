"""W7 backend tests — Operations Command Center API."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Attendance, Contract, ContractBranch, Courier, CourierType, Country, GeoCity, GeoCountry,
    LeaveRequest, OperationalImportBatch, OperationalReadinessState,
    RiderVehicleAssignment, Tenant, User, UserRole, Vehicle,
)
from app.routers import dashboard as dashboard_router


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


def make_tenant(db, name="TestCo"):
    t = Tenant(name=name, country=Country.SA)
    db.add(t); db.commit(); db.refresh(t)
    return t


def make_admin(db, tenant_id):
    u = User(phone="966500000001", password_hash="x", role=UserRole.COMPANY_ADMIN, tenant_id=tenant_id)
    db.add(u); db.commit(); db.refresh(u)
    return u


def make_country(db):
    c = GeoCountry(name="Saudi Arabia", code="SA", flag="🇸🇦", active=True)
    db.add(c); db.commit(); db.refresh(c)
    return c


def make_city(db, country_id, name="Riyadh"):
    c = GeoCity(country_id=country_id, name=name, active=True)
    db.add(c); db.commit(); db.refresh(c)
    return c


def make_operating_city(db, tenant_id, geo_city_id):
    from app.models.entities import TenantOperatingCity
    oc = TenantOperatingCity(tenant_id=tenant_id, geo_city_id=geo_city_id, display_name="Riyadh", is_active=True)
    db.add(oc); db.commit(); db.refresh(oc)
    return oc


def make_contract(db, tenant_id):
    c = Contract(tenant_id=tenant_id, name="HS Riyadh")
    db.add(c); db.commit(); db.refresh(c)
    return c


def make_branch(db, tenant_id, contract_id, city_id):
    b = ContractBranch(tenant_id=tenant_id, contract_id=contract_id, city_id=city_id, city="Riyadh", is_active=True)
    db.add(b); db.commit(); db.refresh(b)
    return b


def make_rider(db, tenant_id, city_id, contract_id, branch_id, name="Rider", phone="966500000100", status="ACTIVE"):
    r = Courier(
        tenant_id=tenant_id, name=name, phone=phone, courier_type=CourierType.COMPANY,
        country=Country.SA, employment_status=status, city_id=city_id,
        contract_id=contract_id, contract_branch_id=branch_id,
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


def test_dashboard_summary_basic(db):
    """Test basic dashboard summary with riders."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    # Create riders
    make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000102")
    make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000103", status="SUSPENDED")
    
    result = dashboard_router.dashboard_summary(user=admin, db=db)
    
    assert result["total_riders"] == 3
    assert result["active_riders"] == 2  # Only ACTIVE ones


def test_dashboard_summary_with_attendance(db):
    """Test dashboard summary with today's attendance."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    r2 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000102")
    
    # Add attendance for one rider today
    db.add(Attendance(courier_id=r1.id, check_in=datetime.now()))
    db.commit()
    
    result = dashboard_router.dashboard_summary(user=admin, db=db)
    
    assert result["total_riders"] == 2
    assert result["attended_today"] == 1
    assert result["absent_today"] == 1  # active_riders - attended - on_leave


def test_dashboard_summary_tenant_isolation(db):
    """Test that dashboard only shows data for the current tenant."""
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    admin1 = make_admin(db, tenant_id=tenant1.id)
    
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    
    # Create operating cities for both tenants
    operating_city1 = make_operating_city(db, tenant_id=tenant1.id, geo_city_id=city.id)
    operating_city2 = make_operating_city(db, tenant_id=tenant2.id, geo_city_id=city.id)
    
    contract1 = make_contract(db, tenant_id=tenant1.id)
    contract2 = make_contract(db, tenant_id=tenant2.id)
    branch1 = make_branch(db, tenant_id=tenant1.id, contract_id=contract1.id, city_id=city.id)
    branch2 = make_branch(db, tenant_id=tenant2.id, contract_id=contract2.id, city_id=city.id)
    
    # Create riders for both tenants
    make_rider(db, tenant_id=tenant1.id, city_id=city.id, contract_id=contract1.id, branch_id=branch1.id, phone="966500000101")
    make_rider(db, tenant_id=tenant2.id, city_id=city.id, contract_id=contract2.id, branch_id=branch2.id, phone="966500000102")
    
    result = dashboard_router.dashboard_summary(user=admin1, db=db)
    
    assert result["total_riders"] == 1  # Only tenant1's rider


def test_needs_attention_absent_riders(db):
    """Test needs attention shows absent riders."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    r2 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000102")
    
    # Only r1 has attendance today
    db.add(Attendance(courier_id=r1.id, check_in=datetime.now()))
    db.commit()
    
    result = dashboard_router.needs_attention(user=admin, db=db)
    
    # Should have absent riders attention item
    absent_items = [item for item in result["items"] if item["signal"] == "absent_riders"]
    assert len(absent_items) == 1
    assert absent_items[0]["count"] == 1  # r2 is absent


def test_needs_attention_readiness_failures(db):
    """Test needs attention shows readiness failures."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    # Create readiness state showing not ready
    db.add(OperationalReadinessState(
        tenant_id=tenant.id, courier_id=r1.id, overall_status="NOT_READY"
    ))
    db.commit()
    
    result = dashboard_router.needs_attention(user=admin, db=db)
    
    readiness_items = [item for item in result["items"] if item["signal"] == "readiness_failures"]
    assert len(readiness_items) == 1
    assert readiness_items[0]["count"] == 1


def test_needs_attention_no_issues(db):
    """Test needs attention returns empty when no issues."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    
    result = dashboard_router.needs_attention(user=admin, db=db)
    
    assert result["items"] == []
    assert result["total"] == 0


def test_workforce_trend_basic(db):
    """Test workforce trend returns data for last 7 days."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    # Add attendance for today
    db.add(Attendance(courier_id=r1.id, check_in=datetime.now()))
    db.commit()
    
    result = dashboard_router.workforce_trend(user=admin, db=db, days=7)
    
    assert len(result["trend"]) == 7
    assert result["period_days"] == 7
    # Today should have 1 attended
    assert result["trend"][-1]["attended"] == 1


def test_dashboard_rbac_required(db):
    """Test that dashboard requires proper RBAC roles."""
    tenant = make_tenant(db)
    # Create a user with invalid role
    u = User(phone="966500000002", password_hash="x", role=UserRole.SUPERVISOR, tenant_id=tenant.id)
    db.add(u); db.commit()
    
    # Supervisor should have access
    result = dashboard_router.dashboard_summary(user=u, db=db)
    assert result is not None


def test_dashboard_no_cross_tenant_data(db):
    """Test that dashboard doesn't expose cross-tenant data."""
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    admin2 = make_admin(db, tenant_id=tenant2.id)
    
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city1 = make_operating_city(db, tenant_id=tenant1.id, geo_city_id=city.id)
    contract1 = make_contract(db, tenant_id=tenant1.id)
    branch1 = make_branch(db, tenant_id=tenant1.id, contract_id=contract1.id, city_id=city.id)
    
    # Create rider for tenant1 only
    make_rider(db, tenant_id=tenant1.id, city_id=city.id, contract_id=contract1.id, branch_id=branch1.id, phone="966500000101")
    
    # Tenant2 admin should see 0 riders
    result = dashboard_router.dashboard_summary(user=admin2, db=db)
    assert result["total_riders"] == 0
