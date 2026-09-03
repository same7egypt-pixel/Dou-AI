"""Turning a raw source row into a delivery fact.

The pipeline CLAUDE.md describes — RawImportRow → RiderIdentityMapping /
ProjectContractMapping → NormalizedDeliveryFact — was missing its middle arrow.
`RawImportRow.status` documents PENDING / ACCEPTED / REJECTED / NORMALIZED and
nothing in the codebase had ever written anything but the default: rows landed
and stayed PENDING forever. Meanwhile the Ninja live endpoint wrote facts
directly, with no raw row behind them, so a delivery a rider was paid for had no
record of what produced it — `provenance` and `raw_row_id` are columns on the
fact and both were always null.

One function does the work for both paths, so a fact means the same thing
whether it arrived over the API or was posted as a row. Every fact carries the
row it came from and the mappings that resolved it.

A row that cannot be normalized is not dropped and not silently retried: it goes
to REJECTED with the reason in `validation_issues`, which is what the
integration screen shows the operator. Adding the missing mapping and pressing
reprocess is the fix, and it is the whole reason `reprocess` exists.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import entities as ent

# What the normalizer reads out of `row_data`. A source names these differently,
# so each field lists the keys accepted for it. Nothing else is guessed at: a
# row missing a required field is rejected with that field named, rather than
# producing a fact with a hole in it.
DELIVERY_ID_KEYS = ("delivery_id", "order_id", "source_delivery_id", "id")
RIDER_ID_KEYS = ("rider_id", "ninja_rider_id", "driver_id", "source_rider_id")
DATE_KEYS = ("event_date", "date", "delivered_at", "completed_at", "event_timestamp")
# `delivery_status` comes first deliberately: a source names the delivery's
# outcome there, while `event_type` is the name of the message ("Ninja sends
# DELIVERY_COMPLETED"). Reading the message name as the outcome rejected
# every live Ninja event as "حالة توصيل غير معروفة".
STATUS_KEYS = ("delivery_status", "status", "event_type")
PROJECT_KEYS = ("project_code", "project", "source_project_id")

# A source says DELIVERED; the fact vocabulary is COMPLETED.
STATUS_MAP = {
    "DELIVERED": "COMPLETED",
    "COMPLETED": "COMPLETED",
    "SUCCESS": "COMPLETED",
    "CANCELLED": "CANCELLED",
    "CANCELED": "CANCELLED",
    "FAILED": "FAILED",
    "RETURNED": "FAILED",
    # Message names, for a source that sends only those.
    "DELIVERY_COMPLETED": "COMPLETED",
    "DELIVERY_CANCELLED": "CANCELLED",
    "DELIVERY_FAILED": "FAILED",
}


class RowRejected(Exception):
    """The row cannot become a fact, and the reason is worth showing."""

    def __init__(self, reason: str, field: Optional[str] = None):
        super().__init__(reason)
        self.reason = reason
        self.field = field


def _first(data: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise RowRejected(f"تاريخ غير مفهوم: {value!r}", "event_date") from exc


def _as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_courier(
    db: Session,
    tenant_id: int,
    source_platform_id: int,
    source_rider_id: str,
    source_phone: Optional[str] = None,
) -> ent.Courier:
    """The rider this row belongs to, or a rejection naming the id that failed.

    An unmapped rider is the single most common reason a row cannot be
    normalized, and it is fixable by the operator in one action — which is why
    the reason carries the source's own id rather than a generic failure.
    """
    mapping = (
        db.query(ent.RiderIdentityMapping)
        .filter(
            ent.RiderIdentityMapping.tenant_id == tenant_id,
            ent.RiderIdentityMapping.source_platform_id == source_platform_id,
            ent.RiderIdentityMapping.source_rider_id == str(source_rider_id),
            ent.RiderIdentityMapping.status == "ACTIVE",
        )
        .first()
    )
    if mapping:
        courier = db.get(ent.Courier, mapping.courier_id)
        if courier and courier.tenant_id == tenant_id:
            return courier

    # The platform's own id may already be on the rider record.
    courier = (
        db.query(ent.Courier)
        .filter(
            ent.Courier.tenant_id == tenant_id,
            ent.Courier.platform_courier_id == str(source_rider_id),
        )
        .first()
    )
    if courier:
        return courier

    # A source that sends the rider's phone identifies them without any mapping
    # having been made. The live Ninja path matched on this first, and routing
    # it through here must not narrow who gets matched.
    if source_phone:
        courier = (
            db.query(ent.Courier)
            .filter(
                ent.Courier.tenant_id == tenant_id,
                ent.Courier.phone == str(source_phone).replace("+", "").strip(),
            )
            .first()
        )
        if courier:
            return courier

    raise RowRejected(
        f"لا يوجد مندوب مرتبط بمعرّف المصدر «{source_rider_id}» — "
        "أضف المطابقة ثم أعد المعالجة",
        "source_rider_id",
    )


def resolve_project(
    db: Session, tenant_id: int, source_platform_id: int
) -> Optional[ent.Project]:
    """The project this platform's deliveries belong to, if one is mapped.

    Optional on purpose: a fact without a project is still a delivery the rider
    made and must be paid for. A missing project mapping degrades reporting, it
    does not invalidate the delivery.
    """
    mapping = (
        db.query(ent.ProjectContractMapping)
        .filter(
            ent.ProjectContractMapping.tenant_id == tenant_id,
            ent.ProjectContractMapping.source_platform_id == source_platform_id,
            ent.ProjectContractMapping.is_active.is_(True),
        )
        .first()
    )
    if not mapping:
        return None
    project = db.get(ent.Project, mapping.project_id)
    return project if project and project.tenant_id == tenant_id else None


def normalize_row(db: Session, row: ent.RawImportRow) -> Optional[ent.NormalizedDeliveryFact]:
    """Produce the fact for one raw row, or mark the row rejected.

    Commits nothing — the caller owns the transaction, so a batch reprocess is
    one commit rather than one per row.
    """
    try:
        data = json.loads(row.row_data)
        if not isinstance(data, dict):
            raise RowRejected("row_data ليس كائن JSON", "row_data")

        delivery_id = _first(data, DELIVERY_ID_KEYS)
        if not delivery_id:
            raise RowRejected(
                "لا يوجد معرّف توصيلة في الصف (delivery_id / order_id)",
                "source_delivery_id",
            )

        rider_id = _first(data, RIDER_ID_KEYS)
        if not rider_id:
            raise RowRejected(
                "لا يوجد معرّف مندوب في الصف (rider_id / driver_id)",
                "source_rider_id",
            )

        raw_date = _first(data, DATE_KEYS) or row.source_timestamp
        if not raw_date:
            raise RowRejected("لا يوجد تاريخ للحدث في الصف", "event_date")
        event_date = _as_date(raw_date)

        raw_status = _first(data, STATUS_KEYS) or "COMPLETED"
        event_type = STATUS_MAP.get(str(raw_status).strip().upper())
        if not event_type:
            raise RowRejected(f"حالة توصيل غير معروفة: {raw_status!r}", "event_type")

        courier = resolve_courier(
            db,
            row.tenant_id,
            row.source_platform_id,
            str(rider_id),
            _first(data, ("rider_phone", "phone", "driver_phone")),
        )
        project = resolve_project(db, row.tenant_id, row.source_platform_id)

    except RowRejected as rejected:
        row.status = "REJECTED"
        row.validation_issues = json.dumps(
            [{"field": rejected.field, "reason": rejected.reason}], ensure_ascii=False
        )
        return None

    idempotency_key = (
        f"{row.tenant_id}:{row.source_platform_id}:{delivery_id}"
    )
    existing = (
        db.query(ent.NormalizedDeliveryFact)
        .filter(
            ent.NormalizedDeliveryFact.tenant_id == row.tenant_id,
            (
                (ent.NormalizedDeliveryFact.idempotency_key == idempotency_key)
                | (
                    ent.NormalizedDeliveryFact.source_delivery_id
                    == str(delivery_id)
                )
            ),
        )
        .first()
    )
    if existing:
        # The same delivery arriving twice is not an error, and it must not
        # produce a second row the rider is paid for. Late-arriving detail is
        # filled in; nothing already recorded is overwritten.
        if existing.courier_id is None:
            existing.courier_id = courier.id
        if existing.project_id is None and project is not None:
            existing.project_id = project.id
        if existing.raw_row_id is None:
            existing.raw_row_id = row.id
        row.status = "NORMALIZED"
        row.validation_issues = None
        return existing

    fact = ent.NormalizedDeliveryFact(
        tenant_id=row.tenant_id,
        source_platform_id=row.source_platform_id,
        source_delivery_id=str(delivery_id),
        raw_row_id=row.id,
        courier_id=courier.id,
        project_id=project.id if project else None,
        event_type=event_type,
        event_date=event_date,
        event_timestamp=row.source_timestamp,
        distance_km=_as_float(_first(data, ("distance_km", "distance"))),
        revenue_amount=_as_float(_first(data, ("revenue_amount", "delivery_fee", "revenue"))),
        cost_amount=_as_float(_first(data, ("cost_amount", "cost"))),
        currency=data.get("currency") or "SAR",
        # Lineage: which row, which checksum, which mappings resolved it. A
        # number in payroll has to be answerable for months later.
        provenance=json.dumps(
            {
                "raw_row_id": row.id,
                "source_id": row.source_id,
                "checksum": row.checksum,
                "schema_version": row.schema_version,
                "source_rider_id": str(rider_id),
                "resolved_courier_id": courier.id,
                "resolved_project_id": project.id if project else None,
                "normalized_at": datetime.utcnow().isoformat(),
            },
            ensure_ascii=False,
        ),
        idempotency_key=idempotency_key,
    )
    db.add(fact)
    row.status = "NORMALIZED"
    row.validation_issues = None
    return fact


def reprocess_rows(
    db: Session, tenant_id: int, source_platform_id: Optional[int] = None
) -> dict:
    """Retry every row that is not yet a fact.

    The operator's loop is: read the rejection, add the missing mapping, press
    reprocess. Rows already NORMALIZED are left alone — reprocessing must not be
    a way to double-count a delivery.
    """
    query = db.query(ent.RawImportRow).filter(
        ent.RawImportRow.tenant_id == tenant_id,
        ent.RawImportRow.status.in_(["PENDING", "REJECTED", "ACCEPTED"]),
    )
    if source_platform_id:
        query = query.filter(
            ent.RawImportRow.source_platform_id == source_platform_id
        )

    normalized = 0
    rejected = 0
    for row in query.order_by(ent.RawImportRow.created_at).all():
        if normalize_row(db, row) is not None:
            normalized += 1
        else:
            rejected += 1
    db.commit()
    return {"normalized": normalized, "rejected": rejected}


def source_platform_for(
    db: Session, tenant_id: int, code: str, name_ar: str
) -> ent.SourcePlatform:
    """This tenant's source platform of that code, created on first use.

    The Ninja endpoint wrote `source_platform_id=1` literally. SourcePlatform
    rows are tenant-scoped, so id 1 belongs to whichever tenant happened to
    create the first one: every other tenant's facts pointed at a stranger's row
    and were attributed to the wrong source in any report that groups by it.
    """
    platform = (
        db.query(ent.SourcePlatform)
        .filter(
            ent.SourcePlatform.tenant_id == tenant_id,
            ent.SourcePlatform.code == code,
        )
        .first()
    )
    if platform:
        return platform
    platform = ent.SourcePlatform(
        tenant_id=tenant_id, code=code, name_ar=name_ar, is_active=True
    )
    db.add(platform)
    db.flush()
    return platform
