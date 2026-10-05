"""Append-only audit trail."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config.constants import Perm
from app.database.database import Database
from app.models import AuditLog
from app.security.auth import CurrentUser, require
from app.utils.dates import day_end_exclusive, day_start


def record(session: Session, actor: CurrentUser | None, action: str, entity: str | None = None,
           entity_id=None, details: dict | None = None, *, username: str | None = None) -> None:
    """Write an audit row inside the caller's transaction."""
    session.add(AuditLog(
        user_id=actor.id if actor else None,
        username=actor.username if actor else username,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=json.dumps(details, default=str, ensure_ascii=False) if details else None,
    ))


class AuditService:
    def __init__(self, db: Database):
        self.db = db

    def list(self, actor: CurrentUser, *, date_from: date | None = None,
             date_to: date | None = None, action: str | None = None, search: str = "",
             limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
        require(actor, Perm.VIEW_AUDIT_LOG)
        with self.db.session() as s:
            q = select(AuditLog)
            if date_from:
                q = q.where(AuditLog.created_at >= day_start(date_from))
            if date_to:
                q = q.where(AuditLog.created_at < day_end_exclusive(date_to))
            if action:
                q = q.where(AuditLog.action == action)
            if search:
                like = f"%{search}%"
                q = q.where(or_(AuditLog.username.ilike(like), AuditLog.details.ilike(like),
                                AuditLog.entity.ilike(like), AuditLog.entity_id == search))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            rows = s.scalars(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
            return [{
                "id": r.id, "created_at": r.created_at, "username": r.username or "",
                "action": r.action, "entity": r.entity or "", "entity_id": r.entity_id or "",
                "details": r.details or "",
            } for r in rows], total

    def actions(self, actor: CurrentUser) -> list[str]:
        require(actor, Perm.VIEW_AUDIT_LOG)
        with self.db.session() as s:
            return list(s.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)))
