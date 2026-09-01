"""Minimal frontend smoke tests for W10 Reports & Exports."""
import re


def _extract_javascript():
    """Extract JavaScript content from fleet.html."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html', 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'<script>\s*(.*?)\s*</script>', content, re.DOTALL)
    return match.group(1) if match else ''


def test_reports_center_function_exists():
    """Test that loadReportsCenter function exists in fleet.html."""
    js = _extract_javascript()
    assert 'async function loadReportsCenter()' in js or 'function loadReportsCenter()' in js, \
        "loadReportsCenter function not found"


def test_reports_export_csv_function_exists():
    """Test that downloadReportCSV function exists in fleet.html."""
    js = _extract_javascript()
    assert 'function downloadReportCSV()' in js, "downloadReportCSV function not found"


def test_reports_export_xlsx_function_exists():
    """Test that downloadReportXLSX function exists in fleet.html."""
    js = _extract_javascript()
    assert 'function downloadReportXLSX()' in js, "downloadReportXLSX function not found"


def test_reports_navigation_hook():
    """Test that reports view is wired to loadReportsCenter."""
    js = _extract_javascript()
    assert "if (view === 'reports') loadReportsCenter();" in js, \
        "Reports navigation hook not found"


def test_reports_catalog_html_exists():
    """Test that reports catalog HTML exists."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html', 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'id="reportsCatalog"' in content, "Reports catalog element not found"
    assert 'data-group="workforce"' in content, "Workforce group not found"
    assert 'data-group="financial"' in content, "Financial group not found"


def test_reports_export_buttons_exist():
    """Test that export buttons exist in reports section."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html', 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'reportsExportCsvBtn' in content, "CSV export button not found"
    assert 'reportsExportXlsxBtn' in content, "XLSX export button not found"


def test_reports_section_exists():
    """Test that reports section exists in fleet.html."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html', 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'id="view-reports"' in content, "Reports section not found"
    assert 'مركز التقارير' in content, "Reports center title not found"
