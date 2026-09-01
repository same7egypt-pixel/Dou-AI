"""Strongly validated ReportSpec for deterministic DOU AI.

A ReportSpec describes requested analytics, never authorization. Every spec is
validated against the server registry and authenticated scope before execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal, cast

from fastapi import HTTPException

ReportOperation = Literal[
    "COUNT",
    "LIST",
    "COMPARE",
    "RANK",
    "TREND",
    "SUMMARY",
    "EXPLAIN",
    "OPEN_REPORT",
]
ReportEntity = Literal[
    "RIDER",
    "OPERATOR",
    "SUPERVISOR",
    "PROJECT",
    "BRANCH",
    "CITY",
    "ORDER",
    "ATTENDANCE",
    "WORKFORCE",
]
ReportMetric = Literal[
    "ACTIVE_RIDERS",
    "ATTENDANCE",
    "ABSENCE",
    "WORKING_HOURS",
    "COMPLETED_ORDERS",
    "ACCEPTANCE_RATE",
    "COMPLETION_RATE",
    "PERFORMANCE",
    "TARGET_ACHIEVEMENT",
    "SLA",
    "CAPACITY",
    "SHORTAGE",
    "IMPORT_HEALTH",
    "DOCUMENTS",
    "FINANCIAL",
]
ReportSource = Literal["NATIVE", "METABASE"]
SortDirection = Literal["ASC", "DESC"]
Period = Literal[
    "TODAY",
    "YESTERDAY",
    "THIS_WEEK",
    "LAST_WEEK",
    "THIS_MONTH",
    "LAST_MONTH",
    "PREVIOUS_PERIOD",
    "LAST_7_DAYS",
    "LAST_30_DAYS",
]
OutputPreference = Literal["KPI", "TABLE", "CHART", "SUMMARY"]

OPERATIONS = frozenset(getattr(ReportOperation, "__args__", ()))
ENTITIES = frozenset(getattr(ReportEntity, "__args__", ()))
METRICS = frozenset(getattr(ReportMetric, "__args__", ()))
PERIODS = frozenset(getattr(Period, "__args__", ()))
SORTS = {"ASC", "DESC"}
OUTPUTS = {"KPI", "TABLE", "CHART", "SUMMARY"}
SAFE_FILTERS = {
    "city_id",
    "branch_id",
    "operator_id",
    "supervisor_id",
    "project_id",
    "rider_id",
}


@dataclass
class ReportSpec:
    operation: ReportOperation = "SUMMARY"
    entity: ReportEntity = "RIDER"
    metric: ReportMetric | None = None
    filters: dict[str, int] = field(default_factory=dict)
    period: Period | None = None
    comparison: Period | None = None
    grouping: str | None = None
    sort: SortDirection | None = None
    limit: int | None = None
    output: OutputPreference = "SUMMARY"
    report_key: str | None = None
    source: ReportSource | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "ReportSpec":
        """Restore only known fields and validate their primitive types."""
        if not isinstance(raw, dict):
            raise ValueError("ReportSpec must be an object")
        known = set(cls.__dataclass_fields__)
        if set(raw) - known:
            raise ValueError("Unknown ReportSpec fields")
        filters = raw.get("filters") or {}
        if not isinstance(filters, dict):
            raise ValueError("ReportSpec filters must be an object")
        return cls(**{**raw, "filters": dict(filters)})


def default_period_for(
    metric: ReportMetric | None, operation: ReportOperation
) -> Period:
    if operation == "TREND":
        return "LAST_7_DAYS"
    if metric in {"ATTENDANCE", "ABSENCE", "WORKING_HOURS"}:
        return "TODAY"
    return "THIS_MONTH"


def resolve_period_range(
    period: Period, today: date | None = None
) -> tuple[datetime, datetime]:
    today = today or date.today()
    if period == "TODAY":
        start = datetime.combine(today, datetime.min.time())
        return start, start + timedelta(days=1)
    if period == "YESTERDAY":
        start = datetime.combine(today - timedelta(days=1), datetime.min.time())
        return start, start + timedelta(days=1)
    if period == "THIS_WEEK":
        start = datetime.combine(
            today - timedelta(days=today.weekday()), datetime.min.time()
        )
        return start, start + timedelta(days=7)
    if period == "LAST_WEEK":
        start = datetime.combine(
            today - timedelta(days=today.weekday() + 7), datetime.min.time()
        )
        return start, start + timedelta(days=7)
    if period == "THIS_MONTH":
        start = datetime.combine(today.replace(day=1), datetime.min.time())
        return start, (start + timedelta(days=32)).replace(day=1)
    if period in {"LAST_MONTH", "PREVIOUS_PERIOD"}:
        end = datetime.combine(today.replace(day=1), datetime.min.time())
        return (end - timedelta(days=1)).replace(day=1), end
    if period == "LAST_7_DAYS":
        end = datetime.combine(today + timedelta(days=1), datetime.min.time())
        return end - timedelta(days=7), end
    if period == "LAST_30_DAYS":
        end = datetime.combine(today + timedelta(days=1), datetime.min.time())
        return end - timedelta(days=30), end
    raise HTTPException(422, "Unsupported report period")


def resolve_previous_period(period: Period) -> Period:
    mapping: dict[Period, Period] = {
        "TODAY": "YESTERDAY",
        "YESTERDAY": "TODAY",
        "THIS_WEEK": "LAST_WEEK",
        "LAST_WEEK": "THIS_WEEK",
        "THIS_MONTH": "LAST_MONTH",
        "LAST_MONTH": "THIS_MONTH",
        "PREVIOUS_PERIOD": "LAST_MONTH",
        "LAST_7_DAYS": "LAST_7_DAYS",
        "LAST_30_DAYS": "LAST_30_DAYS",
    }
    return mapping.get(period, "LAST_MONTH")


def validate_spec_shape(spec: ReportSpec) -> None:
    if spec.operation not in OPERATIONS or spec.entity not in ENTITIES:
        raise HTTPException(422, "Unsupported report operation or entity")
    if spec.metric is not None and spec.metric not in METRICS:
        raise HTTPException(422, "Unsupported report metric")
    if spec.period is not None and spec.period not in PERIODS:
        raise HTTPException(422, "Unsupported report period")
    if spec.comparison is not None and spec.comparison not in PERIODS:
        raise HTTPException(422, "Unsupported comparison period")
    if spec.sort is not None and spec.sort not in SORTS:
        raise HTTPException(422, "Unsupported sort direction")
    if spec.output not in OUTPUTS:
        raise HTTPException(422, "Unsupported output preference")
    if spec.limit is not None and not 1 <= spec.limit <= 100:
        raise HTTPException(422, "Report limit must be between 1 and 100")
    if set(spec.filters) - SAFE_FILTERS:
        raise HTTPException(422, "Unsupported report filter")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in spec.filters.values()
    ):
        raise HTTPException(422, "Report filter identifiers must be positive integers")


def validate_spec_against_scope(spec: ReportSpec, auth_scope) -> None:
    """Ensure explicit filters can only narrow the authenticated scope."""
    validate_spec_shape(spec)
    fixed_filters = {
        "operator_id": auth_scope.operator_id,
        "supervisor_id": auth_scope.supervisor_id,
        "project_id": auth_scope.project_id,
        "rider_id": auth_scope.rider_id,
        "city_id": auth_scope.city_id,
    }
    for name, fixed_value in fixed_filters.items():
        requested = spec.filters.get(name)
        if (
            requested is not None
            and fixed_value is not None
            and requested != fixed_value
        ):
            raise HTTPException(403, f"{name} is outside authenticated scope")
    if auth_scope.project_ids is not None and spec.filters.get("project_id") not in {
        None,
        *auth_scope.project_ids,
    }:
        raise HTTPException(403, "Project filter is outside authenticated scope")


def as_period(value: str) -> Period:
    if value not in PERIODS:
        raise ValueError("Invalid period")
    return cast(Period, value)
