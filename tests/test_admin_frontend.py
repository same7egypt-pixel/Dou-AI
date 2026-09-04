"""Frontend smoke tests for DOU Super Admin Portal (frontend-v2/admin)."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_DIR = ROOT / "frontend-v2" / "admin"
SHELL_JS = (ADMIN_DIR / "shell.js").read_text(encoding="utf-8")
MAIN_JS = (ADMIN_DIR / "main.js").read_text(encoding="utf-8")
PLATFORM_JS = (ADMIN_DIR / "views" / "platform.js").read_text(encoding="utf-8")
FLEX_JS = (ADMIN_DIR / "views" / "flexBookings.js").read_text(encoding="utf-8")
TENANTS_JS = (ADMIN_DIR / "views" / "tenants.js").read_text(encoding="utf-8")
OVERVIEW_JS = (ADMIN_DIR / "views" / "overview.js").read_text(encoding="utf-8")


def test_static_admin_html_is_deleted():
    """Single admin portal rule: static/admin.html must never exist."""
    assert not (ROOT / "static" / "admin.html").exists(), (
        "static/admin.html still exists! It must be completely deleted to prevent dual sources of truth."
    )


def test_admin_v2_views_defined():
    """All 10 canonical views are registered in VIEWS list."""
    expected_views = [
        "overview", "tenants", "flexBookings", "revenue",
        "plans", "usage", "health", "integrations", "audit", "settings"
    ]
    for v in expected_views:
        assert f"'{v}'" in SHELL_JS or f'"{v}"' in SHELL_JS, f"View {v} not found in shell.js"


def test_admin_v2_navigation_labels():
    """Navigation has Arabic and English labels for views."""
    assert "لوحة القيادة" in SHELL_JS
    assert "الشركات المشتركة" in SHELL_JS
    assert "عقود المطاعم (DOU Flex)" in SHELL_JS
    assert "التحصيل والإيرادات" in SHELL_JS
    assert "صحة المنصة" in SHELL_JS


def test_admin_v2_loaders_registered():
    """main.js registers all view loaders."""
    assert "loadOverview" in MAIN_JS
    assert "loadTenants" in MAIN_JS
    assert "loadFlexBookings" in MAIN_JS
    assert "loadRevenue" in MAIN_JS
    assert "loadPlans" in MAIN_JS
    assert "loadUsage" in MAIN_JS
    assert "loadHealth" in MAIN_JS
    assert "loadIntegrations" in MAIN_JS
    assert "loadAudit" in MAIN_JS
    assert "loadSettings" in MAIN_JS


def test_admin_v2_api_calls():
    """API endpoints called by views match backend admin router."""
    assert "/admin/dashboard" in OVERVIEW_JS
    assert "/admin/tenants" in TENANTS_JS
    assert "/admin/dedicated/metrics" in FLEX_JS
    assert "/admin/dedicated/bookings" in FLEX_JS
    assert "/admin/finance/summary" in PLATFORM_JS
    assert "/admin/system-status" in PLATFORM_JS
    assert "/admin/audit-log" in PLATFORM_JS


def test_admin_v2_javascript_syntax():
    """All JS files in frontend-v2/admin parse without syntax errors."""
    for js_path in [
        ADMIN_DIR / "main.js",
        ADMIN_DIR / "shell.js",
        ADMIN_DIR / "views" / "overview.js",
        ADMIN_DIR / "views" / "tenants.js",
        ADMIN_DIR / "views" / "flexBookings.js",
        ADMIN_DIR / "views" / "platform.js",
    ]:
        result = subprocess.run(["node", "--check", str(js_path)], capture_output=True, text=True)
        assert result.returncode == 0, f"JS syntax error in {js_path.name}: {result.stderr}"


def test_admin_v2_no_legacy_delivery_nav():
    """Legacy marketplace views (channels, orders) are not in Super Admin nav."""
    assert "'channels'" not in SHELL_JS
    assert "'orders'" not in SHELL_JS
    assert "'merchants'" not in SHELL_JS
