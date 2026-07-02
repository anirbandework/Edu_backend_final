"""Org Settings API — terminology label-map + academic config that adapts one UI to any
org type. Admin-only (the `org_settings` module is in _ADMIN_ONLY)."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal
from ...auth_rbac.access.deps import require_authority_or_module
from ..services.settings_service import SettingsService

# GET is readable by ANY authed user with an active org (so the FE can adapt labels /
# terminology for staff too — it's not sensitive). EDITING is admin-only.
router = APIRouter(prefix="/api/org-settings", tags=["Org Settings"])


def _org(p: Principal):
    if not p.organisation_uuid:
        raise HTTPException(status_code=400, detail="No active organisation in session.")
    return p.organisation_uuid


class SettingsBody(BaseModel):
    terminology: Optional[dict] = None
    config: Optional[dict] = None


@router.get("")
async def get_settings(principal: Principal = Depends(get_current_principal),
                       db: AsyncSession = Depends(get_db)):
    """Read org_type + terminology + config. Any authed member of the org may read it
    (the UI adapts its labels from this); only an admin may change it."""
    return await SettingsService.get(db, _org(principal))


@router.put("", dependencies=[Depends(require_authority_or_module("org_settings"))])
async def update_settings(body: SettingsBody, principal: Principal = Depends(get_current_principal),
                          db: AsyncSession = Depends(get_db)):
    return await SettingsService.upsert(db, _org(principal),
                                        terminology=body.terminology, config=body.config)
