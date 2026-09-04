"""A DOU-internal account is told where it belongs, not shown ten broken screens.

Found by crawling production as every role. The fleet admin was clean; the
DOU_OPS account signed in, was handed the full sidebar, and then failed 403 on
every screen it opened — over thirty failed requests in one session, with
nothing anywhere saying why.

The cause was `/fleet/me` answering `permissions: ["*"]` alongside
`tenant: null`. The shell believed the permissions and drew screens that every
tenant-scoped endpoint behind them refuses.

The first fix attempted here was to refuse the endpoint for internal roles. That
would have locked DOU staff out of their own console: /admin authenticates
through this same `/fleet/me`. Hence this file's second test — the mistake is
cheap to repeat and expensive to ship.

The fleet endpoints are deliberately not opened to DOU staff. That would build a
cross-tenant read path into the customer application. Staff reach a tenant
through /admin support-login, which issues a token scoped to that tenant.
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
from app.models.entities import Country, Tenant, User, UserRole
from app.routers.auth import create_token, hash_password

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    def account(name, role, phone, tenant=None):
        user = User(
            phone=phone, name=name, role=role, is_active=True,
            tenant_id=tenant.id if tenant else None,
            password_hash=hash_password("Pass12345!"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"user": user, "token": create_token(user)}

    tenant = Tenant(name="شركة", country=Country.SA, plan="PRO",
                    subscription_status="ACTIVE")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    app.dependency_overrides[get_db] = lambda: db
    yield {
        "db": db, "client": TestClient(app), "tenant": tenant, "account": account,
    }
    app.dependency_overrides.clear()
    db.close()


def _me(env, token):
    return env["client"].get("/fleet/me", headers={"Authorization": f"Bearer {token}"})


def test_an_internal_account_is_told_which_surface_is_its_own(env):
    ops = env["account"]("Ops Cloud", UserRole.DOU_OPS, "966500000000")
    body = _me(env, ops["token"]).json()

    assert body["tenant"] is None
    assert body.get("surfaces") == ["/admin"], (
        "the shell has no way to know this account belongs elsewhere"
    )
    assert body.get("surface_notice"), "and no sentence to show the person"


def test_the_admin_console_still_authenticates_through_this_endpoint(env):
    """The first attempt at this fix was a 403 here. /admin calls the same
    endpoint, so that would have locked DOU staff out of their own console."""
    for role in (UserRole.DOU_ADMIN, UserRole.DOU_OPS):
        staff = env["account"](f"{role.value} user", role, f"96650000{role.value[-4:]}")
        res = _me(env, staff["token"])
        assert res.status_code == 200, (
            f"{role.value} can no longer authenticate; /admin is locked out"
        )


def test_a_tenant_account_is_unaffected(env):
    owner = env["account"](
        "مدير", UserRole.COMPANY_ADMIN, "966581112233", env["tenant"]
    )
    body = _me(env, owner["token"]).json()
    assert body["tenant"]["id"] == env["tenant"].id
    assert "surfaces" not in body, (
        "a real tenant account must not be redirected off its own app"
    )


def test_the_fleet_endpoints_stay_closed_to_internal_accounts(env):
    """Opening these to DOU staff would be a cross-tenant read path inside the
    customer application. Telling the account where to go is the fix; widening
    the data boundary is not."""
    ops = env["account"]("Ops Cloud", UserRole.DOU_OPS, "966500000000")
    headers = {"Authorization": f"Bearer {ops['token']}"}
    for path in ("/fleet/overview", "/fleet/couriers/page?page=1&page_size=5",
                 "/fleet/shifts"):
        assert env["client"].get(path, headers=headers).status_code == 403, (
            f"{path} now serves a tenantless internal account"
        )


def test_the_shell_reads_the_surface_instead_of_drawing_broken_screens():
    source = (ROOT / "frontend-v2" / "fleet" / "main.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", source)
    assert "me.surfaces" in code, (
        "the shell still renders the sidebar for an account with no tenant"
    )
    assert "me.tenant" in code


# ─────────────────────────────────────────────────────────────────────────────
# A screen the role cannot use is absent, not merely empty
# ─────────────────────────────────────────────────────────────────────────────


def test_a_supervisor_is_not_offered_payroll(env):
    """`/hr/payroll` refuses anyone outside COMPANY_ROLES, so a supervisor
    opening this screen got a 403 and a blank page. The audit named this and it
    survived; crawling production as a supervisor found it again along with
    every tab behind it."""
    from app.routers.hr import COMPANY_ROLES

    assert UserRole.SUPERVISOR not in COMPANY_ROLES, (
        "if supervisors gained payroll access, this gate should be reconsidered "
        "rather than left stale"
    )
    shell = (ROOT / "frontend-v2" / "fleet" / "shell.js").read_text(encoding="utf-8")
    role_only = shell[shell.index("const ROLE_ONLY = {"):]
    role_only = role_only[: role_only.index("};")]
    assert "payroll:" in role_only, "the payroll screen is still shown to every role"
    assert "SUPERVISOR" not in role_only.split("payroll:")[1].split("\n")[0]


def test_a_supervisor_is_not_offered_the_contracts_tab(env):
    """`/hr/contracts` refuses a supervisor; the tab opened to an empty panel."""
    capacity = (ROOT / "frontend-v2" / "fleet" / "views" / "capacity.js").read_text(
        encoding="utf-8"
    )
    tabs = capacity[capacity.index("const tabsList = ["):]
    tabs = tabs[: tabs.index("const tabsNav")]
    assert "CONTRACT_ROLES" in tabs, "the contracts tab is still unconditional"
    roles_line = tabs[tabs.index("CONTRACT_ROLES ="):].split("\n")[0]
    assert "SUPERVISOR" not in roles_line


def test_the_capacity_screen_still_has_a_tab_for_every_role(env):
    """Hiding a tab must never leave a screen with none: the capacity tab
    itself is unconditional."""
    capacity = (ROOT / "frontend-v2" / "fleet" / "views" / "capacity.js").read_text(
        encoding="utf-8"
    )
    declared = capacity[capacity.index("const tabsList = ["):]
    declared = declared[: declared.index("];")]
    assert "id: 'capacity'" in declared, (
        "every role must land on at least one tab that works"
    )


def test_the_driver_app_knows_who_the_rider_is_before_asking_for_their_tasks():
    """Tasks were requested inside the same Promise.all that fetched the rider,
    from an id the very next line was about to store. On a first sign-in the id
    was absent, `|| 0` stood in, and the rider's first view of their own day was
    an empty list from GET /couriers/0/tasks — 404, filled in only on reload."""
    source = (ROOT / "static" / "courier.html").read_text(encoding="utf-8")
    body = source[source.index("async function loadCore()"):]
    body = body[: body.index("async function refreshCore()")]
    code = re.sub(r"//[^\n]*", "", body)

    assert "|| 0" not in code, "the tasks request still falls back to courier 0"
    promise_all = code[code.index("Promise.all(["):code.index("]);")]
    assert "/tasks" not in promise_all, (
        "tasks are still requested in parallel with the identity they depend on"
    )
    assert "courier?.id" in code, "the rider id must come from the response"
