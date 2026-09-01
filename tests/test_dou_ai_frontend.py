"""Structural smoke tests for DOU AI and Notification Center UI."""

from pathlib import Path

HTML = (Path(__file__).parents[1] / "static" / "fleet.html").read_text(encoding="utf-8")


def test_dou_ai_navigation_and_view_exist():
    assert 'data-view="douai"' in HTML
    assert 'id="view-douai"' in HTML
    assert 'id="aiMessages"' in HTML
    assert 'id="aiInput"' in HTML
    assert "Your intelligent operations assistant." in HTML


def test_dou_ai_workflow_is_wired_to_gateway_only():
    assert "function sendAIMessage" in HTML
    assert "api('/ai/chat'" in HTML
    assert "AI_CONVERSATION_ID" in HTML
    assert "provider_status" not in HTML  # infrastructure details are not rendered
    assert "fetch('http://127.0.0.1:11434" not in HTML
    assert "host.docker.internal:11434" not in HTML


def test_structured_response_rendering_and_failure_states():
    for field in [
        "data.kpis",
        "data.table",
        "data.chart",
        "data.report_link",
        "data.warnings",
        "data.suggested_followups",
        "data.freshness",
    ]:
        assert field in HTML
    assert "aiRetry" in HTML
    assert "checkAIStatus" in HTML


def test_contextual_ai_entry_points_are_curated():
    for view in ["attendance", "performance", "reports"]:
        assert f"openContextualAI('{view}')" in HTML
    assert "function currentAIContext" in HTML


def test_notification_center_workflow_exists():
    """Notifications are accessible via DOU AI or direct URL, not main sidebar."""
    assert 'id="view-notifications"' in HTML
    assert "function loadNotifications" in HTML
    assert "function notificationAction" in HTML
