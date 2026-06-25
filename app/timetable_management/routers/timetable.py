# app/routers/school_authority/timetable.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from ...core.database import get_db
from ...timetable_management.services.timetable_service import TimetableService
from ...timetable_management.models.timetable import DayOfWeek, TimetableStatus, PeriodType
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_authority, assert_same_tenant
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal

import logging
logger = logging.getLogger(__name__)

# Pydantic Models
class MasterTimetableCreate(BaseModel):
    tenant_id: UUID
    created_by: UUID
    timetable_name: str
    description: Optional[str] = None
    academic_year: str
    term: Optional[str] = None
    effective_from: date
    effective_until: Optional[date] = None
    total_periods_per_day: int = 8
    school_start_time: str  # "09:00:00"
    school_end_time: str    # "16:00:00"
    period_duration: int = 45
    break_duration: int = 15
    lunch_duration: int = 60
    working_days: List[str] = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    auto_generate_periods: bool = True

class ClassTimetableCreate(BaseModel):
    tenant_id: UUID
    class_id: UUID
    master_timetable_id: UUID
    academic_year: str
    term: Optional[str] = None
    class_name: Optional[str] = None
    grade_level: Optional[str] = None
    created_by: UUID

class TeacherTimetableCreate(BaseModel):
    tenant_id: UUID
    teacher_id: UUID
    master_timetable_id: UUID
    academic_year: str
    term: Optional[str] = None
    teacher_name: Optional[str] = None
    max_periods_per_day: int = 8
    min_periods_per_day: int = 1
    preferred_periods: Optional[List[int]] = None
    preferred_days: Optional[List[str]] = None
    subjects: Optional[List[str]] = None

class BulkScheduleCreate(BaseModel):
    tenant_id: UUID
    schedule_entries: List[dict]

class BulkScheduleUpdate(BaseModel):
    updates: List[dict]

# ROUTER CONFIGURATION
router = APIRouter(
    prefix="/api/v1/school_authority/timetable", 
    tags=["School Authority - Timetable Management"]
)

# MASTER TIMETABLE ENDPOINTS (School Authority Only)

@router.post("/master", response_model=dict)
async def create_master_timetable(
    timetable_data: MasterTimetableCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('timetable'))  # School Authority / super-admin only
):
    """Create a new master timetable with auto-generated periods"""
    service = TimetableService(db)

    try:
        payload = timetable_data.model_dump()
        # Enforce tenant scoping: non-super-admins cannot create for other tenants
        if not principal.is_super_admin:
            payload["tenant_id"] = principal.tenant_id
        # The acting/creating user is always the authenticated principal
        payload["created_by"] = principal.user_id
        master_timetable = await service.create_master_timetable(payload)
        
        return {
            "id": str(master_timetable.id),
            "message": "Master timetable created successfully",
            "timetable_name": master_timetable.timetable_name,
            "academic_year": master_timetable.academic_year,
            "total_periods": master_timetable.total_periods_per_day,
            "effective_from": master_timetable.effective_from.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/master/{tenant_id}", response_model=List[dict])
async def get_master_timetables(
    tenant_id: UUID,
    academic_year: Optional[str] = Query(None),
    status: Optional[TimetableStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all master timetables for a tenant"""
    service = TimetableService(db)

    # Non-super-admins are locked to their own tenant regardless of path value
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    try:
        filters = {"tenant_id": effective_tenant, "is_deleted": False}
        if academic_year:
            filters["academic_year"] = academic_year
        if status:
            filters["status"] = status
        
        timetables = await service.get_multi(**filters)
        
        # Ensure we always return a list, even if empty
        if not timetables:
            return []
        
        return [
            {
                "id": str(tt.id),
                "timetable_name": tt.timetable_name,
                "description": tt.description,
                "academic_year": tt.academic_year,
                "term": tt.term,
                "effective_from": tt.effective_from.isoformat() if tt.effective_from else None,
                "effective_until": tt.effective_until.isoformat() if tt.effective_until else None,
                "school_start_time": tt.school_start_time.isoformat() if tt.school_start_time else None,
                "school_end_time": tt.school_end_time.isoformat() if tt.school_end_time else None,
                "total_periods_per_day": tt.total_periods_per_day,
                "status": tt.status.value if tt.status else "draft",
                "is_default": tt.is_default,
                "working_days": tt.working_days,
                "total_classes": tt.total_classes,
                "total_teachers": tt.total_teachers,
                "total_schedule_entries": tt.total_schedule_entries,
                "created_at": tt.created_at.isoformat()
            }
            for tt in timetables
        ]
    except Exception as e:
        # Log the error for debugging
        logger.error(f"Error in get_master_timetables: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# CLASS TIMETABLE ENDPOINTS

@router.post("/class", response_model=dict)
async def create_class_timetable(
    class_timetable_data: ClassTimetableCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('timetable'))  # School Authority / super-admin only
):
    """Create timetable for a class (School Authority Only)"""
    service = TimetableService(db)

    try:
        payload = class_timetable_data.model_dump()
        if not principal.is_super_admin:
            payload["tenant_id"] = principal.tenant_id
        payload["created_by"] = principal.user_id
        class_timetable = await service.create_class_timetable(payload)
        
        return {
            "id": str(class_timetable.id),
            "message": "Class timetable created successfully",
            "class_id": str(class_timetable.class_id),
            "class_name": class_timetable.class_name,
            "academic_year": class_timetable.academic_year
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/class/{class_id}/schedule")
async def get_class_schedule(
    class_id: UUID,
    academic_year: str,
    requester_type: str = Query("school_authority", regex="^(school_authority|teacher|student)$"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get weekly schedule for a class (Accessible by School Authority, Teachers, Students)"""
    service = TimetableService(db)
    
    try:
        weekly_schedule = await service.get_class_weekly_schedule(class_id, academic_year)
        
        return {
            "class_id": str(class_id),
            "academic_year": academic_year,
            "weekly_schedule": weekly_schedule,
            "total_periods": sum(len(day_schedule) for day_schedule in weekly_schedule.values()),
            "working_days": [day for day, schedule in weekly_schedule.items() if schedule],
            "access_type": "read_only" if requester_type in ["teacher", "student"] else "full_access"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# TEACHER TIMETABLE ENDPOINTS

@router.post("/teacher", response_model=dict)
async def create_teacher_timetable(
    teacher_timetable_data: TeacherTimetableCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('timetable'))  # School Authority / super-admin only
):
    """Create timetable for a teacher (School Authority Only)"""
    service = TimetableService(db)

    try:
        payload = teacher_timetable_data.model_dump()
        if not principal.is_super_admin:
            payload["tenant_id"] = principal.tenant_id
        teacher_timetable = await service.create_teacher_timetable(payload)
        
        return {
            "id": str(teacher_timetable.id),
            "message": "Teacher timetable created successfully",
            "teacher_id": str(teacher_timetable.teacher_id),
            "teacher_name": teacher_timetable.teacher_name,
            "academic_year": teacher_timetable.academic_year
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/teacher/{teacher_id}/schedule")
async def get_teacher_schedule(
    teacher_id: UUID,
    academic_year: str,
    requester_type: str = Query("school_authority", regex="^(school_authority|teacher)$"),
    requester_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get weekly schedule for a teacher (Accessible by School Authority and the teacher themselves)"""
    service = TimetableService(db)

    # Permission check: a non-privileged teacher can only view their own schedule.
    # Derive the acting identity from the authenticated principal, not client input.
    if requester_type == "teacher" and not (principal.is_super_admin or principal.is_staff):
        if str(principal.user_id) != str(teacher_id):
            raise HTTPException(status_code=403, detail="Teachers can only view their own timetable")
    
    try:
        weekly_schedule = await service.get_teacher_weekly_schedule(teacher_id, academic_year)
        
        return {
            "teacher_id": str(teacher_id),
            "academic_year": academic_year,
            "weekly_schedule": weekly_schedule,
            "total_periods": sum(len(day_schedule) for day_schedule in weekly_schedule.values()),
            "working_days": [day for day, schedule in weekly_schedule.items() if schedule],
            "access_type": "read_only" if requester_type == "teacher" else "full_access"
        }
    except Exception as e:
        logger.error(f"Error in get_teacher_schedule: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# BULK OPERATIONS (School Authority Only)

@router.post("/bulk/schedule", response_model=dict)
async def bulk_create_schedule_entries(
    import_data: BulkScheduleCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('timetable'))  # School Authority / super-admin only
):
    """Bulk create schedule entries (School Authority Only)"""
    service = TimetableService(db)

    # Override client-supplied tenant_id with the principal's tenant (non-super-admin)
    effective_tenant = import_data.tenant_id if principal.is_super_admin else principal.tenant_id

    result = await service.bulk_create_schedule_entries(
        schedule_entries=import_data.schedule_entries,
        tenant_id=effective_tenant
    )
    
    return {
        "message": f"Bulk schedule creation completed. {result['successful_records']} entries created successfully",
        **result
    }

@router.put("/bulk/schedule", response_model=dict)
async def bulk_update_schedule_entries(
    update_data: BulkScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('timetable'))  # School Authority / super-admin only
):
    """Bulk update schedule entries (School Authority Only)"""
    service = TimetableService(db)
    
    result = await service.bulk_update_schedule_entries(
        update_data.updates,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id),
    )
    
    return {
        "message": f"Bulk update completed. {result['updated_records']} entries updated successfully",
        **result
    }

@router.delete("/bulk/schedule", response_model=dict)
async def bulk_delete_schedule_entries(
    entry_ids: List[UUID],
    hard_delete: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('timetable'))  # School Authority / super-admin only
):
    """Bulk delete schedule entries (School Authority Only)"""
    service = TimetableService(db)

    # Hard delete is a destructive, irreversible operation: restrict to super-admins
    if hard_delete and not principal.is_super_admin:
        raise HTTPException(status_code=403, detail="Hard delete requires super-admin privileges")

    result = await service.bulk_delete_schedule_entries(
        entry_ids, hard_delete,
        tenant_id=(None if principal.is_super_admin else principal.tenant_id),
    )
    
    return {
        "message": f"Bulk delete completed. {result['deleted_records']} entries {result['delete_type']} deleted",
        **result
    }

# ANALYTICS AND REPORTING

@router.get("/analytics/{tenant_id}")
async def get_timetable_analytics(
    tenant_id: UUID,
    academic_year: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get comprehensive timetable analytics (School Authority Only)"""
    service = TimetableService(db)

    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    try:
        analytics = await service.get_timetable_analytics(effective_tenant, academic_year)
        
        return {
            "message": "Timetable analytics retrieved successfully",
            **analytics
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# CONFLICT MANAGEMENT (School Authority Only)

@router.get("/conflicts/current/{tenant_id}")
async def get_current_timetable_conflicts(
    tenant_id: UUID,
    academic_year: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all current conflicts in existing timetables"""
    # Non-super-admins are locked to their own tenant regardless of path value
    tenant_id = tenant_id if principal.is_super_admin else principal.tenant_id
    try:
        conflicts = []
        
        # 1. Find teacher double-booking conflicts
        teacher_conflicts_sql = text("""
            SELECT 
                se1.teacher_id,
                se1.teacher_name,
                se1.day_of_week,
                se1.start_time,
                se1.end_time,
                c1.class_name as class1_name,
                c1.grade_level as class1_grade,
                c1.section as class1_section,
                c2.class_name as class2_name,
                c2.grade_level as class2_grade,
                c2.section as class2_section,
                se1.subject_name as subject1,
                se2.subject_name as subject2,
                se1.room_number as room1,
                se2.room_number as room2
            FROM schedule_entries se1
            JOIN schedule_entries se2 ON se1.teacher_id = se2.teacher_id
                AND se1.day_of_week = se2.day_of_week
                AND se1.start_time < se2.end_time
                AND se1.end_time > se2.start_time
                AND se1.id != se2.id
            JOIN class_timetables ct1 ON se1.class_timetable_id = ct1.id
            JOIN class_timetables ct2 ON se2.class_timetable_id = ct2.id
            JOIN classes c1 ON ct1.class_id = c1.id
            JOIN classes c2 ON ct2.class_id = c2.id
            WHERE ct1.tenant_id = :tenant_id
            AND ct1.academic_year = :academic_year
            AND se1.is_deleted = false
            AND se2.is_deleted = false
        """)
        
        result = await db.execute(teacher_conflicts_sql, {
            "tenant_id": tenant_id,
            "academic_year": academic_year
        })
        
        for row in result.fetchall():
            conflicts.append({
                "type": "teacher_double_booking",
                "severity": "high",
                "teacher_id": str(row[0]),
                "teacher_name": row[1],
                "day": row[2].lower(),
                "time": f"{row[3].strftime('%H:%M')}-{row[4].strftime('%H:%M')}",
                "class1": f"Grade {row[6]} {row[5]} ({row[7]})",
                "class2": f"Grade {row[9]} {row[8]} ({row[10]})",
                "subject1": row[11],
                "subject2": row[12],
                "room1": row[13],
                "room2": row[14],
                "message": f"Teacher {row[1]} is double-booked on {row[2].lower()} {row[3].strftime('%H:%M')}-{row[4].strftime('%H:%M')}"
            })
        
        # 2. Find room double-booking conflicts
        room_conflicts_sql = text("""
            SELECT 
                se1.room_number,
                se1.day_of_week,
                se1.start_time,
                se1.end_time,
                c1.class_name as class1_name,
                c1.grade_level as class1_grade,
                c1.section as class1_section,
                c2.class_name as class2_name,
                c2.grade_level as class2_grade,
                c2.section as class2_section,
                se1.subject_name as subject1,
                se2.subject_name as subject2,
                se1.teacher_name as teacher1,
                se2.teacher_name as teacher2
            FROM schedule_entries se1
            JOIN schedule_entries se2 ON se1.room_number = se2.room_number
                AND se1.day_of_week = se2.day_of_week
                AND se1.start_time < se2.end_time
                AND se1.end_time > se2.start_time
                AND se1.id != se2.id
            JOIN class_timetables ct1 ON se1.class_timetable_id = ct1.id
            JOIN class_timetables ct2 ON se2.class_timetable_id = ct2.id
            JOIN classes c1 ON ct1.class_id = c1.id
            JOIN classes c2 ON ct2.class_id = c2.id
            WHERE ct1.tenant_id = :tenant_id
            AND ct1.academic_year = :academic_year
            AND se1.room_number IS NOT NULL
            AND se1.is_deleted = false
            AND se2.is_deleted = false
        """)
        
        result = await db.execute(room_conflicts_sql, {
            "tenant_id": tenant_id,
            "academic_year": academic_year
        })
        
        for row in result.fetchall():
            conflicts.append({
                "type": "room_double_booking",
                "severity": "medium",
                "room_number": row[0],
                "day": row[1].lower(),
                "time": f"{row[2].strftime('%H:%M')}-{row[3].strftime('%H:%M')}",
                "class1": f"Grade {row[5]} {row[4]} ({row[6]})",
                "class2": f"Grade {row[8]} {row[7]} ({row[9]})",
                "subject1": row[10],
                "subject2": row[11],
                "teacher1": row[12],
                "teacher2": row[13],
                "message": f"Room {row[0]} is double-booked on {row[1].lower()} {row[2].strftime('%H:%M')}-{row[3].strftime('%H:%M')}"
            })
        
        return {
            "tenant_id": str(tenant_id),
            "academic_year": academic_year,
            "total_conflicts": len(conflicts),
            "conflicts_by_type": {
                "teacher_double_booking": len([c for c in conflicts if c["type"] == "teacher_double_booking"]),
                "room_double_booking": len([c for c in conflicts if c["type"] == "room_double_booking"])
            },
            "conflicts": conflicts
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/conflicts/{tenant_id}", response_model=List[dict])
async def get_timetable_conflicts(
    tenant_id: UUID,
    unresolved_only: bool = Query(True),
    severity: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get timetable conflicts (School Authority Only)"""
    service = TimetableService(db)

    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    try:
        # Use raw SQL for better performance
        conflicts_sql = text("""
            SELECT 
                tc.id,
                tc.conflict_type,
                tc.severity,
                tc.title,
                tc.description,
                tc.day_of_week,
                tc.period_number,
                tc.room_number,
                tc.is_resolved,
                tc.resolution_notes,
                tc.created_at,
                tc.resolved_date
            FROM timetable_conflicts tc
            WHERE tc.tenant_id = :tenant_id
            AND tc.is_deleted = false
            {}
            {}
            ORDER BY tc.severity DESC, tc.created_at DESC
        """.format(
            "AND tc.is_resolved = false" if unresolved_only else "",
            f"AND tc.severity = '{severity}'" if severity else ""
        ))
        
        result = await db.execute(conflicts_sql, {"tenant_id": effective_tenant})
        conflicts = result.fetchall()
        
        return [
            {
                "id": str(conflict[0]),
                "conflict_type": conflict[1],
                "severity": conflict[2],
                "title": conflict[3],
                "description": conflict[4],
                "day_of_week": conflict[5],
                "period_number": conflict[6],
                "room_number": conflict[7],
                "is_resolved": conflict[8],
                "resolution_notes": conflict[9],
                "created_at": conflict[10].isoformat(),
                "resolved_date": conflict[11].isoformat() if conflict[11] else None
            }
            for conflict in conflicts
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# TEMPLATE SYSTEM (Future Enhancement)

@router.get("/templates/{tenant_id}")
async def get_timetable_templates(
    tenant_id: UUID,
    template_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get available timetable templates (School Authority Only)"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    # Implementation for timetable templates
    return {
        "message": "Timetable templates feature coming soon",
        "available_types": ["class", "teacher", "grade_level"],
        "tenant_id": str(effective_tenant)
    }

# SIMPLIFIED CLASS TIMETABLE MANAGEMENT

class PeriodEntry(BaseModel):
    period_number: int
    start_time: str  # "09:00"
    end_time: str    # "09:45"
    subject_name: str
    teacher_id: UUID
    teacher_name: Optional[str] = None
    room_number: Optional[str] = None

class ClassTimetableData(BaseModel):
    tenant_id: UUID
    class_id: UUID
    academic_year: str
    term: Optional[str] = None
    created_by: UUID
    schedule: Dict[str, List[PeriodEntry]]  # {"monday": [periods], "tuesday": [periods]}

@router.get("/classes/{tenant_id}")
async def get_classes_list(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get list of all classes for timetable creation"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    try:
        sql = text("""
            SELECT id, class_name, grade_level, section
            FROM classes
            WHERE tenant_id = :tenant_id AND is_deleted = false
            ORDER BY grade_level, section
        """)

        result = await db.execute(sql, {"tenant_id": effective_tenant})
        classes = result.fetchall()
        
        return [
            {
                "id": str(cls[0]),
                "class_name": cls[1],
                "grade_level": cls[2],
                "section": cls[3]
            }
            for cls in classes
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/teachers/{tenant_id}")
async def get_teachers_list(
    tenant_id: UUID,
    class_id: UUID = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get list of teachers - all teachers or only those assigned to a specific class"""
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    try:
        if class_id:
            # Get only teachers assigned to this specific class
            sql = text("""
                SELECT t.id, t.first_name, t.last_name
                FROM teachers t
                JOIN classes c ON c.tenant_id = t.tenant_id
                WHERE t.tenant_id = :tenant_id 
                AND t.is_deleted = false
                AND c.id = :class_id
                AND c.assigned_teachers IS NOT NULL
                AND JSON_EXTRACT_PATH_TEXT(c.assigned_teachers, 'teacher_ids') LIKE '%' || t.id::text || '%'
                ORDER BY t.first_name, t.last_name
            """)
            
            result = await db.execute(sql, {
                "tenant_id": effective_tenant,
                "class_id": class_id
            })
        else:
            # Get all teachers
            sql = text("""
                SELECT id, first_name, last_name
                FROM teachers 
                WHERE tenant_id = :tenant_id AND is_deleted = false
                ORDER BY first_name, last_name
            """)
            
            result = await db.execute(sql, {"tenant_id": effective_tenant})

        teachers = result.fetchall()
        
        return [
            {
                "id": str(teacher[0]),
                "name": f"{teacher[1]} {teacher[2]}",
                "subjects": []
            }
            for teacher in teachers
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/class/{class_id}/timetable")
async def get_class_timetable(
    class_id: UUID,
    academic_year: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get existing timetable for a class"""
    try:
        # Scope by tenant for non-super-admins so cross-tenant class ids return nothing
        tenant_filter = "" if principal.is_super_admin else "AND ct.tenant_id = :tenant_id"
        sql = text(f"""
            SELECT
                se.day_of_week,
                se.period_number,
                se.start_time,
                se.end_time,
                se.subject_name,
                se.teacher_id,
                se.teacher_name,
                se.room_number
            FROM schedule_entries se
            JOIN class_timetables ct ON se.class_timetable_id = ct.id
            WHERE ct.class_id = :class_id
            AND ct.academic_year = :academic_year
            {tenant_filter}
            AND se.is_deleted = false
            ORDER BY se.day_of_week, se.period_number
        """)

        params = {"class_id": class_id, "academic_year": academic_year}
        if not principal.is_super_admin:
            params["tenant_id"] = principal.tenant_id
        result = await db.execute(sql, params)
        
        schedule = {
            "monday": [],
            "tuesday": [],
            "wednesday": [],
            "thursday": [],
            "friday": [],
            "saturday": []
        }
        
        for row in result.fetchall():
            day = row[0].lower()  # Convert MONDAY to monday
            period = {
                "period_number": row[1],
                "start_time": row[2].strftime("%H:%M") if row[2] else None,
                "end_time": row[3].strftime("%H:%M") if row[3] else None,
                "subject_name": row[4],
                "teacher_id": str(row[5]) if row[5] else None,
                "teacher_name": row[6],
                "room_number": row[7]
            }
            if day in schedule:  # Only add if day exists in our schedule dict
                schedule[day].append(period)
        
        return {
            "class_id": str(class_id),
            "academic_year": academic_year,
            "schedule": schedule
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/class/timetable/validate")
async def validate_class_timetable(
    timetable_data: ClassTimetableData,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Validate class timetable for conflicts before saving"""
    # Override client-supplied tenant with the principal's tenant (non-super-admin)
    if not principal.is_super_admin:
        timetable_data.tenant_id = principal.tenant_id
    try:
        conflicts = []
        
        # Check for conflicts in the submitted timetable
        for day, periods in timetable_data.schedule.items():
            for i, period in enumerate(periods):
                # 1. Check teacher double-booking
                teacher_conflict_sql = text("""
                    SELECT c.class_name, c.grade_level, c.section
                    FROM schedule_entries se
                    JOIN class_timetables ct ON se.class_timetable_id = ct.id
                    JOIN classes c ON ct.class_id = c.id
                    WHERE se.teacher_id = :teacher_id
                    AND se.day_of_week = :day_of_week
                    AND se.start_time < :end_time
                    AND se.end_time > :start_time
                    AND ct.class_id != :class_id
                    AND se.is_deleted = false
                """)
                
                from datetime import time
                start_time_obj = time(*map(int, period.start_time.split(':')))
                end_time_obj = time(*map(int, period.end_time.split(':')))
                
                result = await db.execute(teacher_conflict_sql, {
                    "teacher_id": period.teacher_id,
                    "day_of_week": day.upper(),
                    "start_time": start_time_obj,
                    "end_time": end_time_obj,
                    "class_id": timetable_data.class_id
                })
                
                teacher_conflicts = result.fetchall()
                for conflict in teacher_conflicts:
                    conflicts.append({
                        "type": "teacher_double_booking",
                        "severity": "high",
                        "day": day,
                        "period": period.period_number,
                        "time": f"{period.start_time}-{period.end_time}",
                        "message": f"Teacher {period.teacher_name} is already assigned to {conflict[1]} {conflict[0]} ({conflict[2]}) at this time"
                    })
                
                # 2. Check room double-booking
                if period.room_number:
                    room_conflict_sql = text("""
                        SELECT c.class_name, c.grade_level, c.section
                        FROM schedule_entries se
                        JOIN class_timetables ct ON se.class_timetable_id = ct.id
                        JOIN classes c ON ct.class_id = c.id
                        WHERE se.room_number = :room_number
                        AND se.day_of_week = :day_of_week
                        AND se.start_time < :end_time
                        AND se.end_time > :start_time
                        AND ct.class_id != :class_id
                        AND se.is_deleted = false
                    """)
                    
                    result = await db.execute(room_conflict_sql, {
                        "room_number": period.room_number,
                        "day_of_week": day.upper(),
                        "start_time": start_time_obj,
                        "end_time": end_time_obj,
                        "class_id": timetable_data.class_id
                    })
                    
                    room_conflicts = result.fetchall()
                    for conflict in room_conflicts:
                        conflicts.append({
                            "type": "room_double_booking",
                            "severity": "medium",
                            "day": day,
                            "period": period.period_number,
                            "time": f"{period.start_time}-{period.end_time}",
                            "message": f"Room {period.room_number} is already booked by {conflict[1]} {conflict[0]} ({conflict[2]}) at this time"
                        })
                
                # 3. Check time overlap within same day for this class
                for j, other_period in enumerate(periods):
                    if i != j:
                        other_start = time(*map(int, other_period.start_time.split(':')))
                        other_end = time(*map(int, other_period.end_time.split(':')))
                        
                        if (start_time_obj < other_end and end_time_obj > other_start):
                            conflicts.append({
                                "type": "time_overlap",
                                "severity": "critical",
                                "day": day,
                                "period": period.period_number,
                                "time": f"{period.start_time}-{period.end_time}",
                                "message": f"Period {period.period_number} ({period.start_time}-{period.end_time}) overlaps with Period {other_period.period_number} ({other_period.start_time}-{other_period.end_time})"
                            })
        
        return {
            "has_conflicts": len(conflicts) > 0,
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
            "class_id": str(timetable_data.class_id)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/class/timetable")
async def save_class_timetable(
    timetable_data: ClassTimetableData,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('timetable'))  # School Authority / super-admin only
):
    """Save complete class timetable"""
    # Enforce tenant scoping and trusted actor identity from the principal
    if not principal.is_super_admin:
        timetable_data.tenant_id = principal.tenant_id
    timetable_data.created_by = principal.user_id
    try:
        # Check if class timetable exists
        check_sql = text("""
            SELECT id FROM class_timetables 
            WHERE class_id = :class_id AND academic_year = :academic_year 
            AND (term = :term OR (term IS NULL AND :term IS NULL))
        """)
        
        result = await db.execute(check_sql, {
            "class_id": timetable_data.class_id,
            "academic_year": timetable_data.academic_year,
            "term": timetable_data.term
        })
        
        existing = result.fetchone()
        
        if existing:
            class_timetable_id = existing[0]
            # Update existing
            update_sql = text("""
                UPDATE class_timetables 
                SET updated_at = NOW(), created_by = :created_by
                WHERE id = :id
            """)
            await db.execute(update_sql, {
                "id": class_timetable_id,
                "created_by": timetable_data.created_by
            })
        else:
            # Create new
            insert_sql = text("""
                INSERT INTO class_timetables (id, tenant_id, class_id, academic_year, term, created_by, created_at, updated_at, is_deleted)
                VALUES (gen_random_uuid(), :tenant_id, :class_id, :academic_year, :term, :created_by, NOW(), NOW(), false)
                RETURNING id
            """)
            
            result = await db.execute(insert_sql, {
                "tenant_id": timetable_data.tenant_id,
                "class_id": timetable_data.class_id,
                "academic_year": timetable_data.academic_year,
                "term": timetable_data.term,
                "created_by": timetable_data.created_by
            })
            
            class_timetable_id = result.fetchone()[0]
        
        # Delete existing schedule entries
        delete_sql = text("""
            DELETE FROM schedule_entries 
            WHERE class_timetable_id = :class_timetable_id
        """)
        await db.execute(delete_sql, {"class_timetable_id": class_timetable_id})
        
        # Insert new schedule entries
        for day, periods in timetable_data.schedule.items():
            for period in periods:
                from datetime import time
                
                # Convert time strings to time objects
                start_time_obj = time(*map(int, period.start_time.split(':')))
                end_time_obj = time(*map(int, period.end_time.split(':')))
                
                insert_sql = text("""
                    INSERT INTO schedule_entries (
                        id, tenant_id, class_timetable_id, day_of_week, period_number,
                        start_time, end_time, subject_name, teacher_id, teacher_name,
                        room_number, created_at, updated_at, is_deleted
                    ) VALUES (
                        gen_random_uuid(), :tenant_id, :class_timetable_id, :day_of_week, :period_number,
                        :start_time, :end_time, :subject_name, :teacher_id, :teacher_name,
                        :room_number, NOW(), NOW(), false
                    )
                """)
                
                await db.execute(insert_sql, {
                    "tenant_id": timetable_data.tenant_id,
                    "class_timetable_id": class_timetable_id,
                    "day_of_week": day.upper(),
                    "period_number": period.period_number,
                    "start_time": start_time_obj,
                    "end_time": end_time_obj,
                    "subject_name": period.subject_name,
                    "teacher_id": period.teacher_id,
                    "teacher_name": period.teacher_name,
                    "room_number": period.room_number
                })
        
        await db.commit()
        
        return {
            "message": "Class timetable saved successfully",
            "class_timetable_id": str(class_timetable_id)
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# READ-ONLY ENDPOINTS (For Teachers and Students)

@router.get("/readonly/class/{class_id}/today")
async def get_class_today_schedule(
    class_id: UUID,
    academic_year: str,
    today: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get today's schedule for a class (Read-only for Teachers and Students)"""
    service = TimetableService(db)
    
    if not today:
        today = date.today()
    
    day_of_week = DayOfWeek(today.strftime("%A").lower())
    
    try:
        weekly_schedule = await service.get_class_weekly_schedule(class_id, academic_year)
        today_schedule = weekly_schedule.get(day_of_week.value, [])
        
        return {
            "class_id": str(class_id),
            "date": today.isoformat(),
            "day_of_week": day_of_week.value,
            "schedule": today_schedule,
            "total_periods": len(today_schedule)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/teacher/{teacher_id}/weekly-schedule")
async def get_teacher_weekly_timetable(
    teacher_id: UUID,
    academic_year: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get teacher's weekly timetable with class details"""
    try:
        # Scope by tenant for non-super-admins to prevent cross-tenant leakage
        tenant_filter = "" if principal.is_super_admin else "AND ct.tenant_id = :tenant_id"
        sql = text(f"""
            SELECT
                se.day_of_week,
                se.period_number,
                se.start_time,
                se.end_time,
                se.subject_name,
                se.room_number,
                c.class_name,
                c.grade_level,
                c.section
            FROM schedule_entries se
            JOIN class_timetables ct ON se.class_timetable_id = ct.id
            JOIN classes c ON ct.class_id = c.id
            WHERE se.teacher_id = :teacher_id
            AND ct.academic_year = :academic_year
            {tenant_filter}
            AND se.is_deleted = false
            ORDER BY se.day_of_week, se.period_number
        """)

        params = {"teacher_id": teacher_id, "academic_year": academic_year}
        if not principal.is_super_admin:
            params["tenant_id"] = principal.tenant_id
        result = await db.execute(sql, params)
        
        schedule = {
            "monday": [],
            "tuesday": [],
            "wednesday": [],
            "thursday": [],
            "friday": [],
            "saturday": []
        }
        
        for row in result.fetchall():
            day = row[0].lower()
            class_info = {
                "period_number": row[1],
                "start_time": row[2].strftime("%H:%M") if row[2] else None,
                "end_time": row[3].strftime("%H:%M") if row[3] else None,
                "subject_name": row[4],
                "room_number": row[5],
                "class_name": row[6],
                "grade_level": row[7],
                "section": row[8],
                "class_display": f"Grade {row[7]} {row[6]} ({row[8]})"
            }
            if day in schedule:
                schedule[day].append(class_info)
        
        return {
            "teacher_id": str(teacher_id),
            "academic_year": academic_year,
            "weekly_schedule": schedule
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/readonly/teacher/{teacher_id}/today")
async def get_teacher_today_schedule(
    teacher_id: UUID,
    academic_year: str,
    today: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get today's schedule for a teacher (Read-only)"""
    service = TimetableService(db)
    
    if not today:
        today = date.today()
    
    day_of_week = DayOfWeek(today.strftime("%A").lower())
    
    try:
        weekly_schedule = await service.get_teacher_weekly_schedule(teacher_id, academic_year)
        today_schedule = weekly_schedule.get(day_of_week.value, [])
        
        return {
            "teacher_id": str(teacher_id),
            "date": today.isoformat(),
            "day_of_week": day_of_week.value,
            "schedule": today_schedule,
            "total_periods": len(today_schedule)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
