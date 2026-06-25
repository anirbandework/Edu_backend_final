# app/services/student_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from ...services.base_service import BaseService
from ..models.student import Student


class StudentService(BaseService[Student]):
    def __init__(self, db: AsyncSession):
        super().__init__(Student, db)
    
    async def get_by_tenant(self, tenant_id: UUID) -> List[Student]:
        """Get all students for a specific tenant/school"""
        stmt = select(self.model).where(
            self.model.tenant_id == tenant_id,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_student_id(self, student_id: str, tenant_id: Optional[UUID] = None) -> Optional[Student]:
        """Get student by their student_id"""
        stmt = select(self.model).where(
            self.model.student_id == student_id,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_email(self, email: str) -> Optional[Student]:
        """Get student by email"""
        stmt = select(self.model).where(
            self.model.email == email,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_admission_number(self, admission_number: str, tenant_id: Optional[UUID] = None) -> Optional[Student]:
        """Get student by admission number"""
        stmt = select(self.model).where(
            self.model.admission_number == admission_number,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_active_students(self, tenant_id: Optional[UUID] = None) -> List[Student]:
        """Get all active students, optionally filtered by tenant"""
        stmt = select(self.model).where(
            self.model.status == "active",
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_students_by_grade(self, grade_level: int, tenant_id: Optional[UUID] = None) -> List[Student]:
        """Get students by grade level"""
        stmt = select(self.model).where(
            self.model.grade_level == grade_level,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_students_by_section(self, section: str, tenant_id: Optional[UUID] = None) -> List[Student]:
        """Get students by section"""
        stmt = select(self.model).where(
            self.model.section == section,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_phone(self, phone: str, tenant_id: Optional[UUID] = None) -> Optional[Student]:
        """Get student by phone number"""
        stmt = select(self.model).where(
            self.model.phone == phone,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create(self, obj_in: dict) -> Student:
        """Create new student with validation"""
        try:
            # Check if student_id already exists for the tenant
            if obj_in.get("student_id") and obj_in.get("tenant_id"):
                existing = await self.get_by_student_id(obj_in.get("student_id"), obj_in.get("tenant_id"))
                if existing:
                    raise HTTPException(
                        status_code=400,
                        detail="Same student ID already exists"
                    )
            
            return await super().create(obj_in)
            
        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Same student ID already exists")
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_students_paginated(
        self,
        page: int = 1,
        size: int = 20,
        tenant_id: Optional[UUID] = None,
        grade_level: Optional[int] = None,
        section: Optional[str] = None
    ) -> dict:
        """Get paginated students with filters ordered alphabetically by name"""
        from sqlalchemy import select, func
        
        offset = (page - 1) * size
        
        # Build query with alphabetical ordering
        stmt = select(self.model).where(self.model.is_deleted == False)
        
        # Add filters
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
        if grade_level:
            stmt = stmt.where(self.model.grade_level == grade_level)
        if section:
            stmt = stmt.where(self.model.section == section)
        
        # Order alphabetically by first_name, then last_name (handle NULLs)
        from sqlalchemy import func
        stmt = stmt.order_by(
            func.coalesce(self.model.first_name, 'zzz').asc(),
            func.coalesce(self.model.last_name, 'zzz').asc()
        )
        
        # Get total count
        count_stmt = select(func.count()).select_from(self.model).where(self.model.is_deleted == False)
        if tenant_id:
            count_stmt = count_stmt.where(self.model.tenant_id == tenant_id)
        if grade_level:
            count_stmt = count_stmt.where(self.model.grade_level == grade_level)
        if section:
            count_stmt = count_stmt.where(self.model.section == section)
        
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar()
        
        # Execute main query with pagination
        stmt = stmt.offset(offset).limit(size)
        result = await self.db.execute(stmt)
        items = result.scalars().all()
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": (total + size - 1) // size,
            "has_next": page * size < total,
            "has_previous": page > 1,
        }
    
    async def update_login_time(self, student_id: UUID) -> Optional[Student]:
        """Update last login time for student"""
        student = await self.get(student_id)
        if student:
            student.last_login = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(student)
        return student
    
    # BULK OPERATIONS USING RAW SQL FOR HIGH PERFORMANCE
    
    async def bulk_import_students(self, students_data: List[dict], tenant_id: UUID) -> dict:
        """Bulk import students using raw SQL for maximum performance"""
        try:
            if not students_data:
                raise HTTPException(status_code=400, detail="No student data provided")
            
            # Check for existing student IDs and phone numbers in database
            student_ids = [student.get("student_id") for student in students_data if student.get("student_id")]
            phones = [student.get("phone") for student in students_data if student.get("phone")]
            
            # Get existing student count for this tenant
            existing_count_sql = text("""
                SELECT COUNT(*) FROM students 
                WHERE tenant_id = :tenant_id AND is_deleted = false
            """)
            count_result = await self.db.execute(existing_count_sql, {"tenant_id": str(tenant_id)})
            existing_student_count = count_result.scalar()
            
            # Check for existing student IDs
            existing_student_ids = set()
            if student_ids:
                existing_student_sql = text("""
                    SELECT student_id FROM students 
                    WHERE tenant_id = :tenant_id AND student_id = ANY(:student_ids) AND is_deleted = false
                """)
                result = await self.db.execute(existing_student_sql, {"tenant_id": str(tenant_id), "student_ids": student_ids})
                existing_student_ids = {row[0] for row in result.fetchall()}
            
            # Check for existing phone numbers
            existing_phones = set()
            if phones:
                existing_phone_sql = text("""
                    SELECT phone FROM students 
                    WHERE phone = ANY(:phones) AND is_deleted = false
                """)
                result = await self.db.execute(existing_phone_sql, {"phones": phones})
                existing_phones = {row[0] for row in result.fetchall()}
            
            # Validate and prepare bulk insert data
            now = datetime.utcnow()
            insert_data = []
            validation_errors = []
            duplicate_errors = []
            phones_in_batch = set()
            student_ids_in_batch = set()
            
            for idx, student_data in enumerate(students_data):
                try:
                    # Validate required fields (minimal: only tenant_id and student_id)
                    required_fields = ["student_id"]
                    for field in required_fields:
                        if not student_data.get(field):
                            validation_errors.append(f"Row {idx + 1}: Missing required field '{field}'")
                            continue
                    
                    if validation_errors:
                        continue
                    
                    # Check student ID uniqueness (required and must be unique)
                    student_id = student_data.get("student_id")
                    if student_id in existing_student_ids:
                        duplicate_errors.append(f"Row {idx + 1}: Student ID '{student_id}' already exists in database")
                        continue
                    if student_id in student_ids_in_batch:
                        duplicate_errors.append(f"Row {idx + 1}: Student ID '{student_id}' is duplicate in this batch")
                        continue
                    student_ids_in_batch.add(student_id)
                    
                    # Check phone number uniqueness (optional but must be unique if provided)
                    phone = student_data.get("phone")
                    if phone:
                        if phone in existing_phones:
                            duplicate_errors.append(f"Row {idx + 1}: Phone number '{phone}' already exists in database")
                            continue
                        if phone in phones_in_batch:
                            duplicate_errors.append(f"Row {idx + 1}: Phone number '{phone}' is duplicate in this batch")
                            continue
                        phones_in_batch.add(phone)
                    
                    # Parse date_of_birth if provided
                    date_of_birth = None
                    if student_data.get("date_of_birth"):
                        try:
                            date_str = student_data["date_of_birth"]
                            if date_str.endswith('Z'):
                                date_str = date_str[:-1] + '+00:00'
                            date_of_birth = datetime.fromisoformat(date_str).replace(tzinfo=None)
                        except Exception as e:
                            validation_errors.append(f"Row {idx + 1}: Invalid date format for date_of_birth: {str(e)}")
                            continue
                    
                    # Prepare student record with JSON serialization
                    import json
                    student_record = {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "student_id": student_data["student_id"],
                        "first_name": student_data.get("first_name"),
                        "last_name": student_data.get("last_name"),
                        "email": student_data.get("email"),
                        "phone": student_data.get("phone"),
                        "date_of_birth": date_of_birth,
                        "address": student_data.get("address"),
                        "role": "student",
                        "status": student_data.get("status", "active"),
                        "admission_number": student_data.get("admission_number"),
                        "roll_number": student_data.get("roll_number"),
                        "grade_level": student_data.get("grade_level"),
                        "section": student_data.get("section"),
                        "academic_year": student_data.get("academic_year"),
                        "parent_info": json.dumps(student_data.get("parent_info")) if student_data.get("parent_info") else None,
                        "health_medical_info": json.dumps(student_data.get("health_medical_info")) if student_data.get("health_medical_info") else None,
                        "emergency_information": json.dumps(student_data.get("emergency_information")) if student_data.get("emergency_information") else None,
                        "behavioral_disciplinary": json.dumps(student_data.get("behavioral_disciplinary")) if student_data.get("behavioral_disciplinary") else None,
                        "extended_academic_info": json.dumps(student_data.get("extended_academic_info")) if student_data.get("extended_academic_info") else None,
                        "enrollment_details": json.dumps(student_data.get("enrollment_details")) if student_data.get("enrollment_details") else None,
                        "financial_info": json.dumps(student_data.get("financial_info")) if student_data.get("financial_info") else None,
                        "extracurricular_social": json.dumps(student_data.get("extracurricular_social")) if student_data.get("extracurricular_social") else None,
                        "attendance_engagement": json.dumps(student_data.get("attendance_engagement")) if student_data.get("attendance_engagement") else None,
                        "additional_metadata": json.dumps(student_data.get("additional_metadata")) if student_data.get("additional_metadata") else None,
                        "created_at": now,
                        "updated_at": now,
                        "is_deleted": False
                    }
                    insert_data.append(student_record)
                    
                except Exception as e:
                    validation_errors.append(f"Row {idx + 1}: {str(e)}")
            
            # Don't throw exception for duplicates, handle like teacher service
            
            # Efficient bulk insert using COPY or VALUES for large datasets
            successful_imports = 0
            if insert_data:
                # Use batch insert with VALUES for better performance
                batch_size = 50  # Process in batches to avoid memory issues
                
                for i in range(0, len(insert_data), batch_size):
                    batch = insert_data[i:i + batch_size]
                    
                    # Create VALUES clause for batch
                    values_list = []
                    params = {}
                    
                    for idx, record in enumerate(batch):
                        param_prefix = f"r{i + idx}_"
                        values_list.append(f"(:{param_prefix}id, :{param_prefix}tenant_id, :{param_prefix}student_id, :{param_prefix}first_name, :{param_prefix}last_name, :{param_prefix}email, :{param_prefix}phone, :{param_prefix}date_of_birth, :{param_prefix}address, :{param_prefix}role, :{param_prefix}status, :{param_prefix}admission_number, :{param_prefix}roll_number, :{param_prefix}grade_level, :{param_prefix}section, :{param_prefix}academic_year, :{param_prefix}parent_info, :{param_prefix}health_medical_info, :{param_prefix}emergency_information, :{param_prefix}behavioral_disciplinary, :{param_prefix}extended_academic_info, :{param_prefix}enrollment_details, :{param_prefix}financial_info, :{param_prefix}extracurricular_social, :{param_prefix}attendance_engagement, :{param_prefix}additional_metadata, :{param_prefix}created_at, :{param_prefix}updated_at, :{param_prefix}is_deleted)")
                        
                        # Add parameters with prefix
                        for key, value in record.items():
                            params[f"{param_prefix}{key}"] = value
                    
                    batch_sql = text(f"""
                        INSERT INTO students (
                            id, tenant_id, student_id, first_name, last_name, 
                            email, phone, date_of_birth, address, role, status,
                            admission_number, roll_number, grade_level, section, academic_year,
                            parent_info, health_medical_info, emergency_information,
                            behavioral_disciplinary, extended_academic_info, enrollment_details,
                            financial_info, extracurricular_social, attendance_engagement,
                            additional_metadata, created_at, updated_at, is_deleted
                        ) VALUES {', '.join(values_list)}
                    """)
                    
                    await self.db.execute(batch_sql, params)
                    successful_imports += len(batch)
                
                await self.db.commit()
            
            return {
                "total_records_processed": len(students_data),
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
    
    async def bulk_update_grades(self, grade_updates: List[dict], tenant_id: UUID) -> dict:
        """Bulk update student grade levels using raw SQL"""
        try:
            if not grade_updates:
                raise HTTPException(status_code=400, detail="No grade update data provided")
            
            # Update students one by one using UUID
            updated_count = 0
            
            for update in grade_updates:
                student_uuid = update.get("student_uuid") or update.get("student_id")  # Support both formats
                new_grade = update.get("new_grade")
                
                if not student_uuid or new_grade is None:
                    continue
                
                update_sql = text("""
                    UPDATE students
                    SET grade_level = :new_grade,
                        updated_at = :updated_at
                    WHERE tenant_id = :tenant_id
                    AND id = :student_uuid
                    AND is_deleted = false
                """)
                
                result = await self.db.execute(
                    update_sql,
                    {
                        "new_grade": new_grade,
                        "updated_at": datetime.utcnow(),
                        "tenant_id": tenant_id,
                        "student_uuid": student_uuid
                    }
                )
                
                if result.rowcount > 0:
                    updated_count += 1
            
            await self.db.commit()
            
            return {
                "updated_students": updated_count,
                "total_requests": len(grade_updates),
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk grade update failed: {str(e)}")
    
    async def bulk_promote_students(self, current_grade: int, tenant_id: UUID, academic_year: str) -> dict:
        """Promote all students from current grade to next grade using raw SQL"""
        try:
            # Get count of students to be promoted
            count_sql = text("""
                SELECT COUNT(*) as student_count
                FROM students
                WHERE tenant_id = :tenant_id
                AND grade_level = :current_grade
                AND status = 'active'
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                count_sql,
                {"tenant_id": tenant_id, "current_grade": current_grade}
            )
            student_count = result.scalar()
            
            if student_count == 0:
                return {
                    "promoted_students": 0,
                    "message": f"No students found in grade {current_grade}",
                    "status": "success"
                }
            
            # Promote students
            promote_sql = text("""
                UPDATE students 
                SET grade_level = grade_level + 1,
                    academic_year = :academic_year,
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND grade_level = :current_grade
                AND status = 'active'
                AND is_deleted = false
            """)
            
            await self.db.execute(
                promote_sql,
                {
                    "academic_year": academic_year,
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "current_grade": current_grade
                }
            )
            
            await self.db.commit()
            
            return {
                "promoted_students": student_count,
                "from_grade": current_grade,
                "to_grade": current_grade + 1,
                "academic_year": academic_year,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk promotion failed: {str(e)}")
    
    async def bulk_update_status(self, student_ids: List[str], new_status: str, tenant_id: UUID) -> dict:
        """Bulk update student status using raw SQL"""
        try:
            if not student_ids:
                raise HTTPException(status_code=400, detail="No student IDs provided")
            
            valid_statuses = ["active", "inactive", "graduated", "transferred", "suspended", "expelled"]
            if new_status not in valid_statuses:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid status. Must be one of: {valid_statuses}"
                )
            
            update_sql = text("""
                UPDATE students
                SET status = :new_status,
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND id = ANY(:student_ids)
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                update_sql,
                {
                    "new_status": new_status,
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "student_ids": student_ids
                }
            )
            
            await self.db.commit()
            
            return {
                "message": f"Status update completed. {result.rowcount} students updated to '{new_status}'",
                "updated_students": result.rowcount,
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
    
    async def bulk_update_sections(self, section_updates: List[dict], tenant_id: UUID) -> dict:
        """Bulk update student sections using raw SQL"""
        try:
            if not section_updates:
                raise HTTPException(status_code=400, detail="No section update data provided")
            
            updated_count = 0
            
            for update in section_updates:
                student_uuid = update.get("student_uuid") or update.get("student_id")
                new_section = update.get("new_section")
                
                if not student_uuid:
                    continue
                
                update_sql = text("""
                    UPDATE students
                    SET section = :new_section,
                        updated_at = :updated_at
                    WHERE tenant_id = :tenant_id
                    AND id = :student_uuid
                    AND is_deleted = false
                """)
                
                result = await self.db.execute(
                    update_sql,
                    {
                        "new_section": new_section,
                        "updated_at": datetime.utcnow(),
                        "tenant_id": tenant_id,
                        "student_uuid": student_uuid
                    }
                )
                
                if result.rowcount > 0:
                    updated_count += 1
            
            await self.db.commit()
            
            return {
                "updated_students": updated_count,
                "total_requests": len(section_updates),
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk section update failed: {str(e)}")
    
    async def bulk_soft_delete(self, student_ids: List[str], tenant_id: UUID) -> dict:
        """Bulk soft delete students using raw SQL"""
        try:
            if not student_ids:
                raise HTTPException(status_code=400, detail="No student IDs provided")
            
            delete_sql = text("""
                UPDATE students
                SET is_deleted = true,
                    status = 'inactive',
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND id = ANY(:student_ids)
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                delete_sql,
                {
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "student_ids": student_ids
                }
            )
            
            await self.db.commit()
            
            return {
                "deleted_students": result.rowcount,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")
    
    async def get_student_statistics(self, tenant_id: UUID) -> dict:
        """Get comprehensive student statistics using raw SQL for performance"""
        try:
            stats_sql = text("""
                SELECT 
                    COUNT(*) as total_students,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active_students,
                    COUNT(CASE WHEN status = 'inactive' THEN 1 END) as inactive_students,
                    COUNT(CASE WHEN status = 'graduated' THEN 1 END) as graduated_students,
                    COUNT(CASE WHEN status = 'transferred' THEN 1 END) as transferred_students,
                    COUNT(CASE WHEN status = 'suspended' THEN 1 END) as suspended_students,
                    COUNT(CASE WHEN status = 'expelled' THEN 1 END) as expelled_students,
                    AVG(grade_level) as average_grade,
                    MIN(grade_level) as lowest_grade,
                    MAX(grade_level) as highest_grade
                FROM students
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
            """)
            
            result = await self.db.execute(stats_sql, {"tenant_id": tenant_id})
            stats = result.fetchone()
            
            # Get grade-wise distribution
            grade_distribution_sql = text("""
                SELECT grade_level, COUNT(*) as student_count
                FROM students
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
                AND status = 'active'
                GROUP BY grade_level
                ORDER BY grade_level
            """)
            
            grade_result = await self.db.execute(grade_distribution_sql, {"tenant_id": tenant_id})
            grade_distribution = {row[0]: row[1] for row in grade_result.fetchall()}
            
            return {
                "total_students": stats[0] or 0,
                "active_students": stats[1] or 0,
                "inactive_students": stats[2] or 0,
                "graduated_students": stats[3] or 0,
                "transferred_students": stats[4] or 0,
                "suspended_students": stats[5] or 0,
                "expelled_students": stats[6] or 0,
                "average_grade": float(stats[7]) if stats[7] else 0.0,
                "lowest_grade": stats[8] or 0,
                "highest_grade": stats[9] or 0,
                "grade_distribution": grade_distribution,
                "tenant_id": str(tenant_id)
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")
