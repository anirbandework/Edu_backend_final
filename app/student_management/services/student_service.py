# app/student_management/services/student_service.py
"""StudentService — the admin "Students" page, now backed by the UNIFIED
`members` table (Member ORM) instead of the legacy `students` table.

A "student" is a Member row carrying a SOFT tag: profile['category'] == 'student'.
Every read here filters on that tag so staff members are never surfaced as
students; every write stamps it on create/import.

Field mapping (legacy students column -> members):
  id            -> members.id (UUID)
  student_id    -> members.staff_id  (human HRID, e.g. "STU001")
  first/last/email/phone/date_of_birth/gender/address/status/password_hash
                -> members columns of the same name
  roll_number, admission_number, academic_year, grade_level, section, parent_info,
  health_medical_info, emergency_information, behavioral_disciplinary,
  extended_academic_info, enrollment_details, financial_info, extracurricular_social,
  attendance_engagement, additional_metadata
                -> stored INSIDE members.profile JSON under the SAME keys.

TRANSITIONAL: grade_level / section live in profile here, but the AUTHORITATIVE
grade/section for a student is their ENROLMENT class (Enrollment.member_id ->
ClassModel). The bulk grade/section/promote ops below mutate profile only; they do
NOT move enrolments. get_student_classes (router) reads the real enrolment.

The legacy `students` table and Student ORM are intentionally untouched (still FK'd
by exams/assessments/chat). This service no longer references them.
"""
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from ...services.base_service import BaseService
from ...staff_management.models.member import Member
from ...auth_rbac.access.service import RBACService

# The soft tag that distinguishes student-members from every other member.
STUDENT_CATEGORY = "student"

# Keys that map to dedicated Member columns (NOT into profile).
_COLUMN_KEYS = {
    "tenant_id", "first_name", "last_name", "email", "phone",
    "date_of_birth", "gender", "address", "status",
}
# Keys that are stored inside members.profile (and re-exposed on responses).
_PROFILE_KEYS = [
    "roll_number", "admission_number", "academic_year", "grade_level", "section",
    "parent_info", "health_medical_info", "emergency_information",
    "behavioral_disciplinary", "extended_academic_info", "enrollment_details",
    "financial_info", "extracurricular_social", "attendance_engagement",
    "additional_metadata",
]


def _is_student_clause():
    """SQLAlchemy predicate: members.profile->>'category' = 'student'.
    profile is the generic JSON type (not the PG dialect type), so `.as_string()`
    is used (not `.astext`) — it compiles to the PG ->> text accessor."""
    return Member.profile["category"].as_string() == STUDENT_CATEGORY


def _prof_get(member: Member, key: str, default=None):
    p = member.profile or {}
    return p.get(key, default)


class StudentService(BaseService[Member]):
    """CRUD for student-members. The exported name stays `StudentService` and the
    public method surface is unchanged so the router import and call-sites keep
    working; only the backing table changed (students -> members)."""

    def __init__(self, db: AsyncSession):
        super().__init__(Member, db)

    # ---------------- role assignment ----------------
    async def _ensure_student_role_id(self, tenant_id) -> UUID:
        """Every student-member needs an rbac role. Reuse the tenant's default
        'staff' role; if none exists, create a default 'Student' staff role."""
        role_id = await RBACService.get_default_role_id(self.db, tenant_id, "staff")
        if role_id:
            return role_id
        # No default staff role for this tenant yet — create one. is_default=True is
        # safe here precisely because get_default_role_id returned None (no existing
        # default to steal), matching the task's None-branch contract.
        role = await RBACService.create_role(
            self.db, tenant_id=tenant_id, user_type="staff",
            role_name="Student", is_default=True,
        )
        return role.id

    # ---------------- helpers ----------------
    def _student_scope(self, stmt, tenant_id=None):
        stmt = stmt.where(Member.is_deleted == False, _is_student_clause())  # noqa: E712
        if tenant_id is not None:
            stmt = stmt.where(Member.tenant_id == tenant_id)
        return stmt

    async def get(self, id: Any, tenant_id: Any = None) -> Optional[Member]:
        """Override BaseService.get to constrain to student-members only."""
        stmt = self._student_scope(select(Member).where(Member.id == id), tenant_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_tenant(self, tenant_id: UUID) -> List[Member]:
        stmt = self._student_scope(select(Member), tenant_id).order_by(
            func.coalesce(Member.first_name, "zzz").asc(),
            func.coalesce(Member.last_name, "zzz").asc(),
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def get_by_student_id(self, student_id: str, tenant_id: Optional[UUID] = None) -> Optional[Member]:
        """Look up a student-member by their human student_id (-> staff_id)."""
        stmt = self._student_scope(
            select(Member).where(Member.staff_id == student_id), tenant_id
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_students_by_grade(self, grade_level: int, tenant_id: Optional[UUID] = None) -> List[Member]:
        stmt = self._student_scope(
            select(Member).where(Member.profile["grade_level"].as_string() == str(grade_level)),
            tenant_id,
        )
        return (await self.db.execute(stmt)).scalars().all()

    # ---------------- create ----------------
    async def create(self, obj_in: dict) -> Member:
        """Create a student-member: maps profile keys into members.profile, stamps
        profile.category='student', assigns the default staff role, role='staff'."""
        tenant_id = obj_in.get("tenant_id")
        student_id = obj_in.get("student_id")

        # student_id (-> staff_id) uniqueness is app-level only and scoped to
        # student-members of this tenant (staff_id is shared with real staff codes,
        # so a global unique check would be wrong).
        if student_id and tenant_id:
            existing = await self.get_by_student_id(student_id, tenant_id)
            if existing:
                raise HTTPException(status_code=400, detail="Same student ID already exists")

        role_id = await self._ensure_student_role_id(tenant_id)

        # Build profile JSON from the profile keys + the soft category tag.
        profile: Dict[str, Any] = {"category": STUDENT_CATEGORY}
        for k in _PROFILE_KEYS:
            if obj_in.get(k) is not None:
                profile[k] = obj_in.get(k)

        member = Member(
            tenant_id=tenant_id,
            rbac_role_id=role_id,
            staff_id=student_id,
            # NOT-NULL columns on members — default blanks where the student form
            # leaves them empty (legacy students allowed NULLs; members do not).
            first_name=(obj_in.get("first_name") or "").strip(),
            last_name=(obj_in.get("last_name") or "").strip(),
            email=(obj_in.get("email") or None),
            phone=(obj_in.get("phone") or "").strip(),
            date_of_birth=obj_in.get("date_of_birth"),
            gender=obj_in.get("gender"),
            address=obj_in.get("address"),
            status=obj_in.get("status") or "active",
            role="staff",
            profile=profile,
        )
        self.db.add(member)
        try:
            await self.db.commit()
        except IntegrityError:
            # Only `email` carries a DB unique constraint on members.
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="That email is already in use.")
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        await self.db.refresh(member)
        return member

    # ---------------- update ----------------
    async def update(self, id: Any, obj_in: Dict, tenant_id: Any = None) -> Optional[Member]:
        """Update a student-member. Column keys hit Member columns; profile keys are
        merged into members.profile."""
        member = await self.get(id, tenant_id=tenant_id)
        if not member:
            return None

        profile = dict(member.profile or {})
        for key, value in obj_in.items():
            if key in _PROFILE_KEYS:
                profile[key] = value
            elif key in _COLUMN_KEYS and hasattr(Member, key):
                setattr(member, key, value)
        profile["category"] = STUDENT_CATEGORY  # keep the soft tag intact
        member.profile = profile
        # Reassign so SQLAlchemy detects the JSON mutation.
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="That email is already in use.")
        await self.db.refresh(member)
        return member

    async def soft_delete(self, id: Any, tenant_id: Any = None) -> bool:
        member = await self.get(id, tenant_id=tenant_id)
        if not member:
            return False
        member.is_deleted = True
        member.status = "inactive"
        await self.db.commit()
        return True

    # ---------------- paginated list ----------------
    async def get_students_paginated(
        self,
        page: int = 1,
        size: int = 20,
        tenant_id: Optional[UUID] = None,
        grade_level: Optional[int] = None,
        section: Optional[str] = None,
    ) -> dict:
        """Paginated student-members, alphabetical, tenant + profile filters."""
        offset = (page - 1) * size

        def _filters(stmt):
            stmt = self._student_scope(stmt, tenant_id)
            if grade_level is not None:
                stmt = stmt.where(Member.profile["grade_level"].as_string() == str(grade_level))
            if section:
                stmt = stmt.where(Member.profile["section"].as_string() == section)
            return stmt

        stmt = _filters(select(Member)).order_by(
            func.coalesce(Member.first_name, "zzz").asc(),
            func.coalesce(Member.last_name, "zzz").asc(),
        )
        count_stmt = _filters(select(func.count()).select_from(Member))

        total = (await self.db.execute(count_stmt)).scalar()
        items = (await self.db.execute(stmt.offset(offset).limit(size))).scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": (total + size - 1) // size if total else 0,
            "has_next": page * size < total,
            "has_previous": page > 1,
        }

    async def get_paginated(self, page: int = 1, size: int = 20, **filters):
        """Used by the export endpoint. Honours tenant_id/grade_level/section/status
        filters, scoped to student-members."""
        tenant_id = filters.get("tenant_id")
        grade_level = filters.get("grade_level")
        section = filters.get("section")
        status = filters.get("status")
        offset = (page - 1) * size

        def _apply(stmt):
            stmt = self._student_scope(stmt, tenant_id)
            if grade_level is not None:
                stmt = stmt.where(Member.profile["grade_level"].as_string() == str(grade_level))
            if section:
                stmt = stmt.where(Member.profile["section"].as_string() == section)
            if status:
                stmt = stmt.where(Member.status == status)
            return stmt

        stmt = _apply(select(Member))
        count_stmt = _apply(select(func.count()).select_from(Member))
        total = (await self.db.execute(count_stmt)).scalar()
        items = (await self.db.execute(stmt.offset(offset).limit(size))).scalars().all()
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": (total + size - 1) // size if total else 0,
            "has_next": page * size < total,
            "has_previous": page > 1,
        }

    # ---------------- bulk operations ----------------
    # These use ORM iteration over student-members (profile is JSON, not JSONB, so
    # jsonb_set-style raw UPDATEs are avoided in favour of safe dict mutation).

    async def bulk_import_students(self, students_data: List[dict], tenant_id: UUID) -> dict:
        """Bulk import student-members. Dedupes on the human student_id (->staff_id)
        and on phone, within this tenant's student-members + globally on phone."""
        try:
            if not students_data:
                raise HTTPException(status_code=400, detail="No student data provided")

            role_id = await self._ensure_student_role_id(tenant_id)

            # Existing student_ids (->staff_id) among this tenant's student-members.
            incoming_ids = [s.get("student_id") for s in students_data if s.get("student_id")]
            existing_student_ids = set()
            if incoming_ids:
                rows = await self.db.execute(
                    self._student_scope(
                        select(Member.staff_id).where(Member.staff_id.in_(incoming_ids)),
                        tenant_id,
                    )
                )
                existing_student_ids = {r for (r,) in rows.fetchall()}

            # Existing phones across ALL members (phone is globally indexed/unique-ish).
            incoming_phones = [s.get("phone") for s in students_data if s.get("phone")]
            existing_phones = set()
            if incoming_phones:
                rows = await self.db.execute(
                    select(Member.phone).where(
                        Member.phone.in_(incoming_phones),
                        Member.is_deleted == False,  # noqa: E712
                    )
                )
                existing_phones = {r for (r,) in rows.fetchall()}

            validation_errors: List[str] = []
            duplicate_errors: List[str] = []
            ids_in_batch: set = set()
            phones_in_batch: set = set()
            to_add: List[Member] = []

            for idx, sd in enumerate(students_data):
                student_id = sd.get("student_id")
                if not student_id:
                    validation_errors.append(f"Row {idx + 1}: Missing required field 'student_id'")
                    continue
                if student_id in existing_student_ids:
                    duplicate_errors.append(f"Row {idx + 1}: Student ID '{student_id}' already exists in database")
                    continue
                if student_id in ids_in_batch:
                    duplicate_errors.append(f"Row {idx + 1}: Student ID '{student_id}' is duplicate in this batch")
                    continue
                ids_in_batch.add(student_id)

                phone = sd.get("phone")
                if phone:
                    if phone in existing_phones:
                        duplicate_errors.append(f"Row {idx + 1}: Phone number '{phone}' already exists in database")
                        continue
                    if phone in phones_in_batch:
                        duplicate_errors.append(f"Row {idx + 1}: Phone number '{phone}' is duplicate in this batch")
                        continue
                    phones_in_batch.add(phone)

                # Parse date_of_birth (iso string) if present.
                date_of_birth = None
                if sd.get("date_of_birth"):
                    try:
                        date_str = sd["date_of_birth"]
                        if isinstance(date_str, str):
                            if date_str.endswith("Z"):
                                date_str = date_str[:-1] + "+00:00"
                            date_of_birth = datetime.fromisoformat(date_str).replace(tzinfo=None)
                        elif isinstance(date_str, datetime):
                            date_of_birth = date_str.replace(tzinfo=None)
                    except Exception as e:
                        validation_errors.append(f"Row {idx + 1}: Invalid date format for date_of_birth: {str(e)}")
                        continue

                profile: Dict[str, Any] = {"category": STUDENT_CATEGORY}
                for k in _PROFILE_KEYS:
                    if sd.get(k) is not None:
                        profile[k] = sd.get(k)

                to_add.append(Member(
                    tenant_id=tenant_id,
                    rbac_role_id=role_id,
                    staff_id=student_id,
                    first_name=(sd.get("first_name") or "").strip(),
                    last_name=(sd.get("last_name") or "").strip(),
                    email=(sd.get("email") or None),
                    phone=(phone or "").strip(),
                    date_of_birth=date_of_birth,
                    gender=sd.get("gender"),
                    address=sd.get("address"),
                    status=sd.get("status", "active"),
                    role="staff",
                    profile=profile,
                ))

            successful_imports = 0
            if to_add:
                self.db.add_all(to_add)
                await self.db.commit()
                successful_imports = len(to_add)

            return {
                "total_records_processed": len(students_data),
                "successful_imports": successful_imports,
                "failed_imports": len(validation_errors) + len(duplicate_errors),
                "duplicate_records": len(duplicate_errors),
                "validation_errors": validation_errors if validation_errors else None,
                "duplicate_errors": duplicate_errors if duplicate_errors else None,
                "tenant_id": str(tenant_id),
                "status": "success" if successful_imports > 0 else "failed",
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk import failed: {str(e)}")

    async def _fetch_students_by_uuids(self, ids: List[str], tenant_id: UUID) -> List[Member]:
        clean = []
        for i in ids:
            try:
                clean.append(str(UUID(str(i))))
            except (ValueError, TypeError):
                continue
        if not clean:
            return []
        stmt = self._student_scope(select(Member).where(Member.id.in_(clean)), tenant_id)
        return (await self.db.execute(stmt)).scalars().all()

    async def bulk_update_grades(self, grade_updates: List[dict], tenant_id: UUID) -> dict:
        """TRANSITIONAL: updates profile.grade_level only. The authoritative grade is
        the student's enrolment class — this does NOT move enrolments."""
        try:
            if not grade_updates:
                raise HTTPException(status_code=400, detail="No grade update data provided")

            updated = 0
            for update in grade_updates:
                # Matches on the members.id UUID (field name may be student_id or student_uuid).
                sid = update.get("student_uuid") or update.get("student_id")
                new_grade = update.get("new_grade")
                if not sid or new_grade is None:
                    continue
                member = await self.get(sid, tenant_id=tenant_id)
                if not member:
                    continue
                profile = dict(member.profile or {})
                profile["grade_level"] = new_grade
                profile["category"] = STUDENT_CATEGORY
                member.profile = profile
                updated += 1

            await self.db.commit()
            return {
                "updated_students": updated,
                "total_requests": len(grade_updates),
                "tenant_id": str(tenant_id),
                "status": "success",
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk grade update failed: {str(e)}")

    async def bulk_promote_students(self, current_grade: int, tenant_id: UUID, academic_year: str) -> dict:
        """TRANSITIONAL: bumps profile.grade_level + sets profile.academic_year for
        active student-members at `current_grade`. Does NOT move enrolments."""
        try:
            stmt = self._student_scope(
                select(Member).where(
                    Member.profile["grade_level"].as_string() == str(current_grade),
                    Member.status == "active",
                ),
                tenant_id,
            )
            members = (await self.db.execute(stmt)).scalars().all()

            if not members:
                return {
                    "promoted_students": 0,
                    "from_grade": current_grade,
                    "to_grade": current_grade + 1,
                    "academic_year": academic_year,
                    "message": f"No students found in grade {current_grade}",
                    "tenant_id": str(tenant_id),
                    "status": "success",
                }

            for member in members:
                profile = dict(member.profile or {})
                try:
                    cur = int(profile.get("grade_level"))
                except (TypeError, ValueError):
                    cur = current_grade
                profile["grade_level"] = cur + 1
                profile["academic_year"] = academic_year
                profile["category"] = STUDENT_CATEGORY
                member.profile = profile

            await self.db.commit()
            return {
                "promoted_students": len(members),
                "from_grade": current_grade,
                "to_grade": current_grade + 1,
                "academic_year": academic_year,
                "tenant_id": str(tenant_id),
                "status": "success",
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk promotion failed: {str(e)}")

    async def bulk_update_status(self, student_ids: List[str], new_status: str, tenant_id: UUID) -> dict:
        """Updates members.status for the given member UUIDs (student-members only)."""
        try:
            if not student_ids:
                raise HTTPException(status_code=400, detail="No student IDs provided")

            valid_statuses = ["active", "inactive", "graduated", "transferred", "suspended", "expelled"]
            if new_status not in valid_statuses:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status. Must be one of: {valid_statuses}",
                )

            members = await self._fetch_students_by_uuids(student_ids, tenant_id)
            for member in members:
                member.status = new_status
            await self.db.commit()

            return {
                "message": f"Status update completed. {len(members)} students updated to '{new_status}'",
                "updated_students": len(members),
                "new_status": new_status,
                "tenant_id": str(tenant_id),
                "status": "success",
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk status update failed: {str(e)}")

    async def bulk_update_sections(self, section_updates: List[dict], tenant_id: UUID) -> dict:
        """TRANSITIONAL: updates profile.section only (authoritative section is the
        enrolment class). Does NOT move enrolments."""
        try:
            if not section_updates:
                raise HTTPException(status_code=400, detail="No section update data provided")

            updated = 0
            for update in section_updates:
                sid = update.get("student_uuid") or update.get("student_id")
                new_section = update.get("new_section")
                if not sid:
                    continue
                member = await self.get(sid, tenant_id=tenant_id)
                if not member:
                    continue
                profile = dict(member.profile or {})
                profile["section"] = new_section
                profile["category"] = STUDENT_CATEGORY
                member.profile = profile
                updated += 1

            await self.db.commit()
            return {
                "updated_students": updated,
                "total_requests": len(section_updates),
                "tenant_id": str(tenant_id),
                "status": "success",
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk section update failed: {str(e)}")

    async def bulk_soft_delete(self, student_ids: List[str], tenant_id: UUID) -> dict:
        """Bulk soft delete student-members (is_deleted=true, status='inactive')."""
        try:
            if not student_ids:
                raise HTTPException(status_code=400, detail="No student IDs provided")

            members = await self._fetch_students_by_uuids(student_ids, tenant_id)
            for member in members:
                member.is_deleted = True
                member.status = "inactive"
            await self.db.commit()

            return {
                "deleted_students": len(members),
                "tenant_id": str(tenant_id),
                "status": "success",
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")

    async def get_student_statistics(self, tenant_id: UUID) -> dict:
        """Statistics over this tenant's student-members. status counts from the
        members.status column; grade aggregates from profile->>'grade_level'."""
        try:
            members = await self.get_by_tenant(tenant_id)

            counts = {
                "active": 0, "inactive": 0, "graduated": 0,
                "transferred": 0, "suspended": 0, "expelled": 0,
            }
            grades: List[int] = []
            grade_distribution: Dict[int, int] = {}

            for m in members:
                if m.status in counts:
                    counts[m.status] += 1
                g = _prof_get(m, "grade_level")
                gi = None
                if g is not None:
                    try:
                        gi = int(g)
                    except (TypeError, ValueError):
                        gi = None
                if gi is not None:
                    grades.append(gi)
                    if m.status == "active":
                        grade_distribution[gi] = grade_distribution.get(gi, 0) + 1

            return {
                "total_students": len(members),
                "active_students": counts["active"],
                "inactive_students": counts["inactive"],
                "graduated_students": counts["graduated"],
                "transferred_students": counts["transferred"],
                "suspended_students": counts["suspended"],
                "expelled_students": counts["expelled"],
                "average_grade": round(sum(grades) / len(grades), 2) if grades else 0.0,
                "lowest_grade": min(grades) if grades else 0,
                "highest_grade": max(grades) if grades else 0,
                "grade_distribution": dict(sorted(grade_distribution.items())),
                "tenant_id": str(tenant_id),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")
