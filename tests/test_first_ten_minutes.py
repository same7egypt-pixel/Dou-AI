"""The first ten minutes decide whether a paid trial becomes a customer.

Walked a genuinely empty account as a new logistics company. Nothing was
broken — every endpoint answered 200 — and the trial still died at the first
action:

The command centre told a company with zero riders that "الأسطول يعمل بحالة
مستقرة وطبيعية". That is the first sentence the product speaks to someone who
has paid, and it is unmeasured; it teaches the customer that status messages
here mean nothing, which costs every real alert afterwards.

Nine screens of zeros offered no order and no starting point, while the command
centre invited the customer to "ask a smart question" about a fleet that did not
exist.

And the obvious first action — add a rider — opened a form numbered 1️⃣ 2️⃣ 3️⃣
whose first required field was an empty dropdown, with nothing anywhere saying
where a contract comes from. The answer was a different tab on a different
screen with no link to it.

The product knew the order all along. It just never said it.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.entities import Contract, Country, Tenant, User, UserRole
from app.routers.auth import create_token, hash_password

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "frontend-v2" / "fleet" / "views"


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    tenant = Tenant(name="شركة جديدة", country=Country.SA, plan="STARTER",
                    subscription_status="ACTIVE")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    owner = User(
        phone="966500111222", name="المالك", role=UserRole.COMPANY_ADMIN,
        tenant_id=tenant.id, is_active=True, password_hash=hash_password("Pass12345!"),
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)

    app.dependency_overrides[get_db] = lambda: db
    yield {
        "db": db, "client": TestClient(app), "tenant": tenant,
        "H": {"Authorization": f"Bearer {create_token(owner)}"},
    }
    app.dependency_overrides.clear()
    db.close()


# ─────────────────────────────────────────────────────────────────────────────
# The guide is a live checklist, not a banner
# ─────────────────────────────────────────────────────────────────────────────


def test_the_overview_reports_what_the_guide_has_to_check(env):
    """Without these counts the checklist could only congratulate the account
    on nothing."""
    body = env["client"].get("/fleet/overview", headers=env["H"]).json()
    for key in ("couriers_total", "contracts_total", "supervisors_total"):
        assert key in body, f"the first-run guide cannot tell whether {key} is done"
    assert body["contracts_total"] == 0
    assert body["supervisors_total"] == 0
    assert body["couriers_total"] == 0


def test_the_counts_move_as_the_customer_completes_each_step(env):
    db = env["db"]
    db.add(User(
        phone="966500999001", name="خالد", role=UserRole.SUPERVISOR,
        tenant_id=env["tenant"].id, is_active=True,
        password_hash=hash_password("Pass12345!"),
    ))
    db.add(Contract(
        tenant_id=env["tenant"].id, name="عقد هنقرستيشن",
        client_name="HungerStation", status="ACTIVE",
    ))
    db.commit()

    body = env["client"].get("/fleet/overview", headers=env["H"]).json()
    assert body["supervisors_total"] == 1
    assert body["contracts_total"] == 1
    assert body["couriers_total"] == 0, "the guide must still show step 3 as open"


def test_the_counts_are_scoped_to_the_company(env):
    """A checklist that counted another company's contracts would tell this
    customer they are done when they have not started."""
    db = env["db"]
    other = Tenant(name="شركة أخرى", country=Country.SA, plan="PRO")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(Contract(tenant_id=other.id, name="عقد الغير", status="ACTIVE"))
    db.add(User(
        phone="966500999009", name="مشرف الغير", role=UserRole.SUPERVISOR,
        tenant_id=other.id, is_active=True, password_hash=hash_password("Pass12345!"),
    ))
    db.commit()

    body = env["client"].get("/fleet/overview", headers=env["H"]).json()
    assert body["contracts_total"] == 0
    assert body["supervisors_total"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# What the screens say
# ─────────────────────────────────────────────────────────────────────────────


def _source(name):
    return (VIEWS / name).read_text(encoding="utf-8")


def test_an_empty_fleet_is_not_called_stable():
    """Scoped to the status block. Looking for the guard anywhere in the file
    matched the first-run guide's own condition further down, so a mutation
    that removed the status override left this passing."""
    code = re.sub(r"//[^\n]*", "", _source("commandCenter.js"))
    block = code[code.index("let statusClass = 'healthy';"):code.index("wrap.append(el('div', { class: 'ops-status-bar' }")]
    assert "fleetSize === 0" in block, (
        "a company with no riders is still told its fleet is operating normally"
    )
    assert "مستقرة وطبيعية" in block[: block.index("fleetSize === 0")], (
        "the empty case must override the default, not precede it"
    )
    override = block[block.index("fleetSize === 0"):]
    assert "statusText" in override, "the guard does not change what is said"


def test_the_command_centre_says_where_to_start():
    code = re.sub(r"//[^\n]*", "", _source("commandCenter.js"))
    assert "renderFirstRunGuide" in code
    guide = code[code.index("function renderFirstRunGuide("):]
    guide = guide[: guide.index("\nfunction ")]
    # The three steps, in the order the product actually requires.
    for step in ("openCreateContractModal", "openSupervisorsManagementModal", "'riders'"):
        assert step in guide, f"the guide has no door for {step}"
    assert "step.done" in guide, "the guide is a banner, not a checklist"


def test_the_guide_is_shown_only_while_it_is_needed():
    """`index` finds the function definition first; the call site is the one
    that has to be guarded."""
    code = re.sub(r"//[^\n]*", "", _source("commandCenter.js"))
    call = code.index("wrap.append(renderFirstRunGuide(")
    preceding = code[max(0, call - 200):call]
    assert "fleetSize === 0" in preceding, (
        "the guide would keep greeting a company that has been running for months"
    )


def test_the_add_rider_form_opens_the_step_that_unblocks_it():
    """It used to present an empty required dropdown and no way forward."""
    # Comments are not stripped here: the boundary this slice needs is a
    # comment, and stripping first left nothing to cut on.
    source = _source("riders.js")
    gate = source[source.index("if (!contracts.length) {"):]
    gate = gate[: gate.index("// Cascading state")]
    assert "openCreateContractModal" in gate, (
        "the wall is still a wall: no route from the blocked form to the fix"
    )
    assert "modal(" in gate


def test_the_branch_dropdown_invents_nothing():
    """It offered "فرع الرياض" with a hardcoded id 1 — a branch that did not
    exist, whose id could belong to another company."""
    code = re.sub(r"//[^\n]*", "", _source("riders.js"))
    assert "'فرع الرياض'" not in code, "the fabricated branch is back"
    assert "value: '1' }" not in code
