"""Migrate dedicated shift bookings to direct merchant contract value and fixed DOU commission.

Revision ID: 20260904_0026
Revises: 20260904_0025
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260904_0026"
down_revision: Union[str, Sequence[str], None] = "20260904_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add new columns as nullable initially to allow data migration
    op.add_column(
        "dedicated_shift_bookings",
        sa.Column("contract_value_monthly", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "dedicated_shift_bookings",
        sa.Column("dou_commission_monthly", sa.Numeric(10, 2), nullable=True),
    )

    # 2. Migrate existing contract data:
    # contract_value_monthly = monthly_fee_to_merchant
    # dou_commission_monthly = dou_margin (or fee - payout fallback)
    op.execute(
        """
        UPDATE dedicated_shift_bookings
        SET contract_value_monthly = COALESCE(monthly_fee_to_merchant, 7000.00),
            dou_commission_monthly = COALESCE(dou_margin, monthly_fee_to_merchant - monthly_payout_to_logistics, 1500.00)
        """
    )

    # 3. Enforce non-null constraints
    op.alter_column("dedicated_shift_bookings", "contract_value_monthly", nullable=False)
    op.alter_column("dedicated_shift_bookings", "dou_commission_monthly", nullable=False)

    # 4. Drop legacy columns
    op.drop_column("dedicated_shift_bookings", "monthly_fee_to_merchant")
    op.drop_column("dedicated_shift_bookings", "monthly_payout_to_logistics")
    op.drop_column("dedicated_shift_bookings", "dou_margin")


def downgrade() -> None:
    # 1. Recreate legacy columns as nullable initially
    op.add_column(
        "dedicated_shift_bookings",
        sa.Column("monthly_fee_to_merchant", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "dedicated_shift_bookings",
        sa.Column("monthly_payout_to_logistics", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "dedicated_shift_bookings",
        sa.Column("dou_margin", sa.Numeric(10, 2), nullable=True),
    )

    # 2. Re-populate legacy columns from new commission model
    op.execute(
        """
        UPDATE dedicated_shift_bookings
        SET monthly_fee_to_merchant = contract_value_monthly,
            dou_margin = dou_commission_monthly,
            monthly_payout_to_logistics = contract_value_monthly - dou_commission_monthly
        """
    )

    # 3. Enforce non-null constraints
    op.alter_column("dedicated_shift_bookings", "monthly_fee_to_merchant", nullable=False)
    op.alter_column("dedicated_shift_bookings", "monthly_payout_to_logistics", nullable=False)
    op.alter_column("dedicated_shift_bookings", "dou_margin", nullable=False)

    # 4. Drop new columns
    op.drop_column("dedicated_shift_bookings", "contract_value_monthly")
    op.drop_column("dedicated_shift_bookings", "dou_commission_monthly")
