"""Create the analytics views Metabase reads from.

The views live in analytics_views.sql rather than in Python so they stay
readable and diffable as SQL. Two things this module handles that the file
cannot:

  * Dialect. Production is PostgreSQL and local development is SQLite, and the
    two disagree on how to replace a view and how to subtract two timestamps.
    Both seams are marked with ``{{...}}`` placeholders in the SQL.

  * Idempotency. Views are dropped and recreated on every run, so editing the
    SQL file and redeploying is enough to publish the change. Nothing depends on
    a view's identity, only on its name and columns.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

SQL_FILE = Path(__file__).resolve().parent.parent / "analytics_views.sql"

# Hours between two timestamps, per dialect.
_HOURS_BETWEEN = {
    "postgresql": "ROUND(CAST(EXTRACT(EPOCH FROM ({end} - {start})) / 3600.0 AS numeric), 2)",
    "sqlite": "ROUND((julianday({end}) - julianday({start})) * 24, 2)",
}

_PLACEHOLDER = re.compile(r"\{\{HOURS_BETWEEN:([^:}]+):([^}]+)\}\}")
_VIEW_NAME = re.compile(r"CREATE\s+VIEW\s+(\w+)\s+AS", re.IGNORECASE)


def _render(sql: str, dialect: str) -> str:
    template = _HOURS_BETWEEN.get(dialect)
    if template is None:
        raise RuntimeError(f"analytics views do not support dialect {dialect!r}")
    return _PLACEHOLDER.sub(
        lambda m: template.format(start=m.group(1), end=m.group(2)), sql
    )


def view_names(sql: str | None = None) -> list[str]:
    return _VIEW_NAME.findall(sql if sql is not None else SQL_FILE.read_text(encoding="utf-8"))


def create_analytics_views(engine: Engine) -> list[str]:
    """Drop and recreate every analytics view. Returns the names created."""
    dialect = engine.dialect.name
    rendered = _render(SQL_FILE.read_text(encoding="utf-8"), dialect)
    # Strip line comments before splitting: prose containing a semicolon would
    # otherwise cut a statement in half.
    body = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [
        block.strip() for block in body.split(";") if "CREATE VIEW" in block.upper()
    ]

    created: list[str] = []
    with engine.begin() as connection:
        for statement in statements:
            name = _VIEW_NAME.search(statement).group(1)
            # DROP then CREATE rather than CREATE OR REPLACE: SQLite has no
            # OR REPLACE for views, and PostgreSQL's refuses a changed column
            # list, which is exactly when a redeploy needs it most.
            connection.execute(text(f"DROP VIEW IF EXISTS {name}"))
            connection.execute(text(statement))
            created.append(name)
    return created
