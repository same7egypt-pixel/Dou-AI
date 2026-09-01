"""Notification event connections for Batch 2+3 operational signals."""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import entities as ent
from .notifications import create_native_notification


def notify_capacity_shortage(
    db: Session, tenant_id: int, scope_type: str, scope_id: int, shortage: int
):
    """Notify management of rider capacity shortage."""
    if shortage <= 0:
        return
    create_native_notification(
        db=db,
        tenant_id=tenant_id,
        notification_type="OPERATIONAL",
        severity="HIGH" if shortage > 5 else "MEDIUM",
        title=f"نقص {shortage} سائقين في {scope_type} {scope_id}",
        message=f"There is a shortage of {shortage} riders in scope {scope_type}/{scope_id}",
        idempotency_key=f"capacity_shortage_{tenant_id}_{scope_type}_{scope_id}_{date.today().isoformat()}",
        dedupe_key=f"capacity_shortage_{scope_type}_{scope_id}",
    )


def notify_absent_riders(db: Session, tenant_id: int, absent_count: int):
    """Notify management/supervisors of absent riders."""
    if absent_count <= 0:
        return
    create_native_notification(
        db=db,
        tenant_id=tenant_id,
        notification_type="ATTENDANCE",
        severity="HIGH" if absent_count > 5 else "MEDIUM",
        title=f"{absent_count} مندوب غائب اليوم",
        message=f"{absent_count} riders are absent today",
        idempotency_key=f"absent_riders_{tenant_id}_{date.today().isoformat()}",
        dedupe_key="absent_riders",
    )


def notify_below_target(db: Session, tenant_id: int, below_count: int):
    """Notify of riders below target."""
    if below_count <= 0:
        return
    create_native_notification(
        db=db,
        tenant_id=tenant_id,
        notification_type="PERFORMANCE",
        severity="MEDIUM",
        title=f"{below_count} مندوب تحت التارجت",
        message=f"{below_count} riders are below target achievement",
        idempotency_key=f"below_target_{tenant_id}_{date.today().isoformat()}",
        dedupe_key="below_target",
    )


def notify_expiring_documents(db: Session, tenant_id: int, expiring_count: int):
    """Notify of expiring documents."""
    if expiring_count <= 0:
        return
    create_native_notification(
        db=db,
        tenant_id=tenant_id,
        notification_type="COMPLIANCE",
        severity="MEDIUM",
        title=f"{expiring_count} مستند ينتهي قريباً",
        message=f"{expiring_count} documents are expiring within 30 days",
        idempotency_key=f"expiring_docs_{tenant_id}_{date.today().isoformat()}",
        dedupe_key="expiring_documents",
    )


def notify_attendance_correction_pending(
    db: Session, tenant_id: int, pending_count: int
):
    """Notify of pending attendance corrections."""
    if pending_count <= 0:
        return
    create_native_notification(
        db=db,
        tenant_id=tenant_id,
        notification_type="ATTENDANCE",
        severity="LOW",
        title=f"{pending_count} تصحيح حضور بانتظار المراجعة",
        message=f"{pending_count} attendance corrections are pending review",
        idempotency_key=f"pending_corrections_{tenant_id}_{date.today().isoformat()}",
        dedupe_key="pending_attendance_corrections",
    )


def notify_onboarding_incomplete(db: Session, tenant_id: int, incomplete_count: int):
    """Notify of incomplete onboardings."""
    if incomplete_count <= 0:
        return
    create_native_notification(
        db=db,
        tenant_id=tenant_id,
        notification_type="ONBOARDING",
        severity="MEDIUM",
        title=f"{incomplete_count} مندوب غير مكتمل التمهيد",
        message=f"{incomplete_count} riders have incomplete onboarding",
        idempotency_key=f"incomplete_onboarding_{tenant_id}_{date.today().isoformat()}",
        dedupe_key="incomplete_onboarding",
    )


def notify_data_health_issue(
    db: Session, tenant_id: int, source: str, error_message: str
):
    """Notify of data health issues (import failures, stale data)."""
    create_native_notification(
        db=db,
        tenant_id=tenant_id,
        notification_type="DATA_HEALTH",
        severity="HIGH",
        title=f"مشكلة في بيانات {source}",
        message=f"Data health issue in {source}: {error_message}",
        idempotency_key=f"data_health_{tenant_id}_{source}_{date.today().isoformat()}",
        dedupe_key=f"data_health_{source}",
    )


def generate_daily_operational_notifications(db: Session, tenant_id: int):
    """Generate all daily operational notifications for a tenant. Called by cron/scheduler."""
    today = date.today()

    # Absent riders
    active_couriers = (
        db.query(ent.Courier)
        .filter(
            ent.Courier.tenant_id == tenant_id,
            ent.Courier.employment_status == "ACTIVE",
        )
        .all()
    )
    if active_couriers:
        active_ids = [c.id for c in active_couriers]
        attended_ids = {
            row[0]
            for row in db.query(func.distinct(ent.Attendance.courier_id))
            .filter(
                ent.Attendance.courier_id.in_(active_ids),
                ent.Attendance.check_in >= datetime.combine(today, datetime.min.time()),
            )
            .all()
        }
        absent_count = len([c_id for c_id in active_ids if c_id not in attended_ids])
        notify_absent_riders(db, tenant_id, absent_count)

    # Below target
    below = (
        db.query(func.count(ent.Target.id))
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.scope_type == "RIDER",
            ent.Target.period == today.strftime("%Y-%m"),
            ent.Target.achievement_percentage < 80,
        )
        .scalar()
        or 0
    )
    notify_below_target(db, tenant_id, below)

    # Expiring documents
    expiring = (
        db.query(func.count(ent.Document.id))
        .filter(
            ent.Document.tenant_id == tenant_id,
            ent.Document.expiry_date <= today + timedelta(days=30),
            ent.Document.expiry_date >= today,
        )
        .scalar()
        or 0
    )
    notify_expiring_documents(db, tenant_id, expiring)

    # Incomplete onboarding
    incomplete = (
        db.query(func.count(ent.OperationalReadinessState.courier_id))
        .filter(
            ent.OperationalReadinessState.tenant_id == tenant_id,
            ent.OperationalReadinessState.onboarding_status != "READY_TO_WORK",
        )
        .scalar()
        or 0
    )
    notify_onboarding_incomplete(db, tenant_id, incomplete)

    # Pending attendance corrections
    pending_corrections = (
        db.query(func.count(ent.AttendanceCorrection.id))
        .filter(
            ent.AttendanceCorrection.tenant_id == tenant_id,
            ent.AttendanceCorrection.status == "PENDING",
        )
        .scalar()
        or 0
    )
    notify_attendance_correction_pending(db, tenant_id, pending_corrections)

    # Data health issues
    health_snapshots = (
        db.query(ent.DataHealthSnapshot)
        .filter(
            ent.DataHealthSnapshot.tenant_id == tenant_id,
            ent.DataHealthSnapshot.last_sync_status == "FAILED",
        )
        .all()
    )
    for snapshot in health_snapshots:
        if snapshot.error_message:
            notify_data_health_issue(
                db, tenant_id, snapshot.source, snapshot.error_message
            )
