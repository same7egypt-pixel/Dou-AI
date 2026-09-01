"""Add Wave 2: source platforms, raw ingestion, rider mapping, delivery facts, reconciliation.

Revision ID: 20260829_0009
Revises: 20260829_0008
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0009"
down_revision: Union[str, Sequence[str], None] = "20260829_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_platforms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("description", sa.String(length=300)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_source_platform_tenant_code"),
    )
    op.create_index("ix_source_platforms_tenant_id", "source_platforms", ["tenant_id"])
    op.create_index("ix_source_platform_tenant_active", "source_platforms", ["tenant_id", "is_active"])

    op.create_table(
        "tenant_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_platform_id", sa.Integer(), sa.ForeignKey("source_platforms.id"), nullable=False),
        sa.Column("connection_name", sa.String(length=120), nullable=False),
        sa.Column("import_frequency", sa.String(length=20), nullable=False, server_default=sa.text("'DAILY'")),
        sa.Column("credential_reference", sa.String(length=300)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_import_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source_platform_id", name="uq_tenant_connection_platform"),
    )
    op.create_index("ix_tenant_connections_tenant_id", "tenant_connections", ["tenant_id"])
    op.create_index("ix_tenant_connection_tenant_active", "tenant_connections", ["tenant_id", "is_active"])

    op.create_table(
        "project_contract_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_platform_id", sa.Integer(), sa.ForeignKey("source_platforms.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("contracts.id")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source_platform_id", "project_id", name="uq_project_contract_mapping"),
    )
    op.create_index("ix_project_contract_mappings_tenant_id", "project_contract_mappings", ["tenant_id"])

    op.create_table(
        "rider_identity_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_platform_id", sa.Integer(), sa.ForeignKey("source_platforms.id"), nullable=False),
        sa.Column("source_rider_id", sa.String(length=80), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("match_method", sa.String(length=30), nullable=False, server_default=sa.text("'MANUAL'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source_platform_id", "source_rider_id", name="uq_rider_identity_mapping"),
    )
    op.create_index("ix_rider_identity_mappings_tenant_id", "rider_identity_mappings", ["tenant_id"])
    op.create_index("ix_rider_identity_mapping_tenant_courier", "rider_identity_mappings", ["tenant_id", "courier_id"])

    op.create_table(
        "raw_import_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_platform_id", sa.Integer(), sa.ForeignKey("source_platforms.id"), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("operational_import_batches.id")),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("row_data", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("source_timestamp", sa.DateTime()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("validation_issues", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source_platform_id", "source_id", name="uq_raw_import_row_source"),
    )
    op.create_index("ix_raw_import_rows_tenant_id", "raw_import_rows", ["tenant_id"])
    op.create_index("ix_raw_import_row_tenant_batch", "raw_import_rows", ["tenant_id", "import_batch_id"])

    op.create_table(
        "normalized_delivery_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_platform_id", sa.Integer(), sa.ForeignKey("source_platforms.id"), nullable=False),
        sa.Column("source_delivery_id", sa.String(length=80), nullable=False),
        sa.Column("raw_row_id", sa.Integer(), sa.ForeignKey("raw_import_rows.id")),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id")),
        sa.Column("contract_branch_id", sa.Integer(), sa.ForeignKey("contract_branches.id")),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("workforce_teams.id")),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_timestamp", sa.DateTime()),
        sa.Column("distance_km", sa.Float()),
        sa.Column("revenue_amount", sa.Float()),
        sa.Column("cost_amount", sa.Float()),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'SAR'")),
        sa.Column("provenance", sa.Text()),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source_platform_id", "source_delivery_id", name="uq_normalized_delivery_fact"),
    )
    op.create_index("ix_normalized_delivery_facts_tenant_id", "normalized_delivery_facts", ["tenant_id"])
    op.create_index("ix_normalized_delivery_fact_tenant_date", "normalized_delivery_facts", ["tenant_id", "event_date"])
    op.create_index("ix_normalized_delivery_fact_rider", "normalized_delivery_facts", ["courier_id"])

    op.create_table(
        "reconciliation_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_platform_id", sa.Integer(), sa.ForeignKey("source_platforms.id"), nullable=False),
        sa.Column("reconciliation_date", sa.Date(), nullable=False),
        sa.Column("source_total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unmapped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_revenue_source", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_revenue_accepted", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("exception_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reconciliation_results_tenant_id", "reconciliation_results", ["tenant_id"])
    op.create_index("ix_reconciliation_tenant_platform_date", "reconciliation_results", ["tenant_id", "source_platform_id", "reconciliation_date"])


def downgrade() -> None:
    op.drop_table("reconciliation_results")
    op.drop_table("normalized_delivery_facts")
    op.drop_table("raw_import_rows")
    op.drop_table("rider_identity_mappings")
    op.drop_table("project_contract_mappings")
    op.drop_table("tenant_connections")
    op.drop_table("source_platforms")
