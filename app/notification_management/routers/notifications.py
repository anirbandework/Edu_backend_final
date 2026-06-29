# app/routers/school_authority/notifications.py
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel, EmailStr
from ...core.database import get_db
from ...auth_rbac.security.deps import get_current_principal, require_super_admin, require_staff, assert_same_tenant
from ...auth_rbac.access.deps import require_staff_or_module
from ...auth_rbac.security.principal import Principal
from ...notification_management.services.notification_service import NotificationService
from ...notification_management.models.notification import (
    NotificationType, NotificationPriority, SenderType, RecipientType,
    NotificationStatus, DeliveryChannel
)

import logging
logger = logging.getLogger(__name__)

# Pydantic Models
class NotificationCreate(BaseModel):
    tenant_id: UUID
    title: str
    message: str
    short_message: Optional[str] = None
    notification_type: NotificationType
    priority: NotificationPriority = NotificationPriority.NORMAL
    recipient_type: RecipientType
    recipient_config: dict  # REQUIRED: Specify who receives the notification
    delivery_channels: Optional[List[str]] = ["in_app"]
    scheduled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    attachments: Optional[dict] = None
    action_url: Optional[str] = None
    action_text: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    academic_year: Optional[str] = None
    term: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "tenant_id": "3fd85f64-5717-4562-b3fc-2c963f66afa6",
                "title": "Important Announcement",
                "message": "This is an important message for students",
                "notification_type": "announcement",
                "priority": "normal",
                "recipient_type": "individual",
                "recipient_config": {
                    "student_ids": ["student-uuid-1", "student-uuid-2"]
                },
                "delivery_channels": ["in_app"]
            }
        }

router = APIRouter(prefix="/api/v1/school_authority/notifications", tags=["School Authority - Notifications"])


def _resolve_acting_user_id(principal: Principal, requested_user_id: UUID) -> UUID:
    """Resolve the user_id a request may act on.

    Super-admins and staff may act on behalf of any user; a regular user may
    only act on their own recipient rows. This prevents reading/mutating
    another user's notification state.
    """
    if principal.is_super_admin or principal.is_staff:
        return requested_user_id
    if str(requested_user_id) != str(principal.user_id):
        raise HTTPException(status_code=403, detail="Cannot act on another user's notifications")
    return UUID(str(principal.user_id))


def _scope_tenant(principal: Principal, requested_tenant_id) -> Optional[str]:
    """Return the effective tenant_id (as str) bound to the principal.

    Non-super-admins are always scoped to their own tenant; super-admins may
    target an explicit tenant or operate cross-tenant (None) when omitted.
    """
    effective = requested_tenant_id if principal.is_super_admin else principal.tenant_id
    return str(effective) if effective is not None else None

async def _validate_and_get_sender_type(db: AsyncSession, sender_id: UUID) -> SenderType:
    """Validate sender exists and return their actual type from database"""
    
    logger.debug(f"Validating sender_id: {sender_id}")
    
    # Check if sender is a student FIRST (should not be allowed to send)
    student_sql = text("""
        SELECT id FROM members 
        WHERE id = :sender_id AND is_deleted = false AND (profile->>'category') = 'student'
    """)
    result = await db.execute(student_sql, {"sender_id": str(sender_id)})
    student_result = result.fetchone()
    logger.debug(f"Student check: {student_result}")
    if student_result:
        logger.debug(f"Student found - raising 403 error")
        raise HTTPException(
            status_code=403, 
            detail="Students are not allowed to send notifications"
        )
    
    # Check if sender is a school authority
    school_authority_sql = text("""
        SELECT id FROM school_authorities 
        WHERE id = :sender_id AND is_deleted = false
    """)
    result = await db.execute(school_authority_sql, {"sender_id": str(sender_id)})
    sa_result = result.fetchone()
    logger.debug(f"School authority check: {sa_result}")
    if sa_result:
        return SenderType.SCHOOL_AUTHORITY
    
    # Check if sender is a teacher
    teacher_sql = text("""
        SELECT id FROM members 
        WHERE id = :sender_id AND is_deleted = false AND (profile->>'category') IS DISTINCT FROM 'student'
    """)
    result = await db.execute(teacher_sql, {"sender_id": str(sender_id)})
    teacher_result = result.fetchone()
    logger.debug(f"Teacher check: {teacher_result}")
    if teacher_result:
        return SenderType.TEACHER

    # Check if sender is a dynamic staff user (faculty/principal/HOD/office...)
    staff_sql = text("""
        SELECT id FROM members
        WHERE id = :sender_id AND is_deleted = false
    """)
    result = await db.execute(staff_sql, {"sender_id": str(sender_id)})
    if result.fetchone():
        return SenderType.SCHOOL_AUTHORITY  # staff send as an authority-type sender

    # Sender not found in any valid table
    raise HTTPException(
        status_code=404,
        detail="Sender not found or invalid sender type"
    )

@router.post("/send", response_model=dict)
async def send_notification(
    notification_data: NotificationCreate,
    sender_id: Optional[UUID] = None,
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff_or_module('send_notification'))  # staff (teacher/authority/super-admin) may send
):
    """Send notification to recipients

    recipient_config examples:
    - Individual students: {"student_ids": ["uuid1", "uuid2"]}
    - Individual teachers: {"teacher_ids": ["uuid1", "uuid2"]}
    - Entire class: {"class_id": "class-uuid"}
    - Entire grade: {"grade": "10"}
    - All students: {} (when recipient_type is "all_students")
    - All teachers: {} (when recipient_type is "all_teachers")
    """
    # Derive the acting sender from the authenticated principal.
    # Non-super-admins can never spoof another sender_id.
    if principal.is_super_admin and sender_id is not None:
        effective_sender_id = sender_id
    else:
        effective_sender_id = UUID(str(principal.user_id))

    # Effective tenant: non-super-admin always bound to their own tenant.
    effective_tenant = (
        notification_data.tenant_id if principal.is_super_admin else principal.tenant_id
    )
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    # Override client-supplied tenant_id so it cannot target another tenant.
    notification_data.tenant_id = UUID(str(effective_tenant))

    service = NotificationService(db)

    try:
        # Validate sender and determine actual sender type from database
        sender_type_enum = await _validate_and_get_sender_type(db, effective_sender_id)

        notification = await service.create_notification(
            sender_id=effective_sender_id,
            sender_type=sender_type_enum,
            notification_data=notification_data.model_dump()
        )
        
        return {
            "id": str(notification.id),
            "message": "Notification sent successfully",
            "title": notification.title,
            "total_recipients": notification.total_recipients,
            "delivered_count": notification.delivered_count,
            "sent_at": notification.sent_at.isoformat() if notification.sent_at else None
        }
    except HTTPException:
        raise  # preserve the original status code
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/for-user/{user_id}")
async def get_notifications_for_user(
    user_id: UUID,
    user_type: str = Query(..., description="Type of user: student, teacher"),
    tenant_id: UUID = Query(..., description="Tenant ID"),
    notification_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    unread_only: bool = Query(False),
    include_archived: bool = Query(False, description="Include archived notifications"),
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get notifications for a specific user (student/teacher)"""
    # Bind tenant to the principal; ignore client-supplied tenant_id for non-super-admin.
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    # A regular (non-staff, non-super-admin) user may only read their own notifications.
    if not principal.is_super_admin and not principal.is_staff:
        if str(user_id) != str(principal.user_id):
            raise HTTPException(status_code=403, detail="Cannot access another user's notifications")

    service = NotificationService(db)

    try:
        logger.debug(f"Getting notifications for user {user_id}, type {user_type}, tenant {effective_tenant}, include_archived={include_archived}")

        notifications = await service.get_notifications_for_user(
            user_id=user_id,
            user_type=user_type,
            tenant_id=effective_tenant,
            notification_type=notification_type,
            status=status,
            unread_only=unread_only,
            include_archived=include_archived,
            limit=limit
        )
        
        return notifications  # Return the list directly as expected by Flutter
        
    except Exception as e:
        logger.debug(f"Error getting notifications: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{notification_id}/mark-read")
async def mark_notification_as_read(
    notification_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Mark specific notification as read for user"""
    user_id = _resolve_acting_user_id(principal, user_id)
    service = NotificationService(db)

    try:
        result = await service.mark_notification_as_read(notification_id, user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{notification_id}/archive")
async def archive_notification(
    notification_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Archive notification for user"""
    user_id = _resolve_acting_user_id(principal, user_id)
    try:
        archive_sql = text("""
            UPDATE notification_recipients 
            SET is_archived = true, updated_at = CURRENT_TIMESTAMP
            WHERE notification_id = :notification_id 
            AND recipient_id = :user_id 
            AND is_deleted = false
        """)
        
        result = await db.execute(archive_sql, {
            "notification_id": str(notification_id),
            "user_id": str(user_id)
        })
        await db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Notification not found for user")
        
        return {"message": "Notification archived successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{notification_id}/unarchive")
async def unarchive_notification(
    notification_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Unarchive notification for user"""
    user_id = _resolve_acting_user_id(principal, user_id)
    try:
        unarchive_sql = text("""
            UPDATE notification_recipients 
            SET is_archived = false, updated_at = CURRENT_TIMESTAMP
            WHERE notification_id = :notification_id 
            AND recipient_id = :user_id 
            AND is_deleted = false
        """)
        
        result = await db.execute(unarchive_sql, {
            "notification_id": str(notification_id),
            "user_id": str(user_id)
        })
        await db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Notification not found for user")
        
        return {"message": "Notification unarchived successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/archived/{user_id}")
async def get_archived_notifications(
    user_id: UUID,
    tenant_id: UUID = Query(..., description="Tenant ID"),
    user_type: str = Query("school_authority", description="Type of user: student, teacher, school_authority"),
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get archived notifications for user"""
    user_id = _resolve_acting_user_id(principal, user_id)
    effective_tenant = _scope_tenant(principal, tenant_id)
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    try:
        archived_sql = text("""
            SELECT 
                n.id,
                n.title,
                n.message,
                n.notification_type,
                n.priority,
                n.status,
                n.created_at,
                n.sent_at,
                nr.read_at,
                nr.delivered_at
            FROM notifications n
            JOIN notification_recipients nr ON n.id = nr.notification_id
            WHERE nr.recipient_id = :user_id
            AND nr.recipient_type = :user_type
            AND n.tenant_id = :tenant_id
            AND nr.is_archived = true
            AND nr.is_deleted = false
            AND n.is_deleted = false
            ORDER BY nr.updated_at DESC
            LIMIT :limit
        """)
        
        result = await db.execute(archived_sql, {
            "user_id": str(user_id),
            "user_type": user_type,
            "tenant_id": effective_tenant,
            "limit": limit
        })
        notifications = result.fetchall()
        
        return [
            {
                "id": str(n[0]),
                "title": n[1],
                "message": n[2],
                "notification_type": n[3],
                "priority": n[4],
                "status": n[5],
                "created_at": n[6].isoformat() if n[6] else None,
                "sent_at": n[7].isoformat() if n[7] else None,
                "read_at": n[8].isoformat() if n[8] else None,
                "delivered_at": n[9].isoformat() if n[9] else None,
                "is_archived": True
            } for n in notifications
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{notification_id}/delete")
async def delete_notification_for_user(
    notification_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Permanently delete notification for user (soft delete)"""
    user_id = _resolve_acting_user_id(principal, user_id)
    try:
        delete_sql = text("""
            UPDATE notification_recipients 
            SET is_deleted = true, updated_at = CURRENT_TIMESTAMP
            WHERE notification_id = :notification_id 
            AND recipient_id = :user_id 
            AND is_deleted = false
        """)
        
        result = await db.execute(delete_sql, {
            "notification_id": str(notification_id),
            "user_id": str(user_id)
        })
        await db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Notification not found for user")
        
        return {"message": "Notification deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sent-by/{sender_id}")
async def get_notifications_sent_by_user(
    sender_id: UUID,
    tenant_id: UUID = Query(...),
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get all notifications sent by a specific user with recipient IDs (optimized)"""
    # A regular user may only view their own sent notifications.
    sender_id = _resolve_acting_user_id(principal, sender_id)
    effective_tenant = _scope_tenant(principal, tenant_id)
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    try:
        # Single query to get notifications with recipients using JSON aggregation
        notifications_sql = text("""
            SELECT 
                n.id,
                n.title,
                n.message,
                n.notification_type,
                n.priority,
                n.total_recipients,
                n.delivered_count,
                n.status,
                n.created_at,
                n.sent_at,
                COALESCE(
                    JSON_AGG(
                        JSON_BUILD_OBJECT(
                            'recipient_id', nr.recipient_id,
                            'recipient_type', nr.recipient_type,
                            'recipient_name', nr.recipient_name
                        )
                    ) FILTER (WHERE nr.id IS NOT NULL),
                    '[]'::json
                ) as recipients
            FROM notifications n
            LEFT JOIN notification_recipients nr ON n.id = nr.notification_id AND nr.is_deleted = false
            WHERE n.sender_id = :sender_id
            AND n.tenant_id = :tenant_id
            AND n.is_deleted = false
            GROUP BY n.id, n.title, n.message, n.notification_type, n.priority, 
                     n.total_recipients, n.delivered_count, n.status, n.created_at, n.sent_at
            ORDER BY n.created_at DESC
            LIMIT :limit
        """)
        
        result = await db.execute(notifications_sql, {
            "sender_id": str(sender_id),
            "tenant_id": effective_tenant,
            "limit": limit
        })
        notifications = result.fetchall()
        
        return [
            {
                "id": str(n[0]),
                "title": n[1],
                "message": n[2],
                "notification_type": n[3],
                "priority": n[4],
                "total_recipients": n[5],
                "delivered_count": n[6],
                "status": n[7],
                "created_at": n[8].isoformat() if n[8] else None,
                "sent_at": n[9].isoformat() if n[9] else None,
                "recipients": n[10] if n[10] else []
            } for n in notifications
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/archive-stats/{user_id}")
async def get_archive_statistics(
    user_id: UUID,
    tenant_id: UUID = Query(..., description="Tenant ID"),
    user_type: str = Query("school_authority", description="Type of user: student, teacher, school_authority"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal)
):
    """Get archive statistics for user"""
    user_id = _resolve_acting_user_id(principal, user_id)
    effective_tenant = _scope_tenant(principal, tenant_id)
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    try:
        stats_sql = text("""
            SELECT 
                COUNT(*) as total_archived,
                COUNT(CASE WHEN nr.updated_at >= CURRENT_DATE - INTERVAL '30 days' THEN 1 END) as archived_this_month,
                COALESCE(SUM(LENGTH(n.message)), 0) as estimated_storage_bytes
            FROM notification_recipients nr
            JOIN notifications n ON nr.notification_id = n.id
            WHERE nr.recipient_id = :user_id
            AND nr.recipient_type = :user_type
            AND n.tenant_id = :tenant_id
            AND nr.is_archived = true
            AND nr.is_deleted = false
            AND n.is_deleted = false
        """)
        
        result = await db.execute(stats_sql, {
            "user_id": str(user_id),
            "user_type": user_type,
            "tenant_id": effective_tenant
        })
        stats = result.fetchone()
        
        return {
            "total_archived": stats[0] if stats else 0,
            "archived_this_month": stats[1] if stats else 0,
            "estimated_storage_kb": round((stats[2] if stats else 0) / 1024, 2)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# DEBUG ENDPOINTS
@router.get("/debug/all-notifications", dependencies=[Depends(require_super_admin)])
async def debug_all_notifications(
    tenant_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug: See all notifications in the database for a tenant"""
    try:
        notifications_sql = text("""
            SELECT 
                n.id,
                n.title,
                n.total_recipients,
                n.delivered_count,
                n.status,
                n.created_at,
                n.sender_id,
                n.sender_type
            FROM notifications n
            WHERE n.tenant_id = :tenant_id
            AND n.is_deleted = false
            ORDER BY n.created_at DESC
            LIMIT 20
        """)
        
        result = await db.execute(notifications_sql, {"tenant_id": tenant_id})
        notifications = result.fetchall()
        
        return {
            "tenant_id": tenant_id,
            "total_notifications": len(notifications),
            "notifications": [
                {
                    "id": str(n[0]),
                    "title": n[1],
                    "total_recipients": n[2],
                    "delivered_count": n[3],
                    "status": n[4],
                    "created_at": n[5].isoformat() if n[5] else None,
                    "sender_id": str(n[6]),
                    "sender_type": n[7]
                } for n in notifications
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")

@router.get("/debug/all-recipients", dependencies=[Depends(require_super_admin)])
async def debug_all_recipients(
    tenant_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug: See all notification recipients for a tenant"""
    try:
        recipients_sql = text("""
            SELECT 
                nr.id,
                nr.notification_id,
                nr.recipient_id,
                nr.recipient_type,
                nr.recipient_name,
                nr.status,
                nr.created_at,
                n.title
            FROM notification_recipients nr
            JOIN notifications n ON nr.notification_id = n.id
            WHERE nr.tenant_id = :tenant_id
            AND nr.is_deleted = false
            ORDER BY nr.created_at DESC
            LIMIT 50
        """)
        
        result = await db.execute(recipients_sql, {"tenant_id": tenant_id})
        recipients = result.fetchall()
        
        return {
            "tenant_id": tenant_id,
            "total_recipients": len(recipients),
            "recipients": [
                {
                    "id": str(r[0]),
                    "notification_id": str(r[1]),
                    "recipient_id": str(r[2]),
                    "recipient_type": r[3],
                    "recipient_name": r[4],
                    "status": r[5],
                    "created_at": r[6].isoformat() if r[6] else None,
                    "notification_title": r[7]
                } for r in recipients
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")

@router.get("/debug/sender-check/{sender_id}", dependencies=[Depends(require_super_admin)])
async def debug_sender_check(
    sender_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug: Check if sender exists in any table"""
    try:
        results = {}
        
        # Check students
        student_sql = text("SELECT id, first_name, last_name FROM members WHERE id = :sender_id AND is_deleted = false AND (profile->>'category') = 'student'")
        result = await db.execute(student_sql, {"sender_id": sender_id})
        student = result.fetchone()
        results["student"] = {"found": bool(student), "data": f"{student[1]} {student[2]}" if student else None}
        
        # Check teachers
        teacher_sql = text("SELECT id, staff_id FROM members WHERE id = :sender_id AND is_deleted = false AND (profile->>'category') IS DISTINCT FROM 'student'")
        result = await db.execute(teacher_sql, {"sender_id": sender_id})
        teacher = result.fetchone()
        results["teacher"] = {"found": bool(teacher), "data": teacher[1] if teacher else None}
        
        # Check school_authorities
        sa_sql = text("SELECT id, first_name, last_name FROM school_authorities WHERE id = :sender_id AND is_deleted = false")
        result = await db.execute(sa_sql, {"sender_id": sender_id})
        sa = result.fetchone()
        results["school_authority"] = {"found": bool(sa), "data": f"{sa[1]} {sa[2]}" if sa else None}
        
        return {
            "sender_id": sender_id,
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")

@router.get("/debug/student-check/{student_id}", dependencies=[Depends(require_super_admin)])
async def debug_student_check(
    student_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug: Check if student exists and their details"""
    try:
        student_sql = text("""
            SELECT 
                id,
                first_name,
                last_name,
                status,
                tenant_id,
                is_deleted
            FROM members
            WHERE id = :student_id AND (profile->>'category') = 'student'
        """)
        
        result = await db.execute(student_sql, {"student_id": student_id})
        student = result.fetchone()
        
        if not student:
            return {
                "student_found": False,
                "message": "Student not found in database"
            }
        
        return {
            "student_found": True,
            "student": {
                "id": str(student[0]),
                "name": f"{student[1]} {student[2]}",
                "status": student[3],
                "tenant_id": str(student[4]),
                "is_deleted": student[5],
                "tenant_matches": str(student[4]) == tenant_id
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")

@router.post("/debug/create-test-notification", dependencies=[Depends(require_super_admin)])
async def create_test_notification(
    student_id: str,
    tenant_id: str,
    sender_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug: Create a test notification directly for debugging"""
    try:
        logger.debug(f"Creating test notification for student {student_id}")
        
        service = NotificationService(db)
        
        # FIXED: Convert string UUIDs to UUID objects properly
        try:
            student_uuid = UUID(student_id)
            tenant_uuid = UUID(tenant_id) 
            sender_uuid = UUID(sender_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {str(e)}")
        
        # Create test notification data
        test_notification_data = {
            "tenant_id": tenant_uuid,  # FIXED: Use UUID object
            "title": "🧪 Test Notification - Debug",
            "message": "This is a test notification created for debugging purposes. If you can see this, the notification system is working correctly!",
            "notification_type": NotificationType.ANNOUNCEMENT,
            "priority": NotificationPriority.NORMAL, 
            "recipient_type": RecipientType.INDIVIDUAL,
            "recipient_config": {
                "student_ids": [str(student_uuid)]  # FIXED: Keep as string in config
            },
            "delivery_channels": ["in_app"],
            "category": "System Test"
        }
        
        notification = await service.create_notification(
            sender_id=sender_uuid,  # FIXED: Use UUID object
            sender_type=SenderType.TEACHER,
            notification_data=test_notification_data
        )
        
        return {
            "success": True,
            "notification_id": str(notification.id),
            "title": notification.title,
            "total_recipients": notification.total_recipients,
            "delivered_count": notification.delivered_count,
            "status": notification.status.value,
            "message": "Test notification created successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(f"Error creating test notification: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create test notification: {str(e)}")

        
    

@router.get("/debug/student-classes/{student_id}", dependencies=[Depends(require_super_admin)])
async def debug_student_classes(
    student_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug: Check student's class assignment (without enrollments table)"""
    try:
        # Check if student has class_id field
        student_class_sql = text("""
            SELECT 
                s.id,
                en.class_id,
                s.first_name,
                s.last_name,
                c.class_name,
                c.grade_level,
                c.section
            FROM members s
            LEFT JOIN enrollments en ON en.member_id = s.id AND en.status = 'active'
            LEFT JOIN classes c ON en.class_id = c.id
            WHERE s.id = :student_id
            AND s.tenant_id = :tenant_id
            AND s.is_deleted = false
            AND (s.profile->>'category') = 'student'
        """)
        
        result = await db.execute(student_class_sql, {"student_id": student_id, "tenant_id": tenant_id})
        student_data = result.fetchone()
        
        if not student_data:
            return {"error": "Student not found"}
        
        return {
            "student_id": student_id,
            "tenant_id": tenant_id,
            "student_name": f"{student_data[2]} {student_data[3]}",
            "class_id": str(student_data[1]) if student_data[1] else None,
            "class_name": student_data[4],
            "grade_level": student_data[5],
            "section": student_data[6]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")

@router.get("/debug/available-classes", dependencies=[Depends(require_super_admin)])
async def debug_available_classes(
    tenant_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug: Check what classes exist in the tenant (without enrollments)"""
    try:
        classes_sql = text("""
            SELECT 
                c.id,
                c.class_name,
                c.grade_level,
                c.section,
                c.status,
                COUNT(s.id) as student_count
            FROM classes c
            LEFT JOIN enrollments en ON en.class_id = c.id AND en.status = 'active'
            LEFT JOIN members s ON s.id = en.member_id AND s.status = 'active' AND s.is_deleted = false AND (s.profile->>'category') = 'student'
            WHERE c.tenant_id = :tenant_id
            AND c.is_deleted = false
            GROUP BY c.id, c.class_name, c.grade_level, c.section, c.status
            ORDER BY c.grade_level, c.section
        """)
        
        result = await db.execute(classes_sql, {"tenant_id": tenant_id})
        classes = result.fetchall()
        
        return {
            "tenant_id": tenant_id,
            "total_classes": len(classes),
            "classes": [
                {
                    "class_id": str(c[0]),
                    "class_name": c[1],
                    "grade_level": c[2],
                    "section": c[3],
                    "status": c[4],
                    "student_count": c[5]
                } for c in classes
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")

@router.get("/debug/archive-test/{user_id}", dependencies=[Depends(require_super_admin)])
async def debug_archive_test(
    user_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Debug: Test archive functionality"""
    try:
        # Check current archive status
        check_sql = text("""
            SELECT 
                nr.notification_id,
                nr.is_archived,
                n.title
            FROM notification_recipients nr
            JOIN notifications n ON nr.notification_id = n.id
            WHERE nr.recipient_id = :user_id
            AND n.tenant_id = :tenant_id
            AND nr.is_deleted = false
            ORDER BY n.created_at DESC
            LIMIT 5
        """)
        
        result = await db.execute(check_sql, {
            "user_id": user_id,
            "tenant_id": tenant_id
        })
        notifications = result.fetchall()
        
        return {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "notifications": [
                {
                    "notification_id": str(n[0]),
                    "is_archived": n[1],
                    "title": n[2]
                } for n in notifications
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")

@router.post("/debug/setup-archive-column", dependencies=[Depends(require_super_admin)])
async def setup_archive_column(
    db: AsyncSession = Depends(get_db)
):
    """Debug: Setup is_archived column if it doesn't exist"""
    try:
        # Check if column exists
        check_column_sql = text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'notification_recipients' 
            AND column_name = 'is_archived'
        """)
        
        result = await db.execute(check_column_sql)
        column_exists = result.fetchone()
        
        if column_exists:
            return {"message": "is_archived column already exists"}
        
        # Add the column
        add_column_sql = text("""
            ALTER TABLE notification_recipients 
            ADD COLUMN is_archived BOOLEAN DEFAULT FALSE
        """)
        
        await db.execute(add_column_sql)
        await db.commit()
        
        return {"message": "is_archived column added successfully"}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Setup failed: {str(e)}")

@router.get("/debug/check-archive-column", dependencies=[Depends(require_super_admin)])
async def check_archive_column(
    db: AsyncSession = Depends(get_db)
):
    """Debug: Check if is_archived column exists"""
    try:
        check_sql = text("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns 
            WHERE table_name = 'notification_recipients' 
            AND column_name = 'is_archived'
        """)
        
        result = await db.execute(check_sql)
        column_info = result.fetchone()
        
        if column_info:
            return {
                "exists": True,
                "column_name": column_info[0],
                "data_type": column_info[1],
                "default_value": column_info[2]
            }
        else:
            return {"exists": False}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Check failed: {str(e)}")