"""W10.5 backend tests — Operator domain and commercial settlement."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    CommercialSettlement, Courier, CourierType, Country, ExternalOperatorIdentity,
    DailyLog, GeoCity, GeoCountry, NormalizedDeliveryFact, OperatorAgreement, RiderAssignment,
    SourcePlatform, Tenant, User, UserRole,
)
from app.routers import operators as operators_router


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


def make_platform_tenant(db, name="Platform"):
    t = Tenant(name=name, country=Country.SA, customer_type="DELIVERY_PLATFORM")
    db.add(t); db.commit(); db.refresh(t)
    return t


def make_operator_tenant(db, name="Operator"):
    t = Tenant(name=name, country=Country.SA, customer_type="LOGISTICS_OPERATOR")
    db.add(t); db.commit(); db.refresh(t)
    return t


def link_platform_operator(db, platform_tenant, operator_tenant):
    """Link a platform to an operator via PlatformOperator."""
    from app.models.entities import PlatformOperator
    sp = db.query(SourcePlatform).filter(SourcePlatform.tenant_id == platform_tenant.id).first()
    if not sp:
        sp = SourcePlatform(name_ar="Default", name_en="Default", code="DEFAULT", tenant_id=platform_tenant.id)
        db.add(sp); db.commit()
    
    po = PlatformOperator(
        tenant_id=platform_tenant.id,
        source_platform_id=sp.id,
        operator_tenant_id=operator_tenant.id,
        relationship_type="OPERATOR",
    )
    db.add(po); db.commit()
    return po


def make_admin(db, tenant_id):
    u = User(phone="966500000001", password_hash="x", role=UserRole.COMPANY_ADMIN, tenant_id=tenant_id)
    db.add(u); db.commit(); db.refresh(u)
    return u


def make_rider(db, tenant_id, name="Rider", phone="966500000100"):
    r = Courier(
        tenant_id=tenant_id, name=name, phone=phone, courier_type=CourierType.COMPANY,
        country=Country.SA, employment_status="ACTIVE",
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


def make_source_platform(db, name="Ninja", tenant_id=None):
    sp = SourcePlatform(name_ar=name, name_en=name, code=name.upper(), tenant_id=tenant_id or 1)
    db.add(sp); db.commit(); db.refresh(sp)
    return sp


# ============================================================
# EXTERNAL IDENTITY TESTS
# ============================================================

def test_external_operator_identity_unique_per_platform(db):
    """Test that same external operator ID can exist on different platforms."""
    platform1 = make_platform_tenant(db, "Platform1")
    platform2 = make_platform_tenant(db, "Platform2")
    operator = make_operator_tenant(db, "OperatorA")
    
    sp1 = make_source_platform(db, "Ninja")
    sp2 = make_source_platform(db, "Jahez")
    
    # Same external_operator_id on different platforms
    db.add(ExternalOperatorIdentity(
        tenant_id=platform1.id, source_platform_id=sp1.id,
        external_operator_id="VENDOR_781", operator_id=operator.id,
    ))
    db.add(ExternalOperatorIdentity(
        tenant_id=platform2.id, source_platform_id=sp2.id,
        external_operator_id="VENDOR_781", operator_id=operator.id,
    ))
    db.commit()
    
    # Verify both exist
    count = db.query(ExternalOperatorIdentity).filter(
        ExternalOperatorIdentity.external_operator_id == "VENDOR_781"
    ).count()
    assert count == 2


# ============================================================
# RIDER ASSIGNMENT TESTS
# ============================================================

def test_rider_assignment_history(db):
    """Test that rider assignment history is preserved."""
    platform = make_platform_tenant(db)
    admin = make_admin(db, tenant_id=platform.id)
    operator_a = make_operator_tenant(db, "OperatorA")
    operator_b = make_operator_tenant(db, "OperatorB")
    rider = make_rider(db, tenant_id=platform.id)
    
    # Assign to Operator A from Jan-Mar
    assignment1 = RiderAssignment(
        tenant_id=platform.id, courier_id=rider.id, operator_id=operator_a.id,
        effective_from=date(2026, 1, 1), effective_to=date(2026, 3, 31),
        status="ENDED",
    )
    db.add(assignment1)
    
    # Assign to Operator B from Apr onwards
    assignment2 = RiderAssignment(
        tenant_id=platform.id, courier_id=rider.id, operator_id=operator_b.id,
        effective_from=date(2026, 4, 1), status="ACTIVE",
    )
    db.add(assignment2)
    db.commit()
    
    # Get history
    history = operators_router.get_rider_assignment_history(rider.id, admin, db)
    
    assert len(history["assignments"]) == 2
    assert history["assignments"][0]["operator_id"] == operator_b.id  # Most recent first
    assert history["assignments"][1]["operator_id"] == operator_a.id


def test_overlapping_assignment_rejected(db):
    """Test that overlapping assignments are rejected."""
    platform = make_platform_tenant(db)
    admin = make_admin(db, tenant_id=platform.id)
    operator = make_operator_tenant(db, "OperatorA")
    rider = make_rider(db, tenant_id=platform.id)
    
    # Link operator to platform
    link_platform_operator(db, platform, operator)
    
    # Create initial assignment
    assignment = RiderAssignment(
        tenant_id=platform.id, courier_id=rider.id, operator_id=operator.id,
        effective_from=date(2026, 1, 1), status="ACTIVE",
    )
    db.add(assignment)
    db.commit()
    
    # Try overlapping assignment
    with pytest.raises(HTTPException) as exc:
        operators_router.assign_rider_to_operator(
            rider.id, operator.id, date(2026, 1, 15), user=admin, db=db
        )
    
    assert exc.value.status_code == 409


# ============================================================
# COMMERCIAL SETTLEMENT TESTS
# ============================================================

def test_commercial_settlement_decimal_precision(db):
    """Test that settlement uses Decimal arithmetic."""
    platform = make_platform_tenant(db)
    admin = make_admin(db, tenant_id=platform.id)
    operator = make_operator_tenant(db, "OperatorA")
    
    # Link operator to platform
    link_platform_operator(db, platform, operator)
    
    # Create agreement
    agreement = OperatorAgreement(
        tenant_id=platform.id, operator_id=operator.id,
        name="Test Agreement", compensation_model="PER_COMPLETED_ORDER",
        rate=Decimal("8.00"), currency="SAR",
        effective_from=date.today(), status="ACTIVE",
    )
    db.add(agreement)
    db.commit()
    
    # Calculate settlement
    calc = operators_router.calculate_operator_settlement(
        operator.id, "2026-08", admin, db
    )
    
    # Verify Decimal precision
    assert calc["base_amount"] == 0.0  # No orders
    assert calc["net_amount"] == 0.0


def test_commercial_settlement_with_orders(db):
    """Settlement bills for the orders the platform recorded under the operator.

    This used to seed NormalizedDeliveryFact rows inside the *operator's* tenant
    and assert they were billed. That encoded a cross-tenant read with no grant
    behind it, against a table nothing populates in practice, so real
    settlements computed zero while the vendor scorecard beside them showed real
    orders. Billing now reads the platform's own daily logs, grouped by
    operator, which is the same source and grouping the scorecard uses.
    """
    platform = make_platform_tenant(db)
    admin = make_admin(db, tenant_id=platform.id)
    operator = make_operator_tenant(db, "OperatorA")
    rider = make_rider(db, tenant_id=platform.id)
    make_source_platform(db)

    link_platform_operator(db, platform, operator)

    agreement = OperatorAgreement(
        tenant_id=platform.id, operator_id=operator.id,
        name="Test Agreement", compensation_model="PER_COMPLETED_ORDER",
        rate=Decimal("8.00"), currency="SAR",
        effective_from=date.today(), status="ACTIVE",
    )
    db.add(agreement)

    # The rider works for this operator, and the platform recorded 100 orders.
    db.add(
        RiderAssignment(
            tenant_id=platform.id, courier_id=rider.id, operator_id=operator.id,
            effective_from=date.today(), status="ACTIVE",
        )
    )
    db.add(
        DailyLog(
            tenant_id=platform.id, courier_id=rider.id,
            log_date=date.today(), orders_count=100,
        )
    )
    db.commit()

    current_month = date.today().strftime("%Y-%m")
    calc = operators_router.calculate_operator_settlement(
        operator.id, current_month, admin, db
    )

    assert calc["eligible_orders"] == 100
    assert calc["base_amount"] == 800.0  # 100 * 8.00


def test_settlement_lifecycle(db):
    """Test settlement lifecycle: DRAFT → APPROVED."""
    platform = make_platform_tenant(db)
    admin = make_admin(db, tenant_id=platform.id)
    operator = make_operator_tenant(db, "OperatorA")
    
    # Link operator to platform
    link_platform_operator(db, platform, operator)
    
    # Create agreement
    agreement = OperatorAgreement(
        tenant_id=platform.id, operator_id=operator.id,
        name="Test Agreement", compensation_model="PER_COMPLETED_ORDER",
        rate=Decimal("8.00"), currency="SAR",
        effective_from=date.today(), status="ACTIVE",
    )
    db.add(agreement)
    db.commit()
    
    # Save settlement
    result = operators_router.save_operator_settlement(
        operator.id, "2026-08", user=admin, db=db
    )
    
    assert result["status"] == "DRAFT"
    
    # Approve settlement
    approved = operators_router.approve_operator_settlement(
        result["id"], admin, db
    )
    
    assert approved["status"] == "APPROVED"


def test_approved_settlement_cannot_mutate(db):
    """Test that approved settlement cannot be silently mutated."""
    platform = make_platform_tenant(db)
    admin = make_admin(db, tenant_id=platform.id)
    operator = make_operator_tenant(db, "OperatorA")
    
    settlement = CommercialSettlement(
        tenant_id=platform.id, operator_id=operator.id,
        period_month="2026-08", base_amount=Decimal("1000.00"),
        net_amount=Decimal("1000.00"), status="APPROVED",
        approved_by=admin.id, approved_at=datetime.utcnow(),
    )
    db.add(settlement)
    db.commit()
    
    # Try to approve again
    with pytest.raises(HTTPException) as exc:
        operators_router.approve_operator_settlement(settlement.id, admin, db)
    
    assert exc.value.status_code == 400


# ============================================================
# RBAC TESTS
# ============================================================

def test_operator_a_cannot_access_operator_b(db):
    """Test that Operator A admin cannot access Operator B."""
    platform = make_platform_tenant(db)
    operator_a = make_operator_tenant(db, "OperatorA")
    operator_b = make_operator_tenant(db, "OperatorB")
    
    # Create admin for Operator A
    admin_a = User(phone="966500000011", password_hash="x", role=UserRole.COMPANY_ADMIN, tenant_id=operator_a.id)
    db.add(admin_a); db.commit()
    
    # Operator A admin should not be able to access Operator B settlements
    with pytest.raises(HTTPException) as exc:
        operators_router.calculate_operator_settlement(
            operator_b.id, "2026-08", admin_a, db
        )
    
    assert exc.value.status_code == 404


def test_unauthorized_role_rejected(db):
    """Test that unauthorized roles are rejected."""
    platform = make_platform_tenant(db)
    u = User(phone="966500000012", password_hash="x", role=UserRole.VIEWER, tenant_id=platform.id)
    db.add(u); db.commit()
    
    with pytest.raises(HTTPException) as exc:
        operators_router.calculate_operator_settlement(1, "2026-08", u, db)
    
    assert exc.value.status_code == 403
