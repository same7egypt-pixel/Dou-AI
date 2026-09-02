from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import ENABLE_PUBLIC_COMPANY_SIGNUP, SECRET_KEY
from ..database import get_db
from ..models.entities import Country, Fleet, Tenant, User, UserRole
from ..schemas.dou import CompanyRegisterIn, CompanyRegisterOut, LoginIn, TokenOut
from ..services.cache import get_redis

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7
TRIAL_DAYS = 14

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


def _login_failure_count(key: str, now: datetime) -> int:
    """Failed attempts inside the window, shared across workers when Redis is up.

    Per-process counters let an attacker get ``LOGIN_MAX_FAILURES`` tries per
    uvicorn worker and reset the budget by restarting the app, so Redis is the
    real throttle and the in-process deque is only the fallback.
    """
    client = get_redis()
    if client is None:
        with _login_lock:
            return len(_prune_failures(key, now))
    try:
        return int(client.get(f"login_fail:{key}") or 0)
    except Exception:
        with _login_lock:
            return len(_prune_failures(key, now))


def _record_login_failure(key: str, now: datetime) -> None:
    client = get_redis()
    if client is not None:
        try:
            redis_key = f"login_fail:{key}"
            pipe = client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, LOGIN_WINDOW_SECONDS)
            pipe.execute()
            return
        except Exception:
            pass
    with _login_lock:
        _prune_failures(key, now).append(now.timestamp())


def _clear_login_failures(key: str) -> None:
    client = get_redis()
    if client is not None:
        try:
            client.delete(f"login_fail:{key}")
        except Exception:
            pass
    with _login_lock:
        _login_failures.pop(key, None)


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("Password is too long")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "phone": user.phone,
        "role": user.role.value,
        "ver": user.token_version or 0,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS),
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
        raise HTTPException(
            403,
            "تفعيل الشركات الجديدة يتم عن طريق إدارة DOU — sales@dou.delivery — 0556338075",
        )
    country = (
        Country(payload.country) if payload.country in ("SA", "EG") else Country.SA
    )
    exists = db.query(User).filter(User.phone == payload.phone).first()
    if exists:
        raise HTTPException(400, "Phone already registered")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Company name is required")
    if len(payload.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    now = datetime.now(timezone.utc)
    tenant = Tenant(
        name=name,
        country=country,
        plan="TRIAL",
        monthly_fee=0,
        billing_day=1,
        subscription_status="ACTIVE",
        due_date=now + timedelta(days=TRIAL_DAYS),
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
    now = datetime.now(timezone.utc)
    key = (
        _login_key(request, payload.phone)
        if request
        else f"direct:{payload.phone.strip()}"
    )
    if _login_failure_count(key, now) >= LOGIN_MAX_FAILURES:
        raise HTTPException(429, "محاولات دخول كثيرة. انتظر 10 دقائق ثم حاول مرة أخرى")
    user = db.query(User).filter(User.phone == payload.phone).first()
    if not user or not verify_password(payload.password, user.password_hash):
        _record_login_failure(key, now)
        raise HTTPException(401, "Invalid phone or password")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    _clear_login_failures(key)
    user.last_login_at = now
    if user.tenant_id:
        tenant = db.get(Tenant, user.tenant_id)
        if tenant:
            tenant.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    return TokenOut(access_token=create_token(user), role=user.role.value)


@router.post("/logout-all")
def logout_all(
    admin_key: str = "",
    x_admin_key: str = Header(default="", alias="X-Admin-Key"),
    db: Session = Depends(get_db),
):
    """يبطل جميع الجلسات الحالية في النظام دفعة واحدة (يرفع token_version للجميع)."""
    from ..config import ADMIN_KEY

    key = x_admin_key or admin_key
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "Invalid admin key")
    db.execute(text("UPDATE users SET token_version = COALESCE(token_version, 0) + 1"))
    db.commit()
    return {"ok": True, "message": "All sessions invalidated"}


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    credentials_exc = HTTPException(401, "Invalid or expired token")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise credentials_exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise credentials_exc
    if int(payload.get("ver", 0)) != (user.token_version or 0):
        raise credentials_exc
    # تطبيق إيقاف الاشتراك على كل وحدات الشركة والسائق، وليس لوحة Fleet فقط.
    # تظل شاشة الفاتورة متاحة حتى يعرف العميل سبب الإيقاف وموعد الاستحقاق.
    if user.tenant_id and (
        not request or request.url.path not in ("/billing/status", "/billing/invoice")
    ):
        from .billing import check_active

        check_active(user, db)
    return user


@router.post("/logout")
def logout_current(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """يبطل كل التوكنات الحالية للحساب عند تسجيل الخروج."""
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(
    payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    current = str(payload.get("current_password") or "")
    new = str(payload.get("new_password") or "")
    if not verify_password(current, user.password_hash):
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
