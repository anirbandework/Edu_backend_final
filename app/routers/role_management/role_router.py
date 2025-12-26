from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from ...core.database import get_db
from ...services.role_management.role_service import RoleManagementService
from ...schemas.role_management.role_schemas import (
    RoleCreate, RoleResponse, UserRoleAssign, UserRoleResponse, UserWithRoles
)

router = APIRouter(prefix="/api/role-management", tags=["Role Management"])

@router.post("/tenants/{tenant_id}/roles", response_model=RoleResponse)
async def create_role(
    tenant_id: UUID,
    role_data: RoleCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new role for a tenant"""
    role = await RoleManagementService.create_role(db, tenant_id, role_data)
    return role

@router.get("/tenants/{tenant_id}/roles", response_model=List[RoleResponse])
async def get_tenant_roles(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get all roles for a tenant"""
    roles = await RoleManagementService.get_tenant_roles(db, tenant_id)
    return roles

@router.post("/tenants/{tenant_id}/assign-role")
async def assign_role_to_user(
    tenant_id: UUID,
    assignment: UserRoleAssign,
    db: AsyncSession = Depends(get_db)
):
    """Assign a role to a user"""
    result = await RoleManagementService.assign_role_to_user(db, tenant_id, assignment)
    return result

@router.get("/tenants/{tenant_id}/users/{user_id}/roles", response_model=List[UserRoleResponse])
async def get_user_roles(
    tenant_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get all roles assigned to a user"""
    user_roles = await RoleManagementService.get_user_roles(db, tenant_id, user_id)
    return user_roles

@router.get("/tenants/{tenant_id}/user-roles")
async def get_all_user_roles(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get all user role assignments for a tenant"""
    user_roles = await RoleManagementService.get_all_user_roles(db, tenant_id)
    return user_roles

@router.post("/tenants/{tenant_id}/bulk-assign-role")
async def bulk_assign_role(
    tenant_id: UUID,
    assignments: List[UserRoleAssign],
    db: AsyncSession = Depends(get_db)
):
    """Assign roles to multiple users"""
    results = await RoleManagementService.bulk_assign_roles(db, tenant_id, assignments)
    return {"assigned": len(results), "assignments": results}

@router.post("/tenants/{tenant_id}/page-permissions")
async def create_page_permissions(
    tenant_id: UUID,
    permissions: List[dict],
    db: AsyncSession = Depends(get_db)
):
    """Create page permissions for a role"""
    created_permissions = []
    for perm in permissions:
        page_permission = PagePermission(
            tenant_id=tenant_id,
            role_id=perm["role_id"],
            page_id=perm["page_id"],
            page_name=perm["page_name"],
            page_path=perm["page_path"],
            page_icon=perm.get("page_icon"),
            page_category=perm.get("page_category"),
            can_view=perm.get("can_view", True),
            can_create=perm.get("can_create", False),
            can_edit=perm.get("can_edit", False),
            can_delete=perm.get("can_delete", False),
            can_export=perm.get("can_export", False),
            can_import=perm.get("can_import", False),
            custom_permissions=perm.get("custom_permissions")
        )
        db.add(page_permission)
        created_permissions.append(page_permission)
    
    await db.commit()
    return {"message": f"Created {len(created_permissions)} page permissions"}

@router.get("/tenants/{tenant_id}/roles/{role_id}/page-permissions")
async def get_role_page_permissions(
    tenant_id: UUID,
    role_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get page permissions for a specific role"""
    result = await db.execute(
        select(PagePermission).where(
            and_(
                PagePermission.tenant_id == tenant_id,
                PagePermission.role_id == role_id,
                PagePermission.is_active == True
            )
        )
    )
    permissions = result.scalars().all()
    return [{
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
        }
    } for p in permissions]

@router.delete("/tenants/{tenant_id}/roles/{role_id}")
async def delete_role(
    tenant_id: UUID,
    role_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Delete a role"""
    success = await RoleManagementService.delete_role(db, tenant_id, role_id)
    if not success:
        raise HTTPException(status_code=404, detail="Role not found")
    return {"message": "Role deleted successfully"}

@router.delete("/tenants/{tenant_id}/users/{user_id}/roles/{role_id}")
async def remove_user_role(
    tenant_id: UUID,
    user_id: UUID,
    role_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Remove a role from a user"""
    success = await RoleManagementService.remove_user_role(db, tenant_id, user_id, role_id)
    if not success:
        raise HTTPException(status_code=404, detail="User role assignment not found")
    return {"message": "Role removed successfully"}