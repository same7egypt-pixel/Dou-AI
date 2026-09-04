"""Operational performance CSV import using DailyLog as the sole eligible-order source."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.entities import (
    Courier,
    DailyLog,
    OperationalImportBatch,
    Project,
    RiderIdentityMapping,
    SourcePlatform,
    User,
)
from .rider_management import canonical_phone

PERFORMANCE_HEADERS = ["rider_phone", "date", "project", "completed_orders", "notes"]

SYNONYMS = {
    "rider_identifier": [
        "rider_phone", "phone", "mobile", "rider_mobile", "driver_phone", "mobile_number",
        "phone_number", "رقم الجوال", "الجوال", "الهاتف", "رقم الهاتف", "جوال المندوب",
        "platform_courier_id", "rider_code", "courier_code", "driver_code", "driver_id", "rider_id", "courier_id",
        "كود السائق", "كود المندوب", "رقم السائق", "معرف السائق", "رقم المندوب", "السائق", "المندوب",
        "iqama", "iqama_number", "national_id", "رقم الإقامة", "الهوية", "رقم الهوية",
    ],
    "date": [
        "date", "log_date", "delivery_date", "order_date", "day", "shift_date",
        "التاريخ", "تاريخ التوصيل", "يوم العمل", "تاريخ الطلب", "تاريخ الوردية", "اليوم",
    ],
    "completed_orders": [
        "completed_orders", "orders", "delivered_orders", "verified_orders", "delivered",
        "successful_orders", "total_orders", "orders_count", "trips", "deliveries",
        "الطلبات", "عدد الطلبات", "الطلبات المكتملة", "الطلبات المسلمة", "الطلبات المؤكدة", "الطلبات الناجحة", "التوصيلات",
    ],
    "project": [
        "project", "project_name", "hub", "branch", "platform", "contract", "zone",
        "المشروع", "الفرع", "المنطقة", "الهب", "المنصة", "العقد",
    ],
    "notes": [
        "notes", "note", "comments", "remarks", "description", "ملاحظات", "ملاحظة", "بيان",
    ],
}

PLATFORM_SIGNATURES = {
    "HUNGERSTATION": ["hungerstation", "هنقرستيشن", "rider code", "delivered orders"],
    "NINJA": ["ninja", "نينجا", "courier id", "verified orders", "الطلبات المؤكدة"],
    "JAHEZ": ["jahez", "جاهز", "driver code", "successful deliveries"],
    "TOYOU": ["toyou", "تويو"],
}


def _clean_header(header: str) -> str:
    return str(header or "").strip().lower().replace("_", " ").replace("-", " ")


def detect_platform_and_map_headers(
    raw_headers: list[str],
    source_hint: Optional[str] = "AUTO",
    file_name: Optional[str] = None,
) -> tuple[str, dict[str, str]]:
    """Detect platform format and map CSV headers to internal canonical fields."""
    cleaned_map = {_clean_header(h): h for h in raw_headers if h}
    mapping: dict[str, str] = {}

    for canonical_field, syn_list in SYNONYMS.items():
        found = None
        for syn in syn_list:
            clean_syn = _clean_header(syn)
            # Exact match
            if clean_syn in cleaned_map:
                found = cleaned_map[clean_syn]
                break
        if not found:
            # Partial match if no exact
            for syn in syn_list:
                clean_syn = _clean_header(syn)
                for clean_h, raw_h in cleaned_map.items():
                    if clean_syn == clean_h or clean_syn in clean_h.split():
                        found = raw_h
                        break
                if found:
                    break
        if found:
            mapping[canonical_field] = found

    # Determine platform
    detected_platform = "DOU_GENERIC"
    hint = (source_hint or "AUTO").upper()
    if hint in PLATFORM_SIGNATURES:
        detected_platform = hint
    else:
        search_corpus = " ".join(cleaned_map.keys()) + " " + _clean_header(file_name or "")
        for plat, sigs in PLATFORM_SIGNATURES.items():
            if any(_clean_header(sig) in search_corpus for sig in sigs):
                detected_platform = plat
                break
        if detected_platform == "DOU_GENERIC" and not set(PERFORMANCE_HEADERS[:4]).issubset(set(raw_headers)):
            detected_platform = "SMART_DETECTED"

    # Validate mandatory fields
    missing = []
    if "rider_identifier" not in mapping:
        missing.append("معرف السائق (جوال / كود المندوب / الإقامة)")
    if "date" not in mapping:
        missing.append("التاريخ (date / log_date)")
    if "completed_orders" not in mapping:
        missing.append("عدد الطلبات المكتملة (completed_orders / delivered)")

    if missing:
        raise ValueError(
            f"تعذر التعرف التلقائي على الأعمدة المطلوبة في الملف: {', '.join(missing)}. "
            "يرجى التأكد من احتواء الملف على أعمدة السائق والتاريخ والطلبات."
        )

    return detected_platform, mapping


def _parse_flexible_date(raw: str) -> date:
    raw = str(raw or "").strip()
    if not raw:
        raise ValueError("تاريخ فارغ")
    raw = raw.split(" ")[0].split("T")[0]
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y")
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt).date()
            if parsed > date.today():
                raise ValueError("التاريخ في الملف مستقبلي")
            return parsed
        except ValueError as e:
            if "مستقبلي" in str(e):
                raise
            continue
    raise ValueError(f"تنسيق التاريخ غير صالح: {raw}")


def _resolve_courier(
    db: Session,
    tenant_id: int,
    identifier: str,
    source_platform_code: Optional[str] = None,
) -> Optional[Courier]:
    raw = str(identifier or "").strip()
    if not raw:
        return None

    # 1. Try RiderIdentityMapping (source-specific identity mappings table)
    mapping_query = (
        db.query(RiderIdentityMapping)
        .filter(
            RiderIdentityMapping.tenant_id == tenant_id,
            RiderIdentityMapping.source_rider_id == raw,
            RiderIdentityMapping.status == "ACTIVE",
        )
    )
    if source_platform_code and source_platform_code not in ("AUTO", "DOU_GENERIC", "SMART_DETECTED"):
        platform = (
            db.query(SourcePlatform)
            .filter(
                SourcePlatform.tenant_id == tenant_id,
                SourcePlatform.code == source_platform_code.upper(),
            )
            .first()
        )
        if platform:
            mapping_query = mapping_query.filter(
                RiderIdentityMapping.source_platform_id == platform.id
            )
    mapping = mapping_query.first()
    if mapping:
        courier = db.get(Courier, mapping.courier_id)
        if courier and courier.tenant_id == tenant_id:
            return courier

    # 2. Try platform_courier_id directly on Courier
    courier = db.query(Courier).filter(
        Courier.tenant_id == tenant_id, Courier.platform_courier_id == raw
    ).first()
    if courier:
        return courier

    # 3. Try canonical phone
    try:
        phone = canonical_phone(raw)
        courier = db.query(Courier).filter(Courier.tenant_id == tenant_id, Courier.phone == phone).first()
        if courier:
            return courier
    except Exception:
        pass

    # 4. Try raw phone directly
    courier = db.query(Courier).filter(Courier.tenant_id == tenant_id, Courier.phone == raw).first()
    if courier:
        return courier

    # 5. Try iqama_number
    courier = db.query(Courier).filter(
        Courier.tenant_id == tenant_id, Courier.iqama_number == raw
    ).first()
    if courier:
        return courier

    return None


def _resolve_project(db: Session, tenant_id: int, courier: Courier, project_text: str) -> Project:
    clean_p = str(project_text or "").strip()
    if clean_p:
        match = (
            db.query(Project)
            .filter(
                Project.tenant_id == tenant_id,
                func.lower(Project.name) == func.lower(clean_p),
            )
            .first()
        )
        if match:
            return match

    if courier.primary_project_id:
        proj = db.get(Project, courier.primary_project_id)
        if proj and proj.tenant_id == tenant_id:
            return proj

    fallback = db.query(Project).filter(Project.tenant_id == tenant_id).first()
    if fallback:
        return fallback

    raise ValueError("المندوب غير مرتبط بمشروع تشغيلي، ولا يوجد مشروع متاح في النظام")


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


def _normalize_row(
    db: Session,
    tenant_id: int,
    row: dict,
    row_number: int,
    mapping: Optional[dict[str, str]] = None,
    source_platform: Optional[str] = None,
) -> Tuple[Optional[dict], list[dict]]:
    errors: list[dict] = []

    # Extract fields via mapping or standard keys
    id_key = mapping.get("rider_identifier", "rider_phone") if mapping else "rider_phone"
    date_key = mapping.get("date", "date") if mapping else "date"
    orders_key = mapping.get("completed_orders", "completed_orders") if mapping else "completed_orders"
    proj_key = mapping.get("project", "project") if mapping else "project"
    notes_key = mapping.get("notes", "notes") if mapping else "notes"

    raw_id = _text(row, id_key)
    courier = (
        _resolve_courier(db, tenant_id, raw_id, source_platform_code=source_platform)
        if raw_id
        else None
    )
    if not courier:
        errors.append(
            _issue(row_number, id_key, f"لم يتم العثور على المندوب في النظام بواسطة المعرف '{raw_id}'")
        )

    raw_date = _text(row, date_key)
    try:
        log_date = _parse_flexible_date(raw_date)
    except ValueError as exc:
        errors.append(_issue(row_number, date_key, str(exc)))
        log_date = None

    raw_orders = _text(row, orders_key)
    try:
        orders = int(float(raw_orders)) if raw_orders else 0
        if orders < 0:
            raise ValueError
    except ValueError:
        errors.append(
            _issue(
                row_number,
                orders_key,
                "عدد الطلبات يجب أن يكون عدداً صحيحاً غير سالب",
            )
        )
        orders = 0

    project = None
    if courier:
        try:
            project = _resolve_project(db, tenant_id, courier, _text(row, proj_key))
        except ValueError as exc:
            errors.append(_issue(row_number, proj_key, str(exc)))

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
    supervisor_name = None
    if courier and courier.supervisor_id:
        sup = db.get(User, courier.supervisor_id)
        if sup:
            supervisor_name = sup.name

    return {
        "row": row_number,
        "courier_id": courier.id,
        "courier_name": courier.name,
        "platform_courier_id": courier.platform_courier_id,
        "courier_phone": courier.phone,
        "city_name": courier.work_city or "غير محدد",
        "supervisor_name": supervisor_name or "بدون مشرف",
        "project_id": project.id,
        "project_name": project.name if project else None,
        "log_date": log_date.isoformat(),
        "orders_count": orders,
        "notes": _text(row, notes_key) or None,
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
        "detected_platform": payload.get("detected_platform", "DOU_GENERIC"),
        "mapped_columns": payload.get("mapped_columns", {}),
        "errors": payload.get("errors", []),
        "warnings": payload.get("warnings", []),
        "analytics": payload.get("analytics", {}),
        "valid_rows_preview": payload.get("valid_rows", [])[:50],
        "result": result,
    }


def preview_performance_import(
    db: Session,
    user,
    csv_text: str,
    file_name: Optional[str] = None,
    source_platform: Optional[str] = "AUTO",
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
    reader = csv.DictReader(io.StringIO(content))
    raw_headers = list(reader.fieldnames or [])
    if not raw_headers:
        raise ValueError("الملف لا يحتوي على رؤوس أعمدة صالحة")

    detected_platform, mapping = detect_platform_and_map_headers(
        raw_headers, source_hint=source_platform, file_name=file_name
    )
    rows = list(reader)
    if not rows:
        raise ValueError("الملف لا يحتوي على صفوف بيانات صالحة")

    valid, errors, seen = [], [], set()
    for number, row in enumerate(rows, 2):
        normalized, row_errors = _normalize_row(
            db, user.tenant_id, row, number, mapping=mapping, source_platform=detected_platform
        )
        if normalized and normalized["row_key"] in seen:
            row_errors.append(
                _issue(number, "rider_identifier/date/project", "سجل الأداء مكرر داخل الملف")
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

    # Aggregate performance analytics by city, supervisor, and courier
    city_stats = {}
    sup_stats = {}
    courier_totals = {}
    for r in valid:
        c_city = r.get("city_name") or "غير محدد"
        c_sup = r.get("supervisor_name") or "بدون مشرف"
        orders_num = r.get("orders_count") or 0
        cid = r.get("courier_id")

        if c_city not in city_stats:
            city_stats[c_city] = {"city": c_city, "orders": 0, "riders": set()}
        city_stats[c_city]["orders"] += orders_num
        city_stats[c_city]["riders"].add(cid)

        if c_sup not in sup_stats:
            sup_stats[c_sup] = {"supervisor": c_sup, "orders": 0, "riders": set()}
        sup_stats[c_sup]["orders"] += orders_num
        sup_stats[c_sup]["riders"].add(cid)

        if cid not in courier_totals:
            courier_totals[cid] = {
                "courier_id": cid,
                "courier_name": r.get("courier_name"),
                "platform_courier_id": r.get("platform_courier_id"),
                "city_name": c_city,
                "supervisor_name": c_sup,
                "total_orders": 0,
                "days_count": 0,
            }
        courier_totals[cid]["total_orders"] += orders_num
        courier_totals[cid]["days_count"] += 1

    by_city = [
        {"city": k, "orders": v["orders"], "riders_count": len(v["riders"])}
        for k, v in sorted(city_stats.items(), key=lambda x: x[1]["orders"], reverse=True)
    ]
    by_supervisor = [
        {"supervisor": k, "orders": v["orders"], "riders_count": len(v["riders"])}
        for k, v in sorted(sup_stats.items(), key=lambda x: x[1]["orders"], reverse=True)
    ]
    matched_couriers = sorted(
        courier_totals.values(), key=lambda x: x["total_orders"], reverse=True
    )

    analytics = {
        "by_city": by_city,
        "by_supervisor": by_supervisor,
        "matched_couriers": matched_couriers,
        "total_matched_riders": len(courier_totals),
        "total_orders": sum(r.get("orders_count", 0) for r in valid),
    }

    payload = {
        "valid_rows": valid,
        "errors": errors,
        "warnings": warnings,
        "detected_platform": detected_platform,
        "mapped_columns": mapping,
        "analytics": analytics,
    }
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
