"""نظام الاشتراكات والفوترة للشركات.

- كل Tenant له: خطة + رسوم شهرية + يوم فوترة + تاريخ استحقاق + حالة.
- عند تجاوز الاستحقاق تتحول الحالة إلى OVERDUE ثم بعد فترة سماح إلى SUSPENDED.
- SUSPENDED تمنع الوصول لكل نقاط Fleet (تعطيل تلقائي).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import Tenant, User, UserRole
from .auth import get_current_user

router = APIRouter(prefix="/billing", tags=["billing"])

GRACE_DAYS = 7  # أيام السماح بعد الاستحقاق قبل التعطيل
MONTH_DAYS = 30  # طول الفترة الشهرية
TRIAL_DAYS = 14  # أيام التجربة المجانية عند إضافة شركة جديدة


class SubscriptionPayload(BaseModel):
    plan: str = "PRO"  # TRIAL / PRO / ENTERPRISE
    monthly_fee: float = 0
    billing_day: int = 1
    set_active: bool = True  # تفعيل فوري (تسجيل دفعة)
    months: int = 1  # مدة الفترة عند التفعيل


def _tenant_for(user: User, db: Session) -> Tenant:
    if user.role in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        return None
    if not user.tenant_id:
        raise HTTPException(403, "حسابك غير مرتبط بشركة")
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(404, "الشركة غير موجودة")
    return tenant


def check_active(user: User, db: Session):
    """ترفع HTTPException إذا كانت الشركة معطّلة — تُستدعى من نقاط Fleet."""
    if user.role in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        return
    tenant = _tenant_for(user, db)
    _refresh_status(tenant, db)
    if tenant.subscription_status == "SUSPENDED":
        raise HTTPException(403, "تم تعطيل حسابك لعدم سداد الاشتراك — تواصل مع DOU")


def _refresh_status(tenant: Tenant, db: Session):
    """يراجع الاستحقاق: ACTIVE→OVERDUE بعد الموعد، ثم SUSPENDED بعد فترة السماح."""
    now = datetime.utcnow()
    if tenant.subscription_status == "SUSPENDED":
        return
    if not tenant.due_date:
        return
    past_due = now > tenant.due_date
    past_grace = now > tenant.due_date + timedelta(days=GRACE_DAYS)
    if past_grace:
        tenant.subscription_status = "SUSPENDED"
        db.commit()
    elif past_due:
        tenant.subscription_status = "OVERDUE"
        db.commit()


# What the company owes DOU is a commercial matter between the account owner
# and DOU. A rider, a supervisor or a dispatcher has no business in it, and a
# courier could read the invoice — amount, due date, subscription state — from
# any authenticated session.
BILLING_READER_ROLES = (
    UserRole.COMPANY,
    UserRole.COMPANY_ADMIN,
    UserRole.ACCOUNTANT,
    UserRole.DOU_ADMIN,
    UserRole.DOU_OPS,
)


def _require_billing_reader(user: User) -> None:
    if user.role not in BILLING_READER_ROLES:
        raise HTTPException(
            403,
            "بيانات الاشتراك والفواتير تُفتح بحساب مدير الشركة أو المحاسب.",
        )


@router.get("/status")
def billing_status(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """حالة اشتراك الشركة الحالية."""
    _require_billing_reader(user)
    tenant = _tenant_for(user, db)
    _refresh_status(tenant, db)
    now = datetime.utcnow()
    due = tenant.due_date
    days_left = (due - now).days if due else None
    return {
        "plan": tenant.plan,
        "monthly_fee": tenant.monthly_fee,
        "status": tenant.subscription_status,
        "due_date": due.isoformat() if due else None,
        "days_left": days_left,
        "billing_day": tenant.billing_day,
    }


@router.get("/invoice")
def billing_invoice(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """فاتورة الشركة الحالية: الفترة، المبلغ، الحالة."""
    _require_billing_reader(user)
    tenant = _tenant_for(user, db)
    _refresh_status(tenant, db)
    now = datetime.utcnow()
    due = tenant.due_date or (now + timedelta(days=TRIAL_DAYS))
    period_start = due - timedelta(days=MONTH_DAYS)
    return {
        "invoice_no": f"DOU-{tenant.id:04d}-{due.strftime('%Y%m')}",
        "tenant": tenant.name,
        "period": {
            "from": period_start.date().isoformat(),
            "to": due.date().isoformat(),
        },
        "amount": tenant.monthly_fee,
        "status": tenant.subscription_status,
        "due_date": due.date().isoformat(),
        "days_left": (due - now).days,
    }


@router.post("/subscribe")
def billing_subscribe(
    payload: SubscriptionPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تسجيل شركة في اشتراك (يستخدمها فريق DOU عند إضافة عميل)."""
    if user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        raise HTTPException(403, "فريق DOU فقط")
    tenant = _tenant_for(user, db) if user.tenant_id else None
    if not tenant:
        # بدون tenant مرتبط: تطبيق على الشركة التي حددها OPS
        raise HTTPException(400, "حدد الشركة عبر /admin")
    now = datetime.utcnow()
    if payload.set_active:
        tenant.plan = payload.plan
        tenant.monthly_fee = payload.monthly_fee
        tenant.billing_day = payload.billing_day
        tenant.last_paid_at = now
        tenant.due_date = now + timedelta(days=MONTH_DAYS * payload.months)
        tenant.subscription_status = "ACTIVE"
    else:
        tenant.plan = payload.plan
        tenant.monthly_fee = payload.monthly_fee
    db.commit()
    return {
        "ok": True,
        "status": tenant.subscription_status,
        "due_date": tenant.due_date.isoformat(),
    }


@router.post("/pay")
def billing_pay(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """لا يجوز للعميل اعتماد دفعته بنفسه؛ التسجيل يتم من إدارة DOU مع إيصال ومراجعة."""
    raise HTTPException(403, "سداد وتجديد الاشتراك يُسجلان من إدارة DOU بعد تأكيد الدفع")


@router.get("/admin/tenants")
def billing_admin_tenants(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """قائمة الشركات مع حالة اشتراكها — لفريق DOU."""
    if user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        raise HTTPException(403, "فريق DOU فقط")
    rows = []
    for t in db.query(Tenant).order_by(Tenant.id).all():
        _refresh_status(t, db)
        rows.append(
            {
                "id": t.id,
                "name": t.name,
                "country": t.country.value,
                "plan": t.plan,
                "monthly_fee": t.monthly_fee,
                "status": t.subscription_status,
                "due_date": t.due_date.isoformat() if t.due_date else None,
            }
        )
    return rows


@router.post("/admin/tenants/{tid}/subscribe")
def billing_admin_subscribe(
    tid: int,
    payload: SubscriptionPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """إدارة اشتراك شركة محددة — لفريق DOU."""
    if user.role not in (UserRole.DOU_OPS, UserRole.DOU_ADMIN):
        raise HTTPException(403, "فريق DOU فقط")
    tenant = db.get(Tenant, tid)
    if not tenant:
        raise HTTPException(404, "الشركة غير موجودة")
    now = datetime.utcnow()
    if payload.set_active:
        tenant.plan = payload.plan
        tenant.monthly_fee = payload.monthly_fee
        tenant.billing_day = payload.billing_day
        tenant.last_paid_at = now
        tenant.due_date = now + timedelta(days=MONTH_DAYS * payload.months)
        tenant.subscription_status = "ACTIVE"
    else:
        tenant.plan = payload.plan
        tenant.monthly_fee = payload.monthly_fee
    db.commit()
    return {
        "ok": True,
        "tenant": tenant.name,
        "status": tenant.subscription_status,
        "due_date": tenant.due_date.isoformat() if tenant.due_date else None,
    }
