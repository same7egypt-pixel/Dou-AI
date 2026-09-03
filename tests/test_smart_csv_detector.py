"""Tests for Smart Platform CSV Auto-Detector (Hungerstation, Ninja, Jahez, ToYou, DOU Generic)."""

from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import entities as ent
from app.services.performance_imports import (
    detect_platform_and_map_headers,
    preview_performance_import,
    confirm_performance_import,
)


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_header_detection_and_mapping():
    # 1. Hungerstation headers
    hs_headers = ["Rider Code", "Date", "Hub", "Delivered Orders", "Notes"]
    plat, mapping = detect_platform_and_map_headers(hs_headers)
    assert plat == "HUNGERSTATION"
    assert mapping["rider_identifier"] == "Rider Code"
    assert mapping["date"] == "Date"
    assert mapping["completed_orders"] == "Delivered Orders"

    # 2. Ninja headers
    ninja_headers = ["Courier ID", "Log Date", "Verified Orders", "Hub Name"]
    plat, mapping = detect_platform_and_map_headers(ninja_headers)
    assert plat == "NINJA"
    assert mapping["rider_identifier"] == "Courier ID"
    assert mapping["date"] == "Log Date"
    assert mapping["completed_orders"] == "Verified Orders"

    # 3. Jahez headers
    jahez_headers = ["Driver Code", "تاريخ التوصيل", "الطلبات المسلمة", "المشروع"]
    plat, mapping = detect_platform_and_map_headers(jahez_headers)
    assert plat == "JAHEZ"
    assert mapping["rider_identifier"] == "Driver Code"
    assert mapping["date"] == "تاريخ التوصيل"
    assert mapping["completed_orders"] == "الطلبات المسلمة"

    # 4. Standard DOU Generic
    dou_headers = ["rider_phone", "date", "project", "completed_orders", "notes"]
    plat, mapping = detect_platform_and_map_headers(dou_headers)
    assert plat == "DOU_GENERIC"
    assert mapping["rider_identifier"] == "rider_phone"


def test_multi_identifier_and_date_resolution(test_db):
    tenant = ent.Tenant(name="Fleet Logistics", country=ent.Country.SA)
    test_db.add(tenant)
    test_db.commit()

    project = ent.Project(name="Al-Malaz Hub", tenant_id=tenant.id)
    test_db.add(project)
    test_db.commit()

    user = ent.User(name="Admin", phone="966500000000", password_hash="hashedpass", tenant_id=tenant.id, role=ent.UserRole.COMPANY)
    test_db.add(user)
    test_db.commit()

    # Rider 1: has platform_courier_id = 'HS-101'
    rider_1 = ent.Courier(
        name="Hungerstation Rider",
        phone="0550000001",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        platform_courier_id="HS-101",
        tenant_id=tenant.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )

    # Rider 2: has iqama_number = '2450000002'
    rider_2 = ent.Courier(
        name="Iqama Identified Rider",
        phone="0550000002",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        iqama_number="2450000002",
        tenant_id=tenant.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )

    # Rider 3: identified by direct phone
    rider_3 = ent.Courier(
        name="Phone Identified Rider",
        phone="0550000003",
        country=ent.Country.SA,
        courier_type=ent.CourierType.COMPANY,
        tenant_id=tenant.id,
        primary_project_id=project.id,
        employment_status="ACTIVE",
    )

    test_db.add_all([rider_1, rider_2, rider_3])
    test_db.commit()

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yesterday_slash = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")

    # CSV with mixed identifiers, different date format, and no project column (auto-resolved to primary_project)
    csv_content = f"""Rider Code,Date,Delivered Orders
HS-101,{yesterday},18
2450000002,{yesterday_slash},22
0550000003,{yesterday},15
"""

    # Preview
    preview = preview_performance_import(test_db, user, csv_content, file_name="hungerstation_export.csv")

    assert preview["detected_platform"] == "HUNGERSTATION"
    assert preview["total_rows"] == 3
    assert preview["valid_rows"] == 3
    assert preview["invalid_rows"] == 0

    batch = test_db.get(ent.OperationalImportBatch, preview["id"])
    confirmed = confirm_performance_import(test_db, user, batch)
    assert confirmed["result"]["imported"] == 3

    # Verify daily logs created accurately
    logs = test_db.query(ent.DailyLog).filter(ent.DailyLog.tenant_id == tenant.id).all()
    assert len(logs) == 3
    orders_by_courier = {log.courier_id: log.orders_count for log in logs}
    assert orders_by_courier[rider_1.id] == 18
    assert orders_by_courier[rider_2.id] == 22
    assert orders_by_courier[rider_3.id] == 15
