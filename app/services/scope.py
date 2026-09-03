"""Shared DOU AI scope and query utilities."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Query, Session

from ..models import entities as ent


@dataclass
class AuthorizedScope:
    tenant_id: int
    customer_type: str
    user_id: int
    role: str
    operator_id: int | None = None
    supervisor_id: int | None = None
    project_ids: list[int] | None = None
    rider_id: int | None = None
    project_id: int | None = None
    city_id: int | None = None
    # What the account has actually bought. DOU AI answered a payroll question
    # for a platform account that /hr/payroll refuses with 403, because the
    # assistant only ever checked tenant and role. The registry now gates on
    # this too, so the assistant cannot be a way around an entitlement.
    capabilities: frozenset[str] = frozenset()


def courier_query(db: Session, scope: AuthorizedScope) -> Query:
    query = db.query(ent.Courier).filter(ent.Courier.tenant_id == scope.tenant_id)
    if scope.supervisor_id:
        query = query.filter(ent.Courier.supervisor_id == scope.supervisor_id)
    if scope.project_ids is not None:
        query = query.filter(
            ent.Courier.primary_project_id.in_(scope.project_ids or [-1])
        )
    if scope.rider_id:
        query = query.filter(ent.Courier.id == scope.rider_id)
    if scope.project_id:
        query = query.filter(ent.Courier.primary_project_id == scope.project_id)
    if scope.city_id:
        query = query.filter(ent.Courier.city_id == scope.city_id)
    if scope.operator_id:
        assigned = db.query(ent.RiderAssignment.courier_id).filter(
            ent.RiderAssignment.tenant_id == scope.tenant_id,
            ent.RiderAssignment.operator_id == scope.operator_id,
            ent.RiderAssignment.status == "ACTIVE",
        )
        query = query.filter(ent.Courier.id.in_(assigned))
    return query
