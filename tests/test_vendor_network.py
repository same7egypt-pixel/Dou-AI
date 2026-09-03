"""The vendor network works end to end: transfer, health, portal, entitlement.

Six defects, all confirmed by calling the running API before any of this was
written:

A rider could be assigned to a vendor exactly once, ever. The overlap check in
POST /rider/assign rejected any open ACTIVE assignment starting on or before the
new date — which is what a rider already working for a vendor has — so every
transfer answered 409 and the "end the current assignment" branch below it was
unreachable. `status="TRANSFERRED"` was in the model and nothing wrote it.

GET /operators/health returned three tenant-level totals and no `operators` key.
The vendor screen reads `healthData.operators` and looks up `active_couriers`
and the portal state on each row, so every per-vendor figure rendered as a dash
however much real data the platform had.

The portal state was not readable anywhere, so a screen could not show whether a
vendor's portal was open, and POST /operators/{id}/portal was unreachable from
the browser.

"مناديب شركات 3PL" was `total riders − freelancers`: a guess presented as a
count, when RiderAssignment holds the answer.

Rider assignment, its history and network health were gated on
OPERATOR_SETTLEMENTS, so a platform that bought vendor management without B2B
settlement could not move a rider between its own vendors.

And every 404 message the backend wrote was thrown away: `_wants_html` treated
`*/*` — what fetch sends when no Accept header is set, which the api client does
not set — as a page navigation, so an API 404 came back as an HTML error page,
JSON.parse failed on it, and the operator was shown "HTTP 404".
"""

import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.entities import (
    Country,
    Courier,
    CourierType,
    CustomerType,
    PlatformOperator,
    RiderAssignment,
    SourcePlatform,
    Tenant,
    User,
    UserRole,
)
from app.routers.auth import create_token, hash_password
from app.services import entitlements

ROOT = Path(__file__).resolve().parents[1]
CAPACITY = ROOT / "frontend-v2" / "fleet" / "views" / "capacity.js"


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    def account(name, customer_type, capabilities, phone):
        tenant = Tenant(
            name=name,
            country=Country.SA,
            plan="PRO",
            subscription_status="ACTIVE",
            customer_type=customer_type.value,
            capabilities=entitlements.serialize(capabilities),
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        user = User(
            phone=phone,
            name=name,
            role=UserRole.COMPANY_ADMIN,
            tenant_id=tenant.id,
            is_active=True,
            password_hash=hash_password("Pass12345!"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"tenant": tenant, "user": user, "token": create_token(user)}

    platform = account(
        "Ninja", CustomerType.DELIVERY_PLATFORM, entitlements.PLATFORM_DEFAULTS,
        "966590000001",
    )
    vendor_a = account(
        "DOU Fleet Riyadh", CustomerType.LOGISTICS_OPERATOR,
        entitlements.LOGISTICS_DEFAULTS, "966590000002",
    )
    vendor_b = account(
        "Speed Jeddah", CustomerType.LOGISTICS_OPERATOR,
        entitlements.LOGISTICS_DEFAULTS, "966590000004",
    )

    source = SourcePlatform(
        tenant_id=platform["tenant"].id, code="NINJA", name_ar="نينجا"
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    links = {}
    for key, vendor in (("a", vendor_a), ("b", vendor_b)):
        link = PlatformOperator(
            tenant_id=platform["tenant"].id,
            source_platform_id=source.id,
            operator_tenant_id=vendor["tenant"].id,
            relationship_type="OPERATOR",
            is_active=True,
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        links[key] = link

    rider = Courier(
        tenant_id=platform["tenant"].id,
        name="سائق تجريبي",
        phone="966599000001",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    yield {
        "db": db, "client": client, "platform": platform,
        "vendor_a": vendor_a, "vendor_b": vendor_b,
        "links": links, "rider": rider, "source": source,
        "account": account,
        "H": {"Authorization": f"Bearer {platform['token']}"},
    }
    app.dependency_overrides.clear()
    db.close()


def _assign(env, vendor, when, token=None):
    return env["client"].post(
        f"/analytics/operators/rider/assign?courier_id={env['rider'].id}"
        f"&operator_id={vendor['tenant'].id}&effective_from={when}",
        headers={"Authorization": f"Bearer {token or env['platform']['token']}"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# A rider can move between vendors
# ─────────────────────────────────────────────────────────────────────────────


def test_a_rider_can_be_moved_from_one_vendor_to_the_next(env):
    """The transfer was the one case the endpoint could not do."""
    first = _assign(env, env["vendor_a"], "2026-01-01")
    assert first.status_code == 200, first.text

    moved = _assign(env, env["vendor_b"], "2026-03-01")
    assert moved.status_code == 200, (
        "moving a rider to another vendor still answers "
        f"{moved.status_code}: {moved.text}"
    )
    assert moved.json()["superseded_assignment_id"] == first.json()["id"]


def test_the_superseded_assignment_is_closed_and_marked_transferred(env):
    """No day may be claimed by two vendors, and the move must be visible."""
    _assign(env, env["vendor_a"], "2026-01-01")
    _assign(env, env["vendor_b"], "2026-03-01")

    rows = (
        env["db"].query(RiderAssignment)
        .order_by(RiderAssignment.effective_from)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].status == "TRANSFERRED", (
        "the model documents TRANSFERRED and nothing ever wrote it"
    )
    assert rows[0].effective_to == date(2026, 3, 1)
    assert rows[1].status == "ACTIVE" and rows[1].effective_to is None


def test_backdating_under_a_live_assignment_is_refused(env):
    """A record starting after the new date would be contradicted, not superseded."""
    _assign(env, env["vendor_a"], "2026-03-01")
    clash = _assign(env, env["vendor_b"], "2026-01-01")
    assert clash.status_code == 409
    assert "2026-03-01" in clash.json()["detail"]


def test_reassigning_to_the_same_vendor_is_refused(env):
    _assign(env, env["vendor_a"], "2026-01-01")
    again = _assign(env, env["vendor_a"], "2026-06-01")
    assert again.status_code == 409
    assert "مُسند بالفعل" in again.json()["detail"]


def test_the_history_names_the_vendor(env):
    _assign(env, env["vendor_a"], "2026-01-01")
    _assign(env, env["vendor_b"], "2026-03-01")
    body = env["client"].get(
        f"/analytics/operators/rider/{env['rider'].id}/history", headers=env["H"]
    ).json()
    names = [a["operator_name"] for a in body["assignments"]]
    assert names == ["Speed Jeddah", "DOU Fleet Riyadh"], (
        "the screen would have to resolve tenant ids itself"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Health carries a row per vendor
# ─────────────────────────────────────────────────────────────────────────────


def test_health_returns_the_per_vendor_rows_the_screen_reads(env):
    _assign(env, env["vendor_a"], "2026-01-01")
    body = env["client"].get("/analytics/operators/health", headers=env["H"]).json()

    assert "operators" in body, (
        "the vendor screen reads healthData.operators; without it every "
        "per-vendor figure renders as a dash"
    )
    rows = {r["operator_id"]: r for r in body["operators"]}
    assert set(rows) == {env["links"]["a"].id, env["links"]["b"].id}
    assert rows[env["links"]["a"].id]["active_couriers"] == 1
    assert rows[env["links"]["b"].id]["active_couriers"] == 0
    assert rows[env["links"]["a"].id]["name"] == "DOU Fleet Riyadh"


def test_health_counts_assigned_riders_rather_than_guessing_from_type(env):
    """`total riders − freelancers` was a guess presented as a count."""
    before = env["client"].get("/analytics/operators/health", headers=env["H"]).json()
    assert before["assigned_riders"] == 0
    assert before["riders_without_assignment"] == 1

    _assign(env, env["vendor_a"], "2026-01-01")

    after = env["client"].get("/analytics/operators/health", headers=env["H"]).json()
    assert after["assigned_riders"] == 1
    assert after["riders_without_assignment"] == 0


def test_a_transferred_rider_is_counted_once_not_twice(env):
    _assign(env, env["vendor_a"], "2026-01-01")
    _assign(env, env["vendor_b"], "2026-03-01")
    body = env["client"].get("/analytics/operators/health", headers=env["H"]).json()
    assert body["assigned_riders"] == 1
    rows = {r["operator_id"]: r for r in body["operators"]}
    assert rows[env["links"]["a"].id]["active_couriers"] == 0
    assert rows[env["links"]["b"].id]["active_couriers"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# The portal is readable and switchable
# ─────────────────────────────────────────────────────────────────────────────


def test_the_portal_state_is_readable(env):
    """A screen cannot offer to open or close what it cannot see."""
    paying = env["account"](
        "Jahez", CustomerType.DELIVERY_PLATFORM,
        tuple(entitlements.PLATFORM_DEFAULTS) + (entitlements.VENDOR_PORTAL,),
        "966590000007",
    )
    db = env["db"]
    source = SourcePlatform(
        tenant_id=paying["tenant"].id, code="JAHEZ", name_ar="جاهز"
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    link = PlatformOperator(
        tenant_id=paying["tenant"].id,
        source_platform_id=source.id,
        operator_tenant_id=env["vendor_a"]["tenant"].id,
        is_active=True,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    headers = {"Authorization": f"Bearer {paying['token']}"}
    health = env["client"].get("/analytics/operators/health", headers=headers).json()
    assert health["operators"][0]["portal"] == "CLOSED"

    opened = env["client"].post(
        f"/enterprise/operators/{link.id}/portal", json={"enabled": True},
        headers=headers,
    )
    assert opened.status_code == 200, opened.text
    health = env["client"].get("/analytics/operators/health", headers=headers).json()
    assert health["operators"][0]["portal"] == "OPEN"

    env["client"].post(
        f"/enterprise/operators/{link.id}/portal", json={"enabled": False},
        headers=headers,
    )
    health = env["client"].get("/analytics/operators/health", headers=headers).json()
    assert health["operators"][0]["portal"] == "CLOSED"


def test_the_portal_stays_a_paid_add_on(env):
    """A platform that has not bought it is told so, not silently granted it."""
    refused = env["client"].post(
        f"/enterprise/operators/{env['links']['a'].id}/portal",
        json={"enabled": True}, headers=env["H"],
    )
    assert refused.status_code == 402


# ─────────────────────────────────────────────────────────────────────────────
# The network is gated on managing the network, not on settling with it
# ─────────────────────────────────────────────────────────────────────────────


def test_managing_the_network_does_not_require_buying_settlements(env):
    caps = [
        c for c in entitlements.PLATFORM_DEFAULTS
        if c != "OPERATOR_SETTLEMENTS"
    ]
    lean = env["account"](
        "Marsool", CustomerType.DELIVERY_PLATFORM, caps, "966590000008"
    )
    db = env["db"]
    source = SourcePlatform(
        tenant_id=lean["tenant"].id, code="MARSOOL", name_ar="مرسول"
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    db.add(PlatformOperator(
        tenant_id=lean["tenant"].id,
        source_platform_id=source.id,
        operator_tenant_id=env["vendor_a"]["tenant"].id,
        is_active=True,
    ))
    rider = Courier(
        tenant_id=lean["tenant"].id, name="مندوب مرسول", phone="966599000009",
        courier_type=CourierType.COMPANY, country=Country.SA,
        employment_status="ACTIVE",
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)

    headers = {"Authorization": f"Bearer {lean['token']}"}
    assert env["client"].get(
        "/analytics/operators/health", headers=headers
    ).status_code == 200
    assigned = env["client"].post(
        f"/analytics/operators/rider/assign?courier_id={rider.id}"
        f"&operator_id={env['vendor_a']['tenant'].id}&effective_from=2026-01-01",
        headers=headers,
    )
    assert assigned.status_code == 200, (
        "assigning a rider to a vendor is an operational act; it was gated on "
        f"OPERATOR_SETTLEMENTS: {assigned.text}"
    )

    # And settlements themselves stay behind their own capability.
    assert env["client"].get(
        "/analytics/operators/settlements", headers=headers
    ).status_code == 403


def test_a_logistics_account_cannot_read_the_vendor_network(env):
    headers = {"Authorization": f"Bearer {env['vendor_a']['token']}"}
    refused = env["client"].get("/analytics/operators/health", headers=headers)
    assert refused.status_code == 403
    assert "MANAGE_OPERATORS" in refused.json()["detail"]


def test_a_rider_cannot_be_assigned_to_another_platforms_vendor(env):
    other = env["account"](
        "HungerStation", CustomerType.DELIVERY_PLATFORM,
        entitlements.PLATFORM_DEFAULTS, "966590000010",
    )
    refused = _assign(env, env["vendor_a"], "2026-01-01", token=other["token"])
    assert refused.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# A 404 keeps the sentence the endpoint wrote
# ─────────────────────────────────────────────────────────────────────────────


def test_an_api_404_answers_json_with_its_own_message(env):
    """`*/*` is what fetch sends, not what a browser navigation sends."""
    missing = env["client"].get(
        "/analytics/operators/settlement/999999",
        headers={**env["H"], "Accept": "*/*"},
    )
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json"), (
        "an API 404 came back as an HTML error page, so JSON.parse failed and "
        "the operator was shown 'HTTP 404' instead of the endpoint's sentence"
    )
    assert missing.json()["detail"] != "Not Found"


def test_a_browser_navigation_still_gets_the_error_page(env):
    page = env["client"].get(
        "/some/unknown/path",
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    assert page.status_code == 404
    assert page.headers["content-type"].startswith("text/html")


# ─────────────────────────────────────────────────────────────────────────────
# The screen renders what the API returns
# ─────────────────────────────────────────────────────────────────────────────


def _vendor_screen_code() -> str:
    """The card renderer alone.

    Slicing to openAddOperatorModal would swallow the togglePortal and
    openAssignRiderModal definitions that sit between them, so "the screen
    offers the portal" would pass on the strength of the function existing
    while the button that calls it was gone — verified: that mutation did not
    fail until this boundary moved.
    """
    source = CAPACITY.read_text(encoding="utf-8")
    start = source.index("async function renderPlatformOperators(")
    end = source.index("async function togglePortal(")
    return re.sub(r"//[^\n]*", "", source[start:end])


def test_the_screen_stops_guessing_the_vendor_rider_count():
    code = _vendor_screen_code()
    assert "totalCouriers - directFreelancers" not in code, (
        "'مناديب شركات 3PL' was total riders minus freelancers — a guess, when "
        "RiderAssignment holds the answer"
    )
    assert "assigned_riders" in code


def test_the_screen_drops_the_fields_the_api_never_returns():
    """cr_number, cities and rate_per_order were the mock's vocabulary."""
    code = _vendor_screen_code()
    for dead in ("op.cr_number", "op.cities", "op.rate_per_order",
                 "h.sla_fulfillment", "h.daily_orders"):
        assert dead not in code, (
            f"{dead} is never returned by any endpoint; it can only render a dash"
        )


def test_the_screen_offers_the_portal_and_the_assignment():
    code = _vendor_screen_code()
    assert "togglePortal(" in code and "openAssignRiderModal(" in code, (
        "the platform pays for VENDOR_PORTAL and could not reach it from a browser"
    )


def test_the_portal_refusal_is_explained_not_shown_as_a_code():
    source = CAPACITY.read_text(encoding="utf-8")
    body = source[source.index("async function togglePortal("):]
    body = body[: body.index("async function openAssignRiderModal(")]
    assert "err.status === 402" in body and "إضافة مدفوعة" in body


def test_the_assignment_modal_saves_through_the_api():
    source = CAPACITY.read_text(encoding="utf-8")
    body = source[source.index("async function openAssignRiderModal("):]
    body = body[: body.index("export async function openAddOperatorModal(")]
    code = re.sub(r"//[^\n]*", "", body)
    assert "/analytics/operators/rider/assign" in code
    assert "/history" in code, "the person assigning must see where the rider is now"
    assert "تم إسناد المندوب" not in code.split("api.post")[0], (
        "the form must not claim success before calling anything"
    )
