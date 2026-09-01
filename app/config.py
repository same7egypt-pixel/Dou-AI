from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dou.db")
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = (
    APP_ENV in {"production", "prod"} or os.getenv("RENDER", "").lower() == "true"
)
DEFAULT_SECRET_KEY = "change-me-in-production-minimum-32-bytes"
LEGACY_DEFAULT_SECRET_KEY = "change-me-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY).strip()
if IS_PRODUCTION and (
    len(SECRET_KEY.encode("utf-8")) < 32
    or SECRET_KEY in {DEFAULT_SECRET_KEY, LEGACY_DEFAULT_SECRET_KEY}
):
    raise RuntimeError("SECRET_KEY must be configured securely in production")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
ENABLE_LEGACY_DELIVERY = os.getenv("ENABLE_LEGACY_DELIVERY", "false").lower() == "true"
ENABLE_PUBLIC_COMPANY_SIGNUP = (
    os.getenv("ENABLE_PUBLIC_COMPANY_SIGNUP", "false").lower() == "true"
)
GOOGLE_ANALYTICS_ID = os.getenv("GOOGLE_ANALYTICS_ID", "G-XF8YF12JVQ").strip()
CORS_ORIGINS = [
    x.strip()
    for x in os.getenv(
        "CORS_ORIGINS",
        "https://dou-platform.onrender.com,http://127.0.0.1:8765,http://localhost:8765",
    ).split(",")
    if x.strip()
]

# Dispatch thresholds
LOCAL_RADIUS_KM = float(os.getenv("SMALL_ORDER_LOCAL_RADIUS_KM", "5"))
LONG_DISTANCE_KM = float(os.getenv("LONG_DISTANCE_THRESHOLD_KM", "25"))
OFFER_TIMEOUT_SEC = 30

# DOU AI production mode. Operational answers are deterministic; no model
# service, model URL, or model download is required.
DOU_AI_MODE = "DETERMINISTIC"

# Signed local Metabase webhook configuration; independent from auth secrets.
METABASE_WEBHOOK_SECRET = os.getenv("METABASE_WEBHOOK_SECRET", "").strip()
NOTIFICATION_DEDUPE_MINUTES = int(os.getenv("NOTIFICATION_DEDUPE_MINUTES", "60"))
NOTIFICATION_WEBHOOK_MAX_AGE_SECONDS = int(
    os.getenv("NOTIFICATION_WEBHOOK_MAX_AGE_SECONDS", "300")
)
NOTIFICATION_WEBHOOK_CLOCK_SKEW_SECONDS = int(
    os.getenv("NOTIFICATION_WEBHOOK_CLOCK_SKEW_SECONDS", "30")
)
NOTIFICATION_WEBHOOK_SECRET = os.getenv("NOTIFICATION_WEBHOOK_SECRET", "").strip()
