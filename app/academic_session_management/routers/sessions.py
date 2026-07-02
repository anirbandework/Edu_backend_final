"""Academic Sessions API — the time axis (year / semester / batch-cycle / term) every
academic record is scoped to. Gated by the `academic_session` module."""
from __future__ import annotations
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal
from ...auth_rbac.access.deps import require_authority_or_module
from ..services.session_service import SessionService

router = APIRouter(
    prefix="/api/academic-sessions",
    tags=["Academic Sessions"],
    dependencies=[Depends(require_authority_or_module("academic_session"))],
)


def _org(p: Principal):
    if not p.organisation_uuid:
        raise HTTPException(status_code=400, detail="No active organisation in session.")
    return p.organisation_uuid


class SessionBody(BaseModel):
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_current: bool = False


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_current: Optional[bool] = None


@router.get("")
async def list_sessions(principal: Principal = Depends(get_current_principal),
                        db: AsyncSession = Depends(get_db)):
    return await SessionService.list(db, _org(principal))


@router.post("")
async def create_session(body: SessionBody, principal: Principal = Depends(get_current_principal),
                         db: AsyncSession = Depends(get_db)):
    try:
        s = await SessionService.create(
            db, organisation_id=_org(principal), name=body.name,
            start_date=body.start_date, end_date=body.end_date, is_current=body.is_current)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SessionService._serialize(s)


@router.put("/{session_id}")
async def update_session(session_id: str, body: SessionUpdate,
                         principal: Principal = Depends(get_current_principal),
                         db: AsyncSession = Depends(get_db)):
    s = await SessionService.get(db, _org(principal), session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        s = await SessionService.update(
            db, s, name=body.name, start_date=body.start_date,
            end_date=body.end_date, is_current=body.is_current)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SessionService._serialize(s)


@router.delete("/{session_id}")
async def delete_session(session_id: str, principal: Principal = Depends(get_current_principal),
                         db: AsyncSession = Depends(get_db)):
    s = await SessionService.get(db, _org(principal), session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found.")
    await SessionService.soft_delete(db, s)
    return {"id": session_id, "detail": "deleted"}
