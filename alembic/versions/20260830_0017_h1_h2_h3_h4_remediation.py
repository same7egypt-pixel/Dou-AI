"""H1/H2/H3/H4 remediation: source instance, nonce replay, AI context.

Revision ID: 20260830_0017
Revises: 20260830_0016
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260830_0017"
down_revision: Union[str, None] = "20260830_0016"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "alert_source_mappings",
        sa.Column("source_instance", sa.String(80), nullable=False, server_default="default"),
    )
    op.drop_constraint("uq_alert_source_external", "alert_source_mappings", type_="unique")
    op.create_unique_constraint(
        "uq_alert_source_external",
        "alert_source_mappings",
        ["source_instance", "source", "external_alert_id"],
    )

    op.create_table(
        "webhook_receipts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nonce", sa.String(80), nullable=False, index=True),
        sa.Column("received_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("nonce", name="uq_webhook_nonce"),
    )


def downgrade() -> None:
    op.drop_table("webhook_receipts")
    op.drop_constraint("uq_alert_source_external", "alert_source_mappings", type_="unique")
    op.create_unique_constraint(
        "uq_alert_source_external",
        "alert_source_mappings",
        ["tenant_id", "source", "external_alert_id"],
    )
    op.drop_column("alert_source_mappings", "source_instance")
