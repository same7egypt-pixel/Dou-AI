import os

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import CORS_ORIGINS, ENABLE_LEGACY_DELIVERY, GOOGLE_ANALYTICS_ID
from .database import get_db
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.security_headers import SecurityHeadersMiddleware
from .middleware.size_limit import RequestSizeLimitMiddleware
from .routers import (
    admin,
    admin_dedicated,
    analytics,
    analytics_freshness,
    auth,
    billing,
    client_invoices,
    couriers,
    dashboard,
    documents,
    dou_ai,
    driver_dedicated,
    enterprise,
    fleet,
    fleet_dedicated,
    geo,
    health,
    hr,
    imports,
    leave,
    merchant,
    merchants,
    ninja_integration,
    notifications,
    operations,
    operators,
    orders,
    payroll,
    performance,
    readiness,
    reports,
    salary,
    shifts,
    shifts_assignment,
    shipping,
    sources,
    supervisor,
    timekeeping,
    vehicles,
    workforce,
)
from .services.observability import init_sentry

app = FastAPI(title="DOU Platform API", version="0.2.0")

# Error reporting. A no-op unless SENTRY_DSN is set, and it touches no database,
# so it is safe at import time.
init_sentry()

# Schema changes belong to Alembic and run from tools/migrate.py before the web
# process starts. Importing this module must never touch the database.

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(RateLimitMiddleware, requests_per_minute=300)
app.add_middleware(RequestSizeLimitMiddleware, max_size_bytes=15 * 1024 * 1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Admin-Key",
        "X-Request-ID",
    ],
)

app.include_router(auth.router)
app.include_router(couriers.router)
app.include_router(shifts.router)
app.include_router(admin.router)
app.include_router(admin.gate_router)
app.include_router(fleet.router)
app.include_router(billing.router)
app.include_router(hr.router)
app.include_router(workforce.router)
app.include_router(vehicles.router)
app.include_router(salary.router)
app.include_router(timekeeping.router)
app.include_router(leave.router)
app.include_router(documents.router)
app.include_router(readiness.router)
app.include_router(sources.router)
app.include_router(ninja_integration.router)
app.include_router(client_invoices.router)
app.include_router(imports.router)
app.include_router(analytics.router)
app.include_router(dashboard.router)
app.include_router(performance.router)
app.include_router(payroll.router)
app.include_router(reports.router)
app.include_router(operators.router)
app.include_router(supervisor.router)
app.include_router(shifts_assignment.router)
app.include_router(operations.router)
app.include_router(enterprise.router)
app.include_router(dou_ai.router)
app.include_router(notifications.router)
app.include_router(analytics_freshness.router)
app.include_router(notifications.webhook_router)
app.include_router(health.router)
app.include_router(merchant.router)
app.include_router(driver_dedicated.router)
app.include_router(fleet_dedicated.router)
app.include_router(admin_dedicated.router)

# المنتج الحالي مخصص لإدارة سائقي الشركات. مسارات التجارة والطلبات والشحن
# القديمة لا تُنشر إلا عند تفعيلها صراحة لأغراض التوافق أو العرض التجريبي.
if ENABLE_LEGACY_DELIVERY:
    app.include_router(merchants.router)
    app.include_router(orders.router)
    app.include_router(shipping.router)
    app.include_router(geo.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)


class NoCacheHtml(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if (path.endswith(".html") or path.endswith(".js") or path.endswith(".css")) and response.status_code == 200:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif any(path.endswith(ext) for ext in [".svg", ".png", ".jpg", ".woff2", ".woff"]) and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


app.mount("/static", NoCacheHtml(directory=STATIC_DIR), name="static")
FRONTEND_V2_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "frontend-v2"
)
os.makedirs(FRONTEND_V2_DIR, exist_ok=True)
app.mount("/frontend-v2", NoCacheHtml(directory=FRONTEND_V2_DIR), name="frontend-v2")


@app.api_route("/", methods=["GET", "HEAD"])
def index(request: Request):
    forwarded_host = (
        request.headers.get("x-forwarded-host", "").split(",")[0].strip().split(":")[0]
    )
    direct_host = request.headers.get("host", "").split(":")[0]
    if "admin.dou.delivery" in {
        request.url.hostname or "",
        forwarded_host,
        direct_host,
    }:
        return FileResponse(os.path.join(FRONTEND_V2_DIR, "admin", "index.html"))
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.api_route("/en", methods=["GET", "HEAD"])
@app.api_route("/en/", methods=["GET", "HEAD"])
def english_landing():
    return FileResponse(os.path.join(STATIC_DIR, "index-en.html"))


@app.api_route("/help", methods=["GET", "HEAD"])
def arabic_help():
    with open(os.path.join(STATIC_DIR, "help.html"), encoding="utf-8") as source:
        return HTMLResponse(
            source.read().replace(
                "</head>", '<script src="/google-analytics.js" defer></script></head>'
            )
        )


@app.api_route("/help/en", methods=["GET", "HEAD"])
def english_help():
    with open(os.path.join(STATIC_DIR, "help-en.html"), encoding="utf-8") as source:
        return HTMLResponse(
            source.read().replace(
                "</head>", '<script src="/google-analytics.js" defer></script></head>'
            )
        )


@app.api_route("/robots.txt", methods=["GET", "HEAD"])
def robots():
    return FileResponse(os.path.join(STATIC_DIR, "robots.txt"), media_type="text/plain")


@app.api_route("/favicon.ico", methods=["GET", "HEAD"])
def favicon():
    return FileResponse(
        os.path.join(STATIC_DIR, "icons", "icon-192.png"), media_type="image/png"
    )


@app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
def sitemap():
    return FileResponse(
        os.path.join(STATIC_DIR, "sitemap.xml"), media_type="application/xml"
    )


@app.get("/google-analytics.js")
def google_analytics():
    if not GOOGLE_ANALYTICS_ID.startswith("G-"):
        return Response("", media_type="application/javascript")
    script = f"""(function(){{var s=document.createElement('script');s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id={GOOGLE_ANALYTICS_ID}';document.head.appendChild(s);window.dataLayer=window.dataLayer||[];window.gtag=function(){{dataLayer.push(arguments)}};gtag('js',new Date());gtag('config','{GOOGLE_ANALYTICS_ID}',{{anonymize_ip:true}});}})();"""
    return Response(
        script,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/app")
@app.get("/app/")
def fleet_app():
    return FileResponse(os.path.join(FRONTEND_V2_DIR, "fleet", "index.html"))


@app.get("/admin")
@app.get("/admin/")
def admin_app():
    return FileResponse(os.path.join(FRONTEND_V2_DIR, "admin", "index.html"))


@app.get("/app/workforce")
@app.get("/app/workforce/")
def app_workforce():
    """Retired. Teams and zones are handled by contracts and branches in /app.

    The old workforce screen called /workforce/riders/{id}/team-transfer and
    rendered a second, parallel org model beside the contract/branch one the
    product actually runs on. Redirecting rather than 404ing means an old
    bookmark lands on the current dashboard.
    """
    return RedirectResponse(url="/app", status_code=308)


@app.get("/driver")
@app.head("/driver")
@app.get("/driver/")
@app.head("/driver/")
def driver_app():
    return FileResponse(os.path.join(STATIC_DIR, "courier.html"))


@app.get("/merchant")
@app.head("/merchant")
@app.get("/merchant/")
@app.head("/merchant/")
def merchant_app():
    return FileResponse(os.path.join(STATIC_DIR, "merchant.html"))




@app.api_route("/sw.js", methods=["GET", "HEAD"])
def rider_service_worker():
    return FileResponse(
        os.path.join(STATIC_DIR, "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/driver", "Cache-Control": "no-cache"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "dou-api"}


@app.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "dou-api", "database": "ok"}


@app.api_route(
    "/.well-known/assetlinks.json", methods=["GET", "HEAD"], include_in_schema=False
)
def android_asset_links():
    return FileResponse(
        os.path.join(STATIC_DIR, "assetlinks.json"),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.api_route("/download/driver-apk", methods=["GET", "HEAD"])
def download_driver_apk():
    return FileResponse(
        os.path.join(STATIC_DIR, "DOU-Driver.apk"),
        media_type="application/vnd.android.package-archive",
        filename="DOU-Driver.apk",
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
    return (
        ERROR_PAGE.replace("__CODE__", str(code))
        .replace("__TITLE__", title)
        .replace("__DETAIL__", detail)
    )


def _wants_html(request: Request) -> bool:
    """Whether this is a page navigation rather than a call from script.

    `*/*` used to count as wanting HTML. That is precisely what `fetch` sends
    when the caller sets no Accept header — which the frontend's api client does
    not — so every 404 raised by an API endpoint came back as an error *page*,
    `JSON.parse` failed on it, and the operator was shown "HTTP 404" instead of
    the sentence the endpoint had written. A browser navigating to a URL asks
    for `text/html` explicitly, so deep links into the SPA still resolve.
    """
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "application/xhtml" in accept


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if _wants_html(request) and not request.url.path.startswith("/static"):
        return HTMLResponse(
            _error_page(
                404,
                "الصفحة غير موجودة",
                "المسار الذي تبحث عنه غير متوفر، أو أن الرابط قديم.",
            ),
            status_code=404,
        )
    # The endpoint's own words, not a generic "Not Found": "لا توجد شركة مسجّلة
    # بهذا الجوال" tells the operator what to do next, and this handler was
    # throwing it away.
    detail = getattr(exc, "detail", None) or "Not Found"
    return JSONResponse({"detail": detail}, status_code=404)


@app.exception_handler(500)
async def internal_error(request: Request, exc):
    import traceback

    print("=== 500 ERROR ===", repr(exc), flush=True)
    traceback.print_exc()
    if _wants_html(request):
        return HTMLResponse(
            _error_page(
                500,
                "خطأ في الخادم",
                "حدث خطأ غير متوقع. حاول مرة أخرى خلال لحظات، وإذا تكررت المشكلة تواصل مع الدعم.",
            ),
            status_code=500,
        )
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
