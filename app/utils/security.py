import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import SECRET_KEY

ALGORITHM = "HS256"
security_bearer = HTTPBearer(auto_error=False)


def hash_pin(pin: str) -> str:
    """Hash a numeric or alphanumeric cashier PIN using bcrypt."""
    return bcrypt.hashpw(pin.strip().encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_pin(pin: str, hashed_pin: str) -> bool:
    """Verify a plain PIN against a stored bcrypt hash."""
    if not pin or not hashed_pin:
        return False
    try:
        return bcrypt.checkpw(pin.strip().encode("utf-8"), hashed_pin.encode("utf-8"))
    except Exception:
        return False


def generate_merchant_api_key(custom_prefix: Optional[str] = None) -> tuple[str, str, str]:
    """
    Generate an API key for POS ingestion.
    Format: dou_live_<prefix>_<secret>
    Prefix: 8-16 alphanumeric chars.
    Secret: 48 hex chars (alphanumeric only, never contains underscore).
    Returns: (raw_key, prefix, hashed_key)
    """
    prefix = custom_prefix if custom_prefix else secrets.token_hex(6)
    # Ensure prefix is clean alphanumeric
    prefix = "".join(c for c in prefix if c.isalnum())[:16]
    secret = secrets.token_hex(24)
    raw_key = f"dou_live_{prefix}_{secret}"
    hashed_key = bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return raw_key, prefix, hashed_key


def hash_merchant_api_key(raw_key: str) -> str:
    """Bcrypt hash an existing merchant API key."""
    return bcrypt.hashpw(raw_key.strip().encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_merchant_api_key(raw_key: str, hashed_key: str) -> bool:
    """Verify an API key against stored bcrypt hash."""
    if not raw_key or not hashed_key:
        return False
    try:
        return bcrypt.checkpw(raw_key.strip().encode("utf-8"), hashed_key.encode("utf-8"))
    except Exception:
        return False


def create_branch_token(
    branch_id: int,
    expires_hours: int = 8,
    merchant_account_id: Optional[int] = None,
) -> str:
    """Generate a branch-scoped JWT for the cashier portal."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": f"merchant_branch:{branch_id}",
        "branch_id": branch_id,
        "scope": "merchant_branch",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    if merchant_account_id is not None:
        payload["merchant_account_id"] = merchant_account_id
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_branch_token(token: str) -> int:
    """
    Decode and validate a branch token.
    Returns the branch_id.
    Raises HTTP 401 on missing/expired/invalid token.
    Raises HTTP 403 on valid Fleet OS or non-branch tokens.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")

    sub = str(payload.get("sub", ""))
    scope = payload.get("scope")

    if not sub.startswith("merchant_branch:") or scope != "merchant_branch":
        raise HTTPException(status_code=403, detail="Forbidden: branch token required.")

    branch_id = payload.get("branch_id")
    if branch_id is None:
        try:
            branch_id = int(sub.split(":")[1])
        except (IndexError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid branch token structure.")
    return int(branch_id)


def get_current_branch_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> int:
    """Dependency that extracts and validates branch_id from Authorization: Bearer <token>."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return decode_branch_token(credentials.credentials)


def create_merchant_account_token(merchant_account_id: int, expires_hours: int = 24) -> str:
    """Generate a merchant-account-scoped JWT for statement / finance portal."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": f"merchant_account:{merchant_account_id}",
        "merchant_account_id": merchant_account_id,
        "scope": "merchant_account",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_merchant_account_token(token: str) -> int:
    """Decode and validate a merchant account token. Returns merchant_account_id.

    Strictly separates branch cashier PIN tokens from merchant account owner tokens.
    Branch cashier tokens receive HTTP 403 guiding them to the cashier portal.
    Expired or invalid tokens receive HTTP 401 prompting re-login.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="تسجيل الدخول مطلوب. يرجى تسجيل الدخول بحساب مالك المطعم.",
        )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="انتهت صلاحية جلسة الدخول. يرجى إعادة تسجيل الدخول لمتابعة العمل.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="رمز الدخول غير صالح. يرجى تسجيل الدخول من جديد.",
        )

    sub = str(payload.get("sub", ""))
    scope = payload.get("scope")

    # Strict isolation: A branch cashier token must NEVER read chain-wide account statements
    if scope == "merchant_branch" or sub.startswith("merchant_branch:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="عذراً، هذا القسم مخصص لمالك المجموعة التجارية فقط. كاشير الفرع غير مصرح له بالاطلاع على الفواتير المجمعة أو كشوف الحساب. يرجى التوجه لبوابة كاشير الفرع عبر /merchant.",
        )

    if not sub.startswith("merchant_account:") or scope != "merchant_account":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="غير مصرح: هذا الإجراء يتطلب توكن مالك الحساب التجاري المعتمد.",
        )

    account_id = payload.get("merchant_account_id")
    if account_id is None:
        try:
            account_id = int(sub.split(":")[1])
        except (IndexError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="رمز الدخول غير صالح في بنيته. يرجى إعادة تسجيل الدخول.",
            )
    return int(account_id)


def get_current_merchant_account_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> int:
    """Dependency that extracts and validates merchant_account_id from Authorization: Bearer <token>."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return decode_merchant_account_token(credentials.credentials)
