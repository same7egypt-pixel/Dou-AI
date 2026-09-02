"""Metabase adapter for approved Saved Questions only.

This adapter executes ONLY pre-registered Metabase Saved Questions.
Browser clients cannot supply arbitrary question IDs, SQL, or query plans.
All DOU scope enforcement happens BEFORE any Metabase call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import HTTPException

from .metabase_registry import get_question

logger = logging.getLogger(__name__)


@dataclass
class MetabaseConfig:
    base_url: str
    api_key: str | None
    username: str | None
    password: str | None
    database_id: int | None
    timeout_seconds: int = 30


def get_metabase_config() -> MetabaseConfig | None:
    """Read Metabase configuration from environment."""
    import os

    base_url = os.getenv("METABASE_URL", "").rstrip("/")
    if not base_url:
        return None

    return MetabaseConfig(
        base_url=base_url,
        api_key=os.getenv("METABASE_API_KEY") or None,
        username=os.getenv("METABASE_USERNAME") or None,
        password=os.getenv("METABASE_PASSWORD") or None,
        database_id=int(os.getenv("METABASE_DATABASE_ID", "0")) or None,
        timeout_seconds=int(os.getenv("METABASE_TIMEOUT_SECONDS", "30")),
    )


def _get_session(config: MetabaseConfig) -> requests.Session:
    """Create authenticated requests session."""
    session = requests.Session()

    if config.api_key:
        session.headers["X-Api-Key"] = config.api_key
        return session

    if config.username and config.password:
        # Session-based auth
        response = session.post(
            f"{config.base_url}/api/session",
            json={"username": config.username, "password": config.password},
            timeout=config.timeout_seconds,
        )
        if response.status_code != 200:
            raise HTTPException(502, "Metabase authentication failed")
        session.headers["X-Metabase-Session"] = response.json().get("id", "")
        return session

    raise HTTPException(502, "Metabase authentication not configured")


def execute_approved_question(
    config: MetabaseConfig,
    question_id: int,
    parameters: dict[str, Any],
    scope: Any,
) -> dict[str, Any]:
    """Execute an approved Metabase question with validated parameters."""
    question = get_question(question_id)
    if not question:
        raise HTTPException(422, "Metabase question is not approved")

    # Validate scope
    if scope.role not in question.allowed_roles:
        raise HTTPException(403, "Question not available for this role")
    if scope.customer_type not in question.allowed_customer_types:
        raise HTTPException(403, "Question not available for this customer type")

    # Scope dimensions are server-derived and cannot be overridden by callers.
    authoritative_scope = {"tenant_id": scope.tenant_id}
    if scope.operator_id is not None:
        authoritative_scope["operator_id"] = scope.operator_id
    if scope.supervisor_id is not None:
        authoritative_scope["supervisor_id"] = scope.supervisor_id
    if scope.project_id is not None:
        authoritative_scope["project_id"] = scope.project_id
    if scope.project_ids is not None:
        authoritative_scope["project_ids"] = list(scope.project_ids)

    required = set(question.required_scope_filters)
    if scope.operator_id is not None:
        required.add("operator_id")
    if scope.supervisor_id is not None:
        required.add("supervisor_id")
    if scope.project_id is not None:
        required.add("project_id")
    if scope.project_ids is not None:
        required.add("project_ids")
    if not required.issubset(set(question.allowed_filters)):
        raise HTTPException(
            500, "Approved Metabase question lacks required scope filters"
        )

    # Validate caller-selectable parameters; authoritative values always win.
    for key in parameters:
        if key not in question.allowed_filters:
            raise HTTPException(422, f"Parameter not approved: {key}")
    parameters = {**parameters, **{key: authoritative_scope[key] for key in required}}

    # Build card execution payload
    # Only allow structured query with template tags
    payload = {
        "parameters": [
            {
                "type": "category",
                "target": ["variable", ["template-tag", key]],
                "value": value,
            }
            for key, value in parameters.items()
        ],
        "ignore_cache": False,
    }

    session = _get_session(config)
    url = f"{config.base_url}/api/card/{question_id}/query"

    try:
        response = session.post(
            url,
            json=payload,
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.warning("Metabase query failed: %s", exc)
        raise HTTPException(503, "Metabase is unavailable")

    if response.status_code == 401:
        raise HTTPException(502, "Metabase authentication expired")
    if response.status_code == 404:
        raise HTTPException(422, "Metabase question not found")
    if response.status_code != 200:
        raise HTTPException(502, f"Metabase query failed: {response.status_code}")

    data = response.json()

    # Parse Metabase result format
    columns = [
        col.get("name", f"col_{i}")
        for i, col in enumerate(data.get("data", {}).get("cols", []))
    ]
    rows = []
    for row in data.get("data", {}).get("rows", []):
        rows.append(dict(zip(columns, row)))

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "source": "METABASE",
        "question_id": question_id,
        "question_name": question.name,
        "freshness": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }


def to_structured_response(
    raw: dict[str, Any], report_link: str | None
) -> dict[str, Any]:
    """Convert a Saved Question result to the DOU AI response contract."""
    rows = raw["rows"]
    columns = raw["columns"]
    kpis = []
    if len(rows) == 1:
        for key, value in rows[0].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                kpis.append({"label": key, "value": value})
    chart = None
    if rows and len(columns) >= 2:
        chart = {
            "type": "bar",
            "labels": [str(row.get(columns[0], "")) for row in rows],
            "series": [
                {"name": columns[1], "data": [row.get(columns[1]) for row in rows]}
            ],
        }
    return {
        "answer": f"The approved analytics report returned {len(rows)} row(s).",
        "kpis": kpis,
        "table": {"columns": columns, "rows": rows},
        "chart": chart,
        "report_link": report_link,
        "source": "Approved Metabase Saved Question",
        "freshness": raw["freshness"],
        "warnings": [],
        "suggested_followups": [],
    }


def check_metabase_available(config: MetabaseConfig | None) -> bool:
    """Check if Metabase is reachable."""
    if not config:
        return False
    try:
        session = _get_session(config)
        response = session.get(
            f"{config.base_url}/api/health",
            timeout=min(config.timeout_seconds, 5),
        )
        return response.status_code == 200
    except requests.RequestException:
        return False
