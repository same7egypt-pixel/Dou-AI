from datetime import datetime, timedelta
from collections import defaultdict, deque
from threading import Lock
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import SECRET_KEY, ENABLE_PUBLIC_COMPANY_SIGNUP
from ..database import get_db
from ..models.entities import Country, Fleet, Tenant, User, UserRole
from ..schemas.dou import CompanyRegisterIn, CompanyRegisterOut, LoginIn, TokenOut

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7
TRIAL_DAYS = 14

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_WINDOW_SECONDS = 600
LOGIN_MAX_FAILURES = 8
_login_failures = defaultdict(deque)
_login_lock = Lock()


def _login_key(request: Request, phone: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    client = forwarded or (request.client.host if request.client else "unknown")
    return f"{client}:{phone.strip()}"


def _prune_failures(key: str, now: datetime):
    cutoff = now.timestamp() - LOGIN_WINDOW_SECONDS
    attempts = _login_failures[key]
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return attempts


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "phone": user.phone,
        "role": user.role.value,
        "ver": user.token_version or 0,
        "exp": datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/register", response_model=TokenOut)
def register(payload: LoginIn, db: Session = Depends(get_db)):
    # حسابات الشركة والسائقين ينشئها مسؤول الشركة من داخل لوحته فقط.
    # إبقاء اختيار الدور هنا كان يسمح لأي زائر بطلب صلاحيات إدارية.
    raise HTTPException(403, "Public user registration is disabled")


@router.post("/company-register", response_model=CompanyRegisterOut)
def company_register(payload: CompanyRegisterIn, db: Session = Depends(get_db)):
    if not ENABLE_PUBLIC_COMPANY_SIGNUP:
        raise HTTPException(403, "تفعيل الشركات الجديدة يتم عن طريق إدارة DOU — sales@dou.delivery — 0556338075")
    country = Country(payload.country) if payload.country in ("SA", "EG") else Country.SA
    exists = db.query(User).filter(User.phone == payload.phone).first()
    if exists:
        raise HTTPException(400, "Phone already registered")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Company name is required")
    if len(payload.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    now = datetime.utcnow()
    tenant = Tenant(
        name=name, country=country,
        plan="TRIAL", monthly_fee=0, billing_day=1,
        subscription_status="ACTIVE", due_date=now + timedelta(days=TRIAL_DAYS),
        created_at=now,
    )
    db.add(tenant)
    db.flush()

    fleet = Fleet(tenant_id=tenant.id, name=f"أسطول {name}", zone="", created_at=now)
    db.add(fleet)
    db.flush()

    user = User(
        phone=payload.phone,
        name=f"إدارة {name}",
        password_hash=hash_password(payload.password),
        role=UserRole.COMPANY,
        country=country,
        tenant_id=tenant.id,
        is_active=True,
        created_at=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return CompanyRegisterOut(
        access_token=create_token(user),
        role=user.role.value,
        company_id=tenant.id,
        company_name=tenant.name,
        fleet_id=fleet.id,
        login_phone=user.phone,
        plan=tenant.plan,
        due_date=tenant.due_date,
    )


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db), request: Request = None):
    now = datetime.utcnow()
    key = _login_key(request, payload.phone) if request else f"direct:{payload.phone.strip()}"
    with _login_lock:
        if len(_prune_failures(key, now)) >= LOGIN_MAX_FAILURES:
            raise HTTPException(429, "محاولات دخول كثيرة. انتظر 10 دقائق ثم حاول مرة أخرى")
    user = db.query(User).filter(User.phone == payload.phone).first()
    if not user or not pwd_context.verify(payload.password, user.password_hash):
        with _login_lock:
            _prune_failures(key, now).append(now.timestamp())
        raise HTTPException(401, "Invalid phone or password")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    with _login_lock:
        _login_failures.pop(key, None)
    user.last_login_at = now
    if user.tenant_id:
        tenant = db.get(Tenant, user.tenant_id)
        if tenant: tenant.last_activity_at = datetime.utcnow()
    db.commit()
    return TokenOut(access_token=create_token(user), role=user.role.value)


@router.post("/logout-all")
def logout_all(admin_key: str, db: Session = Depends(get_db)):
    """يبطل جميع الجلسات الحالية في النظام دفعة واحدة (يرفع token_version للجميع)."""
    from ..config import ADMIN_KEY
    if not ADMIN_KEY or admin_key != ADMIN_KEY:
        raise HTTPException(403, "Invalid admin key")
    db.execute(text("UPDATE users SET token_version = COALESCE(token_version, 0) + 1"))
    db.commit()
    return {"ok": True, "message": "All sessions invalidated"}


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db), request: Request = None
) -> User:
    credentials_exc = HTTPException(401, "Invalid or expired token")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise credentials_exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise credentials_exc
    if int(payload.get("ver", 0)) != (user.token_version or 0):
        raise credentials_exc
    # تطبيق إيقاف الاشتراك على كل وحدات الشركة والسائق، وليس لوحة Fleet فقط.
    # تظل شاشة الفاتورة متاحة حتى يعرف العميل سبب الإيقاف وموعد الاستحقاق.
    if user.tenant_id and (not request or request.url.path not in ("/billing/status", "/billing/invoice")):
        from .billing import check_active
        check_active(user, db)
    return user


@router.post("/logout")
def logout_current(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """يبطل كل التوكنات الحالية للحساب عند تسجيل الخروج."""
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current = str(payload.get("current_password") or "")
    new = str(payload.get("new_password") or "")
    if not pwd_context.verify(current, user.password_hash):
        raise HTTPException(400, "كلمة المرور الحالية غير صحيحة")
    if len(new) < 8:
        raise HTTPException(400, "كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل")
    user.password_hash = hash_password(new)
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return {"ok": True, "message": "تم تغيير كلمة المرور، سجل الدخول مرة أخرى"}


def require_role(*roles: UserRole):
    def checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(403, "Not authorized for this role")
        return user
    return checker
