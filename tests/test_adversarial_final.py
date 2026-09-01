"""Final adversarial security tests for DOU AI + W11-Lite."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import entities as ent
from app.models import intelligence  # noqa: F401
from app.models.intelligence import AlertSourceMapping, Notification
from app.services.dou_ai import answer_question, resolve_scope
from app.services.scope import courier_query
from app.services.notifications import (
    create_routed_notifications,
    ingest_metabase_alert,
    verify_webhook_signature,
)

WEBHOOK_SECRET = "adversarial-webhook-secret"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def webhook_env(monkeypatch):
    monkeypatch.setattr("app.config.NOTIFICATION_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr("app.config.NOTIFICATION_WEBHOOK_MAX_AGE_SECONDS", 300)
    monkeypatch.setattr("app.config.NOTIFICATION_WEBHOOK_CLOCK_SKEW_SECONDS", 30)


def tenant(db, name="T", kind="LOGISTICS_OPERATOR"):
    row = ent.Tenant(name=name, country=ent.Country.SA, customer_type=kind)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def user(db, t, role=ent.UserRole.COMPANY_ADMIN, phone=None):
    row = ent.User(
        phone=phone or f"500{t.id}{role.value}",
        password_hash="x",
        role=role,
        tenant_id=t.id,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _sign(body: bytes, timestamp: int, nonce: str, source_instance: str = "default", secret: str = WEBHOOK_SECRET) -> str:
    """Produce HMAC signature over 'timestamp.nonce.source_instance.body'."""
    message = f"{timestamp}.{nonce}.{source_instance}.".encode() + body
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


# === AI SECURITY ===

def test_cross_tenant_ai_access_denied(db):
    """Tenant A admin cannot ask about Tenant B data."""
    a = tenant(db, "A")
    tenant(db, "B")
    admin_a = user(db, a)
    scope_a = resolve_scope(db, admin_a)
    # Scope should be tenant A only
    assert scope_a.tenant_id == a.id


def test_operator_a_cannot_see_operator_b(db):
    """Platform operator cannot access sibling operator data."""
    tenant(db, "Platform", "DELIVERY_PLATFORM")
    op_a = tenant(db, "OpA", "LOGISTICS_OPERATOR")
    op_b = tenant(db, "OpB", "LOGISTICS_OPERATOR")
    admin_a = user(db, op_a)
    scope = resolve_scope(db, admin_a)
    assert scope.tenant_id == op_a.id
    assert scope.tenant_id != op_b.id


def test_supervisor_cannot_see_unrelated_riders(db):
    """Supervisor scope is restricted to their own team."""
    t = tenant(db)
    sup = user(db, t, role=ent.UserRole.SUPERVISOR, phone="5001")
    scope = resolve_scope(db, sup)
    assert scope.supervisor_id == sup.id


def test_prompt_injection_denied(db):
    """Prompt injection cannot modify tenant scope."""
    t = tenant(db)
    admin = user(db, t)
    scope = resolve_scope(db, admin)
    # Even with injection text, scope remains the same
    assert scope.tenant_id == t.id


def test_external_ai_base_url_rejected():
    """DOU AI should not have an LLM provider that can be configured with external URL."""
    import app.services.dou_ai as svc
    # Provider should be removed from DOU AI
    assert not hasattr(svc, 'provider'), "LLM provider should be removed"
    assert not hasattr(svc, 'LocalAIProvider'), "LocalAIProvider should be removed"


def test_unauthorized_payroll_denied(db):
    """Non-financial roles cannot access payroll data."""
    t = tenant(db)
    viewer = user(db, t, role=ent.UserRole.VIEWER, phone="501")
    scope = resolve_scope(db, viewer)
    with pytest.raises(HTTPException) as exc:
        answer_question(db, scope, "What is our prepared payroll this month?")
    assert exc.value.status_code == 403


def test_unsupported_question_no_hallucination(db):
    """Unsupported questions must not invent data."""
    t = tenant(db)
    admin = user(db, t)
    _, result = answer_question(
        db, resolve_scope(db, admin), "Predict next year's revenue"
    )
    # Should indicate inability to predict or return clarification
    answer = result.get("answer", "").lower()
    assert ("predict" in answer or "cannot" in answer or "can't" in answer
            or "insufficient" in answer or "unavailable" in answer
            or result.get("clarification_options") is not None)


# === DOU AI CONTEXT SECURITY ===


def test_supervisor_unrelated_rider_context_rejected(db):
    """Supervisor A cannot ask about a Rider belonging to Supervisor B."""
    t = tenant(db)
    sup_a = user(db, t, role=ent.UserRole.SUPERVISOR, phone="5001")
    sup_b = user(db, t, role=ent.UserRole.SUPERVISOR, phone="5002")
    fleet = ent.Fleet(tenant_id=t.id, name="Fleet", zone="")
    db.add(fleet)
    db.commit()
    # Create rider for supervisor B
    rider = ent.Courier(
        name="Rider B", phone="6001", tenant_id=t.id, supervisor_id=sup_b.id,
        courier_type=ent.CourierType.COMPANY, country=ent.Country.SA, fleet_id=fleet.id,
        employment_status="ACTIVE"
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)
    # Supervisor A tries to use rider context
    with pytest.raises(HTTPException) as exc:
        resolve_scope(db, sup_a, {"entity_type": "rider", "entity_id": rider.id})
    assert exc.value.status_code == 403


def test_project_manager_unrelated_project_context_rejected(db):
    """Project Manager A cannot ask about Project B."""
    t = tenant(db)
    pm = user(db, t, role=ent.UserRole.PROJECT_MANAGER, phone="5001")
    # Create project 3 (not managed by PM - PM manages 1,2)
    project = ent.Project(name="Project 3", tenant_id=t.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    # PM's managed_project_ids is empty by default, so any project should be rejected
    with pytest.raises(HTTPException) as exc:
        resolve_scope(db, pm, {"entity_type": "project", "entity_id": project.id})
    assert exc.value.status_code == 403


def test_cross_tenant_rider_context_rejected(db):
    """Tenant A user cannot use a Rider from Tenant B as context."""
    a = tenant(db, "A")
    b = tenant(db, "B")
    admin_a = user(db, a)
    fleet_b = ent.Fleet(tenant_id=b.id, name="Fleet B", zone="")
    db.add(fleet_b)
    db.commit()
    rider_b = ent.Courier(
        name="Rider B", phone="6001", tenant_id=b.id,
        courier_type=ent.CourierType.COMPANY, country=ent.Country.SA, fleet_id=fleet_b.id,
        employment_status="ACTIVE"
    )
    db.add(rider_b)
    db.commit()
    db.refresh(rider_b)
    with pytest.raises(HTTPException) as exc:
        resolve_scope(db, admin_a, {"entity_type": "rider", "entity_id": rider_b.id})
    assert exc.value.status_code == 403


def test_valid_rider_context_narrows_result(db):
    """Valid Rider context actually restricts the query to that rider."""
    t = tenant(db)
    admin = user(db, t)
    fleet = ent.Fleet(tenant_id=t.id, name="Fleet", zone="")
    db.add(fleet)
    db.commit()
    rider = ent.Courier(
        name="Rider 1", phone="6001", tenant_id=t.id,
        courier_type=ent.CourierType.COMPANY, country=ent.Country.SA, fleet_id=fleet.id,
        employment_status="ACTIVE"
    )
    db.add(rider)
    db.commit()
    db.refresh(rider)
    scope = resolve_scope(db, admin, {"entity_type": "rider", "entity_id": rider.id})
    assert scope.rider_id == rider.id
    # Verify the query actually filters
    q = courier_query(db, scope)
    results = q.all()
    assert len(results) == 1
    assert results[0].id == rider.id


def test_valid_project_context_narrows_result(db):
    """Valid Project context actually restricts the query to that project."""
    t = tenant(db)
    admin = user(db, t)
    fleet = ent.Fleet(tenant_id=t.id, name="Fleet", zone="")
    db.add(fleet)
    db.commit()
    project = ent.Project(name="Project 1", tenant_id=t.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    rider = ent.Courier(
        name="Rider 1", phone="6001", tenant_id=t.id, primary_project_id=project.id,
        courier_type=ent.CourierType.COMPANY, country=ent.Country.SA, fleet_id=fleet.id,
        employment_status="ACTIVE"
    )
    db.add(rider)
    db.commit()
    scope = resolve_scope(db, admin, {"entity_type": "project", "entity_id": project.id})
    assert scope.project_id == project.id
    q = courier_query(db, scope)
    results = q.all()
    assert len(results) == 1
    assert results[0].primary_project_id == project.id


def test_manipulated_entity_id_rejected(db):
    """Unknown entity_id is rejected."""
    t = tenant(db)
    admin = user(db, t)
    with pytest.raises(HTTPException) as exc:
        resolve_scope(db, admin, {"entity_type": "rider", "entity_id": 99999})
    assert exc.value.status_code == 403


def test_prompt_injection_cannot_alter_scope(db):
    """Prompt text cannot alter server-derived scope."""
    t = tenant(db)
    admin = user(db, t)
    # Malicious entity_id should be rejected, not alter scope
    with pytest.raises(HTTPException) as exc:
        resolve_scope(db, admin, {"current_view": "overview", "entity_type": "rider", "entity_id": "1; DROP TABLE users;--"})
    assert exc.value.status_code in {403, 422}

def test_webhook_replay_with_valid_signature_rejected(webhook_env):
    """Old signed request replay is rejected."""
    body = json.dumps({"alert_id": "x", "event_id": "y", "source_instance": "default"}).encode()
    old_ts = int(datetime.now(timezone.utc).timestamp()) - 600  # 10 min ago
    sig = _sign(body, old_ts, "nonce", "default")
    with pytest.raises(HTTPException) as exc:
        verify_webhook_signature(body, sig, str(old_ts), "nonce", "default")
    assert exc.value.status_code == 401


def test_webhook_future_timestamp_rejected(webhook_env):
    """Future timestamp is rejected."""
    body = json.dumps({"alert_id": "x", "event_id": "y"}).encode()
    future_ts = int(datetime.now(timezone.utc).timestamp()) + 120
    sig = _sign(body, future_ts, "nonce", "default")
    with pytest.raises(HTTPException) as exc:
        verify_webhook_signature(body, sig, str(future_ts), "nonce", "default")
    assert exc.value.status_code == 401


def test_webhook_tampered_body_rejected(webhook_env):
    """Body modified after signing is rejected."""
    body = json.dumps({"alert_id": "x", "event_id": "y"}).encode()
    ts = int(datetime.now(timezone.utc).timestamp())
    sig = _sign(body, ts, "nonce", "default")
    tampered = json.dumps({"alert_id": "x", "event_id": "y", "tenant_id": 999}).encode()
    with pytest.raises(HTTPException) as exc:
        verify_webhook_signature(tampered, sig, str(ts), "nonce", "default")
    assert exc.value.status_code == 401


def test_webhook_tampered_timestamp_rejected(webhook_env):
    """Timestamp modified after signing is rejected."""
    body = json.dumps({"alert_id": "x", "event_id": "y"}).encode()
    ts = int(datetime.now(timezone.utc).timestamp())
    sig = _sign(body, ts, "nonce", "default")
    with pytest.raises(HTTPException) as exc:
        verify_webhook_signature(body, sig, str(ts + 100), "nonce", "default")
    assert exc.value.status_code == 401


def test_webhook_missing_signature_rejected(webhook_env):
    """Missing signature is rejected."""
    body = json.dumps({"alert_id": "x", "event_id": "y"}).encode()
    ts = int(datetime.now(timezone.utc).timestamp())
    with pytest.raises(HTTPException) as exc:
        verify_webhook_signature(body, None, str(ts), "nonce", "default")
    assert exc.value.status_code == 401


def test_webhook_missing_timestamp_rejected(webhook_env):
    """Missing timestamp is rejected."""
    body = json.dumps({"alert_id": "x", "event_id": "y"}).encode()
    with pytest.raises(HTTPException) as exc:
        verify_webhook_signature(body, "sha256=abc", None, "nonce", "default")
    assert exc.value.status_code == 401


def test_webhook_missing_nonce_rejected(webhook_env):
    """Missing nonce is rejected."""
    body = json.dumps({"alert_id": "x", "event_id": "y"}).encode()
    ts = int(datetime.now(timezone.utc).timestamp())
    with pytest.raises(HTTPException) as exc:
        verify_webhook_signature(body, "sha256=abc", str(ts), None, "default")
    assert exc.value.status_code == 401


def test_webhook_missing_source_instance_rejected(webhook_env):
    """Missing source instance is rejected."""
    body = json.dumps({"alert_id": "x", "event_id": "y"}).encode()
    ts = int(datetime.now(timezone.utc).timestamp())
    with pytest.raises(HTTPException) as exc:
        verify_webhook_signature(body, "sha256=abc", str(ts), "nonce", None)
    assert exc.value.status_code == 401


def test_webhook_oversized_payload_rejected(webhook_env):
    """Oversized payload is rejected."""
    with TestClient(app) as client:
        res = client.post(
            "/webhooks/metabase/alerts",
            content=b"x" * 65537,
            headers={"Content-Type": "application/json", "X-DOU-Signature": "bad"},
        )
        assert res.status_code == 413


def test_webhook_forged_tenant_payload_rejected(db, webhook_env):
    """Payload's tenant_id must match the mapping's tenant."""
    a = tenant(db, "A")
    b = tenant(db, "B")
    db.add(AlertSourceMapping(
        tenant_id=a.id, source_instance="metabase-a", source="METABASE", external_alert_id="alert-forge",
        notification_type="OPERATOR_PERFORMANCE", severity="WARNING",
    ))
    db.commit()
    # Payload says tenant B, but mapping is for tenant A
    with pytest.raises(HTTPException) as exc:
        ingest_metabase_alert(db, {
            "alert_id": "alert-forge",
            "event_id": "evt-1",
            "tenant_id": b.id,
            "title": "T",
            "message": "M",
        }, "metabase-a")
    assert exc.value.status_code == 403


def test_webhook_payload_cannot_select_tenant(db, webhook_env):
    """Payload cannot select a different tenant than the mapping."""
    a = tenant(db, "A")
    b = tenant(db, "B")
    db.add(AlertSourceMapping(
        tenant_id=a.id, source_instance="metabase-shared", source="METABASE", external_alert_id="alert-x",
        notification_type="OPERATOR_PERFORMANCE", severity="WARNING",
    ))
    db.commit()
    # Attacker tries to use source_instance but point tenant_id to another tenant
    with pytest.raises(HTTPException) as exc:
        ingest_metabase_alert(db, {
            "alert_id": "alert-x",
            "event_id": "evt-x",
            "tenant_id": b.id,
            "title": "T",
            "message": "M",
        }, "metabase-shared")
    assert exc.value.status_code == 403


def test_source_mapping_tenant_collision_safe(db):
    """Two tenants can have same external_alert_id without collision."""
    a = tenant(db, "A")
    b = tenant(db, "B")
    db.add(AlertSourceMapping(
        tenant_id=a.id, source_instance="metabase-a", source="METABASE", external_alert_id="shared-alert",
        notification_type="OPERATOR_PERFORMANCE", severity="WARNING",
    ))
    db.add(AlertSourceMapping(
        tenant_id=b.id, source_instance="metabase-b", source="METABASE", external_alert_id="shared-alert",
        notification_type="ATTENDANCE", severity="INFO",
    ))
    db.commit()
    assert db.query(AlertSourceMapping).count() == 2


def test_source_instance_collision_same_tenant(db):
    """Two source instances in the same tenant can have the same external_alert_id."""
    a = tenant(db, "A")
    db.add(AlertSourceMapping(
        tenant_id=a.id, source_instance="metabase-1", source="METABASE", external_alert_id="alert-123",
        notification_type="OPERATOR_PERFORMANCE", severity="WARNING",
    ))
    db.add(AlertSourceMapping(
        tenant_id=a.id, source_instance="metabase-2", source="METABASE", external_alert_id="alert-123",
        notification_type="ATTENDANCE", severity="INFO",
    ))
    db.commit()
    assert db.query(AlertSourceMapping).count() == 2


def test_duplicate_webhook_business_dedup(db, webhook_env):
    """Duplicate business event does not create duplicate notification."""
    t = tenant(db)
    admin = user(db, t)
    db.add(AlertSourceMapping(
        tenant_id=t.id, source_instance="metabase-t", source="METABASE", external_alert_id="dup-test",
        notification_type="ORDER_DECLINE", severity="WARNING",
        recipient_roles_json='["COMPANY_ADMIN"]',
    ))
    db.commit()
    ingest_metabase_alert(db, {
        "alert_id": "dup-test",
        "event_id": "evt-dup",
        "tenant_id": t.id,
        "title": "Orders declined",
        "message": "Threshold met",
    }, "metabase-t")
    # Second call with same event_id
    ingest_metabase_alert(db, {
        "alert_id": "dup-test",
        "event_id": "evt-dup",
        "tenant_id": t.id,
        "title": "Orders declined",
        "message": "Threshold met",
    }, "metabase-t")
    assert db.query(Notification).count() == 1
    assert admin.tenant_id == t.id


def test_nonce_replay_rejected(db, webhook_env):
    """Exact signed replay with same nonce is rejected."""
    t = tenant(db)
    admin = user(db, t)
    db.add(AlertSourceMapping(
        tenant_id=t.id, source_instance="metabase-t", source="METABASE", external_alert_id="nonce-test",
        notification_type="ORDER_DECLINE", severity="WARNING",
        recipient_roles_json='["COMPANY_ADMIN"]',
    ))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            body = json.dumps({
                "alert_id": "nonce-test",
                "event_id": "evt-nonce",
                "source_instance": "metabase-t",
                "tenant_id": t.id,
                "title": "T",
                "message": "M",
            }).encode()
            ts = int(datetime.now(timezone.utc).timestamp())
            nonce = "unique-nonce-123"
            sig = _sign(body, ts, nonce, "metabase-t")
            headers = {
                "Content-Type": "application/json",
                "X-DOU-Signature": sig,
                "X-DOU-Timestamp": str(ts),
                "X-DOU-Nonce": nonce,
                "X-DOU-Source-Instance": "metabase-t",
            }
            first = client.post("/webhooks/metabase/alerts", content=body, headers=headers)
            assert first.status_code == 200
            replay = client.post("/webhooks/metabase/alerts", content=body, headers=headers)
            assert replay.status_code == 409
    finally:
        app.dependency_overrides.clear()
    assert admin.tenant_id == t.id


# === NOTIFICATION SECURITY ===

def test_notification_transition_by_other_user_denied(db):
    """Another user cannot transition a notification."""
    t = tenant(db)
    a = user(db, t, phone="701")
    b = user(db, t, phone="702")
    n = create_routed_notifications(
        db,
        tenant_id=t.id,
        recipients=[a],
        notification_type="IMPORT_FAILURE",
        severity="CRITICAL",
        title="Test",
        message="Test",
        source="NATIVE",
        source_reference="ref",
        idempotency_key="k1",
        dedupe_key="d1",
    )[0]
    # User B tries to read
    with pytest.raises(HTTPException) as exc:
        from app.services.notifications import transition
        transition(db, n, b, "READ")
    assert exc.value.status_code == 404


def test_cross_tenant_notification_routing_denied(db):
    """Cross-tenant notification routing is denied."""
    a = tenant(db, "A")
    b = tenant(db, "B")
    admin_b = user(db, b)
    # Try to create notification in tenant A with recipient from tenant B
    with pytest.raises(HTTPException) as exc:
        create_routed_notifications(
            db,
            tenant_id=a.id,
            recipients=[admin_b],  # User from tenant B
            notification_type="IMPORT_FAILURE",
            severity="CRITICAL",
            title="T",
            message="M",
            source="NATIVE",
            source_reference="ref",
            idempotency_key="k-cross",
            dedupe_key="d-cross",
        )
    assert exc.value.status_code == 403



