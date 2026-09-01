"""W8 backend tests — Performance Management API."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Attendance, Contract, ContractBranch, Courier, CourierType, Country, GeoCity, GeoCountry,
    KPIDefinition, KPIResult, Target, Tenant, User, UserRole,
)
from app.routers import performance as perf_router


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


def test_performance_summary_basic(db):
    """Test basic performance summary."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000102")
    
    result = perf_router.performance_summary(user=admin, db=db)
    
    assert result["total_riders"] == 2


def test_performance_summary_with_attendance(db):
    """Test performance summary with attendance data."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    r2 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000102")
    
    # Add attendance for one rider
    db.add(Attendance(courier_id=r1.id, check_in=datetime.now()))
    db.commit()
    
    result = perf_router.performance_summary(user=admin, db=db)
    
    assert result["total_riders"] == 2
    assert result["attendance_rate"] == 50.0


def test_performance_summary_tenant_isolation(db):
    """Test tenant isolation in performance summary."""
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    admin1 = make_admin(db, tenant_id=tenant1.id)
    
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city1 = make_operating_city(db, tenant_id=tenant1.id, geo_city_id=city.id)
    operating_city2 = make_operating_city(db, tenant_id=tenant2.id, geo_city_id=city.id)
    contract1 = make_contract(db, tenant_id=tenant1.id)
    contract2 = make_contract(db, tenant_id=tenant2.id)
    branch1 = make_branch(db, tenant_id=tenant1.id, contract_id=contract1.id, city_id=city.id)
    branch2 = make_branch(db, tenant_id=tenant2.id, contract_id=contract2.id, city_id=city.id)
    
    make_rider(db, tenant_id=tenant1.id, city_id=city.id, contract_id=contract1.id, branch_id=branch1.id, phone="966500000101")
    make_rider(db, tenant_id=tenant2.id, city_id=city.id, contract_id=contract2.id, branch_id=branch2.id, phone="966500000102")
    
    result = perf_router.performance_summary(user=admin1, db=db)
    
    assert result["total_riders"] == 1


def test_performance_explorer_basic(db):
    """Test performance explorer returns rider rows."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    result = perf_router.performance_explorer(user=admin, db=db)
    
    assert result["total"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["name"] is not None


def test_performance_explorer_with_targets(db):
    """Test performance explorer with targets."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    # Create target
    period = date.today().strftime("%Y-%m")
    db.add(Target(
        tenant_id=tenant.id, scope_type="RIDER", scope_id=r1.id,
        target_type="ORDERS", period=period, target_value=100,
        actual_value=80, achievement_percentage=80,
    ))
    db.commit()
    
    result = perf_router.performance_explorer(user=admin, db=db)
    
    assert len(result["rows"]) == 1
    assert result["rows"][0]["target_value"] == 100
    assert result["rows"][0]["achievement_percentage"] == 80


def test_performance_explorer_filter_status(db):
    """Test performance explorer status filtering."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    r2 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000102")
    
    # Create target for r1 (achieved)
    period = date.today().strftime("%Y-%m")
    db.add(Target(
        tenant_id=tenant.id, scope_type="RIDER", scope_id=r1.id,
        target_type="ORDERS", period=period, target_value=100,
        actual_value=100, achievement_percentage=100,
    ))
    # r2 has no target
    db.commit()
    
    # Filter for riders with no target
    result = perf_router.performance_explorer(user=admin, db=db, status_filter="no_target")
    
    assert len(result["rows"]) == 1
    assert result["rows"][0]["courier_id"] == r2.id


def test_scorecard_basic(db):
    """Test performance scorecard."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    # Create KPI definition and result
    kpi_def = KPIDefinition(
        tenant_id=tenant.id, code="COMPLETION_RATE", name_ar="معدل الإكمال",
        numerator_expression="completed_orders", unit="PERCENTAGE",
        effective_from=date.today(),
    )
    db.add(kpi_def); db.commit()
    
    period = date.today().strftime("%Y-%m")
    db.add(KPIResult(
        tenant_id=tenant.id, kpi_definition_id=kpi_def.id,
        scope_type="RIDER", scope_id=r1.id, period=period,
        result_value=85.5,
    ))
    db.commit()
    
    result = perf_router.performance_scorecard(
        scope_type="RIDER", scope_id=r1.id, user=admin, db=db
    )
    
    assert result["scope_type"] == "RIDER"
    assert result["scope_id"] == r1.id
    assert len(result["kpis"]) == 1
    assert result["kpis"][0]["result_value"] == 85.5


def test_trends_basic(db):
    """Test performance trends."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    result = perf_router.performance_trends(
        scope_type="RIDER", scope_id=r1.id, months=6, user=admin, db=db
    )
    
    assert len(result["trends"]) == 6


def test_incentives_basic(db):
    """Test performance incentives visibility."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    result = perf_router.performance_incentives(courier_id=r1.id, user=admin, db=db)
    
    assert "incentives" in result
    assert "total_earnings" in result
    assert "total_deductions" in result


def test_performance_rbac_required(db):
    """Test that performance endpoints require proper RBAC."""
    tenant = make_tenant(db)
    u = User(phone="966500000002", password_hash="x", role=UserRole.SUPERVISOR, tenant_id=tenant.id)
    db.add(u); db.commit()
    
    # Supervisor should have access
    result = perf_router.performance_summary(user=u, db=db)
    assert result is not None
