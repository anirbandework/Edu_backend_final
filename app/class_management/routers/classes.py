"""Classes API — the generic Class/Batch/Course container (rendered per org_type) + its
membership. Gated by the `classes` module."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal
from ...auth_rbac.access.deps import require_authority_or_module
from ..services.class_service import ClassService
from ..services.subject_link_service import ClassSubjectService

router = APIRouter(
    prefix="/api/classes",
    tags=["Classes"],
    dependencies=[Depends(require_authority_or_module("classes"))],
)


def _org(p: Principal):
    if not p.organisation_uuid:
        raise HTTPException(status_code=400, detail="No active organisation in session.")
    return p.organisation_uuid


class ClassBody(BaseModel):
    name: str
    kind_label: Optional[str] = None
    session_id: Optional[str] = None
    parent_id: Optional[str] = None


class ClassUpdate(BaseModel):
    name: Optional[str] = None
    kind_label: Optional[str] = None
    session_id: Optional[str] = None
    parent_id: Optional[str] = None


class MemberBody(BaseModel):
    member_id: str
    # A participant capability key (instructor | class_head | learner) or null to
    # auto-derive from the member's role. NOT a hardcoded student/teacher/assistant.
    capacity: Optional[str] = None


class SubjectLinkBody(BaseModel):
    subject_id: str


class TeacherAssignBody(BaseModel):
    member_id: str


async def _load(db, principal, class_id):
    c = await ClassService.get(db, _org(principal), class_id)
    if not c:
        raise HTTPException(status_code=404, detail="Class not found.")
    return c


@router.get("")
async def list_classes(session_id: str = "", principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    return await ClassService.list(db, _org(principal), session_id=session_id or None)


@router.post("")
async def create_class(body: ClassBody, principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    try:
        c = await ClassService.create(
            db, organisation_id=_org(principal), name=body.name, kind_label=body.kind_label,
            session_id=body.session_id, parent_id=body.parent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ClassService._serialize(c)


@router.put("/{class_id}")
async def update_class(class_id: str, body: ClassUpdate,
                       principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    c = await _load(db, principal, class_id)
    try:
        c = await ClassService.update(
            db, c, name=body.name, kind_label=body.kind_label,
            session_id=body.session_id, parent_id=body.parent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ClassService._serialize(c)


@router.delete("/{class_id}")
async def delete_class(class_id: str, principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    c = await _load(db, principal, class_id)
    await ClassService.soft_delete(db, c)
    return {"id": class_id, "detail": "deleted"}


@router.get("/{class_id}/members")
async def list_members(class_id: str, principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    return await ClassService.list_members(db, _org(principal), class_id)


@router.post("/{class_id}/members")
async def add_member(class_id: str, body: MemberBody,
                     principal: Principal = Depends(get_current_principal),
                     db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    try:
        return await ClassService.add_member(
            db, organisation_id=_org(principal), class_id=class_id,
            member_id=body.member_id, capacity=body.capacity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{class_id}/members/{cm_id}")
async def remove_member(class_id: str, cm_id: str,
                        principal: Principal = Depends(get_current_principal),
                        db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    try:
        await ClassService.remove_member(db, _org(principal), class_id, cm_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": cm_id, "detail": "removed"}


# ----------------------- class ↔ subjects ↔ instructors -----------------------
# Reserved for Phase-1 timetable/attendance — capability-gated so only an
# instructor-capable member can be assigned to teach a subject. (See §3.3.)
@router.get("/{class_id}/subjects")
async def list_class_subjects(class_id: str, principal: Principal = Depends(get_current_principal),
                              db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    return await ClassSubjectService.list_class_subjects(db, _org(principal), class_id)


@router.post("/{class_id}/subjects")
async def link_class_subject(class_id: str, body: SubjectLinkBody,
                             principal: Principal = Depends(get_current_principal),
                             db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    try:
        return await ClassSubjectService.link_subject(
            db, organisation_id=_org(principal), class_id=class_id, subject_id=body.subject_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{class_id}/subjects/{cs_id}")
async def unlink_class_subject(class_id: str, cs_id: str,
                               principal: Principal = Depends(get_current_principal),
                               db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    try:
        await ClassSubjectService.unlink_subject(db, _org(principal), class_id, cs_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": cs_id, "detail": "removed"}


@router.get("/{class_id}/subjects/{subject_id}/teachers")
async def list_subject_teachers(class_id: str, subject_id: str,
                                principal: Principal = Depends(get_current_principal),
                                db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    return await ClassSubjectService.list_teachers(db, _org(principal), class_id, subject_id)


@router.post("/{class_id}/subjects/{subject_id}/teachers")
async def assign_subject_teacher(class_id: str, subject_id: str, body: TeacherAssignBody,
                                 principal: Principal = Depends(get_current_principal),
                                 db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    try:
        return await ClassSubjectService.assign_teacher(
            db, organisation_id=_org(principal), class_id=class_id,
            subject_id=subject_id, member_id=body.member_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{class_id}/subjects/{subject_id}/teachers/{st_id}")
async def unassign_subject_teacher(class_id: str, subject_id: str, st_id: str,
                                   principal: Principal = Depends(get_current_principal),
                                   db: AsyncSession = Depends(get_db)):
    await _load(db, principal, class_id)
    try:
        await ClassSubjectService.unassign_teacher(db, _org(principal), class_id, st_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": st_id, "detail": "removed"}
