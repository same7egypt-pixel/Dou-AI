"""CSV rider-import preview and confirmation service.

No courier is created during preview. Confirmation uses the same shared rider
creation service as the individual company form and runs as one transaction.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.entities import (
    Contract,
    ContractBranch,
    Courier,
    OperationalImportBatch,
    User,
    UserRole,
)
from .operating_structure import (
    resolve_active_tenant_city_by_name,
    require_branch_assignment,
)
from .rider_management import canonical_phone, create_rider_record
from typing import Optional, Tuple

RIDER_IMPORT_HEADERS = [
    "name",
    "mobile",
    "initial_password",
    "national_id_or_iqama",
    "nationality",
    "city",
    "branch",
    "contract_or_project",
    "supervisor",
    "base_salary",
    "employment_status",
    "rider_rate_per_order",
    "vehicle_type",
    "vehicle_plate",
]

# The aliases preserve existing exported templates while the downloaded template stays clear.
RIDER_IMPORT_ALIASES = {
    "phone": "mobile",
    "iqama_number": "national_id_or_iqama",
    "contract": "contract_or_project",
    "status": "employment_status",
    "per_delivery_rate": "rider_rate_per_order",
}
REQUIRED_RIDER_IMPORT_HEADERS = {
    "name",
    "mobile",
    "initial_password",
    "city",
    "branch",
    "contract_or_project",
    "supervisor",
}


def _text(row: dict, key: str) -> str:
    return str(row.get(key) or "").strip()


def _field_error(row_number: int, field: str, reason: str, value: Any = None) -> dict:
    return {
        "row": row_number,
        "field": field,
        "value": "" if value is None else str(value),
        "reason": reason,
    }


def _canonical_row(row: dict) -> dict:
    """Map legacy headers only; values remain input data until relationship resolution."""
    canonical = {}
    for key, value in row.items():
        canonical[
            RIDER_IMPORT_ALIASES.get((key or "").strip(), (key or "").strip())
        ] = value
    return canonical


def rider_template_csv() -> str:
    """UTF-8 with BOM, one header row, and a non-personal QA example row."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=RIDER_IMPORT_HEADERS, lineterminator="\r\n"
    )
    writer.writeheader()
    writer.writerow(
        {
            "name": "Example Rider",
            "mobile": "966500000001",
            "initial_password": "TempPass123",
            "national_id_or_iqama": "2450000000",
            "nationality": "Egyptian",
            "city": "Riyadh",
            "branch": "Riyadh",
            "contract_or_project": "HungerStation Riyadh",
            "supervisor": "Example Supervisor",
            "base_salary": "2000",
            "employment_status": "ACTIVE",
            "rider_rate_per_order": "0",
            "vehicle_type": "Motorcycle",
            "vehicle_plate": "QA-1234",
        }
    )
    return "\ufeff" + output.getvalue()


def _resolve_contract(db: Session, tenant_id: int, value: str) -> Contract:
    rows = (
        db.query(Contract)
        .filter(
            Contract.tenant_id == tenant_id,
            func.lower(Contract.name) == value.casefold(),
        )
        .all()
    )
    if len(rows) != 1:
        raise ValueError("العقد غير معروف أو غير فريد داخل الشركة")
    return rows[0]


def _resolve_branch(
    db: Session, tenant_id: int, contract: Contract, city_id: int, value: str
) -> ContractBranch:
    rows = (
        db.query(ContractBranch)
        .filter(
            ContractBranch.tenant_id == tenant_id,
            ContractBranch.contract_id == contract.id,
            ContractBranch.city_id == city_id,
            ContractBranch.is_active.is_(True),
        )
        .all()
    )
    if value:
        matched = [
            row
            for row in rows
            if str(row.id) == value
            or (row.city or "").strip().casefold() == value.casefold()
        ]
        rows = matched
    if len(rows) != 1:
        raise ValueError("الفرع غير صالح أو لا يطابق العقد والمدينة")
    return rows[0]


def _resolve_supervisor(db: Session, tenant_id: int, name: str) -> User:
    if not name:
        raise ValueError("اسم المشرف مطلوب")
    rows = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.role == UserRole.SUPERVISOR,
            User.is_active.is_(True),
            func.lower(User.name) == name.casefold(),
        )
        .all()
    )
    if len(rows) != 1:
        raise ValueError(
            "المشرف غير معروف أو غير فريد داخل الشركة؛ استخدم الاسم المسجل بالكامل"
        )
    return rows[0]


def normalize_rider_row(
    db: Session, tenant_id: int, row: dict, row_number: int
) -> Tuple[Optional[dict], list[dict], list[dict]]:
    errors: list[dict] = []
    warnings: list[dict] = []
    name, raw_phone, password = (
        _text(row, "name"),
        _text(row, "mobile"),
        _text(row, "initial_password"),
    )
    if not name:
        errors.append(_field_error(row_number, "name", "اسم المندوب مطلوب", name))
    try:
        phone = canonical_phone(raw_phone)
    except ValueError as exc:
        errors.append(_field_error(row_number, "mobile", str(exc), raw_phone))
        phone = ""
    if password and len(password) < 8:
        errors.append(
            _field_error(
                row_number,
                "initial_password",
                "كلمة المرور يجب ألا تقل عن 8 أحرف",
                password,
            )
        )
    if not password:
        errors.append(
            _field_error(
                row_number, "initial_password", "كلمة المرور الأولية مطلوبة", password
            )
        )
    if phone and db.query(Courier).filter(Courier.phone == phone).first():
        errors.append(
            _field_error(row_number, "mobile", "رقم الجوال مستخدم بالفعل", raw_phone)
        )
    city = contract = branch = supervisor = None
    try:
        city = resolve_active_tenant_city_by_name(db, tenant_id, _text(row, "city"))
    except ValueError as exc:
        errors.append(_field_error(row_number, "city", str(exc), _text(row, "city")))
    try:
        contract = _resolve_contract(db, tenant_id, _text(row, "contract_or_project"))
    except ValueError as exc:
        errors.append(
            _field_error(
                row_number,
                "contract_or_project",
                str(exc),
                _text(row, "contract_or_project"),
            )
        )
    if city and contract:
        try:
            branch = _resolve_branch(
                db, tenant_id, contract, city.id, _text(row, "branch")
            )
        except ValueError as exc:
            errors.append(
                _field_error(row_number, "branch", str(exc), _text(row, "branch"))
            )
    try:
        supervisor = _resolve_supervisor(db, tenant_id, _text(row, "supervisor"))
    except ValueError as exc:
        errors.append(
            _field_error(row_number, "supervisor", str(exc), _text(row, "supervisor"))
        )
    if branch and supervisor and branch.supervisor_id != supervisor.id:
        errors.append(
            _field_error(
                row_number,
                "supervisor",
                "المشرف لا يطابق نطاق الفرع والمدينة",
                _text(row, "supervisor"),
            )
        )
    status = (_text(row, "employment_status") or "ACTIVE").upper()
    if status not in {"ACTIVE", "SUSPENDED"}:
        errors.append(
            _field_error(
                row_number,
                "employment_status",
                "الحالة يجب أن تكون ACTIVE أو SUSPENDED",
                status,
            )
        )
    for numeric in ("base_salary", "rider_rate_per_order"):
        raw = _text(row, numeric)
        if raw:
            try:
                if float(raw) < 0:
                    raise ValueError
            except ValueError:
                errors.append(
                    _field_error(
                        row_number, numeric, "القيمة يجب أن تكون رقماً غير سالب", raw
                    )
                )
    if errors:
        return None, errors, warnings
    try:
        # A final shared validation prevents preview and creation from drifting.
        require_branch_assignment(
            db, tenant_id, contract.id, branch.id, supervisor.id, city.id
        )
    except ValueError as exc:
        return (
            None,
            [_field_error(row_number, "assignment", str(exc), _text(row, "branch"))],
            warnings,
        )
    return (
        {
            "row": row_number,
            "name": name,
            "phone": phone,
            "password": password,
            "city_id": city.id,
            "contract_id": contract.id,
            "contract_branch_id": branch.id,
            "supervisor_id": supervisor.id,
            "nationality": _text(row, "nationality") or None,
            "iqama_number": _text(row, "national_id_or_iqama") or None,
            "base_salary": _text(row, "base_salary") or 0,
            "per_delivery_rate": _text(row, "rider_rate_per_order") or 0,
            "employment_status": status,
            "vehicle_type": _text(row, "vehicle_type") or None,
            "vehicle_plate": _text(row, "vehicle_plate") or None,
            "country": "SA",
            "courier_type": "COMPANY",
        },
        errors,
        warnings,
    )


def preview_rider_import(
    db: Session, user: User, csv_text: str, file_name: Optional[str] = None
) -> dict:
    content = (csv_text or "").replace("\ufeff", "")
    if not content.strip():
        raise ValueError("ملف CSV فارغ")
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    previous = (
        db.query(OperationalImportBatch)
        .filter(
            OperationalImportBatch.tenant_id == user.tenant_id,
            OperationalImportBatch.import_type == "RIDERS",
            OperationalImportBatch.fingerprint == fingerprint,
        )
        .first()
    )
    if previous and previous.status == "COMMITTED":
        raise ValueError("تم استيراد هذا الملف سابقاً؛ لن يعاد إدخال المناديب")
    try:
        rows = [_canonical_row(row) for row in csv.DictReader(io.StringIO(content))]
    except csv.Error as exc:
        raise ValueError(f"ملف CSV غير صالح: {exc}")
    if not rows:
        raise ValueError("ملف CSV لا يحتوي صفوفاً")
    if not REQUIRED_RIDER_IMPORT_HEADERS.issubset(set(rows[0].keys() if rows else [])):
        raise ValueError(
            "رؤوس CSV المطلوبة: "
            + ", ".join(
                [
                    "name",
                    "mobile",
                    "initial_password",
                    "city",
                    "branch",
                    "contract_or_project",
                    "supervisor",
                ]
            )
        )
    valid, errors, warnings, seen = [], [], [], set()
    for number, row in enumerate(rows, 2):
        normalized, row_errors, row_warnings = normalize_rider_row(
            db, user.tenant_id, row, number
        )
        if normalized and normalized["phone"] in seen:
            row_errors.append(
                _field_error(
                    number, "mobile", "رقم الجوال مكرر داخل الملف", _text(row, "mobile")
                )
            )
            normalized = None
        if normalized:
            seen.add(normalized["phone"])
            valid.append(normalized)
        errors.extend(row_errors)
        warnings.extend(row_warnings)
    payload = {"valid_rows": valid, "errors": errors, "warnings": warnings}
    if previous:
        batch = previous
        batch.status = "PREVIEW"
        batch.file_name = file_name
        batch.total_rows = len(rows)
        batch.valid_rows = len(valid)
        batch.invalid_rows = len({issue["row"] for issue in errors})
        batch.warning_rows = len({issue["row"] for issue in warnings})
        batch.payload_json = json.dumps(payload)
    else:
        batch = OperationalImportBatch(
            tenant_id=user.tenant_id,
            import_type="RIDERS",
            status="PREVIEW",
            file_name=file_name,
            fingerprint=fingerprint,
            source_label="FILE_IMPORT",
            total_rows=len(rows),
            valid_rows=len(valid),
            invalid_rows=len({issue["row"] for issue in errors}),
            warning_rows=len({issue["row"] for issue in warnings}),
            payload_json=json.dumps(payload),
            created_by=user.id,
        )
        db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch_summary(batch)


def batch_summary(batch: OperationalImportBatch) -> dict:
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


def confirm_rider_import(
    db: Session, user: User, batch: OperationalImportBatch
) -> dict:
    if batch.status == "COMMITTED":
        return batch_summary(batch)
    if batch.status != "PREVIEW":
        raise ValueError("دفعة الاستيراد ليست جاهزة للتأكيد")
    payload = json.loads(batch.payload_json or "{}")
    valid_rows = payload.get("valid_rows", [])
    if not valid_rows or payload.get("errors"):
        raise ValueError("صحح الصفوف غير الصالحة قبل تأكيد الاستيراد")
    imported = []
    try:
        for row in valid_rows:
            courier, _account = create_rider_record(db, user, row)
            imported.append(
                {"row": row["row"], "courier_id": courier.id, "phone": courier.phone}
            )
        batch.status = "COMMITTED"
        batch.confirmed_by = user.id
        batch.confirmed_at = datetime.utcnow()
        batch.result_json = json.dumps(
            {
                "imported": len(imported),
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "rows": imported,
            }
        )
        db.commit()
        db.refresh(batch)
    except Exception:
        db.rollback()
        raise
    return batch_summary(batch)
