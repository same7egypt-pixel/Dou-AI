from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    AuditLog, Country, Courier, CourierType, GeoCity, GeoCountry,
    TeamMembership, Tenant, TenantOperatingCity, User, UserRole,
)
from app.routers.workforce import (
    MembershipCreate, SupervisorAssignmentCreate, TeamCreate, TeamTransfer,
    ZoneCreate, add_team_membership, assign_team_supervisor, create_team,
    create_zone, transfer_rider_team,
)
from app.services.reporting import report_filter_options
from app.services.workforce_scope import supervisor_courier_scope


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def tenant(db, name):
    row = Tenant(name=name, country=Country.SA)
    db.add(row); db.commit(); db.refresh(row)
    return row


def company_user(db, tenant_id):
    row = User(phone=f"company-{tenant_id}", name="Company", password_hash="x", role=UserRole.COMPANY, tenant_id=tenant_id)
    db.add(row); db.commit(); db.refresh(row)
    return row


def rider(db, tenant_id, suffix):
    row = Courier(tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"5000{suffix}", courier_type=CourierType.COMPANY, country=Country.SA)
    db.add(row); db.commit(); db.refresh(row)
    return row


def operating_city(db, tenant_id):
    country = GeoCountry(name=f"Country {tenant_id}", code=f"C{tenant_id}")
    db.add(country); db.flush()
    city = GeoCity(country_id=country.id, name=f"City {tenant_id}")
    db.add(city); db.flush()
    row = TenantOperatingCity(tenant_id=tenant_id, geo_city_id=city.id)
    db.add(row); db.commit(); db.refresh(row)
    return row


def create_zone_and_team(db, user, suffix="A"):
    city = operating_city(db, user.tenant_id)
    zone = create_zone(ZoneCreate(code=f"ZONE-{suffix}", name_ar=f"منطقة {suffix}", name_en=f"Zone {suffix}", operating_city_id=city.id), user, db)
    team = create_team(TeamCreate(code=f"TEAM-{suffix}", name_ar=f"فريق {suffix}", name_en=f"Team {suffix}", zone_id=zone["id"]), user, db)
    return zone, team


def test_zone_rejects_operating_city_from_another_tenant(db):
    first = tenant(db, "First")
    second = tenant(db, "Second")
    user = company_user(db, first.id)
    foreign_city = operating_city(db, second.id)

    with pytest.raises(HTTPException) as error:
        create_zone(ZoneCreate(code="NORTH", name_ar="الشمال", operating_city_id=foreign_city.id), user, db)

    assert error.value.status_code == 404


def test_membership_rejects_cross_tenant_rider_and_audits_valid_create(db):
    first = tenant(db, "First")
    second = tenant(db, "Second")
    user = company_user(db, first.id)
    _, team = create_zone_and_team(db, user)
    foreign_rider = rider(db, second.id, "2")

    with pytest.raises(HTTPException) as error:
        add_team_membership(team["id"], MembershipCreate(courier_id=foreign_rider.id, effective_from=date(2026, 1, 1)), user, db)
    assert error.value.status_code == 404

    own_rider = rider(db, first.id, "1")
    membership = add_team_membership(team["id"], MembershipCreate(courier_id=own_rider.id, effective_from=date(2026, 1, 1)), user, db)
    assert membership["courier_id"] == own_rider.id
    assert db.query(AuditLog).filter(AuditLog.entity == "team_membership", AuditLog.entity_id == membership["id"]).count() == 1


def test_primary_memberships_cannot_overlap(db):
    owner = tenant(db, "Owner")
    user = company_user(db, owner.id)
    _, first_team = create_zone_and_team(db, user, "A")
    _, second_team = create_zone_and_team(db, user, "B")
    own_rider = rider(db, owner.id, "3")
    add_team_membership(first_team["id"], MembershipCreate(courier_id=own_rider.id, effective_from=date(2026, 1, 1)), user, db)

    with pytest.raises(HTTPException) as error:
        add_team_membership(second_team["id"], MembershipCreate(courier_id=own_rider.id, effective_from=date(2026, 2, 1)), user, db)

    assert error.value.status_code == 409


def test_transfer_closes_old_membership_and_preserves_history(db):
    owner = tenant(db, "Owner")
    user = company_user(db, owner.id)
    _, first_team = create_zone_and_team(db, user, "A")
    _, second_team = create_zone_and_team(db, user, "B")
    own_rider = rider(db, owner.id, "4")
    old = add_team_membership(first_team["id"], MembershipCreate(courier_id=own_rider.id, effective_from=date(2026, 1, 1)), user, db)

    new = transfer_rider_team(own_rider.id, TeamTransfer(team_id=second_team["id"], effective_on=date(2026, 3, 1)), user, db)
    previous = db.get(TeamMembership, old["id"])

    assert previous.effective_to == date(2026, 2, 28)
    assert new["team_id"] == second_team["id"]
    assert new["effective_from"] == "2026-03-01"


def test_supervisor_assignment_rejects_cross_tenant_user(db):
    first = tenant(db, "First")
    second = tenant(db, "Second")
    user = company_user(db, first.id)
    _, team = create_zone_and_team(db, user)
    supervisor = User(phone="supervisor-2", password_hash="x", role=UserRole.SUPERVISOR, tenant_id=second.id)
    db.add(supervisor); db.commit(); db.refresh(supervisor)

    with pytest.raises(HTTPException) as error:
        assign_team_supervisor(team["id"], SupervisorAssignmentCreate(supervisor_id=supervisor.id, effective_from=date(2026, 1, 1)), user, db)

    assert error.value.status_code == 404


def test_supervisor_scope_includes_active_team_members_only(db):
    owner = tenant(db, "Owner")
    user = company_user(db, owner.id)
    _, team = create_zone_and_team(db, user)
    supervisor = User(phone="supervisor-1", password_hash="x", role=UserRole.SUPERVISOR, tenant_id=owner.id, is_active=True)
    db.add(supervisor); db.commit(); db.refresh(supervisor)
    own_rider = rider(db, owner.id, "5")
    add_team_membership(team["id"], MembershipCreate(courier_id=own_rider.id, effective_from=date(2026, 1, 1)), user, db)
    assign_team_supervisor(team["id"], SupervisorAssignmentCreate(supervisor_id=supervisor.id, effective_from=date(2026, 1, 1)), user, db)

    visible = db.query(Courier).filter(supervisor_courier_scope(db, supervisor.id, date(2026, 3, 1))).all()

    assert [row.id for row in visible] == [own_rider.id]


def test_report_filters_include_and_apply_team_and_zone(db):
    owner = tenant(db, "Owner")
    user = company_user(db, owner.id)
    zone, team = create_zone_and_team(db, user)
    assigned = rider(db, owner.id, "6")
    rider(db, owner.id, "7")
    add_team_membership(team["id"], MembershipCreate(courier_id=assigned.id, effective_from=date(2026, 1, 1)), user, db)

    options = report_filter_options(
        db, user, {"team_id": team["id"], "effective_on": date(2026, 3, 1)},
        supervisor_courier_scope,
    )

    assert [row["id"] for row in options["riders"]] == [assigned.id]
    assert {row["id"] for row in options["teams"]} == {team["id"]}
    assert {row["id"] for row in options["zones"]} == {zone["id"]}
