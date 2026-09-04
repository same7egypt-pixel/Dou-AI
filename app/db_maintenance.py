"""Explicit database initialization and compatibility migrations.

This module defines database-changing maintenance operations but performs no work
at import time. Production startup must invoke ``tools/migrate.py`` explicitly
before starting the web process.
"""

import os

from .database import Base, SessionLocal, engine
from .migrations import run_migrations

# A model module missing below is missing from Base.metadata, so create_all
# skips its tables and a fresh install comes up without them. Keep this list in
# step with alembic/env.py.
from .models import (
    entities,  # noqa: F401 - core Phase 1 schema
    intelligence,  # noqa: F401 - DOU AI / notifications metadata
    merchant,  # noqa: F401 - DOU Flex / Merchant Phase 2
    salary,  # noqa: F401 - salary structures, components, rider assignments
)
from .models.entities import Country, User, UserRole
from .routers.auth import hash_password
from .services.operating_structure import backfill_operating_cities


def bootstrap_admin_from_environment() -> None:
    """Create or reset the temporary DOU owner only when explicitly configured."""
    phone = os.getenv("BOOTSTRAP_ADMIN_PHONE", "").strip()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    reset = os.getenv("BOOTSTRAP_ADMIN_RESET", "false").lower() == "true"
    if not phone or len(password) < 8:
        return
    with SessionLocal() as db:
        user = db.query(User).filter(User.phone == phone).first()
        if not user:
            user = User(
                phone=phone,
                name="مالك منصة DOU",
                password_hash=hash_password(password),
                role=UserRole.DOU_ADMIN,
                country=Country.SA,
                is_active=True,
            )
            db.add(user)
        elif reset:
            user.password_hash = hash_password(password)
            user.role = UserRole.DOU_ADMIN
            user.is_active = True
            user.token_version = (user.token_version or 0) + 1
        db.commit()
    print("✅ DOU admin bootstrap completed; remove BOOTSTRAP_ADMIN_* variables now")


def initialize_database() -> None:
    """Apply schema setup, compatibility migrations, and controlled backfills."""
    # Not wrapped in try/except. create_all already skips objects that exist
    # (checkfirst), so a failure here means something genuinely wrong with the
    # database, and continuing would boot the app against an incomplete schema
    # while printing that everything is fine.
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    with SessionLocal() as migration_db:
        city_backfill = backfill_operating_cities(migration_db)
        if city_backfill:
            print(f"   ➕ operating-city backfill: {city_backfill}")
    bootstrap_admin_from_environment()
