"""Money on a branch order, and a contracted seat nobody fills yet.

Two gaps that between them block seven asks across four portals.

`branch_dispatch_orders` carried no money at all — no amount, no payment
method, no cash. So a rider could not be told whether to collect from the
customer, a cashier could not clear the rider's float at the end of a shift,
and nobody could reconcile a day's cash against the till.

`dedicated_shift_bookings.rider_id` was NOT NULL, so one row was always one
staffed seat. A branch that contracted ten riders and is running with eight had
no way to say so — and a shortfall you cannot record is a shortfall you cannot
bill an SLA deduction for.

Revision ID: 20260905_0029
Revises: 20260904_0028
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260905_0029"
down_revision: Union[str, Sequence[str], None] = "20260904_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PAYMENT_METHODS = ("cash", "card", "prepaid", "unknown")
ENUM_NAME = "branchorderpaymentmethod"


def _payment_enum(dialect: str, create_type: bool):
    """Postgres needs a named type; SQLite stores the value as text."""
    if dialect == "sqlite":
        return sa.String(length=16)
    return sa.Enum(*PAYMENT_METHODS, name=ENUM_NAME, create_type=create_type)


def upgrade() -> None:
    dialect = op.get_context().dialect.name

    if dialect != "sqlite":
        sa.Enum(*PAYMENT_METHODS, name=ENUM_NAME).create(op.get_bind(), checkfirst=True)

    # 1. Money on a branch order. Every existing row predates the quick-entry
    #    form, so its method is `unknown` rather than a guessed `cash` — a rider
    #    must never be told to collect an amount the system invented.
    op.add_column(
        "branch_dispatch_orders",
        sa.Column("order_amount", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "branch_dispatch_orders",
        sa.Column(
            "payment_method",
            _payment_enum(dialect, create_type=False),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "branch_dispatch_orders",
        sa.Column(
            "cod_amount", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "branch_dispatch_orders",
        sa.Column("cod_settled_at", sa.DateTime(timezone=True), nullable=True),
    )

    # A rider's outstanding float is "delivered, cash, not settled yet", and the
    # cashier's handover screen reads it per branch on every shift close.
    op.create_index(
        "ix_branch_orders_cod_open",
        "branch_dispatch_orders",
        ["merchant_branch_id", "rider_id", "cod_settled_at"],
    )

    # 2. An unfilled contracted seat. SQLite cannot alter a column in place, so
    #    the table is rebuilt; batch_alter_table does that on both dialects.
    with op.batch_alter_table("dedicated_shift_bookings") as batch:
        batch.alter_column(
            "rider_id", existing_type=sa.Integer(), nullable=True
        )


def downgrade() -> None:
    dialect = op.get_context().dialect.name

    # A seat with no rider cannot exist under the old shape. Terminating those
    # rows keeps the money history intact; deleting them would silently drop
    # contracted seats a merchant was billed for.
    op.execute(
        "UPDATE dedicated_shift_bookings SET status = 'terminated', "
        "termination_reason = COALESCE(termination_reason, "
        "'seat was unfilled at schema downgrade') "
        "WHERE rider_id IS NULL AND status != 'terminated'"
    )
    # Still NOT NULL, so an unfilled seat needs some rider. There is no honest
    # answer, and inventing one would attribute a seat to a rider who never
    # worked it — so refuse rather than corrupt.
    bind = op.get_bind()
    orphans = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM dedicated_shift_bookings WHERE rider_id IS NULL"
        )
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} booking(s) hold a contracted seat with no rider. "
            "Assign or delete them before downgrading; this migration will not "
            "guess which rider worked a seat."
        )

    with op.batch_alter_table("dedicated_shift_bookings") as batch:
        batch.alter_column(
            "rider_id", existing_type=sa.Integer(), nullable=False
        )

    op.drop_index("ix_branch_orders_cod_open", table_name="branch_dispatch_orders")
    for column in ("cod_settled_at", "cod_amount", "payment_method", "order_amount"):
        op.drop_column("branch_dispatch_orders", column)

    if dialect != "sqlite":
        sa.Enum(name=ENUM_NAME).drop(op.get_bind(), checkfirst=True)
