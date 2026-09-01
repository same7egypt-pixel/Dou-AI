"""Add onboarding_status to operational readiness state.

Revision ID: 20260830_0018
Revises: 20260830_0017
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260830_0018"
down_revision: Union[str, Sequence[str], None] = "20260830_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "operational_readiness_states",
        sa.Column("onboarding_status", sa.String(20), nullable=False, server_default="NEW"),
    )
    op.create_index(
        "ix_readiness_state_onboarding_status",
        "operational_readiness_states",
        ["tenant_id", "onboarding_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_readiness_state_onboarding_status", table_name="operational_readiness_states")
    op.drop_column("operational_readiness_states", "onboarding_status")
