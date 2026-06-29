# app/routers/authority.py (base router, not the subdirectory)
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr
from datetime import datetime
from ...core.database import get_db
from ...authority_management.models.authority import Authority
from ...authority_management.services.authority_service import AuthorityService
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_authority, assert_same_organisation
from ...auth_rbac.security.principal import Principal

# Existing Pydantic Models
class AuthorityCreate(BaseModel):
    organisation_id: UUID
    authority_id: str
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    position: str
    date_of_birth: Optional[datetime] = None
    address: Optional[str] = None
    gender: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = 0
    joining_date: Optional[datetime] = None
    authority_details: Optional[dict] = None
    permissions: Optional[dict] = None
    org_overview: Optional[dict] = None
    contact_info: Optional[dict] = None

class AuthorityUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    gender: Optional[str] = None
    position: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None
    status: Optional[str] = None
    authority_details: Optional[dict] = None
    permissions: Optional[dict] = None
    org_overview: Optional[dict] = None
    contact_info: Optional[dict] = None

# NEW BULK OPERATION MODELS
class BulkAuthorityImport(BaseModel):
    organisation_id: UUID
    authorities: List[dict]

class BulkStatusUpdate(BaseModel):
    organisation_id: UUID
    authority_ids: List[str]
    new_status: str

class BulkPermissionUpdate(BaseModel):
    organisation_id: UUID
    permission_updates: List[dict]  # [{"authority_id": "AUTH001", "permissions": {...}}]

class BulkPositionUpdate(BaseModel):
    organisation_id: UUID
    position_updates: List[dict]  # [{"authority_id": "AUTH001", "new_position": "Vice Principal"}]

class BulkDeleteRequest(BaseModel):
    organisation_id: UUID
    authority_ids: List[str]

router = APIRouter(prefix="/api/v1/authorities", tags=["Authority"])

# EXISTING ENDPOINTS (unchanged, but with proper async)
@router.get("/", response_model=dict)
async def get_authorities(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    organisation_id: Optional[UUID] = Query(None),
    order_by: str = Query("first_name", description="Field to order by"),
    sort: str = Query("asc", regex="^(asc|desc)$", description="Sort direction"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get paginated authorities"""
    service = AuthorityService(db)

    # Enforce organisation scoping: non-super-admins are locked to their own organisation.
    effective_organisation = organisation_id if principal.is_super_admin else principal.organisation_id

    filters = {}
    if effective_organisation:
        filters["organisation_id"] = effective_organisation
    
    try:
        result = await service.get_paginated(
        page=page, 
        size=size, 
        order_by=order_by,
        sort=sort,
        **filters
    )
        
        formatted_authorities = [
            {
                "id": str(auth.id),
                "organisation_id": str(auth.organisation_id), 
                "authority_id": auth.authority_id,
                "first_name": auth.first_name,
                "last_name": auth.last_name,
                "email": auth.email,
                "phone": auth.phone,
                "position": auth.position,
                "status": auth.status,
                "authority_details": auth.authority_details,
                "permissions": auth.permissions,
                "created_at": auth.created_at.isoformat(),
                "updated_at": auth.updated_at.isoformat()
            }
            for auth in result["items"]
        ]
        
        return {
            "items": formatted_authorities,
            "total": result["total"],
            "page": result["page"],
            "size": result["size"],
            "has_next": result["has_next"],
            "has_previous": result["has_previous"],
            "total_pages": result["total_pages"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/", response_model=dict)
async def create_authority(
    authority_data: AuthorityCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Create new authority"""
    service = AuthorityService(db)

    authority_dict = authority_data.model_dump()
    # Override client-supplied organisation_id: non-super-admins may only create within
    # their own organisation; super-admins may target the supplied organisation.
    if not principal.is_super_admin:
        authority_dict["organisation_id"] = principal.organisation_id
    authority = await service.create(authority_dict)
    
    return {
        "id": str(authority.id),
        "message": "Organisation authority created successfully",
        "authority_id": authority.authority_id
    }

@router.get("/{authority_id}", response_model=dict)
async def get_authority(
    authority_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get specific authority details"""
    service = AuthorityService(db)
    scope_organisation = None if principal.is_super_admin else principal.organisation_id
    authority = await service.get(authority_id, organisation_id=scope_organisation)

    if not authority:
        raise HTTPException(status_code=404, detail="Authority not found")
    
    return {
        "id": str(authority.id),
        "organisation_id": str(authority.organisation_id),
        "authority_id": authority.authority_id,
        "first_name": authority.first_name,
        "last_name": authority.last_name,
        "email": authority.email,
        "phone": authority.phone,
        "date_of_birth": authority.date_of_birth.isoformat() if authority.date_of_birth else None,
        "address": authority.address,
        "gender": authority.gender,
        "role": authority.role,
        "status": authority.status,
        "position": authority.position,
        "qualification": authority.qualification,
        "experience_years": authority.experience_years,
        "joining_date": authority.joining_date.isoformat() if authority.joining_date else None,
        "authority_details": authority.authority_details,
        "permissions": authority.permissions,
        "org_overview": authority.org_overview,
        "contact_info": authority.contact_info,
        "last_login": authority.last_login.isoformat() if authority.last_login else None,
        "created_at": authority.created_at.isoformat(),
        "updated_at": authority.updated_at.isoformat()
    }

@router.put("/{authority_id}", response_model=dict)
async def update_authority(
    authority_id: UUID,
    authority_data: AuthorityUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Update authority information"""
    service = AuthorityService(db)

    scope_organisation = None if principal.is_super_admin else principal.organisation_id
    update_dict = authority_data.model_dump(exclude_unset=True)
    authority = await service.update(authority_id, update_dict, organisation_id=scope_organisation)

    if not authority:
        raise HTTPException(status_code=404, detail="Authority not found")
    
    return {
        "id": str(authority.id),
        "message": "Authority updated successfully"
    }

@router.delete("/{authority_id}")
async def delete_authority(
    authority_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Soft delete authority"""
    service = AuthorityService(db)
    scope_organisation = None if principal.is_super_admin else principal.organisation_id
    success = await service.soft_delete(authority_id, organisation_id=scope_organisation)

    if not success:
        raise HTTPException(status_code=404, detail="Authority not found")
    
    return {"message": "Authority deactivated successfully"}

@router.get("/organisation/{organisation_id}")
async def get_authorities_by_organisation(
    organisation_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all authorities for a specific organisation/organisation"""
    # Non-super-admins may only query their own organisation (super-admin bypass inside).
    assert_same_organisation(principal, organisation_id)
    service = AuthorityService(db)
    authorities = await service.get_by_organisation(organisation_id)
    
    return [
        {
            "id": str(auth.id),
            "authority_id": auth.authority_id,
            "name": f"{auth.first_name} {auth.last_name}",
            "email": auth.email,
            "position": auth.position,
            "status": auth.status
        }
        for auth in authorities
    ]

# NEW BULK OPERATION ENDPOINTS

@router.post("/bulk/import", response_model=dict)
async def bulk_import_authorities(
    import_data: BulkAuthorityImport,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk import authorities from CSV/JSON data"""
    service = AuthorityService(db)

    effective_organisation = import_data.organisation_id if principal.is_super_admin else principal.organisation_id
    result = await service.bulk_import_authorities(
        authorities_data=import_data.authorities,
        organisation_id=effective_organisation
    )
    
    # Create detailed message
    message_parts = []
    if result['successful_imports'] > 0:
        message_parts.append(f"{result['successful_imports']} authorities imported successfully")
    if result.get('duplicate_records', 0) > 0:
        message_parts.append(f"{result['duplicate_records']} duplicates found")
    validation_errors = result['failed_imports'] - result.get('duplicate_records', 0)
    if validation_errors > 0:
        message_parts.append(f"{validation_errors} validation errors")
    
    message = "Bulk import completed. " + ", ".join(message_parts) if message_parts else "No records processed"
    
    return {
        "message": message,
        **result
    }

@router.post("/bulk/update-status", response_model=dict)
async def bulk_update_status(
    status_data: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk update authority status"""
    service = AuthorityService(db)

    effective_organisation = status_data.organisation_id if principal.is_super_admin else principal.organisation_id
    result = await service.bulk_update_status(
        authority_ids=status_data.authority_ids,
        new_status=status_data.new_status,
        organisation_id=effective_organisation
    )
    
    return {
        "message": f"Status update completed. {result['updated_authorities']} authorities updated to '{result['new_status']}'",
        **result
    }

@router.post("/bulk/update-permissions", response_model=dict)
async def bulk_update_permissions(
    permission_data: BulkPermissionUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk update authority permissions"""
    service = AuthorityService(db)

    effective_organisation = permission_data.organisation_id if principal.is_super_admin else principal.organisation_id
    result = await service.bulk_update_permissions(
        permission_updates=permission_data.permission_updates,
        organisation_id=effective_organisation
    )
    
    return {
        "message": f"Permission update completed. {result['updated_authorities']} authorities updated",
        **result
    }

@router.post("/bulk/update-positions", response_model=dict)
async def bulk_update_positions(
    position_data: BulkPositionUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk update authority positions"""
    service = AuthorityService(db)

    effective_organisation = position_data.organisation_id if principal.is_super_admin else principal.organisation_id
    result = await service.bulk_update_positions(
        position_updates=position_data.position_updates,
        organisation_id=effective_organisation
    )
    
    return {
        "message": f"Position update completed. {result['updated_authorities']} authorities updated",
        **result
    }

@router.post("/bulk/delete", response_model=dict)
async def bulk_delete_authorities(
    delete_data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority)  # writes: authority/super-admin only
):
    """Bulk soft delete authorities"""
    service = AuthorityService(db)

    effective_organisation = delete_data.organisation_id if principal.is_super_admin else principal.organisation_id
    result = await service.bulk_soft_delete(
        authority_ids=delete_data.authority_ids,
        organisation_id=effective_organisation
    )
    
    return {
        "message": f"Bulk delete completed. {result['deleted_authorities']} authorities deactivated",
        **result
    }

@router.get("/statistics/{organisation_id}", response_model=dict)
async def get_authority_statistics(
    organisation_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get comprehensive authority statistics for a organisation"""
    # Non-super-admins may only view stats for their own organisation.
    assert_same_organisation(principal, organisation_id)
    service = AuthorityService(db)

    stats = await service.get_authority_statistics(organisation_id)
    
    return {
        "message": "Authority statistics retrieved successfully",
        **stats
    }
