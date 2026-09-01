"""Authenticated DOU AI gateway. Browser clients never contact model/BI services."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from ..models.intelligence import AIConversation, AIMessage, AIRequestLog
from ..services.dou_ai import process_message
from .auth import get_current_user

router = APIRouter(prefix="/ai", tags=["dou-ai"])


class PageContext(BaseModel):
    entity_type: str | None = Field(None, max_length=40)
    entity_id: int | None = None
    operator_id: int | None = None
    supervisor_id: int | None = None
    city_id: int | None = None
    period: str | None = Field(None, max_length=30)
    current_view: str | None = Field(None, max_length=40)


class AIChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    conversation_id: int | None = None
    context: PageContext | None = None


@router.post("/chat")
def chat(
    payload: AIChatRequest,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return process_message(
        db,
        user,
        payload.question.strip(),
        payload.conversation_id,
        payload.context.model_dump(exclude_none=True) if payload.context else None,
    )


@router.get("/conversations")
def conversations(
    user: ent.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if not user.tenant_id:
        raise HTTPException(403, "Tenant scope required")
    rows = (
        db.query(AIConversation)
        .filter(
            AIConversation.tenant_id == user.tenant_id,
            AIConversation.user_id == user.id,
            AIConversation.is_active.is_(True),
        )
        .order_by(AIConversation.updated_at.desc())
        .limit(30)
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


@router.get("/conversations/{conversation_id}")
def conversation(
    conversation_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(AIConversation)
        .filter(
            AIConversation.id == conversation_id,
            AIConversation.tenant_id == user.tenant_id,
            AIConversation.user_id == user.id,
            AIConversation.is_active.is_(True),
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Conversation not found")
    messages = (
        db.query(AIMessage)
        .filter(
            AIMessage.conversation_id == row.id,
            AIMessage.tenant_id == user.tenant_id,
            AIMessage.user_id == user.id,
        )
        .order_by(AIMessage.id)
        .all()
    )
    return {
        "id": row.id,
        "title": row.title,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "structured": m.structured_json,
                "created_at": m.created_at,
            }
            for m in messages
        ],
    }


@router.delete("/conversations/{conversation_id}")
def clear_conversation(
    conversation_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(AIConversation)
        .filter(
            AIConversation.id == conversation_id,
            AIConversation.tenant_id == user.tenant_id,
            AIConversation.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Conversation not found")
    row.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/status")
def status(user: ent.User = Depends(get_current_user)):
    """Safe availability status for deterministic DOU AI."""
    return {
        "available": True,
        "reason": None,
        "assistant": "DOU AI",
        "mode": "deterministic",
    }


@router.get("/observability")
def observability(
    user: ent.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role not in {ent.UserRole.COMPANY, ent.UserRole.COMPANY_ADMIN}:
        raise HTTPException(403, "Admin role required")
    rows = (
        db.query(AIRequestLog)
        .filter(AIRequestLog.tenant_id == user.tenant_id)
        .order_by(AIRequestLog.id.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "timestamp": r.created_at,
            "latency_ms": r.latency_ms,
            "success": r.success,
            "route": r.route,
            "source": r.source,
            "error_category": r.error_category,
        }
        for r in rows
    ]
