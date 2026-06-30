# app/feedback_management/routers/feedback.py
"""Feedback API. Submit is open to any authenticated user; listing / triage /
stats are super-admin only."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal, require_super_admin
from ...auth_rbac.security.principal import Principal
from ..models.feedback import Feedback

router = APIRouter(prefix="/api/v1/feedback", tags=["Feedback"])

_TYPES = {"suggestion", "bug", "complaint", "appreciation", "other"}
_STATUSES = {"pending", "reviewed", "resolved"}


class FeedbackCreate(BaseModel):
    title: str
    message: str
    feedback_type: str = "suggestion"
    rating: Optional[int] = None
    user_name: Optional[str] = None
    user_phone: Optional[str] = None


class StatusUpdate(BaseModel):
    status: str


def _dict(f: Feedback) -> dict:
    return {
        "id": str(f.id),
        "user_type": f.user_type,
        "user_name": f.user_name,
        "user_phone": f.user_phone,
        "organisation_id": str(f.organisation_id) if f.organisation_id else None,
        "feedback_type": f.feedback_type,
        "rating": f.rating,
        "title": f.title,
        "message": f.message,
        "status": f.status,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def _uuid_or_none(v):
    try:
        return UUID(str(v)) if v else None
    except (ValueError, TypeError):
        return None


@router.post("")
async def submit_feedback(
    body: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Any authenticated user submits feedback."""
    if not body.title.strip() or not body.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Title and message are required.")
    ftype = body.feedback_type if body.feedback_type in _TYPES else "other"
    rating = body.rating if (body.rating is not None and 1 <= body.rating <= 5) else None
    fb = Feedback(
        organisation_id=_uuid_or_none(principal.organisation_id),
        user_id=_uuid_or_none(principal.user_id),
        user_type=principal.role,
        user_name=(body.user_name or "").strip() or None,
        user_phone=(body.user_phone or "").strip() or None,
        feedback_type=ftype,
        rating=rating,
        title=body.title.strip(),
        message=body.message.strip(),
        status="pending",
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return {"id": str(fb.id), "message": "Feedback submitted"}


@router.get("")
async def list_feedback(
    status_filter: Optional[str] = Query(None, alias="status"),
    feedback_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Super-admin: all feedback, newest first, optionally filtered."""
    q = select(Feedback).where(Feedback.is_deleted == False)
    if status_filter in _STATUSES:
        q = q.where(Feedback.status == status_filter)
    if feedback_type in _TYPES:
        q = q.where(Feedback.feedback_type == feedback_type)
    q = q.order_by(Feedback.created_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return [_dict(f) for f in rows]


@router.get("/stats")
async def feedback_stats(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Counts by status + total + unread (pending)."""
    rows = (await db.execute(text(
        "SELECT status, COUNT(*) AS c FROM feedback WHERE is_deleted = false GROUP BY status"
    ))).all()
    by_status = {r[0]: r[1] for r in rows}
    total = sum(by_status.values())
    return {
        "total": total,
        "pending": by_status.get("pending", 0),
        "reviewed": by_status.get("reviewed", 0),
        "resolved": by_status.get("resolved", 0),
    }


@router.patch("/{feedback_id}/status")
async def set_status(
    feedback_id: UUID,
    body: StatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Super-admin: move feedback through pending -> reviewed -> resolved."""
    if body.status not in _STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"status must be one of {sorted(_STATUSES)}")
    fb = (await db.execute(
        select(Feedback).where(Feedback.id == feedback_id, Feedback.is_deleted == False)
    )).scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    fb.status = body.status
    await db.commit()
    return {"id": str(feedback_id), "status": fb.status, "message": "Status updated"}


@router.delete("/{feedback_id}")
async def delete_feedback(
    feedback_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    """Super-admin: soft-delete feedback."""
    fb = (await db.execute(
        select(Feedback).where(Feedback.id == feedback_id, Feedback.is_deleted == False)
    )).scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    fb.is_deleted = True
    await db.commit()
    return {"id": str(feedback_id), "message": "Feedback deleted"}
