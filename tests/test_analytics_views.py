"""The analytics views must exist, be readable, and carry a tenant column.

Metabase queries these views instead of the operational tables, so two things
have to be true of every one of them: it runs, and it can be filtered to a
single tenant. Without tenant_id a view cannot be locked by the embed token and
becomes a cross-tenant leak the moment a dashboard is built on it.

The file previously shipped written against a schema that did not exist -- seven
of nine views failed on the first SELECT, referencing columns like `cb.name`,
`a.tenant_id` and `dl.delivery_fee`. Nothing caught it because nothing ever
loaded the file.
"""

import pytest
from sqlalchemy import create_engine, inspect, text

from app.analytics_views import SQL_FILE, create_analytics_views, view_names
from app.database import Base
from app.models import entities  # noqa: F401 - register metadata
from app.models import intelligence  # noqa: F401
from app.models import salary  # noqa: F401

EXPECTED = {
    "analytics_workforce",
    "analytics_attendance",
    "analytics_rider_performance",
    "analytics_payroll",
    "analytics_documents",
    "analytics_vehicles",
    "analytics_import_health",
    "analytics_reconciliation",
    "analytics_platform_facts",
}


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    path = tmp_path_factory.mktemp("views") / "views.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    create_analytics_views(engine)
    return engine


def test_every_expected_view_is_created(engine):
    created = {v for v in inspect(engine).get_view_names() if v.startswith("analytics_")}
    assert EXPECTED <= created, f"missing: {sorted(EXPECTED - created)}"


@pytest.mark.parametrize("view", sorted(EXPECTED))
def test_view_is_queryable(engine, view):
    """SQLite accepts a view referencing a missing column and only fails on
    SELECT, so creating one proves nothing. This selects."""
    with engine.connect() as connection:
        connection.execute(text(f"SELECT * FROM {view} LIMIT 5")).fetchall()


@pytest.mark.parametrize("view", sorted(EXPECTED))
def test_view_exposes_tenant_id(engine, view):
    with engine.connect() as connection:
        columns = list(connection.execute(text(f"SELECT * FROM {view} LIMIT 0")).keys())
    assert "tenant_id" in columns, (
        f"{view} has no tenant_id, so the embed token cannot lock it to one "
        "customer and any dashboard over it leaks across tenants"
    )


def test_payroll_view_reads_snapshots_rather_than_recomputing():
    """A dashboard that derives pay in SQL will drift from the payroll engine.

    Reading finalized snapshots is what keeps BI and the payroll screen in
    agreement about what a rider was actually paid.
    """
    sql = SQL_FILE.read_text(encoding="utf-8")
    block = sql[sql.index("CREATE VIEW analytics_payroll") :]
    block = block[: block.index(";")]
    assert "payroll_snapshots" in block
    for recomputed in ("daily_logs", "bonus_plans", "payroll_adjustments"):
        assert recomputed not in block, (
            f"analytics_payroll joins {recomputed}, which recomputes pay in SQL "
            "instead of reading what was paid"
        )


def test_no_sqlite_only_functions_leak_into_the_shared_sql():
    """Production is PostgreSQL. Dialect differences belong behind the
    placeholders the loader substitutes, not in the shared file."""
    sql = SQL_FILE.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    for sqlite_only in ("julianday(", "strftime(", "IF NOT EXISTS"):
        assert sqlite_only not in body, (
            f"{sqlite_only!r} is SQLite-only and would fail on PostgreSQL"
        )


def test_loader_reports_the_views_the_file_declares():
    assert set(view_names()) == EXPECTED
