"""Run versioned DOU database migrations before the web process starts."""
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# When REPO_ROOT sits at the front of sys.path, the repository's own
# `alembic/` folder (env.py + versions/ — no __init__.py) can shadow the
# installed alembic library and break `from alembic import command`.
# Remove it momentarily for the alembic imports, then restore it before
# importing app modules that live under REPO_ROOT.
if str(REPO_ROOT) in sys.path:
    sys.path.remove(str(REPO_ROOT))

from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from alembic import command  # noqa: E402

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.analytics_views import create_analytics_views  # noqa: E402
from app.database import engine  # noqa: E402
from app.db_maintenance import initialize_database  # noqa: E402


def alembic_config() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


@contextmanager
def migration_lock():
    if engine.dialect.name != "postgresql":
        yield
        return
    lock_id = 4_446_851_001
    with engine.connect() as connection:
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id}
        ).scalar()
        if not acquired:
            raise RuntimeError("Another DOU database migration is already running")
        try:
            yield
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id}
            )


def migrate() -> None:
    config = alembic_config()
    with migration_lock():
        if not inspect(engine).has_table("alembic_version"):
            # Transitional adoption path for existing and fresh Phase 1 databases.
            # It is idempotent and runs once; future changes are Alembic revisions.
            initialize_database()
            command.stamp(config, "head")
        else:
            command.upgrade(config, "head")

        # Recreated on every deploy, after the schema is settled. They are
        # derived objects with no data of their own, so rebuilding them is
        # always safe and makes editing analytics_views.sql a normal deploy.
        create_analytics_views(engine)


if __name__ == "__main__":
    migrate()
    print("✅ Database migration completed")
