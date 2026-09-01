"""Structural smoke tests for Batch 2/3 operational views in fleet.html."""
import os
from pathlib import Path
import subprocess
import tempfile


HTML_PATH = Path("static/fleet.html")


def html():
    return HTML_PATH.read_text()


def test_rider_360_view_is_wired():
    source = html()
    # Rider 360 is opened from Riders list, not from sidebar nav
    assert 'id="view-rider360"' in source
    assert 'id="rider360Select"' in source
    assert 'id="rider360Content"' in source
    assert 'async function loadRider360(preferredId)' in source
    assert '/analytics/riders/' in source
    assert '/profile' in source
    assert 'data-r360tab="profile"' in source


def test_attendance_corrections_view_is_wired():
    """Attendance corrections now live inside Rider 360 Attendance tab."""
    source = html()
    assert 'id="view-rider360"' in source
    assert 'correctRiderAttendance' in source
    assert '/analytics/attendance/corrections' in source


def test_capacity_management_view_is_wired():
    source = html()
    assert 'data-view="capacity"' in source
    assert 'id="view-capacity"' in source
    assert 'id="capacityRequired"' in source
    assert 'id="capacityShortage"' in source
    assert 'id="capacityScopeType"' in source
    assert 'async function loadCapacity()' in source
    assert 'async function saveCapacityRequirement()' in source
    assert '/analytics/capacity/status' in source
    assert '/analytics/capacity/requirements' in source


def test_data_health_view_is_wired():
    """Data health is now accessible via Reports or hidden section."""
    source = html()
    assert 'id="view-dataHealth"' in source
    assert '/analytics/data-health' in source


def test_needs_attention_view_is_wired():
    source = html()
    assert 'data-view="needsAttention"' in source
    assert 'id="view-needsAttention"' in source
    assert 'id="needsAttentionTotal"' in source
    assert 'id="needsAttentionList"' in source
    assert 'async function loadNeedsAttention()' in source
    assert '/analytics/needs-attention/deterministic' in source


def test_new_views_are_registered_in_navigation():
    source = html()
    navigation = ['rider360', 'capacity', 'needsAttention']
    for view in navigation:
        assert f'if(v==="{view}")' in source
        assert f"'{view}'" in source[source.find("const safeViews="):source.find("const safeViews=") + 500]


def test_fleet_inline_javascript_parses_with_node():
    source = html()
    start = source.find("<script>")
    assert start >= 0
    end = source.rfind("</script>")
    javascript = source[start + len("<script>"):end if end > start else None]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as handle:
        handle.write(javascript)
        path = handle.name
    try:
        result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    finally:
        os.unlink(path)
    assert result.returncode == 0, result.stderr


def test_rider_360_not_in_sidebar():
    """Rider 360 is NOT in sidebar nav - opened from Riders list."""
    source = html()
    sidebar_end = source.find('<div class="overlay"')
    sidebar = source[:sidebar_end] if sidebar_end > 0 else source
    assert 'data-view="rider360"' not in sidebar


def test_rider_360_has_8_tabs():
    """Rider 360 has proper tab structure per Prodstack."""
    source = html()
    tabs = ['profile', 'documents', 'shifts', 'attendance', 'performance', 'targets', 'payroll', 'leave']
    for tab in tabs:
        assert f'data-r360tab="{tab}"' in source, f"Tab {tab} missing"


def test_openCourier360_navigates_to_rider360():
    """openCourier360 function opens Rider 360 view."""
    source = html()
    assert 'function openCourier360' in source
    assert 'go("rider360")' in source
