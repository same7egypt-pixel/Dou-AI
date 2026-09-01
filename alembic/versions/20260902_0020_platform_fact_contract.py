"""Link platform performance facts to company contracts.

Revision ID: 20260902_0020
Revises: 20260830_0019
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0020"
down_revision: Union[str, Sequence[str], None] = "20260830_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("platform_delivery_facts") as batch_op:
        batch_op.add_column(sa.Column("contract_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_platform_delivery_facts_contract_id",
            "contracts",
            ["contract_id"],
            ["id"],
        )
    op.create_index(
        "ix_platform_delivery_facts_contract_id",
        "platform_delivery_facts",
        ["contract_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_delivery_facts_contract_id",
        table_name="platform_delivery_facts",
    )
    with op.batch_alter_table("platform_delivery_facts") as batch_op:
        batch_op.drop_constraint(
            "fk_platform_delivery_facts_contract_id",
            type_="foreignkey",
        )
        batch_op.drop_column("contract_id")
