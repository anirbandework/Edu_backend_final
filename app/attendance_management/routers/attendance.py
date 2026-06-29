# app/routers/school_authority/attendance.py
from typing import List, Optional
from uuid import UUID
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from ...core.database import get_db
from ...attendance_management.services.attendance_service import AttendanceService
from ...attendance_management.models.attendance import AttendanceStatus, AttendanceType, UserType
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_staff, assert_same_tenant
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal


def _principal_user_type(principal: Principal) -> UserType:
    """Map the authenticated principal's role to an attendance UserType — never trust a
    client-supplied marker type. Authorities/super-admins mark as SCHOOL_AUTHORITY; a
    dynamic-model member (role 'staff') marks as STAFF. Never emit TEACHER."""
    return UserType.SCHOOL_AUTHORITY if (principal.is_authority or principal.is_super_admin) else UserType.STAFF


def _coerce_user_type(value: Optional[str]) -> Optional[UserType]:
    """Accept a user_type query param as either the enum value or NAME (any case)."""
    if not value:
        return None
    try:
        return UserType(value)
    except ValueError:
        try:
            return UserType[value.upper()]
        except KeyError:
            return None

# Pydantic Models
class AttendanceCreate(BaseModel):
    user_id: UUID
    user_type: UserType
    class_id: Optional[UUID] = None
    attendance_date: Optional[date] = None
    attendance_type: AttendanceType = AttendanceType.DAILY
    status: AttendanceStatus = AttendanceStatus.PRESENT
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    period_number: Optional[int] = None
    subject_name: Optional[str] = None
    location: Optional[str] = None
    remarks: Optional[str] = None
    reason_for_absence: Optional[str] = None
    academic_year: Optional[str] = None
    term: Optional[str] = None

class BulkAttendanceCreate(BaseModel):
    tenant_id: UUID
    attendance_records: List[dict]

class BulkStatusUpdate(BaseModel):
    attendance_ids: List[UUID]
    new_status: str
    updated_by: UUID

class BulkApproveAbsences(BaseModel):
    attendance_ids: List[UUID]
    approved_by: UUID
    approval_remarks: Optional[str] = None

class AttendanceUpdateItem(BaseModel):
    user_id: UUID
    status: str
    remarks: Optional[str] = ""

class BulkAttendanceUpdate(BaseModel):
    attendance_updates: List[AttendanceUpdateItem]
    attendance_date: date
    marked_by: UUID
    marked_by_type: UserType

class BulkStaffAttendanceUpdate(BaseModel):
    attendance_updates: List[dict]  # [{"user_id": UUID, "user_type": str, "status": str, "remarks": str}]
    attendance_date: date
    marked_by: UUID
    marked_by_type: UserType

router = APIRouter(prefix="/api/v1/school_authority/attendance", tags=["School Authority - Attendance Management"])

# MAIN ATTENDANCE MARKING ENDPOINTS

@router.post("/mark", response_model=dict)
async def mark_attendance(
    attendance_data: AttendanceCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('attendance'))
):
    """Mark attendance for a user (student, teacher, or staff). Staff only."""
    service = AttendanceService(db)
    # Derive the acting user AND their type from the verified principal — never the client.
    marked_by = UUID(principal.user_id)
    marked_by_type = _principal_user_type(principal)

    try:
        attendance = await service.mark_attendance(
            user_id=attendance_data.user_id,
            user_type=attendance_data.user_type,
            marked_by=marked_by,
            marked_by_type=marked_by_type,
            attendance_data=attendance_data.model_dump(exclude={"user_id", "user_type"}),
            tenant_id=(None if principal.is_super_admin else principal.tenant_id),
        )
        
        return {
            "id": str(attendance.id),
            "message": "Attendance marked successfully",
            "user_id": str(attendance.user_id),
            "user_type": attendance.user_type.value,
            "attendance_date": attendance.attendance_date.isoformat(),
            "status": attendance.status.value
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/bulk/mark", response_model=dict)
async def bulk_mark_attendance(
    import_data: BulkAttendanceCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('attendance'))  # staff (teacher/authority/super-admin) only
):
    """Bulk mark attendance for multiple users"""
    service = AttendanceService(db)
    # Override client-supplied tenant_id with the principal's tenant (non-super-admin)
    effective_tenant = import_data.tenant_id if principal.is_super_admin else principal.tenant_id

    result = await service.bulk_mark_attendance(
        attendance_records=import_data.attendance_records,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Bulk attendance marking completed. {result['successful_records']} records processed successfully",
        **result
    }


@router.post("/bulk/update-status", response_model=dict)
async def bulk_update_status(
    payload: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('attendance')),  # staff only
):
    """Bulk-update the status of given attendance records. The acting user is
    derived from the JWT (client-supplied updated_by is ignored)."""
    service = AttendanceService(db)
    return await service.bulk_update_attendance_status(
        attendance_ids=payload.attendance_ids,
        new_status=payload.new_status,
        updated_by=UUID(principal.user_id),
    )


@router.post("/bulk/approve-absences", response_model=dict)
async def bulk_approve_absences(
    payload: BulkApproveAbsences,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('attendance')),  # staff only
):
    """Bulk-approve (excuse) absences. The approver is the authenticated principal."""
    service = AttendanceService(db)
    return await service.bulk_approve_absences(
        attendance_ids=payload.attendance_ids,
        approved_by=UUID(principal.user_id),
        approval_remarks=payload.approval_remarks,
    )


@router.get("/dashboard/{tenant_id}")
async def attendance_dashboard(
    tenant_id: UUID,
    user_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Comprehensive attendance statistics for a school (tenant-scoped; non
    super-admins are forced to their own tenant)."""
    service = AttendanceService(db)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    date_range = None
    if start_date or end_date:
        date_range = {}
        if start_date:
            date_range["start_date"] = start_date
        if end_date:
            date_range["end_date"] = end_date
    return await service.get_attendance_dashboard_stats(
        tenant_id=effective_tenant,
        user_type=_coerce_user_type(user_type),
        date_range=date_range,
    )


@router.get("/low-attendance/{tenant_id}")
async def low_attendance_users(
    tenant_id: UUID,
    threshold_percentage: int = Query(75),
    user_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Users whose attendance is below a threshold over the last 30 days
    (tenant-scoped)."""
    service = AttendanceService(db)
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    return await service.get_low_attendance_users(
        tenant_id=effective_tenant,
        threshold_percentage=threshold_percentage,
        user_type=_coerce_user_type(user_type),
    )


@router.get("/class/{class_id}/date/{attendance_date}")
async def class_attendance_by_date(
    class_id: UUID,
    attendance_date: date,
    period_number: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Raw attendance records for a class on a date (full rows, for the admin
    class-by-date view). Tenant-scoped for non super-admins."""
    where = "WHERE class_id = :class_id AND attendance_date = :attendance_date AND is_deleted = false"
    params = {"class_id": str(class_id), "attendance_date": attendance_date}
    if not principal.is_super_admin:
        where += " AND tenant_id = :tenant_id"
        params["tenant_id"] = str(principal.tenant_id)
    if period_number is not None:
        where += " AND period_number = :period_number"
        params["period_number"] = period_number
    result = await db.execute(
        text(f"SELECT * FROM attendances {where} ORDER BY created_at DESC"), params
    )
    out = []
    for row in result.mappings().all():
        d = dict(row)
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif isinstance(v, UUID):
                d[k] = str(v)
        out.append(d)
    return out

# CLASS-BASED ATTENDANCE

@router.get("/class/{class_id}/students-with-attendance/{attendance_date}")
async def get_class_students_with_attendance(
    class_id: UUID,
    attendance_date: date,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all students in class with their attendance status for a specific date"""
    try:
        # Enforce tenant ownership of the class for non-super-admin principals
        if not principal.is_super_admin:
            tenant_check = await db.execute(
                text("SELECT tenant_id FROM classes WHERE id = :class_id AND is_deleted = false"),
                {"class_id": class_id}
            )
            tenant_row = tenant_check.fetchone()
            if not tenant_row:
                raise HTTPException(status_code=404, detail="Class not found")
            assert_same_tenant(principal, str(tenant_row[0]))

        students_with_attendance_sql = text("""
            SELECT 
                c.id as class_id,
                c.class_name,
                c.grade_level,
                c.section,
                c.academic_year,
                s.id as student_id,
                s.staff_id,
                s.first_name,
                s.last_name,
                (s.profile->>'roll_number'),
                a.id as attendance_id,
                a.status as attendance_status,
                a.attendance_time,
                a.remarks,
                a.is_excused
            FROM classes c
            JOIN enrollments e ON c.id = e.class_id
            JOIN members s ON e.member_id = s.id
            LEFT JOIN attendances a ON (
                s.id = a.user_id 
                AND a.attendance_date = :attendance_date 
                AND a.class_id = :class_id
                AND a.is_deleted = false
            )
            WHERE c.id = :class_id
            AND c.is_deleted = false
            AND e.status = 'active'
            AND e.is_deleted = false
            AND s.is_deleted = false
            AND s.status = 'active'
            ORDER BY s.first_name, s.last_name
        """)
        
        result = await db.execute(students_with_attendance_sql, {
            "class_id": class_id,
            "attendance_date": attendance_date
        })
        
        rows = result.fetchall()
        
        if not rows:
            raise HTTPException(status_code=404, detail="Class not found or no students enrolled")
        
        first_row = rows[0]
        class_info = {
            "id": str(first_row[0]),
            "class_name": first_row[1],
            "grade_level": first_row[2],
            "section": first_row[3],
            "academic_year": first_row[4]
        }
        
        students = []
        for row in rows:
            students.append({
                "student_id": str(row[5]),
                "student_number": row[6],
                "first_name": row[7],
                "last_name": row[8],
                "full_name": f"{row[7]} {row[8]}",
                "roll_number": row[9],
                "attendance_id": str(row[10]) if row[10] else None,
                "attendance_status": row[11] if row[11] else "not_marked",
                "attendance_time": row[12].isoformat() if row[12] else None,
                "remarks": row[13],
                "is_excused": row[14] if row[14] is not None else False
            })
        
        return {
            "class_info": class_info,
            "attendance_date": attendance_date.isoformat(),
            "students": students,
            "total_students": len(students),
            "marked_count": len([s for s in students if s["attendance_status"] != "not_marked"]),
            "present_count": len([s for s in students if s["attendance_status"] == "present"]),
            "absent_count": len([s for s in students if s["attendance_status"] == "absent"])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get class attendance: {str(e)}")

@router.post("/class/{class_id}/bulk-update-attendance")
async def bulk_update_class_attendance(
    class_id: UUID,
    request: BulkAttendanceUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('attendance'))  # staff (teacher/authority/super-admin) only
):
    """Bulk update attendance for multiple students in a class"""
    service = AttendanceService(db)
    # Derive acting user from the authenticated principal; do not trust client-supplied marked_by
    acting_user_id = UUID(principal.user_id)

    try:
        attendance_records = []
        for update in request.attendance_updates:
            attendance_records.append({
                "user_id": update.user_id,
                "user_type": "STUDENT",
                "class_id": class_id,
                "attendance_date": request.attendance_date,
                "status": update.status.upper(),
                "remarks": update.remarks or "",
                "marked_by": acting_user_id,
                "marked_by_type": _principal_user_type(principal).name,
                "attendance_type": "DAILY",
                "academic_year": "2025-26"
            })

        class_sql = text("SELECT tenant_id FROM classes WHERE id = :class_id")
        class_result = await db.execute(class_sql, {"class_id": class_id})
        tenant_row = class_result.fetchone()

        if not tenant_row:
            raise HTTPException(status_code=404, detail="Class not found")

        tenant_id = tenant_row[0]
        # Enforce that the principal may act on the class's tenant
        assert_same_tenant(principal, str(tenant_id))

        result = await service.bulk_mark_attendance(
            attendance_records=attendance_records,
            tenant_id=tenant_id
        )
        
        return {
            "message": f"Successfully updated attendance for {result['successful_records']} students",
            "class_id": str(class_id),
            "attendance_date": request.attendance_date.isoformat(),
            "updated_students": result["successful_records"],
            "failed_updates": result["failed_records"],
            "total_processed": len(request.attendance_updates)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update class attendance: {str(e)}")

# GRADE-LEVEL ATTENDANCE

@router.get("/grade/{tenant_id}/{grade_level}/{section}/students-with-attendance/{attendance_date}")
async def get_grade_students_with_attendance(
    tenant_id: UUID,
    grade_level: int,
    section: str,
    attendance_date: date,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all students in a grade+section with their attendance status for a specific date"""
    try:
        # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
        tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id
        students_with_attendance_sql = text("""
            SELECT 
                s.id as student_id,
                s.staff_id,
                s.first_name,
                s.last_name,
                (s.profile->>'roll_number'),
                (s.profile->>'grade_level')::int,
                (s.profile->>'section'),
                a.id as attendance_id,
                a.status as attendance_status,
                a.attendance_time,
                a.remarks,
                a.is_excused
            FROM (SELECT * FROM members WHERE (profile->>'category') = 'student') s
            LEFT JOIN (
                SELECT DISTINCT ON (user_id) 
                    id, user_id, status, attendance_time, remarks, is_excused
                FROM attendances 
                WHERE attendance_date = :attendance_date 
                AND user_type = 'STUDENT'
                AND class_id IS NULL
                AND is_deleted = false
                ORDER BY user_id, attendance_time DESC
            ) a ON s.id = a.user_id
            WHERE s.tenant_id = :tenant_id
            AND (s.profile->>'grade_level')::int = :grade_level
            AND (s.profile->>'section') = :section
            AND s.is_deleted = false
            AND s.status = 'active'
            ORDER BY s.first_name, s.last_name
        """)
        
        result = await db.execute(students_with_attendance_sql, {
            "tenant_id": tenant_id,
            "grade_level": grade_level,
            "section": section,
            "attendance_date": attendance_date
        })
        
        rows = result.fetchall()
        
        students = []
        for row in rows:
            students.append({
                "student_id": str(row[0]),
                "student_number": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "full_name": f"{row[2]} {row[3]}",
                "roll_number": row[4],
                "grade_level": row[5],
                "section": row[6],
                "attendance_id": str(row[7]) if row[7] else None,
                "attendance_status": row[8] if row[8] else "not_marked",
                "attendance_time": row[9].isoformat() if row[9] else None,
                "remarks": row[10],
                "is_excused": row[11] if row[11] is not None else False
            })
        
        return {
            "grade_info": {
                "grade_level": grade_level,
                "section": section,
                "tenant_id": str(tenant_id)
            },
            "attendance_date": attendance_date.isoformat(),
            "students": students,
            "total_students": len(students),
            "marked_count": len([s for s in students if s["attendance_status"] != "not_marked"]),
            "present_count": len([s for s in students if s["attendance_status"] == "PRESENT"]),
            "absent_count": len([s for s in students if s["attendance_status"] == "ABSENT"])
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get grade attendance: {str(e)}")

@router.post("/grade/{tenant_id}/{grade_level}/{section}/bulk-update-attendance")
async def bulk_update_grade_attendance(
    tenant_id: UUID,
    grade_level: int,
    section: str,
    request: BulkAttendanceUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('attendance'))  # staff (teacher/authority/super-admin) only
):
    """Bulk update attendance for students in a grade+section"""
    service = AttendanceService(db)
    # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
    tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id
    # Derive acting user from the authenticated principal; do not trust client-supplied marked_by
    acting_user_id = UUID(principal.user_id)

    try:
        attendance_records = []
        for update in request.attendance_updates:
            attendance_records.append({
                "user_id": update.user_id,
                "user_type": "STUDENT",
                "class_id": None,  # Grade-level attendance has no class_id
                "attendance_date": request.attendance_date,
                "status": update.status.upper(),
                "remarks": update.remarks or "",
                "marked_by": acting_user_id,
                "marked_by_type": _principal_user_type(principal).name,
                "attendance_type": "DAILY",
                "academic_year": "2025-26"
            })
        
        result = await service.bulk_mark_attendance(
            attendance_records=attendance_records,
            tenant_id=tenant_id
        )
        
        return {
            "message": f"Successfully updated attendance for {result['successful_records']} students",
            "grade_level": grade_level,
            "section": section,
            "attendance_date": request.attendance_date.isoformat(),
            "updated_students": result["successful_records"],
            "failed_updates": result["failed_records"],
            "total_processed": len(request.attendance_updates)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update grade attendance: {str(e)}")

# STAFF ATTENDANCE

@router.get("/staff/{tenant_id}/with-attendance/{attendance_date}")
async def get_staff_with_attendance(
    tenant_id: UUID,
    attendance_date: date,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all teachers and school authorities with their attendance status"""
    try:
        # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
        tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id
        teachers_sql = text("""
            SELECT 
                t.id as user_id,
                t.staff_id,
                t.first_name,
                t.last_name,
                'TEACHER' as user_type,
                t.position,
                a.id as attendance_id,
                a.status as attendance_status,
                a.attendance_time,
                a.remarks,
                a.is_excused
            FROM (SELECT * FROM members WHERE (profile->>'category') IS DISTINCT FROM 'student') t
            LEFT JOIN (
                SELECT DISTINCT ON (user_id) 
                    id, user_id, status, attendance_time, remarks, is_excused
                FROM attendances 
                WHERE attendance_date = :attendance_date 
                AND user_type = 'TEACHER'
                AND is_deleted = false
                ORDER BY user_id, attendance_time DESC
            ) a ON t.id = a.user_id
            WHERE t.tenant_id = :tenant_id
            AND t.is_deleted = false
            AND t.status = 'active'
        """)
        
        authorities_sql = text("""
            SELECT 
                sa.id as user_id,
                sa.authority_id as user_number,
                sa.first_name,
                sa.last_name,
                'SCHOOL_AUTHORITY' as user_type,
                sa.role as position,
                a.id as attendance_id,
                a.status as attendance_status,
                a.attendance_time,
                a.remarks,
                a.is_excused
            FROM school_authorities sa
            LEFT JOIN (
                SELECT DISTINCT ON (user_id) 
                    id, user_id, status, attendance_time, remarks, is_excused
                FROM attendances 
                WHERE attendance_date = :attendance_date 
                AND user_type = 'SCHOOL_AUTHORITY'
                AND is_deleted = false
                ORDER BY user_id, attendance_time DESC
            ) a ON sa.id = a.user_id
            WHERE sa.tenant_id = :tenant_id
            AND sa.is_deleted = false
            AND sa.status = 'active'
        """)
        
        params = {"tenant_id": tenant_id, "attendance_date": attendance_date}
        
        teachers_result = await db.execute(teachers_sql, params)
        authorities_result = await db.execute(authorities_sql, params)
        
        all_staff = []
        
        for row in teachers_result.fetchall():
            all_staff.append({
                "user_id": str(row[0]),
                "user_number": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "full_name": f"{row[2]} {row[3]}",
                "user_type": row[4],
                "position": row[5],
                "attendance_id": str(row[6]) if row[6] else None,
                "attendance_status": row[7] if row[7] else "not_marked",
                "attendance_time": row[8].isoformat() if row[8] else None,
                "remarks": row[9],
                "is_excused": row[10] if row[10] is not None else False
            })
        
        for row in authorities_result.fetchall():
            all_staff.append({
                "user_id": str(row[0]),
                "user_number": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "full_name": f"{row[2]} {row[3]}",
                "user_type": row[4],
                "position": row[5],
                "attendance_id": str(row[6]) if row[6] else None,
                "attendance_status": row[7] if row[7] else "not_marked",
                "attendance_time": row[8].isoformat() if row[8] else None,
                "remarks": row[9],
                "is_excused": row[10] if row[10] is not None else False
            })
        

        
        return {
            "attendance_date": attendance_date.isoformat(),
            "staff": all_staff,
            "total_staff": len(all_staff),
            "marked_count": len([s for s in all_staff if s["attendance_status"] != "not_marked"]),
            "present_count": len([s for s in all_staff if s["attendance_status"] == "PRESENT"]),
            "absent_count": len([s for s in all_staff if s["attendance_status"] == "ABSENT"]),
            "late_count": len([s for s in all_staff if s["attendance_status"] == "LATE"])
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get staff attendance: {str(e)}")

@router.post("/staff/{tenant_id}/bulk-update-attendance")
async def bulk_update_staff_attendance(
    tenant_id: UUID,
    request: BulkStaffAttendanceUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('attendance'))  # staff (teacher/authority/super-admin) only
):
    """Bulk update attendance for teachers, school authorities, and staff"""
    service = AttendanceService(db)
    # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
    tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id
    # Derive acting user from the authenticated principal; do not trust client-supplied marked_by
    acting_user_id = UUID(principal.user_id)

    try:
        attendance_records = []
        for update in request.attendance_updates:
            attendance_records.append({
                "user_id": update["user_id"],
                "user_type": update["user_type"].upper(),
                "attendance_date": request.attendance_date,
                "status": update["status"].upper(),
                "remarks": update.get("remarks", ""),
                "marked_by": acting_user_id,
                "marked_by_type": _principal_user_type(principal).name,
                "attendance_type": "DAILY",
                "academic_year": "2025-26"
            })
        
        result = await service.bulk_mark_attendance(
            attendance_records=attendance_records,
            tenant_id=tenant_id
        )
        
        return {
            "message": f"Successfully updated attendance for {result['successful_records']} staff members",
            "attendance_date": request.attendance_date.isoformat(),
            "updated_staff": result["successful_records"],
            "failed_updates": result["failed_records"],
            "total_processed": len(request.attendance_updates)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update staff attendance: {str(e)}")

# STUDENT ATTENDANCE HISTORY

@router.get("/students/{tenant_id}/filter")
async def get_students_for_filter(
    tenant_id: UUID,
    grade_level: int = None,
    section: str = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get students filtered by grade and section for attendance history selection"""
    try:
        # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
        tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id
        sql = text("""
            SELECT 
                s.id,
                s.staff_id,
                s.first_name,
                s.last_name,
                (s.profile->>'grade_level')::int,
                (s.profile->>'section')
            FROM (SELECT * FROM members WHERE (profile->>'category') = 'student') s
            WHERE s.tenant_id = :tenant_id
            AND s.is_deleted = false
            AND s.status = 'active'
            AND (:grade_level::INTEGER IS NULL OR (s.profile->>'grade_level')::int = :grade_level::INTEGER)
            AND (:section::VARCHAR IS NULL OR (s.profile->>'section') = :section::VARCHAR)
            ORDER BY (s.profile->>'grade_level')::int, (s.profile->>'section'), s.first_name, s.last_name
        """)
        
        result = await db.execute(sql, {
            "tenant_id": tenant_id, 
            "grade_level": grade_level,
            "section": section
        })
        
        students = []
        for row in result.fetchall():
            students.append({
                "id": str(row[0]),
                "student_id": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "full_name": f"{row[2]} {row[3]}",
                "grade_level": row[4],
                "section": row[5]
            })
        
        return {"students": students}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get students: {str(e)}")

# STAFF ATTENDANCE HISTORY

@router.get("/staff/{tenant_id}/filter")
async def get_staff_for_filter(
    tenant_id: UUID,
    user_type: str = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get staff (teachers and school authorities) for attendance history selection"""
    try:
        # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
        tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id
        staff = []
        
        # Get teachers if no filter or specifically TEACHER
        if not user_type or user_type == 'TEACHER':
            teachers_sql = text("""
                SELECT 
                    t.id,
                    t.staff_id,
                    t.first_name,
                    t.last_name,
                    'TEACHER' as user_type,
                    t.position
                FROM (SELECT * FROM members WHERE (profile->>'category') IS DISTINCT FROM 'student') t
                WHERE t.tenant_id = :tenant_id
                AND t.is_deleted = false
                AND t.status = 'active'
                ORDER BY t.first_name, t.last_name
            """)
            
            teachers_result = await db.execute(teachers_sql, {"tenant_id": tenant_id})
            for row in teachers_result.fetchall():
                staff.append({
                    "id": str(row[0]),
                    "staff_id": row[1],
                    "first_name": row[2],
                    "last_name": row[3],
                    "full_name": f"{row[2]} {row[3]}",
                    "user_type": row[4],
                    "position": row[5]
                })
        
        # Get school authorities if no filter or specifically SCHOOL_AUTHORITY
        if not user_type or user_type == 'SCHOOL_AUTHORITY':
            authorities_sql = text("""
                SELECT 
                    sa.id,
                    sa.authority_id,
                    sa.first_name,
                    sa.last_name,
                    'SCHOOL_AUTHORITY' as user_type,
                    sa.role as position
                FROM school_authorities sa
                WHERE sa.tenant_id = :tenant_id
                AND sa.is_deleted = false
                AND sa.status = 'active'
                ORDER BY sa.first_name, sa.last_name
            """)
            
            authorities_result = await db.execute(authorities_sql, {"tenant_id": tenant_id})
            for row in authorities_result.fetchall():
                staff.append({
                    "id": str(row[0]),
                    "staff_id": row[1],
                    "first_name": row[2],
                    "last_name": row[3],
                    "full_name": f"{row[2]} {row[3]}",
                    "user_type": row[4],
                    "position": row[5]
                })
        
        return {"staff": staff}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get staff: {str(e)}")

@router.get("/staff/{tenant_id}/{staff_id}/history")
async def get_staff_attendance_history(
    tenant_id: UUID,
    staff_id: UUID,
    start_date: date = None,
    end_date: date = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get attendance history for a specific staff member (teacher or school authority)"""
    try:
        # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
        tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id

        # Default to last 30 days if no dates provided
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        sql = text("""
            SELECT
                a.attendance_date,
                a.status,
                a.attendance_time,
                a.remarks,
                a.is_excused,
                a.user_type
            FROM attendances a
            WHERE a.user_id = :staff_id
            AND a.user_type IN ('TEACHER', 'SCHOOL_AUTHORITY')
            AND a.attendance_date BETWEEN :start_date AND :end_date
            AND a.is_deleted = false
            AND (:tenant_id::uuid IS NULL OR a.tenant_id = :tenant_id::uuid)
            ORDER BY a.attendance_date DESC
        """)

        result = await db.execute(sql, {
            "staff_id": staff_id,
            "start_date": start_date,
            "end_date": end_date,
            "tenant_id": str(tenant_id) if tenant_id else None
        })
        
        # Group by date
        history_by_date = {}
        for row in result.fetchall():
            date_str = row[0].isoformat()
            if date_str not in history_by_date:
                history_by_date[date_str] = {
                    "date": date_str,
                    "attendance": None
                }
            
            history_by_date[date_str]["attendance"] = {
                "status": row[1],
                "attendance_time": row[2].isoformat() if row[2] else None,
                "remarks": row[3],
                "is_excused": row[4],
                "user_type": row[5]
            }
        
        return {
            "staff_id": str(staff_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "attendance_history": list(history_by_date.values())
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get staff attendance history: {str(e)}")

@router.get("/student/{tenant_id}/{student_id}/history")
async def get_student_attendance_history_singular(
    tenant_id: UUID,
    student_id: UUID,
    start_date: date = None,
    end_date: date = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get attendance history for a specific student (both grade and class level) - singular endpoint"""
    try:
        # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
        tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id

        # Default to last 30 days if no dates provided
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        sql = text("""
            SELECT
                a.attendance_date,
                a.status,
                a.attendance_type,
                a.period_number,
                a.subject_name,
                a.class_id,
                a.remarks,
                a.is_excused,
                c.class_name
            FROM attendances a
            LEFT JOIN classes c ON a.class_id = c.id
            WHERE a.user_id = :student_id
            AND a.user_type = 'STUDENT'
            AND a.attendance_date BETWEEN :start_date AND :end_date
            AND a.is_deleted = false
            AND (:tenant_id::uuid IS NULL OR a.tenant_id = :tenant_id::uuid)
            ORDER BY a.attendance_date DESC, a.period_number ASC
        """)

        result = await db.execute(sql, {
            "student_id": student_id,
            "start_date": start_date,
            "end_date": end_date,
            "tenant_id": str(tenant_id) if tenant_id else None
        })
        
        # Group by date
        history_by_date = {}
        for row in result.fetchall():
            date_str = row[0].isoformat()
            if date_str not in history_by_date:
                history_by_date[date_str] = {
                    "date": date_str,
                    "grade_attendance": None,
                    "class_attendance": []
                }
            
            attendance_record = {
                "status": row[1],
                "period_number": row[3],
                "subject_name": row[4],
                "class_id": str(row[5]) if row[5] else None,
                "class_name": row[8],
                "remarks": row[6],
                "is_excused": row[7]
            }
            
            # Grade level attendance: class_id is NULL
            if row[5] is None:  # No class_id means grade-level attendance
                history_by_date[date_str]["grade_attendance"] = attendance_record
            else:  # Has class_id means class-level attendance
                history_by_date[date_str]["class_attendance"].append(attendance_record)
        
        return {
            "student_id": str(student_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "attendance_history": list(history_by_date.values())
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get attendance history: {str(e)}")

@router.get("/students/{tenant_id}/{student_id}/history")
async def get_student_attendance_history(
    tenant_id: UUID,
    student_id: UUID,
    start_date: date = None,
    end_date: date = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get attendance history for a specific student (both grade and class level)"""
    try:
        # Non-super-admin: ignore client-supplied tenant_id and scope to the principal's tenant
        tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id

        # Default to last 30 days if no dates provided
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        sql = text("""
            SELECT
                a.attendance_date,
                a.status,
                a.attendance_type,
                a.period_number,
                a.subject_name,
                a.class_id,
                a.remarks,
                a.is_excused,
                c.class_name
            FROM attendances a
            LEFT JOIN classes c ON a.class_id = c.id
            WHERE a.user_id = :student_id
            AND a.user_type = 'STUDENT'
            AND a.attendance_date BETWEEN :start_date AND :end_date
            AND a.is_deleted = false
            AND (:tenant_id::uuid IS NULL OR a.tenant_id = :tenant_id::uuid)
            ORDER BY a.attendance_date DESC, a.period_number ASC
        """)

        result = await db.execute(sql, {
            "student_id": student_id,
            "start_date": start_date,
            "end_date": end_date,
            "tenant_id": str(tenant_id) if tenant_id else None
        })
        
        # Group by date
        history_by_date = {}
        for row in result.fetchall():
            date_str = row[0].isoformat()
            if date_str not in history_by_date:
                history_by_date[date_str] = {
                    "date": date_str,
                    "grade_attendance": None,
                    "class_attendance": []
                }
            
            attendance_record = {
                "status": row[1],
                "period_number": row[3],
                "subject_name": row[4],
                "class_id": str(row[5]) if row[5] else None,
                "class_name": row[8],
                "remarks": row[6],
                "is_excused": row[7]
            }
            
            # Grade level attendance: class_id is NULL
            if row[5] is None:  # No class_id means grade-level attendance
                history_by_date[date_str]["grade_attendance"] = attendance_record
            else:  # Has class_id means class-level attendance
                history_by_date[date_str]["class_attendance"].append(attendance_record)
        
        return {
            "student_id": str(student_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "attendance_history": list(history_by_date.values())
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get attendance history: {str(e)}")

@router.get("/{attendance_id}")
async def get_attendance_record(
    attendance_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get specific attendance record"""
    service = AttendanceService(db)
    # Scope the lookup to the principal's tenant (None for super-admin -> no scoping)
    attendance = await service.get(
        attendance_id,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id)
    )

    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    return {
        "id": str(attendance.id),
        "tenant_id": str(attendance.tenant_id),
        "user_id": str(attendance.user_id),
        "user_type": attendance.user_type.value,
        "class_id": str(attendance.class_id) if attendance.class_id else None,
        "marked_by": str(attendance.marked_by),
        "marked_by_type": attendance.marked_by_type.value,
        "attendance_date": attendance.attendance_date.isoformat(),
        "attendance_time": attendance.attendance_time.isoformat(),
        "attendance_type": attendance.attendance_type.value,
        "attendance_mode": attendance.attendance_mode.value,
        "status": attendance.status.value,
        "check_in_time": attendance.check_in_time.isoformat() if attendance.check_in_time else None,
        "check_out_time": attendance.check_out_time.isoformat() if attendance.check_out_time else None,
        "expected_check_in": attendance.expected_check_in.isoformat() if attendance.expected_check_in else None,
        "expected_check_out": attendance.expected_check_out.isoformat() if attendance.expected_check_out else None,
        "period_number": attendance.period_number,
        "subject_name": attendance.subject_name,
        "location": attendance.location,
        "remarks": attendance.remarks,
        "reason_for_absence": attendance.reason_for_absence,
        "is_excused": attendance.is_excused,
        "approved_by": str(attendance.approved_by) if attendance.approved_by else None,
        "approval_date": attendance.approval_date.isoformat() if attendance.approval_date else None,
        "approval_remarks": attendance.approval_remarks,
        "academic_year": attendance.academic_year,
        "term": attendance.term,
        "latitude": attendance.latitude,
        "longitude": attendance.longitude,
        "created_at": attendance.created_at.isoformat(),
        "updated_at": attendance.updated_at.isoformat()
    }
