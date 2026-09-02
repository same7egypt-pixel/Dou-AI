from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = ROOT / "app" / "main.py"
AR_LANDING = ROOT / "static" / "index.html"
EN_LANDING = ROOT / "static" / "index-en.html"
REPORT_EXECUTOR = ROOT / "app" / "services" / "report_executor.py"
ANDROID_MAIN = ROOT / "android-driver" / "app" / "src" / "main" / "java" / "delivery" / "dou" / "driver" / "MainActivity.java"


def test_canonical_portal_routes_are_live():
    source = MAIN_PY.read_text(encoding="utf-8")
    assert '@app.get("/app")' in source
    assert 'FRONTEND_V2_DIR, "fleet", "index.html"' in source
    assert '@app.get("/driver")' in source
    assert '@app.get("/admin")' in source
    assert '@app.get("/download/driver-apk")' in source


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
