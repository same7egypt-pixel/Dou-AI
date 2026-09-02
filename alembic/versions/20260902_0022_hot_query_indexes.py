"""Index the filters payroll and reporting run on every request.

``couriers`` had no index on ``tenant_id`` at all, which is the filter that
opens practically every scoped query in the app. ``payroll_adjustments`` had no
index of any kind and is read as (tenant, riders, month) on each payroll sheet.
``attendances`` is scanned by rider set over a date window by the target and
attendance reports. ``daily_logs`` already leads with ``courier_id`` through its
unique constraint, so it needs nothing here.

Revision ID: 20260902_0022
Revises: 20260902_0021
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260902_0022"
down_revision: Union[str, Sequence[str], None] = "20260902_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("ix_couriers_tenant_id", "couriers", ["tenant_id"]),
    ("ix_couriers_tenant_supervisor", "couriers", ["tenant_id", "supervisor_id"]),
    ("ix_couriers_tenant_branch", "couriers", ["tenant_id", "contract_branch_id"]),
    (
        "ix_payroll_adjustments_tenant_courier_month",
        "payroll_adjustments",
        ["tenant_id", "courier_id", "month"],
    ),
    ("ix_attendances_courier_check_in", "attendances", ["courier_id", "check_in"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False, if_not_exists=True)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
