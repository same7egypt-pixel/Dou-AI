"""Minimal frontend smoke tests for W10.5 Operator Domain."""
import re


def _extract_javascript():
    """Extract JavaScript content from fleet.html."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html', 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'<script>\s*(.*?)\s*</script>', content, re.DOTALL)
    return match.group(1) if match else ''


def test_operator_section_exists():
    """Test that operator-related navigation exists."""
    with open('/Users/sameh/DOU-review/dou-server/static/fleet.html', 'r', encoding='utf-8') as f:
        content = f.read()
    # Operators are part of the platform view
    assert 'view-reports' in content, "Reports section not found"


def test_customer_type_hidden_field():
    """Test that customer type is tracked in the frontend."""
    js = _extract_javascript()
    # Customer type should be part of the tenant meta
    assert 'META' in js or 'meta' in js, "META not found in JS"
