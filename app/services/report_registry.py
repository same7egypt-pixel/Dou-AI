"""DOU AI Report Registry.

All selectable report/query capabilities come from this approved server-side registry.
The browser cannot supply arbitrary report keys, metrics, or Metabase question IDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException

from .reportspec import Period, ReportEntity, ReportMetric, ReportOperation, ReportSpec

CustomerType = Literal["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM", "ANY"]

ReportSource = Literal["NATIVE", "METABASE"]


@dataclass
class ReportDefinition:
    report_key: str
    title_ar: str
    title_en: str
    description_ar: str
    description_en: str
    source: ReportSource
    entity: ReportEntity
    default_operation: ReportOperation
    default_metric: ReportMetric | None = None
    allowed_operations: list[ReportOperation] = field(default_factory=list)
    allowed_metrics: list[ReportMetric] = field(default_factory=list)
    allowed_filters: list[str] = field(default_factory=list)
    allowed_grouping: list[str] = field(default_factory=list)
    allowed_sort: list[str] = field(default_factory=list)
    allowed_periods: list[Period] = field(default_factory=list)
    # The capability the account must hold. None means the report is part of
    # every plan. A report that reads money must name the capability that sells
    # it, or the assistant becomes a way around the entitlement guards.
    required_capability: str | None = None
    allowed_roles: list[str] = field(
        default_factory=lambda: [
            "DOU_ADMIN",
            "COMPANY",
            "COMPANY_ADMIN",
            "OPERATIONS",
            "HR",
            "ACCOUNTANT",
            "VIEWER",
            "SUPERVISOR",
            "PROJECT_MANAGER",
        ]
    )
    allowed_customer_types: list[CustomerType] = field(
        default_factory=lambda: ["LOGISTICS_OPERATOR", "DELIVERY_PLATFORM"]
    )
    supports_comparison: bool = True
    supports_trend: bool = False
    deep_link: str | None = None
    metabase_question_id: int | None = None


REPORT_REGISTRY: dict[str, ReportDefinition] = {}


def register(definition: ReportDefinition) -> None:
    REPORT_REGISTRY[definition.report_key] = definition


def get_report(key: str) -> ReportDefinition | None:
    return REPORT_REGISTRY.get(key)


def list_reports() -> list[ReportDefinition]:
    return list(REPORT_REGISTRY.values())


# ── Native DOU Reports ──

register(
    ReportDefinition(
        report_key="FINANCIAL_SUMMARY",
        title_ar="التقارير المالية المحمية",
        title_en="Protected Financial Reports",
        description_ar="مدخل محمي لتقارير الرواتب والتسويات الأصلية",
        description_en="Protected entry point to Native DOU payroll and settlement reports",
        source="NATIVE",
        entity="WORKFORCE",
        default_operation="SUMMARY",
        default_metric="FINANCIAL",
        allowed_operations=["SUMMARY", "LIST"],
        allowed_metrics=["FINANCIAL"],
        allowed_filters=[],
        allowed_grouping=[],
        allowed_sort=[],
        allowed_periods=["TODAY", "THIS_WEEK", "THIS_MONTH", "LAST_MONTH", "PREVIOUS_PERIOD"],
        allowed_roles=["COMPANY", "COMPANY_ADMIN", "ACCOUNTANT"],
        required_capability="RIDER_PAYROLL",
        deep_link="/app?view=reports",
    )
)

register(
    ReportDefinition(
        report_key="RIDER_PERFORMANCE",
        title_ar="أداء السائقين",
        title_en="Rider Performance",
        description_ar="مقارنة أداء السائقين حسب الأوردرات والتارجت",
        description_en="Compare rider performance by orders and targets",
        source="NATIVE",
        entity="RIDER",
        default_operation="COMPARE",
        default_metric="PERFORMANCE",
        allowed_operations=["COUNT", "LIST", "COMPARE", "RANK", "TREND", "SUMMARY"],
        allowed_metrics=[
            "PERFORMANCE",
            "TARGET_ACHIEVEMENT",
            "COMPLETED_ORDERS",
            "ACTIVE_RIDERS",
        ],
        allowed_filters=[
            "city_id",
            "branch_id",
            "supervisor_id",
            "project_id",
            "operator_id",
        ],
        allowed_grouping=["supervisor_id", "project_id", "city_id"],
        allowed_sort=["ASC", "DESC"],
        allowed_periods=[
            "TODAY",
            "YESTERDAY",
            "THIS_WEEK",
            "LAST_WEEK",
            "THIS_MONTH",
            "LAST_MONTH",
            "PREVIOUS_PERIOD",
        ],
        supports_comparison=True,
        supports_trend=True,
        deep_link="/app?view=performance",
    )
)

register(
    ReportDefinition(
        report_key="ATTENDANCE_SUMMARY",
        title_ar="ملخص الحضور",
        title_en="Attendance Summary",
        description_ar="حضور السائقين اليوم أو خلال فترة محددة",
        description_en="Rider attendance for today or a specified period",
        source="NATIVE",
        entity="ATTENDANCE",
        default_operation="COUNT",
        default_metric="ATTENDANCE",
        allowed_operations=["COUNT", "LIST", "TREND", "SUMMARY"],
        allowed_metrics=["ATTENDANCE", "ABSENCE", "WORKING_HOURS"],
        allowed_filters=[
            "city_id",
            "branch_id",
            "supervisor_id",
            "project_id",
            "operator_id",
        ],
        allowed_grouping=["supervisor_id", "project_id", "city_id"],
        allowed_sort=["ASC", "DESC"],
        allowed_periods=[
            "TODAY",
            "YESTERDAY",
            "THIS_WEEK",
            "LAST_WEEK",
            "THIS_MONTH",
            "LAST_MONTH",
            "LAST_7_DAYS",
        ],
        supports_comparison=True,
        supports_trend=True,
        deep_link="/app?view=attendance",
    )
)

register(
    ReportDefinition(
        report_key="OPERATOR_PERFORMANCE",
        title_ar="أداء شركات التشغيل",
        title_en="Operator Performance",
        description_ar="مقارنة أداء شركات التشغيل",
        description_en="Compare operator performance",
        source="NATIVE",
        entity="OPERATOR",
        default_operation="COMPARE",
        default_metric="PERFORMANCE",
        allowed_operations=["COUNT", "LIST", "COMPARE", "RANK", "SUMMARY"],
        allowed_metrics=["PERFORMANCE", "COMPLETED_ORDERS", "TARGET_ACHIEVEMENT"],
        allowed_filters=["city_id"],
        allowed_grouping=[],
        allowed_sort=["ASC", "DESC"],
        allowed_periods=["THIS_MONTH", "LAST_MONTH", "PREVIOUS_PERIOD"],
        allowed_customer_types=["DELIVERY_PLATFORM"],
        supports_comparison=True,
        deep_link="/app?view=operators",
    )
)

register(
    ReportDefinition(
        report_key="ORDER_PERFORMANCE",
        title_ar="أداء الأوردرات",
        title_en="Order Performance",
        description_ar="إحصائيات الأوردرات والتوصيل",
        description_en="Order and delivery statistics",
        source="NATIVE",
        entity="ORDER",
        default_operation="COUNT",
        default_metric="COMPLETED_ORDERS",
        allowed_operations=["COUNT", "LIST", "COMPARE", "TREND", "SUMMARY"],
        allowed_metrics=[
            "COMPLETED_ORDERS",
            "ACCEPTANCE_RATE",
            "COMPLETION_RATE",
            "SLA",
        ],
        allowed_filters=["city_id", "branch_id", "operator_id"],
        allowed_grouping=["city_id", "operator_id"],
        allowed_sort=["ASC", "DESC"],
        allowed_periods=["TODAY", "YESTERDAY", "THIS_WEEK", "THIS_MONTH", "LAST_MONTH"],
        supports_comparison=True,
        supports_trend=True,
        deep_link="/app?view=orders",
    )
)

register(
    ReportDefinition(
        report_key="WORKFORCE_SUMMARY",
        title_ar="ملخص القوى العاملة",
        title_en="Workforce Summary",
        description_ar="ملخص السائقين النشطين والوثائق والحالات",
        description_en="Summary of active riders, documents, and status",
        source="NATIVE",
        entity="WORKFORCE",
        default_operation="SUMMARY",
        default_metric="ACTIVE_RIDERS",
        allowed_operations=["COUNT", "LIST", "SUMMARY"],
        allowed_metrics=["ACTIVE_RIDERS", "CAPACITY", "SHORTAGE", "DOCUMENTS"],
        allowed_filters=["city_id", "branch_id", "supervisor_id", "project_id"],
        allowed_grouping=["supervisor_id", "project_id", "city_id"],
        allowed_sort=["ASC", "DESC"],
        allowed_periods=["TODAY"],
        deep_link="/app?view=couriers",
    )
)

register(
    ReportDefinition(
        report_key="NEEDS_ATTENTION",
        title_ar="محتاج اهتمام",
        title_en="Needs Attention",
        description_ar="حالات تشغيلية تحتاج مراجعة",
        description_en="Operational cases requiring review",
        source="NATIVE",
        entity="RIDER",
        default_operation="LIST",
        default_metric=None,
        allowed_operations=["LIST", "SUMMARY"],
        allowed_metrics=["TARGET_ACHIEVEMENT", "ATTENDANCE", "DOCUMENTS"],
        allowed_filters=["city_id", "branch_id", "supervisor_id", "project_id"],
        allowed_grouping=["supervisor_id", "project_id"],
        allowed_sort=["ASC", "DESC"],
        allowed_periods=["TODAY", "THIS_WEEK", "THIS_MONTH"],
        deep_link="/app?view=overview",
    )
)

register(
    ReportDefinition(
        report_key="IMPORT_HEALTH",
        title_ar="حالة الاستيراد",
        title_en="Import Health",
        description_ar="حالة عمليات استيراد البيانات",
        description_en="Data import operation status",
        source="NATIVE",
        entity="WORKFORCE",
        default_operation="SUMMARY",
        default_metric="IMPORT_HEALTH",
        allowed_operations=["LIST", "SUMMARY"],
        allowed_metrics=["IMPORT_HEALTH"],
        allowed_filters=[],
        allowed_grouping=["status"],
        allowed_sort=["ASC", "DESC"],
        allowed_periods=["TODAY", "THIS_WEEK", "THIS_MONTH"],
        allowed_roles=["DOU_ADMIN", "COMPANY", "COMPANY_ADMIN", "OPERATIONS"],
        deep_link="/app?view=imports",
    )
)


def find_report_by_intent(
    entity: ReportEntity, metric: ReportMetric | None, operation: ReportOperation
) -> ReportDefinition | None:
    """Find a report only when the registry explicitly supports the request."""
    candidates = [r for r in REPORT_REGISTRY.values() if r.entity == entity]
    if metric:
        exact = [r for r in candidates if metric in r.allowed_metrics]
        if exact:
            candidates = exact
        else:
            return None
    return next((r for r in candidates if operation in r.allowed_operations), None)


def validate_registered_report(spec: ReportSpec, scope) -> ReportDefinition:
    """Deny by default unless the registry authorizes every requested capability."""
    if spec.report_key in {"IDENTITY", "UNCERTAIN"}:
        raise HTTPException(422, "Internal response is not an executable report")
    definition = get_report(spec.report_key or "")
    if not definition:
        raise HTTPException(422, "Unsupported question or report")
    if definition.source != spec.source or definition.entity != spec.entity:
        raise HTTPException(422, "Report source or entity does not match the registry")
    if spec.operation == "OPEN_REPORT":
        if not definition.deep_link:
            raise HTTPException(422, "This report has no approved deep link")
    elif spec.operation == "EXPLAIN":
        if definition.report_key not in {
            "RIDER_PERFORMANCE",
            "OPERATOR_PERFORMANCE",
            "NEEDS_ATTENTION",
        }:
            raise HTTPException(
                422, "Deterministic explanation is not approved for this report"
            )
    elif spec.operation not in definition.allowed_operations:
        raise HTTPException(422, "Operation is not approved for this report")
    if spec.metric is not None and spec.metric not in definition.allowed_metrics:
        raise HTTPException(422, "Metric is not approved for this report")
    if spec.period is not None and spec.period not in definition.allowed_periods:
        raise HTTPException(422, "Period is not approved for this report")
    if spec.comparison is not None and not definition.supports_comparison:
        raise HTTPException(422, "Comparison is not approved for this report")
    if spec.grouping is not None and spec.grouping not in definition.allowed_grouping:
        raise HTTPException(422, "Grouping is not approved for this report")
    if spec.sort is not None and spec.sort not in definition.allowed_sort:
        raise HTTPException(422, "Sorting is not approved for this report")
    if set(spec.filters) - set(definition.allowed_filters):
        raise HTTPException(422, "Filter is not approved for this report")
    if scope.role not in definition.allowed_roles:
        raise HTTPException(403, "Report is not available for this role")
    if (
        scope.customer_type not in definition.allowed_customer_types
        and "ANY" not in definition.allowed_customer_types
    ):
        raise HTTPException(403, "Report is not available for this customer type")
    if definition.required_capability:
        held = getattr(scope, "capabilities", None) or frozenset()
        if definition.required_capability not in held:
            raise HTTPException(
                403,
                f"This account is not entitled to {definition.required_capability}",
            )
    return definition
