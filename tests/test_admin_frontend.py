"""Frontend smoke tests for DOU Super Admin Portal (admin.html)."""
import re
import subprocess
import tempfile
import os


def extract_inline_js(filepath):
    with open(filepath) as f:
        content = f.read()
    idx = 0
    while True:
        start = content.find('<script', idx)
        if start == -1:
            break
        tag_end = content.find('>', start)
        tag_content = content[start:tag_end + 1]
        if 'src=' in tag_content:
            idx = start + 1
            continue
        close = content.rfind('</script>')
        if close == -1 or close < start:
            js = content[start + 8:]
            js = js.replace('</body>\n</html>', '').rstrip()
        else:
            js = content[start + 8:close]
        return js.strip()
    raise AssertionError("No inline <script> block found")


def test_admin_html_contains_new_views():
    with open('static/admin.html') as f:
        html = f.read()
    # New views exist
    assert 'id="view-operators"' in html
    assert 'id="view-usage"' in html
    assert 'id="view-health"' in html
    assert 'id="view-integrations"' in html
    assert 'id="view-dou-team"' in html


def test_admin_html_contains_new_navigation():
    with open('static/admin.html') as f:
        html = f.read()
    # New nav buttons
    assert 'data-view="operators"' in html
    assert 'data-view="usage"' in html
    assert 'data-view="health"' in html
    assert 'data-view="integrations"' in html
    assert 'data-view="dou-team"' in html


def test_admin_html_contains_kpis():
    with open('static/admin.html') as f:
        html = f.read()
    # KPI elements for new views
    assert 'id="opTotal"' in html
    assert 'id="usageActive"' in html
    assert 'id="healthApi"' in html
    assert 'id="healthDb"' in html


def test_admin_html_contains_company_360():
    with open('static/admin.html') as f:
        html = f.read()
    assert 'id="companyDetail"' in html
    assert 'loadCompanyProfile' in html


def test_admin_html_contains_dou_team():
    with open('static/admin.html') as f:
        html = f.read()
    assert 'id="dtName"' in html
    assert 'id="dtPhone"' in html
    assert 'id="dtRole"' in html
    assert 'inviteDouMember' in html


def test_admin_html_contains_data_tables():
    with open('static/admin.html') as f:
        html = f.read()
    # Tables for new views
    assert 'id="operatorsCompaniesBody"' in html
    assert 'id="usageNearLimitBody"' in html
    assert 'id="healthDataBody"' in html
    assert 'id="integrationsBody"' in html
    assert 'id="douTeamBody"' in html


def test_admin_js_load_functions():
    js = extract_inline_js('static/admin.html')
    # New loader functions
    assert 'async function loadOperators()' in js
    assert 'async function loadUsage()' in js
    assert 'async function loadHealth()' in js
    assert 'async function loadIntegrations()' in js
    assert 'async function loadDouTeam()' in js
    assert 'async function loadCompanyProfile(' in js


def test_admin_js_navigation_list():
    js = extract_inline_js('static/admin.html')
    # New views in navigation
    assert '"operators"' in js
    assert '"usage"' in js
    assert '"health"' in js
    assert '"integrations"' in js
    assert '"dou-team"' in js


def test_admin_js_api_calls():
    js = extract_inline_js('static/admin.html')
    # API calls to new endpoints
    assert '/admin/operators/health' in js
    assert '/admin/usage/summary' in js
    assert '/admin/health/detailed' in js
    assert '/admin/integrations' in js
    assert '/admin/dou-team' in js
    assert '/admin/tenants/' in js
    assert '/profile' in js


def test_admin_js_node_check():
    js = extract_inline_js('static/admin.html')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write(js)
        f.flush()
        result = subprocess.run(['node', '--check', f.name], capture_output=True, text=True)
    os.unlink(f.name)
    assert result.returncode == 0, f"JS syntax error: {result.stderr}"


def test_admin_html_no_legacy_views():
    with open('static/admin.html') as f:
        html = f.read()
    # Legacy views removed from navigation
    assert 'data-view="merchants"' not in html
    assert 'data-view="channels"' not in html
    assert 'data-view="couriers"' not in html
