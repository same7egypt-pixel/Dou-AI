"""Add employment_model and operator_tenant_id to couriers for hybrid platform isolation.

Revision ID: 20260903_0024
Revises: 20260903_0023
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260903_0024"
down_revision: Union[str, Sequence[str], None] = "20260903_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE couriers ADD COLUMN IF NOT EXISTS employment_model VARCHAR(30) DEFAULT 'DIRECT_HIRE'")
    op.execute("ALTER TABLE couriers ADD COLUMN IF NOT EXISTS operator_tenant_id INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_couriers_tenant_employment ON couriers (tenant_id, employment_model)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_couriers_tenant_employment")
    op.execute("ALTER TABLE couriers DROP COLUMN IF EXISTS operator_tenant_id")
    op.execute("ALTER TABLE couriers DROP COLUMN IF EXISTS employment_model")
