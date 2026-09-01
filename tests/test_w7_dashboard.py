"""Minimal frontend smoke tests for W7 Operations Command Center (now overview)."""
import re


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


def test_html_contains_dashboard_section():
    """Verify dashboard (overview) section exists in fleet.html."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()

    # Dashboard is now the overview view
    assert 'data-view="overview"' in html, "Overview navigation button missing"
    assert 'id="view-overview"' in html, "Overview section missing"
    
    # Summary KPIs
    assert 'id="mCouriers"' in html, "Total riders metric missing"
    assert 'id="mOnline"' in html, "Online riders metric missing"
    assert 'id="mActive"' in html, "Active riders metric missing"
    assert 'id="mPresent"' in html, "Present today metric missing"
    assert 'id="mAbsent"' in html, "Absent today metric missing"
    
    # Workforce metrics
    assert 'id="mReady"' in html, "Ready to work metric missing"
    assert 'id="mNotReady"' in html, "Not ready metric missing"
    assert 'id="mOnLeave"' in html, "On leave metric missing"
    assert 'id="mPendingLeaves"' in html, "Pending leaves metric missing"
    
    # Document metrics
    assert 'id="mDocsExpired"' in html, "Expired documents metric missing"
    assert 'id="mDocs30"' in html, "Documents expiring in 30 days metric missing"
    assert 'id="mDocs60"' in html, "Documents expiring in 60 days metric missing"
    
    # Pool metrics
    assert 'id="poolCompany"' in html, "Company couriers metric missing"
    assert 'id="poolFreelance"' in html, "Freelance couriers metric missing"
    assert 'id="mPayroll"' in html, "Payroll total metric missing"


def test_dashboard_loads_data_from_api():
    """Verify dashboard loads data from real backend APIs."""
    js = _extract_javascript()
    
    assert 'loadOverview' in js, "loadOverview function missing"
    assert '/fleet/overview' in js, "Overview API endpoint missing"
    assert 'renderOverview' in js, "renderOverview function missing"


def test_dashboard_has_refresh_button():
    """Verify dashboard has refresh capability."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()
    
    assert 'onclick="loadOverview()"' in html, "Refresh button missing"
