"""Add driver_orders, verified_orders, variance to daily_logs and invitation tracking to platform_operators.

Revision ID: 20260903_0023
Revises: 20260902_0022
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260903_0023"
down_revision: Union[str, Sequence[str], None] = "20260902_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE daily_logs ADD COLUMN IF NOT EXISTS driver_orders INTEGER DEFAULT 0")
    op.execute("ALTER TABLE daily_logs ADD COLUMN IF NOT EXISTS verified_orders INTEGER DEFAULT 0")
    op.execute("ALTER TABLE daily_logs ADD COLUMN IF NOT EXISTS variance INTEGER DEFAULT 0")

    op.execute("ALTER TABLE platform_operators ADD COLUMN IF NOT EXISTS invitation_status VARCHAR(20) DEFAULT 'ACCEPTED'")
    op.execute("ALTER TABLE platform_operators ADD COLUMN IF NOT EXISTS invited_at TIMESTAMP")
    op.execute("ALTER TABLE platform_operators ADD COLUMN IF NOT EXISTS responded_at TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE daily_logs DROP COLUMN IF EXISTS driver_orders")
    op.execute("ALTER TABLE daily_logs DROP COLUMN IF EXISTS verified_orders")
    op.execute("ALTER TABLE daily_logs DROP COLUMN IF EXISTS variance")
    op.execute("ALTER TABLE platform_operators DROP COLUMN IF EXISTS invitation_status")
    op.execute("ALTER TABLE platform_operators DROP COLUMN IF EXISTS invited_at")
    op.execute("ALTER TABLE platform_operators DROP COLUMN IF EXISTS responded_at")
