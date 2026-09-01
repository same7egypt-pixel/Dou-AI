"""Adopt Alembic after the legacy Phase 1 schema.

Revision ID: 20260829_0001
Revises: None
Create Date: 2026-08-29

This is an intentional marker revision. ``tools/migrate.py`` first brings an
unversioned database to the verified Phase 1 schema using the legacy idempotent
initializer, then stamps this revision. All schema changes after this marker
must be implemented as normal Alembic revisions.
"""
from typing import Sequence, Union


revision: str = "20260829_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("The adopted Phase 1 baseline cannot be downgraded automatically")
