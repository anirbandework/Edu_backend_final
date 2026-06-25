# app/services/class_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from ...services.base_service import BaseService
from ..models.class_model import ClassModel

class ClassService(BaseService[ClassModel]):
    def __init__(self, db: AsyncSession):
        super().__init__(ClassModel, db)
    
    async def get_by_tenant(self, tenant_id: UUID) -> List[ClassModel]:
        """Get all classes for a specific tenant/school"""
        stmt = select(self.model).where(
            self.model.tenant_id == tenant_id,
            self.model.is_deleted == False
        ).order_by(self.model.class_name, self.model.section, self.model.grade_level)
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_grade_level(self, grade_level: int, tenant_id: Optional[UUID] = None) -> List[ClassModel]:
        """Get classes by grade level"""
        stmt = select(self.model).where(
            self.model.grade_level == grade_level,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        stmt = stmt.order_by(self.model.class_name, self.model.section, self.model.grade_level)
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_section(self, section: str, tenant_id: Optional[UUID] = None) -> List[ClassModel]:
        """Get classes by section"""
        stmt = select(self.model).where(
            self.model.section == section,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_academic_year(self, academic_year: str, tenant_id: Optional[UUID] = None) -> List[ClassModel]:
        """Get classes by academic year"""
        stmt = select(self.model).where(
            self.model.academic_year == academic_year,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_active_classes(self, tenant_id: Optional[UUID] = None) -> List[ClassModel]:
        """Get all active classes"""
        stmt = select(self.model).where(
            self.model.is_active == True,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        stmt = stmt.order_by(self.model.class_name, self.model.section, self.model.grade_level)
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_class_name(self, class_name: str, tenant_id: Optional[UUID] = None) -> Optional[ClassModel]:
        """Get class by name"""
        stmt = select(self.model).where(
            self.model.class_name == class_name,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create(self, obj_in: dict) -> ClassModel:
        """Create new class with validation"""
        try:
            # Check if class already exists with same tenant_id, class_name, grade_level, section, academic_year
            required_fields = ["class_name", "tenant_id", "grade_level", "section", "academic_year"]
            if all(obj_in.get(field) is not None for field in required_fields):
                stmt = select(self.model).where(
                    self.model.class_name == obj_in.get("class_name"),
                    self.model.tenant_id == obj_in.get("tenant_id"),
                    self.model.grade_level == obj_in.get("grade_level"),
                    self.model.section == obj_in.get("section"),
                    self.model.academic_year == obj_in.get("academic_year"),
                    self.model.is_deleted == False
                )
                result = await self.db.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Class {obj_in.get('class_name')} already exists for grade {obj_in.get('grade_level')}, section {obj_in.get('section')}, academic year {obj_in.get('academic_year')}"
                    )
            
            return await super().create(obj_in)
            
        except IntegrityError as e:
            await self.db.rollback()
            if "uq_class_identity" in str(e):
                raise HTTPException(status_code=409, detail="Class already exists")
            else:
                raise HTTPException(status_code=400, detail=f"Database integrity error: {str(e)}")
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=400, detail=f"Failed to create class: {str(e)}")
    
    async def get_class_statistics(self, class_id: UUID) -> dict:
        """Get statistics for a specific class"""
        class_obj = await self.get(class_id)
        if not class_obj:
            return {}
        
        return {
            "class_name": class_obj.class_name,
            "grade_level": class_obj.grade_level,
            "section": class_obj.section,
            "maximum_students": class_obj.maximum_students,
            "current_students": class_obj.current_students,
            "available_spots": class_obj.maximum_students - class_obj.current_students,
            "occupancy_rate": round((class_obj.current_students / class_obj.maximum_students * 100), 2) if class_obj.maximum_students > 0 else 0,
            "classroom": class_obj.classroom,
            "is_active": class_obj.is_active,
            "academic_year": class_obj.academic_year
        }
    
    async def update_student_count(self, class_id: UUID, new_count: int) -> Optional[ClassModel]:
        """Update the current student count for a class"""
        class_obj = await self.get(class_id)
        if class_obj:
            if new_count > class_obj.maximum_students:
                raise ValueError(f"Cannot exceed maximum capacity of {class_obj.maximum_students}")
            
            class_obj.current_students = new_count
            await self.db.commit()
            await self.db.refresh(class_obj)
        return class_obj
    
    async def get_classes_with_availability(self, tenant_id: Optional[UUID] = None) -> List[ClassModel]:
        """Get classes that have available spots"""
        stmt = select(self.model).where(
            self.model.current_students < self.model.maximum_students,
            self.model.is_active == True,
            self.model.is_deleted == False
        )
        
        if tenant_id:
            stmt = stmt.where(self.model.tenant_id == tenant_id)
            
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_classes_paginated(
        self,
        page: int = 1,
        size: int = 20,
        tenant_id: Optional[UUID] = None,
        grade_level: Optional[int] = None,
        section: Optional[str] = None,
        academic_year: Optional[str] = None,
        active_only: bool = False
    ) -> dict:
        """Get paginated classes"""
        filters = {}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        if grade_level:
            filters["grade_level"] = grade_level
        if section:
            filters["section"] = section
        if academic_year:
            filters["academic_year"] = academic_year
        if active_only:
            filters["is_active"] = True
            
        result = await self.get_paginated(page=page, size=size, **filters)
        
        # Sort the items manually for complex ordering
        result["items"] = sorted(
            result["items"], 
            key=lambda x: (x.class_name, x.section, x.grade_level)
        )
        
        return result
    
    # BULK OPERATIONS USING RAW SQL FOR HIGH PERFORMANCE
    
    async def bulk_import_classes(self, classes_data: List[dict], tenant_id: UUID) -> dict:
        """Bulk import classes using raw SQL for maximum performance"""
        try:
            if not classes_data:
                raise HTTPException(status_code=400, detail="No class data provided")
            
            # Check for existing classes to avoid duplicates
            existing_check_sql = text("""
                SELECT CONCAT(class_name, '-', section, '-', academic_year) as class_key
                FROM classes
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
            """)
            
            result = await self.db.execute(existing_check_sql, {"tenant_id": tenant_id})
            existing_classes = {row[0] for row in result.fetchall()}
            
            # Validate and prepare bulk insert data
            now = datetime.utcnow()
            insert_data = []
            validation_errors = []
            skipped_duplicates = 0
            
            for idx, class_data in enumerate(classes_data):
                try:
                    # Validate required fields
                    required_fields = ["class_name", "grade_level", "section", "academic_year"]
                    for field in required_fields:
                        if not class_data.get(field):
                            validation_errors.append(f"Row {idx + 1}: Missing required field '{field}'")
                            continue
                    
                    if validation_errors:
                        continue
                    
                    # Check for duplicates
                    class_key = f"{class_data['class_name']}-{class_data['section']}-{class_data['academic_year']}"
                    if class_key in existing_classes:
                        skipped_duplicates += 1
                        continue
                    
                    # Prepare class record
                    class_record = {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "class_name": class_data["class_name"],
                        "grade_level": class_data["grade_level"],
                        "section": class_data["section"],
                        "academic_year": class_data["academic_year"],
                        "maximum_students": class_data.get("maximum_students", 40),
                        "current_students": class_data.get("current_students", 0),
                        "classroom": class_data.get("classroom"),
                        "is_active": class_data.get("is_active", True),
                        "created_at": now,
                        "updated_at": now,
                        "is_deleted": False
                    }
                    insert_data.append(class_record)
                    
                except Exception as e:
                    validation_errors.append(f"Row {idx + 1}: {str(e)}")
            
            if validation_errors:
                raise HTTPException(
                    status_code=400, 
                    detail={"message": "Validation errors found", "errors": validation_errors}
                )
            
            # Bulk insert using raw SQL
            bulk_insert_sql = text("""
                INSERT INTO classes (
                    id, tenant_id, class_name, grade_level, section, academic_year,
                    maximum_students, current_students, classroom, is_active,
                    created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :class_name, :grade_level, :section, :academic_year,
                    :maximum_students, :current_students, :classroom, :is_active,
                    :created_at, :updated_at, :is_deleted
                )
            """)
            
            if insert_data:
                result = await self.db.execute(bulk_insert_sql, insert_data)
                await self.db.commit()
            
            return {
                "total_records_processed": len(classes_data),
                "successful_imports": len(insert_data),
                "failed_imports": len(validation_errors),
                "skipped_duplicates": skipped_duplicates,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk import failed: {str(e)}")
    
    async def bulk_update_capacity(self, capacity_updates: List[dict], tenant_id: UUID) -> dict:
        """Bulk update class capacity using raw SQL"""
        try:
            if not capacity_updates:
                raise HTTPException(status_code=400, detail="No capacity update data provided")
            
            # Build a parameterized CASE per row — only code-controlled param NAMES are
            # interpolated into the SQL; all values (ids, counts) are bound parameters.
            update_cases_max = []
            update_cases_current = []
            class_ids = []
            params = {"updated_at": datetime.utcnow(), "tenant_id": tenant_id}

            for i, update in enumerate(capacity_updates):
                cid = str(update["class_id"])
                class_ids.append(cid)
                params[f"cid_{i}"] = cid
                if "maximum_students" in update:
                    try:
                        params[f"max_{i}"] = int(update["maximum_students"])
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail=f"Invalid maximum_students for class {cid}")
                    update_cases_max.append(f"WHEN CAST(:cid_{i} AS uuid) THEN CAST(:max_{i} AS integer)")
                if "current_students" in update:
                    try:
                        params[f"cur_{i}"] = int(update["current_students"])
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail=f"Invalid current_students for class {cid}")
                    update_cases_current.append(f"WHEN CAST(:cid_{i} AS uuid) THEN CAST(:cur_{i} AS integer)")

            if not update_cases_max and not update_cases_current:
                raise HTTPException(status_code=400, detail="No valid capacity updates provided")

            update_parts = []
            if update_cases_max:
                update_parts.append(f"maximum_students = CASE id {' '.join(update_cases_max)} ELSE maximum_students END")
            if update_cases_current:
                update_parts.append(f"current_students = CASE id {' '.join(update_cases_current)} ELSE current_students END")

            params["class_ids"] = class_ids
            bulk_update_sql = text(f"""
                UPDATE classes
                SET {', '.join(update_parts)}, updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND id = ANY(:class_ids)
                AND is_deleted = false
            """)

            result = await self.db.execute(bulk_update_sql, params)
            
            await self.db.commit()
            
            return {
                "updated_classes": result.rowcount,
                "total_requests": len(capacity_updates),
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk capacity update failed: {str(e)}")
    
    async def bulk_update_status(self, class_ids: List[UUID], is_active: bool, tenant_id: UUID) -> dict:
        """Bulk update class active status using raw SQL"""
        try:
            if not class_ids:
                raise HTTPException(status_code=400, detail="No class IDs provided")
            
            update_sql = text("""
                UPDATE classes
                SET is_active = :is_active,
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND id = ANY(:class_ids)
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                update_sql,
                {
                    "is_active": is_active,
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "class_ids": [str(cid) for cid in class_ids]
                }
            )
            
            await self.db.commit()
            
            return {
                "updated_classes": result.rowcount,
                "new_status": "active" if is_active else "inactive",
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk status update failed: {str(e)}")
    
    async def bulk_assign_classrooms(self, classroom_assignments: List[dict], tenant_id: UUID) -> dict:
        """Bulk assign classrooms to classes using raw SQL"""
        try:
            if not classroom_assignments:
                raise HTTPException(status_code=400, detail="No classroom assignment data provided")
            
            # Parameterized CASE — only param NAMES are interpolated; ids and classroom
            # values are bound parameters (no SQL injection via class_id/classroom).
            update_cases = []
            class_ids = []
            params = {"updated_at": datetime.utcnow(), "tenant_id": tenant_id}

            for i, assignment in enumerate(classroom_assignments):
                cid = str(assignment["class_id"])
                class_ids.append(cid)
                params[f"cid_{i}"] = cid
                params[f"room_{i}"] = assignment.get("classroom") or None
                update_cases.append(f"WHEN CAST(:cid_{i} AS uuid) THEN CAST(:room_{i} AS varchar)")

            if not update_cases:
                raise HTTPException(status_code=400, detail="No valid classroom assignments provided")

            params["class_ids"] = class_ids
            bulk_update_sql = text(f"""
                UPDATE classes
                SET classroom = CASE id {' '.join(update_cases)} ELSE classroom END,
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND id = ANY(:class_ids)
                AND is_deleted = false
            """)

            result = await self.db.execute(bulk_update_sql, params)
            
            await self.db.commit()
            
            return {
                "updated_classes": result.rowcount,
                "total_assignments": len(classroom_assignments),
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk classroom assignment failed: {str(e)}")
    
    async def bulk_academic_year_rollover(self, current_year: str, new_year: str, tenant_id: UUID) -> dict:
        """Rollover all classes to new academic year using raw SQL"""
        try:
            # Get count of classes to be rolled over
            count_sql = text("""
                SELECT COUNT(*) as class_count
                FROM classes
                WHERE tenant_id = :tenant_id
                AND academic_year = :current_year
                AND is_active = true
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                count_sql,
                {"tenant_id": tenant_id, "current_year": current_year}
            )
            class_count = result.scalar()
            
            if class_count == 0:
                return {
                    "rolled_over_classes": 0,
                    "message": f"No classes found for academic year {current_year}",
                    "status": "success"
                }
            
            # Create new classes for new academic year (duplicate existing classes)
            rollover_sql = text("""
                INSERT INTO classes (
                    id, tenant_id, class_name, grade_level, section, academic_year,
                    maximum_students, current_students, classroom, is_active,
                    created_at, updated_at, is_deleted
                )
                SELECT 
                    gen_random_uuid(), tenant_id, class_name, grade_level, section, :new_year,
                    maximum_students, 0, classroom, true,
                    :created_at, :updated_at, false
                FROM classes
                WHERE tenant_id = :tenant_id
                AND academic_year = :current_year
                AND is_active = true
                AND is_deleted = false
            """)
            
            await self.db.execute(
                rollover_sql,
                {
                    "new_year": new_year,
                    "tenant_id": tenant_id,
                    "current_year": current_year,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
            )
            
            await self.db.commit()
            
            return {
                "rolled_over_classes": class_count,
                "previous_academic_year": current_year,
                "new_academic_year": new_year,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Academic year rollover failed: {str(e)}")
    
    async def bulk_soft_delete(self, class_ids: List[UUID], tenant_id: UUID) -> dict:
        """Bulk soft delete classes using raw SQL"""
        try:
            if not class_ids:
                raise HTTPException(status_code=400, detail="No class IDs provided")
            
            delete_sql = text("""
                UPDATE classes
                SET is_deleted = true,
                    is_active = false,
                    updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                AND id = ANY(:class_ids)
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                delete_sql,
                {
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_id,
                    "class_ids": [str(cid) for cid in class_ids]
                }
            )
            
            await self.db.commit()
            
            return {
                "deleted_classes": result.rowcount,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")
    
    async def get_comprehensive_class_statistics(self, tenant_id: UUID) -> dict:
        """Get comprehensive class statistics using raw SQL for performance"""
        try:
            # Main statistics
            stats_sql = text("""
                SELECT 
                    COUNT(*) as total_classes,
                    COUNT(CASE WHEN is_active = true THEN 1 END) as active_classes,
                    COUNT(CASE WHEN is_active = false THEN 1 END) as inactive_classes,
                    SUM(current_students) as total_enrolled_students,
                    SUM(maximum_students) as total_capacity,
                    AVG(current_students::float / NULLIF(maximum_students, 0) * 100) as average_occupancy,
                    MIN(grade_level) as lowest_grade,
                    MAX(grade_level) as highest_grade
                FROM classes
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
            """)
            
            result = await self.db.execute(stats_sql, {"tenant_id": tenant_id})
            stats = result.fetchone()
            
            # Grade-wise distribution
            grade_distribution_sql = text("""
                SELECT grade_level, COUNT(*) as class_count, SUM(current_students) as student_count
                FROM classes
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
                AND is_active = true
                GROUP BY grade_level
                ORDER BY grade_level
            """)
            
            grade_result = await self.db.execute(grade_distribution_sql, {"tenant_id": tenant_id})
            grade_distribution = {row[0]: {"classes": row[1], "students": row[2]} for row in grade_result.fetchall()}
            
            # Academic year distribution
            year_distribution_sql = text("""
                SELECT academic_year, COUNT(*) as class_count
                FROM classes
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
                GROUP BY academic_year
                ORDER BY academic_year DESC
            """)
            
            year_result = await self.db.execute(year_distribution_sql, {"tenant_id": tenant_id})
            year_distribution = {row[0]: row[1] for row in year_result.fetchall()}
            
            # Capacity analysis
            capacity_sql = text("""
                SELECT 
                    COUNT(CASE WHEN (current_students::float / NULLIF(maximum_students, 0)) < 0.5 THEN 1 END) as under_50_percent,
                    COUNT(CASE WHEN (current_students::float / NULLIF(maximum_students, 0)) BETWEEN 0.5 AND 0.8 THEN 1 END) as between_50_80_percent,
                    COUNT(CASE WHEN (current_students::float / NULLIF(maximum_students, 0)) > 0.8 THEN 1 END) as over_80_percent,
                    COUNT(CASE WHEN current_students >= maximum_students THEN 1 END) as at_full_capacity
                FROM classes
                WHERE tenant_id = :tenant_id
                AND is_deleted = false
                AND is_active = true
                AND maximum_students > 0
            """)
            
            capacity_result = await self.db.execute(capacity_sql, {"tenant_id": tenant_id})
            capacity_stats = capacity_result.fetchone()
            
            return {
                "total_classes": stats[0] or 0,
                "active_classes": stats[1] or 0,
                "inactive_classes": stats[2] or 0,
                "total_enrolled_students": stats[3] or 0,
                "total_capacity": stats[4] or 0,
                "overall_occupancy_rate": round(float(stats[5]), 2) if stats[5] else 0.0,
                "capacity_utilization": round((stats[3] / stats[4] * 100), 2) if stats[4] > 0 else 0,
                "lowest_grade": stats[6],
                "highest_grade": stats[7],
                "grade_distribution": grade_distribution,
                "academic_year_distribution": year_distribution,
                "capacity_breakdown": {
                    "under_50_percent": capacity_stats[0] or 0,
                    "between_50_80_percent": capacity_stats[1] or 0,
                    "over_80_percent": capacity_stats[2] or 0,
                    "at_full_capacity": capacity_stats[3] or 0
                },
                "tenant_id": str(tenant_id)
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")
