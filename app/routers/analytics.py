"""Wave 3 router — KPIs, targets, incentive rules, payroll inputs, dashboards."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from ..database import get_db
from ..models import entities as ent
from ..services.workforce_scope import supervisor_courier_scope
from .auth import get_current_user


router = APIRouter(prefix="/analytics", tags=["analytics"])

MANAGE_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.HR,
}
STAFF_ROLES = MANAGE_ROLES | {ent.UserRole.SUPERVISOR}
READ_ROLES = STAFF_ROLES | {
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.VIEWER,
    ent.UserRole.PROJECT_MANAGER,
}


def _tenant_id(user: ent.User, manage: bool = False) -> int:
    allowed = MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(403, "Analytics access required")
    return user.tenant_id


def _same_tenant(db, model, record_id: int, tenant_id: int):
    row = (
        db.query(model)
        .filter(model.id == record_id, model.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


# ---------- schemas ----------


class KPIDefinitionCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    category: str = "OPERATIONS"
    numerator_expression: str
    denominator_expression: Optional[str] = None
    unit: str = "COUNT"
    source_trust_level: str = "MEDIUM"
    version: str = "1.0"
    effective_from: date


class KPIDefinitionUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    numerator_expression: Optional[str] = None
    denominator_expression: Optional[str] = None
    unit: Optional[str] = None
    source_trust_level: Optional[str] = None
    is_active: Optional[bool] = None
    effective_to: Optional[date] = None


class KPIResultCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kpi_definition_id: int
    scope_type: str
    scope_id: int
    period: str
    numerator_value: float = 0
    denominator_value: float = 0
    result_value: float = 0


class TargetCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    scope_type: str
    scope_id: int
    target_type: str
    period: str
    target_value: float


class TargetUpdate(BaseModel):
    actual_value: Optional[float] = None
    achievement_percentage: Optional[float] = None


class IncentiveRuleCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    rule_type: str = "BONUS"
    calculation_expression: str
    priority: int = 0
    precedence_policy: str = "HIGHEST_WINS"
    version: str = "1.0"
    effective_from: date


class IncentiveRuleUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    rule_type: Optional[str] = None
    calculation_expression: Optional[str] = None
    priority: Optional[int] = None
    precedence_policy: Optional[str] = None
    is_active: Optional[bool] = None
    effective_to: Optional[date] = None


class PayrollInputCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    courier_id: int
    month: str
    source_type: str
    source_id: Optional[int] = None
    input_type: str
    amount: float
    description: Optional[str] = None


class PayrollInputUpdate(BaseModel):
    status: str  # APPROVED / VOID


class DashboardCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_ar: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    category: str = "OPERATIONS"


class DashboardUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


class DashboardWidgetCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dashboard_definition_id: int
    kpi_definition_id: Optional[int] = None
    widget_type: str = "METRIC"
    title_ar: str
    title_en: Optional[str] = None
    position: int = 0
    config: Optional[str] = None


# ---------- KPI definitions ----------


@router.post("/kpis", status_code=201)
def create_kpi(
    payload: KPIDefinitionCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.KPIDefinition)
        .filter(
            ent.KPIDefinition.tenant_id == tenant_id,
            ent.KPIDefinition.code == payload.code,
            ent.KPIDefinition.version == payload.version,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            409, "KPI definition with this code and version already exists"
        )
    row = ent.KPIDefinition(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


@router.get("/kpis")
def list_kpis(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.KPIDefinition).filter(ent.KPIDefinition.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ent.KPIDefinition.is_active.is_(True))
    return [
        {
            "id": r.id,
            "code": r.code,
            "name_ar": r.name_ar,
            "name_en": r.name_en,
            "category": r.category,
            "unit": r.unit,
            "version": r.version,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.KPIDefinition.code).all()
    ]


@router.patch("/kpis/{kpi_id}")
def update_kpi(
    kpi_id: int,
    payload: KPIDefinitionUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.KPIDefinition, kpi_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


# ---------- KPI results ----------


@router.post("/kpi-results", status_code=201)
def create_kpi_result(
    payload: KPIResultCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.KPIDefinition, payload.kpi_definition_id, tenant_id)
    existing = (
        db.query(ent.KPIResult)
        .filter(
            ent.KPIResult.tenant_id == tenant_id,
            ent.KPIResult.kpi_definition_id == payload.kpi_definition_id,
            ent.KPIResult.scope_type == payload.scope_type,
            ent.KPIResult.scope_id == payload.scope_id,
            ent.KPIResult.period == payload.period,
        )
        .first()
    )
    if existing:
        # H5 FIX: Atomic update with freshness tracking
        existing.numerator_value = payload.numerator_value
        existing.denominator_value = payload.denominator_value
        existing.result_value = payload.result_value
        existing.freshness_at = datetime.utcnow()
        existing.calculation_version = str(
            float(existing.calculation_version or "1.0") + 0.1
        )
        db.commit()
        db.refresh(existing)
        return {
            "id": existing.id,
            "result_value": existing.result_value,
            "freshness_at": existing.freshness_at.isoformat(),
        }
    row = ent.KPIResult(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "result_value": row.result_value}


@router.get("/kpi-results")
def list_kpi_results(
    kpi_definition_id: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.KPIResult).filter(ent.KPIResult.tenant_id == tenant_id)
    if kpi_definition_id:
        q = q.filter(ent.KPIResult.kpi_definition_id == kpi_definition_id)
    if period:
        q = q.filter(ent.KPIResult.period == period)
    return [
        {
            "id": r.id,
            "kpi_definition_id": r.kpi_definition_id,
            "scope_type": r.scope_type,
            "scope_id": r.scope_id,
            "period": r.period,
            "result_value": r.result_value,
            "freshness_at": r.freshness_at.isoformat(),
        }
        for r in q.order_by(ent.KPIResult.freshness_at.desc()).all()
    ]


# ---------- targets ----------


@router.post("/targets", status_code=201)
def create_target(
    payload: TargetCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.Target)
        .filter(
            ent.Target.tenant_id == tenant_id,
            ent.Target.scope_type == payload.scope_type,
            ent.Target.scope_id == payload.scope_id,
            ent.Target.target_type == payload.target_type,
            ent.Target.period == payload.period,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Target already exists for this scope and period")
    row = ent.Target(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "target_type": row.target_type,
        "target_value": row.target_value,
    }


@router.get("/targets")
def list_targets(
    scope_type: Optional[str] = Query(None),
    scope_id: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.Target).filter(ent.Target.tenant_id == tenant_id)
    if scope_type:
        q = q.filter(ent.Target.scope_type == scope_type)
    if scope_id is not None:
        q = q.filter(ent.Target.scope_id == scope_id)
    if period:
        q = q.filter(ent.Target.period == period)
    if user.role == ent.UserRole.SUPERVISOR:
        scoped_ids = db.query(ent.Courier.id).filter(
            supervisor_courier_scope(db, user.id)
        )
        q = q.filter(
            ent.Target.scope_type == "RIDER",
            ent.Target.scope_id.in_(scoped_ids),
        )
    return [
        {
            "id": r.id,
            "scope_type": r.scope_type,
            "scope_id": r.scope_id,
            "target_type": r.target_type,
            "period": r.period,
            "target_value": r.target_value,
            "actual_value": r.actual_value,
            "achievement_percentage": r.achievement_percentage,
        }
        for r in q.order_by(ent.Target.created_at.desc()).all()
    ]


@router.patch("/targets/{target_id}")
def update_target(
    target_id: int,
    payload: TargetUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.Target, target_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "target_type": row.target_type,
        "actual_value": row.actual_value,
    }


# ---------- incentive rules ----------


@router.post("/incentive-rules", status_code=201)
def create_incentive_rule(
    payload: IncentiveRuleCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.IncentiveRule)
        .filter(
            ent.IncentiveRule.tenant_id == tenant_id,
            ent.IncentiveRule.code == payload.code,
            ent.IncentiveRule.version == payload.version,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            409, "Incentive rule with this code and version already exists"
        )
    row = ent.IncentiveRule(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


@router.get("/incentive-rules")
def list_incentive_rules(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.IncentiveRule).filter(ent.IncentiveRule.tenant_id == tenant_id)
    if active_only:
        q = q.filter(ent.IncentiveRule.is_active.is_(True))
    return [
        {
            "id": r.id,
            "code": r.code,
            "name_ar": r.name_ar,
            "name_en": r.name_en,
            "rule_type": r.rule_type,
            "priority": r.priority,
            "precedence_policy": r.precedence_policy,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.IncentiveRule.priority.desc()).all()
    ]


@router.patch("/incentive-rules/{rule_id}")
def update_incentive_rule(
    rule_id: int,
    payload: IncentiveRuleUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.IncentiveRule, rule_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


# ---------- payroll input records ----------


@router.post("/payroll-inputs", status_code=201)
def create_payroll_input(
    payload: PayrollInputCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(db, ent.Courier, payload.courier_id, tenant_id)
    if payload.input_type not in ("EARNING", "DEDUCTION"):
        raise HTTPException(400, "input_type must be EARNING or DEDUCTION")
    # C1 FIX: Validate source_id belongs to tenant based on source_type
    if payload.source_id is not None:
        if payload.source_type == "ATTENDANCE":
            attendance = (
                db.query(ent.Attendance)
                .filter(
                    ent.Attendance.id == payload.source_id,
                    ent.Attendance.courier_id == payload.courier_id,
                )
                .first()
            )
            if not attendance:
                raise HTTPException(404, "Attendance not found for this courier")
        elif payload.source_type == "LEAVE":
            leave_req = (
                db.query(ent.LeaveRequest)
                .filter(
                    ent.LeaveRequest.id == payload.source_id,
                    ent.LeaveRequest.tenant_id == tenant_id,
                )
                .first()
            )
            if not leave_req:
                raise HTTPException(404, "Leave request not found")
        elif payload.source_type == "DELIVERY_FACT":
            fact = (
                db.query(ent.NormalizedDeliveryFact)
                .filter(
                    ent.NormalizedDeliveryFact.id == payload.source_id,
                    ent.NormalizedDeliveryFact.tenant_id == tenant_id,
                )
                .first()
            )
            if not fact:
                raise HTTPException(404, "Delivery fact not found")
        elif payload.source_type == "RULE":
            _same_tenant(db, ent.IncentiveRule, payload.source_id, tenant_id)
        elif payload.source_type == "MANUAL":
            pass  # No source to validate
    if payload.source_id is not None:
        existing = (
            db.query(ent.PayrollInputRecord)
            .filter(
                ent.PayrollInputRecord.tenant_id == tenant_id,
                ent.PayrollInputRecord.courier_id == payload.courier_id,
                ent.PayrollInputRecord.month == payload.month,
                ent.PayrollInputRecord.source_type == payload.source_type,
                ent.PayrollInputRecord.source_id == payload.source_id,
            )
            .first()
        )
    else:
        # M6 FIX: For MANUAL inputs without source_id, use idempotency on amount + description
        existing = (
            db.query(ent.PayrollInputRecord)
            .filter(
                ent.PayrollInputRecord.tenant_id == tenant_id,
                ent.PayrollInputRecord.courier_id == payload.courier_id,
                ent.PayrollInputRecord.month == payload.month,
                ent.PayrollInputRecord.source_type == payload.source_type,
                ent.PayrollInputRecord.source_id.is_(None),
                ent.PayrollInputRecord.amount == payload.amount,
                ent.PayrollInputRecord.description == payload.description,
            )
            .first()
        )
    if existing:
        raise HTTPException(409, "Payroll input record already exists")
    row = ent.PayrollInputRecord(
        tenant_id=tenant_id,
        courier_id=payload.courier_id,
        month=payload.month,
        source_type=payload.source_type,
        source_id=payload.source_id,
        input_type=payload.input_type,
        amount=payload.amount,
        description=payload.description,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "courier_id": row.courier_id,
        "month": row.month,
        "input_type": row.input_type,
        "amount": row.amount,
    }


@router.get("/payroll-inputs")
def list_payroll_inputs(
    courier_id: Optional[int] = Query(None),
    month: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.PayrollInputRecord).filter(
        ent.PayrollInputRecord.tenant_id == tenant_id
    )
    if courier_id:
        q = q.filter(ent.PayrollInputRecord.courier_id == courier_id)
    if month:
        q = q.filter(ent.PayrollInputRecord.month == month)
    return [
        {
            "id": r.id,
            "courier_id": r.courier_id,
            "month": r.month,
            "source_type": r.source_type,
            "input_type": r.input_type,
            "amount": r.amount,
            "status": r.status,
            "description": r.description,
        }
        for r in q.order_by(ent.PayrollInputRecord.created_at.desc()).all()
    ]


@router.post("/payroll-inputs/{input_id}/reverse", status_code=201)
def reverse_payroll_input(
    input_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    """Reverse a payroll input by creating a reversing entry."""
    tenant_id = _tenant_id(user, manage=True)
    original = _same_tenant(db, ent.PayrollInputRecord, input_id, tenant_id)
    if original.status == "VOID":
        raise HTTPException(409, "Input already reversed")
    # C2 FIX: Reject reversing a reversal
    if original.reversal_of_id is not None:
        raise HTTPException(409, "Cannot reverse a reversal")
    # Create reversing entry
    reversal_input_type = "DEDUCTION" if original.input_type == "EARNING" else "EARNING"
    reversal = ent.PayrollInputRecord(
        tenant_id=tenant_id,
        courier_id=original.courier_id,
        month=original.month,
        source_type="REVERSAL",
        source_id=original.id,
        input_type=reversal_input_type,
        amount=original.amount,
        description=f"Reversal of input #{original.id}",
        reversal_of_id=original.id,
        created_by=user.id,
    )
    original.status = "VOID"
    db.add(reversal)
    db.commit()
    db.refresh(reversal)
    return {
        "id": reversal.id,
        "reversal_of_id": reversal.reversal_of_id,
        "status": "APPROVED",
    }


# ---------- dashboards ----------


@router.post("/dashboards", status_code=201)
def create_dashboard(
    payload: DashboardCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    existing = (
        db.query(ent.DashboardDefinition)
        .filter(
            ent.DashboardDefinition.tenant_id == tenant_id,
            ent.DashboardDefinition.code == payload.code,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Dashboard with this code already exists")
    row = ent.DashboardDefinition(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


@router.get("/dashboards")
def list_dashboards(
    active_only: bool = Query(True),
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user)
    q = db.query(ent.DashboardDefinition).filter(
        ent.DashboardDefinition.tenant_id == tenant_id
    )
    if active_only:
        q = q.filter(ent.DashboardDefinition.is_active.is_(True))
    return [
        {
            "id": r.id,
            "code": r.code,
            "name_ar": r.name_ar,
            "name_en": r.name_en,
            "category": r.category,
            "is_active": r.is_active,
        }
        for r in q.order_by(ent.DashboardDefinition.code).all()
    ]


@router.patch("/dashboards/{dashboard_id}")
def update_dashboard(
    dashboard_id: int,
    payload: DashboardUpdate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    row = _same_tenant(db, ent.DashboardDefinition, dashboard_id, tenant_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name_ar": row.name_ar}


# ---------- dashboard widgets ----------


@router.post("/dashboard-widgets", status_code=201)
def create_dashboard_widget(
    payload: DashboardWidgetCreate,
    user: ent.User = Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = _tenant_id(user, manage=True)
    _same_tenant(
        db, ent.DashboardDefinition, payload.dashboard_definition_id, tenant_id
    )
    if payload.kpi_definition_id:
        _same_tenant(db, ent.KPIDefinition, payload.kpi_definition_id, tenant_id)
    row = ent.DashboardWidget(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "dashboard_definition_id": row.dashboard_definition_id,
        "title_ar": row.title_ar,
    }


@router.get("/dashboard-widgets/{dashboard_id}")
def list_dashboard_widgets(
    dashboard_id: int, user: ent.User = Depends(get_current_user), db=Depends(get_db)
):
    tenant_id = _tenant_id(user)
    _same_tenant(db, ent.DashboardDefinition, dashboard_id, tenant_id)
    q = db.query(ent.DashboardWidget).filter(
        ent.DashboardWidget.tenant_id == tenant_id,
        ent.DashboardWidget.dashboard_definition_id == dashboard_id,
    )
    return [
        {
            "id": r.id,
            "kpi_definition_id": r.kpi_definition_id,
            "widget_type": r.widget_type,
            "title_ar": r.title_ar,
            "position": r.position,
        }
        for r in q.order_by(ent.DashboardWidget.position).all()
    ]
