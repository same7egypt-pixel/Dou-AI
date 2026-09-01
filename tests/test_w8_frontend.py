"""Minimal frontend smoke tests for W8 Performance Management (now in Rider 360)."""
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


def test_html_contains_performance_section():
    """Verify W8 performance section exists in Rider 360 tabs."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()

    # Performance is now in Rider 360 tabs
    assert 'data-r360tab="performance"' in html, "Performance tab missing in Rider 360"
    assert 'id="rider360Tab-performance"' in html, "Performance tab content missing"
    
    # Performance functions
    assert 'loadR360Performance' in html, "loadR360Performance function missing"
    assert '/analytics/performance/scorecard' in html, "Performance scorecard API missing"


def test_performance_loads_data_from_api():
    """Verify performance loads data from real backend APIs."""
    js = _extract_javascript()
    
    assert 'loadR360Performance' in js, "loadR360Performance function missing"
    assert '/analytics/performance/scorecard' in js, "Performance scorecard API missing"


def test_performance_has_targets_tab():
    """Verify performance has targets sub-section."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html') as f:
        html = f.read()
    
    assert 'data-r360tab="targets"' in html, "Targets tab missing"
    assert 'id="rider360Tab-targets"' in html, "Targets tab content missing"
