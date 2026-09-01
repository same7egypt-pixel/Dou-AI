"""Add import_date to raw_import_rows for timezone-safe reconciliation.

Revision ID: 20260829_0012
Revises: 20260829_0011
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0012"
down_revision: Union[str, Sequence[str], None] = "20260829_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_import_rows",
        sa.Column("import_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_raw_import_rows_import_date", "raw_import_rows", ["import_date"])
    # Backfill existing rows from created_at (UTC)
    op.execute(
        "UPDATE raw_import_rows SET import_date = DATE(created_at) WHERE import_date IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_raw_import_rows_import_date", table_name="raw_import_rows")
    op.drop_column("raw_import_rows", "import_date")
