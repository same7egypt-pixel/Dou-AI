"""W6: Unified import history, retry, and order/raw-data ingestion workflow."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user


router = APIRouter(prefix="/imports", tags=["imports"])

MANAGE_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
}
ADMIN_ROLES = {ent.UserRole.COMPANY_ADMIN, ent.UserRole.DOU_ADMIN, ent.UserRole.DOU_OPS}


def _tenant_id(user: ent.User) -> int:
    if not user.tenant_id:
        raise HTTPException(403, "Tenant access required")
    return user.tenant_id


@router.get("/history")
def list_import_history(
    import_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    """List import history for the tenant with optional filters."""
    tenant_id = _tenant_id(user)
    q = db.query(ent.OperationalImportBatch).filter(
        ent.OperationalImportBatch.tenant_id == tenant_id
    )
    if import_type:
        q = q.filter(ent.OperationalImportBatch.import_type == import_type)
    if status_filter:
        q = q.filter(ent.OperationalImportBatch.status == status_filter)

    total = q.count()
    rows = (
        q.order_by(desc(ent.OperationalImportBatch.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_batch_summary(b) for b in rows],
    }


@router.get("/{batch_id}")
def get_import_detail(
    batch_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Get full import batch detail including errors/warnings."""
    tenant_id = _tenant_id(user)
    batch = (
        db.query(ent.OperationalImportBatch)
        .filter(
            ent.OperationalImportBatch.id == batch_id,
            ent.OperationalImportBatch.tenant_id == tenant_id,
        )
        .first()
    )
    if not batch:
        raise HTTPException(404, "Import batch not found")
    return _batch_detail(batch)


@router.post("/{batch_id}/retry")
def retry_failed_rows(
    batch_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Retry import for previously failed/invalid rows only."""
    tenant_id = _tenant_id(user)
    batch = (
        db.query(ent.OperationalImportBatch)
        .filter(
            ent.OperationalImportBatch.id == batch_id,
            ent.OperationalImportBatch.tenant_id == tenant_id,
        )
        .first()
    )
    if not batch:
        raise HTTPException(404, "Import batch not found")
    if batch.status == "COMMITTED":
        raise HTTPException(409, "Batch already committed")

    # Re-run preview on the original file
    # The fingerprint check will find the existing batch and update it

    if batch.import_type == "RIDERS":
        # Re-process with original payload
        payload_data = batch.payload_json or "{}"
        import json

        json.loads(payload_data)
        # Create new preview with original CSV text
        # User must re-upload for retry
        raise HTTPException(400, "Please re-upload the file to retry with corrections")
    else:
        raise HTTPException(400, "Retry not supported for this import type")


@router.delete("/{batch_id}")
def cancel_import_batch(
    batch_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Cancel a PREVIEW batch before confirmation."""
    tenant_id = _tenant_id(user)
    if user.role not in ADMIN_ROLES:
        raise HTTPException(403, "Admin access required")
    batch = (
        db.query(ent.OperationalImportBatch)
        .filter(
            ent.OperationalImportBatch.id == batch_id,
            ent.OperationalImportBatch.tenant_id == tenant_id,
        )
        .first()
    )
    if not batch:
        raise HTTPException(404, "Import batch not found")
    if batch.status == "COMMITTED":
        raise HTTPException(409, "Cannot delete committed batch")
    db.delete(batch)
    db.commit()
    return {"ok": True}


def _batch_summary(batch: ent.OperationalImportBatch) -> dict:
    import json

    return {
        "id": batch.id,
        "import_type": batch.import_type,
        "status": batch.status,
        "file_name": batch.file_name,
        "source_label": batch.source_label,
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "invalid_rows": batch.invalid_rows,
        "warning_rows": batch.warning_rows,
        "created_at": batch.created_at.isoformat(),
        "confirmed_at": batch.confirmed_at.isoformat() if batch.confirmed_at else None,
        "created_by": batch.created_by,
        "result": json.loads(batch.result_json) if batch.result_json else None,
    }


def _batch_detail(batch: ent.OperationalImportBatch) -> dict:
    import json

    payload = json.loads(batch.payload_json) if batch.payload_json else {}
    result = json.loads(batch.result_json) if batch.result_json else {}
    return {
        "id": batch.id,
        "import_type": batch.import_type,
        "status": batch.status,
        "file_name": batch.file_name,
        "source_label": batch.source_label,
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "invalid_rows": batch.invalid_rows,
        "warning_rows": batch.warning_rows,
        "errors": payload.get("errors", []),
        "warnings": payload.get("warnings", []),
        "valid_rows_preview": payload.get("valid_rows", [])[:100],  # Limit preview
        "result": result,
        "created_at": batch.created_at.isoformat(),
        "confirmed_at": batch.confirmed_at.isoformat() if batch.confirmed_at else None,
        "created_by": batch.created_by,
    }
