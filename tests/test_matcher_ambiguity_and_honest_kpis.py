"""Two identifiers that collide must not be resolved by luck, and no endpoint
may assert a number it did not measure.

An identity mapping belongs to a source platform. When a sheet's platform could
not be identified — SMART_DETECTED, or a format nobody has taught the detector —
the matcher skipped the platform filter and took `.first()` among every mapping
sharing that raw id. Two platforms both numbering their riders from 1 is not
hypothetical, and the result is a delivery credited to the wrong person and paid
to them. This is the third place the same class of defect appeared: the
ingestion idempotency check and the Ninja live path were the first two.

And the dashboards catalogue shipped a `kpis` array on every entry with values
written by hand — "نسبة الحضور 94%", "معدل الإنجاز 98.2%". The tab is hidden
until Metabase is hosted, so nobody had seen them, which is why they survived an
audit that named them and a cleanup that claimed to have removed them (it edited
the frontend file of the same name).
"""

import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import entities as ent
from app.services.performance_imports import _resolve_courier

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    tenant = ent.Tenant(name="Logistics Pro", country=ent.Country.SA, plan="PRO")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    def source(code, name):
        row = ent.SourcePlatform(
            tenant_id=tenant.id, code=code, name_ar=name, is_active=True
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def rider(name, phone):
        row = ent.Courier(
            tenant_id=tenant.id, name=name, phone=phone,
            courier_type=ent.CourierType.COMPANY, country=ent.Country.SA,
            employment_status="ACTIVE",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def mapping(platform, source_rider_id, courier):
        db.add(ent.RiderIdentityMapping(
            tenant_id=tenant.id, source_platform_id=platform.id,
            source_rider_id=source_rider_id, courier_id=courier.id,
            match_method="MANUAL", confidence=1.0, status="ACTIVE",
            effective_from=date(2026, 1, 1),
        ))
        db.commit()

    yield {
        "db": db, "tenant": tenant,
        "source": source, "rider": rider, "mapping": mapping,
    }
    db.close()


# ─────────────────────────────────────────────────────────────────────────────
# A colliding id is reported, not guessed
# ─────────────────────────────────────────────────────────────────────────────


def test_an_unidentified_sheet_does_not_guess_between_two_platforms(env):
    """The row goes to the unmatched list, where an operator names it."""
    hs = env["source"]("HUNGERSTATION", "هنقرستيشن")
    ninja = env["source"]("NINJA", "نينجا")
    ahmed = env["rider"]("أحمد", "966599000001")
    khaled = env["rider"]("خالد", "966599000002")
    env["mapping"](hs, "1001", ahmed)
    env["mapping"](ninja, "1001", khaled)

    for unknown in ("SMART_DETECTED", "DOU_GENERIC", "AUTO", None):
        resolved = _resolve_courier(
            env["db"], env["tenant"].id, "1001", source_platform_code=unknown
        )
        assert resolved is None, (
            f"with the platform unknown ({unknown!r}) the matcher picked "
            f"{resolved.name if resolved else None} out of two candidates — "
            "one of them would be paid for the other's deliveries"
        )


def test_a_known_platform_still_resolves_its_own_rider(env):
    """Refusing an ambiguous id must not break the identified case."""
    hs = env["source"]("HUNGERSTATION", "هنقرستيشن")
    ninja = env["source"]("NINJA", "نينجا")
    ahmed = env["rider"]("أحمد", "966599000001")
    khaled = env["rider"]("خالد", "966599000002")
    env["mapping"](hs, "1001", ahmed)
    env["mapping"](ninja, "1001", khaled)

    assert _resolve_courier(
        env["db"], env["tenant"].id, "1001", source_platform_code="HUNGERSTATION"
    ).id == ahmed.id
    assert _resolve_courier(
        env["db"], env["tenant"].id, "1001", source_platform_code="NINJA"
    ).id == khaled.id


def test_an_unambiguous_id_still_resolves_without_a_platform(env):
    """Only a genuine collision is refused; one mapping is still a match."""
    hs = env["source"]("HUNGERSTATION", "هنقرستيشن")
    ahmed = env["rider"]("أحمد", "966599000001")
    env["mapping"](hs, "2002", ahmed)

    assert _resolve_courier(
        env["db"], env["tenant"].id, "2002", source_platform_code="SMART_DETECTED"
    ).id == ahmed.id


def test_two_mappings_pointing_at_one_rider_are_not_a_collision(env):
    """The same person registered on two platforms is not ambiguous."""
    hs = env["source"]("HUNGERSTATION", "هنقرستيشن")
    ninja = env["source"]("NINJA", "نينجا")
    ahmed = env["rider"]("أحمد", "966599000001")
    env["mapping"](hs, "3003", ahmed)
    env["mapping"](ninja, "3003", ahmed)

    assert _resolve_courier(
        env["db"], env["tenant"].id, "3003", source_platform_code="SMART_DETECTED"
    ).id == ahmed.id


def test_a_rider_is_never_matched_across_a_tenant_boundary(env):
    """The oldest rule in this codebase."""
    db = env["db"]
    hs = env["source"]("HUNGERSTATION", "هنقرستيشن")
    ahmed = env["rider"]("أحمد", "966599000001")
    env["mapping"](hs, "4004", ahmed)

    other = ent.Tenant(name="Another Co", country=ent.Country.SA, plan="PRO")
    db.add(other)
    db.commit()
    db.refresh(other)

    assert _resolve_courier(
        db, other.id, "4004", source_platform_code="HUNGERSTATION"
    ) is None


def test_a_mapping_pointing_outside_its_tenant_resolves_to_nothing(env):
    """The `courier.tenant_id == tenant_id` check after the lookup exists for a
    mapping row whose courier_id points at another tenant's rider — a shape the
    mapping query's own tenant filter cannot catch, because the *mapping* is in
    the right tenant and only its target is not.

    Asserting the outcome through the normal path was not enough: removing that
    check left the test passing, because the query filter alone already blocks
    the ordinary case."""
    db = env["db"]
    hs = env["source"]("HUNGERSTATION", "هنقرستيشن")

    other = ent.Tenant(name="Another Co", country=ent.Country.SA, plan="PRO")
    db.add(other)
    db.commit()
    db.refresh(other)
    stranger = ent.Courier(
        tenant_id=other.id, name="مندوب شركة أخرى", phone="966599009999",
        courier_type=ent.CourierType.COMPANY, country=ent.Country.SA,
        employment_status="ACTIVE",
    )
    db.add(stranger)
    db.commit()
    db.refresh(stranger)

    # A mapping owned by our tenant that points at the other tenant's rider.
    db.add(ent.RiderIdentityMapping(
        tenant_id=env["tenant"].id, source_platform_id=hs.id,
        source_rider_id="5005", courier_id=stranger.id,
        match_method="MANUAL", confidence=1.0, status="ACTIVE",
        effective_from=date(2026, 1, 1),
    ))
    db.commit()

    assert _resolve_courier(
        db, env["tenant"].id, "5005", source_platform_code="HUNGERSTATION"
    ) is None, "a mapping resolved to a rider belonging to another company"


# ─────────────────────────────────────────────────────────────────────────────
# No endpoint asserts a number it did not measure
# ─────────────────────────────────────────────────────────────────────────────


def test_the_dashboard_catalogue_states_no_measurements():
    """It lists what exists; Metabase measures. A hardcoded percentage here
    discredits every real number shown beside it."""
    source = (ROOT / "app" / "routers" / "reports.py").read_text(encoding="utf-8")
    catalogue = source[source.index("    dashboards = ["):]
    catalogue = catalogue[: catalogue.index("\n    ]")]
    code = re.sub(r"#[^\n]*", "", catalogue)

    assert '"kpis"' not in code, (
        "the dashboard catalogue carries hand-written measurements again"
    )
    invented = re.findall(r'"value":\s*"[^"]*[0-9][^"]*"', code)
    assert not invented, f"hardcoded metric values: {invented[:5]}"


def test_the_reports_screen_does_not_invent_a_rider_count():
    """`|| 8` meant a company with no riders read "8 سائق" — a number the
    customer can disprove in one click."""
    source = (ROOT / "frontend-v2" / "fleet" / "views" / "reports.js").read_text(
        encoding="utf-8"
    )
    code = re.sub(r"//[^\n]*", "", source)
    for invented in ("|| 8", "|| 750", "94.2", "98.6"):
        assert invented not in code, (
            f"the reports screen still falls back to {invented!r}"
        )
