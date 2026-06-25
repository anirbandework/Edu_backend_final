# app/routers/tenant.py
"""Tenant (School) management endpoints with bulk operations."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import select, or_, and_
from pydantic import BaseModel, Field

from ...core.database import get_db
from ..models.tenant import Tenant
from ..services.tenant_service import TenantService
from ..schemas.tenant_schemas import Tenant as TenantSchema, TenantCreate, TenantUpdate
from sqlalchemy import func, text
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal

logger = logging.getLogger(__name__)

# Helper functions for safe calculations
def _safe_percentage(numerator, denominator):
    try:
        if denominator and denominator > 0 and numerator is not None:
            return round((numerator / denominator * 100), 2)
    except (ZeroDivisionError, TypeError, ValueError):
        pass
    return 0.0

def _safe_ratio(numerator, denominator):
    try:
        if denominator and denominator > 0 and numerator is not None:
            return round((numerator / denominator), 2)
    except (ZeroDivisionError, TypeError, ValueError):
        pass
    return 0.0

# BULK OPERATION MODELS WITH VALIDATION
class BulkTenantImport(BaseModel):
    tenants: List[dict] = Field(..., min_items=1, max_items=1000, description="List of tenant data")
    
    def __init__(self, **data):
        try:
            super().__init__(**data)
        except Exception as e:
            raise ValueError(f"Invalid bulk import data: {str(e)}")

class BulkStatusUpdate(BaseModel):
    tenant_ids: List[UUID] = Field(..., min_items=1, max_items=100, description="List of tenant IDs")
    is_active: bool = Field(..., description="New active status")
    
    def __init__(self, **data):
        try:
            super().__init__(**data)
        except Exception as e:
            raise ValueError(f"Invalid status update data: {str(e)}")

class BulkCapacityUpdate(BaseModel):
    capacity_updates: List[dict] = Field(..., min_items=1, max_items=100, description="Capacity updates")

class BulkFinancialUpdate(BaseModel):
    financial_updates: List[dict] = Field(..., min_items=1, max_items=100, description="Financial updates")

class BulkChargesUpdate(BaseModel):
    charges_updates: List[dict] = Field(..., min_items=1, max_items=100, description="Charges updates")

class BulkDeleteRequest(BaseModel):
    tenant_ids: List[UUID] = Field(..., min_items=1, max_items=100, description="List of tenant IDs to delete")

router = APIRouter(prefix="/api/v1/tenants", tags=["Tenant Management"])

# EXISTING ENDPOINTS (with TenantService)
@router.get("/", response_model=dict)
async def get_tenants(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    include_inactive: bool = Query(False, description="Include deactivated schools"),
    order_by: str = Query("school_name", description="Field to order by"),
    sort: str = Query("asc", regex="^(asc|desc)$", description="Sort direction"),
    db: AsyncSession = Depends(get_db)
):
    """Get all tenants with pagination - active tenants by default"""
    try:
        service = TenantService(db)
        
        # Build filters
        filters = {}
        if not include_inactive:
            filters["is_active"] = True
        
        result = await service.get_paginated(
            page=page, 
            size=size, 
            order_by=order_by,
            sort=sort,
            **filters
        )
        
        if not result or "items" not in result:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "size": size,
                "has_next": False,
                "has_previous": False,
                "total_pages": 0,
                "showing": "all schools" if include_inactive else "active schools only"
            }
        
        # Handle Pydantic validation errors
        formatted_tenants = []
        validation_errors = []
        
        for i, tenant in enumerate(result["items"]):
            try:
                formatted_tenant = TenantSchema.model_validate(tenant)
                formatted_tenants.append(formatted_tenant)
            except Exception as e:
                logger.error("Validation error for tenant %s: %s", i, str(e))
                validation_errors.append(f"Tenant {i}: Invalid data format")
        
        response_data = {
            "items": formatted_tenants,
            "total": result["total"],
            "page": result["page"],
            "size": result["size"],
            "has_next": result["has_next"],
            "has_previous": result["has_previous"],
            "total_pages": result["total_pages"],
            "showing": "all schools" if include_inactive else "active schools only"
        }
        
        if validation_errors:
            response_data["warnings"] = validation_errors[:5]  # Limit warnings
        
        return response_data
    except SQLAlchemyError as e:
        # Sanitize error message to avoid log injection and include traceback for operators
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error in get_tenants: %s", sanitized_error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching tenants"
        )
    except Exception as e:
        logger.error("Unexpected error in get_tenants: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )

@router.post("/", response_model=TenantSchema)
async def create_tenant(
    tenant_data: TenantCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Create a new tenant (school). When an admin creates it, the school is
    stamped with owner_authority_id = that admin and becomes their active school
    if they had none."""
    try:
        service = TenantService(db)
        
        # Convert validated input data
        tenant_dict = tenant_data.model_dump()
        
        # Check for duplicates before attempting creation
        try:
            email = tenant_dict.get('email')
            phone = tenant_dict.get('phone')
            school_name = tenant_dict.get('school_name')
            address = tenant_dict.get('address')
            
            conditions = []
            if email:
                conditions.append(Tenant.email == email)
            if phone:
                conditions.append(Tenant.phone == phone)
            if school_name and address:
                conditions.append((Tenant.school_name == school_name) & (Tenant.address == address))
            
            if conditions:
                stmt = select(Tenant).where(or_(*conditions)).where(Tenant.is_deleted.is_(False))
                result = await db.execute(stmt)
                existing_tenant = result.scalar_one_or_none()
                
                if existing_tenant:
                    # Check which field caused the duplicate
                    if existing_tenant.email == email:
                        conflict_detail = {
                            "error": "Duplicate Email",
                            "message": "A school with this email address already exists",
                            "field": "email",
                            "value": email
                        }
                    elif existing_tenant.phone == phone:
                        conflict_detail = {
                            "error": "Duplicate Phone",
                            "message": "A school with this phone number already exists",
                            "field": "phone",
                            "value": phone
                        }
                    else:
                        conflict_detail = {
                            "error": "Duplicate School",
                            "message": "A school with this name and address already exists",
                            "fields": ["school_name", "address"],
                            "values": {
                                "school_name": school_name,
                                "address": address
                            }
                        }
                    
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=conflict_detail
                    )
        except HTTPException:
            raise
        except Exception as dup_error:
            logger.error("Error during duplicate check: %s", str(dup_error), exc_info=True)
            # Continue with creation attempt if duplicate check fails
        
        # Generate school_code if not provided
        if not tenant_dict.get("school_code"):
            tenant_dict['school_code'] = await service.generate_school_code(tenant_dict["school_name"])
        
        # Create tenant
        tenant = await service.create(tenant_dict)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Tenant creation failed - no data returned"
            )

        # Stamp ownership when an admin (school_authority) creates the school, and
        # make it their active school if they had none. Super-admin-created schools
        # are left unowned.
        if principal is not None and not principal.is_super_admin and principal.role == "school_authority":
            await db.execute(
                text("UPDATE tenants SET owner_authority_id = :oid WHERE id = :tid"),
                {"oid": str(principal.user_id), "tid": str(tenant.id)},
            )
            await db.execute(
                text("UPDATE school_authorities SET tenant_id = :tid "
                     "WHERE id = :oid AND tenant_id IS NULL"),
                {"tid": str(tenant.id), "oid": str(principal.user_id)},
            )
            await db.commit()

        return tenant
        
    except IntegrityError as e:
        await db.rollback()
        error_message = str(e.orig) if hasattr(e, 'orig') else str(e)
        
        # Handle different types of duplicate errors
        if 'uq_tenant_email' in error_message or 'email' in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Email",
                    "message": "A school with this email address already exists",
                    "field": "email",
                    "value": tenant_dict.get("email")
                }
            )
        elif 'uq_tenant_phone' in error_message or 'phone' in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Phone",
                    "message": "A school with this phone number already exists",
                    "field": "phone",
                    "value": tenant_dict.get("phone")
                }
            )
        elif 'uq_tenant_school_name_address' in error_message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate School",
                    "message": "A school with this name and address already exists",
                    "fields": ["school_name", "address"],
                    "values": {
                        "school_name": tenant_dict.get("school_name"),
                        "address": tenant_dict.get("address")
                    }
                }
            )
        
        if 'uq_tenant_school_code' in error_message or 'school_code' in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate School Code",
                    "message": "A school with this school code already exists",
                    "field": "school_code",
                    "value": tenant_dict.get("school_code")
                }
            )
        
        # Sanitize error message to prevent log injection and avoid leaking internal details to clients
        sanitized_error = str(error_message).replace('\n', ' ').replace('\r', ' ')[:200]
        # Log full sanitized error for operators (do not return internal details to clients)
        logger.error("Unhandled integrity error creating tenant: %s", sanitized_error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Data Conflict",
                "message": "A conflict occurred with existing school data"
            }
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Database error creating tenant: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while creating tenant"
        )
    # amazonq-ignore-next-line
    except Exception as e:
        await db.rollback()
        # Log detailed error information for debugging
        logger.error("Unexpected error creating tenant: %s", str(e), exc_info=True)
        # amazonq-ignore-next-line
        logger.error("Tenant data: %s", tenant_dict)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating tenant"
        )

@router.get("/{tenant_id}", response_model=TenantSchema)
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific tenant by ID"""
    try:
        service = TenantService(db)
        tenant = await service.get(tenant_id)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail=f"School with ID {tenant_id} not found"
            )
        return tenant
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        # Sanitize error message to prevent log injection
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error getting tenant %s: %s", tenant_id, sanitized_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching tenant"
        )
    except Exception as e:
        logger.error("Unexpected error getting tenant %s: %s", tenant_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )

@router.put("/{tenant_id}", response_model=TenantSchema)
async def update_tenant(
    tenant_id: UUID,
    tenant_data: TenantUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a tenant by ID"""
    try:
        service = TenantService(db)
        
        update_data = tenant_data.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No update data provided"
            )
        
        tenant = await service.update(tenant_id, update_data)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="School not found"
            )
        return tenant
        
    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        raw_error = str(e.orig) if hasattr(e, 'orig') else str(e)
        raw_error_lower = raw_error.lower()
        # sanitize and truncate for logging to avoid log injection
        sanitized_error = raw_error.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        
        if 'uq_tenant_email' in raw_error_lower or 'email' in raw_error_lower:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Email",
                    "message": "Another school with this email address already exists",
                    "field": "email"
                }
            )
        elif 'uq_tenant_phone' in raw_error_lower or 'phone' in raw_error_lower:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Phone", 
                    "message": "Another school with this phone number already exists",
                    "field": "phone"
                }
            )
        else:
            # Log sanitized details for operators, but return a generic message to clients
            safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
            logger.error("Integrity error updating tenant %s: %s", safe_tenant_id, sanitized_error)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Data",
                    "message": "Another school with similar information already exists",
                    "info": "Conflict detected; operation not completed"
                }
            )
    except SQLAlchemyError as e:
        await db.rollback()
        safe_error = ' '.join(str(e).splitlines())[:200]  # Sanitize and truncate error message
        safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        # Log sanitized tenant id and include traceback for operators
        logger.error("Database error updating tenant %s: %s", safe_tenant_id, safe_error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while updating tenant"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Unexpected error updating tenant %s: %s", tenant_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating tenant"
        )

@router.delete("/{tenant_id}")
async def delete_tenant(
    tenant_id: UUID,
    hard_delete: bool = Query(False, description="Permanently delete instead of deactivating"),
    db: AsyncSession = Depends(get_db)
):
    """Delete or deactivate a tenant"""
    try:
        service = TenantService(db)
        
        if hard_delete:
            success = await service.hard_delete(tenant_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, 
                    detail="School not found"
                )
            return {"message": "School deleted permanently"}
        else:
            success = await service.soft_delete(tenant_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, 
                    detail="School not found"
                )
            return {"message": "School deactivated successfully"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ')
        logger.error("Database error deleting tenant %s: %s", str(tenant_id), sanitized_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while deleting tenant"
        )
    except Exception as e:
        await db.rollback()
        safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Unexpected error deleting tenant %s: %s", safe_tenant_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting tenant"
        )

# EXISTING UTILITY ENDPOINTS
@router.patch("/{tenant_id}/reactivate")
async def reactivate_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Reactivate a deactivated school"""
    try:
        service = TenantService(db)
        tenant = await service.update(tenant_id, {"is_active": True, "is_deleted": False})
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="School not found"
            )
        return {"message": "School reactivated successfully"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error reactivating tenant %s: %s", safe_tenant_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while reactivating tenant"
        )
    except Exception as e:
        await db.rollback()
        safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Unexpected error reactivating tenant %s: %s", safe_tenant_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while reactivating tenant"
        )

@router.get("/{tenant_id}/stats")
async def get_tenant_stats(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for a specific tenant"""
    try:
        service = TenantService(db)
        tenant = await service.get(tenant_id)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="School not found"
            )
        
        return {
            "school_name": tenant.school_name,
            "is_active": tenant.is_active,
            "maximum_capacity": tenant.maximum_capacity or 0
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ')
        safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(sanitized_error).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error getting tenant stats %s: %s", safe_tenant_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching tenant statistics"
        )
    except Exception as e:
        safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Unexpected error getting tenant stats %s: %s", safe_tenant_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching tenant statistics"
        )

@router.get("/{tenant_id}/charges", response_model=dict)
async def get_tenant_charges(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get charge details for a specific tenant"""
    try:
        service = TenantService(db)
        charges = await service.get_tenant_charges(tenant_id)
        return charges
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        logger.error("Database error getting tenant charges %s: %s", safe_tenant_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching charges"
        )
    except Exception as e:
        safe_tenant_id = str(tenant_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        logger.error("Unexpected error getting tenant charges %s: %s", safe_tenant_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching charges"
        )

# BULK OPERATION ENDPOINTS WITH PROPER ERROR HANDLING

@router.post("/bulk/import", response_model=dict)
async def bulk_import_tenants(
    import_data: BulkTenantImport,
    db: AsyncSession = Depends(get_db)
):
    """Bulk import tenants from CSV/JSON data"""
    try:
        service = TenantService(db)
        
        result = await service.bulk_import_tenants(
            tenants_data=import_data.tenants
        )
        
        return {
            "message": f"Bulk import completed. {result['successful_imports']} schools imported successfully",
            **result
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        # amazonq-ignore-next-line
        logger.error("Database error in bulk import: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred during bulk import"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Unexpected error in bulk import: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during bulk import"
        )

@router.post("/bulk/update-status", response_model=dict)
async def bulk_update_status(
    status_data: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Bulk update tenant active status"""
    try:
        service = TenantService(db)
        
        result = await service.bulk_update_status(
            tenant_ids=status_data.tenant_ids,
            is_active=status_data.is_active
        )
        
        # Construct message based on result structure
        if isinstance(result, dict) and 'updated_tenants' in result and 'new_status' in result:
            message = f"Status update completed. {result.get('updated_tenants', 0)} schools updated to '{result.get('new_status', status_data.is_active)}'"
        else:
            message = "Status update completed."
        
        return {
            "message": message,
            **result
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Database error in bulk status update: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred during bulk status update"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Unexpected error in bulk status update: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during bulk status update"
        )

@router.post("/bulk/update-capacity", response_model=dict)
async def bulk_update_capacity(
    capacity_data: BulkCapacityUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Bulk update tenant maximum capacity"""
    try:
        service = TenantService(db)
        
        result = await service.bulk_update_capacity(
            capacity_updates=capacity_data.capacity_updates
        )
        
        return {
            "message": (
                f"Capacity update completed. {result['updated_tenants']} schools updated"
                if 'updated_tenants' in result
                else "Capacity update completed."
            ),
            **result
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Database error in bulk capacity update: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred during bulk capacity update"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Unexpected error in bulk capacity update: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during bulk capacity update"
        )

@router.post("/bulk/update-financial", response_model=dict)
async def bulk_update_financial(
    financial_data: BulkFinancialUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Bulk update tenant financial information"""
    try:
        service = TenantService(db)
        
        result = await service.bulk_update_financial_info(
            financial_updates=financial_data.financial_updates
        )
        
        return {
            "message": (
                f"Financial update completed. {result['updated_tenants']} schools updated"
                if isinstance(result, dict) and 'updated_tenants' in result
                else "Financial update completed."
            ),
            **result
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Database error in bulk financial update: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred during bulk financial update"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Unexpected error in bulk financial update: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during bulk financial update"
        )

@router.post("/bulk/update-charges", response_model=dict)
async def bulk_update_charges(
    charges_data: BulkChargesUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Bulk update tenant charges information"""
    try:
        service = TenantService(db)
        
        result = await service.bulk_update_charges(
            charges_updates=charges_data.charges_updates
        )
        
        return {
            "message": (
                f"Charges update completed. {result['updated_tenants']} schools updated"
                if isinstance(result, dict) and 'updated_tenants' in result
                else "Charges update completed."
            ),
            **result
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Database error in bulk charges update: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred during bulk charges update"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Unexpected error in bulk charges update: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during bulk charges update"
        )



@router.post("/bulk/delete", response_model=dict)
async def bulk_delete_tenants(
    delete_data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db)
):
    """Bulk soft delete tenants"""
    try:
        service = TenantService(db)
        
        result = await service.bulk_soft_delete(
            tenant_ids=delete_data.tenant_ids
        )
        
        return {
            "message": "Bulk delete completed. {} schools deactivated".format(result.get('deleted_tenants', 0)),
            **result
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Database error in bulk delete: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred during bulk delete"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Unexpected error in bulk delete: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during bulk delete"
        )

# amazonq-ignore-next-line
# amazonq-ignore-next-line
@router.get("/analytics/comprehensive")
async def get_comprehensive_statistics(
    db: AsyncSession = Depends(get_db)
):
    """Get comprehensive tenant statistics optimized for 100k+ users"""
    try:
        result = await db.execute(select(
            func.count(Tenant.id).label('total'),
            func.count().filter(Tenant.is_active == True).label('active'),
            func.sum(Tenant.maximum_capacity),
            func.avg(Tenant.annual_tuition),
            func.count().filter(Tenant.charges_applied == True).label('with_charges'),
            func.avg(Tenant.charges_amount).label('avg_charges')
        ).where(Tenant.is_deleted == False))
        
        stats = result.first()
        total, active, with_charges = stats[0] or 0, stats[1] or 0, stats[4] or 0

        # Platform-wide people counts (students / teachers / admins).
        people = (await db.execute(text(
            """
            SELECT
              (SELECT COUNT(*) FROM students WHERE is_deleted = false) AS students,
              (SELECT COUNT(*) FROM teachers WHERE is_deleted = false) AS teachers,
              (SELECT COUNT(*) FROM school_authorities
                 WHERE is_deleted = false AND role = 'school_authority') AS admins,
              (SELECT COUNT(*) FROM school_authorities
                 WHERE is_deleted = false AND role = 'school_authority' AND status = 'active') AS admins_active
            """
        ))).first()
        total_students = people[0] or 0
        total_teachers = people[1] or 0
        total_admins = people[2] or 0
        admins_active = people[3] or 0

        # Distribution of schools by type.
        type_rows = (await db.execute(text(
            "SELECT COALESCE(school_type, 'Unspecified') AS t, COUNT(*) AS c "
            "FROM tenants WHERE is_deleted = false GROUP BY school_type ORDER BY c DESC"
        ))).all()
        school_type_distribution = {r[0]: r[1] for r in type_rows}

        return {
            "total_tenants": total,
            "active_tenants": active,
            "inactive_tenants": total - active,
            "activation_rate": _safe_percentage(active, total),
            "total_capacity": int(stats[2] or 0),
            "average_tuition": stats[3] or 0.0,
            "total_students": total_students,
            "total_teachers": total_teachers,
            "total_admins": total_admins,
            "active_admins": admins_active,
            "inactive_admins": total_admins - admins_active,
            "capacity_utilization": _safe_percentage(total_students, int(stats[2] or 0)),
            "charges_summary": {
                "tenants_with_charges": with_charges,
                "tenants_without_charges": total - with_charges,
                "charges_applied_rate": _safe_percentage(with_charges, total),
                "average_charges_amount": float(stats[5]) if stats[5] else 0.0
            },
            "financial_summary": {
                "total_annual_revenue": 0.0,
                "average_tuition": stats[3] or 0.0,
                "average_registration_fee": 0.0,
                "average_charges": float(stats[5]) if stats[5] else 0.0,
                "tuition_range": {"min": 0.0, "max": 0.0}
            },
            "school_type_distribution": school_type_distribution,
            "language_distribution": {}
        }
    except SQLAlchemyError as e:
        logger.error("Database error in comprehensive analytics: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching analytics"
        )
    except Exception as e:
        logger.error("Unexpected error in comprehensive analytics: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching analytics"
        )

# EXISTING SUMMARY ENDPOINTS
@router.get("/summary/all")
async def get_tenants_summary(
    include_inactive: bool = Query(False, description="Include deactivated schools"),
    limit: int = Query(1000, ge=1, le=5000, description="Maximum number of results"),
    db: AsyncSession = Depends(get_db)
):
    """Get summary of all tenants with optimized response"""
    try:
        # Use direct database projection query for better performance
        stmt = select(
            Tenant.id,
            Tenant.school_code,
            Tenant.school_name,
            Tenant.is_active
        ).where(Tenant.is_deleted == False)
        
        if not include_inactive:
            stmt = stmt.where(Tenant.is_active == True)
        
        stmt = stmt.limit(limit)
        
        result = await db.execute(stmt)
        tenants = result.fetchall()
        
        return [
            {
                "id": str(tenant.id),
                "school_code": tenant.school_code or "N/A",
                "school_name": tenant.school_name or "Unknown School",
                "is_active": bool(tenant.is_active) if tenant.is_active is not None else False
            }
            for tenant in tenants
        ]
    except SQLAlchemyError as e:
        logger.error("Database error getting tenants summary: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching tenants summary"
        )
    except Exception as e:
        logger.error("Unexpected error getting tenants summary: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching tenants summary"
        )

@router.post("/check-duplicate", response_model=dict)
async def check_duplicate_tenant(
    tenant_data: TenantCreate,
    db: AsyncSession = Depends(get_db)
):
    """Check if a tenant with similar data already exists"""
    try:
        tenant_dict = tenant_data.model_dump()
        
        # Validate required fields
        email = tenant_dict.get('email')
        phone = tenant_dict.get('phone')
        school_name = tenant_dict.get('school_name')
        address = tenant_dict.get('address')
        
        # Normalize string inputs: treat empty/whitespace as None
        def normalize_string(value):
            if isinstance(value, str):
                return value.strip() or None
            return value
        
        email = normalize_string(email)
        if email and email.startswith('mailto:'):
            email = email[7:]
        phone = normalize_string(phone)
        school_name = normalize_string(school_name)
        address = normalize_string(address)
        
        # Require at least one identifier: email, phone, or both school_name and address
        if not (email or phone or (school_name and address)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide email, phone, or both school_name and address for duplicate check"
            )
        
        # Build filter conditions only for provided values to avoid invalid comparisons
        conditions = []
        if email:
            conditions.append(Tenant.email == email)
        if phone:
            conditions.append(Tenant.phone == phone)
        if school_name and address:
            conditions.append((Tenant.school_name == school_name) & (Tenant.address == address))
        
        if not conditions:
            # Defensive check: should not happen because of earlier validation
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields provided for duplicate check"
            )
        
        # Check for existing records with same email, phone, or name+address
        # amazonq-ignore-next-line
        try:
            stmt = select(Tenant).where(or_(*conditions)).where(Tenant.is_deleted.is_(False))
        except (ValueError, TypeError) as e:
            # Sanitize error message to prevent log injection
            sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
            logger.error("Error constructing duplicate check filter: %s", sanitized_error)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid data provided for duplicate check"
            )
        
        try:
            result = await db.execute(stmt)
            existing_tenant = result.scalar_one_or_none()
        except SQLAlchemyError as e:
            sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
            logger.error("Database error executing duplicate check: %s", sanitized_error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error occurred while checking for duplicates"
            )
        
        if existing_tenant:
            return {
                "is_duplicate": True,
                "message": "Similar school already exists",
                "existing_school": {
                    "id": str(existing_tenant.id),
                    "school_name": existing_tenant.school_name,
                    "email": existing_tenant.email,
                    "phone": existing_tenant.phone,
                    "address": existing_tenant.address,
                    "is_active": existing_tenant.is_active
                }
            }
        else:
            return {
                "is_duplicate": False,
                "message": "No duplicate found, safe to create"
            }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        # Sanitize error message to prevent log injection
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error checking duplicate tenant: %s", sanitized_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while checking for duplicates"
        )
    except Exception as e:
        # Sanitize error message to prevent log injection
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Unexpected error checking duplicate tenant: %s", sanitized_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while checking for duplicates"
        )
