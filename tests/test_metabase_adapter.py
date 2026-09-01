"""Tests for Metabase adapter boundary."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi import HTTPException

from app.services.metabase_adapter import (
    MetabaseConfig,
    check_metabase_available,
    execute_approved_question,
    to_structured_response,
)
from app.services.metabase_registry import (
    MetabaseQuestion,
    register_question,
)


@pytest.fixture(autouse=True)
def clear_registry():
    from app.services.metabase_registry import APPROVED_QUESTIONS

    original = APPROVED_QUESTIONS.copy()
    APPROVED_QUESTIONS.clear()
    yield
    APPROVED_QUESTIONS.clear()
    APPROVED_QUESTIONS.update(original)


@pytest.fixture
def config():
    return MetabaseConfig(
        base_url="http://localhost:3000",
        api_key="test-api-key",
        username=None,
        password=None,
        database_id=1,
        timeout_seconds=5,
    )


@pytest.fixture
def scope():
    from app.services.scope import AuthorizedScope

    return AuthorizedScope(
        tenant_id=1,
        customer_type="LOGISTICS_OPERATOR",
        user_id=1,
        role="COMPANY",
    )


def test_unapproved_question_rejected(config, scope):
    """Unapproved question IDs are rejected."""
    with pytest.raises(HTTPException) as exc:
        execute_approved_question(config, 99999, {}, scope)
    assert exc.value.status_code == 422


def test_unauthorized_role_rejected(config, scope):
    """Unauthorized roles are rejected."""
    register_question(
        MetabaseQuestion(
            question_id=100,
            name="Test Question",
            description="Test",
            collection_id=None,
            database_id=1,
            allowed_roles=["DOU_ADMIN"],
            allowed_filters=["tenant_id"],
            allowed_customer_types=["LOGISTICS_OPERATOR"],
        )
    )
    with pytest.raises(HTTPException) as exc:
        execute_approved_question(config, 100, {}, scope)
    assert exc.value.status_code == 403


def test_unauthorized_customer_type_rejected(config, scope):
    """Unauthorized customer types are rejected."""
    register_question(
        MetabaseQuestion(
            question_id=100,
            name="Test Question",
            description="Test",
            collection_id=None,
            database_id=1,
            allowed_roles=["COMPANY"],
            allowed_filters=["tenant_id"],
            allowed_customer_types=["DELIVERY_PLATFORM"],
        )
    )
    with pytest.raises(HTTPException) as exc:
        execute_approved_question(config, 100, {}, scope)
    assert exc.value.status_code == 403


def test_unapproved_filter_rejected(config, scope):
    """Unapproved filters are rejected."""
    register_question(
        MetabaseQuestion(
            question_id=100,
            name="Test Question",
            description="Test",
            collection_id=None,
            database_id=1,
            allowed_roles=["COMPANY"],
            allowed_filters=["tenant_id"],
            allowed_customer_types=["LOGISTICS_OPERATOR"],
        )
    )
    with pytest.raises(HTTPException) as exc:
        execute_approved_question(config, 100, {"unauthorized_filter": "x"}, scope)
    assert exc.value.status_code == 422


def test_approved_question_executes(config, scope):
    """Approved questions execute with validated parameters."""
    register_question(
        MetabaseQuestion(
            question_id=100,
            name="Test Question",
            description="Test",
            collection_id=None,
            database_id=1,
            allowed_roles=["COMPANY"],
            allowed_filters=["tenant_id"],
            allowed_customer_types=["LOGISTICS_OPERATOR"],
        )
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "cols": [{"name": "count"}],
            "rows": [[42]],
        }
    }

    with patch("app.services.metabase_adapter.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session_cls.return_value = mock_session

        result = execute_approved_question(config, 100, {"tenant_id": 1}, scope)

    assert result["source"] == "METABASE"
    assert result["question_id"] == 100
    assert result["row_count"] == 1
    assert result["rows"] == [{"count": 42}]


def test_metabase_unavailable_raises_503(config, scope):
    """Metabase unavailability raises 503."""
    register_question(
        MetabaseQuestion(
            question_id=100,
            name="Test Question",
            description="Test",
            collection_id=None,
            database_id=1,
            allowed_roles=["COMPANY"],
            allowed_filters=["tenant_id"],
            allowed_customer_types=["LOGISTICS_OPERATOR"],
        )
    )

    with patch("app.services.metabase_adapter.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.post.side_effect = requests.ConnectionError("Connection refused")
        mock_session_cls.return_value = mock_session

        with pytest.raises(HTTPException) as exc:
            execute_approved_question(config, 100, {}, scope)
    assert exc.value.status_code == 503


def test_check_metabase_available(config):
    """Health check returns True when Metabase is reachable."""
    with patch("app.services.metabase_adapter.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_session_cls.return_value = mock_session

        assert check_metabase_available(config) is True


def test_check_metabase_unavailable(config):
    """Health check returns False when Metabase is unreachable."""
    with patch("app.services.metabase_adapter.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("Connection refused")
        mock_session_cls.return_value = mock_session

        assert check_metabase_available(config) is False


def test_check_metabase_no_config():
    """Health check returns False when no config."""
    assert check_metabase_available(None) is False


def test_forged_tenant_parameter_is_overwritten(config, scope):
    """The authenticated tenant, never caller input, reaches Metabase."""
    register_question(MetabaseQuestion(
        question_id=100, name="Scoped", description="Test", collection_id=None,
        database_id=1, allowed_roles=["COMPANY"], allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR"],
    ))
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": {"cols": [], "rows": []}}
    with patch("app.services.metabase_adapter.requests.Session") as session_cls:
        session = MagicMock()
        session.post.return_value = response
        session_cls.return_value = session
        execute_approved_question(config, 100, {"tenant_id": 999}, scope)
    payload = session.post.call_args.kwargs["json"]
    assert payload["parameters"][0]["value"] == scope.tenant_id


def test_supervisor_question_must_support_supervisor_scope(config, scope):
    """A scoped account cannot execute a tenant-wide Saved Question."""
    scope.role = "SUPERVISOR"
    scope.supervisor_id = 77
    register_question(MetabaseQuestion(
        question_id=100, name="Tenant only", description="Test", collection_id=None,
        database_id=1, allowed_roles=["SUPERVISOR"], allowed_filters=["tenant_id"],
        allowed_customer_types=["LOGISTICS_OPERATOR"],
    ))
    with pytest.raises(HTTPException) as exc:
        execute_approved_question(config, 100, {}, scope)
    assert exc.value.status_code == 500


def test_structured_response_contains_kpi_table_chart_and_metadata():
    raw = {
        "columns": ["operator", "orders"],
        "rows": [{"operator": "A", "orders": 7}],
        "freshness": "2026-01-01T00:00:00Z",
    }
    result = to_structured_response(raw, "/app?view=operators")
    assert result["table"]["rows"] == raw["rows"]
    assert result["chart"]["series"][0]["data"] == [7]
    assert result["kpis"] == [{"label": "orders", "value": 7}]
    assert result["freshness"] == raw["freshness"]
    assert result["report_link"].startswith("/app?")
