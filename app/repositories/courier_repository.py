"""Centralized Courier repository for scoped data access."""
from __future__ import annotations
from typing import Optional, List
from sqlalchemy import or_
from sqlalchemy.orm import Session, Query

from ..models import entities as ent
from ..services.scope import AuthorizedScope


class CourierRepository:
    """Centralized courier query logic with strict tenant & supervisor scoping."""

    def __init__(self, db: Session):
        self.db = db

    def by_scope(self, scope: AuthorizedScope) -> Query:
        """Base query filtered by tenant + supervisor + project scope."""
        q = self.db.query(ent.Courier)
        if scope.tenant_id is not None:
            q = q.filter(ent.Courier.tenant_id == scope.tenant_id)
        if scope.supervisor_id:
            from ..services.workforce_scope import supervisor_courier_scope
            q = q.filter(supervisor_courier_scope(self.db, scope.supervisor_id))
        if scope.project_ids is not None:
            q = q.filter(ent.Courier.primary_project_id.in_(scope.project_ids))
        return q

    def search(self, scope: AuthorizedScope, term: str) -> Query:
        """Search couriers by name or phone within scope."""
        q = self.by_scope(scope)
        if term and term.strip():
            needle = f"%{term.strip()}%"
            q = q.filter(
                or_(
                    ent.Courier.name.ilike(needle),
                    ent.Courier.phone.ilike(needle),
                )
            )
        return q

    def active_couriers(self, scope: AuthorizedScope) -> List[ent.Courier]:
        """Get all active couriers in scope."""
        return self.by_scope(scope).filter(ent.Courier.employment_status == "ACTIVE").all()
