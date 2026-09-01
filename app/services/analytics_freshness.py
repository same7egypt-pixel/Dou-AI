"""Analytics freshness tracking for materialized analytics tables."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models.intelligence import AnalyticsRefreshState

ANALYTICS_TABLES = [
    "analytics_workforce",
    "analytics_attendance",
    "analytics_rider_performance",
    "analytics_orders",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_freshness(db: Session) -> list[dict]:
    """Return freshness state for all tracked analytics tables."""
    states = db.query(AnalyticsRefreshState).all()
    by_name = {s.table_name: s for s in states}
    result = []
    for table in ANALYTICS_TABLES:
        state = by_name.get(table)
        if state is None:
            result.append(
                {
                    "table": table,
                    "status": "UNKNOWN",
                    "last_refresh": None,
                    "row_count": None,
                    "error": None,
                }
            )
        else:
            result.append(
                {
                    "table": state.table_name,
                    "status": state.status,
                    "last_refresh": state.last_refresh_succeeded_at,
                    "row_count": state.row_count,
                    "error": state.last_error,
                }
            )
    return result


def record_refresh_start(db: Session, table_name: str) -> AnalyticsRefreshState:
    state = (
        db.query(AnalyticsRefreshState)
        .filter(AnalyticsRefreshState.table_name == table_name)
        .first()
    )
    if state is None:
        state = AnalyticsRefreshState(table_name=table_name)
        db.add(state)
    state.status = "REFRESHING"
    state.last_refresh_started_at = utcnow()
    state.last_error = None
    db.commit()
    return state


def record_refresh_success(db: Session, table_name: str, row_count: int) -> None:
    state = (
        db.query(AnalyticsRefreshState)
        .filter(AnalyticsRefreshState.table_name == table_name)
        .first()
    )
    if state is None:
        state = AnalyticsRefreshState(table_name=table_name)
        db.add(state)
    now = utcnow()
    state.status = "READY"
    state.last_refresh_succeeded_at = now
    state.last_refresh_failed_at = None
    state.last_error = None
    state.row_count = row_count
    state.updated_at = now
    db.commit()


def record_refresh_failure(db: Session, table_name: str, error: str) -> None:
    state = (
        db.query(AnalyticsRefreshState)
        .filter(AnalyticsRefreshState.table_name == table_name)
        .first()
    )
    if state is None:
        state = AnalyticsRefreshState(table_name=table_name)
        db.add(state)
    now = utcnow()
    state.status = "FAILED"
    state.last_refresh_failed_at = now
    state.last_error = error[:2000]
    state.updated_at = now
    db.commit()


def is_fresh(db: Session, table_name: str) -> bool:
    """Check if a materialized table is considered fresh."""
    state = (
        db.query(AnalyticsRefreshState)
        .filter(AnalyticsRefreshState.table_name == table_name)
        .first()
    )
    if state is None or state.status != "READY":
        return False
    if state.last_refresh_succeeded_at is None:
        return False
    return True
