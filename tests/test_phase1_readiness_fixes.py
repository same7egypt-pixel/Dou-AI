"""The Phase 1 audit findings, each pinned so it cannot come back.

Every test here names a defect that a real customer would have hit. They are
product defects rather than code defects, which is why 685 passing tests did not
catch any of them.
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
from app.models.entities import (
    ContractBranch,
    Country,
    Courier,
    CourierType,
    CourierDocumentSubmission,
    CustomerType,
    Document,
    GeoCity,
    GeoCountry,
    Tenant,
    User,
    UserRole,
)
from app.routers.auth import create_token, hash_password
from app.services import entitlements
from app.services.operating_structure import require_active_tenant_city

ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────────────────────
# Payroll: one calculation path, on every screen that shows money
# ─────────────────────────────────────────────────────────────────────────────

RIDER360 = ROOT / "frontend-v2" / "fleet" / "views" / "rider360.js"
PAYROLL_VIEW = ROOT / "frontend-v2" / "fleet" / "views" / "payroll.js"


def test_no_screen_reads_the_parallel_payroll_ledger():
    """/analytics/payroll/* reads PayrollInputRecord, which the payroll engine
    never writes. Rider 360 showed a rider 0 SAR while the payroll sheet showed
    216 for the same rider and month."""
    for path in ROOT.glob("frontend-v2/**/*.js"):
        source = path.read_text(encoding="utf-8")
        # Strip comments so the explanation of the defect is not the defect.
        code = re.sub(r"//[^\n]*", "", source)
        assert "/analytics/payroll" not in code, (
            f"{path.relative_to(ROOT)} reads the parallel payroll ledger; "
            "payroll has exactly one calculation path (CLAUDE.md)"
        )


def test_rider360_payroll_uses_the_rider_statement():
    source = RIDER360.read_text(encoding="utf-8")
    assert "/hr/payroll/rider/" in source, (
        "Rider 360's payroll tab must read the same engine as the payroll sheet"
    )


def test_the_payroll_screen_does_not_fall_back_to_another_source():
    """A failure rendered as zeros looks like an answer."""
    source = PAYROLL_VIEW.read_text(encoding="utf-8")
    body = source[source.index("async function renderPayrollLedger") :][:1500]
    assert ".catch(" not in body.split("api.get(`/hr/payroll")[1][:200], (
        "the payroll ledger must surface a failure, not silently swap data source"
    )


# ─────────────────────────────────────────────────────────────────────────────
# A branch with no city must explain itself, not return a 500
# ─────────────────────────────────────────────────────────────────────────────


def test_a_branch_without_a_city_raises_a_readable_error(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    with pytest.raises(ValueError) as exc:
        require_active_tenant_city(db, 1, None)
    assert "مدينة" in str(exc.value), "the operator must be told what to fix"
    db.close()


# ─────────────────────────────────────────────────────────────────────────────
# DOU AI is not a way around an entitlement
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    country = GeoCountry(name="السعودية", code="SA", active=True)
    db.add(country)
    db.commit()
    db.refresh(country)
    city = GeoCity(country_id=country.id, name="الرياض", active=True)
    db.add(city)
    db.commit()

    def account(name, customer_type, capabilities, phone, role=UserRole.COMPANY_ADMIN):
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
            role=role,
            tenant_id=tenant.id,
            is_active=True,
            password_hash=hash_password("Pass12345!"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"tenant": tenant, "user": user, "token": create_token(user)}

    platform = account(
        "Ninja", CustomerType.DELIVERY_PLATFORM, entitlements.PLATFORM_DEFAULTS, "966590000001"
    )
    logistics = account(
        "Al-Rowad", CustomerType.LOGISTICS_OPERATOR, entitlements.LOGISTICS_DEFAULTS, "966590000002"
    )

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield {"client": client, "db": db, "platform": platform, "logistics": logistics}
    app.dependency_overrides.clear()
    db.close()


def _auth(account):
    return {"Authorization": f"Bearer {account['token']}"}


def test_dou_ai_refuses_a_financial_report_the_account_has_not_bought(env):
    """The assistant answered a payroll question for an account that /hr/payroll
    refuses with 403, because it only ever checked tenant and role."""
    res = env["client"].post(
        "/ai/chat",
        json={"question": "نزل لي شيت الرواتب والخصومات"},
        headers=_auth(env["platform"]),
    )
    assert res.status_code == 403, (
        f"DOU AI served a payroll report to a platform account ({res.status_code}); "
        "the assistant must not be a way around a capability guard"
    )
    assert "RIDER_PAYROLL" in res.text


def test_dou_ai_still_answers_what_the_account_is_entitled_to(env):
    res = env["client"].post(
        "/ai/chat",
        json={"question": "كم عدد السائقين النشطين؟"},
        headers=_auth(env["platform"]),
    )
    assert res.status_code == 200, res.text


def test_dou_ai_serves_payroll_to_an_account_that_bought_it(env):
    res = env["client"].post(
        "/ai/chat",
        json={"question": "نزل لي شيت الرواتب والخصومات"},
        headers=_auth(env["logistics"]),
    )
    assert res.status_code == 200, res.text


# ─────────────────────────────────────────────────────────────────────────────
# Documents: the company can file one, and approving it moves the gate
# ─────────────────────────────────────────────────────────────────────────────

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def _rider(env, account):
    rider = Courier(
        tenant_id=account["tenant"].id,
        name="مندوب الاختبار",
        phone="966577000001",
        courier_type=CourierType.COMPANY,
        country=Country.SA,
        employment_status="ACTIVE",
    )
    env["db"].add(rider)
    env["db"].commit()
    env["db"].refresh(rider)
    return rider


def test_the_company_can_file_a_document_for_a_rider(env):
    """Only the rider could put a file into the system, from the phone app."""
    rider = _rider(env, env["logistics"])
    res = env["client"].post(
        f"/hr/couriers/{rider.id}/documents",
        json={"document_type": "IQAMA", "filename": "iqama.png",
              "mime_type": "image/png", "file_data": PNG},
        headers=_auth(env["logistics"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "PENDING"


def test_a_filed_document_is_visible_on_the_rider(env):
    """Rider 360 read a metadata-only store that nothing writes to, so documents
    uploaded from the app were invisible and could never be reviewed."""
    rider = _rider(env, env["logistics"])
    env["client"].post(
        f"/hr/couriers/{rider.id}/documents",
        json={"document_type": "IQAMA", "filename": "iqama.png",
              "mime_type": "image/png", "file_data": PNG},
        headers=_auth(env["logistics"]),
    )
    res = env["client"].get(
        f"/hr/couriers/{rider.id}/documents", headers=_auth(env["logistics"])
    )
    assert res.status_code == 200
    assert [d["document_type"] for d in res.json()] == ["IQAMA"]


def test_approving_a_document_clears_the_readiness_gate(env):
    """Approving a document left the rider on documents:MISSING forever, so no
    sequence of actions in the product could make a rider READY."""
    rider = _rider(env, env["logistics"])
    env["client"].post(
        f"/hr/couriers/{rider.id}/documents",
        json={"document_type": "IQAMA", "filename": "iqama.png",
              "mime_type": "image/png", "file_data": PNG},
        headers=_auth(env["logistics"]),
    )
    doc_id = env["client"].get(
        f"/hr/couriers/{rider.id}/documents", headers=_auth(env["logistics"])
    ).json()[0]["id"]

    before = env["client"].get(f"/readiness/{rider.id}", headers=_auth(env["logistics"]))
    assert before.json()["dimensions"]["documents"] == "MISSING"

    decided = env["client"].post(
        f"/hr/documents/{doc_id}/decide",
        json={"action": "approve", "note": "مطابق"},
        headers=_auth(env["logistics"]),
    )
    assert decided.status_code == 200, decided.text

    after = env["client"].get(f"/readiness/{rider.id}", headers=_auth(env["logistics"]))
    assert after.json()["dimensions"]["documents"] == "VERIFIED", (
        "an approved document must reach the gate that decides whether the rider "
        f"may work: {after.json()['dimensions']}"
    )
    assert not any(b.startswith("documents:") for b in after.json()["blockers"])
    # And it is recorded in the store readiness is computed from.
    assert env["db"].query(Document).filter(Document.owner_id == rider.id).count() == 1


def test_a_rider_document_stays_inside_its_tenant(env):
    rider = _rider(env, env["logistics"])
    for method, kwargs in (
        ("get", {}),
        ("post", {"json": {"document_type": "IQAMA", "filename": "x.png",
                           "mime_type": "image/png", "file_data": PNG}}),
    ):
        res = getattr(env["client"], method)(
            f"/hr/couriers/{rider.id}/documents",
            headers=_auth(env["platform"]),
            **kwargs,
        )
        assert res.status_code == 404, (
            f"{method.upper()} leaked another tenant's rider ({res.status_code})"
        )


def test_a_rider_cannot_file_documents_for_someone_else(env):
    rider = _rider(env, env["logistics"])
    courier_user = User(
        phone="966577000009", name="مندوب", role=UserRole.COURIER,
        tenant_id=env["logistics"]["tenant"].id, courier_id=rider.id,
        is_active=True, password_hash=hash_password("Pass12345!"),
    )
    env["db"].add(courier_user)
    env["db"].commit()
    res = env["client"].post(
        f"/hr/couriers/{rider.id}/documents",
        json={"document_type": "IQAMA", "filename": "x.png",
              "mime_type": "image/png", "file_data": PNG},
        headers={"Authorization": f"Bearer {create_token(courier_user)}"},
    )
    assert res.status_code == 403


def test_a_document_must_be_a_known_type_and_within_size(env):
    rider = _rider(env, env["logistics"])
    bad_type = env["client"].post(
        f"/hr/couriers/{rider.id}/documents",
        json={"document_type": "ANYTHING", "filename": "x.png",
              "mime_type": "image/png", "file_data": PNG},
        headers=_auth(env["logistics"]),
    )
    assert bad_type.status_code == 400
    not_a_file = env["client"].post(
        f"/hr/couriers/{rider.id}/documents",
        json={"document_type": "IQAMA", "filename": "x.png",
              "mime_type": "image/png", "file_data": "not-a-data-uri"},
        headers=_auth(env["logistics"]),
    )
    assert not_a_file.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Customer-facing errors do not name internal configuration
# ─────────────────────────────────────────────────────────────────────────────


def test_the_analytics_error_does_not_leak_an_env_var_name():
    """Reading the setting by name is fine; showing that name to the customer
    is not — they cannot act on it, and it describes our infrastructure."""
    source = (ROOT / "app" / "routers" / "reports.py").read_text(encoding="utf-8")
    arabic_messages = re.findall(r'"([^"]*[؀-ۿ][^"]*)"', source)
    for message in arabic_messages:
        assert "METABASE" not in message and "SECRET_KEY" not in message, (
            f"a customer-facing message names internal configuration: {message}"
        )


def test_the_supervisor_error_names_where_to_fix_it():
    """The first rider a customer adds hits this, and the branch's supervisor is
    set on a different screen entirely."""
    source = (ROOT / "app" / "services" / "operating_structure.py").read_text(encoding="utf-8")
    message = source[source.index("لا يوجد مشرف مسؤول نشط") :][:400]
    assert "تخطيط السعة" in message and "إضافة فرع" in message, (
        "the error must name the screen that fixes it"
    )


# ─────────────────────────────────────────────────────────────────────────────
# An unconfigured feature is absent, not broken
# ─────────────────────────────────────────────────────────────────────────────


def test_dashboards_report_not_configured_instead_of_failing(env, monkeypatch):
    """The endpoint raised 503 when analytics was not hosted, so every customer
    met a third tab that only ever showed an error. The screen could not tell
    "not set up" from "failed"."""
    # State the precondition rather than inherit it from whatever ran before.
    monkeypatch.setattr(
        "app.routers.reports.METABASE_EMBEDDING_SECRET_KEY", "", raising=False
    )
    res = env["client"].get(
        "/analytics/reports/dashboards", headers=_auth(env["logistics"])
    )
    assert res.status_code == 200, (
        f"an unhosted analytics stack must not surface as a failure: {res.status_code}"
    )
    body = res.json()
    assert body["status"] == "NOT_CONFIGURED"
    assert body["dashboards"] == []


def test_the_reports_screen_hides_the_tab_until_analytics_exists():
    source = (ROOT / "frontend-v2" / "fleet" / "views" / "reports.js").read_text(encoding="utf-8")
    assert "NOT_CONFIGURED" in source, (
        "the reports screen must read the configuration state before rendering "
        "the dashboards tab"
    )
    assert "analyticsReady ?" in source, (
        "the dashboards tab must be conditional, not always rendered"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The account surface, and retiring the screen that used to hold it
# ─────────────────────────────────────────────────────────────────────────────

SETTINGS_VIEW = ROOT / "frontend-v2" / "fleet" / "views" / "settings.js"


def test_the_product_can_manage_its_own_users(env):
    """A company could not add an accountant or an operations user without being
    sent to the retired dashboard: /fleet/users had no caller in this product."""
    assert SETTINGS_VIEW.exists(), "the settings screen must exist"
    source = SETTINGS_VIEW.read_text(encoding="utf-8")
    for call in ("/fleet/users", "/auth/change-password", "/billing/status"):
        assert call in source, f"settings must cover {call}"

    res = env["client"].get("/fleet/users", headers=_auth(env["logistics"]))
    assert res.status_code == 200, res.text


def test_a_company_user_can_be_added_and_removed(env):
    created = env["client"].post(
        "/fleet/users",
        json={"name": "محاسب", "phone": "966596660009",
              "password": "Pass12345!", "role": "ACCOUNTANT"},
        headers=_auth(env["logistics"]),
    )
    assert created.status_code == 200, created.text
    user_id = created.json()["id"]

    listed = env["client"].get("/fleet/users", headers=_auth(env["logistics"])).json()
    assert any(u["id"] == user_id for u in listed)

    removed = env["client"].delete(
        f"/fleet/users/{user_id}", headers=_auth(env["logistics"])
    )
    assert removed.status_code == 200, removed.text


def test_company_users_stay_inside_their_tenant(env):
    """The screen is role-gated in the nav; the data must be tenant-gated here."""
    created = env["client"].post(
        "/fleet/users",
        json={"name": "موظف", "phone": "966596660010",
              "password": "Pass12345!", "role": "VIEWER"},
        headers=_auth(env["logistics"]),
    )
    user_id = created.json()["id"]
    leaked = env["client"].get("/fleet/users", headers=_auth(env["platform"])).json()
    assert not any(u["id"] == user_id for u in leaked), (
        "another tenant's company users were listed"
    )


def test_the_rider_message_loop_has_both_halves():
    """The driver app has a company-messages screen and nothing could write to
    it: sending existed only on the retired dashboard, so the inbox was
    permanently empty."""
    riders = (ROOT / "frontend-v2" / "fleet" / "views" / "riders.js").read_text(encoding="utf-8")
    assert "/hr/broadcast" in riders, "the product must be able to message its riders"
    courier = (ROOT / "static" / "courier.html").read_text(encoding="utf-8")
    assert "/hr/me/messages" in courier, "the rider must still receive them"


def test_rider_requests_can_be_answered():
    """Riders submit self-service requests from the app; the queue that answers
    them existed only on the retired dashboard."""
    needs = (ROOT / "frontend-v2" / "fleet" / "views" / "needsAttention.js").read_text(encoding="utf-8")
    assert "/hr/employee-requests" in needs
    assert "/decide" in needs, "the queue must be able to decide, not only list"


def test_the_retired_screens_redirect_rather_than_break(env):
    """They called endpoints that no longer exist. An old bookmark should land
    on the current product, not on a broken copy of the old one."""
    for path in ("/static/fleet.html", "/static/workforce.html", "/static/supervisor.html"):
        body = (ROOT / path.replace("/static/", "static/")).read_text(encoding="utf-8")
        assert "url=/app" in body and len(body) < 800, (
            f"{path} must be a redirect to /app, not a second dashboard"
        )

    res = env["client"].get("/app/workforce", follow_redirects=False)
    assert res.status_code in (307, 308), res.status_code
    assert res.headers["location"] == "/app"
