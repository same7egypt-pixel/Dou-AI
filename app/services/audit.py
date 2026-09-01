"""Centralized audit logging service."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy.orm import Session
from ..models import entities as ent


class AuditService:
    """Centralized audit logging service for compliance and tracking."""

    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        actor: ent.User,
        action: str,
        entity: str,
        entity_id: Optional[int] = None,
        before: Optional[dict] = None,
        after: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> ent.AuditLog:
        entry = ent.AuditLog(
            tenant_id=actor.tenant_id,
            actor_id=actor.id,
            actor_name=actor.name or "—",
            actor_role=actor.role.value if hasattr(actor.role, "value") else str(actor.role),
            action=action,
            entity=entity,
            entity_id=entity_id,
            before_json=json.dumps(before, default=str) if before else None,
            after_json=json.dumps(after, default=str) if after else None,
            metadata_json=json.dumps(metadata, default=str) if metadata else None,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(entry)
        return entry

    def log_create(self, actor: ent.User, entity: str, entity_id: int, after: dict):
        return self.log(actor, "CREATE", entity, entity_id, after=after)

    def log_update(self, actor: ent.User, entity: str, entity_id: int, before: dict, after: dict):
        return self.log(actor, "UPDATE", entity, entity_id, before=before, after=after)

    def log_delete(self, actor: ent.User, entity: str, entity_id: int, before: dict):
        return self.log(actor, "DELETE", entity, entity_id, before=before)

    def log_login(self, actor: ent.User):
        return self.log(actor, "LOGIN", "user", actor.id)

    def log_export(self, actor: ent.User, entity: str, filters: dict):
        return self.log(actor, "EXPORT", entity, metadata=filters)
