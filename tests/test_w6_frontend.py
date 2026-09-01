"""Minimal frontend smoke tests for W6 bulk import workflow.

Verifies that critical DOM elements and JavaScript functions exist.
This is a structural regression test, not a full browser simulation.
"""


def test_html_contains_import_sections():
    """Verify all W6 import UI sections exist in fleet.html."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()

    # W5: Navigation and context
    assert 'id="contextSelector"' in html, "Hierarchy context selector missing"
    assert 'id="globalSearch"' in html, "Global search input missing"

    # W6: Import sections (imports and importHistory are now combined)
    assert 'id="view-imports"' in html, "Bulk import section missing"
    assert 'importTab-riders' in html, "Riders import tab missing"
    assert 'importTab-performance' in html, "Performance import tab missing"

    # W6: Import form elements
    assert 'id="riderImportFile"' in html, "Rider file input missing"
    assert 'id="performanceImportFile"' in html, "Performance file input missing"
    assert 'id="riderImportPreview"' in html, "Rider preview section missing"
    assert 'id="performanceImportPreview"' in html, "Performance preview section missing"
    assert 'id="riderImportConfirm"' in html, "Rider confirm button missing"
    assert 'id="performanceImportConfirm"' in html, "Performance confirm button missing"

    # W6: Import history table
    assert 'id="importHistoryBody"' in html, "Import history table body missing"
    assert 'id="importHistoryPagination"' in html, "Import history pagination missing"
    assert 'id="historyTypeFilter"' in html, "History type filter missing"
    assert 'id="historyStatusFilter"' in html, "History status filter missing"


def _extract_javascript():
    """Extract JavaScript content from fleet.html."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        content = f.read()
    
    idx = 0
    while True:
        start = content.find('<script', idx)
        if start == -1:
            break
        after = content[start:start+20]
        if 'src=' in after:
            idx = start + 1
            continue
        script_content = content[start+8:]
        script_content = script_content.replace('</body>\n</html>', '').rstrip()
        assert script_content.strip(), "Inline script is empty"
        return script_content
    
    raise AssertionError("No inline <script> block found")


def test_javascript_contains_import_functions():
    """Verify all W6 import JavaScript functions are defined."""
    js = _extract_javascript()

    # W5: Context and search functions
    assert 'function initHierarchyContext' in js, "initHierarchyContext missing"
    assert 'function changeOperatorContext' in js, "changeOperatorContext missing"
    assert 'function performGlobalSearch' in js, "performGlobalSearch missing"
    assert 'function applyRBACNavigation' in js, "applyRBACNavigation missing"

    # W6: Import workflow functions
    assert 'function switchImportTab' in js, "switchImportTab missing"
    assert 'function downloadRiderImportTemplate' in js, "downloadRiderImportTemplate missing"
    assert 'function downloadPerformanceImportTemplate' in js, "downloadPerformanceImportTemplate missing"
    assert 'function previewRiderImport' in js, "previewRiderImport missing"
    assert 'function confirmRiderImport' in js, "confirmRiderImport missing"
    assert 'function previewPerformanceImport' in js, "previewPerformanceImport missing"
    assert 'function confirmPerformanceImport' in js, "confirmPerformanceImport missing"
    assert 'function loadImportHistory' in js, "loadImportHistory missing"
    assert 'function viewImportDetail' in js, "viewImportDetail missing"

    # W6: Helper functions
    assert 'function renderImportSummary' in js, "renderImportSummary missing"
    assert 'function renderImportErrors' in js, "renderImportErrors missing"


def test_import_preview_shows_validation_summary():
    """Verify import preview displays validation summary cards."""
    js = _extract_javascript()
    assert 'total_rows' in js, "total_rows missing"
    assert 'valid_rows' in js, "valid_rows missing"
    assert 'invalid_rows' in js, "invalid_rows missing"


def test_rider_360_has_proper_tabs():
    """Verify Rider 360 has proper tab structure."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()

    assert 'data-r360tab="profile"' in html, "Profile tab missing"
    assert 'data-r360tab="documents"' in html, "Documents tab missing"
    assert 'data-r360tab="shifts"' in html, "Shifts tab missing"
    assert 'data-r360tab="attendance"' in html, "Attendance tab missing"
    assert 'data-r360tab="performance"' in html, "Performance tab missing"
    assert 'data-r360tab="targets"' in html, "Targets tab missing"
    assert 'data-r360tab="payroll"' in html, "Payroll tab missing"
    assert 'data-r360tab="leave"' in html, "Leave tab missing"
    assert 'function showRider360Tab' in html, "showRider360Tab function missing"


def test_phase2_surfaces_hidden():
    """Verify Phase 2 surfaces are hidden from Phase 1 Fleet UI."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()

    assert 'id="view-dispatch"' in html
    assert 'id="view-orders"' in html
    assert 'id="view-channels"' in html
    assert 'id="view-shipping"' in html
    # All should be hidden
    assert 'data-phase2="true"' in html


def test_fleet_sidebar_has_8_items():
    """Verify Fleet sidebar has exactly 8 navigation items per Prodstack."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()

    # Check for the 8 required views
    required_views = ['overview', 'couriers', 'shifts', 'needsAttention', 'capacity', 'reports', 'payouts', 'douai']
    for view in required_views:
        assert f'data-view="{view}"' in html, f"Sidebar missing {view}"


def test_rider_360_not_in_sidebar():
    """Verify Rider 360 is NOT a sidebar button - it's opened from Riders list."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()

    # Find the sidebar section
    sidebar_end = html.find('<div class="overlay"')
    sidebar_html = html[:sidebar_end] if sidebar_end > 0 else html

    # Rider 360 should NOT be a nav button in the sidebar
    assert 'data-view="rider360"' not in sidebar_html, "Rider 360 should not be in sidebar"
