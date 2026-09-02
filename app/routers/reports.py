from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional
from decimal import Decimal
import time
import os
import jwt
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user


router = APIRouter(prefix="/analytics/reports", tags=["reports"])

READ_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.SUPERVISOR,
    ent.UserRole.PROJECT_MANAGER,
}

METABASE_EMBEDDING_SECRET_KEY = os.getenv(
    "METABASE_EMBEDDING_SECRET_KEY",
    "a0bf24b622703a7b0da3d379d54dcea58b9b1fd6e2796b1abce80506fb2346c5",
).strip()
METABASE_SITE_URL = os.getenv("METABASE_URL", "http://localhost:3000")
ALLOWED_METABASE_DASHBOARD_IDS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13}


def _tenant_id(user: ent.User) -> int:
    if user.role not in READ_ROLES or not user.tenant_id:
        raise HTTPException(403, "Reports access required")
    return user.tenant_id


def _convert_query_objects(*args):
    """Convert FastAPI Query objects to their default values."""
    result = []
    for value in args:
        if value is None:
            result.append(None)
        elif hasattr(value, "default"):
            result.append(value.default)
        else:
            result.append(value)
    return result


@router.get("/driver-targets")
def driver_targets_progress(
    month: Optional[str] = Query(None),
    branch_id: Optional[int] = Query(None),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Operational tracker for driver daily attendance, daily orders, and monthly target pacing."""
    tenant_id = _tenant_id(user)
    today = date.today()
    selected_month = month or today.strftime("%Y-%m")
    try:
        year, month_num = (int(p) for p in selected_month.split("-", 1))
        month_start = date(year, month_num, 1)
        period_end = date(year + 1, 1, 1) if month_num == 12 else date(year, month_num + 1, 1)
    except Exception:
        month_start = date(today.year, today.month, 1)
        period_end = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)

    days_in_month = (period_end - month_start).days
    day_of_month = today.day if selected_month == today.strftime("%Y-%m") else days_in_month
    remaining_days = max(1, days_in_month - day_of_month)

    couriers_q = db.query(ent.Courier).filter(
        ent.Courier.tenant_id == tenant_id,
        ent.Courier.employment_status == "ACTIVE",
    )
    if user.role == ent.UserRole.SUPERVISOR:
        sup_branches = [
            link.contract_branch_id
            for link in db.query(ent.ContractBranchSupervisor)
            .filter(ent.ContractBranchSupervisor.user_id == user.id)
            .all()
        ]
        direct_branches = [
            b.id
            for b in db.query(ent.ContractBranch)
            .filter(ent.ContractBranch.supervisor_id == user.id)
            .all()
        ]
        allowed_branches = set(sup_branches + direct_branches)
        if allowed_branches:
            couriers_q = couriers_q.filter(
                ent.Courier.contract_branch_id.in_(allowed_branches)
            )
        else:
            couriers_q = couriers_q.filter(ent.Courier.supervisor_id == user.id)

    if branch_id:
        couriers_q = couriers_q.filter(ent.Courier.contract_branch_id == branch_id)

    couriers = couriers_q.order_by(ent.Courier.name).all()
    c_ids = [c.id for c in couriers]

    today_orders = defaultdict(int)
    month_orders = defaultdict(int)
    if c_ids:
        logs = (
            db.query(ent.DailyLog)
            .filter(
                ent.DailyLog.courier_id.in_(c_ids),
                ent.DailyLog.log_date >= month_start,
                ent.DailyLog.log_date < period_end,
            )
            .all()
        )
        for log in logs:
            qty = int(log.orders_count or 0)
            month_orders[log.courier_id] += qty
            if log.log_date == today:
                today_orders[log.courier_id] += qty

    today_attendances = {}
    if c_ids:
        today_dt_start = datetime.combine(today, datetime.min.time())
        today_dt_end = datetime.combine(today + timedelta(days=1), datetime.min.time())
        atts = (
            db.query(ent.Attendance)
            .filter(
                ent.Attendance.courier_id.in_(c_ids),
                ent.Attendance.check_in >= today_dt_start,
                ent.Attendance.check_in < today_dt_end,
            )
            .all()
        )
        for att in atts:
            today_attendances[att.courier_id] = {
                "checked_in": True,
                "time": att.check_in.strftime("%H:%M") if att.check_in else None,
                "is_late": att.is_late,
            }

    branch_ids = [c.contract_branch_id for c in couriers if c.contract_branch_id]
    branches = (
        {
            b.id: (b.branch_name or b.city or f"فرع #{b.id}")
            for b in db.query(ent.ContractBranch)
            .filter(ent.ContractBranch.id.in_(branch_ids))
            .all()
        }
        if branch_ids
        else {}
    )

    rows = []
    total_month_orders = 0
    total_today_orders = 0
    on_track_count = 0
    at_risk_count = 0
    achieved_count = 0

    for c in couriers:
        done = month_orders[c.id]
        t_orders = today_orders[c.id]
        target = int(c.bonus_target or 400)
        if target <= 0:
            target = 400

        total_month_orders += done
        total_today_orders += t_orders

        pct = round((done / target) * 100, 1) if target > 0 else 100.0
        remaining = max(0, target - done)
        required_daily_rate = round(remaining / remaining_days, 1) if remaining > 0 else 0.0

        expected_pace = (day_of_month / days_in_month) * target
        if done >= target:
            status = "ACHIEVED"
            achieved_count += 1
        elif done >= expected_pace * 0.85:
            status = "ON_TRACK"
            on_track_count += 1
        else:
            status = "AT_RISK"
            at_risk_count += 1

        att_info = today_attendances.get(
            c.id, {"checked_in": False, "time": None, "is_late": False}
        )

        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "branch_id": c.contract_branch_id,
                "branch_name": branches.get(
                    c.contract_branch_id, c.zone or "الفرع الرئيسي"
                ),
                "checked_in": att_info["checked_in"],
                "checkin_time": att_info["time"],
                "today_orders": t_orders,
                "month_orders": done,
                "monthly_target": target,
                "achievement_pct": pct,
                "remaining_orders": remaining,
                "required_daily_rate": required_daily_rate,
                "status": status,
            }
        )

    return {
        "month": selected_month,
        "days_in_month": days_in_month,
        "day_of_month": day_of_month,
        "remaining_days": remaining_days,
        "summary": {
            "total_couriers": len(couriers),
            "total_today_orders": total_today_orders,
            "total_month_orders": total_month_orders,
            "avg_orders_per_courier": round(
                total_month_orders / max(1, len(couriers)), 1
            ),
            "achieved_count": achieved_count,
            "on_track_count": on_track_count,
            "at_risk_count": at_risk_count,
        },
        "rows": rows,
    }


def _generate_metabase_embed_url(
    dashboard_id: int, tenant_id: Optional[int] = None
) -> str:
    """Generate signed JWT embed URL for Metabase dashboard."""
    if dashboard_id not in ALLOWED_METABASE_DASHBOARD_IDS:
        raise HTTPException(404, "Unknown analytics dashboard")
    secret = (
        METABASE_EMBEDDING_SECRET_KEY
        or "a0bf24b622703a7b0da3d379d54dcea58b9b1fd6e2796b1abce80506fb2346c5"
    )
    payload = {
        "resource": {"dashboard": dashboard_id},
        "params": {},
        "exp": int(time.time()) + (24 * 60 * 60),  # 24 hours expiry using true POSIX epoch
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    return f"{METABASE_SITE_URL}/embed/dashboard/{token}#bordered=false&titled=false"



@router.get("/catalog")
def report_catalog(user: ent.User = Depends(get_current_user)):
    """Return available reports based on role."""
    role = user.role
    catalog = {
        "workforce": [
            {
                "id": "rider_master",
                "name_ar": "تقرير المندوبين",
                "name_en": "Rider Master Report",
                "description": "سجل المناديب والتوزيع الميداني",
            },
            {
                "id": "active_inactive",
                "name_ar": "المندوبين النشطين/غير النشطين",
                "name_en": "Active/Inactive Riders",
                "description": "حالة النشاط التشغيلي للقوة العاملة",
            },
            {
                "id": "rider_assignment",
                "name_ar": "تقرير التوزيع",
                "name_en": "Rider Assignment Report",
                "description": "توزيع المناديب على الفروع والمشرفين",
            },
            {
                "id": "city_distribution",
                "name_ar": "توزيع المدن",
                "name_en": "City/Branch Distribution",
                "description": "إحصائيات المناديب حسب المدينة",
            },
        ],
        "attendance": [
            {
                "id": "attendance_report",
                "name_ar": "تقرير الحضور",
                "name_en": "Attendance Report",
                "description": "سجل الحضور اليومي والدخول والخروج",
            },
            {
                "id": "working_hours",
                "name_ar": "ساعات العمل",
                "name_en": "Working Hours Report",
                "description": "إجمالي ساعات العمل المنجزة",
            },
            {
                "id": "late_absence",
                "name_ar": "التأخير والغياب",
                "name_en": "Late/Absence Report",
                "description": "معدلات الغياب والتأخير غير المبرر",
            },
        ],
        "leave": [
            {
                "id": "leave_requests",
                "name_ar": "طلبات الإجازات",
                "name_en": "Leave Requests",
                "description": "سجل طلبات الإجازات وحالة الاعتماد",
            },
            {
                "id": "leave_balances",
                "name_ar": "رصيد الإجازات",
                "name_en": "Leave Balances",
                "description": "أرصدة الاستحقاق والمتبقي لكل سائق",
            },
        ],
        "documents": [
            {
                "id": "rider_documents",
                "name_ar": "مستندات المندوبين",
                "name_en": "Rider Documents",
                "description": "حالة الوثائق والهويات والرخص",
            },
            {
                "id": "expiring_documents",
                "name_ar": "المستندات المنتهية قريباً",
                "name_en": "Expiring Documents",
                "description": "وثائق تنتهي خلال 30 إلى 60 يوماً",
            },
            {
                "id": "expired_documents",
                "name_ar": "المستندات المنتهية",
                "name_en": "Expired Documents",
                "description": "وثائق منتهية تتطلب التجديد الفوري",
            },
            {
                "id": "missing_documents",
                "name_ar": "المستندات المفقودة",
                "name_en": "Missing Documents",
                "description": "سائقون لديهم نواقص في ملف KYC",
            },
        ],
        "vehicles": [
            {
                "id": "vehicle_master",
                "name_ar": "تقرير المركبات",
                "name_en": "Vehicle Master",
                "description": "سجل مركبات الأسطول واللوحات",
            },
            {
                "id": "rider_vehicle_assignment",
                "name_ar": "توزيع المركبات",
                "name_en": "Rider-Vehicle Assignment",
                "description": "المركبات المسندة لكل سائق",
            },
            {
                "id": "unassigned_riders",
                "name_ar": "مندوبين بدون مركبة",
                "name_en": "Unassigned Riders",
                "description": "سائقون بانتظار إسناد مركبة",
            },
        ],
        "orders": [
            {
                "id": "operational_performance",
                "name_ar": "الأداء التشغيلي",
                "name_en": "Operational Performance",
                "description": "حجم التوصيلات والطلبات اليومية",
            },
            {
                "id": "import_batches",
                "name_ar": "دفعات الاستيراد",
                "name_en": "Import Batches",
                "description": "سجل ملفات وبيانات المنصات المستوردة",
            },
            {
                "id": "import_failures",
                "name_ar": "فشل الاستيراد",
                "name_en": "Import Failures",
                "description": "الصفوف غير المطابقة بانتظار المعالجة",
            },
        ],
        "performance": [
            {
                "id": "rider_performance",
                "name_ar": "أداء المندوب",
                "name_en": "Rider Performance",
                "description": "إنتاجية كل سائق ومعدل الإكمال",
            },
            {
                "id": "team_performance",
                "name_ar": "أداء الفريق",
                "name_en": "Team Performance",
                "description": "مقارنة أداء المشرفين والفرق",
            },
            {
                "id": "branch_performance",
                "name_ar": "أداء الفرع",
                "name_en": "Branch Performance",
                "description": "إحصائيات الفروع والمشاريع",
            },
            {
                "id": "target_achievement",
                "name_ar": "تحقيق الأهداف",
                "name_en": "Target Achievement",
                "description": "نسبة تحقيق المستهدفات المعتمدة",
            },
            {
                "id": "below_target",
                "name_ar": "أقل من الهدف",
                "name_en": "Below-Target Riders",
                "description": "السائقون المحتاجون لدعم تشغيلي",
            },
        ],
        "financial": [
            {
                "id": "payroll_ledger",
                "name_ar": "أستاذ الرواتب",
                "name_en": "Payroll Ledger",
                "description": "مسير الرواتب المالي المفصل",
            },
            {
                "id": "rider_payroll_breakdown",
                "name_ar": "تفصيل راتب المندوب",
                "name_en": "Rider Payroll Breakdown",
                "description": "الأساسي والحوافز والخصومات لكل سائق",
            },
            {
                "id": "incentives_report",
                "name_ar": "الحوافز",
                "name_en": "Incentives Report",
                "description": "المكافآت والشرائح المحققة",
            },
            {
                "id": "deductions_report",
                "name_ar": "الخصومات",
                "name_en": "Deductions Report",
                "description": "الجزاءات والغياب والسلف",
            },
            {
                "id": "manual_adjustments",
                "name_ar": "التعديلات اليدوية",
                "name_en": "Manual Adjustments",
                "description": "التسويات المالية اليدوية",
            },
            {
                "id": "reversals_report",
                "name_ar": "المعكوسات",
                "name_en": "Reversals Report",
                "description": "القيود المالية المعكوسة والمصححة",
            },
            {
                "id": "cost_summary",
                "name_ar": "ملخص التكاليف",
                "name_en": "Cost Summary",
                "description": "تكلفة الأسطول ومقارنة الإيراد",
            },
        ],
        "audit": [
            {
                "id": "integration_audit",
                "name_ar": "سجل تكامل البيانات",
                "name_en": "Integration Audit",
                "description": "تتبع عمليات التكامل المصرح بها",
            },
            {
                "id": "security_audit",
                "name_ar": "سجل الأمان",
                "name_en": "Security Audit",
                "description": "أحداث الأمان ضمن نطاق الشركة",
            },
        ],
    }

    role_permissions = {
        ent.UserRole.SUPERVISOR: ["workforce", "attendance", "performance"],
        ent.UserRole.PROJECT_MANAGER: [
            "workforce",
            "attendance",
            "performance",
            "orders",
        ],
        ent.UserRole.HR: ["workforce", "attendance", "leave", "documents"],
        ent.UserRole.ACCOUNTANT: ["financial"],
        ent.UserRole.OPERATIONS: [
            "workforce",
            "attendance",
            "orders",
            "performance",
            "documents",
            "vehicles",
        ],
    }

    allowed = role_permissions.get(role)
    if allowed:
        catalog = {k: v for k, v in catalog.items() if k in allowed}

    return {
        "catalog": catalog,
        "role": role.value if hasattr(role, "value") else str(role),
    }


@router.get("/analytics-views")
def analytics_views(user: ent.User = Depends(get_current_user)):
    """Return the stable analytics view contract used by reporting clients."""
    _tenant_id(user)
    return {
        "views": [
            {"id": "analytics_workforce", "name": "Workforce"},
            {"id": "analytics_attendance", "name": "Attendance"},
            {"id": "analytics_rider_performance", "name": "Rider performance"},
            {"id": "analytics_orders", "name": "Orders"},
            {"id": "analytics_payroll", "name": "Payroll"},
        ]
    }


@router.get("/dashboards")
@router.get("/metabase/dashboards")
def metabase_dashboards(user: ent.User = Depends(get_current_user)):
    """Return available Metabase interactive dashboards with signed JWT embed URLs."""
    tenant_id = _tenant_id(user)
    dashboards = [
        {
            "id": 2,
            "key": "executive_ops",
            "title": "لوحة العمليات التنفيذية",
            "name_ar": "لوحة العمليات التنفيذية",
            "name_en": "Executive Operations Dashboard",
            "description": "نظرة شاملة على السائقين، الورديات، الحضور، ومعدل الامتثال العام للأسطول",
            "icon": "📊",
            "embed_url": _generate_metabase_embed_url(2, tenant_id),
            "kpis": [
                {"label": "إجمالي الأسطول", "value": "محدث"},
                {"label": "نسبة الحضور", "value": "94%"},
                {"label": "معدل الإنجاز", "value": "98.2%"},
            ],
        },
        {
            "id": 3,
            "key": "workforce_readiness",
            "title": "لوحة القوى العاملة والجاهزية",
            "name_ar": "لوحة القوى العاملة والجاهزية",
            "name_en": "Workforce & Readiness Dashboard",
            "description": "توزيع السائقين على الفروع، رصد الموانع التشغيلية، ومتابعة وثائق KYC",
            "icon": "👥",
            "embed_url": _generate_metabase_embed_url(3, tenant_id),
            "kpis": [
                {"label": "جاهز للتشغيل", "value": "85%"},
                {"label": "وثائق مكتملة", "value": "91%"},
            ],
        },
        {
            "id": 4,
            "key": "attendance_shifts",
            "title": "لوحة الحضور والورديات الميدانية",
            "name_ar": "لوحة الحضور والورديات الميدانية",
            "name_en": "Attendance & Shift Compliance",
            "description": "تحليل أوقات الدخول والخروج، التأخير والغياب، وتغطية ساعات العمل",
            "icon": "⏱️",
            "embed_url": _generate_metabase_embed_url(4, tenant_id),
            "kpis": [
                {"label": "الالتزام بالورديات", "value": "92%"},
                {"label": "متوسط الساعات", "value": "8.4 س"},
            ],
        },
        {
            "id": 5,
            "key": "rider_performance",
            "title": "لوحة أداء المناديب وجودة الخدمة",
            "name_ar": "لوحة أداء المناديب وجودة الخدمة",
            "name_en": "Rider Performance & SLA Matrix",
            "description": "أعلى المناديب إنجازاً، معدل قبول الطلبات، ونسب تحقيق الأهداف",
            "icon": "🎯",
            "embed_url": _generate_metabase_embed_url(5, tenant_id),
            "kpis": [
                {"label": "معدل القبول", "value": "96.5%"},
                {"label": "تحقيق التارجت", "value": "88%"},
            ],
        },
        {
            "id": 6,
            "key": "payroll_financial",
            "title": "لوحة الرواتب والتسويات المالية",
            "name_ar": "لوحة الرواتب والتسويات المالية",
            "name_en": "Payroll & Financial Summary",
            "description": "تفصيل الرواتب الأساسية، الحوافز المكتسبة، والخصومات المعتمدة",
            "icon": "💰",
            "embed_url": _generate_metabase_embed_url(6, tenant_id),
            "kpis": [
                {"label": "إجمالي المسير", "value": "مستقر"},
                {"label": "نسبة الحوافز", "value": "18%"},
            ],
        },
    ]
    return {
        "dashboards": dashboards,
        "metabase_url": METABASE_SITE_URL,
        "status": "AVAILABLE",
    }


@router.get("/dashboards/{dashboard_id}/embed")
@router.get("/metabase/dashboards/{dashboard_id}/embed")
def metabase_dashboard_embed(
    dashboard_id: int, user: ent.User = Depends(get_current_user)
):
    tenant_id = _tenant_id(user)
    iframe_url = _generate_metabase_embed_url(dashboard_id, tenant_id)
    return {"iframe_url": iframe_url, "dashboard_id": dashboard_id}


@router.get("/workforce/rider_master")
def workforce_rider_master(
    city_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    project_id: Optional[int] = None,
    employment_status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rider master report with hierarchy filtering."""
    tenant_id = _tenant_id(user)
    page, page_size = _convert_query_objects(page, page_size)
    page = page or 1
    page_size = page_size or 50

    query = db.query(ent.Courier).filter(ent.Courier.tenant_id == tenant_id)
    if city_id:
        query = query.filter(ent.Courier.city_id == city_id)
    if branch_id:
        query = query.filter(ent.Courier.contract_branch_id == branch_id)
    if project_id:
        query = query.filter(ent.Courier.primary_project_id == project_id)
    if employment_status:
        query = query.filter(ent.Courier.employment_status == employment_status)

    total = query.count()
    riders = (
        query.order_by(ent.Courier.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    rows = []
    for r in riders:
        rows.append(
            {
                "rider_id": r.id,
                "name": r.name,
                "phone": r.phone,
                "city": r.city_id,
                "branch": r.contract_branch_id,
                "supervisor": r.supervisor_id or "—",
                "status": r.employment_status,
                "type": r.courier_type.value if r.courier_type else "COMPANY",
            }
        )

    return {
        "report": "rider_master",
        "title_ar": "تقرير المندوبين الشامل",
        "total": total,
        "page": page,
        "page_size": page_size,
        "kpis": [
            {"label": "إجمالي المناديب", "value": total},
            {
                "label": "نشطون",
                "value": len([r for r in rows if r["status"] == "ACTIVE"]),
            },
        ],
        "rows": rows,
    }


@router.get("/attendance/summary")
def attendance_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    city_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attendance summary report."""
    tenant_id = _tenant_id(user)
    end = date_to or date.today()
    start = date_from or (end - timedelta(days=30))

    query = db.query(ent.Courier).filter(ent.Courier.tenant_id == tenant_id)
    if city_id:
        query = query.filter(ent.Courier.city_id == city_id)
    if branch_id:
        query = query.filter(ent.Courier.contract_branch_id == branch_id)

    riders = query.all()
    rider_ids = [r.id for r in riders]

    if not rider_ids:
        return {
            "report": "attendance_summary",
            "title_ar": "تقرير الحضور والورديات",
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "total_riders": 0,
            "rows": [],
            "kpis": [],
        }

    attendances = (
        db.query(ent.Attendance)
        .filter(
            ent.Attendance.courier_id.in_(rider_ids),
            ent.Attendance.check_in >= datetime.combine(start, datetime.min.time()),
            ent.Attendance.check_in <= datetime.combine(end, datetime.max.time()),
        )
        .all()
    )

    rider_attendance = {}
    for a in attendances:
        if a.courier_id not in rider_attendance:
            rider_attendance[a.courier_id] = {"days": set(), "late": 0, "hours": 0}
        if a.check_in:
            rider_attendance[a.courier_id]["days"].add(a.check_in.date())
        if a.is_late:
            rider_attendance[a.courier_id]["late"] += 1
        if a.check_out and a.check_in:
            rider_attendance[a.courier_id]["hours"] += (
                a.check_out - a.check_in
            ).total_seconds() / 3600

    rows = []
    total_days = 0
    total_late = 0
    for r in riders:
        att = rider_attendance.get(r.id, {"days": set(), "late": 0, "hours": 0})
        days_count = len(att["days"])
        total_days += days_count
        total_late += att["late"]
        rows.append(
            {
                "rider_id": r.id,
                "name": r.name,
                "attendance_days": days_count,
                "late_count": att["late"],
                "worked_hours": round(att["hours"], 1),
                "status": "ملتزم" if att["late"] == 0 else "يوجد تأخير",
            }
        )

    return {
        "report": "attendance_summary",
        "title_ar": "تقرير الحضور وساعات العمل",
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "total_riders": len(riders),
        "kpis": [
            {"label": "إجمالي أيام الحضور", "value": total_days},
            {"label": "سجلات التأخير", "value": total_late},
            {"label": "نسبة الالتزام", "value": f"{max(0, 100 - (total_late * 5))}%"},
        ],
        "rows": rows,
    }


@router.get("/financial/payroll_ledger")
def financial_payroll_ledger(
    month: Optional[str] = None,
    city_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    input_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Payroll ledger report."""
    tenant_id = _tenant_id(user)
    page, page_size = _convert_query_objects(page, page_size)
    page = page or 1
    page_size = page_size or 50
    period = month or date.today().strftime("%Y-%m")

    query = db.query(ent.PayrollInputRecord).filter(
        ent.PayrollInputRecord.tenant_id == tenant_id,
        ent.PayrollInputRecord.month == period,
    )
    if input_type:
        query = query.filter(ent.PayrollInputRecord.input_type == input_type)

    query = query.join(ent.Courier, ent.PayrollInputRecord.courier_id == ent.Courier.id)
    if city_id:
        query = query.filter(ent.Courier.city_id == city_id)
    if branch_id:
        query = query.filter(ent.Courier.contract_branch_id == branch_id)

    total = query.count()
    records = (
        query.order_by(ent.PayrollInputRecord.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    rows = []
    total_amount = Decimal("0")
    for rec in records:
        total_amount += rec.amount or Decimal("0")
        rows.append(
            {
                "id": rec.id,
                "courier_id": rec.courier_id,
                "month": rec.month,
                "input_type": rec.input_type,
                "amount": float(rec.amount or 0),
                "amount_formatted": f"{float(rec.amount or 0):,.2f} ر.س",
                "description": rec.description or "—",
                "status": rec.status,
            }
        )

    return {
        "report": "payroll_ledger",
        "title_ar": "مسير أستاذ الرواتب والتسويات",
        "period": period,
        "total": total,
        "page": page,
        "page_size": page_size,
        "kpis": [
            {"label": "إجمالي المسجل", "value": f"{float(total_amount):,.2f} ر.س"},
            {"label": "عدد القيود", "value": total},
        ],
        "rows": rows,
    }


@router.get("/download/csv")
def download_csv(
    report_type: str = Query(...),
    group: Optional[str] = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stable CSV download route declared before the generic report route."""
    return export_csv(report_type=report_type, group=group, user=user, db=db)


@router.get("/download/xlsx")
def download_xlsx(
    report_type: str = Query(...),
    group: Optional[str] = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stable XLSX download route declared before the generic report route."""
    return export_xlsx(report_type=report_type, group=group, user=user, db=db)


@router.get("/platform-facts/contracts")
def platform_fact_contracts(
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tenant contracts available for platform-performance uploads."""
    tenant_id = _tenant_id(user)
    contracts = (
        db.query(ent.Contract)
        .filter(ent.Contract.tenant_id == tenant_id)
        .order_by(ent.Contract.name)
        .all()
    )
    return {
        "contracts": [
            {
                "id": contract.id,
                "name": contract.name,
                "status": contract.status,
                "client_name": contract.client_name or contract.name,
            }
            for contract in contracts
        ]
    }


# Generic Dispatcher for all catalog reports with safe entity extraction
def get_report_data(
    group: str,
    report_id: str,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generic report dispatcher handling all report categories with live data."""
    tenant_id = _tenant_id(user)

    # 1. Workforce
    if group == "workforce":
        if report_id == "rider_master":
            return workforce_rider_master(user=user, db=db)
        riders = db.query(ent.Courier).filter(ent.Courier.tenant_id == tenant_id).all()
        rows = []
        for r in riders:
            if report_id == "active_inactive":
                rows.append(
                    {
                        "رقم_السائق": r.id,
                        "الاسم": r.name,
                        "الجوال": r.phone,
                        "الحالة": r.employment_status,
                        "النوع": r.courier_type.value if r.courier_type else "COMPANY",
                    }
                )
            elif report_id == "city_distribution":
                rows.append(
                    {
                        "المدينة": r.city_id,
                        "السائق": r.name,
                        "الجوال": r.phone,
                        "الفرع": r.contract_branch_id,
                        "الحالة": r.employment_status,
                    }
                )
            else:
                rows.append(
                    {
                        "رقم_السائق": r.id,
                        "الاسم": r.name,
                        "الفرع": r.contract_branch_id,
                        "المشرف": r.supervisor_id or "—",
                        "الحالة": r.employment_status,
                    }
                )
        return {
            "report": report_id,
            "title_ar": "تقرير القوى العاملة",
            "total": len(rows),
            "rows": rows,
            "kpis": [
                {"label": "إجمالي المناديب", "value": len(rows)},
                {
                    "label": "نشطون",
                    "value": len(
                        [r for r in riders if r.employment_status == "ACTIVE"]
                    ),
                },
            ],
        }

    # 2. Attendance
    elif group == "attendance":
        return attendance_summary(user=user, db=db)

    # 3. Documents
    elif group == "documents":
        docs = (
            db.query(ent.CourierDocumentSubmission)
            .filter(ent.CourierDocumentSubmission.tenant_id == tenant_id)
            .all()
            if hasattr(ent, "CourierDocumentSubmission")
            else []
        )
        rows = []
        for d in docs:
            rows.append(
                {
                    "رقم_المستند": d.id,
                    "السائق": d.courier_id,
                    "نوع_المستند": d.document_type,
                    "اسم_الملف": d.filename or "—",
                    "الحالة": d.status,
                    "تاريخ_الرفع": str(d.created_at or "—")[:10],
                }
            )
        return {
            "report": report_id,
            "title_ar": "تقرير المستندات والامتثال",
            "total": len(rows),
            "rows": rows,
            "kpis": [{"label": "إجمالي السجلات", "value": len(rows)}],
        }

    # 4. Vehicles
    elif group == "vehicles":
        vehicles = (
            db.query(ent.Vehicle).filter(ent.Vehicle.tenant_id == tenant_id).all()
        )
        assignments = (
            {
                a.vehicle_id: a.courier_id
                for a in db.query(ent.RiderVehicleAssignment)
                .filter(
                    ent.RiderVehicleAssignment.tenant_id == tenant_id,
                    ent.RiderVehicleAssignment.is_primary.is_(True),
                )
                .all()
            }
            if hasattr(ent, "RiderVehicleAssignment")
            else {}
        )
        rows = []
        if report_id == "unassigned_riders":
            assigned_courier_ids = set(assignments.values())
            riders = (
                db.query(ent.Courier).filter(ent.Courier.tenant_id == tenant_id).all()
            )
            for r in riders:
                if r.id not in assigned_courier_ids:
                    rows.append(
                        {
                            "رقم_السائق": r.id,
                            "الاسم": r.name,
                            "الجوال": r.phone,
                            "الفرع": r.contract_branch_id or 1,
                            "الحالة": "بانتظار إسناد مركبة",
                        }
                    )
        else:
            for v in vehicles:
                assigned_courier = assignments.get(v.id, "غير مسند")
                rows.append(
                    {
                        "معرف_المركبة": v.id,
                        "اللوحة": v.plate_number,
                        "النوع": v.vehicle_type or "سيارة",
                        "الموديل": v.model or "—",
                        "الحالة_التشغيلية": v.operational_status or "نشطة",
                        "السائق_المسند": assigned_courier,
                    }
                )
        return {
            "report": report_id,
            "title_ar": "تقرير الأسطول والمركبات",
            "total": len(rows),
            "rows": rows,
            "kpis": [
                {"label": "إجمالي السجلات", "value": len(rows)},
                {"label": "المركبات النشطة", "value": len(vehicles)},
            ],
        }

    # 5. Leaves
    elif group == "leave":
        leaves = (
            db.query(ent.LeaveRequest)
            .filter(ent.LeaveRequest.tenant_id == tenant_id)
            .all()
            if hasattr(ent, "LeaveRequest")
            else []
        )
        rows = []
        for req in leaves:
            days_count = (
                (req.to_date - req.from_date).days + 1 if (req.to_date and req.from_date) else 1
            )
            rows.append(
                {
                    "رقم_الطلب": req.id,
                    "السائق": req.courier_id,
                    "من": str(req.from_date),
                    "إلى": str(req.to_date),
                    "عدد_الأيام": days_count,
                    "الحالة": req.status,
                    "السبب": req.reason or "—",
                }
            )
        return {
            "report": report_id,
            "title_ar": "تقرير الإجازات والأرصدة",
            "total": len(rows),
            "rows": rows,
            "kpis": [{"label": "طلبات الإجازات", "value": len(rows)}],
        }

    # 6. Orders
    elif group == "orders":
        batches = (
            db.query(ent.OperationalImportBatch)
            .filter(ent.OperationalImportBatch.tenant_id == tenant_id)
            .all()
            if hasattr(ent, "OperationalImportBatch")
            else []
        )
        rows = []
        for b in batches:
            rows.append(
                {
                    "رقم_الدفعة": b.id,
                    "نوع_الاستيراد": b.import_type,
                    "الملف": b.file_name or "—",
                    "إجمالي_الصفوف": b.total_rows or 0,
                    "الصفوف_السليمة": b.valid_rows or 0,
                    "الأخطاء": b.invalid_rows or 0,
                    "الحالة": b.status,
                    "تاريخ_الاستيراد": str(b.created_at or "—")[:19],
                }
            )
        return {
            "report": report_id,
            "title_ar": "تقرير العمليات والطلبات",
            "total": len(rows),
            "rows": rows,
            "kpis": [{"label": "إجمالي الدفعات", "value": len(rows)}],
        }

    # 7. Performance
    elif group == "performance":
        targets = (
            db.query(ent.Target).filter(ent.Target.tenant_id == tenant_id).all()
            if hasattr(ent, "Target")
            else []
        )
        rows = []
        for t in targets:
            rows.append(
                {
                    "الهدف": t.target_type,
                    "النطاق": t.scope_type,
                    "المستهدف": t.target_value,
                    "الفعلي": t.actual_value,
                    "نسبة_الإنجاز": f"{t.achievement_percentage or 0}%",
                    "الفترة": t.period,
                }
            )
        return {
            "report": report_id,
            "title_ar": "تقرير مؤشرات الأداء",
            "total": len(rows),
            "rows": rows,
            "kpis": [{"label": "الأهداف المحددة", "value": len(rows)}],
        }

    # 8. Financial
    elif group == "financial":
        if report_id == "payroll_ledger":
            return financial_payroll_ledger(user=user, db=db)
        inputs = (
            db.query(ent.PayrollInputRecord)
            .filter(ent.PayrollInputRecord.tenant_id == tenant_id)
            .all()
        )
        rows = []
        for i in inputs:
            rows.append(
                {
                    "السائق": i.courier_id,
                    "الشهر": i.month,
                    "النوع": i.input_type,
                    "المبلغ": f"{float(i.amount or 0):,.2f} ر.س",
                    "الوصف": i.description or "—",
                    "الحالة": i.status,
                }
            )
        return {
            "report": report_id,
            "title_ar": "تقرير العمليات والرواتب",
            "total": len(rows),
            "rows": rows,
            "kpis": [{"label": "عدد القيود", "value": len(rows)}],
        }

    elif group == "audit":
        if report_id == "integration_audit":
            logs = (
                db.query(ent.IntegrationAuditLog)
                .filter(ent.IntegrationAuditLog.tenant_id == tenant_id)
                .order_by(ent.IntegrationAuditLog.timestamp.desc())
                .limit(500)
                .all()
            )
            rows = [
                {
                    "id": row.id,
                    "direction": row.direction,
                    "event_type": row.event_type,
                    "status_code": row.status_code,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                }
                for row in logs
            ]
        elif report_id == "security_audit":
            logs = (
                db.query(ent.SecurityAuditLog)
                .filter(ent.SecurityAuditLog.tenant_id == tenant_id)
                .order_by(ent.SecurityAuditLog.timestamp.desc())
                .limit(500)
                .all()
            )
            rows = [
                {
                    "id": row.id,
                    "actor_id": row.actor_id,
                    "actor_role": row.actor_role,
                    "action": row.action,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                }
                for row in logs
            ]
        else:
            raise HTTPException(404, "Unknown audit report")
        return {
            "report": report_id,
            "title_ar": "سجل التدقيق",
            "total": len(rows),
            "rows": rows,
            "kpis": [{"label": "إجمالي السجلات", "value": len(rows)}],
        }

    # Default Fallback
    riders = db.query(ent.Courier).filter(ent.Courier.tenant_id == tenant_id).all()
    rows = [
        {"رقم": r.id, "الاسم": r.name, "الحالة": r.employment_status} for r in riders
    ]
    return {
        "report": report_id,
        "title_ar": f"تقرير: {report_id}",
        "total": len(rows),
        "rows": rows,
        "kpis": [{"label": "الإجمالي", "value": len(rows)}],
    }


@router.get("/export/csv")
def export_csv(
    report_type: str = Query(...),
    group: Optional[str] = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generic CSV export endpoint for all reports."""
    data = get_report_data(group or "workforce", report_type, user=user, db=db)
    rows = data.get("rows", [])

    output = io.StringIO()
    output.write("\ufeff")  # BOM for Arabic Excel support
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("لا توجد بيانات\n")

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="dou-{report_type}-{date.today().isoformat()}.csv"'
        },
    )


@router.get("/export/xlsx")
def export_xlsx(
    report_type: str = Query(...),
    group: Optional[str] = None,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Excel XLSX export endpoint."""
    data = get_report_data(group or "workforce", report_type, user=user, db=db)
    rows = data.get("rows", [])

    try:
        from openpyxl import Workbook

        USE_OPENPYXL = True
    except ImportError:
        import xlsxwriter

        USE_OPENPYXL = False

    output = io.BytesIO()
    if USE_OPENPYXL:
        wb = Workbook()
        ws = wb.active
        ws.title = report_type[:30]
        if rows:
            headers = list(rows[0].keys())
            ws.append(headers)
            for r in rows:
                ws.append([r.get(h) for h in headers])
        else:
            ws.append(["لا توجد بيانات"])
        wb.save(output)
    else:
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet(report_type[:30])
        if rows:
            headers = list(rows[0].keys())
            for col, header in enumerate(headers):
                worksheet.write(0, col, header)
            for row_idx, r in enumerate(rows, 1):
                for col, header in enumerate(headers):
                    worksheet.write(row_idx, col, r.get(header))
        else:
            worksheet.write(0, 0, "لا توجد بيانات")
        workbook.close()

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="dou-{report_type}-{date.today().isoformat()}.xlsx"'
        },
    )


# ---------- Platform Delivery Facts (Raw Data & Analytics) ----------


@router.get("/platform-facts")
def get_platform_delivery_facts(
    contract_id: Optional[int] = Query(None),
    contract_name: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    report_date: Optional[str] = Query(None, alias="date"),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve raw platform delivery facts (19 KPIs) and summary analytics."""
    tenant_id = _tenant_id(user)
    q = db.query(ent.PlatformDeliveryFact).filter(
        ent.PlatformDeliveryFact.tenant_id == tenant_id
    )
    if contract_id:
        q = q.filter(ent.PlatformDeliveryFact.contract_id == contract_id)
    elif contract_name:
        q = q.filter(ent.PlatformDeliveryFact.contract_name == contract_name)
    all_rows = q.order_by(ent.PlatformDeliveryFact.created_date.desc()).all()
    available_dates = sorted(
        {r.created_date.isoformat() for r in all_rows if r.created_date},
        reverse=True,
    )
    selected_date = report_date or (available_dates[0] if available_dates else None)
    if report_date:
        try:
            datetime.strptime(report_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "date غير صالح — استخدم YYYY-MM-DD")
    if month and not report_date:
        rows = [
            r
            for r in all_rows
            if r.created_date and r.created_date.strftime("%Y-%m") == month
        ]
        selected_date = None
    else:
        rows = [
            r
            for r in all_rows
            if r.created_date and r.created_date.isoformat() == selected_date
        ]

    # Calculate aggregated analytics
    total_notified = sum(r.notified_deliveries or 0 for r in rows)
    total_completed = sum(r.completed_deliveries or 0 for r in rows)
    total_accepted = sum(r.accepted_deliveries or 0 for r in rows)
    total_stacked = sum(r.stacked_deliveries or 0 for r in rows)
    total_declined = sum(r.declined_deliveries or 0 for r in rows)
    total_cancelled = sum(r.cancelled_deliveries or 0 for r in rows)
    total_no_shows = sum(r.no_shows or 0 for r in rows)
    total_planned_hours = sum(r.planned_hours or 0.0 for r in rows)
    total_actual_hours = sum(r.actual_working_hours or 0.0 for r in rows)
    total_break_hours = sum(r.break_hours or 0.0 for r in rows)

    avg_acceptance_rate = (
        (total_accepted / total_notified) if total_notified > 0 else 1.0
    )
    completion_rate = (total_completed / total_notified) if total_notified > 0 else 1.0
    stacked_rate = (total_stacked / total_completed) if total_completed > 0 else 0.0
    hours_utilization = (
        (total_actual_hours / total_planned_hours) if total_planned_hours > 0 else 1.0
    )

    return {
        "summary": {
            "total_records": len(rows),
            "total_notified": total_notified,
            "total_completed": total_completed,
            "total_accepted": total_accepted,
            "total_stacked": total_stacked,
            "total_declined": total_declined,
            "total_cancelled": total_cancelled,
            "total_no_shows": total_no_shows,
            "total_planned_hours": round(total_planned_hours, 2),
            "total_actual_hours": round(total_actual_hours, 2),
            "total_break_hours": round(total_break_hours, 2),
            "avg_acceptance_rate": round(avg_acceptance_rate * 100, 1),
            "completion_rate": round(completion_rate * 100, 1),
            "stacked_rate": round(stacked_rate * 100, 1),
            "hours_utilization": round(hours_utilization * 100, 1),
            "selected_date": selected_date,
            "available_dates": available_dates,
        },
        "rows": [
            {
                "id": r.id,
                "contract_id": r.contract_id,
                "created_date": r.created_date.isoformat() if r.created_date else None,
                "city_name": r.city_name,
                "contract_name": r.contract_name,
                "riders_count": r.riders_count,
                "shifts_done": r.shifts_done,
                "planned_hours": round(r.planned_hours or 0, 2),
                "actual_working_hours": round(r.actual_working_hours or 0, 2),
                "break_hours": round(r.break_hours or 0, 2),
                "acceptance_rate": round((r.acceptance_rate or 0) * 100, 1),
                "contact_rate": round((r.contact_rate or 0) * 100, 2),
                "no_shows": r.no_shows,
                "notified_deliveries": r.notified_deliveries,
                "completed_deliveries": r.completed_deliveries,
                "accepted_deliveries": r.accepted_deliveries,
                "stacked_deliveries": r.stacked_deliveries,
                "declined_deliveries": r.declined_deliveries,
                "cancelled_deliveries": r.cancelled_deliveries,
                "deduction_deliveries": r.deduction_deliveries,
                "not_accepted_deliveries": r.not_accepted_deliveries,
            }
            for r in rows
        ],
    }


@router.post("/platform-facts/upload")
def upload_platform_delivery_facts(
    payload: dict,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload and ingest raw platform performance CSV records (19 columns)."""
    tenant_id = _tenant_id(user)
    csv_text = payload.get("csv_text", "")
    if not csv_text:
        raise HTTPException(400, "csv_text is required")
    try:
        contract_id = int(payload.get("contract_id"))
    except (TypeError, ValueError):
        raise HTTPException(400, "contract_id is required")
    contract = (
        db.query(ent.Contract)
        .filter(
            ent.Contract.id == contract_id,
            ent.Contract.tenant_id == tenant_id,
        )
        .first()
    )
    if not contract:
        raise HTTPException(404, "Contract not found for this company")

    f = io.StringIO(csv_text.lstrip("\ufeff").strip())
    reader = csv.DictReader(f)
    required_columns = (
        "Created Date",
        "City Name",
        "Contract Name",
        "# Riders",
        "Shifts Done",
        "Planned Hours",
        "Actual Working Hours",
        "Break Hours",
        "Acceptance Rate",
        "Contact Rate",
        "No Shows",
        "Notified Deliveries",
        "Completed Deliveries",
        "Accepted Deliveries",
        "Stacked Deliveries",
        "Declined Deliveries",
        "Cancelled Deliveries",
        "Deduction Deliveries",
        "Not Accepted Deliveries",
    )
    normalized_headers = {
        (header or "").lstrip("\ufeff").strip() for header in (reader.fieldnames or [])
    }
    missing_columns = [name for name in required_columns if name not in normalized_headers]
    if missing_columns:
        raise HTTPException(
            400,
            "أعمدة مطلوبة غير موجودة: " + ", ".join(missing_columns),
        )

    imported = 0
    updated = 0
    parsed_rows = []
    errors = []

    for row_number, raw_row in enumerate(reader, start=2):
        row = {
            (key or "").lstrip("\ufeff").strip(): (value or "").strip()
            for key, value in raw_row.items()
        }
        date_raw = row.get("Created Date", "")
        if not date_raw:
            errors.append(f"الصف {row_number}: التاريخ فارغ")
            continue
        dt = None
        clean_date = date_raw.strip().strip('"').strip("'")
        for fmt in ["%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y.%m.%d", "%d.%m.%Y"]:
            try:
                dt = datetime.strptime(clean_date, fmt).date()
                break
            except Exception:
                pass
        if not dt:
            errors.append(f"الصف {row_number}: تاريخ غير صالح ({date_raw})")
            continue

        contract_name = contract.name
        city_name = row.get("City Name", "").strip()
        if not city_name:
            errors.append(f"الصف {row_number}: المدينة فارغة")
            continue

        try:
            def number(column, integer=False):
                value = float(row[column]) if row[column] else 0.0
                return int(value) if integer else value

            values = {
                "riders_count": number("# Riders", True),
                "shifts_done": number("Shifts Done", True),
                "planned_hours": number("Planned Hours"),
                "actual_working_hours": number("Actual Working Hours"),
                "break_hours": number("Break Hours"),
                "acceptance_rate": number("Acceptance Rate"),
                "contact_rate": number("Contact Rate"),
                "no_shows": number("No Shows", True),
                "notified_deliveries": number("Notified Deliveries", True),
                "completed_deliveries": number("Completed Deliveries", True),
                "accepted_deliveries": number("Accepted Deliveries", True),
                "stacked_deliveries": number("Stacked Deliveries", True),
                "declined_deliveries": number("Declined Deliveries", True),
                "cancelled_deliveries": number("Cancelled Deliveries", True),
                "deduction_deliveries": number("Deduction Deliveries", True),
                "not_accepted_deliveries": number("Not Accepted Deliveries", True),
            }
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"الصف {row_number}: قيمة رقمية غير صالحة ({exc})")
            continue
        if values["acceptance_rate"] > 1:
            values["acceptance_rate"] /= 100
        if values["contact_rate"] > 1:
            values["contact_rate"] /= 100
        parsed_rows.append((dt, city_name, values))

    if errors:
        raise HTTPException(400, " | ".join(errors[:5]))
    if not parsed_rows:
        raise HTTPException(400, "لم يتم العثور على صفوف بيانات صالحة في الملف")

    for dt, city_name, values in parsed_rows:

        # Check existing
        fact = (
            db.query(ent.PlatformDeliveryFact)
            .filter(
                ent.PlatformDeliveryFact.tenant_id == tenant_id,
                (
                    (ent.PlatformDeliveryFact.contract_id == contract.id)
                    | (
                        (ent.PlatformDeliveryFact.contract_id.is_(None))
                        & (ent.PlatformDeliveryFact.contract_name == contract_name)
                    )
                ),
                ent.PlatformDeliveryFact.created_date == dt,
            )
            .first()
        )

        if fact:
            fact.contract_id = contract.id
            fact.contract_name = contract.name
            for key, value in values.items():
                setattr(fact, key, value)
            fact.source_type = "CSV_IMPORT"
            updated += 1
        else:
            fact = ent.PlatformDeliveryFact(
                tenant_id=tenant_id,
                contract_id=contract.id,
                created_date=dt,
                city_name=city_name,
                contract_name=contract_name,
                **values,
                source_type="CSV_IMPORT",
            )
            db.add(fact)
            imported += 1

    db.commit()
    return {
        "status": "SUCCESS",
        "contract": {"id": contract.id, "name": contract.name},
        "imported": imported,
        "updated": updated,
        "rows_processed": len(parsed_rows),
    }


@router.get("/{group}/{report_id}")
def get_report_data_endpoint(
    group: str,
    report_id: str,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generic catch-all route for domain reports data."""
    return get_report_data(group, report_id, user=user, db=db)
