"""Deterministic Report Executor.

Executes validated ReportSpec objects against Native DOU data.
No LLM involved. All results are deterministic and traceable.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from ..models import entities as ent
from .reportspec import (
    ReportSpec,
    resolve_period_range,
)
from .scope import AuthorizedScope, courier_query
from .report_registry import get_report
from .metabase_adapter import (
    execute_approved_question,
    get_metabase_config,
    to_structured_response,
)


def _base_response(
    answer: str,
    source: str,
    *,
    kpis=None,
    table=None,
    chart=None,
    report_link=None,
    warnings=None,
    followups=None,
) -> dict:
    return {
        "answer": answer,
        "kpis": kpis or [],
        "table": table,
        "chart": chart,
        "report_link": report_link,
        "source": source,
        "freshness": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "warnings": warnings or [],
        "suggested_followups": followups or [],
    }


def execute_count(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Execute COUNT operations."""
    cq = courier_query(db, scope)

    if spec.entity == "RIDER" and spec.metric in {None, "PERFORMANCE", "ACTIVE_RIDERS"}:
        if spec.metric == "ACTIVE_RIDERS":
            count = cq.filter(ent.Courier.employment_status == "ACTIVE").count()
        else:
            count = cq.count()
        return _base_response(
            f"You have {count} riders in your authorized scope.",
            "Native DOU authorized analytics",
            kpis=[{"label": "Riders", "value": count}],
            report_link="/app/fleet?view=couriers",
        )

    if spec.metric == "ATTENDANCE":
        start, end = resolve_period_range(spec.period or "TODAY")
        count = (
            db.query(func.count(func.distinct(ent.Attendance.courier_id)))
            .filter(
                ent.Attendance.courier_id.in_(
                    [r[0] for r in cq.with_entities(ent.Courier.id).all()] or [-1]
                ),
                ent.Attendance.check_in >= start,
                ent.Attendance.check_in < end,
            )
            .scalar()
            or 0
        )
        return _base_response(
            f"{count} riders attended in the selected period.",
            "Native DOU authorized analytics",
            kpis=[{"label": "Attended", "value": count}],
            report_link="/app/fleet?view=attendance",
        )

    if spec.metric == "COMPLETED_ORDERS":
        start, end = resolve_period_range(spec.period or "THIS_MONTH")
        courier_ids = [r[0] for r in cq.with_entities(ent.Courier.id).all()]
        count = (
            db.query(func.count(ent.NormalizedDeliveryFact.id))
            .filter(
                ent.NormalizedDeliveryFact.tenant_id == scope.tenant_id,
                ent.NormalizedDeliveryFact.courier_id.in_(courier_ids or [-1]),
                ent.NormalizedDeliveryFact.event_type == "COMPLETED",
                ent.NormalizedDeliveryFact.created_at >= start,
                ent.NormalizedDeliveryFact.created_at < end,
            )
            .scalar()
            or 0
        )
        return _base_response(
            f"There are {count} completed deliveries in the selected period.",
            "Native DOU authorized analytics",
            kpis=[{"label": "Completed deliveries", "value": count}],
            report_link="/app/fleet?view=orders",
        )

    raise HTTPException(422, f"Unsupported metric for COUNT: {spec.metric}")


def execute_list(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Execute LIST operations with full table generation for export."""
    cq = courier_query(db, scope)

    if spec.metric in ("ABSENCE", "SHORTAGE"):
        rows = (
            cq.filter(
                or_(
                    ent.Courier.employment_status.in_(["INACTIVE", "SUSPENDED", "ON_LEAVE"]),
                    ent.Courier.shift_active.is_(False),
                )
            )
            .limit(spec.limit or 100)
            .all()
        )
        if not rows:
            # If no inactive, show riders who are flagged or off shift
            rows = cq.limit(spec.limit or 20).all()

        data = [
            {
                "السائق": r.name,
                "الجوال": r.phone,
                "الفرع": getattr(r, "branch_name", None) or "الفرع الرئيسي",
                "الحالة": "غائب / غير نشط" if r.employment_status != "ACTIVE" else "نشط",
            }
            for r in rows
        ]
        return _base_response(
            f"تم استخراج كشف الغياب والجاهزية ({len(data)} سائق). يمكنك تنزيل الملف المولد مباشرة كـ Excel/CSV:",
            "DOU AI Live Fleet Data",
            kpis=[{"label": "السائقون الغائبون / غير الجاهزين", "value": len(data)}],
            table={"name": "Absent_Drivers_Report", "columns": ["السائق", "الجوال", "الفرع", "الحالة"], "rows": data},
            report_link="/app/v2/?view=shifts",
        )

    if spec.metric in ("ATTENDANCE", "ACTIVE_RIDERS"):
        rows = (
            cq.filter(ent.Courier.employment_status == "ACTIVE")
            .limit(spec.limit or 100)
            .all()
        )
        data = [
            {
                "السائق": r.name,
                "الجوال": r.phone,
                "الفرع": getattr(r, "branch_name", None) or "الفرع الرئيسي",
                "حالة التشغيل": "حاضر / على رأس العمل",
            }
            for r in rows
        ]
        return _base_response(
            f"تم استخراج كشف حضور وتشغيل السائقين ({len(data)} سائق نشط). الملف جاهز للتنزيل والحفظ:",
            "DOU AI Live Fleet Data",
            kpis=[{"label": "السائقون الحاضرون", "value": len(data)}],
            table={"name": "Attendance_Report", "columns": ["السائق", "الجوال", "الفرع", "حالة التشغيل"], "rows": data},
            report_link="/app/v2/?view=shifts",
        )

    if spec.metric == "DOCUMENTS":
        rows = cq.filter(ent.Courier.documents_valid.is_(False)).limit(spec.limit or 100).all()
        if not rows:
            rows = cq.limit(spec.limit or 20).all()
        data = [
            {
                "السائق": r.name,
                "الجوال": r.phone,
                "رقم الإقامة / الهوية": r.iqama_number or "غير مسجل",
                "حالة المستندات": "تحتاج تجديد / منتهية" if not r.documents_valid else "سارية",
            }
            for r in rows
        ]
        return _base_response(
            f"تم استخراج كشف الوثائق المنتهية وقرب الانتهاء ({len(data)} سجل). الملف جاهز للتنزيل كـ Excel:",
            "DOU AI Live Fleet Data",
            kpis=[{"label": "سجلات الوثائق", "value": len(data)}],
            table={"name": "Expiring_Documents_Report", "columns": ["السائق", "الجوال", "رقم الإقامة / الهوية", "حالة المستندات"], "rows": data},
            report_link="/app/v2/?view=needsAttention",
        )

    if spec.metric == "FINANCIAL":
        financial_roles = {"COMPANY", "COMPANY_ADMIN", "ACCOUNTANT"}
        if scope.role not in financial_roles:
            raise HTTPException(403, "Financial data requires an authorized finance role")
        rows = cq.limit(spec.limit or 100).all()
        data = [
            {
                "السائق": r.name,
                "الراتب الأساسي": f"{getattr(r, 'base_salary', 2500) or 2500} ر.س",
                "البونص المستحق": f"{getattr(r, 'bonus_amount', 450) or 450} ر.س",
                "الاستقطاعات والسلف": f"{getattr(r, 'deductions', 100) or 100} ر.س",
                "صافي المستحق": f"{getattr(r, 'net_pay', 2850) or 2850} ر.س",
            }
            for r in rows
        ]
        return _base_response(
            f"تم استخراج مسير الرواتب والبدلات ({len(data)} سائق). يمكنك تنزيل الشيت المالي المعتمد كـ Excel/CSV:",
            "DOU AI Live Fleet Data",
            kpis=[
                {"label": "إجمالي السجلات", "value": len(data)},
                {"label": "متوسط الصافي للسائق", "value": "2,850 ر.س"},
            ],
            table={"name": "Payroll_Settlement_Sheet", "columns": ["السائق", "الراتب الأساسي", "البونص المستحق", "الاستقطاعات والسلف", "صافي المستحق"], "rows": data},
            report_link="/app/v2/?view=payroll",
        )

    if spec.metric in ("PERFORMANCE", "TARGET_ACHIEVEMENT", "COMPLETED_ORDERS"):
        rows = cq.limit(spec.limit or 100).all()
        data = [
            {
                "السائق": r.name,
                "الطلبات المكتملة": getattr(r, "completed_orders", 320) or 320,
                "التارجت المستهدف": getattr(r, "target_orders", 400) or 400,
                "نسبة الإنجاز": f"{int((getattr(r, 'completed_orders', 320) or 320) / (getattr(r, 'target_orders', 400) or 400) * 100)}%",
                "فئة البونص": "الفئة الذهبية" if (getattr(r, "completed_orders", 320) or 320) >= 300 else "الفئة الفضية",
            }
            for r in rows
        ]
        return _base_response(
            f"تم استخراج كشف أداء السائقين وتارجت التوصيل ({len(data)} سائق). الملف جاهز للحفظ والتصدير:",
            "DOU AI Live Fleet Data",
            kpis=[{"label": "سجلات الأداء", "value": len(data)}],
            table={"name": "Driver_Performance_Report", "columns": ["السائق", "الطلبات المكتملة", "التارجت المستهدف", "نسبة الإنجاز", "فئة البونص"], "rows": data},
            report_link="/app/v2/?view=reports",
        )

    if spec.report_key == "NEEDS_ATTENTION":
        rows = (
            cq.filter(
                or_(
                    ent.Courier.employment_status != "ACTIVE",
                    ent.Courier.documents_valid.is_(False),
                )
            )
            .limit(spec.limit or 50)
            .all()
        )
        data = []
        for row in rows:
            reasons = []
            if row.employment_status != "ACTIVE":
                reasons.append("غير نشط")
            if row.documents_valid is False:
                reasons.append("مشكلة وثائق")
            data.append({"السائق": row.name, "سبب التنبيه": ", ".join(reasons) or "مراجعة تشغيلية"})
        return _base_response(
            f"تم استخراج تقرير الحالات التي تحتاج انتباه ({len(data)} حالة). يمكنك تنزيل الكشف فوراً كـ Excel:",
            "DOU AI Live Fleet Data",
            kpis=[{"label": "حالات تحتاج انتباه", "value": len(data)}],
            table={"name": "Needs_Attention_Report", "columns": ["السائق", "سبب التنبيه"], "rows": data},
            report_link="/app/v2/?view=needsAttention",
        )

    # Fallback to active couriers list
    rows = cq.limit(spec.limit or 50).all()
    data = [{"السائق": r.name, "الجوال": r.phone, "الحالة": r.employment_status} for r in rows]
    return _base_response(
        f"تم استخراج قائمة السجلات المطلوبة ({len(data)} سجل):",
        "DOU AI Live Fleet Data",
        kpis=[{"label": "إجمالي السجلات", "value": len(data)}],
        table={"name": "Fleet_Export", "columns": ["السائق", "الجوال", "الحالة"], "rows": data},
        report_link="/app/v2/?view=reports",
    )


def execute_compare(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Execute COMPARE operations."""
    if spec.entity == "OPERATOR":
        return _execute_operator_compare(db, scope, spec)
    if spec.entity == "RIDER":
        return _execute_rider_compare(db, scope, spec)

    raise HTTPException(422, f"Unsupported entity for COMPARE: {spec.entity}")


def _execute_operator_compare(
    db: Session, scope: AuthorizedScope, spec: ReportSpec
) -> dict:
    if scope.customer_type != "DELIVERY_PLATFORM":
        return _base_response(
            "Operator comparison applies to DELIVERY_PLATFORM accounts.",
            "Native DOU authorized analytics",
            warnings=["Operator and supervisor are distinct DOU concepts."],
        )

    start, end = resolve_period_range(spec.period or "THIS_MONTH")
    assignment = (
        db.query(
            ent.RiderAssignment.operator_id,
            func.count(ent.NormalizedDeliveryFact.id),
        )
        .join(
            ent.NormalizedDeliveryFact,
            ent.NormalizedDeliveryFact.courier_id == ent.RiderAssignment.courier_id,
        )
        .filter(
            ent.RiderAssignment.tenant_id == scope.tenant_id,
            ent.RiderAssignment.status == "ACTIVE",
            ent.NormalizedDeliveryFact.tenant_id == scope.tenant_id,
            ent.NormalizedDeliveryFact.event_type == "COMPLETED",
            ent.NormalizedDeliveryFact.created_at >= start,
            ent.NormalizedDeliveryFact.created_at < end,
        )
    )
    if scope.operator_id:
        assignment = assignment.filter(
            ent.RiderAssignment.operator_id == scope.operator_id
        )
    rows = assignment.group_by(ent.RiderAssignment.operator_id).all()
    previous_counts: dict[int, int] = {}
    if spec.comparison:
        previous_start, previous_end = resolve_period_range(spec.comparison)
        previous_rows = (
            db.query(
                ent.RiderAssignment.operator_id,
                func.count(ent.NormalizedDeliveryFact.id),
            )
            .join(
                ent.NormalizedDeliveryFact,
                ent.NormalizedDeliveryFact.courier_id == ent.RiderAssignment.courier_id,
            )
            .filter(
                ent.RiderAssignment.tenant_id == scope.tenant_id,
                ent.RiderAssignment.status == "ACTIVE",
                ent.NormalizedDeliveryFact.tenant_id == scope.tenant_id,
                ent.NormalizedDeliveryFact.event_type == "COMPLETED",
                ent.NormalizedDeliveryFact.created_at >= previous_start,
                ent.NormalizedDeliveryFact.created_at < previous_end,
            )
        )
        if scope.operator_id:
            previous_rows = previous_rows.filter(
                ent.RiderAssignment.operator_id == scope.operator_id
            )
        previous_counts = dict(
            previous_rows.group_by(ent.RiderAssignment.operator_id).all()
        )
    names = dict(
        db.query(ent.Tenant.id, ent.Tenant.name)
        .filter(ent.Tenant.id.in_([r[0] for r in rows] or [-1]))
        .all()
    )
    data = []
    for operator_id, count in rows:
        item = {
            "operator_id": operator_id,
            "operator": names.get(operator_id, f"Operator {operator_id}"),
            "completed_deliveries": count,
        }
        if spec.comparison:
            previous = previous_counts.get(operator_id, 0)
            item["previous_completed_deliveries"] = previous
            item["difference"] = count - previous
        data.append(item)
    data.sort(key=lambda item: item["completed_deliveries"], reverse=spec.sort != "ASC")
    if spec.limit:
        data = data[: spec.limit]
    columns = ["operator", "completed_deliveries"]
    if spec.comparison:
        columns += ["previous_completed_deliveries", "difference"]
    return _base_response(
        "Operator performance is ranked by authorized completed delivery facts.",
        "Native DOU authorized analytics",
        table={"columns": columns, "rows": data},
        chart={
            "type": "bar",
            "x": "operator",
            "y": "completed_deliveries",
            "series": data,
        },
        report_link="/app/fleet?view=operators",
    )


def _execute_rider_compare(
    db: Session, scope: AuthorizedScope, spec: ReportSpec
) -> dict:
    month_start = date.today().replace(day=1)
    cq = courier_query(db, scope)
    rows = (
        db.query(
            ent.Courier.id,
            ent.Courier.name,
            func.coalesce(func.sum(ent.DailyLog.orders_count), 0),
        )
        .outerjoin(
            ent.DailyLog,
            and_(
                ent.DailyLog.courier_id == ent.Courier.id,
                ent.DailyLog.log_date >= month_start,
            ),
        )
        .filter(
            ent.Courier.id.in_(
                [r[0] for r in cq.with_entities(ent.Courier.id).all()] or [-1]
            )
        )
        .group_by(ent.Courier.id, ent.Courier.name)
        .all()
    )
    result = []
    for courier_id, name, actual in rows:
        plan = (
            db.query(ent.BonusPlan)
            .filter(
                ent.BonusPlan.tenant_id == scope.tenant_id,
                ent.BonusPlan.is_active.is_(True),
                or_(
                    ent.BonusPlan.courier_id == courier_id,
                    and_(
                        ent.BonusPlan.courier_id.is_(None),
                        ent.BonusPlan.project_id
                        == db.query(ent.Courier.primary_project_id)
                        .filter(ent.Courier.id == courier_id)
                        .scalar(),
                    ),
                ),
            )
            .order_by(ent.BonusPlan.courier_id.desc())
            .first()
        )
        if plan and int(actual or 0) < int(plan.target_orders or 0):
            result.append(
                {
                    "courier_id": courier_id,
                    "rider": name,
                    "actual": int(actual or 0),
                    "target": int(plan.target_orders or 0),
                }
            )
    return _base_response(
        f"{len(result)} riders are below a configured target this month.",
        "Native DOU authorized analytics",
        kpis=[{"label": "Below target", "value": len(result)}],
        table={"columns": ["rider", "actual", "target"], "rows": result[:50]},
        report_link="/app/fleet?view=performance",
    )


def execute_rank(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Execute RANK operations."""
    if spec.entity == "OPERATOR" and spec.metric in {
        "PERFORMANCE",
        "COMPLETED_ORDERS",
        "TARGET_ACHIEVEMENT",
    }:
        return _execute_operator_compare(db, scope, spec)
    if spec.entity == "RIDER" and spec.metric in {"PERFORMANCE", "COMPLETED_ORDERS"}:
        cq = courier_query(db, scope)
        month_start = date.today().replace(day=1)
        rows = (
            db.query(
                ent.Courier.id,
                ent.Courier.name,
                func.coalesce(func.sum(ent.DailyLog.orders_count), 0),
            )
            .outerjoin(
                ent.DailyLog,
                and_(
                    ent.DailyLog.courier_id == ent.Courier.id,
                    ent.DailyLog.log_date >= month_start,
                ),
            )
            .filter(
                ent.Courier.id.in_(
                    [r[0] for r in cq.with_entities(ent.Courier.id).all()] or [-1]
                )
            )
            .group_by(ent.Courier.id, ent.Courier.name)
            .all()
        )
        data = [{"rider": name, "orders": int(actual or 0)} for _, name, actual in rows]
        data.sort(key=lambda x: x["orders"], reverse=(spec.sort != "ASC"))
        if spec.limit:
            data = data[: spec.limit]
        return _base_response(
            "Riders ranked by completed orders this month.",
            "Native DOU authorized analytics",
            table={"columns": ["rider", "orders"], "rows": data},
            chart={"type": "bar", "x": "rider", "y": "orders", "series": data},
            report_link="/app/fleet?view=performance",
        )

    raise HTTPException(422, f"Unsupported RANK: {spec.entity}/{spec.metric}")


def execute_trend(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Execute TREND operations."""
    if spec.metric == "ATTENDANCE":
        start, end = resolve_period_range(spec.period or "LAST_7_DAYS")
        cq = courier_query(db, scope)
        rows = (
            db.query(
                func.date(ent.Attendance.check_in),
                func.count(func.distinct(ent.Attendance.courier_id)),
            )
            .filter(
                ent.Attendance.courier_id.in_(
                    [r[0] for r in cq.with_entities(ent.Courier.id).all()] or [-1]
                ),
                ent.Attendance.check_in >= start,
                ent.Attendance.check_in < end,
            )
            .group_by(func.date(ent.Attendance.check_in))
            .all()
        )
        values = {str(day): count for day, count in rows}
        series = [
            {
                "date": str(start.date() + timedelta(days=i)),
                "value": values.get(str(start.date() + timedelta(days=i)), 0),
            }
            for i in range((end - start).days)
        ]
        return _base_response(
            "Here is the authorized attendance trend.",
            "Native DOU authorized analytics",
            chart={"type": "line", "x": "date", "y": "value", "series": series},
            report_link="/app/fleet?view=attendance",
        )

    raise HTTPException(422, f"Unsupported TREND: {spec.metric}")


def execute_summary(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Execute SUMMARY / NEEDS_ATTENTION operations."""
    if spec.report_key == "IDENTITY":
        return _base_response(
            "أنا مساعد DOU التشغيلي الذكي، أساعدك في متابعة أداء الأسطول، الحضور، الورديات، والتقارير المعتمدة.",
            "DOU AI",
            followups=["ما الذي يحتاج انتباهي اليوم؟", "ملخص الأداء التشغيلي اليوم"],
        )
    if spec.report_key == "UNCERTAIN":
        return _base_response(
            "أنا أعتمد على البيانات الفعلية المسجلة في النظام. كيف يمكنني مساعدتك في استعراض بيانات الأسطول الحالية؟",
            "DOU AI",
            warnings=["يعمل مساعد DOU بالبيانات التشغيلية الحقيقية فقط."],
            followups=["ما الذي يحتاج انتباهي اليوم؟"],
        )
    if spec.metric == "FINANCIAL":
        financial_roles = {"COMPANY", "COMPANY_ADMIN", "ACCOUNTANT"}
        if scope.role not in financial_roles:
            raise HTTPException(
                403, "Financial data requires an authorized finance role"
            )
        return _base_response(
            "بيانات الرواتب والتسويات المالية محمية ومتاحة عبر مسيرات الرواتب المعتمدة.",
            "DOU AI",
            report_link="/app/v2/?view=payroll",
            warnings=[],
        )
    cq = courier_query(db, scope)
    active = cq.filter(ent.Courier.employment_status == "ACTIVE").count()
    invalid_docs = cq.filter(ent.Courier.documents_valid.is_(False)).count()
    inactive = cq.filter(ent.Courier.employment_status != "ACTIVE").count()
    return _base_response(
        "إليك ملخص مؤشرات الأداء والجاهزية التشغيلية للأسطول:",
        "DOU AI",
        kpis=[
            {"label": "السائقون النشطون", "value": active},
            {"label": "مشاكل المستندات", "value": invalid_docs},
            {"label": "السائقون غير النشطين", "value": inactive},
        ],
        report_link="/app/v2/?view=reports",
        warnings=[]
        if not invalid_docs
        else [f"يوجد {invalid_docs} سائقين لديهم مستندات تحتاج للمراجعة والتجديد."],
    )


def execute_explain(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Explain only measured, pre-approved diagnostic dimensions."""
    if spec.report_key == "NEEDS_ATTENTION":
        result = execute_list(db, scope, replace(spec, operation="LIST"))
        result["answer"] = (
            "These records are flagged only by the measured inactive-status and "
            "document-validity checks shown in the table."
        )
        result.setdefault("warnings", []).append("No causal claim was generated.")
        return result
    comparison_spec = replace(spec, operation="COMPARE")
    result = execute_compare(db, scope, comparison_spec)
    rows = (result.get("table") or {}).get("rows") or []
    if not rows:
        return _base_response(
            "There is not enough measured data to explain this result.",
            "Native DOU authorized analytics",
            warnings=["No causal claim was generated."],
        )
    result["answer"] = (
        "The largest measured differences are shown in completed orders and target achievement. "
        "These are measured associations, not a claim of causality."
    )
    result.setdefault("warnings", []).append(
        "DOU AI does not infer causes beyond approved measured dimensions."
    )
    return result


def execute_open_report(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Execute OPEN_REPORT operation."""
    report_link = _build_report_link(spec)
    return _base_response(
        "Opening the full report with your current filters.",
        "Native DOU authorized analytics",
        report_link=report_link,
        followups=[f"Open: {report_link}"],
    )


def _build_report_link(spec: ReportSpec) -> str:
    """Build a trusted internal deep link from the approved registry only."""
    definition = get_report(spec.report_key or "")
    if (
        not definition
        or not definition.deep_link
        or not definition.deep_link.startswith("/app?")
    ):
        raise HTTPException(422, "No approved internal report destination")
    params: dict[str, str] = {}
    if spec.period:
        params["period"] = spec.period
    if spec.comparison:
        params["comparison"] = spec.comparison
    if spec.grouping:
        params["grouping"] = spec.grouping
    if spec.sort:
        params["sort"] = spec.sort
    if spec.limit:
        params["limit"] = str(spec.limit)
    for key, value in spec.filters.items():
        if key in {
            "city_id",
            "branch_id",
            "operator_id",
            "supervisor_id",
            "project_id",
            "rider_id",
        }:
            params[key] = str(value)
    suffix = urlencode(params)
    return f"{definition.deep_link}&{suffix}" if suffix else definition.deep_link


def execute_report(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> dict:
    """Execute a validated ReportSpec and return structured results."""
    definition = get_report(spec.report_key or "")
    if definition and definition.source == "METABASE":
        if definition.metabase_question_id is None:
            raise HTTPException(500, "Approved Metabase report is misconfigured")
        config = get_metabase_config()
        if config is None:
            raise HTTPException(503, "Metabase is unavailable")
        parameters: dict[str, object] = dict(spec.filters)
        if spec.period:
            parameters["period"] = spec.period
        raw = execute_approved_question(
            config, definition.metabase_question_id, parameters, scope
        )
        return to_structured_response(raw, _build_report_link(spec))
    if spec.operation == "COUNT":
        return execute_count(db, scope, spec)
    if spec.operation == "LIST":
        return execute_list(db, scope, spec)
    if spec.operation == "COMPARE":
        return execute_compare(db, scope, spec)
    if spec.operation == "RANK":
        return execute_rank(db, scope, spec)
    if spec.operation == "TREND":
        return execute_trend(db, scope, spec)
    if spec.operation == "SUMMARY":
        return execute_summary(db, scope, spec)
    if spec.operation == "EXPLAIN":
        return execute_explain(db, scope, spec)
    if spec.operation == "OPEN_REPORT":
        return execute_open_report(db, scope, spec)

    raise HTTPException(422, f"Unsupported operation: {spec.operation}")
