"""A platform account can build its operating structure, and its vendor screen tells the truth.

Three defects, all reported by the product owner from the running product:

The operating structure was *replaced* for platforms rather than added to.
capacity.js rendered the same tab id as either "commercial contracts and
branches" or "3PL operating partners" depending on account type, so a platform
holding MANAGE_RIDERS and MANAGE_SUPERVISORS had no screen that could create the
contract, city, branch or supervisor that adding a rider requires. It could not
add a single rider.

The vendor screen was a mock. Two invented companies with fabricated CR numbers
were hardcoded as a fallback, alongside a hardcoded 98.4% SLA and `|| 48` /
`|| 12` rider counts, so a platform with no vendors was shown an imaginary
business as if it were its own.

The "link a 3PL partner" form saved nothing. Its submit handler read the company
name, showed "✅ تم ربط الشركة اللوجستية بنجاح" and closed, without calling any
API — and asked for a CR number, a rate and free-text cities that
PlatformOperator has no columns for.
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
from app.models.entities import Country, CustomerType, PlatformOperator, Tenant, User, UserRole
from app.routers.auth import create_token, hash_password
from app.services import entitlements

ROOT = Path(__file__).resolve().parents[1]
CAPACITY = ROOT / "frontend-v2" / "fleet" / "views" / "capacity.js"


# ─────────────────────────────────────────────────────────────────────────────
# The operating structure is additive
# ─────────────────────────────────────────────────────────────────────────────


def test_the_contracts_tab_is_not_swapped_for_the_vendor_tab():
    """One tab id must not render two different products."""
    source = CAPACITY.read_text(encoding="utf-8")
    tabs = source[source.index("const tabsList = ["):]
    tabs = tabs[: tabs.index("const tabsNav")]
    assert "isPlatform ?" not in tabs, (
        "the contracts tab label still branches on account type; a platform "
        "loses the operating structure instead of gaining the vendor network"
    )
    assert "id: 'operators'" in tabs, "the vendor network needs its own tab"
    assert "can('MANAGE_OPERATORS')" in tabs, "the vendor tab is a capability, not a type"


def test_contracts_management_does_not_redirect_platforms():
    source = CAPACITY.read_text(encoding="utf-8")
    body = source[source.index("async function renderContractsManagement("):][:600]
    assert "renderPlatformOperators" not in body, (
        "the contracts screen still hands platforms to the vendor screen"
    )


def test_creating_a_contract_and_supervisor_is_offered_to_every_account_type():
    source = CAPACITY.read_text(encoding="utf-8")
    actions = source[source.index("if (isAdmin && activeCapacityTab === 'contracts')"):][:900]
    assert "openCreateContractModal" in actions and "openSupervisorsManagementModal" in actions
    assert "isPlatform" not in actions.split("else if")[0], (
        "creating a contract or a supervisor must not depend on account type"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Nothing on the vendor screen is invented
# ─────────────────────────────────────────────────────────────────────────────


def test_no_fabricated_company_or_metric_survives():
    """Scoped to the vendor renderer: a default value in a create form is a
    starting point the user edits, not a number presented as the customer's."""
    source = CAPACITY.read_text(encoding="utf-8")
    start = source.index("async function renderPlatformOperators(")
    end = source.index("export async function openAddOperatorModal(")
    code = re.sub(r"//[^\n]*", "", source[start:end])
    for invented in (
        "عشم اللوجستية", "الرواد لخدمات الميل", "7001928374", "7002847192",
        "98.4%", "98.5%", "|| 48", "|| 12", "opRidersCount * 14", "|| 16.5",
    ):
        assert invented not in code, (
            f"the vendor screen still invents {invented!r} when the API returns nothing"
        )


def test_the_vendor_form_calls_the_api():
    source = CAPACITY.read_text(encoding="utf-8")
    body = source[source.index("export async function openAddOperatorModal("):]
    body = body[: body.index("// MODALS: CREATE CONTRACT")]
    assert "/enterprise/operators/link" in body, "the form must save through the API"
    # Strip comments: the description of the old defect is not the defect.
    code = re.sub(r"//[^\n]*", "", body)
    assert "تم ربط الشركة اللوجستية" not in code.split("api.post")[0], (
        "the form still claims success before calling anything"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Linking a vendor, and refusing to become a tenant-enumeration oracle
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    def account(name, customer_type, capabilities, phone):
        tenant = Tenant(
            name=name, country=Country.SA, plan="PRO", subscription_status="ACTIVE",
            customer_type=customer_type.value,
            capabilities=entitlements.serialize(capabilities),
        )
        db.add(tenant); db.commit(); db.refresh(tenant)
        user = User(
            phone=phone, name=name, role=UserRole.COMPANY_ADMIN, tenant_id=tenant.id,
            is_active=True, password_hash=hash_password("Pass12345!"),
        )
        db.add(user); db.commit(); db.refresh(user)
        return {"tenant": tenant, "user": user, "token": create_token(user)}

    platform = account("Ninja", CustomerType.DELIVERY_PLATFORM,
                       entitlements.PLATFORM_DEFAULTS, "966590000001")
    other_platform = account("HungerStation", CustomerType.DELIVERY_PLATFORM,
                             entitlements.PLATFORM_DEFAULTS, "966590000003")
    vendor = account("Al-Rowad Logistics", CustomerType.LOGISTICS_OPERATOR,
                     entitlements.LOGISTICS_DEFAULTS, "966590000002")

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield {"client": client, "db": db, "platform": platform,
               "vendor": vendor, "other_platform": other_platform}
    app.dependency_overrides.clear()
    db.close()


def _auth(a):
    return {"Authorization": f"Bearer {a['token']}"}


def test_a_source_platform_is_created_on_first_use(env):
    """Linking needs a source_platform_id and nothing exposed one, so the
    endpoint could not be called from a browser at all."""
    res = env["client"].get("/enterprise/source-platforms", headers=_auth(env["platform"]))
    assert res.status_code == 200, res.text
    assert len(res.json()) == 1


def test_a_platform_links_an_existing_company(env):
    res = env["client"].post(
        "/enterprise/operators/link",
        json={"admin_phone": "966590000002"},
        headers=_auth(env["platform"]),
    )
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "Al-Rowad Logistics"
    assert env["db"].query(PlatformOperator).count() == 1


def test_the_same_company_cannot_be_linked_twice(env):
    for _ in range(1):
        env["client"].post("/enterprise/operators/link",
                           json={"admin_phone": "966590000002"}, headers=_auth(env["platform"]))
    again = env["client"].post("/enterprise/operators/link",
                               json={"admin_phone": "966590000002"}, headers=_auth(env["platform"]))
    assert again.status_code == 409


@pytest.mark.parametrize(
    "phone,why",
    [
        ("966000000000", "a phone belonging to nobody"),
        ("966590000003", "another platform, which is not a vendor"),
        ("966590000001", "itself"),
    ],
)
def test_linking_never_reveals_who_is_a_dou_customer(env, phone, why):
    """Every failure answers the same 404, so the endpoint cannot be used to
    discover which companies exist on DOU."""
    res = env["client"].post("/enterprise/operators/link",
                             json={"admin_phone": phone}, headers=_auth(env["platform"]))
    assert res.status_code == 404, f"{why} leaked a distinguishable status"


def test_an_account_without_the_capability_cannot_link(env):
    res = env["client"].post("/enterprise/operators/link",
                             json={"admin_phone": "966590000001"}, headers=_auth(env["vendor"]))
    assert res.status_code == 403
    assert "MANAGE_OPERATORS" in res.text
