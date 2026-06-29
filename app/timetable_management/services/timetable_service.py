# app/services/timetable_service.py
from typing import List, Optional, Dict, Any, Union
from uuid import UUID
import uuid
from datetime import date, time, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, and_, or_, desc
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from ...services.base_service import BaseService
from ..models.timetable import (
    MasterTimetable, Period, ClassTimetable, TeacherTimetable, 
    ScheduleEntry, TimetableConflict, Subject, TimetableTemplate,
    TimetableAuditLog, DayOfWeek, PeriodType, TimetableStatus, ConflictSeverity
)

import logging
logger = logging.getLogger(__name__)


class TimetableService(BaseService[MasterTimetable]):
    def __init__(self, db: AsyncSession):
        super().__init__(MasterTimetable, db)
    
    # MASTER TIMETABLE OPERATIONS
    
    async def create_master_timetable(self, timetable_data: dict) -> MasterTimetable:
        """Create a new master timetable with auto-generated periods"""
        try:
            master_timetable = await self.create(timetable_data)
            
            # Auto-generate periods if enabled
            if timetable_data.get("auto_generate_periods", True):
                await self._generate_default_periods(master_timetable)
            
            # Log audit
            await self._log_audit_action(
                action_type="create",
                entity_type="master_timetable",
                entity_id=master_timetable.id,
                performed_by=timetable_data.get("created_by"),
                change_description=f"Created master timetable: {master_timetable.timetable_name}"
            )
            
            return master_timetable
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to create master timetable: {str(e)}")
    
    async def _generate_default_periods(self, master_timetable: MasterTimetable):
        """Generate default periods for a master timetable using bulk SQL"""
        try:
            periods_data = []
            current_time = master_timetable.school_start_time
            base_date = datetime.combine(date.today(), current_time)
            
            period_count = 0
            time_offset = 0
            
            for i in range(master_timetable.total_periods_per_day):
                # Calculate period times
                period_start = (base_date + timedelta(minutes=time_offset)).time()
                period_end = (base_date + timedelta(minutes=time_offset + master_timetable.period_duration)).time()
                
                # Regular period
                period_count += 1
                periods_data.append({
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(master_timetable.tenant_id),
                    "master_timetable_id": str(master_timetable.id),
                    "period_number": period_count,
                    "period_name": f"Period {period_count}",
                    "period_type": "regular",
                    "start_time": period_start,
                    "end_time": period_end,
                    "duration_minutes": master_timetable.period_duration,
                    "is_teaching_period": True,
                    "is_active": True,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "is_deleted": False
                })
                
                time_offset += master_timetable.period_duration
                
                # Add breaks
                if i == 2:  # Morning break after 3rd period
                    periods_data.append({
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(master_timetable.tenant_id),
                        "master_timetable_id": str(master_timetable.id),
                        "period_number": period_count + 0.5,
                        "period_name": "Morning Break",
                        "period_type": "break",
                        "start_time": period_end,
                        "end_time": (base_date + timedelta(minutes=time_offset + master_timetable.break_duration)).time(),
                        "duration_minutes": master_timetable.break_duration,
                        "is_teaching_period": False,
                        "is_active": True,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                        "is_deleted": False
                    })
                    time_offset += master_timetable.break_duration
                
                elif i == 5:  # Lunch break after 6th period
                    periods_data.append({
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(master_timetable.tenant_id),
                        "master_timetable_id": str(master_timetable.id),
                        "period_number": period_count + 0.5,
                        "period_name": "Lunch Break",
                        "period_type": "lunch",
                        "start_time": period_end,
                        "end_time": (base_date + timedelta(minutes=time_offset + master_timetable.lunch_duration)).time(),
                        "duration_minutes": master_timetable.lunch_duration,
                        "is_teaching_period": False,
                        "is_active": True,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                        "is_deleted": False
                    })
                    time_offset += master_timetable.lunch_duration
                else:
                    time_offset += 5  # 5 minute gap between regular periods
            
            # Bulk insert periods using raw SQL
            if periods_data:
                bulk_insert_sql = text("""
                    INSERT INTO periods (
                        id, tenant_id, master_timetable_id, period_number, period_name, 
                        period_type, start_time, end_time, duration_minutes, is_teaching_period, 
                        is_active, created_at, updated_at, is_deleted
                    ) VALUES (
                        :id, :tenant_id, :master_timetable_id, :period_number, :period_name,
                        :period_type, :start_time, :end_time, :duration_minutes, :is_teaching_period,
                        :is_active, :created_at, :updated_at, :is_deleted
                    )
                """)
                
                await self.db.execute(bulk_insert_sql, periods_data)
                await self.db.commit()
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to generate periods: {str(e)}")
    
    # BULK OPERATIONS USING RAW SQL FOR HIGH PERFORMANCE
    
    async def bulk_create_schedule_entries(self, schedule_entries: List[dict], tenant_id: UUID) -> dict:
        """Bulk create schedule entries using raw SQL for maximum performance"""
        try:
            if not schedule_entries:
                raise HTTPException(status_code=400, detail="No schedule entries provided")
            
            now = datetime.utcnow()
            insert_data = []
            validation_errors = []
            
            for idx, entry in enumerate(schedule_entries):
                try:
                    # Validate required fields
                    required_fields = ["class_timetable_id", "period_id", "day_of_week", "subject_name"]
                    for field in required_fields:
                        if not entry.get(field):
                            validation_errors.append(f"Row {idx + 1}: Missing required field '{field}'")
                            continue
                    
                    if validation_errors:
                        continue
                    
                    # Prepare schedule entry
                    schedule_record = {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "class_timetable_id": str(entry["class_timetable_id"]),
                        "teacher_timetable_id": str(entry["teacher_timetable_id"]) if entry.get("teacher_timetable_id") else None,
                        "period_id": str(entry["period_id"]),
                        "subject_id": str(entry["subject_id"]) if entry.get("subject_id") else None,
                        "day_of_week": entry["day_of_week"],
                        "subject_name": entry["subject_name"],
                        "subject_code": entry.get("subject_code"),
                        "room_number": entry.get("room_number"),
                        "building": entry.get("building"),
                        "floor": entry.get("floor"),
                        "teacher_name": entry.get("teacher_name"),
                        "notes": entry.get("notes"),
                        "is_recurring": entry.get("is_recurring", True),
                        "effective_date": entry.get("effective_date"),
                        "expiry_date": entry.get("expiry_date"),
                        "attendance_required": entry.get("attendance_required", True),
                        "batch_id": str(uuid.uuid4()),  # Same batch for all entries
                        "import_source": "bulk_import",
                        "created_at": now,
                        "updated_at": now,
                        "is_deleted": False,
                        "is_active": True
                    }
                    insert_data.append(schedule_record)
                    
                except Exception as e:
                    validation_errors.append(f"Row {idx + 1}: {str(e)}")
            
            if validation_errors:
                raise HTTPException(
                    status_code=400,
                    detail={"message": "Validation errors found", "errors": validation_errors}
                )
            
            # Bulk insert with conflict handling
            bulk_insert_sql = text("""
                INSERT INTO schedule_entries (
                    id, tenant_id, class_timetable_id, teacher_timetable_id, period_id, subject_id,
                    day_of_week, subject_name, subject_code, room_number, building, floor,
                    teacher_name, notes, is_recurring, effective_date, expiry_date,
                    attendance_required, batch_id, import_source, created_at, updated_at,
                    is_deleted, is_active
                ) VALUES (
                    :id, :tenant_id, :class_timetable_id, :teacher_timetable_id, :period_id, :subject_id,
                    :day_of_week, :subject_name, :subject_code, :room_number, :building, :floor,
                    :teacher_name, :notes, :is_recurring, :effective_date, :expiry_date,
                    :attendance_required, :batch_id, :import_source, :created_at, :updated_at,
                    :is_deleted, :is_active
                ) ON CONFLICT (class_timetable_id, day_of_week, period_id) 
                DO UPDATE SET
                    subject_name = EXCLUDED.subject_name,
                    teacher_timetable_id = EXCLUDED.teacher_timetable_id,
                    teacher_name = EXCLUDED.teacher_name,
                    room_number = EXCLUDED.room_number,
                    updated_at = EXCLUDED.updated_at
            """)
            
            await self.db.execute(bulk_insert_sql, insert_data)
            await self.db.commit()
            
            # Run conflict detection after bulk insert
            if insert_data:
                await self._bulk_detect_conflicts(tenant_id, insert_data[0]["batch_id"])
            
            return {
                "total_records_processed": len(schedule_entries),
                "successful_records": len(insert_data),
                "failed_records": len(validation_errors),
                "batch_id": insert_data[0]["batch_id"] if insert_data else None,
                "tenant_id": str(tenant_id),
                "status": "success"
            }
            
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk schedule creation failed: {str(e)}")
    
    async def _bulk_detect_conflicts(self, tenant_id: UUID, batch_id: str):
        """Bulk detect conflicts for newly created schedule entries"""
        try:
            # Teacher double booking conflicts
            teacher_conflicts_sql = text("""
                INSERT INTO timetable_conflicts (
                    id, tenant_id, conflict_type, severity, title, description,
                    teacher_id, day_of_week, period_number, conflict_data,
                    detected_by, created_at, updated_at, is_deleted
                )
                SELECT 
                    gen_random_uuid(),
                    :tenant_id,
                    'teacher_double_booking',
                    'high',
                    'Teacher Double Booking',
                    'Teacher ' || se1.teacher_name || ' is scheduled for multiple classes at the same time',
                    tt.teacher_id,
                    se1.day_of_week,
                    p.period_number,
                    json_build_object(
                        'conflicting_entries', array[se1.id::text, se2.id::text],
                        'class_names', array[ct1.class_name, ct2.class_name]
                    ),
                    'system',
                    now(),
                    now(),
                    false
                FROM schedule_entries se1
                JOIN schedule_entries se2 ON (
                    se1.teacher_timetable_id = se2.teacher_timetable_id
                    AND se1.day_of_week = se2.day_of_week
                    AND se1.period_id = se2.period_id
                    AND se1.id < se2.id
                )
                JOIN periods p ON se1.period_id = p.id
                JOIN class_timetables ct1 ON se1.class_timetable_id = ct1.id
                JOIN class_timetables ct2 ON se2.class_timetable_id = ct2.id
                JOIN teacher_timetables tt ON se1.teacher_timetable_id = tt.id
                WHERE se1.tenant_id = :tenant_id
                AND se1.batch_id = :batch_id
                AND se1.is_active = true
            """)
            
            await self.db.execute(teacher_conflicts_sql, {
                "tenant_id": tenant_id,
                "batch_id": batch_id
            })
            
            # Room conflicts
            room_conflicts_sql = text("""
                INSERT INTO timetable_conflicts (
                    id, tenant_id, conflict_type, severity, title, description,
                    room_number, day_of_week, period_number, conflict_data,
                    detected_by, created_at, updated_at, is_deleted
                )
                SELECT 
                    gen_random_uuid(),
                    :tenant_id,
                    'room_conflict',
                    'medium',
                    'Room Double Booking',
                    'Room ' || se1.room_number || ' is booked for multiple classes',
                    se1.room_number,
                    se1.day_of_week,
                    p.period_number,
                    json_build_object(
                        'conflicting_entries', array[se1.id::text, se2.id::text],
                        'subjects', array[se1.subject_name, se2.subject_name]
                    ),
                    'system',
                    now(),
                    now(),
                    false
                FROM schedule_entries se1
                JOIN schedule_entries se2 ON (
                    se1.room_number = se2.room_number
                    AND se1.day_of_week = se2.day_of_week
                    AND se1.period_id = se2.period_id
                    AND se1.id < se2.id
                )
                JOIN periods p ON se1.period_id = p.id
                WHERE se1.tenant_id = :tenant_id
                AND se1.batch_id = :batch_id
                AND se1.room_number IS NOT NULL
                AND se1.room_number != ''
                AND se1.is_active = true
            """)
            
            await self.db.execute(room_conflicts_sql, {
                "tenant_id": tenant_id,
                "batch_id": batch_id
            })
            
            await self.db.commit()
            
        except Exception as e:
            # Don't fail the main operation if conflict detection fails
            logger.error(f"Conflict detection failed: {str(e)}")
            pass
    
    # Only these columns may be bulk-updated. The field name is interpolated into SQL, so it
    # MUST come from this whitelist (never directly from the client) to avoid SQL injection.
    _UPDATABLE_ENTRY_FIELDS = {
        "subject_name", "subject_code", "teacher_id", "teacher_name", "room_number", "building",
        "start_time", "end_time", "period_number", "day_of_week", "is_active", "is_substitution",
        "period_id", "subject_id", "class_timetable_id", "teacher_timetable_id",
    }

    async def bulk_update_schedule_entries(self, updates: List[dict], tenant_id=None) -> dict:
        """Bulk update schedule entries (tenant-scoped; only whitelisted columns)."""
        try:
            if not updates:
                raise HTTPException(status_code=400, detail="No updates provided")

            updated_count = 0
            tenant_param = str(tenant_id) if tenant_id else None

            for update in updates:
                if not update.get("schedule_entry_id"):
                    continue

                update_fields = []
                params = {
                    "schedule_entry_id": update["schedule_entry_id"],
                    "updated_at": datetime.utcnow(),
                    "tenant_id": tenant_param,
                }
                for field, value in update.items():
                    if field in self._UPDATABLE_ENTRY_FIELDS and value is not None:
                        update_fields.append(f"{field} = :{field}")
                        params[field] = value

                if update_fields:
                    update_sql = text(f"""
                        UPDATE schedule_entries
                        SET {', '.join(update_fields)}, updated_at = :updated_at
                        WHERE id = :schedule_entry_id
                        AND is_deleted = false
                        AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
                    """)
                    result = await self.db.execute(update_sql, params)
                    updated_count += result.rowcount

            await self.db.commit()

            return {
                "updated_records": updated_count,
                "total_requests": len(updates),
                "status": "success"
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk update failed: {str(e)}")
    
    async def bulk_delete_schedule_entries(self, entry_ids: List[UUID], hard_delete: bool = False, tenant_id=None) -> dict:
        """Bulk delete schedule entries (tenant-scoped)."""
        try:
            if not entry_ids:
                raise HTTPException(status_code=400, detail="No entry IDs provided")

            if hard_delete:
                delete_sql = text("""
                    DELETE FROM schedule_entries
                    WHERE id = ANY(:entry_ids)
                    AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
                """)
            else:
                delete_sql = text("""
                    UPDATE schedule_entries
                    SET is_deleted = true, is_active = false, updated_at = :updated_at
                    WHERE id = ANY(:entry_ids)
                    AND is_deleted = false
                    AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
                """)

            result = await self.db.execute(delete_sql, {
                "entry_ids": [str(eid) for eid in entry_ids],
                "updated_at": datetime.utcnow(),
                "tenant_id": str(tenant_id) if tenant_id else None,
            })

            await self.db.commit()

            return {
                "deleted_records": result.rowcount,
                "delete_type": "hard" if hard_delete else "soft",
                "status": "success"
            }

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")
    
    # CLASS AND TEACHER TIMETABLE OPERATIONS
    
    async def create_class_timetable(self, class_timetable_data: dict) -> ClassTimetable:
        """Create timetable for a specific class"""
        try:
            class_timetable = ClassTimetable(**class_timetable_data)
            self.db.add(class_timetable)
            await self.db.commit()
            await self.db.refresh(class_timetable)
            
            # Update master timetable statistics
            await self._update_master_timetable_stats(class_timetable.master_timetable_id)
            
            return class_timetable
            
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Class timetable already exists for this academic year")
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to create class timetable: {str(e)}")
    
    async def create_teacher_timetable(self, teacher_timetable_data: dict) -> TeacherTimetable:
        """Create timetable for a specific teacher"""
        try:
            teacher_timetable = TeacherTimetable(**teacher_timetable_data)
            self.db.add(teacher_timetable)
            await self.db.commit()
            await self.db.refresh(teacher_timetable)
            
            # Update master timetable statistics
            await self._update_master_timetable_stats(teacher_timetable.master_timetable_id)
            
            return teacher_timetable
            
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Teacher timetable already exists for this academic year")
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to create teacher timetable: {str(e)}")
    
    async def _update_master_timetable_stats(self, master_timetable_id: UUID):
        """Update statistics for master timetable"""
        stats_sql = text("""
            UPDATE master_timetables
            SET 
                total_classes = (
                    SELECT COUNT(*) FROM class_timetables 
                    WHERE master_timetable_id = :master_id AND is_deleted = false
                ),
                total_teachers = (
                    SELECT COUNT(*) FROM teacher_timetables 
                    WHERE master_timetable_id = :master_id AND is_deleted = false
                ),
                total_schedule_entries = (
                    SELECT COUNT(*) FROM schedule_entries se
                    JOIN class_timetables ct ON se.class_timetable_id = ct.id
                    WHERE ct.master_timetable_id = :master_id AND se.is_deleted = false
                ),
                updated_at = :updated_at
            WHERE id = :master_id
        """)
        
        await self.db.execute(stats_sql, {
            "master_id": master_timetable_id,
            "updated_at": datetime.utcnow()
        })
        await self.db.commit()
    
    # SCHEDULE RETRIEVAL OPERATIONS (Optimized with Raw SQL)
    
    async def get_class_weekly_schedule(self, class_id: UUID, academic_year: str) -> Dict[str, List[dict]]:
        """Get optimized weekly schedule for a class using raw SQL"""
        try:
            weekly_schedule_sql = text("""
                SELECT 
                    se.day_of_week,
                    p.period_number,
                    p.period_name,
                    p.start_time,
                    p.end_time,
                    se.subject_name,
                    se.subject_code,
                    se.teacher_name,
                    se.room_number,
                    se.building,
                    se.notes,
                    se.is_substitution,
                    se.id as schedule_entry_id
                FROM schedule_entries se
                JOIN class_timetables ct ON se.class_timetable_id = ct.id
                JOIN periods p ON se.period_id = p.id
                WHERE ct.class_id = :class_id
                AND ct.academic_year = :academic_year
                AND ct.is_active = true
                AND se.is_active = true
                AND se.is_deleted = false
                ORDER BY 
                    CASE se.day_of_week
                        WHEN 'monday' THEN 1
                        WHEN 'tuesday' THEN 2
                        WHEN 'wednesday' THEN 3
                        WHEN 'thursday' THEN 4
                        WHEN 'friday' THEN 5
                        WHEN 'saturday' THEN 6
                        WHEN 'sunday' THEN 7
                    END,
                    p.period_number
            """)
            
            result = await self.db.execute(weekly_schedule_sql, {
                "class_id": class_id,
                "academic_year": academic_year
            })
            
            schedule_data = result.fetchall()
            
            # Organize by day
            weekly_schedule = {day.value: [] for day in DayOfWeek}
            
            for row in schedule_data:
                day_schedule = {
                    "schedule_entry_id": str(row[12]),
                    "period_number": row[1],
                    "period_name": row[2],
                    "start_time": row[3].isoformat() if row[3] else None,
                    "end_time": row[4].isoformat() if row[4] else None,
                    "subject_name": row[5],
                    "subject_code": row[6],
                    "teacher_name": row[7],
                    "room_number": row[8],
                    "building": row[9],
                    "notes": row[10],
                    "is_substitution": row[11]
                }
                weekly_schedule[row[0]].append(day_schedule)
            
            return weekly_schedule
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get class schedule: {str(e)}")
    
    async def get_teacher_weekly_schedule(self, teacher_id: UUID, academic_year: str) -> Dict[str, List[dict]]:
        """Get optimized weekly schedule for a teacher using raw SQL"""
        try:
            # Initialize empty schedule
            weekly_schedule = {day.value: [] for day in DayOfWeek}
            
            teacher_schedule_sql = text("""
                SELECT 
                    se.day_of_week,
                    p.period_number,
                    p.period_name,
                    p.start_time,
                    p.end_time,
                    se.subject_name,
                    se.subject_code,
                    ct.class_name,
                    se.room_number,
                    se.building,
                    se.notes,
                    se.id as schedule_entry_id
                FROM schedule_entries se
                JOIN teacher_timetables tt ON se.teacher_timetable_id = tt.id
                JOIN class_timetables ct ON se.class_timetable_id = ct.id
                JOIN periods p ON se.period_id = p.id
                WHERE tt.teacher_id = :teacher_id
                AND tt.academic_year = :academic_year
                AND tt.is_active = true
                AND se.is_active = true
                AND se.is_deleted = false
                ORDER BY 
                    CASE se.day_of_week
                        WHEN 'monday' THEN 1
                        WHEN 'tuesday' THEN 2
                        WHEN 'wednesday' THEN 3
                        WHEN 'thursday' THEN 4
                        WHEN 'friday' THEN 5
                        WHEN 'saturday' THEN 6
                        WHEN 'sunday' THEN 7
                    END,
                    p.period_number
            """)
            
            result = await self.db.execute(teacher_schedule_sql, {
                "teacher_id": teacher_id,
                "academic_year": academic_year
            })
            
            schedule_data = result.fetchall()
            
            # Process results if any exist
            if schedule_data:
                for row in schedule_data:
                    day_schedule = {
                        "schedule_entry_id": str(row[11]),
                        "period_number": row[1],
                        "period_name": row[2],
                        "start_time": row[3].isoformat() if row[3] else None,
                        "end_time": row[4].isoformat() if row[4] else None,
                        "subject_name": row[5],
                        "subject_code": row[6],
                        "class_name": row[7],
                        "room_number": row[8],
                        "building": row[9],
                        "notes": row[10]
                    }
                    weekly_schedule[row[0]].append(day_schedule)
            
            return weekly_schedule
            
        except Exception as e:
            # Return empty schedule on error instead of raising exception
            logger.error(f"Error in get_teacher_weekly_schedule: {str(e)}")
            return {day.value: [] for day in DayOfWeek}
    
    # ANALYTICS AND REPORTING
    
    async def get_timetable_analytics(self, tenant_id: UUID, academic_year: str) -> dict:
        """Get comprehensive timetable analytics using raw SQL"""
        try:
            analytics_sql = text("""
                SELECT 
                    -- Basic counts
                    COUNT(DISTINCT mt.id) as total_master_timetables,
                    COUNT(DISTINCT ct.id) as total_class_timetables,
                    COUNT(DISTINCT tt.id) as total_teacher_timetables,
                    COUNT(DISTINCT se.id) as total_schedule_entries,
                    COUNT(DISTINCT tc.id) as total_conflicts,
                    COUNT(CASE WHEN tc.is_resolved = false THEN 1 END) as unresolved_conflicts,
                    
                    -- Utilization stats
                    COUNT(DISTINCT se.room_number) as unique_rooms_used,
                    COUNT(DISTINCT se.subject_name) as unique_subjects,
                    
                    -- Workload stats
                    AVG(tt.actual_periods_per_week) as avg_teacher_periods,
                    MAX(tt.actual_periods_per_week) as max_teacher_periods,
                    MIN(tt.actual_periods_per_week) as min_teacher_periods
                    
                FROM master_timetables mt
                LEFT JOIN class_timetables ct ON mt.id = ct.master_timetable_id
                LEFT JOIN teacher_timetables tt ON mt.id = tt.master_timetable_id
                LEFT JOIN schedule_entries se ON ct.id = se.class_timetable_id
                LEFT JOIN timetable_conflicts tc ON mt.tenant_id = tc.tenant_id
                WHERE mt.tenant_id = :tenant_id
                AND mt.academic_year = :academic_year
                AND mt.is_deleted = false
            """)
            
            result = await self.db.execute(analytics_sql, {
                "tenant_id": tenant_id,
                "academic_year": academic_year
            })
            
            analytics_data = result.fetchone()
            
            if not analytics_data:
                return {"message": "No timetable data found"}
            
            return {
                "total_master_timetables": analytics_data[0] or 0,
                "total_class_timetables": analytics_data[1] or 0,
                "total_teacher_timetables": analytics_data[2] or 0,
                "total_schedule_entries": analytics_data[3] or 0,
                "total_conflicts": analytics_data[4] or 0,
                "unresolved_conflicts": analytics_data[5] or 0,
                "unique_rooms_used": analytics_data[6] or 0,
                "unique_subjects": analytics_data[7] or 0,
                "average_teacher_periods": round(float(analytics_data[8]), 2) if analytics_data[8] else 0.0,
                "max_teacher_periods": analytics_data[9] or 0,
                "min_teacher_periods": analytics_data[10] or 0,
                "conflict_resolution_rate": round(
                    ((analytics_data[4] - analytics_data[5]) / analytics_data[4] * 100), 2
                ) if analytics_data[4] > 0 else 100.0,
                "tenant_id": str(tenant_id),
                "academic_year": academic_year
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get analytics: {str(e)}")
    
    # AUDIT LOGGING
    
    async def _log_audit_action(
        self,
        action_type: str,
        entity_type: str,
        entity_id: UUID,
        performed_by: UUID,
        change_description: str,
        old_values: dict = None,
        new_values: dict = None
    ):
        """Log audit action"""
        try:
            audit_log = TimetableAuditLog(
                tenant_id=entity_id,  # This might need adjustment based on context
                action_type=action_type,
                entity_type=entity_type,
                entity_id=entity_id,
                performed_by=performed_by,
                old_values=old_values,
                new_values=new_values,
                change_description=change_description
            )
            self.db.add(audit_log)
            await self.db.commit()
        except Exception:
            # Don't fail the main operation if audit logging fails
            pass
