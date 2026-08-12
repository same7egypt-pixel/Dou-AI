from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dou.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
ENABLE_LEGACY_DELIVERY = os.getenv("ENABLE_LEGACY_DELIVERY", "false").lower() == "true"
CORS_ORIGINS = [x.strip() for x in os.getenv(
    "CORS_ORIGINS", "https://dou-platform.onrender.com,http://127.0.0.1:8765,http://localhost:8765"
).split(",") if x.strip()]

# Dispatch thresholds
LOCAL_RADIUS_KM = float(os.getenv("SMALL_ORDER_LOCAL_RADIUS_KM", "5"))
LONG_DISTANCE_KM = float(os.getenv("LONG_DISTANCE_THRESHOLD_KM", "25"))
OFFER_TIMEOUT_SEC = 30
