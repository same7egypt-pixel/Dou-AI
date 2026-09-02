#!/usr/bin/env python3
"""Give staging a realistic shape: a client contract, a branch, and delivery facts.

Staging had riders but no contract, no branch and no platform facts, so the
reports that read those returned empty and the E2E suite could not tell an empty
dataset from a broken endpoint. This mirrors how a real customer is set up:

    company -> contract with the delivery platform -> branch in a city
    -> riders assigned to the branch -> daily delivery facts

Idempotent: re-running it will not duplicate the contract or the facts.
"""

from datetime import date, timedelta

from sqlalchemy import func

from app.database import SessionLocal
from app.models.entities import (
    Contract,
    ContractBranch,
    Courier,
    DailyLog,
    PlatformDeliveryFact,
    Tenant,
)


def main() -> None:
    db = SessionLocal()
    # Pick the tenant that actually operates riders. Tenant 1 is the DOU
    # platform itself, not a customer, so ordering by id picks the wrong one.
    tenant = (
        db.query(Tenant)
        .join(Courier, Courier.tenant_id == Tenant.id)
        .group_by(Tenant.id)
        .order_by(func.count(Courier.id).desc())
        .first()
    )
    if tenant is None:
        raise SystemExit("staging has no tenant with riders; seed demo data first")

    contract = (
        db.query(Contract)
        .filter(Contract.tenant_id == tenant.id, Contract.name == "HungerStation")
        .first()
    )
    if contract is None:
        contract = Contract(
            tenant_id=tenant.id,
            name="HungerStation",
            status="ACTIVE",
            scope_type="CONTRACT",
            client_rate_per_order=11.5,   # what the company bills the platform
            start_date=date.today() - timedelta(days=90),
        )
        db.add(contract)
        db.flush()

    branch = (
        db.query(ContractBranch)
        .filter(ContractBranch.contract_id == contract.id)
        .first()
    )
    if branch is None:
        branch = ContractBranch(
            tenant_id=tenant.id,
            contract_id=contract.id,
            branch_name="الرياض — العليا",
            city="الرياض",
            is_active=True,
            dedicated_riders_target=5,
        )
        db.add(branch)
        db.flush()

    riders = db.query(Courier).filter(Courier.tenant_id == tenant.id).all()
    for rider in riders:
        rider.contract_id = contract.id
        rider.contract_branch_id = branch.id

    # Two weeks of platform facts. This table is a daily aggregate per contract,
    # not per rider, and is unique on (tenant, contract_name, date).
    created = 0
    for offset in range(14):
        day = date.today() - timedelta(days=offset)
        exists = (
            db.query(PlatformDeliveryFact)
            .filter(
                PlatformDeliveryFact.tenant_id == tenant.id,
                PlatformDeliveryFact.contract_name == contract.name,
                PlatformDeliveryFact.created_date == day,
            )
            .first()
        )
        if not exists:
            notified = 90 + (offset * 7) % 40
            completed = notified - (offset % 5) - 3
            db.add(
                PlatformDeliveryFact(
                    tenant_id=tenant.id,
                    contract_id=contract.id,
                    created_date=day,
                    city_name="Riyadh",
                    contract_name=contract.name,
                    riders_count=len(riders),
                    shifts_done=len(riders),
                    planned_hours=len(riders) * 9.0,
                    actual_working_hours=len(riders) * (8.0 + (offset % 3) * 0.4),
                    break_hours=len(riders) * 0.5,
                    acceptance_rate=round(0.93 + (offset % 5) * 0.01, 2),
                    notified_deliveries=notified,
                    completed_deliveries=completed,
                    accepted_deliveries=completed + 2,
                    declined_deliveries=offset % 4,
                    cancelled_deliveries=offset % 3,
                    no_shows=offset % 2,
                    source_type="FILE_IMPORT",
                )
            )
            created += 1

        # Per-rider daily orders, which is what payroll reads.
        for index, rider in enumerate(riders):
            if (
                db.query(DailyLog)
                .filter(DailyLog.courier_id == rider.id, DailyLog.log_date == day)
                .first()
            ):
                continue
            db.add(
                DailyLog(
                    tenant_id=tenant.id,
                    courier_id=rider.id,
                    log_date=day,
                    orders_count=12 + (index * 3 + offset) % 9,
                )
            )

    db.commit()
    print(
        f"contract={contract.name} branch={branch.branch_name} "
        f"riders={len(riders)} new_fact_days={created}"
    )
    db.close()


if __name__ == "__main__":
    main()
