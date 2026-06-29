# app/services/notification_service.py
from typing import List, Optional, Dict, Any, Union
from uuid import UUID
import uuid
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, desc, and_, or_
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from ...services.base_service import BaseService
from ..models.notification import (
    Notification, NotificationRecipient, NotificationTemplate, 
    NotificationDeliveryLog, NotificationPreference, NotificationGroup,
    NotificationSchedule, NotificationBatch,
    NotificationType, NotificationPriority, NotificationStatus, 
    DeliveryChannel, RecipientType, SenderType
)

import logging
logger = logging.getLogger(__name__)


class NotificationService(BaseService[Notification]):
    def __init__(self, db: AsyncSession):
        super().__init__(Notification, db)
    
    async def create_notification(
        self, 
        sender_id: UUID,
        sender_type: SenderType,
        notification_data: dict
    ) -> Notification:
        """Create and send notification - FIXED VERSION"""
        
        # Convert sender_type to string value for DB usage
        sender_type_str = sender_type.value if hasattr(sender_type, 'value') else str(sender_type)
        
        # Validate sender permissions
        permission_result = await self._validate_sender_permissions(sender_id, sender_type_str, notification_data)
        if not permission_result:
            raise HTTPException(status_code=403, detail="Insufficient permissions to send notification")
        
        # Convert enum values in notification_data to string
        processed_data = {}
        for key, value in notification_data.items():
            if hasattr(value, 'value'):
                processed_data[key] = value.value
            else:
                processed_data[key] = value
        
        # Create notification with string values
        notification = Notification(
            sender_id=sender_id,
            sender_type=sender_type_str,
            **processed_data
        )
        
        self.db.add(notification)
        await self.db.flush()  # Get ID without committing
        
        
        # Generate recipients
        recipients = await self._generate_recipients(notification)
        notification.total_recipients = len(recipients)
        
        # Batch insert recipients for better performance
        if len(recipients) > 100:  # Use bulk insert for large recipient lists
            await self._bulk_insert_recipients(notification.id, recipients)
        else:
            # Use individual inserts for small lists
            for recipient_data in recipients:
                recipient = NotificationRecipient(
                    notification_id=notification.id,
                    tenant_id=recipient_data["tenant_id"],
                    recipient_id=recipient_data["recipient_id"],
                    recipient_type=recipient_data["recipient_type"],
                    recipient_name=recipient_data["recipient_name"],
                    recipient_email=recipient_data.get("recipient_email"),
                    recipient_phone=recipient_data.get("recipient_phone"),
                    status=NotificationStatus.DELIVERED.value,
                    delivered_at=datetime.utcnow(),
                )
                self.db.add(recipient)
        
        # Update notification status and counts
        notification.status = NotificationStatus.SENT.value
        notification.sent_at = datetime.utcnow()
        notification.delivered_count = len(recipients)
        
        await self.db.commit()
        await self.db.refresh(notification)
        
        return notification
    
    # MAIN METHODS THAT YOUR FLUTTER APP NEEDS
    
    async def get_notifications_for_user(
        self,
        user_id: UUID,
        user_type: str,
        tenant_id: UUID,
        notification_type: Optional[str] = None,
        status: Optional[str] = None,
        unread_only: bool = False,
        include_archived: bool = False,
        limit: int = 50
    ) -> List[dict]:
        """Get notifications for a specific user (student/teacher) - FIXED VERSION"""
        
        try:
            # Convert UUID to string for comparison
            user_id_str = str(user_id)
            tenant_id_str = str(tenant_id)
            
            # Base query to get notifications for the user
            base_where = """
                WHERE nr.recipient_id = :user_id 
                AND nr.recipient_type = :user_type 
                AND n.tenant_id = :tenant_id 
                AND n.is_deleted = false 
                AND nr.is_deleted = false
            """
            
            params = {
                "user_id": user_id_str,
                "user_type": user_type,
                "tenant_id": tenant_id_str
            }
            
            # Add archive filter
            if not include_archived:
                base_where += " AND nr.is_archived = false"
            
            # Add additional filters
            if notification_type:
                base_where += " AND n.notification_type = :notification_type"
                params["notification_type"] = notification_type
            
            if status:
                base_where += " AND n.status = :status"
                params["status"] = status
            
            if unread_only:
                base_where += " AND nr.read_at IS NULL"
            
            # Main query with sender name
            notifications_sql = text(f"""
                SELECT 
                    n.id,
                    n.tenant_id,
                    n.sender_id,
                    n.sender_type,
                    n.title,
                    n.message,
                    n.short_message,
                    n.notification_type,
                    n.priority,
                    n.recipient_type,
                    n.recipient_config,
                    n.delivery_channels,
                    n.scheduled_at,
                    n.expires_at,
                    n.attachments,
                    n.action_url,
                    n.action_text,
                    n.category,
                    n.tags,
                    n.academic_year,
                    n.term,
                    n.status,
                    n.sent_at,
                    n.created_at,
                    n.updated_at,
                    nr.read_at,
                    CASE WHEN nr.read_at IS NULL THEN false ELSE true END as is_read,
                    CASE 
                        WHEN n.sender_type = 'school_authority' THEN CONCAT(sa.first_name, ' ', sa.last_name)
                        WHEN n.sender_type = 'teacher' THEN CONCAT(
                            COALESCE(t.first_name, ''),
                            ' ',
                            COALESCE(t.last_name, '')
                        )
                        ELSE 'System'
                    END as sender_name
                FROM notifications n
                JOIN notification_recipients nr ON n.id = nr.notification_id
                LEFT JOIN school_authorities sa ON n.sender_id = sa.id AND n.sender_type = 'school_authority'
                LEFT JOIN members t ON n.sender_id = t.id AND n.sender_type = 'teacher'
                {base_where}
                ORDER BY n.created_at DESC
                LIMIT :limit
            """)
            
            params["limit"] = limit
            
            result = await self.db.execute(notifications_sql, params)
            rows = result.fetchall()
            
            logger.debug(f"Found {len(rows)} notifications for user")
            
            notifications = []
            for row in rows:
                notification = {
                    "id": str(row[0]),
                    "tenant_id": str(row[1]),
                    "sender_id": str(row[2]),
                    "sender_type": row[3],
                    "sender_name": row[27].strip() if row[27] else "Unknown",
                    "title": row[4],
                    "message": row[5],
                    "short_message": row[6],
                    "notification_type": row[7],
                    "priority": row[8],
                    "recipient_type": row[9],
                    "recipient_config": row[10],
                    "delivery_channels": row[11],
                    "scheduled_at": row[12].isoformat() if row[12] else None,
                    "expires_at": row[13].isoformat() if row[13] else None,
                    "attachments": row[14],
                    "action_url": row[15],
                    "action_text": row[16],
                    "category": row[17],
                    "tags": row[18],
                    "academic_year": row[19],
                    "term": row[20],
                    "status": row[21],
                    "sent_at": row[22].isoformat() if row[22] else None,
                    "created_at": row[23].isoformat() if row[23] else None,
                    "updated_at": row[24].isoformat() if row[24] else None,
                    "read_at": row[25].isoformat() if row[25] else None,
                    "is_read": row[26],
                    "is_archived": False  # These are non-archived notifications
                }
                notifications.append(notification)
            
            return notifications
            
        except Exception as e:
            logger.debug(f"Error getting notifications: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get user notifications: {str(e)}")

    async def mark_notification_as_read(
        self,
        notification_id: UUID,
        user_id: UUID
    ) -> dict:
        """
        Mark a specific notification as read for a user, with correct enum and proper error handling.
        """
        try:
            now = datetime.utcnow()
            # Use proper enum value for status
            update_sql = text("""
                UPDATE notification_recipients
                SET read_at = :read_at,
                    status = :status,
                    updated_at = :updated_at
                WHERE notification_id = :notification_id
                  AND recipient_id = :user_id
                  AND read_at IS NULL
                  AND is_deleted = false
            """)
            result = await self.db.execute(
                update_sql,
                {
                    "read_at": now,
                    "status": NotificationStatus.READ.value,
                    "updated_at": now,
                    "notification_id": str(notification_id),
                    "user_id": str(user_id)
                }
            )

            if result.rowcount == 0:
                # Could not update any row => not found/invalid/already read
                raise HTTPException(status_code=404, detail="Notification not found or already read")

            # Update read count for notification
            update_count_sql = text("""
                UPDATE notifications
                SET read_count = (
                    SELECT COUNT(*)
                    FROM notification_recipients nr
                    WHERE nr.notification_id = notifications.id
                      AND nr.read_at IS NOT NULL
                      AND nr.is_deleted = false
                ),
                updated_at = :updated_at
                WHERE id = :notification_id
            """)
            await self.db.execute(
                update_count_sql,
                {
                    "updated_at": now,
                    "notification_id": str(notification_id)
                }
            )

            await self.db.commit()
            return {
                "message": "Notification marked as read",
                "notification_id": str(notification_id),
                "user_id": str(user_id),
                "read_at": now.isoformat()
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            # Explicit error: this will give detail in the 400/500 response!
            raise HTTPException(status_code=500, detail=f"Failed to mark notification as read: {str(e)}")
    # FIXED RECIPIENT GENERATION METHOD
    async def _generate_recipients(self, notification: Notification) -> List[Dict[str, Any]]:
        """Generate list of recipients based on notification configuration - FIXED VERSION"""
        
        logger.debug(f"Generating recipients for notification {notification.id}")
        logger.debug(f"Recipient type: {notification.recipient_type}")
        logger.debug(f"Recipient config: {notification.recipient_config}")
        logger.debug(f"Tenant ID: {notification.tenant_id}")
        
        recipients = []
        recipient_type = notification.recipient_type
        recipient_config = notification.recipient_config or {}
        
        try:
            if recipient_type == RecipientType.INDIVIDUAL.value:
                # Individual recipients
                student_ids = recipient_config.get("student_ids", [])
                teacher_ids = recipient_config.get("teacher_ids", [])
                school_authority_ids = recipient_config.get("school_authority_ids", [])
                
                logger.debug(f"Individual - Student IDs: {student_ids}")
                logger.debug(f"Individual - Teacher IDs: {teacher_ids}")
                logger.debug(f"Individual - School Authority IDs: {school_authority_ids}")
                
                # Get student details
                if student_ids:
                    student_sql = text("""
                        SELECT id, first_name, last_name, email, phone
                        FROM (SELECT * FROM members WHERE (profile->>'category') = 'student') AS students
                        WHERE id = ANY(:student_ids)
                        AND tenant_id = :tenant_id
                        AND is_deleted = false
                    """)
                    
                    result = await self.db.execute(
                        student_sql,
                        {"student_ids": [str(sid) for sid in student_ids], "tenant_id": str(notification.tenant_id)}
                    )
                    
                    student_rows = result.fetchall()
                    logger.debug(f"Found {len(student_rows)} students")
                    
                    for row in student_rows:
                        recipients.append({
                            "tenant_id": str(notification.tenant_id),
                            "recipient_id": str(row[0]),
                            "recipient_type": "student",
                            "recipient_name": f"{row[1]} {row[2]}",
                            "recipient_email": row[3],
                            "recipient_phone": row[4]
                        })
                
                # Get teacher details
                if teacher_ids:
                    teacher_sql = text("""
                        SELECT id, 
                               first_name as first_name,
                               last_name as last_name,
                               email as email,
                               phone as phone
                        FROM (SELECT * FROM members WHERE (profile->>'category') IS DISTINCT FROM 'student') AS teachers
                        WHERE id = ANY(:teacher_ids)
                        AND tenant_id = :tenant_id
                        AND is_deleted = false
                    """)
                    
                    result = await self.db.execute(
                        teacher_sql,
                        {"teacher_ids": [str(tid) for tid in teacher_ids], "tenant_id": str(notification.tenant_id)}
                    )
                    
                    teacher_rows = result.fetchall()
                    logger.debug(f"Found {len(teacher_rows)} teachers")
                    
                    for row in teacher_rows:
                        recipients.append({
                            "tenant_id": str(notification.tenant_id),
                            "recipient_id": str(row[0]),
                            "recipient_type": "teacher",
                            "recipient_name": f"{row[1] or ''} {row[2] or ''}".strip(),
                            "recipient_email": row[3],
                            "recipient_phone": row[4]
                        })
                
                # Get school authority details
                if school_authority_ids:
                    sa_sql = text("""
                        SELECT id, first_name, last_name, email, phone
                        FROM school_authorities
                        WHERE id = ANY(:sa_ids)
                        AND tenant_id = :tenant_id
                        AND is_deleted = false
                    """)
                    
                    result = await self.db.execute(
                        sa_sql,
                        {"sa_ids": [str(said) for said in school_authority_ids], "tenant_id": str(notification.tenant_id)}
                    )
                    
                    sa_rows = result.fetchall()
                    logger.debug(f"Found {len(sa_rows)} school authorities")
                    
                    for row in sa_rows:
                        recipients.append({
                            "tenant_id": str(notification.tenant_id),
                            "recipient_id": str(row[0]),
                            "recipient_type": "school_authority",
                            "recipient_name": f"{row[1] or ''} {row[2] or ''}".strip(),
                            "recipient_email": row[3],
                            "recipient_phone": row[4]
                        })
            
            elif recipient_type == RecipientType.ALL_STUDENTS.value:
                logger.debug("Getting all students")
                # All students in tenant
                all_students_sql = text("""
                    SELECT id, first_name, last_name, email, phone
                    FROM (SELECT * FROM members WHERE (profile->>'category') = 'student') AS students
                    WHERE tenant_id = :tenant_id
                    AND status = 'active'
                    AND is_deleted = false
                """)
                
                result = await self.db.execute(all_students_sql, {"tenant_id": str(notification.tenant_id)})
                student_rows = result.fetchall()
                logger.debug(f"Found {len(student_rows)} active students")
                
                for row in student_rows:
                    recipients.append({
                        "tenant_id": str(notification.tenant_id),
                        "recipient_id": str(row[0]),
                        "recipient_type": "student",
                        "recipient_name": f"{row[1]} {row[2]}",
                        "recipient_email": row[3],
                        "recipient_phone": row[4]
                    })
            
            elif recipient_type == RecipientType.ALL_TEACHERS.value:
                logger.debug("Getting all teachers")
                # All teachers in tenant
                all_teachers_sql = text("""
                    SELECT id,
                           first_name as first_name,
                           last_name as last_name,
                           email as email,
                           phone as phone
                    FROM (SELECT * FROM members WHERE (profile->>'category') IS DISTINCT FROM 'student') AS teachers
                    WHERE tenant_id = :tenant_id
                    AND status = 'active'
                    AND is_deleted = false
                """)
                
                result = await self.db.execute(all_teachers_sql, {"tenant_id": str(notification.tenant_id)})
                teacher_rows = result.fetchall()
                logger.debug(f"Found {len(teacher_rows)} active teachers")
                
                for row in teacher_rows:
                    recipients.append({
                        "tenant_id": str(notification.tenant_id),
                        "recipient_id": str(row[0]),
                        "recipient_type": "teacher",
                        "recipient_name": f"{row[1] or ''} {row[2] or ''}".strip(),
                        "recipient_email": row[3],
                        "recipient_phone": row[4]
                    })
            
            elif recipient_type == RecipientType.ALL_SCHOOL_AUTHORITIES.value:
                logger.debug("Getting all school authorities")
                # All school authorities in tenant
                all_sa_sql = text("""
                    SELECT id, first_name, last_name, email, phone
                    FROM school_authorities
                    WHERE tenant_id = :tenant_id
                    AND status = 'active'
                    AND is_deleted = false
                """)
                
                result = await self.db.execute(all_sa_sql, {"tenant_id": str(notification.tenant_id)})
                sa_rows = result.fetchall()
                logger.debug(f"Found {len(sa_rows)} active school authorities")
                
                for row in sa_rows:
                    recipients.append({
                        "tenant_id": str(notification.tenant_id),
                        "recipient_id": str(row[0]),
                        "recipient_type": "school_authority",
                        "recipient_name": f"{row[1] or ''} {row[2] or ''}".strip(),
                        "recipient_email": row[3],
                        "recipient_phone": row[4]
                    })
            
            elif recipient_type == RecipientType.CLASS.value:
                # Class notifications - supports single class, multiple classes, and grade-based
                class_ids = recipient_config.get("class_ids", [])
                grades = recipient_config.get("grades", [])
                
                # Handle single class_id format
                if "class_id" in recipient_config:
                    class_ids = [recipient_config["class_id"]]
                
                logger.debug(f"Class - Class IDs: {class_ids}")
                logger.debug(f"Class - Grades: {grades}")
                
                # Handle specific class IDs
                if class_ids:
                    target = recipient_config.get("target", "students")
                    
                    for class_id in class_ids:
                        logger.debug(f"Looking for {target} in class {class_id}")
                        
                        if target in ["students", "all"]:
                            # Get students through enrollments table
                            class_students_sql = text("""
                                SELECT s.id, s.first_name, s.last_name, s.email, s.phone
                                FROM (SELECT * FROM members WHERE (profile->>'category') = 'student') s
                                JOIN enrollments e ON s.id = e.member_id
                                WHERE e.class_id = :class_id
                                AND s.tenant_id = :tenant_id
                                AND s.is_deleted = false
                                AND s.status = 'active'
                                AND e.status = 'active'
                            """)
                            
                            result = await self.db.execute(
                                class_students_sql,
                                {"class_id": str(class_id), "tenant_id": str(notification.tenant_id)}
                            )
                            rows = result.fetchall()
                            
                            logger.debug(f"Found {len(rows)} students in class {class_id}")
                            for row in rows:
                                recipients.append({
                                    "tenant_id": str(notification.tenant_id),
                                    "recipient_id": str(row[0]),
                                    "recipient_type": "student",
                                    "recipient_name": f"{row[1]} {row[2]}",
                                    "recipient_email": row[3],
                                    "recipient_phone": row[4]
                                })
                        
                        if target in ["teachers", "all"]:
                            # Get teachers assigned to class
                            class_teachers_sql = text("""
                                SELECT DISTINCT t.id,
                                       t.first_name as first_name,
                                       t.last_name as last_name,
                                       t.email as email,
                                       t.phone as phone
                                FROM (SELECT * FROM members WHERE (profile->>'category') IS DISTINCT FROM 'student') t
                                JOIN classes c ON c.assigned_teachers::jsonb @> ('[{"teacher_id":"' || t.id || '"}]')::jsonb
                                WHERE c.id = :class_id
                                AND t.tenant_id = :tenant_id
                                AND t.is_deleted = false
                                AND t.status = 'active'
                                AND c.is_deleted = false
                            """)
                            
                            result = await self.db.execute(
                                class_teachers_sql,
                                {"class_id": str(class_id), "tenant_id": str(notification.tenant_id)}
                            )
                            teacher_rows = result.fetchall()
                            
                            logger.debug(f"Found {len(teacher_rows)} teachers in class {class_id}")
                            for row in teacher_rows:
                                recipients.append({
                                    "tenant_id": str(notification.tenant_id),
                                    "recipient_id": str(row[0]),
                                    "recipient_type": "teacher",
                                    "recipient_name": f"{row[1] or ''} {row[2] or ''}".strip(),
                                    "recipient_email": row[3],
                                    "recipient_phone": row[4]
                                })
                
                # Handle grade-based notifications
                elif grades:
                    logger.debug(f"Looking for students in grades: {grades}")
                    
                    grade_students_sql = text("""
                        SELECT s.id, s.first_name, s.last_name, s.email, s.phone
                        FROM (SELECT * FROM members WHERE (profile->>'category') = 'student') s
                        JOIN enrollments e ON s.id = e.member_id
                        JOIN classes c ON e.class_id = c.id
                        WHERE c.grade_level = ANY(:grades)
                        AND s.tenant_id = :tenant_id
                        AND s.is_deleted = false
                        AND s.status = 'active'
                        AND e.status = 'active'
                        AND c.is_deleted = false
                    """)
                    
                    result = await self.db.execute(
                        grade_students_sql,
                        {"grades": grades, "tenant_id": str(notification.tenant_id)}
                    )
                    rows = result.fetchall()
                    
                    logger.debug(f"Found {len(rows)} students in grades {grades}")
                    for row in rows:
                        recipients.append({
                            "tenant_id": str(notification.tenant_id),
                            "recipient_id": str(row[0]),
                            "recipient_type": "student",
                            "recipient_name": f"{row[1]} {row[2]}",
                            "recipient_email": row[3],
                            "recipient_phone": row[4]
                        })
            
            elif recipient_type == RecipientType.GRADE.value:
                # Students in specific grades
                grade_levels = recipient_config.get("grade_levels", [])
                
                logger.debug(f"Grade - Grade levels: {grade_levels}")
                
                if grade_levels:
                    try:
                        grade_students_sql = text("""
                            SELECT id, first_name, last_name, email, phone
                            FROM (SELECT * FROM members WHERE (profile->>'category') = 'student') AS students
                            WHERE (profile->>'grade_level')::int = ANY(:grade_levels)
                            AND tenant_id = :tenant_id
                            AND status = 'active'
                            AND is_deleted = false
                        """)
                        
                        result = await self.db.execute(
                            grade_students_sql,
                            {"grade_levels": grade_levels, "tenant_id": str(notification.tenant_id)}
                        )
                        
                        grade_rows = result.fetchall()
                        logger.debug(f"Found {len(grade_rows)} students in grades")
                        
                        for row in grade_rows:
                            recipients.append({
                                "tenant_id": str(notification.tenant_id),
                                "recipient_id": str(row[0]),
                                "recipient_type": "student",
                                "recipient_name": f"{row[1]} {row[2]}",
                                "recipient_email": row[3],
                                "recipient_phone": row[4]
                            })
                    except Exception as e:
                        logger.debug(f"Grade query failed: {str(e)}")
            
            elif recipient_type == "all_institution":
                logger.debug("Getting all institution members (optimized for large lists)")
                
                # Use single optimized query to get all recipients
                all_recipients_sql = text("""
                    SELECT 'student' as type, id, first_name, last_name, email, phone
                    FROM (SELECT * FROM members WHERE (profile->>'category') = 'student') AS students
                    WHERE tenant_id = :tenant_id AND status = 'active' AND is_deleted = false
                    
                    UNION ALL
                    
                    SELECT 'teacher' as type, id,
                           first_name as first_name,
                           last_name as last_name,
                           email as email,
                           phone as phone
                    FROM (SELECT * FROM members WHERE (profile->>'category') IS DISTINCT FROM 'student') AS teachers
                    WHERE tenant_id = :tenant_id AND status = 'active' AND is_deleted = false
                    
                    UNION ALL
                    
                    SELECT 'school_authority' as type, id, first_name, last_name, email, phone
                    FROM school_authorities
                    WHERE tenant_id = :tenant_id AND status = 'active' AND is_deleted = false
                    
                    LIMIT 2000
                """)
                
                result = await self.db.execute(all_recipients_sql, {"tenant_id": str(notification.tenant_id)})
                all_rows = result.fetchall()
                logger.debug(f"Found {len(all_rows)} total institution members")
                
                for row in all_rows:
                    recipients.append({
                        "tenant_id": str(notification.tenant_id),
                        "recipient_id": str(row[1]),
                        "recipient_type": row[0],
                        "recipient_name": f"{row[2] or ''} {row[3] or ''}".strip(),
                        "recipient_email": row[4],
                        "recipient_phone": row[5]
                    })
            
            logger.debug(f"Generated {len(recipients)} total recipients")
            if len(recipients) == 0:
                logger.warning(f"No recipients found for {recipient_type} with config {recipient_config}")
                if recipient_type == RecipientType.CLASS.value:
                    logger.debug(f"HINT - No students found for class. Check if class_id exists and has enrolled students")
            for i, recipient in enumerate(recipients):
                logger.debug(f"Recipient {i+1}: {recipient['recipient_name']} ({recipient['recipient_id']})")
            
            return recipients
            
        except Exception as e:
            logger.debug(f"Error in _generate_recipients: {str(e)}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            # Log error details for debugging
            # Log error for debugging
            raise e
    
    async def _bulk_insert_recipients(self, notification_id: UUID, recipients: List[Dict[str, Any]]) -> None:
        """Bulk insert recipients using raw SQL for better performance"""
        if not recipients:
            return
        
        # Prepare bulk insert data
        now = datetime.utcnow()
        values = []
        
        for recipient in recipients:
            values.append({
                'notification_id': str(notification_id),
                'tenant_id': recipient['tenant_id'],
                'recipient_id': recipient['recipient_id'],
                'recipient_type': recipient['recipient_type'],
                'recipient_name': recipient['recipient_name'],
                'recipient_email': recipient.get('recipient_email'),
                'recipient_phone': recipient.get('recipient_phone'),
                'status': NotificationStatus.DELIVERED.value,
                'delivered_at': now,
                'created_at': now,
                'updated_at': now,
                'is_deleted': False
            })
        
        # Batch insert in chunks of 500
        chunk_size = 500
        for i in range(0, len(values), chunk_size):
            chunk = values[i:i + chunk_size]
            
            bulk_insert_sql = text("""
                INSERT INTO notification_recipients (
                    notification_id, tenant_id, recipient_id, recipient_type,
                    recipient_name, recipient_email, recipient_phone, status,
                    delivered_at, created_at, updated_at, is_deleted
                ) VALUES 
            """ + ",".join([
                "(:notification_id_{i}, :tenant_id_{i}, :recipient_id_{i}, :recipient_type_{i}, "
                ":recipient_name_{i}, :recipient_email_{i}, :recipient_phone_{i}, :status_{i}, "
                ":delivered_at_{i}, :created_at_{i}, :updated_at_{i}, :is_deleted_{i})"
                .format(i=idx) for idx in range(len(chunk))
            ]))
            
            # Flatten parameters
            params = {}
            for idx, item in enumerate(chunk):
                for key, value in item.items():
                    params[f"{key}_{idx}"] = value
            
            await self.db.execute(bulk_insert_sql, params)
    
    # Keep all existing validation and utility methods
    async def _validate_sender_permissions(
            self, 
            sender_id: UUID, 
            sender_type: str, 
            notification_data: dict
        ) -> bool:
            """Validate if sender has permission to send notification"""
            
            recipient_type = notification_data.get("recipient_type")
            
            logger.debug(f"Validating permissions - sender_type: {sender_type}, recipient_type: {recipient_type}")
            
            if sender_type in ['school_authority', 'admin']:
                logger.debug(f"School authority/admin validation")
                return True
            
            elif sender_type == 'teacher':
                logger.debug(f"Teacher validation - allowing all_students")
                return True
            
            logger.debug(f"No permission - sender_type: {sender_type}")
            return False

    async def _verify_teacher_assignment(self, teacher_id: UUID, notification_data: dict) -> bool:
        """Verify teacher is assigned to the target class/students"""
        # For now, return True - implement based on your specific requirements
        return True
