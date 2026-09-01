"""Operational performance CSV import using DailyLog as the sole eligible-order source."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from ..models.entities import Courier, DailyLog, OperationalImportBatch, Project
from .rider_management import canonical_phone
from typing import Optional, Tuple

PERFORMANCE_HEADERS = ["rider_phone", "date", "project", "completed_orders", "notes"]


def performance_template_csv() -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=PERFORMANCE_HEADERS)
    writer.writeheader()
    writer.writerow(
        {
            "rider_phone": "966500000001",
            "date": "2026-08-01",
            "project": "Current Project Name",
            "completed_orders": "0",
            "notes": "Platform report row",
        }
    )
    return output.getvalue()


def _issue(row: int, field: str, reason: str) -> dict:
    return {"row": row, "field": field, "reason": reason}


def _text(row: dict, key: str) -> str:
    return str(row.get(key) or "").strip()


def _project_for_row(
    db: Session, tenant_id: int, courier: Courier, project_name: str
) -> Project:
    if not courier.primary_project_id:
        raise ValueError("المندوب غير مرتبط بمشروع تشغيلي")
    project = db.get(Project, courier.primary_project_id)
    if not project or project.tenant_id != tenant_id:
        raise ValueError("المندوب غير مرتبط بمشروع صحيح تابع للشركة")
    if project_name and project.name.casefold() != project_name.casefold():
        raise ValueError("المشروع في الملف لا يطابق مشروع المندوب الحالي")
    return project


def _normalize_row(
    db: Session, tenant_id: int, row: dict, row_number: int
) -> Tuple[Optional[dict], list[dict]]:
    errors: list[dict] = []
    try:
        phone = canonical_phone(_text(row, "rider_phone"))
    except ValueError as exc:
        errors.append(_issue(row_number, "rider_phone", str(exc)))
        phone = ""
    courier = (
        db.query(Courier)
        .filter(Courier.tenant_id == tenant_id, Courier.phone == phone)
        .first()
        if phone
        else None
    )
    if not courier:
        errors.append(
            _issue(row_number, "rider_phone", "المندوب غير تابع للشركة أو غير موجود")
        )
    try:
        log_date = date.fromisoformat(_text(row, "date"))
        if log_date > date.today():
            raise ValueError
    except ValueError:
        errors.append(_issue(row_number, "date", "التاريخ غير صالح أو مستقبلي"))
        log_date = None
    try:
        orders = int(_text(row, "completed_orders"))
        if orders < 0:
            raise ValueError
    except ValueError:
        errors.append(
            _issue(
                row_number,
                "completed_orders",
                "عدد الطلبات يجب أن يكون عدداً صحيحاً غير سالب",
            )
        )
        orders = 0
    project = None
    if courier:
        try:
            project = _project_for_row(db, tenant_id, courier, _text(row, "project"))
        except ValueError as exc:
            errors.append(_issue(row_number, "project", str(exc)))
    if errors:
        return None, errors
    existing = (
        db.query(DailyLog)
        .filter(
            DailyLog.courier_id == courier.id,
            DailyLog.project_id == project.id,
            DailyLog.log_date == log_date,
        )
        .first()
    )
    return {
        "row": row_number,
        "courier_id": courier.id,
        "project_id": project.id,
        "log_date": log_date.isoformat(),
        "orders_count": orders,
        "notes": _text(row, "notes") or None,
        "will_update": bool(existing),
        "row_key": f"{courier.id}:{project.id}:{log_date.isoformat()}",
    }, []


def _summary(batch: OperationalImportBatch) -> dict:
    payload = json.loads(batch.payload_json or "{}")
    result = json.loads(batch.result_json or "{}")
    return {
        "id": batch.id,
        "import_type": batch.import_type,
        "status": batch.status,
        "file_name": batch.file_name,
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "invalid_rows": batch.invalid_rows,
        "warning_rows": batch.warning_rows,
        "errors": payload.get("errors", []),
        "warnings": payload.get("warnings", []),
        "result": result,
    }


def preview_performance_import(
    db: Session, user, csv_text: str, file_name: Optional[str] = None
) -> dict:
    content = (csv_text or "").replace("\ufeff", "")
    if not content.strip():
        raise ValueError("ملف CSV فارغ")
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    previous = (
        db.query(OperationalImportBatch)
        .filter(
            OperationalImportBatch.tenant_id == user.tenant_id,
            OperationalImportBatch.import_type == "PERFORMANCE",
            OperationalImportBatch.fingerprint == fingerprint,
        )
        .first()
    )
    if previous and previous.status == "COMMITTED":
        raise ValueError("تم استيراد هذا الملف سابقاً؛ لن تتضاعف الطلبات")
    rows = list(csv.DictReader(io.StringIO(content)))
    if not rows or not set(PERFORMANCE_HEADERS[:4]).issubset(set(rows[0].keys())):
        raise ValueError("رؤوس CSV المطلوبة: " + ", ".join(PERFORMANCE_HEADERS[:4]))
    valid, errors, seen = [], [], set()
    for number, row in enumerate(rows, 2):
        normalized, row_errors = _normalize_row(db, user.tenant_id, row, number)
        if normalized and normalized["row_key"] in seen:
            row_errors.append(
                _issue(number, "rider_phone/date/project", "سجل الأداء مكرر داخل الملف")
            )
            normalized = None
        if normalized:
            seen.add(normalized["row_key"])
            valid.append(normalized)
        errors.extend(row_errors)
    warnings = [
        {
            "row": row["row"],
            "field": "completed_orders",
            "reason": "سيتم استبدال قيمة سجل اليوم القائم من هذا الملف",
        }
        for row in valid
        if row["will_update"]
    ]
    payload = {"valid_rows": valid, "errors": errors, "warnings": warnings}
    if previous:
        batch = previous
        batch.status = "PREVIEW"
        batch.file_name = file_name
        batch.total_rows = len(rows)
        batch.valid_rows = len(valid)
        batch.invalid_rows = len({issue["row"] for issue in errors})
        batch.warning_rows = len(warnings)
        batch.payload_json = json.dumps(payload)
    else:
        batch = OperationalImportBatch(
            tenant_id=user.tenant_id,
            import_type="PERFORMANCE",
            status="PREVIEW",
            file_name=file_name,
            fingerprint=fingerprint,
            source_label="FILE_IMPORT",
            total_rows=len(rows),
            valid_rows=len(valid),
            invalid_rows=len({issue["row"] for issue in errors}),
            warning_rows=len(warnings),
            payload_json=json.dumps(payload),
            created_by=user.id,
        )
        db.add(batch)
    db.commit()
    db.refresh(batch)
    return _summary(batch)


def confirm_performance_import(
    db: Session, user, batch: OperationalImportBatch
) -> dict:
    if batch.status == "COMMITTED":
        return _summary(batch)
    if batch.status != "PREVIEW":
        raise ValueError("دفعة الأداء ليست جاهزة للتأكيد")
    payload = json.loads(batch.payload_json or "{}")
    rows = payload.get("valid_rows", [])
    if not rows or payload.get("errors"):
        raise ValueError("صحح صفوف الأداء غير الصالحة قبل التأكيد")
    imported = updated = 0
    try:
        for row in rows:
            log_date = date.fromisoformat(row["log_date"])
            log = (
                db.query(DailyLog)
                .filter(
                    DailyLog.courier_id == row["courier_id"],
                    DailyLog.project_id == row["project_id"],
                    DailyLog.log_date == log_date,
                )
                .first()
            )
            if log:
                log.orders_count = row["orders_count"]
                log.notes = row.get("notes") or log.notes
                updated += 1
            else:
                log = DailyLog(
                    courier_id=row["courier_id"],
                    tenant_id=user.tenant_id,
                    project_id=row["project_id"],
                    log_date=log_date,
                    orders_count=row["orders_count"],
                    notes=row.get("notes"),
                )
                db.add(log)
                imported += 1
            log.source_type = "FILE_IMPORT"
            log.source_batch_id = batch.id
            log.source_row_key = row["row_key"]
        batch.status = "COMMITTED"
        batch.confirmed_by = user.id
        batch.confirmed_at = datetime.utcnow()
        batch.result_json = json.dumps(
            {"imported": imported, "updated": updated, "skipped": 0, "failed": 0}
        )
        db.commit()
        db.refresh(batch)
    except Exception:
        db.rollback()
        raise
    return _summary(batch)
