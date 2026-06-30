# app/routers/organisation.py
"""Organisation (Organisation) management endpoints with bulk operations."""
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
from ..models.organisation import Organisation
from ..services.organisation_service import OrganisationService
from ..schemas.organisation_schemas import Organisation as OrganisationSchema, OrganisationCreate, OrganisationUpdate
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

# BULK OPERATION MODELS WITH VALIDATION
class BulkOrganisationImport(BaseModel):
    organisations: List[dict] = Field(..., min_items=1, max_items=1000, description="List of organisation data")
    
    def __init__(self, **data):
        try:
            super().__init__(**data)
        except Exception as e:
            raise ValueError(f"Invalid bulk import data: {str(e)}")

class BulkStatusUpdate(BaseModel):
    organisation_ids: List[UUID] = Field(..., min_items=1, max_items=100, description="List of organisation IDs")
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
    organisation_ids: List[UUID] = Field(..., min_items=1, max_items=100, description="List of organisation IDs to delete")

router = APIRouter(prefix="/api/v1/organisations", tags=["Organisation Management"])

# EXISTING ENDPOINTS (with OrganisationService)
@router.get("/", response_model=dict)
async def get_organisations(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    include_inactive: bool = Query(False, description="Include deactivated organisations"),
    order_by: str = Query("name", description="Field to order by"),
    sort: str = Query("asc", regex="^(asc|desc)$", description="Sort direction"),
    db: AsyncSession = Depends(get_db)
):
    """Get all organisations with pagination - active organisations by default"""
    try:
        service = OrganisationService(db)
        
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
                "showing": "all organisations" if include_inactive else "active organisations only"
            }
        
        # Handle Pydantic validation errors
        formatted_organisations = []
        validation_errors = []
        
        for i, organisation in enumerate(result["items"]):
            try:
                formatted_organisation = OrganisationSchema.model_validate(organisation)
                formatted_organisations.append(formatted_organisation)
            except Exception as e:
                logger.error("Validation error for organisation %s: %s", i, str(e))
                validation_errors.append(f"Organisation {i}: Invalid data format")
        
        response_data = {
            "items": formatted_organisations,
            "total": result["total"],
            "page": result["page"],
            "size": result["size"],
            "has_next": result["has_next"],
            "has_previous": result["has_previous"],
            "total_pages": result["total_pages"],
            "showing": "all organisations" if include_inactive else "active organisations only"
        }
        
        if validation_errors:
            response_data["warnings"] = validation_errors[:5]  # Limit warnings
        
        return response_data
    except SQLAlchemyError as e:
        # Sanitize error message to avoid log injection and include traceback for operators
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error in get_organisations: %s", sanitized_error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching organisations"
        )
    except Exception as e:
        logger.error("Unexpected error in get_organisations: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )

@router.post("/", response_model=OrganisationSchema)
async def create_organisation(
    organisation_data: OrganisationCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Create a new organisation (organisation). When an admin creates it, the organisation is
    stamped with owner_authority_id = that admin and becomes their active organisation
    if they had none."""
    # Only the platform super-admin or a organisation authority (admin) may create an
    # organisation — not teachers/students/staff (who could otherwise POST here
    # directly and mint unowned organisations).
    if principal.role not in ("super_admin", "authority"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only an admin or the platform super-admin can create an organisation")
    try:
        service = OrganisationService(db)
        
        # Convert validated input data
        organisation_dict = organisation_data.model_dump()
        
        # Check for duplicates before attempting creation
        try:
            email = organisation_dict.get('email')
            phone = organisation_dict.get('phone')
            name = organisation_dict.get('name')
            address = organisation_dict.get('address')
            
            conditions = []
            if email:
                conditions.append(Organisation.email == email)
            if phone:
                conditions.append(Organisation.phone == phone)
            if name and address:
                conditions.append((Organisation.name == name) & (Organisation.address == address))
            
            if conditions:
                stmt = select(Organisation).where(or_(*conditions)).where(Organisation.is_deleted.is_(False))
                result = await db.execute(stmt)
                existing_organisation = result.scalar_one_or_none()
                
                if existing_organisation:
                    # Check which field caused the duplicate
                    if existing_organisation.email == email:
                        conflict_detail = {
                            "error": "Duplicate Email",
                            "message": "An organisation with this email address already exists",
                            "field": "email",
                            "value": email
                        }
                    elif existing_organisation.phone == phone:
                        conflict_detail = {
                            "error": "Duplicate Phone",
                            "message": "An organisation with this phone number already exists",
                            "field": "phone",
                            "value": phone
                        }
                    else:
                        conflict_detail = {
                            "error": "Duplicate Organisation",
                            "message": "An organisation with this name and address already exists",
                            "fields": ["name", "address"],
                            "values": {
                                "name": name,
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
        
        # Generate code if not provided
        if not organisation_dict.get("code"):
            organisation_dict['code'] = await service.generate_code(organisation_dict["name"])
        
        # Create organisation
        organisation = await service.create(organisation_dict)
        if not organisation:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Organisation creation failed - no data returned"
            )

        # Stamp ownership when an admin (authority) creates the organisation, and
        # make it their active organisation if they had none. Super-admin-created organisations
        # are left unowned.
        if principal is not None and not principal.is_super_admin and principal.role == "authority":
            await db.execute(
                text("UPDATE organisations SET owner_authority_id = :oid WHERE id = :tid"),
                {"oid": str(principal.user_id), "tid": str(organisation.id)},
            )
            await db.execute(
                text("UPDATE authorities SET organisation_id = :tid "
                     "WHERE id = :oid AND organisation_id IS NULL"),
                {"tid": str(organisation.id), "oid": str(principal.user_id)},
            )
            await db.commit()

        return organisation
        
    except IntegrityError as e:
        await db.rollback()
        error_message = str(e.orig) if hasattr(e, 'orig') else str(e)
        
        # Handle different types of duplicate errors
        if 'uq_organisation_email' in error_message or 'email' in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Email",
                    "message": "An organisation with this email address already exists",
                    "field": "email",
                    "value": organisation_dict.get("email")
                }
            )
        elif 'uq_organisation_phone' in error_message or 'phone' in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Phone",
                    "message": "An organisation with this phone number already exists",
                    "field": "phone",
                    "value": organisation_dict.get("phone")
                }
            )
        elif 'uq_organisation_name_address' in error_message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Organisation",
                    "message": "An organisation with this name and address already exists",
                    "fields": ["name", "address"],
                    "values": {
                        "name": organisation_dict.get("name"),
                        "address": organisation_dict.get("address")
                    }
                }
            )
        
        if 'uq_organisation_code' in error_message or 'code' in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Organisation Code",
                    "message": "An organisation with this organisation code already exists",
                    "field": "code",
                    "value": organisation_dict.get("code")
                }
            )
        
        # Sanitize error message to prevent log injection and avoid leaking internal details to clients
        sanitized_error = str(error_message).replace('\n', ' ').replace('\r', ' ')[:200]
        # Log full sanitized error for operators (do not return internal details to clients)
        logger.error("Unhandled integrity error creating organisation: %s", sanitized_error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Data Conflict",
                "message": "A conflict occurred with existing organisation data"
            }
        )
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Database error creating organisation: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while creating organisation"
        )
    # amazonq-ignore-next-line
    except Exception as e:
        await db.rollback()
        # Log detailed error information for debugging
        logger.error("Unexpected error creating organisation: %s", str(e), exc_info=True)
        # amazonq-ignore-next-line
        logger.error("Organisation data: %s", organisation_dict)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating organisation"
        )

@router.get("/{organisation_id}", response_model=OrganisationSchema)
async def get_organisation(
    organisation_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific organisation by ID"""
    try:
        service = OrganisationService(db)
        organisation = await service.get(organisation_id)
        if not organisation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail=f"Organisation with ID {organisation_id} not found"
            )
        return organisation
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        # Sanitize error message to prevent log injection
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error getting organisation %s: %s", organisation_id, sanitized_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching organisation"
        )
    except Exception as e:
        logger.error("Unexpected error getting organisation %s: %s", organisation_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )

@router.put("/{organisation_id}", response_model=OrganisationSchema)
async def update_organisation(
    organisation_id: UUID,
    organisation_data: OrganisationUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a organisation by ID"""
    try:
        service = OrganisationService(db)
        
        update_data = organisation_data.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No update data provided"
            )
        
        organisation = await service.update(organisation_id, update_data)
        if not organisation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Organisation not found"
            )
        return organisation
        
    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        raw_error = str(e.orig) if hasattr(e, 'orig') else str(e)
        raw_error_lower = raw_error.lower()
        # sanitize and truncate for logging to avoid log injection
        sanitized_error = raw_error.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        
        if 'uq_organisation_email' in raw_error_lower or 'email' in raw_error_lower:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Email",
                    "message": "Another organisation with this email address already exists",
                    "field": "email"
                }
            )
        elif 'uq_organisation_phone' in raw_error_lower or 'phone' in raw_error_lower:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Phone", 
                    "message": "Another organisation with this phone number already exists",
                    "field": "phone"
                }
            )
        else:
            # Log sanitized details for operators, but return a generic message to clients
            safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
            logger.error("Integrity error updating organisation %s: %s", safe_organisation_id, sanitized_error)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail={
                    "error": "Duplicate Data",
                    "message": "Another organisation with similar information already exists",
                    "info": "Conflict detected; operation not completed"
                }
            )
    except SQLAlchemyError as e:
        await db.rollback()
        safe_error = ' '.join(str(e).splitlines())[:200]  # Sanitize and truncate error message
        safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        # Log sanitized organisation id and include traceback for operators
        logger.error("Database error updating organisation %s: %s", safe_organisation_id, safe_error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while updating organisation"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Unexpected error updating organisation %s: %s", organisation_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating organisation"
        )

@router.delete("/{organisation_id}")
async def delete_organisation(
    organisation_id: UUID,
    hard_delete: bool = Query(False, description="Permanently delete instead of deactivating"),
    db: AsyncSession = Depends(get_db)
):
    """Delete or deactivate a organisation"""
    try:
        service = OrganisationService(db)
        
        if hard_delete:
            success = await service.hard_delete(organisation_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, 
                    detail="Organisation not found"
                )
            return {"message": "Organisation deleted permanently"}
        else:
            success = await service.soft_delete(organisation_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, 
                    detail="Organisation not found"
                )
            return {"message": "Organisation deactivated successfully"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ')
        logger.error("Database error deleting organisation %s: %s", str(organisation_id), sanitized_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while deleting organisation"
        )
    except Exception as e:
        await db.rollback()
        safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Unexpected error deleting organisation %s: %s", safe_organisation_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting organisation"
        )

# EXISTING UTILITY ENDPOINTS
@router.patch("/{organisation_id}/reactivate")
async def reactivate_organisation(
    organisation_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Reactivate a deactivated organisation"""
    try:
        service = OrganisationService(db)
        organisation = await service.update(organisation_id, {"is_active": True, "is_deleted": False})
        if not organisation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Organisation not found"
            )
        return {"message": "Organisation reactivated successfully"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error reactivating organisation %s: %s", safe_organisation_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while reactivating organisation"
        )
    except Exception as e:
        await db.rollback()
        safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Unexpected error reactivating organisation %s: %s", safe_organisation_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while reactivating organisation"
        )

@router.get("/{organisation_id}/stats")
async def get_organisation_stats(
    organisation_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for a specific organisation"""
    try:
        service = OrganisationService(db)
        organisation = await service.get(organisation_id)
        if not organisation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Organisation not found"
            )
        
        return {
            "name": organisation.name,
            "is_active": organisation.is_active,
            "maximum_capacity": organisation.maximum_capacity or 0
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ')
        safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(sanitized_error).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Database error getting organisation stats %s: %s", safe_organisation_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching organisation statistics"
        )
    except Exception as e:
        safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        safe_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Unexpected error getting organisation stats %s: %s", safe_organisation_id, safe_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching organisation statistics"
        )

@router.get("/{organisation_id}/charges", response_model=dict)
async def get_organisation_charges(
    organisation_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get charge details for a specific organisation"""
    try:
        service = OrganisationService(db)
        charges = await service.get_organisation_charges(organisation_id)
        return charges
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        logger.error("Database error getting organisation charges %s: %s", safe_organisation_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching charges"
        )
    except Exception as e:
        safe_organisation_id = str(organisation_id).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:36]
        logger.error("Unexpected error getting organisation charges %s: %s", safe_organisation_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching charges"
        )

# BULK OPERATION ENDPOINTS WITH PROPER ERROR HANDLING

@router.post("/bulk/import", response_model=dict)
async def bulk_import_organisations(
    import_data: BulkOrganisationImport,
    db: AsyncSession = Depends(get_db)
):
    """Bulk import organisations from CSV/JSON data"""
    try:
        service = OrganisationService(db)
        
        result = await service.bulk_import_organisations(
            organisations_data=import_data.organisations
        )
        
        return {
            "message": f"Bulk import completed. {result['successful_imports']} organisations imported successfully",
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
    """Bulk update organisation active status"""
    try:
        service = OrganisationService(db)
        
        result = await service.bulk_update_status(
            organisation_ids=status_data.organisation_ids,
            is_active=status_data.is_active
        )
        
        # Construct message based on result structure
        if isinstance(result, dict) and 'updated_organisations' in result and 'new_status' in result:
            message = f"Status update completed. {result.get('updated_organisations', 0)} organisations updated to '{result.get('new_status', status_data.is_active)}'"
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
    """Bulk update organisation maximum capacity"""
    try:
        service = OrganisationService(db)
        
        result = await service.bulk_update_capacity(
            capacity_updates=capacity_data.capacity_updates
        )
        
        return {
            "message": (
                f"Capacity update completed. {result['updated_organisations']} organisations updated"
                if 'updated_organisations' in result
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
    """Bulk update organisation financial information"""
    try:
        service = OrganisationService(db)
        
        result = await service.bulk_update_financial_info(
            financial_updates=financial_data.financial_updates
        )
        
        return {
            "message": (
                f"Financial update completed. {result['updated_organisations']} organisations updated"
                if isinstance(result, dict) and 'updated_organisations' in result
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
    """Bulk update organisation charges information"""
    try:
        service = OrganisationService(db)
        
        result = await service.bulk_update_charges(
            charges_updates=charges_data.charges_updates
        )
        
        return {
            "message": (
                f"Charges update completed. {result['updated_organisations']} organisations updated"
                if isinstance(result, dict) and 'updated_organisations' in result
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
async def bulk_delete_organisations(
    delete_data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db)
):
    """Bulk soft delete organisations"""
    try:
        service = OrganisationService(db)
        
        result = await service.bulk_soft_delete(
            organisation_ids=delete_data.organisation_ids
        )
        
        return {
            "message": "Bulk delete completed. {} organisations deactivated".format(result.get('deleted_organisations', 0)),
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
    """Get comprehensive organisation statistics optimized for 100k+ users"""
    try:
        result = await db.execute(select(
            func.count(Organisation.id).label('total'),
            func.count().filter(Organisation.is_active == True).label('active'),
            func.sum(Organisation.maximum_capacity),
            func.avg(Organisation.annual_tuition),
            func.count().filter(Organisation.charges_applied == True).label('with_charges'),
            func.avg(Organisation.charges_amount).label('avg_charges')
        ).where(Organisation.is_deleted == False))
        
        stats = result.first()
        total, active, with_charges = stats[0] or 0, stats[1] or 0, stats[4] or 0

        # Platform-wide people counts (students / teachers / admins).
        people = (await db.execute(text(
            """
            SELECT
              (SELECT COUNT(*) FROM members WHERE is_deleted = false AND (profile->>'category') = 'student') AS students,
              (SELECT COUNT(*) FROM members WHERE is_deleted = false AND (profile->>'category') IS DISTINCT FROM 'student') AS teachers,
              (SELECT COUNT(*) FROM authorities
                 WHERE is_deleted = false AND role = 'authority') AS admins,
              (SELECT COUNT(*) FROM authorities
                 WHERE is_deleted = false AND role = 'authority' AND status = 'active') AS admins_active
            """
        ))).first()
        total_students = people[0] or 0
        total_teachers = people[1] or 0
        total_admins = people[2] or 0
        admins_active = people[3] or 0

        # Distribution of organisations by type.
        type_rows = (await db.execute(text(
            "SELECT COALESCE(org_type, 'Unspecified') AS t, COUNT(*) AS c "
            "FROM organisations WHERE is_deleted = false GROUP BY org_type ORDER BY c DESC"
        ))).all()
        org_type_distribution = {r[0]: r[1] for r in type_rows}

        return {
            "total_organisations": total,
            "active_organisations": active,
            "inactive_organisations": total - active,
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
                "organisations_with_charges": with_charges,
                "organisations_without_charges": total - with_charges,
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
            "org_type_distribution": org_type_distribution,
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
async def get_organisations_summary(
    include_inactive: bool = Query(False, description="Include deactivated organisations"),
    limit: int = Query(1000, ge=1, le=5000, description="Maximum number of results"),
    db: AsyncSession = Depends(get_db)
):
    """Get summary of all organisations with optimized response"""
    try:
        # Use direct database projection query for better performance
        stmt = select(
            Organisation.id,
            Organisation.code,
            Organisation.name,
            Organisation.is_active
        ).where(Organisation.is_deleted == False)
        
        if not include_inactive:
            stmt = stmt.where(Organisation.is_active == True)
        
        stmt = stmt.limit(limit)
        
        result = await db.execute(stmt)
        organisations = result.fetchall()
        
        return [
            {
                "id": str(organisation.id),
                "code": organisation.code or "N/A",
                "name": organisation.name or "Unknown Organisation",
                "is_active": bool(organisation.is_active) if organisation.is_active is not None else False
            }
            for organisation in organisations
        ]
    except SQLAlchemyError as e:
        logger.error("Database error getting organisations summary: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching organisations summary"
        )
    except Exception as e:
        logger.error("Unexpected error getting organisations summary: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching organisations summary"
        )

@router.post("/check-duplicate", response_model=dict)
async def check_duplicate_organisation(
    organisation_data: OrganisationCreate,
    db: AsyncSession = Depends(get_db)
):
    """Check if a organisation with similar data already exists"""
    try:
        organisation_dict = organisation_data.model_dump()
        
        # Validate required fields
        email = organisation_dict.get('email')
        phone = organisation_dict.get('phone')
        name = organisation_dict.get('name')
        address = organisation_dict.get('address')
        
        # Normalize string inputs: treat empty/whitespace as None
        def normalize_string(value):
            if isinstance(value, str):
                return value.strip() or None
            return value
        
        email = normalize_string(email)
        if email and email.startswith('mailto:'):
            email = email[7:]
        phone = normalize_string(phone)
        name = normalize_string(name)
        address = normalize_string(address)
        
        # Require at least one identifier: email, phone, or both name and address
        if not (email or phone or (name and address)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide email, phone, or both name and address for duplicate check"
            )
        
        # Build filter conditions only for provided values to avoid invalid comparisons
        conditions = []
        if email:
            conditions.append(Organisation.email == email)
        if phone:
            conditions.append(Organisation.phone == phone)
        if name and address:
            conditions.append((Organisation.name == name) & (Organisation.address == address))
        
        if not conditions:
            # Defensive check: should not happen because of earlier validation
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields provided for duplicate check"
            )
        
        # Check for existing records with same email, phone, or name+address
        # amazonq-ignore-next-line
        try:
            stmt = select(Organisation).where(or_(*conditions)).where(Organisation.is_deleted.is_(False))
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
            existing_organisation = result.scalar_one_or_none()
        except SQLAlchemyError as e:
            sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
            logger.error("Database error executing duplicate check: %s", sanitized_error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error occurred while checking for duplicates"
            )
        
        if existing_organisation:
            return {
                "is_duplicate": True,
                "message": "Similar organisation already exists",
                "existing_organisation": {
                    "id": str(existing_organisation.id),
                    "name": existing_organisation.name,
                    "email": existing_organisation.email,
                    "phone": existing_organisation.phone,
                    "address": existing_organisation.address,
                    "is_active": existing_organisation.is_active
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
        logger.error("Database error checking duplicate organisation: %s", sanitized_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while checking for duplicates"
        )
    except Exception as e:
        # Sanitize error message to prevent log injection
        sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
        logger.error("Unexpected error checking duplicate organisation: %s", sanitized_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while checking for duplicates"
        )
