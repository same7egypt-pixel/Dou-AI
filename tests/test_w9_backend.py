"""W9 backend tests — Payroll & Financial Operations API."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Attendance, Contract, ContractBranch, Courier, CourierType, Country, GeoCity, GeoCountry,
    IncentiveRule, PayrollInputRecord, Tenant, User, UserRole,
)
from app.routers import payroll as payroll_router


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


def test_payroll_summary_basic(db):
    """Test basic payroll summary."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    # Add payroll input (MANUAL goes to adjustments, not earnings)
    period = date.today().strftime("%Y-%m")
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=1000,
        description="راتب ثابت", status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_summary(user=admin, db=db)
    
    assert result["total_riders"] == 1
    assert result["total_adjustments"] == 1000  # MANUAL = adjustments
    assert result["net_amount"] == 1000  # Only adjustments count


def test_payroll_summary_tenant_isolation(db):
    """Test tenant isolation in payroll summary."""
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
    
    r1 = make_rider(db, tenant_id=tenant1.id, city_id=city.id, contract_id=contract1.id, branch_id=branch1.id, phone="966500000101")
    r2 = make_rider(db, tenant_id=tenant2.id, city_id=city.id, contract_id=contract2.id, branch_id=branch2.id, phone="966500000102")
    
    period = date.today().strftime("%Y-%m")
    db.add(PayrollInputRecord(
        tenant_id=tenant1.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=1000, status="APPROVED",
    ))
    db.add(PayrollInputRecord(
        tenant_id=tenant2.id, courier_id=r2.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=2000, status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_summary(user=admin1, db=db)
    
    assert result["total_riders"] == 1
    assert result["total_adjustments"] == 1000


def test_payroll_ledger_basic(db):
    """Test payroll ledger retrieval."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=1000, status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_ledger(user=admin, db=db)
    
    assert result["total"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["amount"] == 1000


def test_payroll_ledger_filtering(db):
    """Test payroll ledger filtering."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=1000, status="APPROVED",
    ))
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="DEDUCTION", amount=200, status="APPROVED",
    ))
    db.commit()
    
    # Filter by type
    result = payroll_router.payroll_ledger(user=admin, db=db, input_type="EARNING")
    assert result["total"] == 1
    assert result["rows"][0]["input_type"] == "EARNING"


def test_rider_payroll_breakdown(db):
    """Test rider payroll breakdown."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    # ATTENDANCE = base input
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="ATTENDANCE", input_type="EARNING", amount=1000, status="APPROVED",
    ))
    # MANUAL DEDUCTION
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="DEDUCTION", amount=200, status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.rider_payroll_breakdown(courier_id=r1.id, user=admin, db=db)
    
    assert result["courier_id"] == r1.id
    assert result["totals"]["base"] == 1000  # ATTENDANCE = base
    assert result["totals"]["manual"] == -200  # MANUAL DEDUCTION
    assert result["totals"]["net"] == 800


def test_payroll_incentives(db):
    """Test payroll incentives visibility."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    # Create incentive rule
    rule = IncentiveRule(
        tenant_id=tenant.id, code="BONUS", name_ar="مكافأة",
        rule_type="BONUS", calculation_expression="orders * 5",
        effective_from=date.today(),
    )
    db.add(rule); db.commit()
    
    period = date.today().strftime("%Y-%m")
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="RULE", source_id=rule.id, input_type="EARNING",
        amount=500, description="مكافأة أداء", status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_incentives(user=admin, db=db)
    
    assert len(result["incentives"]) == 1
    assert result["incentives"][0]["amount"] == 500
    assert result["total_earnings"] == 500


def test_payroll_readiness(db):
    """Test payroll readiness assessment."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    r2 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000102")
    
    # Only r1 has payroll inputs
    period = date.today().strftime("%Y-%m")
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=1000, status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_readiness(user=admin, db=db)
    
    assert result["total_active_riders"] == 2
    assert result["riders_with_inputs"] == 1
    assert result["missing_riders"] == 1
    assert result["readiness"] == "INCOMPLETE"


def test_cost_summary(db):
    """Test cost summary."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    # ATTENDANCE = base earnings
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="ATTENDANCE", input_type="EARNING", amount=1000, status="APPROVED",
    ))
    # MANUAL = adjustments (not in earnings/deductions)
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="DEDUCTION", amount=200, status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.cost_summary(user=admin, db=db)
    
    assert result["total_earnings"] == 1000  # ATTENDANCE only
    assert result["total_deductions"] == 0  # MANUAL excluded
    assert result["net_amount"] == 800  # 1000 - 200 = 800


def test_payroll_rbac_required(db):
    """Test that payroll endpoints require proper RBAC."""
    tenant = make_tenant(db)
    u = User(phone="966500000002", password_hash="x", role=UserRole.ACCOUNTANT, tenant_id=tenant.id)
    db.add(u); db.commit()
    
    # Accountant should have read access
    result = payroll_router.payroll_summary(user=u, db=db)
    assert result is not None
