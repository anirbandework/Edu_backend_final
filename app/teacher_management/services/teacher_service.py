# app/services/teacher_service.py
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
from ..models.teacher import Teacher

class TeacherService(BaseService[Teacher]):
    def __init__(self, db: AsyncSession):
        super().__init__(Teacher, db)
    
    async def get_by_tenant(self, tenant_id: UUID) -> List[Teacher]:
        """Get all teachers for a specific tenant/school"""
        stmt = select(self.model).where(
            self.model.tenant_id == tenant_id,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_teacher_id(self, teacher_id: str, tenant_id: Optional[UUID] = None) -> Optional[Teacher]:
        """Get teacher by their teacher_id"""
        stmt = select(self.model).where(
            self.model.teacher_id == teacher_id,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_email(self, email: str) -> Optional[Teacher]:
        """Get a teacher by the canonical (indexed) email column — a single indexed lookup.

        Previously the fallback loaded EVERY teacher into memory and scanned the JSON in
        Python (fatal at 100k rows). The `email` column is authoritative: create() and
        bulk_import populate it (create() even hoists the address out of personal_info JSON
        before calling here), so a column lookup is both correct and index-backed."""
        stmt = (
            select(self.model)
            .where(self.model.email == email, self.model.is_deleted == False)
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()
    
    async def get_active_teachers(self, tenant_id: Optional[UUID] = None) -> List[Teacher]:
        """Get all active teachers, optionally filtered by tenant"""
        stmt = select(self.model).where(
            self.model.status == "active",
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_teachers_by_subject(self, subject: str, tenant_id: Optional[UUID] = None) -> List[Teacher]:
        """Get teachers who teach a specific subject"""
        stmt = select(self.model).where(self.model.is_deleted == False)
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
        
        result = await self.db.execute(stmt)
        teachers = result.scalars().all()
        subject_teachers = []
        
        for teacher in teachers:
            assignments = (teacher.academic_responsibilities.get('teaching_assignments', []) 
                         if teacher.academic_responsibilities else [])
            for assignment in assignments:
                if assignment.get('subject', '').lower() == subject.lower():
                    subject_teachers.append(teacher)
                    break
        
        return subject_teachers
    
    async def create(self, obj_in: dict) -> Teacher:
        """Create new teacher with validation"""
        try:
            # Check if teacher_id already exists for the tenant
            if obj_in.get("teacher_id") and obj_in.get("tenant_id"):
                existing = await self.get_by_teacher_id(obj_in.get("teacher_id"), obj_in.get("tenant_id"))
                if existing:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Teacher with ID {obj_in.get('teacher_id')} already exists for this school"
                    )
            
            # Check email uniqueness if provided (check both individual field and JSON)
            email = obj_in.get("email")
            if not email:
                personal_info = obj_in.get("personal_info", {})
                if personal_info and personal_info.get("contact_info", {}).get("primary_email"):
                    email = personal_info["contact_info"]["primary_email"]
            
            if email:
                existing_email = await self.get_by_email(email)
                if existing_email:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Teacher with email {email} already exists"
                    )
            
            return await super().create(obj_in)

        except HTTPException:
            await self.db.rollback()
            raise  # preserve 400/409 from the duplicate checks above (don't re-wrap)
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Teacher already exists")
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_teachers_paginated(
        self,
        page: int = 1,
        size: int = 20,
        tenant_id: Optional[UUID] = None
    ) -> dict:
        """Get paginated teachers ordered alphabetically by first name"""
        filters = {}
        if tenant_id:
            filters["tenant_id"] = tenant_id
            
        return await self.get_paginated(
            page=page, 
            size=size, 
            order_by="first_name", 
            sort="asc", 
            **filters
        )
    
    async def update_login_time(self, teacher_id: UUID) -> Optional[Teacher]:
        """Update last login time for teacher"""
        teacher = await self.get(teacher_id)
        if teacher:
            teacher.last_login = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(teacher)
        return teacher
    
    # BULK OPERATIONS USING RAW SQL FOR HIGH PERFORMANCE
    
    async def bulk_import_teachers(self, teachers_data: List[dict], tenant_id: UUID) -> dict:
        """Bulk import teachers with duplicate detection using raw SQL"""
        try:
            if not teachers_data:
                raise HTTPException(status_code=400, detail="No teacher data provided")
            
            # Check for existing duplicates
            emails = [teacher.get("email") for teacher in teachers_data if teacher.get("email")]
            teacher_ids = [teacher.get("teacher_id") for teacher in teachers_data if teacher.get("teacher_id")]
            
            existing_check_sql = text("""
                SELECT email, teacher_id FROM teachers 
                WHERE tenant_id = :tenant_id 
                AND (email = ANY(:emails) OR teacher_id = ANY(:teacher_ids))
                AND is_deleted = false
            """)
            
            result = await self.db.execute(existing_check_sql, {
                "tenant_id": tenant_id,
                "emails": emails,
                "teacher_ids": teacher_ids
            })
            
            existing_records = result.fetchall()
            existing_emails = {row[0] for row in existing_records if row[0]}
            existing_teacher_ids = {row[1] for row in existing_records if row[1]}
            
            # Validate and prepare data
            now = datetime.utcnow()
            insert_data = []
            validation_errors = []
            duplicate_errors = []
            
            for idx, teacher_data in enumerate(teachers_data):
                try:
                    # Check required fields
                    required_fields = ["teacher_id"]
                    for field in required_fields:
                        if not teacher_data.get(field):
                            validation_errors.append(f"Row {idx + 1}: Missing required field '{field}'")
                            continue
                    
                    # Check for duplicates
                    email = teacher_data.get("email")
                    teacher_id = teacher_data.get("teacher_id")
                    
                    if email and email in existing_emails:
                        duplicate_errors.append(f"Row {idx + 1}: Email '{email}' already exists")
                        continue
                    
                    if teacher_id in existing_teacher_ids:
                        duplicate_errors.append(f"Row {idx + 1}: Teacher ID '{teacher_id}' already exists")
                        continue
                    
                    # Parse datetime fields
                    date_of_birth = None
                    if teacher_data.get("date_of_birth"):
                        date_of_birth = datetime.fromisoformat(teacher_data["date_of_birth"].replace('Z', '+00:00'))
                    
                    joining_date = None
                    if teacher_data.get("joining_date"):
                        joining_date = datetime.fromisoformat(teacher_data["joining_date"].replace('Z', '+00:00'))
                    
                    teacher_record = {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "teacher_id": teacher_id,
                        "first_name": teacher_data.get("first_name"),
                        "last_name": teacher_data.get("last_name"),
                        "email": email,
                        "phone": teacher_data.get("phone"),
                        "date_of_birth": date_of_birth,
                        "gender": teacher_data.get("gender"),
                        "address": teacher_data.get("address"),
                        "position": teacher_data.get("position"),
                        "joining_date": joining_date,
                        "role": teacher_data.get("role", "teacher"),
                        "qualification": teacher_data.get("qualification"),
                        "experience_years": teacher_data.get("experience_years", 0),
                        "teacher_details": json.dumps(teacher_data.get("teacher_details")) if teacher_data.get("teacher_details") else None,
                        "personal_info": json.dumps(teacher_data.get("personal_info")) if teacher_data.get("personal_info") else None,
                        "contact_info": json.dumps(teacher_data.get("contact_info")) if teacher_data.get("contact_info") else None,
                        "family_info": json.dumps(teacher_data.get("family_info")) if teacher_data.get("family_info") else None,
                        "qualifications": json.dumps(teacher_data.get("qualifications")) if teacher_data.get("qualifications") else None,
                        "employment": json.dumps(teacher_data.get("employment")) if teacher_data.get("employment") else None,
                        "academic_responsibilities": json.dumps(teacher_data.get("academic_responsibilities")) if teacher_data.get("academic_responsibilities") else None,
                        "timetable": json.dumps(teacher_data.get("timetable")) if teacher_data.get("timetable") else None,
                        "performance_evaluation": json.dumps(teacher_data.get("performance_evaluation")) if teacher_data.get("performance_evaluation") else None,
                        "status": teacher_data.get("status", "active"),
                        "last_login": None,
                        "created_at": now,
                        "updated_at": now,
                        "is_deleted": False
                    }
                    insert_data.append(teacher_record)
                    
                except Exception as e:
                    validation_errors.append(f"Row {idx + 1}: {str(e)}")
            
            # Efficient bulk insert using batch VALUES for large datasets
            successful_imports = 0
            if insert_data:
                batch_size = 50  # Process in batches to avoid memory issues
                
                for i in range(0, len(insert_data), batch_size):
                    batch = insert_data[i:i + batch_size]
                    
                    # Create VALUES clause for batch
                    values_list = []
                    params = {}
                    
                    for idx, record in enumerate(batch):
                        param_prefix = f"t{i + idx}_"
                        values_list.append(f"(:{param_prefix}id, :{param_prefix}tenant_id, :{param_prefix}teacher_id, :{param_prefix}first_name, :{param_prefix}last_name, :{param_prefix}email, :{param_prefix}phone, :{param_prefix}date_of_birth, :{param_prefix}gender, :{param_prefix}address, :{param_prefix}position, :{param_prefix}joining_date, :{param_prefix}role, :{param_prefix}qualification, :{param_prefix}experience_years, :{param_prefix}teacher_details, :{param_prefix}personal_info, :{param_prefix}contact_info, :{param_prefix}family_info, :{param_prefix}qualifications, :{param_prefix}employment, :{param_prefix}academic_responsibilities, :{param_prefix}timetable, :{param_prefix}performance_evaluation, :{param_prefix}status, :{param_prefix}last_login, :{param_prefix}created_at, :{param_prefix}updated_at, :{param_prefix}is_deleted)")
                        
                        # Add parameters with prefix
                        for key, value in record.items():
                            params[f"{param_prefix}{key}"] = value
                    
                    batch_sql = text(f"""
                        INSERT INTO teachers (
                            id, tenant_id, teacher_id, first_name, last_name, email, phone,
                            date_of_birth, gender, address, position, joining_date, role,
                            qualification, experience_years, teacher_details, personal_info,
                            contact_info, family_info, qualifications, employment,
                            academic_responsibilities, timetable, performance_evaluation,
                            status, last_login, created_at, updated_at, is_deleted
                        ) VALUES {', '.join(values_list)}
                    """)
                    
                    await self.db.execute(batch_sql, params)
                    successful_imports += len(batch)
                
                await self.db.commit()
            
            return {
                "total_records_processed": len(teachers_data),
                "successful_imports": successful_imports,
                "failed_imports": len(validation_errors) + len(duplicate_errors),
                "duplicate_records": len(duplicate_errors),
                "validation_errors": validation_errors if validation_errors else None,
                "duplicate_errors": duplicate_errors if duplicate_errors else None,
                "tenant_id": str(tenant_id),
                "status": "success" if successful_imports > 0 else "failed"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk import failed: {str(e)}")
    
    async def bulk_update_status(self, teacher_uuids: List[UUID], new_status: str, tenant_id: UUID) -> dict:
        """Bulk update teacher status in a SINGLE tenant-scoped UPDATE (no per-row N+1)."""
        try:
            if not teacher_uuids:
                raise HTTPException(status_code=400, detail="No teacher UUIDs provided")

            valid_statuses = ["active", "inactive", "resigned", "terminated", "on_leave"]
            if new_status not in valid_statuses:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status '{new_status}'. Must be one of: {valid_statuses}"
                )

            update_sql = text("""
                UPDATE teachers
                SET status = :new_status,
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND id = ANY(:teacher_uuids)
                AND is_deleted = false
            """)
            result = await self.db.execute(
                update_sql,
                {
                    "new_status": new_status,
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "teacher_uuids": [str(u) for u in teacher_uuids],
                },
            )
            await self.db.commit()

            return {
                "updated_teachers": result.rowcount,
                "new_status": new_status,
                "tenant_id": str(tenant_id),
                "status": "success"
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk status update failed: {str(e)}")
    
    async def bulk_assign_subjects(self, subject_assignments: List[dict], tenant_id: UUID) -> dict:
        """Bulk assign subjects to teachers using raw SQL"""
        try:
            if not subject_assignments:
                raise HTTPException(status_code=400, detail="No subject assignment data provided")
            
            # Get current teachers with their academic responsibilities using individual queries
            teachers_data = {}
            
            for assignment in subject_assignments:
                teacher_uuid = str(assignment.get("teacher-uuid") or assignment.get("teacher_uuid"))
                
                teachers_sql = text("""
                    SELECT id, academic_responsibilities
                    FROM teachers
                    WHERE tenant_id = :tenant_id
                    AND id = :teacher_uuid
                    AND is_deleted = false
                """)
                
                result = await self.db.execute(
                    teachers_sql, 
                    {"tenant_id": tenant_id, "teacher_uuid": teacher_uuid}
                )
                
                row = result.fetchone()
                if row:
                    teachers_data[str(row[0])] = {"academic_responsibilities": row[1] or {}}

            # Update academic responsibilities for each teacher
            updated_count = 0

            for assignment in subject_assignments:
                teacher_uuid = str(assignment.get("teacher-uuid") or assignment.get("teacher_uuid"))

                if teacher_uuid not in teachers_data:
                    continue
                
                current_responsibilities = teachers_data[teacher_uuid]["academic_responsibilities"]
                teaching_assignments = current_responsibilities.get("teaching_assignments", [])
                
                # Add new subject assignments with enhanced structure
                new_assignments = assignment.get("subjects", [])
                for subject_data in new_assignments:
                    # Check if subject already exists
                    existing = next((a for a in teaching_assignments 
                                   if a.get("subject") == subject_data.get("subject")), None)
                    if not existing:
                        # Enhanced subject assignment structure
                        subject_assignment = {
                            "subject": subject_data.get("subject"),
                            "grade": subject_data.get("grade"),
                            "section": subject_data.get("section"),
                            "hours_per_week": subject_data.get("hours_per_week"),
                            "assigned_date": datetime.utcnow().isoformat()
                        }
                        teaching_assignments.append(subject_assignment)
                
                current_responsibilities["teaching_assignments"] = teaching_assignments
                
                # Update teacher record
                update_teacher_sql = text("""
                    UPDATE teachers
                    SET academic_responsibilities = :academic_responsibilities,
                        updated_at = :updated_at
                    WHERE id = :teacher_uuid
                """)
                
                await self.db.execute(
                    update_teacher_sql,
                    {
                        "academic_responsibilities": json.dumps(current_responsibilities),
                        "updated_at": datetime.utcnow(),
                        "teacher_uuid": teacher_uuid
                    }
                )
                updated_count += 1
            
            await self.db.commit()
            
            return {
                "updated_teachers": updated_count,
                "total_assignments": len(subject_assignments),
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk subject assignment failed: {str(e)}")
    
    async def bulk_salary_update(self, salary_updates: List[dict], tenant_id: UUID) -> dict:
        """Bulk update teacher salaries using raw SQL"""
        try:
            if not salary_updates:
                raise HTTPException(status_code=400, detail="No salary update data provided")
            
            # Get current teachers with their teacher_details using individual queries
            teachers_data = {}
            
            for salary_update in salary_updates:
                teacher_uuid = str(salary_update.get("teacher-uuid") or salary_update.get("teacher_uuid"))
                
                teachers_sql = text("""
                    SELECT id, teacher_details
                    FROM teachers
                    WHERE tenant_id = :tenant_id
                    AND id = :teacher_uuid
                    AND is_deleted = false
                """)
                
                result = await self.db.execute(
                    teachers_sql, 
                    {"tenant_id": tenant_id, "teacher_uuid": teacher_uuid}
                )
                
                row = result.fetchone()
                if row:
                    teachers_data[str(row[0])] = {"teacher_details": row[1] or {}}
            
            # Update teacher_details for each teacher
            updated_count = 0
            for salary_update in salary_updates:
                teacher_uuid = str(salary_update.get("teacher-uuid") or salary_update.get("teacher_uuid"))
                if teacher_uuid not in teachers_data:
                    continue
                
                current_details = teachers_data[teacher_uuid]["teacher_details"]
                
                # Update salary_details in teacher_details JSON
                salary_details = {
                    "basic_salary": salary_update.get("basic_salary"),
                    "allowances": salary_update.get("allowances", {}),
                    "effective_date": salary_update.get("effective_date", datetime.utcnow()).isoformat() if isinstance(salary_update.get("effective_date"), datetime) else salary_update.get("effective_date", datetime.utcnow().isoformat()),
                    "increment_reason": salary_update.get("reason", "Bulk salary update"),
                    "updated_at": datetime.utcnow().isoformat()
                }
                
                current_details["salary_details"] = salary_details
                
                # Update teacher record
                update_teacher_sql = text("""
                    UPDATE teachers
                    SET teacher_details = :teacher_details,
                        updated_at = :updated_at
                    WHERE id = :teacher_uuid
                """)
                
                await self.db.execute(
                    update_teacher_sql,
                    {
                        "teacher_details": json.dumps(current_details),
                        "updated_at": datetime.utcnow(),
                        "teacher_uuid": teacher_uuid
                    }
                )
                updated_count += 1
            
            await self.db.commit()
            
            return {
                "updated_teachers": updated_count,
                "total_updates": len(salary_updates),
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk salary update failed: {str(e)}")
    
    async def bulk_soft_delete(self, teacher_uuids: List[UUID], tenant_id: UUID) -> dict:
        """Bulk soft delete teachers using raw SQL"""
        try:
            if not teacher_uuids:
                raise HTTPException(status_code=400, detail="No teacher UUIDs provided")
            
            delete_sql = text("""
                UPDATE teachers
                SET is_deleted = true,
                    status = 'inactive',
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND id = ANY(:teacher_uuids)
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                delete_sql,
                {
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "teacher_uuids": [str(uuid) for uuid in teacher_uuids]
                }
            )
            
            await self.db.commit()
            
            return {
                "deleted_teachers": result.rowcount,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")
    
    async def get_teacher_statistics(self, tenant_id: UUID) -> dict:
        """Get comprehensive teacher statistics using raw SQL for performance"""
        try:
            stats_sql = text("""
                SELECT 
                    COUNT(*) as total_teachers,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active_teachers,
                    COUNT(CASE WHEN status = 'inactive' THEN 1 END) as inactive_teachers,
                    COUNT(CASE WHEN status = 'on_leave' THEN 1 END) as on_leave_teachers,
                    COUNT(CASE WHEN status = 'resigned' THEN 1 END) as resigned_teachers
                FROM teachers
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
            """)
            
            result = await self.db.execute(stats_sql, {"tenant_id": tenant_id})
            stats = result.fetchone()
            
            # Get department-wise distribution
            dept_distribution_sql = text("""
                SELECT 
                    teacher_details->>'department' as department,
                    COUNT(*) as teacher_count
                FROM teachers
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
                AND status = 'active'
                AND teacher_details->>'department' IS NOT NULL
                GROUP BY teacher_details->>'department'
                ORDER BY teacher_count DESC
            """)
            
            dept_result = await self.db.execute(dept_distribution_sql, {"tenant_id": tenant_id})
            dept_distribution = {row[0]: row[1] for row in dept_result.fetchall()}
            
            return {
                "total_teachers": stats[0] or 0,
                "active_teachers": stats[1] or 0,
                "inactive_teachers": stats[2] or 0,
                "on_leave_teachers": stats[3] or 0,
                "resigned_teachers": stats[4] or 0,
                "department_distribution": dept_distribution,
                "tenant_id": str(tenant_id)
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")
