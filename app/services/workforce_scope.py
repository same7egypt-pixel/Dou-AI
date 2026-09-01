"""Central server-side workforce scope expressions."""

from datetime import date
from typing import Optional

from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session

from ..models.entities import (
    ContractBranch,
    Courier,
    TeamMembership,
    TeamSupervisorAssignment,
    User,
)


def supervisor_courier_scope(
    db: Session, supervisor_id: int, as_of: Optional[date] = None
):
    """Return a tenant-locked SQL expression for a supervisor's current riders."""
    selected_date = as_of or date.today()
    supervisor = db.get(User, supervisor_id)
    if not supervisor or not supervisor.tenant_id:
        return false()
    tenant_id = supervisor.tenant_id

    assigned_team_ids = select(TeamSupervisorAssignment.team_id).where(
        TeamSupervisorAssignment.tenant_id == tenant_id,
        TeamSupervisorAssignment.supervisor_id == supervisor_id,
        TeamSupervisorAssignment.effective_from <= selected_date,
        or_(
            TeamSupervisorAssignment.effective_to.is_(None),
            TeamSupervisorAssignment.effective_to >= selected_date,
        ),
    )
    team_courier_ids = (
        select(TeamMembership.courier_id)
        .join(
            Courier,
            Courier.id == TeamMembership.courier_id,
        )
        .where(
            TeamMembership.tenant_id == tenant_id,
            Courier.tenant_id == tenant_id,
            TeamMembership.team_id.in_(assigned_team_ids),
            TeamMembership.effective_from <= selected_date,
            or_(
                TeamMembership.effective_to.is_(None),
                TeamMembership.effective_to >= selected_date,
            ),
        )
    )
    branch_ids = select(ContractBranch.id).where(
        ContractBranch.tenant_id == tenant_id,
        ContractBranch.supervisor_id == supervisor_id,
    )
    project_ids = select(ContractBranch.project_id).where(
        ContractBranch.tenant_id == tenant_id,
        ContractBranch.supervisor_id == supervisor_id,
        ContractBranch.project_id.isnot(None),
    )
    return and_(
        Courier.tenant_id == tenant_id,
        or_(
            Courier.supervisor_id == supervisor_id,
            Courier.id.in_(team_courier_ids),
            and_(
                Courier.supervisor_id.is_(None),
                or_(
                    Courier.contract_branch_id.in_(branch_ids),
                    Courier.primary_project_id.in_(project_ids),
                ),
            ),
        ),
    )
