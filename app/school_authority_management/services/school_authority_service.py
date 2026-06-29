# app/services/school_authority_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from ...services.base_service import BaseService
from ..models.school_authority import SchoolAuthority

class SchoolAuthorityService(BaseService[SchoolAuthority]):
    def __init__(self, db: AsyncSession):
        super().__init__(SchoolAuthority, db)
    
    async def get_by_tenant(self, tenant_id: UUID) -> List[SchoolAuthority]:
        """Get all authorities for a specific tenant/school"""
        stmt = select(self.model).where(
            self.model.tenant_id == tenant_id,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_email(self, email: str) -> Optional[SchoolAuthority]:
        """Get authority by email address"""
        stmt = select(self.model).where(
            self.model.email == email,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_authority_id(self, authority_id: str) -> Optional[SchoolAuthority]:
        """Get authority by their authority_id"""
        stmt = select(self.model).where(
            self.model.authority_id == authority_id,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_active_authorities(self, tenant_id: Optional[UUID] = None) -> List[SchoolAuthority]:
        """Get all active authorities, optionally filtered by tenant"""
        stmt = select(self.model).where(
            self.model.status == "active",
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def create(self, obj_in: dict) -> SchoolAuthority:
        """Create new authority with validation"""
        try:
            # Check if email already exists
            existing = await self.get_by_email(obj_in.get("email"))
            if existing:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Authority with email {obj_in.get('email')} already exists"
                )
            
            # Check if authority_id already exists
            if obj_in.get("authority_id"):
                existing_auth_id = await self.get_by_authority_id(obj_in.get("authority_id"))
                if existing_auth_id:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Authority with ID {obj_in.get('authority_id')} already exists"
                    )
            
            return await super().create(obj_in)
            
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail=f"Database constraint violation: {str(e)}")
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=400, detail=f"Error creating authority: {str(e)}")
    
    async def update_login_time(self, authority_id: UUID) -> Optional[SchoolAuthority]:
        """Update last login time for authority"""
        authority = await self.get(authority_id)
        if authority:
            authority.last_login = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(authority)
        return authority
    
    # BULK OPERATIONS USING RAW SQL FOR HIGH PERFORMANCE
    
    async def bulk_import_authorities(self, authorities_data: List[dict], tenant_id: UUID) -> dict:
        """Bulk import school authorities with duplicate detection"""
        try:
            if not authorities_data:
                raise HTTPException(status_code=400, detail="No authority data provided")
            
            # Check for existing duplicates
            emails = [auth.get("email") for auth in authorities_data if auth.get("email")]
            authority_ids = [auth.get("authority_id") for auth in authorities_data if auth.get("authority_id")]
            
            existing_check_sql = text("""
                SELECT email, authority_id FROM school_authorities 
                WHERE tenant_id = :tenant_id 
                AND (email = ANY(:emails) OR authority_id = ANY(:authority_ids))
                AND is_deleted = false
            """)
            
            result = await self.db.execute(existing_check_sql, {
                "tenant_id": tenant_id,
                "emails": emails,
                "authority_ids": authority_ids
            })
            
            existing_records = result.fetchall()
            existing_emails = {row[0] for row in existing_records}
            existing_auth_ids = {row[1] for row in existing_records}
            
            # Validate and prepare data
            now = datetime.utcnow()
            insert_data = []
            validation_errors = []
            duplicate_errors = []
            
            for idx, authority_data in enumerate(authorities_data):
                try:
                    # Check required fields
                    required_fields = ["authority_id", "first_name", "last_name", "email", "phone", "position"]
                    for field in required_fields:
                        if not authority_data.get(field):
                            validation_errors.append(f"Row {idx + 1}: Missing required field '{field}'")
                            continue
                    
                    # Check for duplicates
                    email = authority_data.get("email")
                    auth_id = authority_data.get("authority_id")
                    
                    if email in existing_emails:
                        duplicate_errors.append(f"Row {idx + 1}: Email '{email}' already exists")
                        continue
                    
                    if auth_id in existing_auth_ids:
                        duplicate_errors.append(f"Row {idx + 1}: Authority ID '{auth_id}' already exists")
                        continue
                    
                    # Parse datetime fields
                    date_of_birth = None
                    if authority_data.get("date_of_birth"):
                        date_of_birth = datetime.fromisoformat(authority_data["date_of_birth"].replace('Z', '+00:00'))
                    
                    joining_date = None
                    if authority_data.get("joining_date"):
                        joining_date = datetime.fromisoformat(authority_data["joining_date"].replace('Z', '+00:00'))
                    
                    authority_record = {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "authority_id": auth_id,
                        "first_name": authority_data["first_name"],
                        "last_name": authority_data["last_name"],
                        "email": email,
                        "phone": authority_data["phone"],
                        "date_of_birth": date_of_birth,
                        "address": authority_data.get("address"),
                        "role": "school_authority",
                        "status": authority_data.get("status", "active"),
                        "position": authority_data["position"],
                        "qualification": authority_data.get("qualification"),
                        "experience_years": authority_data.get("experience_years", 0),
                        "joining_date": joining_date,
                        "authority_details": json.dumps(authority_data.get("authority_details")) if authority_data.get("authority_details") else None,
                        "permissions": json.dumps(authority_data.get("permissions")) if authority_data.get("permissions") else None,
                        "school_overview": json.dumps(authority_data.get("school_overview")) if authority_data.get("school_overview") else None,
                        "contact_info": json.dumps(authority_data.get("contact_info")) if authority_data.get("contact_info") else None,
                        "last_login": None,
                        "created_at": now,
                        "updated_at": now,
                        "is_deleted": False
                    }
                    insert_data.append(authority_record)
                    
                except Exception as e:
                    validation_errors.append(f"Row {idx + 1}: {str(e)}")
            
            # Insert only non-duplicate records
            successful_imports = 0
            if insert_data:
                bulk_insert_sql = text("""
                    INSERT INTO school_authorities (
                        id, tenant_id, authority_id, first_name, last_name, email, phone,
                        date_of_birth, address, role, status, position, qualification,
                        experience_years, joining_date, authority_details, permissions,
                        school_overview, contact_info, last_login, created_at, updated_at, is_deleted
                    ) VALUES (
                        :id, :tenant_id, :authority_id, :first_name, :last_name, :email, :phone,
                        :date_of_birth, :address, :role, :status, :position, :qualification,
                        :experience_years, :joining_date, :authority_details, :permissions,
                        :school_overview, :contact_info, :last_login, :created_at, :updated_at, :is_deleted
                    )
                """)
                
                await self.db.execute(bulk_insert_sql, insert_data)
                await self.db.commit()
                successful_imports = len(insert_data)
            
            return {
                "total_records_processed": len(authorities_data),
                "successful_imports": successful_imports,
                "failed_imports": len(validation_errors) + len(duplicate_errors),
                "duplicate_records": len(duplicate_errors),
                "validation_errors": validation_errors if validation_errors else None,
                "duplicate_errors": duplicate_errors if duplicate_errors else None,
                "tenant_id": str(tenant_id),
                "status": "success" if successful_imports > 0 else "failed"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk import failed: {str(e)}")
    
    async def bulk_update_status(self, authority_ids: List[str], new_status: str, tenant_id: UUID) -> dict:
        """Bulk update authority status using raw SQL"""
        try:
            if not authority_ids:
                raise HTTPException(status_code=400, detail="No authority IDs provided")
            
            valid_statuses = ["active", "inactive", "resigned", "terminated", "on_leave"]
            if new_status not in valid_statuses:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid status. Must be one of: {valid_statuses}"
                )
            
            update_sql = text("""
                UPDATE school_authorities
                SET status = :new_status,
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND authority_id = ANY(:authority_ids)
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                update_sql,
                {
                    "new_status": new_status,
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "authority_ids": authority_ids
                }
            )
            
            await self.db.commit()
            
            return {
                "updated_authorities": result.rowcount,
                "new_status": new_status,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk status update failed: {str(e)}")
    
    async def bulk_update_permissions(self, permission_updates: List[dict], tenant_id: UUID) -> dict:
        """Bulk update authority permissions using raw SQL"""
        try:
            if not permission_updates:
                raise HTTPException(status_code=400, detail="No permission update data provided")
            
            # Get current authorities with their permissions
            authorities_sql = text("""
                SELECT id, authority_id, permissions
                FROM school_authorities
                WHERE tenant_id = :tenant_id
                AND authority_id = ANY(:authority_ids)
                AND is_deleted = false
            """)
            
            authority_ids = [update["authority_id"] for update in permission_updates]
            result = await self.db.execute(
                authorities_sql, 
                {"tenant_id": tenant_id, "authority_ids": authority_ids}
            )
            
            authorities_data = {}
            for row in result.fetchall():
                permissions = row[2] or {}
                if isinstance(permissions, str):
                    permissions = json.loads(permissions)
                authorities_data[row[1]] = {"id": row[0], "permissions": permissions}
            
            # Update permissions for each authority
            updated_count = 0
            for permission_update in permission_updates:
                authority_id = permission_update["authority_id"]
                if authority_id not in authorities_data:
                    continue
                
                current_permissions = authorities_data[authority_id]["permissions"]
                new_permissions = permission_update.get("permissions", {})
                
                # Merge permissions
                current_permissions.update(new_permissions)
                
                # Update authority record
                update_authority_sql = text("""
                    UPDATE school_authorities
                    SET permissions = :permissions,
                        updated_at = :updated_at
                    WHERE id = :authority_id
                """)
                
                await self.db.execute(
                    update_authority_sql,
                    {
                        "permissions": json.dumps(current_permissions),
                        "updated_at": datetime.utcnow(),
                        "authority_id": authorities_data[authority_id]["id"]
                    }
                )
                updated_count += 1
            
            await self.db.commit()
            
            return {
                "updated_authorities": updated_count,
                "total_updates": len(permission_updates),
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk permission update failed: {str(e)}")
    
    async def bulk_update_positions(self, position_updates: List[dict], tenant_id: UUID) -> dict:
        """Bulk update authority positions using individual updates"""
        try:
            if not position_updates:
                raise HTTPException(status_code=400, detail="No position update data provided")
            
            updated_count = 0
            
            for update in position_updates:
                authority_id = update["authority_id"]
                new_position = update["new_position"]
                
                update_sql = text("""
                    UPDATE school_authorities 
                    SET position = :new_position,
                        updated_at = :updated_at
                    WHERE tenant_id = :tenant_id
                    AND authority_id = :authority_id
                    AND is_deleted = false
                """)
                
                result = await self.db.execute(
                    update_sql,
                    {
                        "new_position": new_position,
                        "updated_at": datetime.utcnow(),
                        "tenant_id": tenant_id,
                        "authority_id": authority_id
                    }
                )
                
                if result.rowcount > 0:
                    updated_count += 1
            
            await self.db.commit()
            
            return {
                "updated_authorities": updated_count,
                "total_requests": len(position_updates),
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk position update failed: {str(e)}")
    
    async def bulk_soft_delete(self, authority_ids: List[str], tenant_id: UUID) -> dict:
        """Bulk soft delete authorities using raw SQL"""
        try:
            if not authority_ids:
                raise HTTPException(status_code=400, detail="No authority IDs provided")
            
            delete_sql = text("""
                UPDATE school_authorities
                SET is_deleted = true,
                    status = 'inactive',
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND authority_id = ANY(:authority_ids)
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                delete_sql,
                {
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "authority_ids": authority_ids
                }
            )
            
            await self.db.commit()
            
            return {
                "deleted_authorities": result.rowcount,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")
    
    async def get_authority_statistics(self, tenant_id: UUID) -> dict:
        """Get comprehensive authority statistics using raw SQL for performance"""
        try:
            stats_sql = text("""
                SELECT 
                    COUNT(*) as total_authorities,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active_authorities,
                    COUNT(CASE WHEN status = 'inactive' THEN 1 END) as inactive_authorities,
                    COUNT(CASE WHEN status = 'resigned' THEN 1 END) as resigned_authorities,
                    COUNT(CASE WHEN status = 'terminated' THEN 1 END) as terminated_authorities,
                    COUNT(CASE WHEN status = 'on_leave' THEN 1 END) as on_leave_authorities,
                    AVG(experience_years) as average_experience,
                    MIN(joining_date) as earliest_joining,
                    MAX(joining_date) as latest_joining
                FROM school_authorities
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
            """)
            
            result = await self.db.execute(stats_sql, {"tenant_id": tenant_id})
            stats = result.fetchone()
            
            # Get position-wise distribution
            position_distribution_sql = text("""
                SELECT position, COUNT(*) as authority_count
                FROM school_authorities
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
                AND status = 'active'
                GROUP BY position
                ORDER BY authority_count DESC
            """)
            
            position_result = await self.db.execute(position_distribution_sql, {"tenant_id": tenant_id})
            position_distribution = {row[0]: row[1] for row in position_result.fetchall()}
            
            return {
                "total_authorities": stats[0] or 0,
                "active_authorities": stats[1] or 0,
                "inactive_authorities": stats[2] or 0,
                "resigned_authorities": stats[3] or 0,
                "terminated_authorities": stats[4] or 0,
                "on_leave_authorities": stats[5] or 0,
                "average_experience": float(stats[6]) if stats[6] else 0.0,
                "earliest_joining": stats[7].isoformat() if stats[7] else None,
                "latest_joining": stats[8].isoformat() if stats[8] else None,
                "position_distribution": position_distribution,
                "tenant_id": str(tenant_id)
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")
