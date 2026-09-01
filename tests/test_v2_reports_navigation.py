from pathlib import Path

from app.routers import reports


ROOT = Path(__file__).resolve().parents[1]
REPORTS_JS = ROOT / "frontend-v2" / "fleet" / "views" / "reports.js"
MAIN_CSS = ROOT / "frontend-v2" / "shared" / "styles" / "main.css"


def test_reports_v2_starts_with_three_workflows():
    source = REPORTS_JS.read_text(encoding="utf-8")
    assert "let activeSubTab = 'overview'" in source
    assert "تسجيلات المندوبين" in source
    assert "تقرير أداء الشركة اليومي" in source
    assert "المنصات المتصلة بالـ API" in source
    assert "renderReportsOverviewLayout" in source


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
    assert "?contract_id=${encodeURIComponent(platformContractFilter)}" in source
