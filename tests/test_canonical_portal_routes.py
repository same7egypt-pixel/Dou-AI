from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = ROOT / "app" / "main.py"
AR_LANDING = ROOT / "static" / "index.html"
EN_LANDING = ROOT / "static" / "index-en.html"
REPORT_EXECUTOR = ROOT / "app" / "services" / "report_executor.py"
ANDROID_MAIN = ROOT / "android-driver" / "app" / "src" / "main" / "java" / "delivery" / "dou" / "driver" / "MainActivity.java"


def test_canonical_portal_routes_are_live():
    """Asserted against the app's own route table, not the text of main.py.

    This used to grep for `@app.get("/driver")` and `@app.get("/download/…")`.
    Both routes later grew a HEAD handler and became `@app.api_route`, which is
    the same route serving the same file — and the guard failed twice over a
    decorator spelling while the routes were demonstrably live. What the test's
    name promises is that the path is served; that is what it checks now.
    """
    from app.main import app

    served = {
        route.path: route.methods
        for route in app.routes
        if hasattr(route, "path") and hasattr(route, "methods")
    }
    for path in ("/app", "/driver", "/admin", "/download/driver-apk"):
        assert path in served, f"{path} is not routed at all"
        assert "GET" in served[path], f"{path} is routed but does not answer GET"

    # The files behind them, which the route table cannot show.
    source = MAIN_PY.read_text(encoding="utf-8")
    assert 'FRONTEND_V2_DIR, "fleet", "index.html"' in source
    assert 'FRONTEND_V2_DIR, "admin", "index.html"' in source
    # One admin console. The retired one must not come back on any path.
    assert 'STATIC_DIR, "admin.html"' not in source
    assert not (ROOT / "static" / "admin.html").exists(), (
        "the retired admin console is back in the tree; two consoles is two "
        "sources of truth"
    )


def test_versioned_portal_routes_are_disabled():
    source = MAIN_PY.read_text(encoding="utf-8")
    assert '@app.get("/app/v2")' not in source
    assert '@app.get("/admin/v2")' not in source


def test_runtime_links_use_canonical_paths_and_domain():
    runtime_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (AR_LANDING, EN_LANDING, REPORT_EXECUTOR, ANDROID_MAIN)
    )
    assert "/app/v2" not in runtime_sources
    assert "18.194.202.73" not in runtime_sources
    assert "127.0.0.1:8123" not in runtime_sources
    assert "https://dou.delivery/driver" in runtime_sources


def test_no_screen_reads_a_column_that_was_dropped():
    """`contract_value_monthly` and `dou_commission_monthly` were removed in
    migration 0027 when the commission model was reverted. A screen still
    reading them looks like a working fallback and can only ever be dead."""
    import re

    dropped = ("contract_value_monthly", "dou_commission_monthly")
    offenders = []
    for path in list((ROOT / "frontend-v2").rglob("*.js")) + list(
        (ROOT / "app").rglob("*.py")
    ):
        if "alembic" in str(path):
            continue
        code = re.sub(r"//[^\n]*|#[^\n]*", "", path.read_text(encoding="utf-8"))
        for column in dropped:
            if column in code:
                offenders.append(f"{path.relative_to(ROOT)}: {column}")
    assert not offenders, "reading columns that no longer exist: " + ", ".join(offenders)
