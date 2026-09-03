"""Secure, deterministic DOU AI orchestration.

Authorization is applied to SQLAlchemy queries before any aggregate context
can reach a report executor. All operational questions are answered
deterministically so operational figures are never model-generated.

DOU AI is now a Deterministic Conversational BI layer.
No LLM is used in the normal runtime path.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import entities as ent
from ..models.intelligence import AIConversation, AIMessage, AIRequestLog
from .conversational_parser import (
    generate_clarification_options,
    is_ambiguous,
    parse_question,
)
from .entitlements import capabilities_for
from .report_executor import execute_report
from .report_registry import validate_registered_report
from .reportspec import ReportSpec, default_period_for, validate_spec_against_scope
from .scope import AuthorizedScope


def _role_value(user: ent.User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def resolve_scope(
    db: Session, user: ent.User, page_context: dict | None = None
) -> AuthorizedScope:
    """Build scope exclusively from authenticated identity, then validate context."""
    if not user.tenant_id:
        raise HTTPException(403, "DOU AI requires a tenant-scoped account")
    tenant = db.get(ent.Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(403, "Tenant scope is unavailable")
    role = _role_value(user)
    allowed_roles = {
        "DOU_ADMIN",
        "COMPANY",
        "COMPANY_ADMIN",
        "OPERATIONS",
        "HR",
        "ACCOUNTANT",
        "VIEWER",
        "SUPERVISOR",
        "PROJECT_MANAGER",
    }
    if role not in allowed_roles:
        raise HTTPException(
            403, "DOU AI operations access is not available for this role"
        )

    raw_ct = (tenant.customer_type or "LOGISTICS_OPERATOR").upper()
    if "PLATFORM" in raw_ct:
        canonical_ct = "DELIVERY_PLATFORM"
    else:
        canonical_ct = "LOGISTICS_OPERATOR"

    scope = AuthorizedScope(
        tenant_id=user.tenant_id,
        customer_type=canonical_ct,
        user_id=user.id,
        role=role,
        supervisor_id=user.id if role == "SUPERVISOR" else None,
        capabilities=frozenset(capabilities_for(tenant)),
    )
    if role == "PROJECT_MANAGER":
        try:
            scope.project_ids = [
                int(v) for v in json.loads(user.managed_project_ids or "[]")
            ]
        except (ValueError, TypeError, json.JSONDecodeError):
            scope.project_ids = []

    context = page_context or {}

    requested_operator = context.get("operator_id")
    if requested_operator is not None:
        try:
            requested_operator = int(requested_operator)
        except (TypeError, ValueError):
            raise HTTPException(422, "Invalid Operator context")
        if scope.customer_type != "DELIVERY_PLATFORM":
            raise HTTPException(
                403, "Operator context is only valid for delivery platforms"
            )
        linked = (
            db.query(ent.PlatformOperator.id)
            .filter(
                ent.PlatformOperator.tenant_id == scope.tenant_id,
                ent.PlatformOperator.operator_tenant_id == requested_operator,
                ent.PlatformOperator.is_active.is_(True),
            )
            .first()
        )
        if not linked:
            raise HTTPException(
                403, "Operator is outside your authorized platform scope"
            )
        scope.operator_id = requested_operator

    requested_supervisor = context.get("supervisor_id")
    if requested_supervisor is not None:
        try:
            requested_supervisor = int(requested_supervisor)
        except (TypeError, ValueError):
            raise HTTPException(422, "Invalid supervisor context")
        if scope.supervisor_id and requested_supervisor != scope.supervisor_id:
            raise HTTPException(403, "Supervisor context cannot expand team scope")
        supervisor = (
            db.query(ent.User.id)
            .filter(
                ent.User.id == requested_supervisor,
                ent.User.tenant_id == scope.tenant_id,
                ent.User.role == ent.UserRole.SUPERVISOR,
                ent.User.is_active.is_(True),
            )
            .first()
        )
        if not supervisor:
            raise HTTPException(403, "Supervisor is outside your authorized scope")
        scope.supervisor_id = requested_supervisor

    requested_rider = context.get("entity_id")
    if requested_rider is not None and context.get("entity_type") == "rider":
        try:
            requested_rider = int(requested_rider)
        except (TypeError, ValueError):
            raise HTTPException(422, "Invalid rider context")
        rider = (
            db.query(ent.Courier)
            .filter(
                ent.Courier.id == requested_rider,
                ent.Courier.tenant_id == scope.tenant_id,
            )
            .first()
        )
        if not rider:
            raise HTTPException(403, "Rider is outside your authorized tenant scope")
        if scope.supervisor_id and rider.supervisor_id != scope.supervisor_id:
            raise HTTPException(403, "Rider is outside your authorized team scope")
        if (
            scope.project_ids is not None
            and rider.primary_project_id not in scope.project_ids
        ):
            raise HTTPException(403, "Rider is outside your authorized project scope")
        scope.rider_id = requested_rider

    requested_project = context.get("entity_id")
    if requested_project is not None and context.get("entity_type") == "project":
        try:
            requested_project = int(requested_project)
        except (TypeError, ValueError):
            raise HTTPException(422, "Invalid project context")
        project = (
            db.query(ent.Project)
            .filter(
                ent.Project.id == requested_project,
                ent.Project.tenant_id == scope.tenant_id,
            )
            .first()
        )
        if not project:
            raise HTTPException(403, "Project is outside your authorized tenant scope")
        if scope.project_ids is not None and requested_project not in scope.project_ids:
            raise HTTPException(403, "Project is outside your authorized scope")
        scope.project_id = requested_project

    requested_city = context.get("city_id")
    if requested_city is not None:
        try:
            requested_city = int(requested_city)
        except (TypeError, ValueError):
            raise HTTPException(422, "Invalid city context")
        city = db.get(ent.GeoCity, requested_city)
        if not city:
            raise HTTPException(403, "City is not recognized")
        scope.city_id = requested_city

    return scope


def _resolve_city_alias(db: Session, scope: AuthorizedScope, alias: str) -> int:
    rows = (
        db.query(ent.GeoCity.id)
        .join(
            ent.TenantOperatingCity,
            ent.TenantOperatingCity.geo_city_id == ent.GeoCity.id,
        )
        .filter(
            ent.TenantOperatingCity.tenant_id == scope.tenant_id,
            ent.TenantOperatingCity.is_active.is_(True),
            ent.GeoCity.active.is_(True),
            func.lower(ent.GeoCity.name) == alias.casefold(),
        )
        .all()
    )
    if not rows:
        raise HTTPException(422, f"Unknown or inactive city: {alias}")
    if len(rows) > 1:
        raise HTTPException(409, f"Ambiguous city: {alias}")
    return rows[0][0]


def _normalize_filters(db: Session, scope: AuthorizedScope, spec: ReportSpec) -> None:
    """Resolve names and validate every entity filter inside the tenant."""
    alias = spec.filters.pop("city_alias", None)
    if alias is not None:
        if not isinstance(alias, str):
            raise HTTPException(422, "Invalid city alias")
        spec.filters["city_id"] = _resolve_city_alias(db, scope, alias)

    validators = {
        "city_id": (ent.TenantOperatingCity, ent.TenantOperatingCity.geo_city_id),
        "branch_id": (ent.ContractBranch, ent.ContractBranch.id),
        "project_id": (ent.Project, ent.Project.id),
        "supervisor_id": (ent.User, ent.User.id),
        "rider_id": (ent.Courier, ent.Courier.id),
    }
    for name, (model, column) in validators.items():
        value = spec.filters.get(name)
        if value is None:
            continue
        query = db.query(column).filter(column == value)
        if hasattr(model, "tenant_id"):
            query = query.filter(model.tenant_id == scope.tenant_id)
        if name == "city_id":
            query = query.filter(ent.TenantOperatingCity.tenant_id == scope.tenant_id)
        if name == "supervisor_id":
            query = query.filter(
                ent.User.role == ent.UserRole.SUPERVISOR, ent.User.is_active.is_(True)
            )
        if not query.first():
            raise HTTPException(403, f"{name} is outside authenticated tenant scope")

    operator_id = spec.filters.get("operator_id")
    if operator_id is not None:
        linked = (
            db.query(ent.PlatformOperator.id)
            .filter(
                ent.PlatformOperator.tenant_id == scope.tenant_id,
                ent.PlatformOperator.operator_tenant_id == operator_id,
                ent.PlatformOperator.is_active.is_(True),
            )
            .first()
        )
        if scope.customer_type != "DELIVERY_PLATFORM" or not linked:
            raise HTTPException(
                403, "Operator filter is outside authenticated platform scope"
            )


def _narrow_scope(scope: AuthorizedScope, spec: ReportSpec) -> AuthorizedScope:
    narrowed = replace(scope)
    for name in ("operator_id", "supervisor_id", "project_id", "rider_id", "city_id"):
        value = spec.filters.get(name)
        if value is not None:
            setattr(narrowed, name, value)
    return narrowed


def answer_question(
    db: Session,
    scope: AuthorizedScope,
    question: str,
    previous_intent: str | None = None,
    current_spec: ReportSpec | None = None,
) -> tuple[str, dict]:
    """Deterministic question answering using ReportSpec."""
    if is_ambiguous(question, current_spec):
        options = generate_clarification_options(question)
        normalized_q = question.strip().lower()
        if any(
            g in normalized_q
            for g in (
                "سلام",
                "مرحبا",
                "أهلا",
                "اهلا",
                "صباح",
                "مساء",
                "هلا",
                "hi",
                "hello",
            )
        ):
            answer_text = "وعليكم السلام ورحمة الله وبركاته! أهلاً بك في مساعد DOU للعمليات التشغيلية والتقارير. كيف يمكنني مساعدتك اليوم؟ إليك بعض الاستفسارات المقترحة:"
        else:
            answer_text = "أهلاً بك في مساعد DOU الذكي. يرجى تحديد الاستفسار أو نوع التقرير المطلوب من الخيارات التالية:"
        return "clarification_needed", {
            "answer": answer_text,
            "clarification_options": options,
            "source": "DOU AI",
            "freshness": "",
            "kpis": [],
            "table": None,
            "chart": None,
            "report_link": None,
            "warnings": [],
            "suggested_followups": [
                "ملخص الأداء التشغيلي اليوم",
                "من هم السائقون الغائبون اليوم؟",
                "تقرير الرواتب والمسير المالي",
                "السائقون تحت المستهدف",
            ],
        }

    spec = parse_question(question, current_spec)
    if spec.report_key not in {"IDENTITY", "UNCERTAIN"}:
        _normalize_filters(db, scope, spec)
        if not spec.period:
            spec.period = default_period_for(spec.metric, spec.operation)
        validate_spec_against_scope(spec, scope)
        validate_registered_report(spec, scope)
        execution_scope = _narrow_scope(scope, spec)
    else:
        execution_scope = scope

    response = execute_report(db, execution_scope, spec)
    if spec.report_key == "IDENTITY" and "who are you" in question.casefold():
        response["answer"] = "I'm DOU AI, your intelligent operations assistant."
    response["report_spec"] = spec.to_dict()
    return spec.operation.lower(), response


def process_message(
    db: Session,
    user: ent.User,
    question: str,
    conversation_id: int | None,
    page_context: dict | None,
) -> dict:
    started = time.monotonic()
    scope = resolve_scope(db, user, page_context)
    conversation = None
    if conversation_id:
        conversation = (
            db.query(AIConversation)
            .filter(
                AIConversation.id == conversation_id,
                AIConversation.tenant_id == scope.tenant_id,
                AIConversation.user_id == user.id,
                AIConversation.is_active.is_(True),
            )
            .first()
        )
        if not conversation:
            raise HTTPException(404, "Conversation not found")
    else:
        conversation = AIConversation(
            tenant_id=scope.tenant_id,
            user_id=user.id,
            title=question[:157],
            context_json=json.dumps(page_context or {}, separators=(",", ":")),
        )
        db.add(conversation)
        db.flush()

    previous = (
        db.query(AIMessage)
        .filter(
            AIMessage.conversation_id == conversation.id, AIMessage.role == "ASSISTANT"
        )
        .order_by(AIMessage.id.desc())
        .first()
    )
    previous_spec = None
    if previous and previous.structured_json:
        try:
            raw_spec = json.loads(previous.structured_json).get("report_spec")
            if raw_spec:
                previous_spec = ReportSpec.from_dict(raw_spec)
        except (TypeError, ValueError, json.JSONDecodeError):
            previous_spec = None

    db.add(
        AIMessage(
            tenant_id=scope.tenant_id,
            conversation_id=conversation.id,
            user_id=user.id,
            role="USER",
            content=question,
        )
    )
    success, error, caught = True, None, None
    try:
        intent, response = answer_question(db, scope, question, None, previous_spec)
    except Exception as exc:
        success, error, caught = (
            False,
            "authorization_error" if isinstance(exc, HTTPException) else "query_error",
            exc,
        )
        intent, response = "error", None
    latency = int((time.monotonic() - started) * 1000)
    db.add(
        AIRequestLog(
            tenant_id=scope.tenant_id,
            user_id=user.id,
            conversation_id=conversation.id,
            route="deterministic_bi",
            source="NATIVE_DOU",
            model_identifier="deterministic",
            latency_ms=latency,
            success=success,
            error_category=error,
        )
    )
    if caught:
        db.commit()
        raise caught

    payload = {
        **response,
        "intent": intent,
        "conversation_id": conversation.id,
        "latency_ms": latency,
        "deterministic": True,
    }
    db.add(
        AIMessage(
            tenant_id=scope.tenant_id,
            conversation_id=conversation.id,
            user_id=user.id,
            role="ASSISTANT",
            content=response["answer"],
            structured_json=json.dumps(payload, separators=(",", ":")),
        )
    )
    conversation.context_json = json.dumps(page_context or {}, separators=(",", ":"))
    db.commit()
    return payload
