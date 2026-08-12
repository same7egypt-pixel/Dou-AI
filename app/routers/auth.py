from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import SECRET_KEY
from ..database import get_db
from ..models.entities import Country, Fleet, Tenant, User, UserRole
from ..schemas.dou import CompanyRegisterIn, CompanyRegisterOut, LoginIn, TokenOut

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7
DEFAULT_PASSWORD = "dou123456"
TRIAL_DAYS = 14

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

router = APIRouter(prefix="/auth", tags=["auth"])


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
    role = UserRole(payload.role) if payload.role else UserRole.CUSTOMER
    exists = db.query(User).filter(
        User.phone == payload.phone, User.role == role
    ).first()
    if exists:
        raise HTTPException(400, "Phone already registered for this role")
    user = User(
        phone=payload.phone,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=role,
        country=payload.country,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_token(user), role=user.role.value)


@router.post("/company-register", response_model=CompanyRegisterOut)
def company_register(payload: CompanyRegisterIn, db: Session = Depends(get_db)):
    country = Country(payload.country) if payload.country in ("SA", "EG") else Country.SA
    exists = db.query(User).filter(User.phone == payload.phone).first()
    if exists:
        raise HTTPException(400, "Phone already registered")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Company name is required")

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
        password_hash=hash_password(DEFAULT_PASSWORD),
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
        password=DEFAULT_PASSWORD,
        plan=tenant.plan,
        due_date=tenant.due_date,
    )


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == payload.phone).first()
    if not user or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid phone or password")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    return TokenOut(access_token=create_token(user), role=user.role.value)


@router.post("/logout-all")
def logout_all(admin_key: str, db: Session = Depends(get_db)):
    """يبطل جميع الجلسات الحالية في النظام دفعة واحدة (يرفع token_version للجميع)."""
    from ..config import ADMIN_KEY
    if admin_key != ADMIN_KEY:
        raise HTTPException(403, "Invalid admin key")
    db.execute(text("UPDATE users SET token_version = COALESCE(token_version, 0) + 1"))
    db.commit()
    return {"ok": True, "message": "All sessions invalidated"}


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
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
    return user


def require_role(*roles: UserRole):
    def checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(403, "Not authorized for this role")
        return user
    return checker
