"""Add Phase 2 DOU Flex merchant, branch, dedicated shift, and settlement tables.

Revision ID: 20260904_0025
Revises: 20260903_0024
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260904_0025"
down_revision: Union[str, Sequence[str], None] = "20260903_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- merchant_accounts ---
    op.create_table(
        "merchant_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_name", sa.String(255), nullable=False),
        sa.Column("vat_number", sa.String(20), nullable=True),
        sa.Column("billing_contact_email", sa.String(255), nullable=False),
        sa.Column("billing_contact_phone", sa.String(20), nullable=False),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("api_key_prefix", sa.String(16), nullable=True),
        sa.Column("api_key_hash", sa.String(255), nullable=True, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_merchant_accounts_api_key_hash", "merchant_accounts", ["api_key_hash"])
    op.create_index("ix_merchant_accounts_api_key_prefix", "merchant_accounts", ["api_key_prefix"])

    # --- merchant_branches ---
    op.create_table(
        "merchant_branches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_account_id", sa.Integer(), sa.ForeignKey("merchant_accounts.id"), nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("district", sa.String(100), nullable=True),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("geofence_radius_meters", sa.Integer(), nullable=False, server_default="150"),
        sa.Column("cashier_access_pin", sa.String(255), nullable=False),
        sa.Column("tablet_device_id", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- dedicated_shift_bookings ---
    op.create_table(
        "dedicated_shift_bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_branch_id", sa.Integer(), sa.ForeignKey("merchant_branches.id"), nullable=False),
        sa.Column("logistics_company_tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("shift_type", sa.Enum("peak_3h", "full_day_8h", name="shifttype"), nullable=False),
        sa.Column("shift_start_time", sa.Time(), nullable=False),
        sa.Column("shift_end_time", sa.Time(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("monthly_fee_to_merchant", sa.Numeric(10, 2), nullable=False),
        sa.Column("monthly_payout_to_logistics", sa.Numeric(10, 2), nullable=False),
        sa.Column("dou_margin", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.Enum("active", "paused", "terminated", name="bookingstatus"), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("termination_reason", sa.Text(), nullable=True),
    )

    # --- shift_attendance_logs ---
    op.create_table(
        "shift_attendance_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedicated_shift_booking_id", sa.Integer(), sa.ForeignKey("dedicated_shift_bookings.id"), nullable=False),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("checkin_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkin_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("checkin_lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("geofence_validated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("checkout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkout_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("checkout_lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- branch_dispatch_orders ---
    op.create_table(
        "branch_dispatch_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_branch_id", sa.Integer(), sa.ForeignKey("merchant_branches.id"), nullable=False),
        sa.Column("dedicated_shift_booking_id", sa.Integer(), sa.ForeignKey("dedicated_shift_bookings.id"), nullable=True),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("customer_phone", sa.String(20), nullable=False),
        sa.Column("delivery_address_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("pending", "en_route", "delivered", name="branchorderstatus"), nullable=False, server_default="pending"),
        sa.Column("order_source", sa.String(50), nullable=False, server_default="manual_cashier"),
        sa.Column("external_order_id", sa.String(100), nullable=True),
        sa.Column("is_pool_eligible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_branch_dispatch_orders_external_order_id", "branch_dispatch_orders", ["external_order_id"])

    # --- monthly_settlement_ledger ---
    op.create_table(
        "monthly_settlement_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_account_id", sa.Integer(), sa.ForeignKey("merchant_accounts.id"), nullable=False),
        sa.Column("settlement_month", sa.Date(), nullable=False),
        sa.Column("total_rider_shift_months", sa.Numeric(8, 4), nullable=False),
        sa.Column("gross_fee_charged_to_merchant", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_payout_to_logistics", sa.Numeric(12, 2), nullable=False),
        sa.Column("dou_net_margin", sa.Numeric(12, 2), nullable=False),
        sa.Column("settlement_status", sa.Enum("draft", "issued", "paid", name="settlementstatus"), nullable=False, server_default="draft"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bank_transfer_reference", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("monthly_settlement_ledger")
    op.drop_index("ix_branch_dispatch_orders_external_order_id", "branch_dispatch_orders")
    op.drop_table("branch_dispatch_orders")
    op.drop_table("shift_attendance_logs")
    op.drop_table("dedicated_shift_bookings")
    op.drop_table("merchant_branches")
    op.drop_index("ix_merchant_accounts_api_key_prefix", "merchant_accounts")
    op.drop_index("ix_merchant_accounts_api_key_hash", "merchant_accounts")
    op.drop_table("merchant_accounts")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS shifttype")
        op.execute("DROP TYPE IF EXISTS bookingstatus")
        op.execute("DROP TYPE IF EXISTS branchorderstatus")
        op.execute("DROP TYPE IF EXISTS settlementstatus")
