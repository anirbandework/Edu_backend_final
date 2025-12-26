from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Optional
from uuid import UUID
from pydantic import BaseModel

from ..core.database import get_db
from ..services.page_permission_service import PagePermissionService

router = APIRouter(prefix="/api/page-permissions", tags=["Page Permissions"])

class PagePermissionCreate(BaseModel):
    page_id: str
    page_name: str
    page_path: str
    page_icon: Optional[str] = None
    page_category: Optional[str] = None
    can_view: bool = True
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_export: bool = False
    can_import: bool = False
    custom_permissions: Optional[Dict] = {}
    is_active: bool = True

class PagePermissionUpdate(BaseModel):
    permissions: List[PagePermissionCreate]

@router.post("/role/{role_id}")
async def create_page_permission(
    role_id: UUID,
    permission_data: PagePermissionCreate,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Create a new page permission for a role"""
    try:
        permission = await PagePermissionService.create_page_permission(
            db, tenant_id, role_id, permission_data.dict()
        )
        return {
            "message": "Page permission created successfully",
            "permission_id": str(permission.id)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/role/{role_id}")
async def get_role_permissions(
    role_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get all page permissions for a role"""
    try:
        permissions = await PagePermissionService.get_role_permissions(
            db, tenant_id, role_id
        )
        return [
            {
                "id": str(p.id),
                "page_id": p.page_id,
                "page_name": p.page_name,
                "page_path": p.page_path,
                "page_icon": p.page_icon,
                "page_category": p.page_category,
                "permissions": {
                    "can_view": p.can_view,
                    "can_create": p.can_create,
                    "can_edit": p.can_edit,
                    "can_delete": p.can_delete,
                    "can_export": p.can_export,
                    "can_import": p.can_import,
                    "custom": p.custom_permissions
                },
                "is_active": p.is_active
            }
            for p in permissions
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/role/{role_id}")
async def update_role_permissions(
    role_id: UUID,
    permissions_data: PagePermissionUpdate,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Update all permissions for a role"""
    try:
        permissions = await PagePermissionService.update_role_permissions(
            db, tenant_id, role_id, [p.dict() for p in permissions_data.permissions]
        )
        return {
            "message": "Role permissions updated successfully",
            "updated_count": len(permissions)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/tenant/{tenant_id}/seed")
async def seed_default_permissions(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Seed default page permissions for all roles in a tenant"""
    try:
        await PagePermissionService.seed_default_permissions(db, tenant_id)
        return {"message": "Default permissions seeded successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/user-pages")
async def get_user_accessible_pages(
    tenant_id: UUID = Query(...),
    role_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get all pages accessible to a user based on their role"""
    try:
        pages = await PagePermissionService.get_user_accessible_pages(
            db, tenant_id, role_id
        )
        return {
            "pages": pages,
            "total_count": len(pages)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))