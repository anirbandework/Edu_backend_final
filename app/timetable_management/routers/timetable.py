"""Timetable API — weekly slots per class + a 'today' view. Gated by the `timetable`
module (admins always; staff whose role is granted the page)."""
from __future__ import annotations
from datetime import time as time_cls
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal
from ...auth_rbac.access.deps import require_authority_or_module
from ..services.timetable_service import TimetableService

router = APIRouter(
    prefix="/api/timetable",
    tags=["Timetable"],
    dependencies=[Depends(require_authority_or_module("timetable"))],
)


def _org(p: Principal):
    if not p.organisation_uuid:
        raise HTTPException(status_code=400, detail="No active organisation in session.")
    return p.organisation_uuid


class SlotBody(BaseModel):
    class_id: str
    weekday: int                       # 0 = Mon … 6 = Sun
    start_time: time_cls
    end_time: time_cls
    subject_id: Optional[str] = None
    instructor_member_id: Optional[str] = None
    room: Optional[str] = None


class SlotUpdate(BaseModel):
    weekday: int
    start_time: time_cls
    end_time: time_cls
    subject_id: Optional[str] = None
    instructor_member_id: Optional[str] = None
    room: Optional[str] = None


async def _load(db, principal, slot_id):
    s = await TimetableService.get(db, _org(principal), slot_id)
    if not s:
        raise HTTPException(status_code=404, detail="Slot not found.")
    return s


@router.get("")
async def list_slots(class_id: str, principal: Principal = Depends(get_current_principal),
                     db: AsyncSession = Depends(get_db)):
    return await TimetableService.list_by_class(db, _org(principal), class_id)


@router.post("")
async def create_slot(body: SlotBody, principal: Principal = Depends(get_current_principal),
                      db: AsyncSession = Depends(get_db)):
    try:
        slot = await TimetableService.create(
            db, organisation_id=_org(principal), class_id=body.class_id, weekday=body.weekday,
            start_time=body.start_time, end_time=body.end_time, subject_id=body.subject_id,
            instructor_member_id=body.instructor_member_id, room=body.room)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TimetableService._serialize(slot)


@router.put("/{slot_id}")
async def update_slot(slot_id: str, body: SlotUpdate,
                      principal: Principal = Depends(get_current_principal),
                      db: AsyncSession = Depends(get_db)):
    slot = await _load(db, principal, slot_id)
    try:
        slot = await TimetableService.update(
            db, slot, weekday=body.weekday, start_time=body.start_time, end_time=body.end_time,
            subject_id=body.subject_id, instructor_member_id=body.instructor_member_id,
            room=body.room)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TimetableService._serialize(slot)


@router.delete("/{slot_id}")
async def delete_slot(slot_id: str, principal: Principal = Depends(get_current_principal),
                      db: AsyncSession = Depends(get_db)):
    slot = await _load(db, principal, slot_id)
    await TimetableService.soft_delete(db, slot)
    return {"id": slot_id, "detail": "deleted"}


@router.get("/today")
async def today(weekday: int, mine: bool = False,
                principal: Principal = Depends(get_current_principal),
                db: AsyncSession = Depends(get_db)):
    """Slots on a weekday across the org. `mine=true` (for a staff instructor) filters to
    the caller's own slots — the 'my classes today' feed."""
    instructor = principal.user_id if (mine and principal.role == "staff") else None
    return await TimetableService.today(db, _org(principal), weekday, instructor_member_id=instructor)
