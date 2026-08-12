from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from .database import Base, engine
from .routers import merchants, couriers, orders, auth, shifts, shipping, analytics, geo, admin, fleet, billing, hr
from .models import entities  # noqa: F401 — يسجّل الجداول على Base
from .migrations import run_migrations
from .config import ENABLE_LEGACY_DELIVERY, CORS_ORIGINS
from .database import SessionLocal
from .models.entities import Country, User, UserRole
from .routers.auth import hash_password
import os

Base.metadata.create_all(bind=engine)
run_migrations(engine)


def bootstrap_admin_from_environment():
    """تهيئة مؤقتة وآمنة لمالك DOU، ثم تُحذف المتغيرات من Render."""
    phone = os.getenv("BOOTSTRAP_ADMIN_PHONE", "").strip()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    reset = os.getenv("BOOTSTRAP_ADMIN_RESET", "false").lower() == "true"
    if not phone or len(password) < 8:
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone == phone).first()
        if not user:
            user = User(phone=phone, name="مالك منصة DOU", password_hash=hash_password(password),
                        role=UserRole.DOU_ADMIN, country=Country.SA, is_active=True)
            db.add(user)
        elif reset:
            user.password_hash = hash_password(password)
            user.role = UserRole.DOU_ADMIN
            user.is_active = True
            user.token_version = (user.token_version or 0) + 1
        db.commit()
        print("✅ DOU admin bootstrap completed; remove BOOTSTRAP_ADMIN_* variables now")
    finally:
        db.close()


bootstrap_admin_from_environment()

app = FastAPI(title="DOU Platform API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(couriers.router)
app.include_router(shifts.router)
app.include_router(admin.router)
app.include_router(admin.gate_router)
app.include_router(fleet.router)
app.include_router(billing.router)
app.include_router(hr.router)

# المنتج الحالي مخصص لإدارة سائقي الشركات. مسارات التجارة والطلبات والشحن
# القديمة لا تُنشر إلا عند تفعيلها صراحة لأغراض التوافق أو العرض التجريبي.
if ENABLE_LEGACY_DELIVERY:
    app.include_router(merchants.router)
    app.include_router(orders.router)
    app.include_router(shipping.router)
    app.include_router(analytics.router)
    app.include_router(geo.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)


class NoCacheHtml(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.endswith(".html") and response.status_code == 200:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/static", NoCacheHtml(directory=STATIC_DIR), name="static")


@app.get("/")
def index(request: Request):
    """اعرض الواجهة الصحيحة حسب النطاق، مع بقاء روابط Render والمحلي متوافقة."""
    host = request.url.hostname or ""
    page_by_host = {
        "app.dou.delivery": "fleet.html",
        "driver.dou.delivery": "courier.html",
        "admin.dou.delivery": "admin.html",
    }
    return FileResponse(os.path.join(STATIC_DIR, page_by_host.get(host, "index.html")))


@app.get("/health")
def health():
    return {"status": "ok", "service": "dou-api"}


@app.get("/download/driver-apk")
def download_driver_apk():
    return RedirectResponse(
        "https://github.com/same7egypt-pixel/dou-server/releases/download/driver-latest/DOU-Driver.apk",
        status_code=302,
    )


ERROR_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ — منصة DOU</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,'Segoe UI',Tahoma,sans-serif;background:#0f1117;color:#e8eaf0;display:flex;align-items:center;justify-content:center;min-height:100vh}
  .box{text-align:center;padding:40px;max-width:420px}
  .code{font-size:72px;font-weight:800;color:#4f8cff;line-height:1}
  .msg{font-size:20px;margin:16px 0 6px;font-weight:600}
  .sub{color:#8b93a7;margin-bottom:26px;font-size:14px}
  a.btn{display:inline-block;background:#4f8cff;color:#fff;text-decoration:none;padding:11px 26px;border-radius:10px;font-weight:600;margin:0 4px}
  a.btn.ghost{background:transparent;border:1px solid #2a3040;color:#c7cedd}
</style>
</head>
<body><div class="box">
  <div class="code">__CODE__</div>
  <div class="msg">__TITLE__</div>
  <div class="sub">__DETAIL__</div>
  <div>
    <a class="btn" href="/">العودة للرئيسية</a>
    <a class="btn ghost" href="javascript:location.reload()">إعادة المحاولة</a>
  </div>
</div></body></html>"""


def _error_page(code: int, title: str, detail: str) -> str:
    return (ERROR_PAGE.replace("__CODE__", str(code))
                     .replace("__TITLE__", title)
                     .replace("__DETAIL__", detail))


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "application/xhtml" in accept or accept == "*/*"


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if _wants_html(request) and not request.url.path.startswith("/static"):
        return HTMLResponse(_error_page(404, "الصفحة غير موجودة",
                                        "المسار الذي تبحث عنه غير متوفر، أو أن الرابط قديم."),
                            status_code=404)
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@app.exception_handler(500)
async def internal_error(request: Request, exc):
    if _wants_html(request):
        return HTMLResponse(_error_page(500, "خطأ في الخادم",
                                        "حدث خطأ غير متوقع. حاول مرة أخرى خلال لحظات، وإذا تكررت المشكلة تواصل مع الدعم."),
                            status_code=500)
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
