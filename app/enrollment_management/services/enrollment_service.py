# app/services/enrollment_service.py
from typing import Any, List, Optional
from uuid import UUID
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from ...services.base_service import BaseService
from ..models.enrollment import Enrollment
from ...staff_management.models.member import Member


class EnrollmentService(BaseService[Enrollment]):
    def __init__(self, db: AsyncSession):
        super().__init__(Enrollment, db)

    async def _get_member(self, member_id: UUID, tenant_id: Any = None) -> Optional[Member]:
        """Fetch a non-deleted Member, optionally tenant-scoped."""
        stmt = select(Member).where(Member.id == member_id, Member.is_deleted == False)
        if tenant_id is not None:
            stmt = stmt.where(Member.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_member(self, member_id: UUID) -> List[Enrollment]:
        """Get all enrollments for a specific member"""
        stmt = select(self.model).where(
            self.model.member_id == member_id,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_class(self, class_id: UUID) -> List[Enrollment]:
        """Get all enrollments for a specific class"""
        stmt = select(self.model).where(
            self.model.class_id == class_id,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_by_academic_year(self, academic_year: str, member_id: Optional[UUID] = None, class_id: Optional[UUID] = None) -> List[Enrollment]:
        """Get enrollments by academic year"""
        stmt = select(self.model).where(
            self.model.academic_year == academic_year,
            self.model.is_deleted == False
        )

        if member_id:
            stmt = stmt.where(self.model.member_id == member_id)
        if class_id:
            stmt = stmt.where(self.model.class_id == class_id)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_active_enrollments(self, member_id: Optional[UUID] = None, class_id: Optional[UUID] = None) -> List[Enrollment]:
        """Get all active enrollments"""
        stmt = select(self.model).where(
            self.model.status == "active",
            self.model.is_deleted == False
        )

        if member_id:
            stmt = stmt.where(self.model.member_id == member_id)
        if class_id:
            stmt = stmt.where(self.model.class_id == class_id)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_member_and_class(self, member_id: UUID, class_id: UUID) -> Optional[Enrollment]:
        """Get specific enrollment by member and class"""
        stmt = select(self.model).where(
            self.model.member_id == member_id,
            self.model.class_id == class_id,
            self.model.is_deleted == False
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create(self, obj_in: dict, scope_tenant: Any = None) -> Enrollment:
        """Create a new enrollment, tenant-scoped and validated.

        The target class and member must belong to the same tenant; when scope_tenant
        is given (a non-super-admin caller) that tenant is enforced, so nobody can enroll
        across schools. tenant_id is denormalized onto the enrollment from the class.
        A "student" here is simply a MEMBER enrolled in a class — grade/section live on
        the class, not the member, so there is nothing to sync back onto the member."""
        try:
            member_id = obj_in.get("member_id")
            class_id = obj_in.get("class_id")
            if not member_id or not class_id:
                raise HTTPException(status_code=400, detail="member_id and class_id are required")

            from ...class_management.services.class_service import ClassService
            class_service = ClassService(self.db)

            # Tenant-scope BOTH lookups: a caller can only touch their own tenant's rows.
            class_obj = await class_service.get(class_id, tenant_id=scope_tenant)
            if not class_obj:
                raise HTTPException(status_code=404, detail="Class not found")
            member = await self._get_member(member_id, tenant_id=scope_tenant)
            if not member:
                raise HTTPException(status_code=404, detail="Member not found")
            # Integrity: member and class must share a tenant (also blocks a super-admin
            # accidentally mixing schools).
            if str(member.tenant_id) != str(class_obj.tenant_id):
                raise HTTPException(status_code=400, detail="Member and class belong to different schools")

            existing = await self.get_by_member_and_class(member_id, class_id)
            if existing:
                raise HTTPException(status_code=400, detail="Member is already enrolled in this class")

            if class_obj.current_students >= class_obj.maximum_students:
                raise HTTPException(status_code=400, detail=f"Class is full. Maximum capacity: {class_obj.maximum_students}")

            obj_in["tenant_id"] = class_obj.tenant_id
            enrollment = await super().create(obj_in)

            await class_service.update_student_count(class_obj.id, class_obj.current_students + 1)
            return enrollment

        except HTTPException:
            await self.db.rollback()
            raise
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Enrollment already exists")
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
    
    async def update_enrollment_status(self, enrollment_id: UUID, status: str, tenant_id: Any = None) -> Optional[Enrollment]:
        """Update enrollment status"""
        enrollment = await self.get(enrollment_id, tenant_id=tenant_id)
        if enrollment:
            old_status = enrollment.status
            enrollment.status = status
            await self.db.commit()
            await self.db.refresh(enrollment)
            
            # Update class student count if status changed from/to active
            if (old_status == "active" and status != "active") or (old_status != "active" and status == "active"):
                from ...class_management.services.class_service import ClassService
                class_service = ClassService(self.db)
                class_obj = await class_service.get(enrollment.class_id)
                
                if class_obj:
                    # Recalculate active enrollments for this class
                    active_enrollments = await self.get_active_enrollments(class_id=enrollment.class_id)
                    await class_service.update_student_count(class_obj.id, len(active_enrollments))
        
        return enrollment
    
    async def get_enrollments_paginated(
        self,
        page: int = 1,
        size: int = 20,
        member_id: Optional[UUID] = None,
        class_id: Optional[UUID] = None,
        academic_year: Optional[str] = None,
        status: Optional[str] = None
    ) -> dict:
        """Get paginated enrollments"""
        filters = {}
        if member_id:
            filters["member_id"] = member_id
        if class_id:
            filters["class_id"] = class_id
        if academic_year:
            filters["academic_year"] = academic_year
        if status:
            filters["status"] = status
            
        return await self.get_paginated(page=page, size=size, **filters)
    
    async def bulk_enroll_students(self, class_id: UUID, member_ids: List[UUID], academic_year: str, tenant_id: Any = None) -> dict:
        """Bulk enroll multiple members in a class using raw SQL for performance"""
        # Tenant-scope the class: a caller can't enroll into another school's class.
        from ...class_management.services.class_service import ClassService
        class_service = ClassService(self.db)
        class_obj = await class_service.get(class_id, tenant_id=tenant_id)

        if not class_obj:
            raise HTTPException(status_code=404, detail="Class not found")

        available_spots = class_obj.maximum_students - class_obj.current_students

        if len(member_ids) > available_spots:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough spots available. Available: {available_spots}, Requested: {len(member_ids)}"
            )

        # Use raw SQL for bulk operations
        try:
            # 1. Check for existing enrollments using raw SQL
            existing_check_sql = text("""
                SELECT member_id
                FROM enrollments
                WHERE class_id = :class_id
                AND member_id = ANY(:member_ids)
                AND is_deleted = false
            """)

            result = await self.db.execute(
                existing_check_sql,
                {
                    "class_id": class_id,
                    "member_ids": [str(sid) for sid in member_ids]
                }
            )
            existing_member_ids = {str(row[0]) for row in result.fetchall()}

            # Filter out members who are already enrolled
            new_member_ids = [sid for sid in member_ids if str(sid) not in existing_member_ids]

            # Restrict to members that actually belong to this class's tenant (integrity).
            valid_sql = text("SELECT id FROM members WHERE id = ANY(:sids) AND tenant_id = :tid AND is_deleted = false")
            vres = await self.db.execute(valid_sql, {"sids": [str(s) for s in new_member_ids], "tid": class_obj.tenant_id})
            valid_ids = {str(r[0]) for r in vres.fetchall()}
            new_member_ids = [sid for sid in new_member_ids if str(sid) in valid_ids]

            if not new_member_ids:
                return {
                    "successful_enrollments": 0,
                    "failed_enrollments": len(member_ids),
                    "successful": [],
                    "failed": [{"member_id": str(sid), "reason": "Already enrolled"} for sid in member_ids],
                    "class_capacity_after": f"{class_obj.current_students}/{class_obj.maximum_students}"
                }

            # 2. Bulk insert enrollments using raw SQL
            now = datetime.utcnow()
            enrollment_data = []

            for member_id in new_member_ids:
                enrollment_data.append({
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(class_obj.tenant_id),
                    "member_id": str(member_id),
                    "class_id": str(class_id),
                    "enrollment_date": now,
                    "academic_year": academic_year,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                    "is_deleted": False
                })

            # Execute bulk insert
            bulk_insert_sql = text("""
                INSERT INTO enrollments (
                    id, tenant_id, member_id, class_id, enrollment_date,
                    academic_year, status, created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :member_id, :class_id, :enrollment_date,
                    :academic_year, :status, :created_at, :updated_at, :is_deleted
                )
            """)

            await self.db.execute(bulk_insert_sql, enrollment_data)

            # 3. Update class student count using raw SQL
            update_count_sql = text("""
                UPDATE classes
                SET current_students = current_students + :increment,
                    updated_at = :updated_at
                WHERE id = :class_id
            """)

            await self.db.execute(
                update_count_sql,
                {
                    "increment": len(new_member_ids),
                    "updated_at": now,
                    "class_id": class_id
                }
            )

            await self.db.commit()

            # Prepare response
            successful = [{"member_id": str(sid)} for sid in new_member_ids]
            failed = [{"member_id": str(sid), "reason": "Already enrolled"} for sid in existing_member_ids]

            new_total = class_obj.current_students + len(new_member_ids)
            
            return {
                "successful_enrollments": len(successful),
                "failed_enrollments": len(failed),
                "successful": successful,
                "failed": failed,
                "class_capacity_after": f"{new_total}/{class_obj.maximum_students}"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk enrollment failed: {str(e)}")
    
    async def academic_year_rollover(self, current_year: str, new_year: str, tenant_id: UUID) -> dict:
        """Roll over the academic year using raw SQL.

        Grade/section live on the CLASS, not on the member, so there is no per-member
        grade to promote here — we simply close out the prior year's active enrollments.
        """
        try:
            # 1. Get current enrollments count (distinct members)
            count_sql = text("""
                SELECT COUNT(DISTINCT e.member_id) as member_count
                FROM enrollments e
                JOIN classes c ON e.class_id = c.id
                WHERE e.academic_year = :current_year
                AND c.tenant_id = :tenant_id
                AND e.status = 'active'
                AND e.is_deleted = false
            """)

            result = await self.db.execute(
                count_sql,
                {"current_year": current_year, "tenant_id": tenant_id}
            )
            member_count = result.scalar()

            # 2. Mark old enrollments as completed
            complete_enrollments_sql = text("""
                UPDATE enrollments
                SET status = 'completed',
                    updated_at = :updated_at
                WHERE academic_year = :current_year
                AND class_id IN (
                    SELECT id FROM classes WHERE tenant_id = :tenant_id
                )
                AND status = 'active'
            """)
            
            await self.db.execute(
                complete_enrollments_sql,
                {
                    "current_year": current_year,
                    "tenant_id": tenant_id,
                    "updated_at": datetime.utcnow()
                }
            )
            
            await self.db.commit()

            return {
                "promoted_students": member_count,
                "previous_academic_year": current_year,
                "new_academic_year": new_year,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Academic year rollover failed: {str(e)}")
    
    async def bulk_update_enrollment_status(self, enrollment_ids: List[UUID], new_status: str, tenant_id: Any = None) -> dict:
        """Bulk update enrollment status, scoped to the caller's tenant."""
        try:
            update_sql = text("""
                UPDATE enrollments
                SET status = :new_status,
                    updated_at = :updated_at
                WHERE id = ANY(:enrollment_ids)
                AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
                AND is_deleted = false
            """)

            result = await self.db.execute(
                update_sql,
                {
                    "new_status": new_status,
                    "updated_at": datetime.utcnow(),
                    "enrollment_ids": [str(eid) for eid in enrollment_ids],
                    "tenant_id": str(tenant_id) if tenant_id else None,
                }
            )

            await self.db.commit()

            return {
                "updated_enrollments": result.rowcount,
                "new_status": new_status,
                "status": "success"
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk status update failed: {str(e)}")
    
    async def bulk_transfer_students(self, member_ids: List[UUID], from_class_id: UUID, to_class_id: UUID, academic_year: str, tenant_id: Any = None) -> dict:
        """Bulk transfer members between classes using raw SQL"""
        try:
            # Both classes must belong to the caller's tenant.
            from ...class_management.services.class_service import ClassService
            class_service = ClassService(self.db)
            target_class = await class_service.get(to_class_id, tenant_id=tenant_id)
            if not target_class:
                raise HTTPException(status_code=404, detail="Target class not found")
            source_class = await class_service.get(from_class_id, tenant_id=tenant_id)
            if not source_class:
                raise HTTPException(status_code=404, detail="Source class not found")

            # Only transfer members that belong to this tenant.
            vsql = text("SELECT id FROM members WHERE id = ANY(:sids) AND tenant_id = :tid AND is_deleted = false")
            vres = await self.db.execute(vsql, {"sids": [str(s) for s in member_ids], "tid": target_class.tenant_id})
            member_ids = [r[0] for r in vres.fetchall()]
            if not member_ids:
                raise HTTPException(status_code=400, detail="No valid members to transfer")

            available_spots = target_class.maximum_students - target_class.current_students

            if len(member_ids) > available_spots:
                raise HTTPException(
                    status_code=400,
                    detail=f"Not enough spots in target class. Available: {available_spots}, Requested: {len(member_ids)}"
                )

            # 1. Deactivate old enrollments
            deactivate_sql = text("""
                UPDATE enrollments
                SET status = 'transferred',
                    updated_at = :updated_at
                WHERE member_id = ANY(:member_ids)
                AND class_id = :from_class_id
                AND academic_year = :academic_year
                AND status = 'active'
                AND is_deleted = false
            """)

            await self.db.execute(
                deactivate_sql,
                {
                    "member_ids": [str(sid) for sid in member_ids],
                    "from_class_id": from_class_id,
                    "academic_year": academic_year,
                    "updated_at": datetime.utcnow()
                }
            )

            # 2. Create new enrollments
            now = datetime.utcnow()
            new_enrollments = []

            for member_id in member_ids:
                new_enrollments.append({
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(target_class.tenant_id),
                    "member_id": str(member_id),
                    "class_id": str(to_class_id),
                    "enrollment_date": now,
                    "academic_year": academic_year,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                    "is_deleted": False
                })

            create_sql = text("""
                INSERT INTO enrollments (
                    id, tenant_id, member_id, class_id, enrollment_date,
                    academic_year, status, created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :member_id, :class_id, :enrollment_date,
                    :academic_year, :status, :created_at, :updated_at, :is_deleted
                )
            """)

            await self.db.execute(create_sql, new_enrollments)
            
            # 3. Update class student counts
            # Decrease from_class count
            decrease_sql = text("""
                UPDATE classes 
                SET current_students = current_students - :decrement,
                    updated_at = :updated_at
                WHERE id = :class_id
            """)
            
            await self.db.execute(
                decrease_sql,
                {
                    "decrement": len(member_ids),
                    "updated_at": now,
                    "class_id": from_class_id
                }
            )
            
            # Increase to_class count
            increase_sql = text("""
                UPDATE classes 
                SET current_students = current_students + :increment,
                    updated_at = :updated_at
                WHERE id = :class_id
            """)
            
            await self.db.execute(
                increase_sql,
                {
                    "increment": len(member_ids),
                    "updated_at": now,
                    "class_id": to_class_id
                }
            )

            await self.db.commit()

            return {
                "transferred_students": len(member_ids),
                "from_class_id": str(from_class_id),
                "to_class_id": str(to_class_id),
                "academic_year": academic_year,
                "status": "success"
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk transfer failed: {str(e)}")

    # NEW BULK METHODS (Additional methods that were missing proper integration)
    
    async def bulk_import_enrollments(self, enrollments_data: List[dict], tenant_id: Any = None) -> dict:
        """Bulk import enrollments using raw SQL (tenant-scoped via each row's class)."""
        try:
            if not enrollments_data:
                raise HTTPException(status_code=400, detail="No enrollment data provided")

            # Resolve each referenced class's tenant once; restrict to the caller's tenant.
            class_ids = list({str(e.get("class_id")) for e in enrollments_data if e.get("class_id")})
            cmap = {}
            if class_ids:
                cres = await self.db.execute(
                    text("SELECT id, tenant_id FROM classes WHERE id = ANY(:cids) AND is_deleted = false"),
                    {"cids": class_ids},
                )
                cmap = {str(cid): str(tid) for cid, tid in cres.fetchall()}

            # Validate and prepare bulk insert data
            now = datetime.utcnow()
            insert_data = []
            validation_errors = []
            
            for idx, enrollment_data in enumerate(enrollments_data):
                try:
                    # Validate required fields
                    required_fields = ["member_id", "class_id", "academic_year"]
                    for field in required_fields:
                        if not enrollment_data.get(field):
                            validation_errors.append(f"Row {idx + 1}: Missing required field '{field}'")
                            continue
                    
                    if validation_errors:
                        continue

                    cid = str(enrollment_data["class_id"])
                    class_tenant = cmap.get(cid)
                    if not class_tenant:
                        validation_errors.append(f"Row {idx + 1}: Class not found")
                        continue
                    if tenant_id is not None and class_tenant != str(tenant_id):
                        validation_errors.append(f"Row {idx + 1}: Class belongs to another school")
                        continue

                    # Prepare enrollment record
                    enrollment_record = {
                        "id": str(uuid.uuid4()),
                        "tenant_id": class_tenant,
                        "member_id": str(enrollment_data["member_id"]),
                        "class_id": cid,
                        "enrollment_date": enrollment_data.get("enrollment_date", now),
                        "academic_year": enrollment_data["academic_year"],
                        "status": enrollment_data.get("status", "active"),
                        "created_at": now,
                        "updated_at": now,
                        "is_deleted": False
                    }
                    insert_data.append(enrollment_record)
                    
                except Exception as e:
                    validation_errors.append(f"Row {idx + 1}: {str(e)}")
            
            if validation_errors:
                raise HTTPException(
                    status_code=400, 
                    detail={"message": "Validation errors found", "errors": validation_errors}
                )
            
            # Bulk insert using raw SQL
            bulk_insert_sql = text("""
                INSERT INTO enrollments (
                    id, tenant_id, member_id, class_id, enrollment_date, academic_year,
                    status, created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :member_id, :class_id, :enrollment_date, :academic_year,
                    :status, :created_at, :updated_at, :is_deleted
                ) ON CONFLICT (member_id, class_id, academic_year) DO NOTHING
            """)

            if insert_data:
                await self.db.execute(bulk_insert_sql, insert_data)
                await self.db.commit()

            return {
                "total_records_processed": len(enrollments_data),
                "successful_enrollments": len(insert_data),
                "failed_enrollments": len(validation_errors),
                "validation_errors": validation_errors or None,
                "status": "success"
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk import failed: {str(e)}")

    async def bulk_enroll_by_grade(self, grade_level: int, target_class_ids: List[UUID], academic_year: str, tenant_id: UUID) -> dict:
        """Bulk enroll members across multiple classes for a grade.

        Grade lives on the CLASS (the target classes are the grade), not on the member,
        so we distribute the tenant's unenrolled members across the supplied classes.
        """
        try:
            # Restrict target classes to the caller's tenant (and avoid div-by-zero below).
            if target_class_ids:
                cres = await self.db.execute(
                    text("SELECT id FROM classes WHERE id = ANY(:cids) AND tenant_id = :tid AND is_deleted = false"),
                    {"cids": [str(c) for c in target_class_ids], "tid": tenant_id},
                )
                target_class_ids = [r[0] for r in cres.fetchall()]
            if not target_class_ids:
                raise HTTPException(status_code=400, detail="No valid target classes for this tenant")

            # Get members who aren't enrolled for this academic year
            unenrolled_members_sql = text("""
                SELECT m.id
                FROM members m
                LEFT JOIN enrollments e ON m.id = e.member_id
                    AND e.academic_year = :academic_year
                    AND e.status = 'active'
                    AND e.is_deleted = false
                WHERE m.tenant_id = :tenant_id
                AND m.is_deleted = false
                AND m.status = 'active'
                AND e.id IS NULL
            """)

            result = await self.db.execute(
                unenrolled_members_sql,
                {
                    "tenant_id": tenant_id,
                    "academic_year": academic_year
                }
            )

            unenrolled_member_ids = [row[0] for row in result.fetchall()]

            if not unenrolled_member_ids:
                return {
                    "enrolled_students": 0,
                    "message": f"No unenrolled members found for grade level {grade_level}",
                    "status": "success"
                }

            # Distribute members across target classes
            now = datetime.utcnow()
            enrollment_data = []
            members_per_class = len(unenrolled_member_ids) // len(target_class_ids)
            remaining_members = len(unenrolled_member_ids) % len(target_class_ids)

            member_index = 0
            for i, class_id in enumerate(target_class_ids):
                # Calculate how many members for this class
                members_for_this_class = members_per_class
                if i < remaining_members:
                    members_for_this_class += 1

                # Assign members to this class
                for _ in range(members_for_this_class):
                    if member_index < len(unenrolled_member_ids):
                        enrollment_data.append({
                            "id": str(uuid.uuid4()),
                            "tenant_id": str(tenant_id),
                            "member_id": str(unenrolled_member_ids[member_index]),
                            "class_id": str(class_id),
                            "enrollment_date": now,
                            "academic_year": academic_year,
                            "status": "active",
                            "created_at": now,
                            "updated_at": now,
                            "is_deleted": False
                        })
                        member_index += 1

            # Execute bulk insert
            bulk_insert_sql = text("""
                INSERT INTO enrollments (
                    id, tenant_id, member_id, class_id, enrollment_date, academic_year,
                    status, created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :member_id, :class_id, :enrollment_date, :academic_year,
                    :status, :created_at, :updated_at, :is_deleted
                )
            """)

            await self.db.execute(bulk_insert_sql, enrollment_data)
            
            # Update class student counts
            for class_id in target_class_ids:
                class_enrollments = [e for e in enrollment_data if e["class_id"] == str(class_id)]
                if class_enrollments:
                    update_count_sql = text("""
                        UPDATE classes 
                        SET current_students = current_students + :increment,
                            updated_at = :updated_at
                        WHERE id = :class_id
                    """)
                    
                    await self.db.execute(
                        update_count_sql,
                        {
                            "increment": len(class_enrollments),
                            "updated_at": now,
                            "class_id": class_id
                        }
                    )
            
            await self.db.commit()
            
            return {
                "enrolled_students": len(enrollment_data),
                "grade_level": grade_level,
                "target_classes": len(target_class_ids),
                "academic_year": academic_year,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk enrollment by grade failed: {str(e)}")

    async def bulk_withdraw_students(self, member_ids: List[UUID], academic_year: str, withdrawal_reason: str = "Withdrawn", tenant_id: Any = None) -> dict:
        """Bulk withdraw members from all enrollments (tenant-scoped)."""
        try:
            if not member_ids:
                raise HTTPException(status_code=400, detail="No member IDs provided")

            withdraw_sql = text("""
                UPDATE enrollments
                SET status = :withdrawal_reason,
                    updated_at = :updated_at
                WHERE member_id = ANY(:member_ids)
                AND academic_year = :academic_year
                AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
                AND status = 'active'
                AND is_deleted = false
            """)

            result = await self.db.execute(
                withdraw_sql,
                {
                    "withdrawal_reason": withdrawal_reason,
                    "updated_at": datetime.utcnow(),
                    "member_ids": [str(sid) for sid in member_ids],
                    "academic_year": academic_year,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                }
            )

            # Update class student counts (decrease)
            update_counts_sql = text("""
                UPDATE classes
                SET current_students = (
                    SELECT COUNT(*)
                    FROM enrollments
                    WHERE class_id = classes.id
                    AND status = 'active'
                    AND is_deleted = false
                ),
                updated_at = :updated_at
                WHERE id IN (
                    SELECT DISTINCT class_id
                    FROM enrollments
                    WHERE member_id = ANY(:member_ids)
                    AND academic_year = :academic_year
                )
            """)

            await self.db.execute(
                update_counts_sql,
                {
                    "updated_at": datetime.utcnow(),
                    "member_ids": [str(sid) for sid in member_ids],
                    "academic_year": academic_year
                }
            )
            
            await self.db.commit()
            
            return {
                "withdrawn_students": result.rowcount,
                "academic_year": academic_year,
                "withdrawal_reason": withdrawal_reason,
                "status": "success"
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk withdrawal failed: {str(e)}")

    async def bulk_auto_assign_enrollments(self, tenant_id: UUID, academic_year: str, grade_level: Optional[int] = None) -> dict:
        """Auto-assign unenrolled members to available classes with capacity.

        Grade lives on the CLASS, not the member, so the optional grade_level filters
        the candidate CLASSES; members are then packed into whatever capacity exists.
        """
        try:
            # Get unenrolled members for this academic year
            unenrolled_query = text("""
                SELECT m.id
                FROM members m
                LEFT JOIN enrollments e ON m.id = e.member_id
                    AND e.academic_year = :academic_year
                    AND e.status = 'active'
                    AND e.is_deleted = false
                WHERE m.tenant_id = :tenant_id
                AND m.is_deleted = false
                AND m.status = 'active'
                AND e.id IS NULL
            """)

            params = {"tenant_id": tenant_id, "academic_year": academic_year}

            result = await self.db.execute(unenrolled_query, params)
            unenrolled_members = [row[0] for row in result.fetchall()]

            if not unenrolled_members:
                return {
                    "assigned_students": 0,
                    "message": "No unenrolled members found",
                    "status": "success"
                }

            assigned_count = 0
            now = datetime.utcnow()

            # Get available classes (optionally scoped to a grade) ordered by free capacity.
            available_classes_query = """
                SELECT id, maximum_students, current_students
                FROM classes
                WHERE tenant_id = :tenant_id
                AND academic_year = :academic_year
                AND is_active = true
                AND is_deleted = false
                AND current_students < maximum_students
            """
            class_params = {"tenant_id": tenant_id, "academic_year": academic_year}
            if grade_level is not None:
                available_classes_query += " AND grade_level = :grade_level"
                class_params["grade_level"] = grade_level
            available_classes_query += " ORDER BY (maximum_students - current_students) DESC"

            result = await self.db.execute(text(available_classes_query), class_params)
            available_classes = result.fetchall()

            if available_classes:
                # Pack members into classes with capacity.
                enrollment_data = []
                member_index = 0

                for class_id, max_capacity, current_students in available_classes:
                    available_spots = max_capacity - current_students

                    while available_spots > 0 and member_index < len(unenrolled_members):
                        enrollment_data.append({
                            "id": str(uuid.uuid4()),
                            "tenant_id": str(tenant_id),
                            "member_id": str(unenrolled_members[member_index]),
                            "class_id": str(class_id),
                            "enrollment_date": now,
                            "academic_year": academic_year,
                            "status": "active",
                            "created_at": now,
                            "updated_at": now,
                            "is_deleted": False
                        })
                        member_index += 1
                        available_spots -= 1

                if enrollment_data:
                    bulk_insert_sql = text("""
                        INSERT INTO enrollments (
                            id, tenant_id, member_id, class_id, enrollment_date, academic_year,
                            status, created_at, updated_at, is_deleted
                        ) VALUES (
                            :id, :tenant_id, :member_id, :class_id, :enrollment_date, :academic_year,
                            :status, :created_at, :updated_at, :is_deleted
                        )
                    """)

                    await self.db.execute(bulk_insert_sql, enrollment_data)
                    assigned_count += len(enrollment_data)

                    # Update class counts
                    class_counts = {}
                    for enrollment in enrollment_data:
                        cid = enrollment["class_id"]
                        class_counts[cid] = class_counts.get(cid, 0) + 1

                    for cid, count in class_counts.items():
                        update_count_sql = text("""
                            UPDATE classes
                            SET current_students = current_students + :increment,
                                updated_at = :updated_at
                            WHERE id = :class_id
                        """)

                        await self.db.execute(
                            update_count_sql,
                            {"increment": count, "updated_at": now, "class_id": cid}
                        )

            await self.db.commit()

            return {
                "assigned_students": assigned_count,
                "total_unenrolled": len(unenrolled_members),
                "academic_year": academic_year,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Auto-assignment failed: {str(e)}")

    async def bulk_soft_delete_enrollments(self, enrollment_ids: List[UUID]) -> dict:
        """Bulk soft delete enrollments using raw SQL"""
        try:
            if not enrollment_ids:
                raise HTTPException(status_code=400, detail="No enrollment IDs provided")
            
            delete_sql = text("""
                UPDATE enrollments
                SET is_deleted = true,
                    status = 'deleted',
                    updated_at = :updated_at
                WHERE id = ANY(:enrollment_ids)
                AND is_deleted = false
            """)
            
            result = await self.db.execute(
                delete_sql,
                {
                    "updated_at": datetime.utcnow(),
                    "enrollment_ids": [str(eid) for eid in enrollment_ids]
                }
            )
            
            await self.db.commit()
            
            return {
                "deleted_enrollments": result.rowcount,
                "status": "success"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")

    async def get_comprehensive_enrollment_statistics(self, tenant_id: UUID, academic_year: Optional[str] = None) -> dict:
        """Get comprehensive enrollment statistics using raw SQL for performance"""
        try:
            base_where = "WHERE e.is_deleted = false"
            params = {}
            
            if tenant_id:
                base_where += " AND c.tenant_id = :tenant_id"
                params["tenant_id"] = tenant_id
            
            if academic_year:
                base_where += " AND e.academic_year = :academic_year"
                params["academic_year"] = academic_year
            
            # Main statistics
            stats_sql = text(f"""
                SELECT 
                    COUNT(*) as total_enrollments,
                    COUNT(CASE WHEN e.status = 'active' THEN 1 END) as active_enrollments,
                    COUNT(CASE WHEN e.status = 'completed' THEN 1 END) as completed_enrollments,
                    COUNT(CASE WHEN e.status = 'transferred' THEN 1 END) as transferred_enrollments,
                    COUNT(CASE WHEN e.status = 'withdrawn' THEN 1 END) as withdrawn_enrollments,
                    COUNT(DISTINCT e.member_id) as unique_students,
                    COUNT(DISTINCT e.class_id) as unique_classes
                FROM enrollments e
                JOIN classes c ON e.class_id = c.id
                {base_where}
            """)

            result = await self.db.execute(stats_sql, params)
            stats = result.fetchone()

            # Grade-wise enrollment distribution (grade lives on the class, not the member)
            grade_distribution_sql = text(f"""
                SELECT c.grade_level, COUNT(*) as enrollment_count
                FROM enrollments e
                JOIN classes c ON e.class_id = c.id
                {base_where}
                AND e.status = 'active'
                GROUP BY c.grade_level
                ORDER BY c.grade_level
            """)
            
            grade_result = await self.db.execute(grade_distribution_sql, params)
            grade_distribution = {row[0]: row[1] for row in grade_result.fetchall()}
            
            # Academic year distribution
            year_distribution_sql = text(f"""
                SELECT e.academic_year, COUNT(*) as enrollment_count
                FROM enrollments e
                JOIN classes c ON e.class_id = c.id
                {base_where}
                GROUP BY e.academic_year
                ORDER BY e.academic_year DESC
            """)
            
            year_result = await self.db.execute(year_distribution_sql, params)
            year_distribution = {row[0]: row[1] for row in year_result.fetchall()}
            
            return {
                "total_enrollments": stats[0] or 0,
                "active_enrollments": stats[1] or 0,
                "completed_enrollments": stats[2] or 0,
                "transferred_enrollments": stats[3] or 0,
                "withdrawn_enrollments": stats[4] or 0,
                "unique_students": stats[5] or 0,
                "unique_classes": stats[6] or 0,
                "enrollment_rate": round((stats[1] / stats[0] * 100), 2) if stats[0] > 0 else 0,
                "grade_distribution": grade_distribution,
                "academic_year_distribution": year_distribution,
                "tenant_id": str(tenant_id),
                "academic_year": academic_year
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")
