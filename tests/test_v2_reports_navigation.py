from pathlib import Path

from app.routers import reports


ROOT = Path(__file__).resolve().parents[1]
REPORTS_JS = ROOT / "frontend-v2" / "fleet" / "views" / "reports.js"
MAIN_CSS = ROOT / "frontend-v2" / "shared" / "styles" / "main.css"


def test_reports_v2_starts_with_three_workflows():
    """Reports opens on driver targets, with the three tabs the 360 view defines.

    This replaced an earlier "overview" landing layout; the screen still offers
    exactly three workflows, so the guard is kept and pointed at the current set.
    """
    source = REPORTS_JS.read_text(encoding="utf-8")
    assert "let activeSubTab = 'driver_targets'" in source
    for tab in ("driver_targets", "platform_facts", "dashboards"):
        assert f"'data-tab': '{tab}'" in source
    assert "تارجت وإنجاز السائقين" in source
    assert "أداء المنصات" in source
    assert "لوحات التحليل" in source


def test_report_links_use_catalog_id_and_stable_download_routes():
    source = REPORTS_JS.read_text(encoding="utf-8")
    assert "report.report_type || report.id" in source
    assert "/analytics/reports/download/${format}" in source
    assert "encodeURIComponent(reportType)" in source
    assert "encodeURIComponent(group)" in source
    assert "Authorization: `Bearer ${api.getToken()}`" in source


def test_download_routes_are_registered_before_generic_report_route():
    paths = [route.path for route in reports.router.routes]
    generic_index = paths.index("/analytics/reports/{group}/{report_id}")
    assert paths.index("/analytics/reports/download/csv") < generic_index
    assert paths.index("/analytics/reports/download/xlsx") < generic_index


def test_reports_overview_has_responsive_styles():
    styles = MAIN_CSS.read_text(encoding="utf-8")
    assert ".reports-journeys" in styles
    assert "@media (max-width: 700px)" in styles


def test_platform_upload_and_dashboard_are_contract_scoped():
    source = REPORTS_JS.read_text(encoding="utf-8")
    assert "/analytics/reports/platform-facts/contracts" in source
    assert "platform-upload-contract" in source
    assert "contract_id: Number(contractId)" in source
    assert "params.set('contract_id', platformContractFilter)" in source
    assert "params.set('date', platformDateFilter)" in source
    assert "if (errors.length)" in source
    assert "لم يتم استيراد الملف" in source
    assert "totalImported + totalUpdated === 0" in source
    assert "platformDateFilter = ''" in source
    assert "Rider\\'s Performance" in source


def test_reports_do_not_route_analytics_to_chat():
    source = REPORTS_JS.read_text(encoding="utf-8")
    assert "ai_queries" not in source
    assert "renderAIQueriesTab" not in source
    assert "openAIDrawer" not in source
    assert "مساعد التحليلات" not in source
    assert "Analytics Assistant" not in source
