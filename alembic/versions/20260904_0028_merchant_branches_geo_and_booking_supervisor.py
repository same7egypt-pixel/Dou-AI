"""Add city_id and country_id to merchant_branches, supervisor_id to dedicated_shift_bookings.

Revision ID: 20260904_0028
Revises: 20260904_0027
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

revision: str = "20260904_0028"
down_revision: Union[str, Sequence[str], None] = "20260904_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_context().dialect.name

    # 1. Add city_id and country_id to merchant_branches
    if dialect == "sqlite":
        op.add_column("merchant_branches", sa.Column("city_id", sa.Integer(), nullable=True))
        op.add_column("merchant_branches", sa.Column("country_id", sa.Integer(), nullable=True))
        op.add_column("dedicated_shift_bookings", sa.Column("supervisor_id", sa.Integer(), nullable=True))
    else:
        op.add_column(
            "merchant_branches",
            sa.Column(
                "city_id",
                sa.Integer(),
                sa.ForeignKey("geo_cities.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(
            "merchant_branches",
            sa.Column(
                "country_id",
                sa.Integer(),
                sa.ForeignKey("geo_countries.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(
            "dedicated_shift_bookings",
            sa.Column(
                "supervisor_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # 3. Canonical backfill of existing merchant_branches using find_or_create_city & ensure_geo_country
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        from app.services.operating_structure import find_or_create_city

        class _DefaultTenant:
            market_code = "SA"
            country = "SA"

        tenant = _DefaultTenant()

        # Query all branches where city_id IS NULL and city IS NOT NULL
        branches = bind.execute(
            sa.text("SELECT id, city FROM merchant_branches WHERE city_id IS NULL AND city IS NOT NULL")
        ).fetchall()

        for row in branches:
            b_id = row[0]
            b_city = row[1]
            if not b_city or not str(b_city).strip():
                continue
            city_obj = find_or_create_city(session, tenant, str(b_city))
            bind.execute(
                sa.text(
                    "UPDATE merchant_branches SET city_id = :city_id, country_id = :country_id WHERE id = :id"
                ),
                {"city_id": city_obj.id, "country_id": city_obj.country_id, "id": b_id},
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def downgrade() -> None:
    op.drop_column("dedicated_shift_bookings", "supervisor_id")
    op.drop_column("merchant_branches", "country_id")
    op.drop_column("merchant_branches", "city_id")
