"""Merchant branch self-service, verification gating, and company rider approvals.

Adds:
- created_by_source, verification_status, verified_by_admin_id, and verified_at to merchant_branches.
- rider_assignment_approvals table for company courier approvals by restaurant merchants.

Revision ID: 20260905_0031
Revises: 20260905_0030
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0031"
down_revision: Union[str, Sequence[str], None] = "20260905_0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add verification and creation source columns to merchant_branches
    with op.batch_alter_table("merchant_branches") as batch_op:
        batch_op.add_column(
            sa.Column(
                "created_by_source",
                sa.String(length=20),
                nullable=False,
                server_default="ADMIN",
            )
        )
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.String(length=20),
                nullable=False,
                server_default="VERIFIED",
            )
        )
        batch_op.add_column(
            sa.Column(
                "verified_by_admin_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "verified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )

    # 2. Create rider_assignment_approvals table
    op.create_table(
        "rider_assignment_approvals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "booking_id",
            sa.Integer(),
            sa.ForeignKey("dedicated_shift_bookings.id", ondelete="CASCADE"),
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
        sa.Column(
            "merchant_account_id",
            sa.Integer(),
            sa.ForeignKey("merchant_accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "logistics_company_tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "courier_id",
            sa.Integer(),
            sa.ForeignKey("couriers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("courier_name", sa.String(length=255), nullable=False),
        sa.Column("courier_phone", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # 1. Drop rider_assignment_approvals table
    op.drop_table("rider_assignment_approvals")

    # 2. Drop added columns from merchant_branches
    with op.batch_alter_table("merchant_branches") as batch_op:
        batch_op.drop_column("verified_at")
        batch_op.drop_column("verified_by_admin_id")
        batch_op.drop_column("verification_status")
        batch_op.drop_column("created_by_source")
