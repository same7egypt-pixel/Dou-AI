"""Settlement VAT rate/amount and merchant capacity requests.

Adds vat_rate and vat_amount to monthly_settlement_ledger so every issued settlement
locks and preserves the historical tax rate and amount at issuance date.

Creates merchant_capacity_requests to allow restaurant chain owners to formally
request seat capacity adjustments for future months under a multi-stage review pattern.

Revision ID: 20260905_0030
Revises: 20260905_0029
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0030"
down_revision: Union[str, Sequence[str], None] = "20260905_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add VAT rate and VAT amount to monthly_settlement_ledger
    with op.batch_alter_table("monthly_settlement_ledger") as batch_op:
        batch_op.add_column(
            sa.Column("vat_rate", sa.Numeric(5, 4), nullable=True)
        )
        batch_op.add_column(
            sa.Column("vat_amount", sa.Numeric(12, 2), nullable=True)
        )

    # 2. Create merchant_capacity_requests table
    op.create_table(
        "merchant_capacity_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "merchant_account_id",
            sa.Integer(),
            sa.ForeignKey("merchant_accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "merchant_branch_id",
            sa.Integer(),
            sa.ForeignKey("merchant_branches.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("current_capacity", sa.Integer(), nullable=False),
        sa.Column("requested_capacity", sa.Integer(), nullable=False),
        sa.Column("effective_month", sa.String(length=7), nullable=False),  # e.g. "2026-10"
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="requested",
        ),  # requested, under_review, approved, rejected
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("merchant_capacity_requests")
    with op.batch_alter_table("monthly_settlement_ledger") as batch_op:
        batch_op.drop_column("vat_amount")
        batch_op.drop_column("vat_rate")
