"""Every runtime file the app opens must be copied into the image.

Removing the source bind mount was correct, but it exposed a class of failure
the mount had been hiding: the container runs only what the Dockerfile COPYs.
scripts/ was missing, so the nightly backup would have failed silently every
night. analytics_views.sql was missing, and because it is read during migration
the container refused to boot at all - a production outage that a passing test
suite and a clean lint did not predict.

This asserts the Dockerfile carries what the code reads at runtime.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")

# Paths the running container opens, and why.
REQUIRED = {
    "app": "the application itself",
    "tools": "tools/migrate.py runs before uvicorn starts",
    "alembic": "migration revisions",
    "alembic.ini": "migration config",
    "scripts": "scripts/backup.py is invoked by the nightly cron",
    "analytics_views.sql": "read during migration to build the BI views",
    "frontend-v2": "the fleet and admin SPAs",
    "static": "the landing pages and the rider PWA",
}


def _copied_paths() -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"^COPY\s+(\S+)\s+\S+\s*$", DOCKERFILE, re.M)
    }


@pytest.mark.parametrize("path,reason", sorted(REQUIRED.items()))
def test_dockerfile_copies_runtime_path(path, reason):
    assert path in _copied_paths(), (
        f"the image does not COPY {path!r}, needed because {reason}. "
        "The container runs the image, not the host tree."
    )


def test_the_migration_entrypoint_can_find_its_sql():
    """analytics_views.py resolves the SQL relative to the package, so the file
    has to sit at the image root exactly as it does in the repository."""
    from app.analytics_views import SQL_FILE

    assert SQL_FILE.name == "analytics_views.sql"
    assert SQL_FILE.parent == ROOT, (
        "the SQL file is resolved outside the repository root; the Dockerfile "
        "copies it to /app, so the loader must look there"
    )
    assert SQL_FILE.exists()
