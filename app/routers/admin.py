from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import ADMIN_KEY, ENABLE_LEGACY_DELIVERY, ENABLE_PUBLIC_COMPANY_SIGNUP
from sqlalchemy import text
from ..models.entities import Channel, Courier, Merchant, Staff, CourierType, Country, User, UserRole, Tenant, Fleet, SubscriptionPlan, SubscriptionPayment, AdminAuditLog
from .auth import get_current_user, hash_password, SECRET_KEY, ALGORITHM
from jose import jwt as pyjwt, JWTError
from datetime import datetime, timedelta
from calendar import monthrange

MARKETS = {
    "SA": ("ar", "SAR", "Asia/Riyadh"), "AE": ("en", "AED", "Asia/Dubai"),
    "EG": ("ar", "EGP", "Africa/Cairo"), "KW": ("ar", "KWD", "Asia/Kuwait"),
    "QA": ("ar", "QAR", "Asia/Qatar"), "BH": ("ar", "BHD", "Asia/Bahrain"),
    "OM": ("ar", "OMR", "Asia/Muscat"), "GB": ("en", "GBP", "Europe/London"),
    "US": ("en", "USD", "America/New_York"), "CA": ("en", "CAD", "America/Toronto"),
    "AU": ("en", "AUD", "Australia/Sydney"), "OTHER": ("en", "USD", "UTC"),
}

def regional_settings(payload: dict):
    market = (payload.get("market_code") or payload.get("country") or "SA").upper()
    if market not in MARKETS: market = "OTHER"
    lang, currency, timezone = MARKETS[market]
    lang = payload.get("default_language") if payload.get("default_language") in ("ar", "en") else lang
    currency = (payload.get("currency") or currency).upper()[:3]
    timezone = (payload.get("timezone") or timezone).strip()
    return market, lang, currency, timezone


def add_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))


def overdue_months(due_date: Optional[datetime], now: datetime) -> int:
    """عدد دورات الفوترة المتأخرة بالتقويم، وليس قسمة تقريبية على 30 يومًا."""
    if not due_date or due_date >= now:
        return 0
    months = 0
    cursor = due_date
    while cursor < now and months < 120:
        months += 1
        cursor = add_calendar_months(cursor, 1)
    return months


async def require_admin(x_admin_key: str = Header(default="", alias="X-Admin-Key"),
                        authorization: str = Header(default=""),
                        db: Session = Depends(get_db)):
    """بوابة لوحة التحكم: تقبل المفتاح الإداري (X-Admin-Key) أو توكن JWT لدور أدمن."""
    if ADMIN_KEY and x_admin_key and x_admin_key == ADMIN_KEY:
        return db.query(User).filter(User.role == UserRole.DOU_ADMIN, User.is_active == True).first()
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except JWTError:
            raise HTTPException(401, "Access denied")
        if payload.get("role") not in ("DOU_ADMIN", "DOU_OPS"):
            raise HTTPException(403, "Not an admin account")
        user = db.get(User, int(payload["sub"]))
        if not user or not user.is_active:
            raise HTTPException(401, "Access denied")
        if int(payload.get("ver", 0)) != (user.token_version or 0):
            raise HTTPException(401, "Access denied")
        return user
    raise HTTPException(401, "Access denied")


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

gate_router = APIRouter(prefix="/admin", tags=["admin"])


class NameOnly(BaseModel):
    name: str


class GateIn(BaseModel):
    username: str
    password: str


@gate_router.post("/gate")
def admin_gate(payload: GateIn):
    # أُلغيت البوابة القديمة لأنها كانت تعيد مفتاح الإدارة السري للمتصفح.
    raise HTTPException(410, "Use secure admin account login")


@gate_router.get("/public-plans")
def public_plans(currency: str = "SAR", db: Session = Depends(get_db)):
    """الباقات النشطة المعروضة في صفحة المبيعات، بدون أي بيانات إدارية حساسة."""
    return [
        {
            "code": plan.code,
            "name": plan.name,
            "name_en": plan.name_en or plan.name,
            "monthly_price": plan.monthly_price,
            "monthly_price_usd": plan.monthly_price_usd or 0,
            "max_couriers": plan.max_couriers,
            "features_ar": plan.features_ar or "",
            "features_en": plan.features_en or "",
        }
        for plan in db.query(SubscriptionPlan)
        .filter(SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.monthly_price)
        .all()
    ]


# ---------- Merchants ----------
class MerchantIn(BaseModel):
    name: str
    country: str = "SA"
    delivery_method: str = "PLATFORM"
    city: Optional[str] = None
    district: Optional[str] = None
    category: Optional[str] = None


class MerchantPatch(BaseModel):
    active: Optional[bool] = None
    delivery_method: Optional[str] = None
    category: Optional[str] = None


@router.get("/merchants")
def list_merchants(db: Session = Depends(get_db)):
    rows = []
    for m in db.query(Merchant).all():
        rows.append({
            "id": m.id, "name": m.name, "country": m.country.value if hasattr(m.country, "value") else m.country,
            "city": m.city, "district": m.district, "category": m.category or "",
            "delivery_method": m.delivery_method.value if hasattr(m.delivery_method, "value") else m.delivery_method,
            "is_active": True, "theme": m.theme, "slug": m.slug,
        })
    return rows


@router.post("/merchants")
def add_merchant(payload: MerchantIn, db: Session = Depends(get_db)):
    m = Merchant(
        name=payload.name,
        country=Country(payload.country) if payload.country in ("SA", "EG") else Country.SA,
        city=payload.city or "", district=payload.district or "",
        slug=f"store-{abs(hash(payload.name)) % 99999}", category=payload.category or "",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"id": m.id, "name": m.name, "country": m.country.value, "city": m.city,
            "district": m.district, "category": m.category, "is_active": True}


@router.patch("/merchants/{mid}")
def patch_merchant(mid: int, payload: MerchantPatch, db: Session = Depends(get_db)):
    m = db.get(Merchant, mid)
    if not m:
        raise HTTPException(404, "Merchant not found")
    if payload.active is not None:
        m.is_active = payload.active
    if payload.delivery_method:
        m.delivery_method = payload.delivery_method
    if payload.category:
        m.category = payload.category
    db.commit()
    return {"ok": True, "id": m.id, "is_active": m.is_active}


@router.delete("/merchants/{mid}")
def delete_merchant(mid: int, db: Session = Depends(get_db)):
    m = db.get(Merchant, mid)
    if not m:
        raise HTTPException(404, "Merchant not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ---------- Channels ----------
class ChannelIn(BaseModel):
    name: str
    icon: str = "🔌"
    type: str = "PARTNER"
    commission: float = 0.0


class ChannelPatch(BaseModel):
    active: Optional[bool] = None
    commission: Optional[float] = None


@router.get("/channels")
def list_channels(db: Session = Depends(get_db)):
    return [
        {"id": c.id, "name": c.name, "icon": c.icon, "type": c.type,
         "commission": c.commission, "is_active": c.is_active, "orders_share": c.orders_share}
        for c in db.query(Channel).all()
    ]


@router.post("/channels")
def add_channel(payload: ChannelIn, db: Session = Depends(get_db)):
    c = Channel(name=payload.name, icon=payload.icon, type=payload.type, commission=payload.commission)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "icon": c.icon, "type": c.type,
            "commission": c.commission, "is_active": True, "orders_share": 0}


@router.patch("/channels/{cid}")
def patch_channel(cid: int, payload: ChannelPatch, db: Session = Depends(get_db)):
    c = db.get(Channel, cid)
    if not c:
        raise HTTPException(404, "Channel not found")
    if payload.active is not None:
        c.is_active = payload.active
        c.status = "active" if payload.active else "inactive"
    if payload.commission is not None:
        c.commission = payload.commission
    db.commit()
    return {"id": c.id, "is_active": c.is_active, "commission": c.commission}


@router.delete("/channels/{cid}")
def delete_channel(cid: int, db: Session = Depends(get_db)):
    c = db.get(Channel, cid)
    if not c:
        raise HTTPException(404, "Channel not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------- Companies ----------
class CompanyIn(BaseModel):
    name: str
    code: str
    country: str = "SA"


class CompanyPatch(BaseModel):
    active: Optional[bool] = None


@router.get("/tenants")
def list_tenants(db: Session = Depends(get_db)):
    """الشركات المشتركة في DOU مع أعداد السائقين والمستخدمين."""
    rows = []
    for tenant in db.query(Tenant).order_by(Tenant.id.desc()).all():
        last_login = db.query(User).filter(User.tenant_id == tenant.id).order_by(User.last_login_at.desc()).first()
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == tenant.plan).first()
        now = datetime.utcnow()
        month_start = datetime(now.year, now.month, 1)
        next_month = add_calendar_months(month_start, 1)
        month_payments = db.query(SubscriptionPayment).filter(
            SubscriptionPayment.tenant_id == tenant.id,
            SubscriptionPayment.paid_at >= month_start,
            SubscriptionPayment.paid_at < next_month,
        ).all()
        late_months = overdue_months(tenant.due_date, now)
        rows.append({
            "id": tenant.id, "name": tenant.name,
            "country": tenant.country.value if hasattr(tenant.country, "value") else tenant.country,
            "market_code": tenant.market_code or (tenant.country.value if hasattr(tenant.country, "value") else tenant.country),
            "default_language": tenant.default_language or "ar", "currency": tenant.currency or "SAR",
            "timezone": tenant.timezone or "Asia/Riyadh",
            "plan": tenant.plan or "TRIAL", "monthly_fee": tenant.monthly_fee or 0,
            "subscription_status": tenant.subscription_status or "ACTIVE",
            "due_date": tenant.due_date.isoformat() if tenant.due_date else None,
            "couriers_count": db.query(Courier).filter(Courier.tenant_id == tenant.id).count(),
            "users_count": db.query(User).filter(User.tenant_id == tenant.id, User.role != UserRole.COURIER).count(),
            "max_couriers": plan.max_couriers if plan else 0,
            "last_login_at": last_login.last_login_at.isoformat() if last_login and last_login.last_login_at else None,
            "last_activity_at": tenant.last_activity_at.isoformat() if tenant.last_activity_at else None,
            "paid_this_month": bool(month_payments),
            "paid_this_month_amount": round(sum(p.amount or 0 for p in month_payments), 2),
            "months_overdue": late_months,
            "outstanding_amount": round(late_months * (tenant.monthly_fee or 0), 2),
            "last_paid_at": tenant.last_paid_at.isoformat() if tenant.last_paid_at else None,
        })
    return rows


@router.get("/finance/summary")
def finance_summary(month: Optional[str] = None, db: Session = Depends(get_db)):
    """دفتر متابعة تحصيل الاشتراكات: الإيراد الفعلي، المتوقع، والمتأخرات حسب العملة."""
    now = datetime.utcnow()
    try:
        month_start = datetime.strptime(month, "%Y-%m") if month else datetime(now.year, now.month, 1)
    except ValueError:
        raise HTTPException(400, "صيغة الشهر يجب أن تكون YYYY-MM")
    next_month = add_calendar_months(month_start, 1)
    tenants = db.query(Tenant).order_by(Tenant.name).all()
    payments = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.paid_at >= month_start,
        SubscriptionPayment.paid_at < next_month,
    ).order_by(SubscriptionPayment.paid_at.desc()).all()
    payments_by_tenant = {}
    for payment in payments:
        payments_by_tenant.setdefault(payment.tenant_id, []).append(payment)

    actual_by_currency, expected_by_currency, outstanding_by_currency = {}, {}, {}
    rows = []
    for tenant in tenants:
        currency = tenant.currency or "SAR"
        tenant_payments = payments_by_tenant.get(tenant.id, [])
        paid_amount = round(sum(p.amount or 0 for p in tenant_payments), 2)
        late_months = overdue_months(tenant.due_date, now)
        outstanding = round(late_months * (tenant.monthly_fee or 0), 2)
        expected_by_currency[currency] = round(expected_by_currency.get(currency, 0) + (tenant.monthly_fee or 0), 2)
        actual_by_currency[currency] = round(actual_by_currency.get(currency, 0) + paid_amount, 2)
        outstanding_by_currency[currency] = round(outstanding_by_currency.get(currency, 0) + outstanding, 2)
        if late_months:
            collection_status = "OVERDUE"
        elif tenant_payments:
            collection_status = "PAID_THIS_MONTH"
        elif tenant.due_date:
            collection_status = "COVERED"
        else:
            collection_status = "UNCONFIGURED"
        rows.append({
            "tenant_id": tenant.id, "company": tenant.name, "plan": tenant.plan,
            "currency": currency, "monthly_fee": tenant.monthly_fee or 0,
            "paid_this_month": bool(tenant_payments), "paid_amount": paid_amount,
            "receipts_count": len(tenant_payments),
            "last_receipt": tenant_payments[0].receipt_number if tenant_payments else None,
            "last_paid_at": tenant.last_paid_at.isoformat() if tenant.last_paid_at else None,
            "due_date": tenant.due_date.isoformat() if tenant.due_date else None,
            "months_overdue": late_months, "outstanding_amount": outstanding,
            "subscription_status": tenant.subscription_status or "ACTIVE",
            "collection_status": collection_status,
        })
    recent = [{
        "receipt_number": p.receipt_number, "tenant_id": p.tenant_id,
        "company": next((t.name for t in tenants if t.id == p.tenant_id), "—"),
        "amount": p.amount, "currency": p.currency or "SAR",
        "payment_method": p.payment_method, "paid_at": p.paid_at.isoformat(),
        "period_months": p.period_months, "recorded_by": p.recorded_by_name,
    } for p in payments[:20]]
    return {
        "month": month_start.strftime("%Y-%m"), "actual_revenue": actual_by_currency,
        "expected_revenue": expected_by_currency, "outstanding": outstanding_by_currency,
        "companies": len(rows), "paid_companies": sum(r["paid_this_month"] for r in rows),
        "unpaid_this_month": sum(not r["paid_this_month"] for r in rows),
        "overdue_companies": sum(r["months_overdue"] > 0 for r in rows),
        "rows": rows, "recent_payments": recent,
    }


@router.get("/system-status")
def system_status(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False
    return {
        "api": "ONLINE", "database": "ONLINE" if database_ok else "ERROR",
        "public_company_signup": ENABLE_PUBLIC_COMPANY_SIGNUP,
        "legacy_delivery_modules": ENABLE_LEGACY_DELIVERY,
        "subscription_payments": "ADMIN_RECORDED",
        "backup_status": "MANAGED_EXTERNALLY",
    }


@router.patch("/tenants/{tid}")
def patch_tenant(tid: int, payload: dict, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    tenant = db.get(Tenant, tid)
    if not tenant:
        raise HTTPException(404, "Company not found")
    if payload.get("subscription_status") in ("ACTIVE", "OVERDUE", "SUSPENDED"):
        tenant.subscription_status = payload["subscription_status"]
    if payload.get("plan"):
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == str(payload["plan"]).upper(), SubscriptionPlan.is_active.is_(True)).first()
        if not plan: raise HTTPException(400,"الباقة غير موجودة أو غير نشطة")
        tenant.plan = plan.code
        tenant.monthly_fee = plan.monthly_price_usd if (tenant.currency or "SAR")=="USD" and plan.monthly_price_usd else plan.monthly_price
    for key in ("name","contact_email","contact_phone"):
        if key in payload:setattr(tenant,key,(payload.get(key) or "").strip())
    if "monthly_fee" in payload:tenant.monthly_fee=float(payload.get("monthly_fee") or 0)
    if any(k in payload for k in ("market_code","default_language","currency","timezone")):
        tenant.market_code,tenant.default_language,tenant.currency,tenant.timezone=regional_settings(payload)
    if "billing_day" in payload:tenant.billing_day=max(1,min(28,int(payload.get("billing_day") or 1)))
    if payload.get("due_date"):
        try:tenant.due_date=datetime.fromisoformat(payload["due_date"])
        except ValueError:raise HTTPException(400,"Invalid due date")
    if payload.get("mark_paid"):
        tenant.last_paid_at=datetime.utcnow();tenant.subscription_status="ACTIVE"
        if not tenant.due_date or tenant.due_date<datetime.utcnow():tenant.due_date=datetime.utcnow()+timedelta(days=30)
    db.add(AdminAuditLog(actor_id=actor.id if actor else None, actor_name=actor.name if actor else "Admin Key",
                         action=f"تعديل اشتراك الشركة: {payload}", tenant_id=tid, entity="tenant", entity_id=tid))
    db.commit()
    return {"ok": True}


@router.get("/tenants/{tid}")
def tenant_detail(tid:int,db:Session=Depends(get_db)):
    t=db.get(Tenant,tid)
    if not t:raise HTTPException(404,"Company not found")
    users=db.query(User).filter(User.tenant_id==tid,User.role!=UserRole.COURIER).all()
    payments=db.query(SubscriptionPayment).filter(SubscriptionPayment.tenant_id==tid).order_by(SubscriptionPayment.paid_at.desc()).all()
    return {"id":t.id,"name":t.name,"country":t.country.value,"market_code":t.market_code or t.country.value,"default_language":t.default_language or "ar","currency":t.currency or "SAR","timezone":t.timezone or "Asia/Riyadh","contact_email":t.contact_email,"contact_phone":t.contact_phone,"plan":t.plan,"monthly_fee":t.monthly_fee or 0,"billing_day":t.billing_day or 1,"due_date":t.due_date.isoformat() if t.due_date else None,"last_paid_at":t.last_paid_at.isoformat() if t.last_paid_at else None,"subscription_status":t.subscription_status,"created_at":t.created_at.isoformat(),"users":[{"id":u.id,"name":u.name,"phone":u.phone,"role":u.role.value,"last_login_at":u.last_login_at.isoformat() if u.last_login_at else None,"active":u.is_active} for u in users],"couriers_count":db.query(Courier).filter(Courier.tenant_id==tid).count(),"payments":[{"id":p.id,"amount":p.amount,"currency":p.currency or t.currency or "SAR","payment_method":p.payment_method,"paid_at":p.paid_at.isoformat(),"period_months":p.period_months,"reference":p.reference,"receipt_number":p.receipt_number,"notes":p.notes,"recorded_by":p.recorded_by_name} for p in payments]}


@router.post("/tenants/{tid}/payments")
def record_subscription_payment(tid:int,payload:dict,db:Session=Depends(get_db),actor:User=Depends(require_admin)):
    tenant=db.get(Tenant,tid)
    if not tenant:raise HTTPException(404,"Company not found")
    amount=float(payload.get("amount") or 0);months=max(1,min(36,int(payload.get("period_months") or 1)))
    if amount<=0:raise HTTPException(400,"المبلغ يجب أن يكون أكبر من صفر")
    expected=round((tenant.monthly_fee or 0)*months,2)
    if expected>0 and abs(amount-expected)>0.01 and not payload.get("allow_variance"):
        raise HTTPException(400,f"المبلغ المتوقع لـ {months} شهر: {expected:.2f} {tenant.currency or 'SAR'}. فعّل اعتماد مبلغ مختلف إذا كان هناك خصم أو تسوية")
    try:paid_at=datetime.fromisoformat(payload.get("paid_at")) if payload.get("paid_at") else datetime.utcnow()
    except ValueError:raise HTTPException(400,"تاريخ الدفع غير صحيح")
    base=tenant.due_date if tenant.due_date and tenant.due_date>paid_at else paid_at
    new_due=add_calendar_months(base,months)
    receipt=f"DOU-{paid_at.strftime('%Y%m')}-{tid:04d}-{db.query(SubscriptionPayment).filter(SubscriptionPayment.tenant_id==tid).count()+1:04d}"
    payment=SubscriptionPayment(tenant_id=tid,amount=amount,currency=tenant.currency or "SAR",payment_method=(payload.get("payment_method") or "CASH").upper(),paid_at=paid_at,period_months=months,reference=(payload.get("reference") or "").strip() or None,receipt_number=receipt,notes=(payload.get("notes") or "").strip() or None,recorded_by_id=actor.id if actor else None,recorded_by_name=actor.name if actor else "Admin")
    tenant.last_paid_at=paid_at;tenant.due_date=new_due;tenant.subscription_status="ACTIVE"
    db.add(payment);db.add(AdminAuditLog(actor_id=actor.id if actor else None,actor_name=actor.name if actor else "Admin",action=f"تسجيل دفعة اشتراك {amount:.2f} ر.س ({payment.payment_method}) بإيصال {receipt}",tenant_id=tid,entity="subscription_payment"));db.commit();db.refresh(payment)
    return {"ok":True,"receipt_number":receipt,"new_due_date":new_due.isoformat(),"amount":amount,"expected_amount":expected,"variance":round(amount-expected,2),"currency":tenant.currency or "SAR"}


@router.post("/tenants")
def create_tenant(payload:dict,db:Session=Depends(get_db),actor:User=Depends(require_admin)):
    name=(payload.get("name") or "").strip();phone=(payload.get("owner_phone") or "").strip();password=str(payload.get("password") or "")
    if not name or not phone or len(password)<8:raise HTTPException(400,"اسم الشركة ورقم المالك وكلمة مرور 8 أحرف مطلوبة")
    if db.query(User).filter(User.phone==phone).first():raise HTTPException(400,"رقم المالك مستخدم")
    market,language,currency,timezone=regional_settings(payload);country=Country.EG if market=="EG" else Country.SA;plan_code=payload.get("plan") or "STARTER";plan=db.query(SubscriptionPlan).filter(SubscriptionPlan.code==plan_code).first()
    fee=(plan.monthly_price_usd if currency=="USD" and plan and plan.monthly_price_usd else plan.monthly_price if plan else float(payload.get("monthly_fee") or 0))
    t=Tenant(name=name,country=country,market_code=market,default_language=language,currency=currency,timezone=timezone,contact_phone=payload.get("contact_phone") or phone,contact_email=payload.get("contact_email"),plan=plan_code,monthly_fee=fee,billing_day=int(payload.get("billing_day") or 1),due_date=datetime.utcnow()+timedelta(days=int(payload.get("trial_days") or 14)),subscription_status="ACTIVE");db.add(t);db.flush();db.add(Fleet(tenant_id=t.id,name=f"أسطول {name}"));db.add(User(phone=phone,name=payload.get("owner_name") or f"إدارة {name}",password_hash=hash_password(password),role=UserRole.COMPANY,tenant_id=t.id,country=country,is_active=True));db.add(AdminAuditLog(actor_id=actor.id if actor else None,actor_name=actor.name if actor else "Admin",action="إنشاء شركة لوجستية وحساب المالك",tenant_id=t.id,entity="tenant",entity_id=t.id));db.commit();return {"ok":True,"id":t.id,"owner_phone":phone}


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    defaults = [("STARTER","الأساسية","Starter",499,149,10),("GROWTH","النمو","Growth",999,269,75),("BUSINESS","الأعمال","Business",1999,499,150),("ENTERPRISE","المؤسسات","Enterprise",3500,899,0)]
    if not db.query(SubscriptionPlan).count():
        db.add_all([SubscriptionPlan(code=c,name=n,name_en=e,monthly_price=p,monthly_price_usd=u,max_couriers=m) for c,n,e,p,u,m in defaults]); db.commit()
    return [{"id":p.id,"code":p.code,"name":p.name,"name_en":p.name_en or "","monthly_price":p.monthly_price,"monthly_price_usd":p.monthly_price_usd or 0,"max_couriers":p.max_couriers,"features_ar":p.features_ar or "","features_en":p.features_en or "","is_active":p.is_active} for p in db.query(SubscriptionPlan).order_by(SubscriptionPlan.monthly_price).all()]


@router.post("/plans")
def save_plan(payload: dict, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    code=(payload.get("code") or "").upper().strip(); name=(payload.get("name") or "").strip()
    if not code or not name: raise HTTPException(400,"الكود والاسم مطلوبان")
    p=db.query(SubscriptionPlan).filter(SubscriptionPlan.code==code).first() or SubscriptionPlan(code=code,name=name)
    p.name=name; p.name_en=(payload.get("name_en") or "").strip() or None; p.monthly_price=float(payload.get("monthly_price") or 0); p.monthly_price_usd=float(payload.get("monthly_price_usd") or 0); p.max_couriers=int(payload.get("max_couriers") or 0); p.features_ar=(payload.get("features_ar") or "").strip() or None; p.features_en=(payload.get("features_en") or "").strip() or None; p.is_active=payload.get("is_active",True)
    db.add(p); db.add(AdminAuditLog(actor_id=actor.id if actor else None,actor_name=actor.name if actor else "Admin",action=f"حفظ باقة {code}",entity="plan")); db.commit()
    return {"ok":True}


@router.post("/tenants/{tid}/support-login")
def support_login(tid:int, db: Session=Depends(get_db), actor: User=Depends(require_admin)):
    tenant=db.get(Tenant,tid)
    if not tenant: raise HTTPException(404,"Company not found")
    target=db.query(User).filter(User.tenant_id==tid,User.role.in_([UserRole.COMPANY,UserRole.COMPANY_ADMIN]),User.is_active==True).first()
    if not target: raise HTTPException(404,"لا يوجد حساب إدارة نشط للشركة")
    token=pyjwt.encode({"sub":str(target.id),"phone":target.phone,"role":target.role.value,"ver":target.token_version or 0,"support_by":actor.id if actor else None,"exp":datetime.utcnow()+timedelta(minutes=30)},SECRET_KEY,algorithm=ALGORITHM)
    db.add(AdminAuditLog(actor_id=actor.id if actor else None,actor_name=actor.name if actor else "Admin",action="دخول دعم آمن لمدة 30 دقيقة",tenant_id=tid,entity="support",entity_id=target.id)); db.commit()
    return {"access_token":token,"role":target.role.value,"expires_minutes":30,"company":tenant.name}


@router.get("/audit-logs")
def admin_logs(db: Session=Depends(get_db)):
    return [{"id":x.id,"actor":x.actor_name or "—","action":x.action,"tenant":db.get(Tenant,x.tenant_id).name if x.tenant_id and db.get(Tenant,x.tenant_id) else "—","created_at":x.created_at.isoformat() if x.created_at else None} for x in db.query(AdminAuditLog).order_by(AdminAuditLog.id.desc()).limit(300).all()]


@router.get("/subscription-alerts")
def subscription_alerts(db: Session=Depends(get_db)):
    now=datetime.utcnow(); rows=[]
    for t in db.query(Tenant).all():
        days=(t.due_date-now).days if t.due_date else None
        if t.subscription_status in ("OVERDUE","SUSPENDED") or (days is not None and days<=15):
            rows.append({"tenant_id":t.id,"company":t.name,"status":t.subscription_status,"days_left":days,"due_date":t.due_date.isoformat() if t.due_date else None})
    return rows


@router.get("/companies")
def list_companies(db: Session = Depends(get_db)):
    from ..models.entities import ShippingCompany
    return [
        {"id": c.id, "name": c.name, "code": c.code,
         "country": c.country.value if hasattr(c.country, "value") else c.country,
         "is_active": c.is_active}
        for c in db.query(ShippingCompany).all()
    ]


@router.post("/companies")
def add_company(payload: CompanyIn, db: Session = Depends(get_db)):
    from ..models.entities import ShippingCompany
    c = ShippingCompany(name=payload.name, code=payload.code.upper(),
                        country=Country(payload.country) if payload.country in ("SA", "EG") else Country.SA)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "code": c.code, "country": c.country.value, "is_active": True}


@router.patch("/companies/{cid}")
def patch_company(cid: int, payload: CompanyPatch, db: Session = Depends(get_db)):
    from ..models.entities import ShippingCompany
    c = db.get(ShippingCompany, cid)
    if not c:
        raise HTTPException(404, "Company not found")
    if payload.active is not None:
        c.is_active = payload.active
    db.commit()
    return {"ok": True, "id": c.id, "is_active": c.is_active}


@router.delete("/companies/{cid}")
def delete_company(cid: int, db: Session = Depends(get_db)):
    from ..models.entities import ShippingCompany
    c = db.get(ShippingCompany, cid)
    if not c:
        raise HTTPException(404, "Company not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------- Couriers ----------
class CourierIn(BaseModel):
    name: str
    phone: str
    courier_type: str = "FREELANCER"
    country: str = "SA"


class CourierPatch(BaseModel):
    active: Optional[bool] = None


@router.get("/couriers")
def list_couriers(db: Session = Depends(get_db)):
    return [
        {"id": c.id, "name": c.name, "phone": c.phone,
         "courier_type": c.courier_type.value if hasattr(c.courier_type, "value") else c.courier_type,
         "country": c.country.value if hasattr(c.country, "value") else c.country,
         "is_active": c.employment_status == "ACTIVE" and c.is_available is not False,
         "is_online": c.is_online, "score": c.score,
         "acceptance_rate": c.acceptance_rate}
        for c in db.query(Courier).all()
    ]


@router.post("/couriers")
def add_courier(payload: CourierIn, db: Session = Depends(get_db)):
    c = Courier(
        name=payload.name, phone=payload.phone,
        courier_type=CourierType(payload.courier_type) if payload.courier_type in ("COMPANY", "FREELANCER") else CourierType.FREELANCER,
        country=Country(payload.country) if payload.country in ("SA", "EG") else Country.SA,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "phone": c.phone,
            "courier_type": c.courier_type.value, "country": c.country.value, "is_active": True}


@router.patch("/couriers/{cid}")
def patch_courier(cid: int, payload: CourierPatch, db: Session = Depends(get_db)):
    c = db.get(Courier, cid)
    if not c:
        raise HTTPException(404, "Courier not found")
    if payload.active is not None:
        c.is_available = payload.active
        c.employment_status = "ACTIVE" if payload.active else "SUSPENDED"
        linked_user = db.query(User).filter(User.courier_id == c.id).first()
        if linked_user:
            linked_user.is_active = payload.active
            linked_user.token_version = (linked_user.token_version or 0) + 1
    db.commit()
    return {"ok": True, "id": c.id}


@router.delete("/couriers/{cid}")
def delete_courier(cid: int, db: Session = Depends(get_db)):
    c = db.get(Courier, cid)
    if not c:
        raise HTTPException(404, "Courier not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------- Staff ----------
class StaffIn(BaseModel):
    name: str
    email: str = ""
    role: str = ""
    access: str = "limited"


class StaffPatch(BaseModel):
    active: Optional[bool] = None
    role: Optional[str] = None


@router.get("/staff")
def list_staff(db: Session = Depends(get_db)):
    return [
        {"id": s.id, "name": s.name, "email": s.email, "role": s.role,
         "access": s.access, "region": s.region or "", "status": s.status}
        for s in db.query(Staff).all()
    ]


@router.post("/staff")
def add_staff(payload: StaffIn, db: Session = Depends(get_db)):
    s = Staff(name=payload.name, email=payload.email, role=payload.role, access=payload.access)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "name": s.name, "email": s.email, "role": s.role,
            "access": s.access, "status": "active"}


@router.patch("/staff/{sid}")
def patch_staff(sid: int, payload: StaffPatch, db: Session = Depends(get_db)):
    s = db.get(Staff, sid)
    if not s:
        raise HTTPException(404, "Staff not found")
    if payload.active is not None:
        s.status = "active" if payload.active else "inactive"
    if payload.role:
        s.role = payload.role
    db.commit()
    return {"ok": True, "id": s.id, "status": s.status}


@router.delete("/staff/{sid}")
def delete_staff(sid: int, db: Session = Depends(get_db)):
    s = db.get(Staff, sid)
    if not s:
        raise HTTPException(404, "Staff not found")
    db.delete(s)
    db.commit()
    return {"ok": True}


ROLE_NAMES = {
    "CUSTOMER": "عميل", "MERCHANT": "تاجر", "COURIER": "مندوب",
    "COMPANY": "شركة لوجستية", "SUPERVISOR": "مشرف",
    "DOU_OPS": "فريق العمليات", "DOU_ADMIN": "مدير المنصة",
}


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.id).all()
    return [
        {"id": u.id, "name": u.name, "phone": u.phone, "role": u.role,
         "role_ar": ROLE_NAMES.get(u.role, u.role), "is_active": u.is_active,
         "tenant_id": u.tenant_id}
        for u in rows
    ]


@router.patch("/users/{uid}")
def patch_user(uid: int, payload: dict, db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    role = payload.get("role")
    if role is not None:
        r = role.upper()
        if r not in UserRole.__members__:
            raise HTTPException(400, f"دور غير صالح: {role}")
        u.role = r
    if payload.get("is_active") is not None:
        u.is_active = bool(payload["is_active"])
    password = payload.get("password")
    if password is not None:
        if len(password) < 6:
            raise HTTPException(400, "كلمة المرور قصيرة جداً (6 أحرف على الأقل)")
        u.password_hash = hash_password(password)
        u.token_version = (u.token_version or 0) + 1
    db.commit()
    return {"ok": True, "id": u.id, "role": u.role, "is_active": u.is_active}
