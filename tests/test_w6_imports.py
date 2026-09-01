"""W6 tests — Bulk onboarding and data ingestion workflows."""
import csv
import io
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Contract, ContractBranch, Courier, Country, GeoCity, GeoCountry, OperationalImportBatch,
    Project, ProjectContractMapping, SourcePlatform, Tenant, User, UserRole,
)
from app.routers import imports as imports_router
from app.services.rider_imports import normalize_rider_row, preview_rider_import


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


def make_operating_city(db, tenant_id, geo_city_id, display_name="Riyadh"):
    """Helper to create TenantOperatingCity for import tests."""
    from app.models.entities import TenantOperatingCity
    oc = TenantOperatingCity(tenant_id=tenant_id, geo_city_id=geo_city_id, display_name=display_name, is_active=True)
    db.add(oc); db.commit(); db.refresh(oc)
    return oc


def make_source_platform(db, tenant_id):
    sp = SourcePlatform(tenant_id=tenant_id, code="HS", name_ar="هنقرستيشن", name_en="HungerStation")
    db.add(sp); db.commit(); db.refresh(sp)
    return sp


def make_project(db, tenant_id):
    p = Project(tenant_id=tenant_id, name="HS Riyadh", is_active=True)
    db.add(p); db.commit(); db.refresh(p)
    return p


def make_project_mapping(db, tenant_id, source_platform_id, project_id):
    m = ProjectContractMapping(
        tenant_id=tenant_id, source_platform_id=source_platform_id,
        project_id=project_id, is_active=True
    )
    db.add(m); db.commit(); db.refresh(m)
    return m


def make_contract(db, tenant_id):
    c = Contract(tenant_id=tenant_id, name="HS Riyadh")
    db.add(c); db.commit(); db.refresh(c)
    return c


def make_supervisor(db, tenant_id, name="Super", phone="96650000099"):
    u = User(phone=phone, password_hash="x", role=UserRole.SUPERVISOR, tenant_id=tenant_id, name=name, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def make_branch(db, tenant_id, contract_id, city_id, supervisor_id=None, project_id=None):
    b = ContractBranch(tenant_id=tenant_id, contract_id=contract_id, city_id=city_id, city="Riyadh", is_active=True, supervisor_id=supervisor_id, project_id=project_id)
    db.add(b); db.commit(); db.refresh(b)
    return b


def setup_full_tenant(db):
    """Helper to create a complete tenant setup for rider import tests."""
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)
    country = make_country(db)
    city = make_city(db, country_id=country.id)
    operating_city = make_operating_city(db, tenant_id=tenant.id, geo_city_id=city.id)
    sp = make_source_platform(db, tenant_id=tenant.id)
    project = make_project(db, tenant_id=tenant.id)
    make_project_mapping(db, tenant_id=tenant.id, source_platform_id=sp.id, project_id=project.id)
    contract = make_contract(db, tenant_id=tenant.id)
    sup = make_supervisor(db, tenant_id=tenant.id)
    branch = make_branch(db, tenant_id=tenant.id, contract_id=contract.id, city_id=city.id, supervisor_id=sup.id, project_id=project.id)
    return tenant, admin


def test_preview_rider_import_valid(db):
    tenant, admin = setup_full_tenant(db)

    csv_text = "name,mobile,initial_password,city,branch,contract_or_project,supervisor,base_salary,employment_status\n"
    csv_text += "New Rider,966500000100,Pass1234,Riyadh,Riyadh,HS Riyadh,Super,2000,ACTIVE"

    result = preview_rider_import(db, admin, csv_text, "test.csv")
    assert result["total_rows"] == 1
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 0


def test_preview_rider_import_invalid_phone(db):
    tenant, admin = setup_full_tenant(db)

    csv_text = "name,mobile,initial_password,city,branch,contract_or_project,supervisor,base_salary,employment_status\n"
    csv_text += "Bad Rider,,Pass1234,Riyadh,Riyadh,HS Riyadh,Super,2000,ACTIVE"

    result = preview_rider_import(db, admin, csv_text, "test.csv")
    assert result["total_rows"] == 1
    assert result["valid_rows"] == 0
    assert result["invalid_rows"] == 1
    assert len(result["errors"]) > 0


def test_preview_rider_import_duplicate_in_file(db):
    tenant, admin = setup_full_tenant(db)

    csv_text = "name,mobile,initial_password,city,branch,contract_or_project,supervisor,base_salary,employment_status\n"
    csv_text += "Rider One,966500000100,Pass1234,Riyadh,Riyadh,HS Riyadh,Super,2000,ACTIVE\n"
    csv_text += "Rider Two,966500000100,Pass1234,Riyadh,Riyadh,HS Riyadh,Super,2000,ACTIVE"

    result = preview_rider_import(db, admin, csv_text, "test.csv")
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 1


def test_import_history_list(db):
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)

    # Create some import batches
    for i in range(3):
        batch = OperationalImportBatch(
            tenant_id=tenant.id, import_type="RIDERS", status="PREVIEW",
            file_name=f"test{i}.csv", fingerprint=f"fp{i}",
            total_rows=10, valid_rows=8, invalid_rows=2, created_by=admin.id,
        )
        db.add(batch)
    db.commit()

    result = imports_router.list_import_history(user=admin, db=db, limit=50, offset=0)
    assert result["total"] >= 1
    assert len(result["items"]) >= 1


def test_import_history_filter_by_type(db):
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)

    b1 = OperationalImportBatch(
        tenant_id=tenant.id, import_type="RIDERS", status="COMMITTED",
        file_name="riders.csv", fingerprint="fp1",
        total_rows=10, valid_rows=10, invalid_rows=0, created_by=admin.id,
    )
    b2 = OperationalImportBatch(
        tenant_id=tenant.id, import_type="PERFORMANCE", status="COMMITTED",
        file_name="perf.csv", fingerprint="fp2",
        total_rows=50, valid_rows=50, invalid_rows=0, created_by=admin.id,
    )
    db.add_all([b1, b2]); db.commit()

    result = imports_router.list_import_history(import_type="RIDERS", user=admin, db=db, limit=50, offset=0)
    assert result["total"] >= 1
    assert all(item["import_type"] == "RIDERS" for item in result["items"])


def test_import_history_tenant_isolation(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    admin1 = make_admin(db, tenant_id=tenant1.id)
    admin2 = User(phone="966500000002", password_hash="x", role=UserRole.COMPANY_ADMIN, tenant_id=tenant2.id)
    db.add(admin2); db.commit()

    b1 = OperationalImportBatch(
        tenant_id=tenant1.id, import_type="RIDERS", status="COMMITTED",
        file_name="t1.csv", fingerprint="fp1",
        total_rows=10, valid_rows=10, invalid_rows=0, created_by=admin1.id,
    )
    b2 = OperationalImportBatch(
        tenant_id=tenant2.id, import_type="RIDERS", status="COMMITTED",
        file_name="t2.csv", fingerprint="fp2",
        total_rows=20, valid_rows=20, invalid_rows=0, created_by=admin2.id,
    )
    db.add_all([b1, b2]); db.commit()

    result = imports_router.list_import_history(user=admin1, db=db, limit=50, offset=0)
    # Only tenant1's batches should be visible
    assert all(item["file_name"] == "t1.csv" for item in result["items"])


def test_get_import_detail(db):
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)

    batch = OperationalImportBatch(
        tenant_id=tenant.id, import_type="RIDERS", status="PREVIEW",
        file_name="test.csv", fingerprint="fp1",
        total_rows=10, valid_rows=8, invalid_rows=2, created_by=admin.id,
        payload_json=json.dumps({"errors": [{"row": 1, "field": "mobile", "reason": "bad"}]}),
    )
    db.add(batch); db.commit(); db.refresh(batch)

    result = imports_router.get_import_detail(batch.id, user=admin, db=db)
    assert result["id"] == batch.id
    assert result["import_type"] == "RIDERS"
    assert len(result["errors"]) == 1


def test_get_import_detail_not_found(db):
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)

    with pytest.raises(HTTPException) as exc:
        imports_router.get_import_detail(999, user=admin, db=db)
    assert exc.value.status_code == 404


def test_cancel_import_batch(db):
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)

    batch = OperationalImportBatch(
        tenant_id=tenant.id, import_type="RIDERS", status="PREVIEW",
        file_name="test.csv", fingerprint="fp1",
        total_rows=10, valid_rows=8, invalid_rows=2, created_by=admin.id,
    )
    db.add(batch); db.commit()

    result = imports_router.cancel_import_batch(batch.id, user=admin, db=db)
    assert result["ok"] is True
    assert db.query(OperationalImportBatch).count() == 0


def test_cancel_committed_batch_fails(db):
    tenant = make_tenant(db)
    admin = make_admin(db, tenant_id=tenant.id)

    batch = OperationalImportBatch(
        tenant_id=tenant.id, import_type="RIDERS", status="COMMITTED",
        file_name="test.csv", fingerprint="fp1",
        total_rows=10, valid_rows=10, invalid_rows=0, created_by=admin.id,
    )
    db.add(batch); db.commit()

    with pytest.raises(HTTPException) as exc:
        imports_router.cancel_import_batch(batch.id, user=admin, db=db)
    assert exc.value.status_code == 409


def test_confirm_rider_import_idempotent(db):
    """Confirming twice should not create duplicate riders."""
    tenant, admin = setup_full_tenant(db)

    csv_text = "name,mobile,initial_password,city,branch,contract_or_project,supervisor,base_salary,employment_status\n"
    csv_text += "New Rider,966500000100,Pass1234,Riyadh,Riyadh,HS Riyadh,Super,2000,ACTIVE"

    result = preview_rider_import(db, admin, csv_text, "test.csv")
    batch_id = result["id"]

    from app.services.rider_imports import confirm_rider_import
    batch = db.query(OperationalImportBatch).get(batch_id)
    confirm_rider_import(db, admin, batch)
    assert db.query(Courier).count() == 1

    # Second confirm should be idempotent
    confirm_rider_import(db, admin, batch)
    assert db.query(Courier).count() == 1
