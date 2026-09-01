"""Minimal frontend smoke tests for W9 Payroll & Financial Operations."""
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


def test_html_contains_payroll_section():
    """Verify W9 payroll section exists in fleet.html."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()

    # Payroll navigation
    assert 'data-view="payouts"' in html, "Payroll navigation button missing"
    
    # Payroll section
    assert 'id="view-payouts"' in html, "Payroll section missing"
    
    # Payroll Summary elements
    assert 'id="payoutsTotal"' in html, "Payroll total missing"
    assert 'id="payoutsBody"' in html, "Payroll table body missing"
    assert 'loadPayroll()' in html, "Payroll loader missing"
    
    # Payroll functions
    assert 'function loadPayouts' in html or 'function loadPayroll' in html, "Payroll load function missing"


def test_javascript_contains_payroll_functions():
    """Verify payroll JavaScript functions are defined."""
    js = _extract_javascript()

    assert 'function loadPayouts' in js or 'function loadPayroll' in js, "loadPayroll/loadPayouts missing"


def test_payroll_loads_on_navigation():
    """Verify payroll loads when navigating to the view."""
    js = _extract_javascript()

    assert "if (view === 'payouts') loadPayouts()" in js or "if (view === 'payroll') loadPayroll()" in js, "Payroll not triggered on navigation"


def test_payroll_shows_loading_state():
    """Verify payroll shows loading state while fetching."""
    js = _extract_javascript()

    assert 'loadPayroll' in js or 'loadPayouts' in js
    assert 'loading' in js.lower(), "Missing loading state in payroll"


def test_payroll_handles_errors():
    """Verify payroll handles API errors gracefully."""
    js = _extract_javascript()

    assert 'catch' in js, "Missing error handling in payroll"
    assert 'error' in js.lower(), "Missing error state in payroll"
