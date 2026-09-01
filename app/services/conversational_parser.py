"""Rule-based Arabic/English parser for deterministic DOU AI.

The parser recognizes a deliberately finite vocabulary. It never emits SQL,
table names, browser-selected question IDs, or authorization scope.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TypeVar, cast

from .report_registry import find_report_by_intent, get_report
from .reportspec import (
    Period,
    ReportEntity,
    ReportMetric,
    ReportOperation,
    ReportSpec,
    SortDirection,
)

T = TypeVar("T")

ENTITY_SYNONYMS: dict[ReportEntity, tuple[str, ...]] = {
    "RIDER": (
        "riders",
        "rider",
        "drivers",
        "driver",
        "couriers",
        "courier",
        "سواقين",
        "سواق",
        "سائقين",
        "سائق",
        "مناديب",
        "مندوب",
        "رايدرات",
        "رايدر",
    ),
    "OPERATOR": (
        "operators",
        "operator",
        "شركات التشغيل",
        "شركة تشغيل",
        "شركات مشغلة",
        "شركة مشغلة",
        "مشغلين",
        "مشغل",
        "اوبريتورز",
        "اوبريتور",
    ),
    "SUPERVISOR": ("supervisors", "supervisor", "مشرفين", "مشرف"),
    "PROJECT": ("projects", "project", "مشاريع", "مشروع"),
    "BRANCH": ("branches", "branch", "فروع", "فرع"),
    "CITY": ("cities", "city", "مدن", "مدينة"),
    "ORDER": (
        "orders",
        "order",
        "deliveries",
        "delivery",
        "طلبات",
        "طلب",
        "اوردرات",
        "أوردرات",
        "اوردر",
        "أوردر",
    ),
    "ATTENDANCE": ("attendance", "working hours", "حضور", "غياب", "ساعات عمل"),
    "WORKFORCE": ("workforce", "القوى العاملة", "الفريق"),
}
METRIC_SYNONYMS: dict[ReportMetric, tuple[str, ...]] = {
    "ACTIVE_RIDERS": (
        "active riders",
        "active drivers",
        "active",
        "السواقين النشطين",
        "نشطين",
        "نشط",
    ),
    "ATTENDANCE": ("attendance", "attended", "حضر", "حضور"),
    "ABSENCE": ("absence", "absent", "غياب", "غايب", "غائب"),
    "WORKING_HOURS": ("working hours", "ساعات عمل"),
    "COMPLETED_ORDERS": (
        "completed orders",
        "orders delivered",
        "deliveries",
        "orders",
        "اوردرات",
        "أوردرات",
        "طلبات",
        "توصيلات",
    ),
    "ACCEPTANCE_RATE": ("acceptance rate", "معدل القبول"),
    "COMPLETION_RATE": ("completion rate", "معدل الإكمال"),
    "PERFORMANCE": ("performance", "أداء", "اداء"),
    "TARGET_ACHIEVEMENT": (
        "target achievement",
        "below target",
        "under target",
        "تحت التارجت",
        "التارجت",
        "تارجت",
        "الهدف",
    ),
    "SLA": ("sla", "مستوى الخدمة"),
    "CAPACITY": ("capacity", "السعة", "طاقة"),
    "SHORTAGE": ("shortage", "نقص", "عجز"),
    "IMPORT_HEALTH": ("import health", "import", "حالة الاستيراد", "استيراد"),
    "DOCUMENTS": ("documents", "وثائق", "مستندات"),
    "FINANCIAL": (
        "payroll",
        "salary",
        "settlement",
        "رواتب",
        "راتب",
        "تسوية",
        "مالية",
        "مالي",
    ),
}
OPERATION_SYNONYMS: dict[ReportOperation, tuple[str, ...]] = {
    "OPEN_REPORT": (
        "open the full report",
        "open full report",
        "open report",
        "افتح التقرير",
        "افتح التقرير الكامل",
    ),
    "EXPLAIN": ("why", "explain", "ليه", "لماذا", "اشرح"),
    "TREND": ("trend", "ترند", "اتجاه"),
    "COMPARE": ("compare", "comparison", "قارن", "مقارنة"),
    "RANK": ("rank", "ranking", "رتب", "ترتيب", "bottom", "top", "أسوأ", "أفضل"),
    "COUNT": ("how many", "count", "كام", "كم", "عدد"),
    "LIST": (
        "show me",
        "show",
        "list",
        "file",
        "export",
        "download",
        "excel",
        "csv",
        "sheet",
        "وريني",
        "اعرض",
        "هات",
        "مين",
        "ملف",
        "شيت",
        "إكسيل",
        "اكسيل",
        "تنزيل",
        "تحميل",
        "نزل",
        "استخرج",
        "صدر",
    ),
    "SUMMARY": ("summary", "report", "ملخص", "تقرير", "بيان", "كشف"),
}
PERIOD_SYNONYMS: dict[Period, tuple[str, ...]] = {
    "PREVIOUS_PERIOD": ("previous period", "الفترة اللي فاتت", "الفترة السابقة"),
    "LAST_30_DAYS": ("last 30 days", "آخر 30 يوم"),
    "LAST_7_DAYS": ("last 7 days", "آخر 7 أيام"),
    "LAST_MONTH": ("last month", "الشهر اللي فات", "الشهر الماضي"),
    "THIS_MONTH": ("this month", "الشهر ده", "هذا الشهر"),
    "LAST_WEEK": ("last week", "الاسبوع اللي فات", "الأسبوع الماضي"),
    "THIS_WEEK": ("this week", "الاسبوع ده", "الأسبوع ده", "هذا الأسبوع"),
    "YESTERDAY": ("yesterday", "امبارح", "أمس"),
    "TODAY": ("today", "النهارده", "اليوم"),
}
CITY_ALIASES = {
    "riyadh": "Riyadh",
    "الرياض": "Riyadh",
    "jeddah": "Jeddah",
    "جدة": "Jeddah",
    "جده": "Jeddah",
    "dammam": "Dammam",
    "الدمام": "Dammam",
    "khobar": "Khobar",
    "الخبر": "Khobar",
}
SORT_SYNONYMS: dict[SortDirection, tuple[str, ...]] = {
    "ASC": (
        "ascending",
        "worst first",
        "least first",
        "من الأسوأ",
        "من الأقل",
        "تصاعدي",
    ),
    "DESC": (
        "descending",
        "best first",
        "most first",
        "من الأفضل",
        "من الأعلى",
        "من الأكثر",
        "تنازلي",
    ),
}


def _first(text: str, catalog: dict[T, tuple[str, ...]]) -> T | None:
    normalized = text.casefold().strip()
    for key, terms in catalog.items():
        if any(term.casefold() in normalized for term in terms):
            return key
    return None


def parse_entity(text: str) -> ReportEntity | None:
    return _first(text, ENTITY_SYNONYMS)


def parse_metric(text: str) -> ReportMetric | None:
    return _first(text, METRIC_SYNONYMS)


def parse_operation(text: str) -> ReportOperation:
    return _first(text, OPERATION_SYNONYMS) or "SUMMARY"


def parse_period(text: str) -> Period | None:
    return _first(text, PERIOD_SYNONYMS)


def parse_sort(text: str) -> SortDirection | None:
    return _first(text, SORT_SYNONYMS)


def parse_city_alias(text: str) -> str | None:
    normalized = text.casefold()
    return next(
        (
            name
            for alias, name in CITY_ALIASES.items()
            if alias.casefold() in normalized
        ),
        None,
    )


def parse_limit(text: str) -> tuple[int, SortDirection] | None:
    match = re.search(
        r"(?:top|bottom|أعلى|أسوأ|أفضل|اول|أول)\s+(\d{1,3})", text.casefold()
    )
    if not match:
        return None
    value = min(int(match.group(1)), 100)
    direction: SortDirection = (
        "ASC" if match.group(0).startswith(("bottom", "أسوأ")) else "DESC"
    )
    return value, direction


def parse_report_key(text: str) -> str | None:
    normalized = text.casefold()
    if any(
        term in normalized
        for term in (
            "needs attention",
            "need attention",
            "محتاج اهتمام",
            "تحتاج اهتمام",
        )
    ):
        return "NEEDS_ATTENTION"
    for key in (
        "RIDER_PERFORMANCE",
        "ATTENDANCE_SUMMARY",
        "OPERATOR_PERFORMANCE",
        "ORDER_PERFORMANCE",
        "WORKFORCE_SUMMARY",
        "NEEDS_ATTENTION",
        "IMPORT_HEALTH",
        "FINANCIAL_SUMMARY",
    ):
        if key.casefold() in normalized:
            return key
    return None


def _is_explicit_followup(text: str) -> bool:
    """Recognize modifiers that intentionally operate on prior report state."""
    normalized = text.casefold()
    return any(
        term in normalized
        for term in (
            "بدل",
            "instead",
            "بس",
            " only",
            "change it",
            "change to",
            "رتبهم",
            "rank them",
            "قارن بالشهر",
            "compare with",
            "compare to",
            "افتح التقرير",
            "open the full report",
            "open report",
            "ليه",
            "why",
        )
    )


def parse_question(text: str, current_spec: ReportSpec | None = None) -> ReportSpec:
    normalized = text.casefold().strip()
    if any(
        term in normalized for term in ("who are you", "مين انت", "من انت", "من أنت")
    ):
        return ReportSpec(report_key="IDENTITY")
    if any(
        term in normalized
        for term in ("predict", "forecast", "future", "تنبؤ", "مستقبل")
    ):
        return ReportSpec(report_key="UNCERTAIN")
    # Complete questions start a new report even inside a conversation. Only
    # explicit modifiers are allowed to reuse prior structured state.
    if current_spec is not None and _is_explicit_followup(text):
        return _apply_followup(text, current_spec)

    entity = parse_entity(text)
    metric = parse_metric(text)
    operation = parse_operation(text)
    if metric in {"ATTENDANCE", "ABSENCE", "WORKING_HOURS"}:
        entity = "ATTENDANCE"
    elif metric == "COMPLETED_ORDERS" and entity not in {"OPERATOR", "RIDER"}:
        entity = "ORDER"
    if entity is None:
        if metric in {"ATTENDANCE", "ABSENCE", "WORKING_HOURS"}:
            entity = "ATTENDANCE"
        elif metric == "COMPLETED_ORDERS":
            entity = "ORDER"
        elif metric in {
            "IMPORT_HEALTH",
            "CAPACITY",
            "SHORTAGE",
            "DOCUMENTS",
            "FINANCIAL",
            "ACTIVE_RIDERS",
        }:
            entity = "RIDER" if metric == "ACTIVE_RIDERS" else "WORKFORCE"
        else:
            entity = "RIDER"
    if metric == "TARGET_ACHIEVEMENT" and operation == "LIST":
        operation = "COMPARE"
    report_key = parse_report_key(text)
    definition = (
        get_report(report_key)
        if report_key
        else find_report_by_intent(entity, metric, operation)
    )
    period = parse_period(text)
    if definition:
        metric = metric or definition.default_metric
        if operation not in definition.allowed_operations:
            operation = definition.default_operation
        if period is None and len(definition.allowed_periods) == 1:
            period = definition.allowed_periods[0]
    limit = parse_limit(text)
    filters: dict[str, int | str] = {}
    city_alias = parse_city_alias(text)
    if city_alias:
        filters["city_alias"] = city_alias
    return ReportSpec(
        operation=operation,
        entity=entity,
        metric=metric,
        filters=cast(dict[str, int], filters),
        period=period,
        sort=parse_sort(text) or (limit[1] if limit else None),
        limit=limit[0] if limit else None,
        report_key=definition.report_key if definition else None,
        source=definition.source if definition else None,
        raw_question=text,
    )


def _apply_followup(text: str, current: ReportSpec) -> ReportSpec:
    spec = replace(current, filters=dict(current.filters))
    operation = parse_operation(text)
    period = parse_period(text)
    metric = parse_metric(text)
    city_alias = parse_city_alias(text)
    limit = parse_limit(text)
    if operation == "OPEN_REPORT":
        spec.operation = "OPEN_REPORT"
    elif operation == "EXPLAIN":
        spec.operation = "EXPLAIN"
    elif operation == "COMPARE" and period is not None:
        spec.comparison = period
    elif operation != "SUMMARY" and not (
        operation == "LIST"
        and metric is not None
        and any(term in text.casefold() for term in ("بدل", "instead"))
    ):
        spec.operation = operation
    if period is not None and not (
        operation == "COMPARE" and "last" in text.casefold() or "اللي فات" in text
    ):
        spec.period = period
    if metric is not None:
        spec.metric = metric
        replacement = find_report_by_intent(spec.entity, metric, spec.operation)
        if replacement:
            spec.report_key, spec.source = replacement.report_key, replacement.source
    if city_alias:
        spec.filters["city_alias"] = cast(int, city_alias)
    sort = parse_sort(text)
    if sort:
        spec.sort = sort
    if limit:
        spec.limit, spec.sort = limit
    return spec


def is_ambiguous(text: str, current_spec: ReportSpec | None = None) -> bool:
    normalized = text.casefold().strip()
    if current_spec is not None and parse_operation(text) in {"OPEN_REPORT", "EXPLAIN"}:
        return False
    if len(normalized) < 3:
        return True
    if any(
        term in normalized for term in ("who are you", "مين انت", "من انت", "من أنت")
    ):
        return False
    if (
        any(
            term in normalized
            for term in (
                "اعملي تقرير",
                "اعمللي تقرير",
                "operations report",
                "تقرير عن التشغيل",
            )
        )
        and parse_metric(text) is None
    ):
        return True
    if (
        parse_operation(text) == "COMPARE"
        and parse_period(text) is None
        and current_spec is None
    ):
        return True
    recognized = parse_entity(text) or parse_metric(text) or parse_report_key(text)
    return not bool(recognized) and current_spec is None


def generate_clarification_options(text: str) -> list[dict]:
    if parse_operation(text) == "COMPARE" and parse_period(text) is None:
        return [
            {"key": "this_month", "label_ar": "الشهر ده", "label_en": "This month"},
            {"key": "this_week", "label_ar": "الأسبوع ده", "label_en": "This week"},
            {"key": "today", "label_ar": "النهارده", "label_en": "Today"},
        ]
    return [
        {"key": "performance", "label_ar": "الأداء", "label_en": "Performance"},
        {"key": "attendance", "label_ar": "الحضور", "label_en": "Attendance"},
        {"key": "orders", "label_ar": "الأوردرات", "label_en": "Orders"},
        {"key": "operators", "label_ar": "شركات التشغيل", "label_en": "Operators"},
        {
            "key": "summary",
            "label_ar": "ملخص الإدارة",
            "label_en": "Management Summary",
        },
    ]
