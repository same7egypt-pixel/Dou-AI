"""Add analytics refresh state + fix source mapping uniqueness.

Revision ID: 20260830_0016
Revises: 20260830_0015
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260830_0016"
down_revision: Union[str, Sequence[str], None] = "20260830_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("analytics_refresh_states",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("table_name", sa.String(80), nullable=False),
        sa.Column("last_refresh_started_at", sa.DateTime),
        sa.Column("last_refresh_succeeded_at", sa.DateTime),
        sa.Column("last_refresh_failed_at", sa.DateTime),
        sa.Column("last_error", sa.Text),
        sa.Column("row_count", sa.Integer),
        sa.Column("status", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("table_name", name="uq_analytics_refresh_table"))
    # Fix source mapping uniqueness to include tenant_id
    op.drop_constraint("uq_alert_source_external", "alert_source_mappings", type_="unique")
    op.create_unique_constraint("uq_alert_source_external", "alert_source_mappings",
                                ["tenant_id", "source", "external_alert_id"])


def downgrade() -> None:
    op.drop_constraint("uq_alert_source_external", "alert_source_mappings", type_="unique")
    op.create_unique_constraint("uq_alert_source_external", "alert_source_mappings",
                                ["source", "external_alert_id"])
    op.drop_table("analytics_refresh_states")
