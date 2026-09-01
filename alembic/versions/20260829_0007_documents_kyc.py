"""Add documents and KYC pipeline.

Revision ID: 20260829_0007
Revises: 20260829_0006
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0007"
down_revision: Union[str, Sequence[str], None] = "20260829_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120)),
        sa.Column("description_ar", sa.String(length=300)),
        sa.Column("description_en", sa.String(length=300)),
        sa.Column("category", sa.String(length=30), nullable=False, server_default=sa.text("'RIDER'")),
        sa.Column("requires_expiry", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_document_type_tenant_code"),
    )
    op.create_index("ix_document_types_tenant_id", "document_types", ["tenant_id"])
    op.create_index("ix_document_type_tenant_active", "document_types", ["tenant_id", "is_active"])

    op.create_table(
        "document_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_type_id", sa.Integer(), sa.ForeignKey("document_types.id"), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("market_code", sa.String(length=2), nullable=False, server_default=sa.text("'SA'")),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "document_type_id", "scope", "market_code", name="uq_document_requirement"),
    )
    op.create_index("ix_document_requirements_tenant_id", "document_requirements", ["tenant_id"])
    op.create_index("ix_document_requirement_tenant_scope", "document_requirements", ["tenant_id", "scope"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_type_id", sa.Integer(), sa.ForeignKey("document_types.id"), nullable=False),
        sa.Column("owner_type", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=180), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("storage_bucket", sa.String(length=120), nullable=False, server_default=sa.text("'dou-documents'")),
        sa.Column("checksum_sha256", sa.String(length=64)),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("scan_status", sa.String(length=20), nullable=False, server_default=sa.text("'CLEAN'")),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("review_note", sa.String(length=300)),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_document_tenant_owner", "documents", ["tenant_id", "owner_type", "owner_id"])
    op.create_index("ix_document_tenant_type", "documents", ["tenant_id", "document_type_id"])

    op.create_table(
        "kyc_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("missing_documents", sa.Text()),
        sa.Column("notes", sa.String(length=300)),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "courier_id", name="uq_kyc_status_tenant_courier"),
    )
    op.create_index("ix_kyc_statuses_tenant_id", "kyc_statuses", ["tenant_id"])
    op.create_index("ix_kyc_status_tenant_status", "kyc_statuses", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("kyc_statuses")
    op.drop_table("documents")
    op.drop_table("document_requirements")
    op.drop_table("document_types")
