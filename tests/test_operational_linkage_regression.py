from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Attendance,
    BonusPlan,
    Contract,
    ContractBranch,
    ContractBranchSupervisor,
    Country,
    Courier,
    CourierType,
    DailyLog,
    GeoCity,
    GeoCountry,
    Project,
    Tenant,
    TenantOperatingCity,
    User,
    UserRole,
)
from app.routers.fleet import update_courier
from app.routers.hr import delete_contract_branch, hr_contracts, update_contract
from app.routers.vehicles import (
    VehicleAssignmentCreate,
    VehicleCreate,
    assign_vehicle,
    create_vehicle,
)
from app.services.financial_calculations import calculate_payroll_preview


def test_supervisor_assignment_links_operational_and_financial_chain():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        tenant = Tenant(name="Lifecycle Co", country=Country.SA, market_code="SA")
        db.add(tenant)
        db.flush()
        admin = User(
            phone="admin-life",
            password_hash="x",
            role=UserRole.COMPANY,
            tenant_id=tenant.id,
        )
        supervisor = User(
            name="Primary Supervisor",
            phone="sup-life",
            password_hash="x",
            role=UserRole.SUPERVISOR,
            tenant_id=tenant.id,
            is_active=True,
        )
        country = GeoCountry(name="Saudi Arabia", code="SA", flag="SA", active=True)
        db.add_all([admin, supervisor, country])
        db.flush()
        city = GeoCity(country_id=country.id, name="Riyadh", active=True)
        project = Project(
            tenant_id=tenant.id,
            name="Contract Branch",
            is_active=True,
            manager_id=supervisor.id,
        )
        contract = Contract(
            tenant_id=tenant.id,
            name="Lifecycle Contract",
            status="ACTIVE",
        )
        db.add_all([city, project, contract])
        db.flush()
        db.add(
            TenantOperatingCity(
                tenant_id=tenant.id,
                geo_city_id=city.id,
                display_name=city.name,
                is_active=True,
            )
        )
        branch = ContractBranch(
            tenant_id=tenant.id,
            contract_id=contract.id,
            city_id=city.id,
            city=city.name,
            project_id=project.id,
            supervisor_id=supervisor.id,
            is_active=True,
        )
        rider = Courier(
            tenant_id=tenant.id,
            name="Lifecycle Rider",
            phone="rider-life",
            courier_type=CourierType.COMPANY,
            country=Country.SA,
            employment_status="ACTIVE",
            base_salary=2000,
        )
        db.add_all([branch, rider])
        db.commit()

        update_courier(rider.id, {"supervisor_id": supervisor.id}, admin, db)
        db.refresh(rider)
        assert rider.contract_id == contract.id
        assert rider.contract_branch_id == branch.id
        assert rider.primary_project_id == project.id
        assert rider.supervisor_id == supervisor.id

        second_supervisor = User(
            name="Second Supervisor",
            phone="sup-life-2",
            password_hash="x",
            role=UserRole.SUPERVISOR,
            tenant_id=tenant.id,
            is_active=True,
        )
        db.add(second_supervisor)
        db.add(
            Project(
                tenant_id=tenant.id,
                name=f"{contract.name} — {city.name} — {supervisor.name}",
                is_active=False,
            )
        )
        db.commit()
        update_contract(
            contract.id,
            {
                "branches": [
                    {
                        "id": branch.id,
                        "city_id": city.id,
                        "supervisor_ids": [supervisor.id, second_supervisor.id],
                    }
                ]
            },
            admin,
            db,
        )
        db.refresh(rider)
        assert rider.supervisor_id == supervisor.id
        assert {
            row.supervisor_id
            for row in db.query(ContractBranchSupervisor)
            .filter(ContractBranchSupervisor.contract_branch_id == branch.id)
            .all()
        } == {supervisor.id, second_supervisor.id}
        listed_branch = hr_contracts(admin, db)["rows"][0]["branches"][0]
        assert set(listed_branch["supervisor_ids"]) == {
            supervisor.id,
            second_supervisor.id,
        }

        vehicle = create_vehicle(
            VehicleCreate(plate_number="LIFE 100", vehicle_type="Motorcycle"),
            admin,
            db,
        )
        assignment = assign_vehicle(
            vehicle["id"],
            VehicleAssignmentCreate(courier_id=rider.id, effective_from=date.today()),
            admin,
            db,
        )
        assert assignment["courier_id"] == rider.id

        db.add(
            BonusPlan(
                tenant_id=tenant.id,
                contract_id=contract.id,
                contract_branch_id=branch.id,
                project_id=project.id,
                plan_type="FLAT_PER_ORDER",
                flat_order_rate=9,
                is_active=True,
                effective_from=date.today().replace(day=1),
            )
        )
        db.add(
            DailyLog(
                courier_id=rider.id,
                project_id=project.id,
                log_date=date.today(),
                orders_count=10,
            )
        )
        db.add(
            Attendance(
                courier_id=rider.id,
                check_in=datetime.now() - timedelta(hours=8),
                check_out=datetime.now(),
            )
        )
        db.commit()

        payroll = calculate_payroll_preview(
            db, rider, date.today().strftime("%Y-%m")
        )
        assert payroll["bonus"]["source"] == "branch"
        assert payroll["bonus"]["orders"] == 10
        assert payroll["bonus"]["earned"] == 90
        assert payroll["itemized_breakdown"]["base_salary"] == 2000
        assert payroll["itemized_breakdown"]["delivery_pay"] == 60
        assert payroll["itemized_breakdown"]["net_pay"] == 2150
        assert (
            db.query(Attendance).filter(Attendance.courier_id == rider.id).count()
            == 1
        )
    finally:
        db.close()


def test_contract_branch_deletion_disappears_from_contracts_and_preserves_riders():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        tenant = Tenant(name="Branch Delete Co", country=Country.SA, market_code="SA")
        db.add(tenant)
        db.flush()
        admin = User(
            phone="admin-branch-delete",
            password_hash="x",
            role=UserRole.COMPANY,
            tenant_id=tenant.id,
        )
        contract = Contract(
            tenant_id=tenant.id,
            name="Delete Contract",
            status="ACTIVE",
        )
        db.add_all([admin, contract])
        db.flush()
        empty_branch = ContractBranch(
            tenant_id=tenant.id,
            contract_id=contract.id,
            city="Riyadh",
            is_active=True,
        )
        occupied_branch = ContractBranch(
            tenant_id=tenant.id,
            contract_id=contract.id,
            city="Jeddah",
            is_active=True,
        )
        db.add_all([empty_branch, occupied_branch])
        db.flush()
        rider = Courier(
            tenant_id=tenant.id,
            name="Assigned Rider",
            phone="rider-branch-delete",
            courier_type=CourierType.COMPANY,
            country=Country.SA,
            employment_status="ACTIVE",
            contract_id=contract.id,
            contract_branch_id=occupied_branch.id,
        )
        db.add(rider)
        db.commit()

        assert delete_contract_branch(empty_branch.id, admin, db) == {"ok": True}
        rows = hr_contracts(admin, db)["rows"]
        assert [branch["id"] for branch in rows[0]["branches"]] == [
            occupied_branch.id
        ]

        with pytest.raises(HTTPException) as exc:
            delete_contract_branch(occupied_branch.id, admin, db)
        assert exc.value.status_code == 409
        db.refresh(rider)
        db.refresh(occupied_branch)
        assert rider.contract_branch_id == occupied_branch.id
        assert occupied_branch.is_active is True
    finally:
        db.close()
