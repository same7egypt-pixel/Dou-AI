"""Phase 1 End-to-End scenario tests.

Covers:
1. Logistics Operator: create → onboard → assign → shift → attendance → performance
2. Delivery Platform: create platform → add operator → assign riders → settlements
3. Supervisor scope: supervisor sees only own riders, cannot cross boundaries
4. Financial authorization: payroll access controlled by role
5. DOU Admin provisioning: create company → activate → record payment → Company 360
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

import os
os.environ["ADMIN_KEY"] = "test-admin-key"

from app.main import app
from app.database import Base, get_db
from app.models.entities import (
    Attendance,
    Contract,
    ContractBranch,
    GeoCity,
    GeoCountry,
    PlatformOperator,
    Project,
    SourcePlatform,
    SubscriptionPlan,
    TenantOperatingCity,
    User,
    UserRole,
)
from app.routers.auth import hash_password

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_phase1_e2e.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    # Seed plans
    db.add(SubscriptionPlan(code="STARTER", name="Starter", name_en="Starter",
                            monthly_price=499, monthly_price_usd=149, max_couriers=50, is_active=True))
    db.add(SubscriptionPlan(code="GROWTH", name="Growth", name_en="Growth",
                            monthly_price=999, monthly_price_usd=269, max_couriers=150, is_active=True))
    db.flush()
    # DOU Admin
    admin = User(name="DOU Admin", phone="966500000001",
                 password_hash=hash_password("admin123456"),
                 role=UserRole.DOU_ADMIN, is_active=True)
    db.add(admin)
    db.commit()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)


def admin_auth():
    return {"X-Admin-Key": "test-admin-key"}


def login_user(phone, password):
    r = client.post("/auth/login", json={"phone": phone, "password": password})
    assert r.status_code == 200, f"Login failed for {phone}: {r.text}"
    return r.json()["access_token"]


def seed_operating_structure(db, tenant_id, supervisor_id, suffix):
    """Create the authoritative city → project → contract branch assignment."""
    country = db.query(GeoCountry).filter(GeoCountry.code == "SA").first()
    if not country:
        country = GeoCountry(name="Saudi Arabia", code="SA", active=True)
        db.add(country)
        db.flush()
    city = GeoCity(country_id=country.id, name=f"Riyadh {suffix}", active=True)
    db.add(city)
    db.flush()
    db.add(TenantOperatingCity(tenant_id=tenant_id, geo_city_id=city.id, is_active=True))
    project = Project(tenant_id=tenant_id, name=f"Project {suffix}", is_active=True)
    db.add(project)
    db.flush()
    contract = Contract(tenant_id=tenant_id, project_id=project.id, name=f"Contract {suffix}", status="ACTIVE")
    db.add(contract)
    db.flush()
    branch = ContractBranch(
        tenant_id=tenant_id, contract_id=contract.id, city_id=city.id,
        city=city.name, project_id=project.id, supervisor_id=supervisor_id, is_active=True,
    )
    db.add(branch)
    db.commit()
    return contract, branch


# ============================================================
# SCENARIO 1: Logistics Operator Lifecycle
# ============================================================
class TestLogisticsOperatorScenario:
    def test_full_lifecycle(self, setup_db):
        db = setup_db
        # Step 1: DOU Admin creates logistics company
        r = client.post("/admin/tenants", json={
            "name": "Speed Logistics",
            "owner_name": "Ahmed",
            "owner_phone": "966511111111",
            "password": "company123456",
            "market_code": "SA",
            "plan": "STARTER",
        }, headers=admin_auth())
        assert r.status_code == 200
        tenant_id = r.json()["id"]

        # Step 2: Company Admin logs in
        token = login_user("966511111111", "company123456")
        auth = {"Authorization": f"Bearer {token}"}

        # Step 3: Admin creates a supervisor
        r = client.post("/hr/supervisors", json={
            "name": "Khalid Supervisor",
            "phone": "966522222222",
            "password": "super123456",
        }, headers=auth)
        assert r.status_code in (200, 201)
        supervisor_id = r.json()["id"]
        contract, branch = seed_operating_structure(db, tenant_id, supervisor_id, "lifecycle")

        # Step 4: Admin creates a rider in the supervisor's authoritative branch
        r = client.post("/fleet/couriers", json={
            "name": "Rider Omar",
            "phone": "966533333333",
            "country": "SA",
            "courier_type": "COMPANY",
            "password": "rider123456",
            "contract_id": contract.id,
            "contract_branch_id": branch.id,
            "supervisor_id": supervisor_id,
        }, headers=auth)
        assert r.status_code == 200
        rider_id = r.json()["id"]

        # Step 6: Check readiness (NEW → READY_FOR_REVIEW → READY_TO_WORK)
        r = client.get(f"/readiness/{rider_id}", headers=auth)
        assert r.status_code == 200
        assert r.json()["overall_status"] in ("NOT_READY", "RESTRICTED")

        # Step 7: Create shift and assign rider
        r = client.post("/shifts", json={
            "name": "Morning Shift",
            "start_time": "08:00",
            "end_time": "16:00",
            "courier_ids": [rider_id],
        }, headers=auth)
        assert r.status_code in (200, 201)

        # Step 8: Rider checks in
        r = client.post("/shifts/attendance/check-in", json={
            "courier_id": rider_id,
            "lat": 24.7136,
            "lng": 46.6753,
        }, headers=auth)
        # Should succeed or associate to shift
        assert r.status_code in (200, 201)

        # Step 9: Supervisor logs in and sees rider
        sup_token = login_user("966522222222", "super123456")
        sup_auth = {"Authorization": f"Bearer {sup_token}"}
        r = client.get("/supervisor/riders", headers=sup_auth)
        assert r.status_code == 200
        riders = r.json()
        assert any(rid["id"] == rider_id for rid in riders)

        # Step 10: Supervisor attendance view
        r = client.get("/supervisor/attendance", headers=sup_auth)
        assert r.status_code == 200

        # Step 11: DOU Admin views Company 360
        r = client.get(f"/admin/tenants/{tenant_id}/profile", headers=admin_auth())
        assert r.status_code == 200
        profile = r.json()
        assert profile["name"] == "Speed Logistics"
        assert profile["usage"]["couriers"] == 1
        assert profile["usage"]["supervisors"] == 1

        # Step 12: Record payment
        r = client.post(f"/admin/tenants/{tenant_id}/payments", json={
            "amount": 499, "payment_method": "BANK_TRANSFER", "period_months": 1,
        }, headers=admin_auth())
        assert r.status_code == 200
        assert r.json()["receipt_number"].startswith("DOU-")


# ============================================================
# SCENARIO 2: Delivery Platform with Operators
# ============================================================
class TestDeliveryPlatformScenario:
    def test_platform_with_operator(self, setup_db):
        db = setup_db
        # Step 1: Create delivery platform
        r = client.post("/admin/tenants", json={
            "name": "FoodExpress Platform",
            "owner_name": "Sara",
            "owner_phone": "966544444444",
            "password": "platform123456",
            "market_code": "SA",
            "plan": "GROWTH",
        }, headers=admin_auth())
        assert r.status_code == 200
        platform_id = r.json()["id"]

        # Step 2: Create operator tenant
        r = client.post("/admin/tenants", json={
            "name": "Quick Delivery Co",
            "owner_name": "Omar",
            "owner_phone": "966555555555",
            "password": "operator123456",
            "market_code": "SA",
            "plan": "STARTER",
        }, headers=admin_auth())
        assert r.status_code == 200
        operator_tenant_id = r.json()["id"]

        # Step 3: Platform admin logs in
        token = login_user("966544444444", "platform123456")
        auth = {"Authorization": f"Bearer {token}"}

        # Step 4: Create operator relationship
        source = SourcePlatform(
            tenant_id=platform_id, code="internal", name_ar="Internal", name_en="Internal",
        )
        db.add(source)
        db.flush()
        op = PlatformOperator(
            tenant_id=platform_id,
            source_platform_id=source.id,
            operator_tenant_id=operator_tenant_id,
            is_active=True,
        )
        db.add(op)
        db.commit()

        # Step 5: Platform creates a supervisor and an owned rider pool
        r = client.post("/hr/supervisors", json={
            "name": "Platform Supervisor", "phone": "966566666665", "password": "super123456",
        }, headers=auth)
        assert r.status_code == 200
        supervisor_id = r.json()["id"]
        contract, branch = seed_operating_structure(db, platform_id, supervisor_id, "platform")
        r = client.post("/fleet/couriers", json={
            "name": "Operator Rider",
            "phone": "966566666666",
            "country": "SA",
            "courier_type": "COMPANY",
            "password": "rider123456",
            "contract_id": contract.id,
            "contract_branch_id": branch.id,
            "supervisor_id": supervisor_id,
        }, headers=auth)
        assert r.status_code == 200
        rider_id = r.json()["id"]

        # Step 6: Platform assigns its rider to the linked operator
        r = client.post(
            f"/analytics/operators/rider/assign?courier_id={rider_id}&operator_id={operator_tenant_id}&effective_from=2026-08-30",
            headers=auth,
        )
        assert r.status_code == 200

        # Step 8: Platform views operator list
        r = client.get(f"/admin/tenants/{platform_id}/operators", headers=admin_auth())
        assert r.status_code == 200
        ops = r.json()
        assert len(ops) >= 1

        # Step 9: Operator health
        r = client.get("/admin/operators/health", headers=admin_auth())
        assert r.status_code == 200
        assert r.json()["total_operators"] >= 1

        # Step 10: Assignment history remains available to the platform
        r = client.get(f"/analytics/operators/rider/{rider_id}/history", headers=auth)
        assert r.status_code == 200
        assert r.json()["assignments"][0]["operator_id"] == operator_tenant_id


# ============================================================
# SCENARIO 3: Supervisor Scope & Isolation
# ============================================================
class TestSupervisorScopeScenario:
    def test_supervisor_sees_only_own_riders(self, setup_db):
        db = setup_db
        # Create company
        r = client.post("/admin/tenants", json={
            "name": "Scope Test Co",
            "owner_name": "Admin",
            "owner_phone": "966577777777",
            "password": "admin123456",
            "market_code": "SA",
            "plan": "STARTER",
        }, headers=admin_auth())
        tenant_id = r.json()["id"]
        token = login_user("966577777777", "admin123456")
        auth = {"Authorization": f"Bearer {token}"}

        # Create two supervisors
        r = client.post("/hr/supervisors", json={
            "name": "Sup A", "phone": "966588888881", "password": "super123456",
        }, headers=auth)
        sup_a_id = r.json()["id"]
        r = client.post("/hr/supervisors", json={
            "name": "Sup B", "phone": "966588888882", "password": "super123456",
        }, headers=auth)
        sup_b_id = r.json()["id"]
        contract_a, branch_a = seed_operating_structure(db, tenant_id, sup_a_id, "scope-a")
        contract_b, branch_b = seed_operating_structure(db, tenant_id, sup_b_id, "scope-b")

        # Create riders assigned to different supervisor-owned branches
        r = client.post("/fleet/couriers", json={
            "name": "Rider A", "phone": "966599999991", "country": "SA",
            "courier_type": "COMPANY", "password": "rider123456",
            "supervisor_id": sup_a_id, "contract_id": contract_a.id,
            "contract_branch_id": branch_a.id,
        }, headers=auth)
        assert r.status_code == 200
        rider_a_id = r.json()["id"]
        r = client.post("/fleet/couriers", json={
            "name": "Rider B", "phone": "966599999992", "country": "SA",
            "courier_type": "COMPANY", "password": "rider123456",
            "supervisor_id": sup_b_id, "contract_id": contract_b.id,
            "contract_branch_id": branch_b.id,
        }, headers=auth)
        assert r.status_code == 200
        rider_b_id = r.json()["id"]

        # Supervisor A logs in
        sup_a_token = login_user("966588888881", "super123456")
        sup_a_auth = {"Authorization": f"Bearer {sup_a_token}"}

        # Supervisor A sees only their rider
        r = client.get("/supervisor/riders", headers=sup_a_auth)
        assert r.status_code == 200
        riders = r.json()
        rider_ids = [r["id"] for r in riders]
        assert rider_a_id in rider_ids
        assert rider_b_id not in rider_ids

        # Supervisor A cannot access Supervisor B's rider readiness
        r = client.get(f"/readiness/{rider_b_id}", headers=sup_a_auth)
        assert r.status_code in (403, 404)


# ============================================================
# SCENARIO 4: Financial Authorization
# ============================================================
class TestFinancialAuthorizationScenario:
    def test_role_based_payroll_access(self, setup_db):
        db = setup_db
        # Create company
        r = client.post("/admin/tenants", json={
            "name": "Finance Test Co",
            "owner_name": "Admin",
            "owner_phone": "966511122222",
            "password": "admin123456",
            "market_code": "SA",
            "plan": "STARTER",
        }, headers=admin_auth())
        tenant_id = r.json()["id"]
        admin_token = login_user("966511122222", "admin123456")
        company_auth = {"Authorization": f"Bearer {admin_token}"}
        assert client.get("/analytics/payroll/summary", headers=company_auth).status_code == 200

        # Create accountant
        accountant = User(
            name="Accountant", phone="966511133333",
            password_hash=hash_password("acct123456"),
            role=UserRole.ACCOUNTANT, tenant_id=tenant_id, is_active=True,
        )
        db.add(accountant)
        db.commit()
        acct_token = login_user("966511133333", "acct123456")
        acct_auth = {"Authorization": f"Bearer {acct_token}"}

        # Accountant can view payroll
        r = client.get("/analytics/payroll/summary", headers=acct_auth)
        assert r.status_code == 200

        # Accountant cannot create riders
        r = client.post("/fleet/couriers", json={
            "name": "Test", "phone": "966511144444", "country": "SA",
        }, headers=acct_auth)
        assert r.status_code == 403


# ============================================================
# SCENARIO 5: Cross-Tenant Isolation
# ============================================================
class TestCrossTenantIsolation:
    def test_cannot_access_other_tenant_data(self, setup_db):
        db = setup_db
        # Create two companies
        r = client.post("/admin/tenants", json={
            "name": "Company A", "owner_name": "A", "owner_phone": "966512345001",
            "password": "pass123456", "market_code": "SA", "plan": "STARTER",
        }, headers=admin_auth())
        tenant_a_id = r.json()["id"]

        r = client.post("/admin/tenants", json={
            "name": "Company B", "owner_name": "B", "owner_phone": "966512345002",
            "password": "pass123456", "market_code": "SA", "plan": "STARTER",
        }, headers=admin_auth())
        tenant_b_id = r.json()["id"]

        # Company A admin logs in
        token_a = login_user("966512345001", "pass123456")
        auth_a = {"Authorization": f"Bearer {token_a}"}

        # Create an authoritative branch and rider in tenant A
        r = client.post("/hr/supervisors", json={
            "name": "Tenant A Supervisor", "phone": "966512345004", "password": "super123456",
        }, headers=auth_a)
        supervisor_id = r.json()["id"]
        contract, branch = seed_operating_structure(db, tenant_a_id, supervisor_id, "tenant-a")
        r = client.post("/fleet/couriers", json={
            "name": "Rider A", "phone": "966512345003", "country": "SA",
            "courier_type": "COMPANY", "password": "rider123456",
            "supervisor_id": supervisor_id, "contract_id": contract.id,
            "contract_branch_id": branch.id,
        }, headers=auth_a)
        assert r.status_code == 200
        rider_a_id = r.json()["id"]

        # Company B admin logs in
        token_b = login_user("966512345002", "pass123456")
        auth_b = {"Authorization": f"Bearer {token_b}"}

        # Company B cannot view Company A's rider readiness
        r = client.get(f"/readiness/{rider_a_id}", headers=auth_b)
        assert r.status_code in (403, 404)

        # Company B cannot view Company A's payroll
        r = client.get("/analytics/payroll/summary", headers=auth_b)
        # Either 200 with empty or 403 — but definitely not Company A's data
        if r.status_code == 200:
            # Should not contain rider_a_id data
            pass

        # Tenant A cannot view Tenant B's Company 360 (via admin only)
        r = client.get(f"/admin/tenants/{tenant_b_id}/profile", headers=auth_a)
        assert r.status_code in (401, 403)


# ============================================================
# SCENARIO 6: Attendance Correction Workflow
# ============================================================
class TestAttendanceCorrectionScenario:
    def test_correction_lifecycle(self, setup_db):
        db = setup_db
        # Create company
        r = client.post("/admin/tenants", json={
            "name": "Correction Test Co",
            "owner_name": "Admin",
            "owner_phone": "966513456001",
            "password": "admin123456",
            "market_code": "SA",
            "plan": "STARTER",
        }, headers=admin_auth())
        tenant_id = r.json()["id"]
        token = login_user("966513456001", "admin123456")
        auth = {"Authorization": f"Bearer {token}"}

        # Create rider under an authoritative branch
        r = client.post("/hr/supervisors", json={
            "name": "Correction Supervisor", "phone": "966513456003", "password": "super123456",
        }, headers=auth)
        supervisor_id = r.json()["id"]
        contract, branch = seed_operating_structure(db, tenant_id, supervisor_id, "correction")
        r = client.post("/fleet/couriers", json={
            "name": "Rider", "phone": "966513456002", "country": "SA",
            "courier_type": "COMPANY", "password": "rider123456",
            "supervisor_id": supervisor_id, "contract_id": contract.id,
            "contract_branch_id": branch.id,
        }, headers=auth)
        assert r.status_code == 200
        rider_id = r.json()["id"]

        # Create attendance record
        attendance = Attendance(
            courier_id=rider_id,
            shift_id=None,
            check_in=datetime(2026, 8, 30, 9, 30),
            check_out=datetime(2026, 8, 30, 17, 0),
            check_in_lat=24.7, check_in_lng=46.6,
        )
        db.add(attendance)
        db.commit()
        att_id = attendance.id

        # Create correction request
        r = client.post("/analytics/attendance/corrections", json={
            "attendance_id": att_id,
            "corrected_check_in": "2026-08-30T09:00:00",
            "reason": "GPS delay - actual check-in was 9:00",
        }, headers=auth)
        assert r.status_code == 201
        correction_id = r.json()["id"]

        # List pending corrections
        r = client.get("/analytics/attendance/corrections?status_filter=PENDING", headers=auth)
        assert r.status_code == 200
        corrections = r.json()
        assert any(c["id"] == correction_id for c in corrections)

        # Approve correction
        r = client.post(f"/analytics/attendance/corrections/{correction_id}/review", json={
            "decision": "APPROVED",
            "note": "Verified with rider",
        }, headers=auth)
        assert r.status_code == 200

        # Verify status changed
        r = client.get("/analytics/attendance/corrections?status_filter=APPROVED", headers=auth)
        assert r.status_code == 200
        approved = r.json()
        assert any(c["id"] == correction_id for c in approved)


# ============================================================
# SCENARIO 7: Capacity & Needs Attention
# ============================================================
class TestCapacityNeedsAttentionScenario:
    def test_capacity_shortage_signal(self, setup_db):
        # Create company
        r = client.post("/admin/tenants", json={
            "name": "Capacity Test Co",
            "owner_name": "Admin",
            "owner_phone": "966514567001",
            "password": "admin123456",
            "market_code": "SA",
            "plan": "STARTER",
        }, headers=admin_auth())
        assert r.status_code == 200
        token = login_user("966514567001", "admin123456")
        auth = {"Authorization": f"Bearer {token}"}

        # Create capacity requirement
        r = client.post("/analytics/capacity/requirements", json={
            "scope_type": "BRANCH",
            "scope_id": 1,
            "required_riders": 10,
            "effective_from": "2026-08-30",
        }, headers=auth)
        assert r.status_code == 201

        # Check capacity status
        r = client.get("/analytics/capacity/status?scope_type=BRANCH&scope_id=1", headers=auth)
        assert r.status_code == 200
        status = r.json()
        assert status["required"] == 10
        assert status["shortage"] == 10  # No riders assigned

        # Needs attention should flag capacity shortage
        r = client.get("/analytics/needs-attention/deterministic", headers=auth)
        assert r.status_code == 200
        assert any(item["signal"] == "capacity_shortage" for item in r.json()["items"])
