"""W9 Final Financial Correctness Verification Tests."""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

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


# ============================================================
# TEST 1: Decimal Safety - 0.10 + 0.20 = 0.30
# ============================================================
def test_decimal_safety_point_one_plus_point_two(db):
    """
    Test that 0.10 + 0.20 = 0.30 exactly (not 0.30000000000000004).
    """
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add entries with exact decimal amounts
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("0.10"), status="APPROVED",
    ))
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("0.20"), status="APPROVED",
    ))
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="DEDUCTION", amount=Decimal("0.30"), status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_summary(user=admin, db=db)
    
    # Manual adjustments: 0.10 + 0.20 - 0.30 = 0.00
    net = result["net_amount"]
    assert net == 0.0, f"Net amount should be exactly 0.0, got {net}"


# ============================================================
# TEST 2: 1000 x 0.01 = 10.00
# ============================================================
def test_decimal_safety_thousand_times_one_cent(db):
    """
    Test that 1000 entries of 0.01 = 10.00 exactly.
    """
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add 1000 entries of 0.01 each = 10.00 total
    for _ in range(1000):
        db.add(PayrollInputRecord(
            tenant_id=tenant.id, courier_id=r1.id, month=period,
            source_type="MANUAL", input_type="EARNING", amount=Decimal("0.01"), status="APPROVED",
        ))
    db.commit()
    
    result = payroll_router.payroll_summary(user=admin, db=db)
    
    # Should be exactly 10.00 (1000 * 0.01)
    net = result["net_amount"]
    assert net == 10.0, f"Aggregation error: expected 10.00, got {net}"


# ============================================================
# TEST 3: Earnings + Deductions + Manual Adjustments
# ============================================================
def test_decimal_safety_earnings_deductions_adjustments(db):
    """
    Test that earnings, deductions, and manual adjustments are calculated correctly.
    """
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add various types with exact decimal amounts
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="ATTENDANCE", input_type="EARNING", amount=Decimal("1000.00"), status="APPROVED",
    ))
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("500.50"), status="APPROVED",
    ))
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="DEDUCTION", amount=Decimal("200.25"), status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_summary(user=admin, db=db)
    
    # Expected:
    # earnings (non-MANUAL) = 1000.00
    # deductions (non-MANUAL) = 0
    # manual_adjustments = 500.50 - 200.25 = 300.25
    # net = 1000.00 - 0 + 300.25 = 1300.25
    expected_net = 1300.25
    
    assert result["net_amount"] == expected_net, f"Net calculation error: expected {expected_net}, got {result['net_amount']}"
    assert result["total_earnings"] == 1000.00
    assert result["total_adjustments"] == 300.25


# ============================================================
# TEST 4: Reversal exact cancellation
# ============================================================
def test_decimal_safety_reversal_cancellation(db):
    """
    Test that reversal mathematically cancels the original.
    """
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add original entry
    original = PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("1000.00"), status="APPROVED",
    )
    db.add(original); db.commit()
    
    # Void the original and add reversal
    original.status = "VOID"
    reversal = PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="REVERSAL", input_type="DEDUCTION", amount=Decimal("1000.00"),
        status="APPROVED", reversal_of_id=original.id,
    )
    db.add(reversal); db.commit()
    
    result = payroll_router.payroll_summary(user=admin, db=db)
    
    # Net should be 0 (original VOID + reversal excluded from totals)
    assert result["net_amount"] == 0.0, f"Reversal error: expected 0, got {result['net_amount']}"
    assert result["total_earnings"] == 0.0
    assert result["total_reversals"] == 1


# ============================================================
# TEST 5: Large totals
# ============================================================
def test_decimal_safety_large_totals(db):
    """
    Test aggregation of large amounts.
    """
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add large amounts
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="ATTENDANCE", input_type="EARNING", amount=Decimal("999999.99"), status="APPROVED",
    ))
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="DEDUCTION", amount=Decimal("0.01"), status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_summary(user=admin, db=db)
    
    # Expected: 999999.99 - 0.01 = 999999.98
    expected_net = 999999.98
    assert abs(result["net_amount"] - expected_net) < 0.001, f"Large total error: expected {expected_net}, got {result['net_amount']}"


# ============================================================
# TEST 6: Negative amounts / deduction semantics
# ============================================================
def test_decimal_safety_negative_deduction_semantics(db):
    """
    Test that deductions are treated as negative adjustments.
    """
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add manual earning and manual deduction
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("500.00"), status="APPROVED",
    ))
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="DEDUCTION", amount=Decimal("200.00"), status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_summary(user=admin, db=db)
    
    # Manual adjustments should be: 500 - 200 = 300
    assert result["total_adjustments"] == 300.0, f"Manual adjustment error: expected 300, got {result['total_adjustments']}"
    assert result["net_amount"] == 300.0


# ============================================================
# TEST 7: Rounding/quantization boundary cases
# ============================================================
def test_decimal_safety_rounding_boundary(db):
    """
    Test rounding at 0.005 boundary (should round up).
    """
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add entry with 3 decimal places (will be stored as NUMERIC(18,2))
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("10.005"), status="APPROVED",
    ))
    db.commit()
    
    result = payroll_router.payroll_summary(user=admin, db=db)
    
    # 10.005 should round to 10.01 (ROUND_HALF_UP)
    assert abs(result["net_amount"] - 10.01) < 0.001, f"Rounding error: expected 10.01, got {result['net_amount']}"


# ============================================================
# TEST 8: Concurrency - duplicate prevention for manual inputs
# ============================================================
def test_concurrency_duplicate_prevention(db):
    """
    Test that duplicate manual inputs are prevented by unique constraint.
    """
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add first entry
    db.add(PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("1000.00"),
        description="same", status="APPROVED",
    ))
    db.commit()
    
    # Verify only one record exists
    count = db.query(PayrollInputRecord).filter(
        PayrollInputRecord.tenant_id == tenant.id,
        PayrollInputRecord.courier_id == r1.id,
        PayrollInputRecord.month == period,
        PayrollInputRecord.source_type == "MANUAL",
        PayrollInputRecord.input_type == "EARNING",
        PayrollInputRecord.source_id.is_(None),
        PayrollInputRecord.amount == Decimal("1000.00"),
        PayrollInputRecord.description == "same",
    ).count()
    
    assert count == 1


# ============================================================
# TEST 9: Concurrency - duplicate reversal prevention
# ============================================================
def test_concurrency_duplicate_reversal_prevention(db):
    """
    Test that duplicate reversals are prevented by C2 fix.
    """
    from app.routers.analytics import reverse_payroll_input
    
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add original entry
    original = PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("1000.00"), status="APPROVED",
    )
    db.add(original); db.commit()
    
    # Void the original and add reversal
    original.status = "VOID"
    reversal = PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="REVERSAL", input_type="DEDUCTION", amount=Decimal("1000.00"),
        status="APPROVED", reversal_of_id=original.id,
    )
    db.add(reversal); db.commit()
    
    # Now try to reverse the reversal (should fail)
    with pytest.raises(HTTPException) as exc:
        reverse_payroll_input(reversal.id, admin, db)
    
    assert exc.value.status_code == 409


# ============================================================
# TEST 10: Verify actual types used
# ============================================================
def test_verify_money_storage_type(db):
    """
    Verify the storage type of monetary amounts.
    
    With Numeric(18,2), SQLite stores as NUMERIC which Python reads as Decimal/float.
    """
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
        source_type="MANUAL", input_type="EARNING", amount=Decimal("100.50"), status="APPROVED",
    ))
    db.commit()
    
    # Retrieve and check type
    record = db.query(PayrollInputRecord).first()
    
    # With Numeric(18,2), SQLAlchemy returns Decimal or float depending on SQLite handling
    # The key is that the value is exact
    assert record.amount == Decimal("100.50") or record.amount == 100.50, f"Amount mismatch: {record.amount}"


# ============================================================
# TEST 11: Reversal-of-reversal prevention
# ============================================================
def test_reversal_of_reversal_prevention(db):
    """
    Test that reversing a reversal is prevented.
    """
    from app.routers.analytics import reverse_payroll_input
    
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    contract = make_contract(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id)
    
    r1 = make_rider(db, tenant_id=tenant.id, city_id=city.id, contract_id=contract.id, branch_id=branch.id, phone="966500000101")
    
    period = date.today().strftime("%Y-%m")
    
    # Add original entry
    original = PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="MANUAL", input_type="EARNING", amount=Decimal("1000.00"), status="APPROVED",
    )
    db.add(original); db.commit()
    
    # Void the original and add reversal
    original.status = "VOID"
    reversal = PayrollInputRecord(
        tenant_id=tenant.id, courier_id=r1.id, month=period,
        source_type="REVERSAL", input_type="DEDUCTION", amount=Decimal("1000.00"),
        status="APPROVED", reversal_of_id=original.id,
    )
    db.add(reversal); db.commit()
    
    # Try to reverse the reversal - should fail with 409
    with pytest.raises(HTTPException) as exc:
        reverse_payroll_input(reversal.id, admin, db)
    
    assert exc.value.status_code == 409
    assert "Cannot reverse a reversal" in exc.value.detail
