"""Shared rider creation and branch-assignment validation.

Company routes and bulk imports call this service so relational validation cannot
weaken when an operation is applied to many riders.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models.entities import (
    Country,
    Courier,
    CourierType,
    Fleet,
    SubscriptionPlan,
    Tenant,
    User,
    UserRole,
)
from ..routers.auth import hash_password
from .operating_structure import require_branch_assignment


def canonical_phone(value: Any) -> str:
    phone = str(value or "").strip().replace(" ", "")
    if not phone:
        raise ValueError("رقم الجوال مطلوب")
    return phone if phone.startswith("966") else "966" + phone.lstrip("0")


def enforce_courier_plan_cap(db: Session, tenant_id: int) -> None:
    """Raise if the tenant's subscription plan caps couriers and is already at the limit."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        return
    plan = (
        db.query(SubscriptionPlan)
        .filter(SubscriptionPlan.code == tenant.plan)
        .first()
    )
    if (
        plan
        and plan.max_couriers
        and db.query(Courier).filter(Courier.tenant_id == tenant_id).count()
        >= plan.max_couriers
    ):
        raise ValueError("تم الوصول للحد الأقصى من المندوبين في الباقة")


def create_rider_record(
    db: Session,
    user: User,
    payload: dict,
    enforce_plan: bool = True,
    tenant_id: Optional[int] = None,
) -> tuple[Courier, User]:
    """Create a courier and its login without committing the surrounding transaction.

    A fleet user creates riders inside their own tenant, so tenant_id comes from
    the caller's account. A DOU admin has no tenant of their own and names the
    fleet explicitly — that is what tenant_id overrides, and it is the only
    difference between the two callers. Everything else (the login, the phone
    uniqueness check, the plan cap) stays identical, because a rider created by
    DOU support and a rider created by the fleet are the same rider.
    """
    tenant_id = tenant_id if tenant_id is not None else user.tenant_id
    if not tenant_id:
        raise ValueError("حساب الشركة غير مرتبط بكيان تشغيلي")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم المندوب مطلوب")
    phone = canonical_phone(payload.get("phone"))
    if db.query(Courier).filter(Courier.phone == phone).first():
        raise ValueError("رقم جوال المندوب مستخدم بالفعل")
    if (
        db.query(User)
        .filter(User.phone == phone, User.role == UserRole.COURIER)
        .first()
    ):
        raise ValueError("حساب المندوب مستخدم بالفعل")
    password = str(payload.get("password") or "")
    if len(password) < 8:
        raise ValueError("كلمة مرور المندوب يجب أن تكون 8 أحرف على الأقل")
    try:
        country = Country(payload.get("country") or "SA")
        courier_type = CourierType(payload.get("courier_type") or "COMPANY")
        base_salary = float(payload.get("base_salary") or 0)
        per_delivery_rate = float(payload.get("per_delivery_rate") or 0)
        bonus_target = float(payload.get("bonus_target") or 0)
    except (TypeError, ValueError):
        raise ValueError("قيم المندوب الرقمية أو نوعه غير صالحة")
    if enforce_plan:
        enforce_courier_plan_cap(db, tenant_id)
    contract, branch, city, project, supervisor = require_branch_assignment(
        db,
        tenant_id,
        payload.get("contract_id"),
        payload.get("contract_branch_id"),
        supervisor_id=payload.get("supervisor_id"),
        city_id=payload.get("city_id"),
    )
    fleet = db.query(Fleet).filter(Fleet.tenant_id == tenant_id).first()
    courier = Courier(
        tenant_id=tenant_id,
        fleet_id=fleet.id if fleet else None,
        name=name,
        phone=phone,
        courier_type=courier_type,
        country=country,
        lat=payload.get("lat"),
        lng=payload.get("lng"),
        base_salary=base_salary,
        per_delivery_rate=per_delivery_rate,
        bonus_target=bonus_target,
        bank_iban=payload.get("bank_iban"),
        nationality=(payload.get("nationality") or None),
        iqama_number=(payload.get("iqama_number") or None),
        emergency_name=(payload.get("emergency_name") or None),
        emergency_phone=(payload.get("emergency_phone") or None),
        vehicle_type=(payload.get("vehicle_type") or None),
        vehicle_plate=(payload.get("vehicle_plate") or None),
        photo_url=(payload.get("photo_url") or None),
        employment_status=payload.get("employment_status") or "ACTIVE",
        employment_model=payload.get("employment_model") or "DIRECT_HIRE",
        operator_tenant_id=payload.get("operator_tenant_id"),
        supervisor_id=supervisor.id,
        primary_project_id=project.id,
        contract_id=contract.id,
        contract_branch_id=branch.id,
        city_id=city.id,
        work_city=branch.city or city.name,
        platform=project.name,
        platform_courier_id=str(payload.get("platform_courier_id")).strip()
        if payload.get("platform_courier_id")
        else None,
    )
    db.add(courier)
    db.flush()
    account = User(
        phone=phone,
        name=name,
        password_hash=hash_password(password),
        role=UserRole.COURIER,
        courier_id=courier.id,
        tenant_id=tenant_id,
        country=country,
        is_active=courier.employment_status == "ACTIVE",
    )
    db.add(account)
    db.flush()
    return courier, account


def apply_branch_assignment(db: Session, courier: Courier, payload: dict) -> dict:
    """Apply one validated branch assignment; returns values for audit logging."""
    contract, branch, city, project, supervisor = require_branch_assignment(
        db,
        courier.tenant_id,
        payload.get("contract_id") or courier.contract_id,
        payload.get("contract_branch_id"),
        supervisor_id=payload.get("supervisor_id"),
        city_id=payload.get("city_id"),
    )
    old = {
        "contract_branch_id": courier.contract_branch_id,
        "supervisor_id": courier.supervisor_id,
        "project_id": courier.primary_project_id,
    }
    courier.contract_id = contract.id
    courier.contract_branch_id = branch.id
    courier.city_id = city.id
    courier.work_city = branch.city or city.name
    courier.supervisor_id = supervisor.id
    courier.primary_project_id = project.id
    courier.platform = project.name
    return old
