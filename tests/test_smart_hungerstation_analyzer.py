import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import entities as ent
from app.services.rider_management import create_rider_record
from app.services.performance_imports import preview_performance_import
from app.services.operating_structure import find_or_create_city, ensure_tenant_operating_city


@pytest.fixture
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    tenant = ent.Tenant(name="Logistics Pro", country=ent.Country.SA, plan="PRO")
    db.add(tenant)
    db.commit()

    admin = ent.User(
        tenant_id=tenant.id,
        phone="966500000001",
        name="مدير العمليات",
        role=ent.UserRole.COMPANY_ADMIN,
        password_hash="hashed_pw",
        is_active=True,
    )
    sup_riyadh = ent.User(
        tenant_id=tenant.id,
        phone="966500000002",
        name="المشرف خالد",
        role=ent.UserRole.SUPERVISOR,
        password_hash="hashed_pw",
        is_active=True,
    )
    sup_jeddah = ent.User(
        tenant_id=tenant.id,
        phone="966500000003",
        name="المشرف سعيد",
        role=ent.UserRole.SUPERVISOR,
        password_hash="hashed_pw",
        is_active=True,
    )
    db.add_all([admin, sup_riyadh, sup_jeddah])
    db.commit()

    city_riyadh = find_or_create_city(db, tenant, "الرياض")
    city_jeddah = find_or_create_city(db, tenant, "جدة")
    ensure_tenant_operating_city(db, tenant, city_riyadh)
    ensure_tenant_operating_city(db, tenant, city_jeddah)
    db.commit()

    contract = ent.Contract(
        tenant_id=tenant.id,
        name="عقد هنقرستيشن الرئيسي",
        client_name="Hungerstation",
        status="ACTIVE",
        start_date=date(2026, 1, 1),
    )
    project = ent.Project(tenant_id=tenant.id, name="هنقرستيشن", is_active=True)
    db.add_all([contract, project])
    db.commit()

    branch_riyadh = ent.ContractBranch(
        tenant_id=tenant.id,
        contract_id=contract.id,
        project_id=project.id,
        city="الرياض",
        city_id=city_riyadh.id,
        branch_name="فرع الرياض",
        supervisor_id=sup_riyadh.id,
        is_active=True,
    )
    branch_jeddah = ent.ContractBranch(
        tenant_id=tenant.id,
        contract_id=contract.id,
        project_id=project.id,
        city="جدة",
        city_id=city_jeddah.id,
        branch_name="فرع جدة",
        supervisor_id=sup_jeddah.id,
        is_active=True,
    )
    db.add_all([branch_riyadh, branch_jeddah])
    db.commit()

    source = ent.SourcePlatform(
        tenant_id=tenant.id,
        code="HUNGERSTATION",
        name_ar="هنقرستيشن",
        is_active=True,
    )
    db.add(source)
    db.commit()

    return {
        "db": db,
        "tenant": tenant,
        "admin": admin,
        "sup_riyadh": sup_riyadh,
        "sup_jeddah": sup_jeddah,
        "contract": contract,
        "branch_riyadh": branch_riyadh,
        "branch_jeddah": branch_jeddah,
        "city_riyadh": city_riyadh,
        "city_jeddah": city_jeddah,
        "source": source,
    }


def test_create_rider_with_platform_courier_id(env):
    db = env["db"]
    payload = {
        "name": "أحمد محمود",
        "phone": "966551234567",
        "password": "Password123!",
        "platform_courier_id": "HS-9988",
        "contract_id": env["contract"].id,
        "contract_branch_id": env["branch_riyadh"].id,
        "supervisor_id": env["sup_riyadh"].id,
        "city_id": env["city_riyadh"].id,
    }
    courier, user = create_rider_record(db, env["admin"], payload)
    db.commit()

    assert courier.id is not None
    assert courier.name == "أحمد محمود"
    assert courier.platform_courier_id == "HS-9988"
    assert courier.work_city == "الرياض"
    assert courier.supervisor_id == env["sup_riyadh"].id


def test_smart_hungerstation_sheet_matching_with_names_and_breakdowns(env):
    db = env["db"]

    # Register Rider 1 in Riyadh with platform_courier_id = 94821
    create_rider_record(
        db,
        env["admin"],
        {
            "name": "محمد أحمد الشريف",
            "phone": "966550000001",
            "password": "Password123!",
            "platform_courier_id": "94821",
            "contract_id": env["contract"].id,
            "contract_branch_id": env["branch_riyadh"].id,
            "supervisor_id": env["sup_riyadh"].id,
            "city_id": env["city_riyadh"].id,
        },
    )

    # Register Rider 2 in Jeddah with platform_courier_id = 94822
    create_rider_record(
        db,
        env["admin"],
        {
            "name": "إبراهيم عبد الله",
            "phone": "966550000002",
            "password": "Password123!",
            "platform_courier_id": "94822",
            "contract_id": env["contract"].id,
            "contract_branch_id": env["branch_jeddah"].id,
            "supervisor_id": env["sup_jeddah"].id,
            "city_id": env["city_jeddah"].id,
        },
    )
    db.commit()

    # Raw HungerStation CSV containing ONLY Rider IDs and Orders (No rider names!)
    csv_content = (
        "Rider ID,Date,Completed Orders\n"
        "94821,2026-09-01,15\n"
        "94821,2026-09-02,20\n"
        "94822,2026-09-01,18\n"
    )

    preview = preview_performance_import(
        db, env["admin"], csv_text=csv_content, file_name="Hungerstation_Daily_Report.csv"
    )

    assert preview["detected_platform"] == "HUNGERSTATION"
    assert preview["valid_rows"] == 3
    assert preview["invalid_rows"] == 0

    analytics = preview["analytics"]
    assert analytics["total_orders"] == 53  # 15 + 20 + 18
    assert analytics["total_matched_riders"] == 2

    # Verify Matched Couriers List with real names and totals
    matched = analytics["matched_couriers"]
    assert len(matched) == 2

    # Rider 1: Mohammed Ahmed (Riyadh, 35 orders)
    r1 = next(c for c in matched if c["platform_courier_id"] == "94821")
    assert r1["courier_name"] == "محمد أحمد الشريف"
    assert r1["total_orders"] == 35
    assert r1["city_name"] == "الرياض"
    assert r1["supervisor_name"] == "المشرف خالد"

    # Rider 2: Ibrahim Abdullah (Jeddah, 18 orders)
    r2 = next(c for c in matched if c["platform_courier_id"] == "94822")
    assert r2["courier_name"] == "إبراهيم عبد الله"
    assert r2["total_orders"] == 18
    assert r2["city_name"] == "جدة"
    assert r2["supervisor_name"] == "المشرف سعيد"

    # Verify City Performance Breakdown
    by_city = {c["city"]: c["orders"] for c in analytics["by_city"]}
    assert by_city["الرياض"] == 35
    assert by_city["جدة"] == 18

    # Verify Supervisor Performance Breakdown
    by_sup = {s["supervisor"]: s["orders"] for s in analytics["by_supervisor"]}
    assert by_sup["المشرف خالد"] == 35
    assert by_sup["المشرف سعيد"] == 18


def test_matching_via_rider_identity_mapping_table(env):
    """Verify that riders mapped in the independent RiderIdentityMapping table
    are also seamlessly resolved with real names and breakdowns.
    """
    db = env["db"]

    # Create courier without platform_courier_id
    courier, _ = create_rider_record(
        db,
        env["admin"],
        {
            "name": "سعد القرني",
            "phone": "966550000003",
            "password": "Password123!",
            "contract_id": env["contract"].id,
            "contract_branch_id": env["branch_riyadh"].id,
            "supervisor_id": env["sup_riyadh"].id,
            "city_id": env["city_riyadh"].id,
        },
    )
    db.commit()

    # Map this courier specifically in RiderIdentityMapping for HUNGERSTATION
    mapping = ent.RiderIdentityMapping(
        tenant_id=env["tenant"].id,
        source_platform_id=env["source"].id,
        source_rider_id="HS-MAPPING-77",
        courier_id=courier.id,
        status="ACTIVE",
        effective_from=date(2026, 1, 1),
    )
    db.add(mapping)
    db.commit()

    csv_content = (
        "driver_id,order_date,delivered\n"
        "HS-MAPPING-77,2026-09-01,25\n"
    )

    preview = preview_performance_import(
        db, env["admin"], csv_text=csv_content, file_name="Hungerstation_Report.csv"
    )

    assert preview["valid_rows"] == 1
    assert preview["invalid_rows"] == 0

    matched = preview["analytics"]["matched_couriers"]
    assert len(matched) == 1
    assert matched[0]["courier_name"] == "سعد القرني"
    assert matched[0]["total_orders"] == 25
    assert matched[0]["city_name"] == "الرياض"
    assert matched[0]["supervisor_name"] == "المشرف خالد"
