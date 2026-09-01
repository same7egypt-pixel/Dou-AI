"""Mixins for SQLAlchemy models."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from sqlalchemy.orm import declarative_mixin


@declarative_mixin
class SoftDeleteMixin:
    """Mixin to add soft delete support to models."""
    deleted_at = Column(DateTime, nullable=True, default=None)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self):
        """Mark record as deleted without removing it."""
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self):
        """Restore a soft-deleted record."""
        self.deleted_at = None
