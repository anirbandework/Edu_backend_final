"""Subjects API — the subject/course-content list. Gated by the `subjects` module."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal
from ...auth_rbac.access.deps import require_authority_or_module
from ..services.subject_service import SubjectService

router = APIRouter(
    prefix="/api/subjects",
    tags=["Subjects"],
    dependencies=[Depends(require_authority_or_module("subjects"))],
)


def _org(p: Principal):
    if not p.organisation_uuid:
        raise HTTPException(status_code=400, detail="No active organisation in session.")
    return p.organisation_uuid


class SubjectBody(BaseModel):
    name: str
    code: Optional[str] = None


class SubjectUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None


@router.get("")
async def list_subjects(principal: Principal = Depends(get_current_principal),
                        db: AsyncSession = Depends(get_db)):
    return await SubjectService.list(db, _org(principal))


@router.post("")
async def create_subject(body: SubjectBody, principal: Principal = Depends(get_current_principal),
                         db: AsyncSession = Depends(get_db)):
    try:
        s = await SubjectService.create(db, organisation_id=_org(principal),
                                        name=body.name, code=body.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SubjectService._serialize(s)


@router.put("/{subject_id}")
async def update_subject(subject_id: str, body: SubjectUpdate,
                         principal: Principal = Depends(get_current_principal),
                         db: AsyncSession = Depends(get_db)):
    s = await SubjectService.get(db, _org(principal), subject_id)
    if not s:
        raise HTTPException(status_code=404, detail="Subject not found.")
    try:
        s = await SubjectService.update(db, s, name=body.name, code=body.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SubjectService._serialize(s)


@router.delete("/{subject_id}")
async def delete_subject(subject_id: str, principal: Principal = Depends(get_current_principal),
                         db: AsyncSession = Depends(get_db)):
    s = await SubjectService.get(db, _org(principal), subject_id)
    if not s:
        raise HTTPException(status_code=404, detail="Subject not found.")
    await SubjectService.soft_delete(db, s)
    return {"id": subject_id, "detail": "deleted"}
