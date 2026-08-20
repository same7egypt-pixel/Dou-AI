"""Create a disposable DOU QA tenant for repeatable performance measurements.

Run only with DATABASE_URL pointed at an isolated database. This script never reads
or writes production connection settings or production records.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from app.database import Base, SessionLocal, engine
from app.models import entities  # noqa: F401 -- registers all models with Base
from app.models.entities import (
    Attendance,
    Contract,
    ContractBranch,
    Country,
    Courier,
    CourierType,
    Fleet,
    GeoCity,
    GeoCountry,
    Project,
    Tenant,
    TenantOperatingCity,
    User,
    UserRole,
    DailyLog,
)
from app.routers.auth import hash_password


QA_TENANT_NAME = "DOU Performance QA"
QA_PHONE = "966581112233"
QA_PASSWORD = "QAPerfPass123"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--riders", type=int, default=100)
    parser.add_argument("--with-activity", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0 <= args.riders <= 5000:
        raise SystemExit("--riders must be between 0 and 5000")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(Tenant).filter(Tenant.name == QA_TENANT_NAME).first()
        if existing:
            raise SystemExit("QA tenant already exists; recreate the isolated QA database before seeding")

        tenant = Tenant(
            name=QA_TENANT_NAME,
            country=Country.SA,
            market_code="SA",
            default_language="ar",
            currency="SAR",
            timezone="Asia/Riyadh",
            contact_email="qa-performance@invalid.example",
            contact_phone=QA_PHONE,
            is_dou_internal=False,
            plan="PRO",
            subscription_status="ACTIVE",
        )
        db.add(tenant)
        db.flush()

        company = User(
            phone=QA_PHONE,
            name="DOU Performance QA Company",
            password_hash=hash_password(QA_PASSWORD),
            role=UserRole.COMPANY,
            tenant_id=tenant.id,
            country=Country.SA,
            is_active=True,
        )
        supervisor = User(
            phone="966589990002",
            name="DOU Performance QA Supervisor",
            password_hash=hash_password(QA_PASSWORD),
            role=UserRole.SUPERVISOR,
            tenant_id=tenant.id,
            country=Country.SA,
            is_active=True,
        )
        fleet = Fleet(tenant_id=tenant.id, name="QA Operations Fleet", zone="QA Zone")
        country = GeoCountry(name="Saudi Arabia", code="SA", active=True)
        db.add_all([company, supervisor, fleet, country])
        db.flush()

        city = GeoCity(country_id=country.id, name="QA Riyadh", active=True)
        db.add(city)
        db.flush()
        db.add(TenantOperatingCity(tenant_id=tenant.id, geo_city_id=city.id, is_active=True))

        project = Project(tenant_id=tenant.id, name="QA Operations Project", manager_id=company.id, is_active=True)
        db.add(project)
        db.flush()
        contract = Contract(
            tenant_id=tenant.id,
            project_id=project.id,
            name="QA Commercial Contract",
            client_name="QA Client",
            client_rate_per_order=8.0,
            contract_type="COMMERCIAL",
            status="ACTIVE",
            start_date=datetime.utcnow(),
        )
        db.add(contract)
        db.flush()
        branch = ContractBranch(
            tenant_id=tenant.id,
            contract_id=contract.id,
            city_id=city.id,
            city=city.name,
            project_id=project.id,
            supervisor_id=supervisor.id,
            is_active=True,
        )
        db.add(branch)
        db.flush()

        today = date.today()
        riders = []
        logs = []
        attendance = []
        for number in range(args.riders):
            courier = Courier(
                tenant_id=tenant.id,
                fleet_id=fleet.id,
                name=f"QA Rider {number + 1:05d}",
                phone=f"966588{number:06d}",
                courier_type=CourierType.COMPANY,
                country=Country.SA,
                is_online=number % 3 == 0,
                documents_valid=number % 19 != 0,
                employment_status="ACTIVE",
                supervisor_id=supervisor.id,
                primary_project_id=project.id,
                contract_id=contract.id,
                contract_branch_id=branch.id,
                city_id=city.id,
                work_city=city.name,
                platform=project.name,
                acceptance_rate=98.0,
                on_time_rate=96.0,
                completion_rate=97.0,
                score=4.7,
                base_salary=1000.0,
                per_delivery_rate=5.0,
                hired_at=datetime.utcnow() - timedelta(days=90),
            )
            riders.append(courier)
        db.add_all(riders)
        db.flush()
        courier_account_hash = hash_password(QA_PASSWORD)
        db.add_all([
            User(
                phone=courier.phone,
                name=courier.name,
                password_hash=courier_account_hash,
                role=UserRole.COURIER,
                courier_id=courier.id,
                tenant_id=tenant.id,
                country=Country.SA,
                is_active=True,
            )
            for courier in riders
        ])
        if args.with_activity:
            for number, courier in enumerate(riders):
                logs.append(DailyLog(
                    courier_id=courier.id,
                    tenant_id=tenant.id,
                    project_id=project.id,
                    log_date=today,
                    orders_count=20 + (number % 11),
                    source_type="PERFORMANCE_QA",
                ))
                if number % 2 == 0:
                    attendance.append(Attendance(
                        courier_id=courier.id,
                        check_in=datetime.utcnow() - timedelta(hours=2),
                        is_late=number % 10 == 0,
                    ))
        db.add_all(logs + attendance)
        db.commit()
        print({"tenant": tenant.name, "riders": args.riders, "company_phone": QA_PHONE})
    finally:
        db.close()


if __name__ == "__main__":
    main()
