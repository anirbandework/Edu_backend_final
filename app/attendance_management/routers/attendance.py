"""Attendance API — open a class session and record its learners. Gated by the
`attendance` module (admins always; staff whose role is granted the page)."""
from __future__ import annotations
from datetime import date as date_cls
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal
from ...auth_rbac.access.deps import require_authority_or_module
from ..services.attendance_service import AttendanceService

router = APIRouter(
    prefix="/api/attendance",
    tags=["Attendance"],
    dependencies=[Depends(require_authority_or_module("attendance"))],
)


def _org(p: Principal):
    if not p.organisation_uuid:
        raise HTTPException(status_code=400, detail="No active organisation in session.")
    return p.organisation_uuid


class OpenBody(BaseModel):
    class_id: str
    date: date_cls
    subject_id: Optional[str] = None        # required only in per_period mode
    instructor_member_id: Optional[str] = None


class RecordItem(BaseModel):
    member_id: str
    status: str                             # present | absent | late | excused | leave


class SaveBody(BaseModel):
    records: List[RecordItem]
    instructor_member_id: Optional[str] = None


@router.get("/roster")
async def roster(class_id: str, principal: Principal = Depends(get_current_principal),
                 db: AsyncSession = Depends(get_db)):
    return await AttendanceService.learner_roster(db, _org(principal), class_id)


@router.post("/open")
async def open_attendance(body: OpenBody, principal: Principal = Depends(get_current_principal),
                          db: AsyncSession = Depends(get_db)):
    """Find-or-create the session for (class, date[, subject]) and return it with the
    learner roster + any saved statuses — everything the marking screen needs."""
    try:
        return await AttendanceService.open(
            db, organisation_id=_org(principal), class_id=body.class_id, on_date=body.date,
            subject_id=body.subject_id, instructor_member_id=body.instructor_member_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{session_id}")
async def save_attendance(session_id: str, body: SaveBody,
                          principal: Principal = Depends(get_current_principal),
                          db: AsyncSession = Depends(get_db)):
    try:
        return await AttendanceService.save(
            db, organisation_id=_org(principal), session_id=session_id,
            records=[r.model_dump() for r in body.records],
            marked_by=principal.user_uuid, instructor_member_id=body.instructor_member_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions")
async def list_sessions(class_id: str, limit: int = 60,
                        principal: Principal = Depends(get_current_principal),
                        db: AsyncSession = Depends(get_db)):
    return await AttendanceService.list_sessions(db, _org(principal), class_id, limit)


@router.get("/summary")
async def summary(class_id: str, principal: Principal = Depends(get_current_principal),
                  db: AsyncSession = Depends(get_db)):
    """Per-learner attendance % for a class → { total_sessions, learners:[{name,present,marked,pct}] }."""
    return await AttendanceService.learner_summary(db, _org(principal), class_id)


@router.get("/session/{session_id}")
async def get_session(session_id: str, principal: Principal = Depends(get_current_principal),
                      db: AsyncSession = Depends(get_db)):
    sess = await AttendanceService.get_session(db, _org(principal), session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Attendance session not found.")
    roster = await AttendanceService.learner_roster(db, _org(principal), sess.class_id)
    records = await AttendanceService._records_map(db, sess.id)
    return {"session": AttendanceService._serialize(sess), "roster": roster, "records": records}
