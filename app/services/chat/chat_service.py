# app/services/chat/chat_service_fixed.py
from typing import List, Optional, Dict
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func, text
from ..base_service import BaseService
from ...models.chat.chat_room import ChatRoom
from ...models.chat.chat_message import ChatMessage

class ChatService(BaseService[ChatRoom]):
    def __init__(self, db: AsyncSession):
        super().__init__(ChatRoom, db)
    
    async def get_or_create_chat_room(self, teacher_id: UUID, student_id: UUID, tenant_id: UUID) -> ChatRoom:
        """Get existing chat room or create new one"""
        stmt = select(ChatRoom).where(
            and_(
                ChatRoom.teacher_id == teacher_id,
                ChatRoom.student_id == student_id,
                ChatRoom.tenant_id == tenant_id,
                ChatRoom.is_deleted == False
            )
        )
        result = await self.db.execute(stmt)
        chat_room = result.scalar_one_or_none()
        
        if not chat_room:
            chat_room = ChatRoom(
                teacher_id=teacher_id,
                student_id=student_id,
                tenant_id=tenant_id
            )
            self.db.add(chat_room)
            await self.db.commit()
            await self.db.refresh(chat_room)
        
        return chat_room
    
    async def send_message(self, chat_room_id: UUID, sender_id: UUID, sender_type: str, message: str) -> ChatMessage:
        """Send a message in chat room"""
        chat_message = ChatMessage(
            chat_room_id=chat_room_id,
            sender_id=sender_id,
            sender_type=sender_type,
            message=message
        )
        self.db.add(chat_message)
        await self.db.commit()
        await self.db.refresh(chat_message)
        return chat_message
    
    async def get_chat_history(self, chat_room_id: UUID, limit: int = 50, offset: int = 0) -> List[ChatMessage]:
        """Get chat history for a room"""
        stmt = select(ChatMessage).where(
            and_(
                ChatMessage.chat_room_id == chat_room_id,
                ChatMessage.is_deleted == False
            )
        ).order_by(desc(ChatMessage.created_at)).offset(offset).limit(limit)
        
        result = await self.db.execute(stmt)
        return list(reversed(result.scalars().all()))
    
    async def get_available_teachers(self, student_id: UUID, tenant_id: UUID) -> List[Dict]:
        """Get all available teachers for a student to chat with"""
        try:
            from ...models.tenant_specific.teacher import Teacher
            from .websocket_manager import websocket_manager
            
            stmt = select(Teacher).where(
                and_(
                    Teacher.tenant_id == tenant_id,
                    Teacher.is_deleted == False
                )
            )
            result = await self.db.execute(stmt)
            teachers = result.scalars().all()
            
            return [
                {
                    "id": str(teacher.id),
                    "name": f"{teacher.first_name or ''} {teacher.last_name or ''}".strip(),
                    "email": teacher.email or "",
                    "subject": getattr(teacher, 'subject_specialization', None) or "",
                    "is_online": websocket_manager.is_user_online(teacher.id)
                }
                for teacher in teachers
            ]
        except Exception as e:
            return []
    
    async def get_available_students(self, teacher_id: UUID, tenant_id: UUID) -> List[Dict]:
        """Get all available students for a teacher to chat with"""
        try:
            from ...models.tenant_specific.student import Student
            from .websocket_manager import websocket_manager
            
            stmt = select(Student).where(
                and_(
                    Student.tenant_id == tenant_id,
                    Student.is_deleted == False
                )
            )
            result = await self.db.execute(stmt)
            students = result.scalars().all()
            
            return [
                {
                    "id": str(student.id),
                    "name": f"{student.first_name or ''} {student.last_name or ''}".strip(),
                    "email": student.email or "",
                    "student_id": getattr(student, 'student_id', None) or "",
                    "class_name": getattr(student, 'class_name', None),
                    "is_online": websocket_manager.is_user_online(student.id)
                }
                for student in students
            ]
        except Exception as e:
            return []
    
    async def get_student_chats(self, student_id: UUID, tenant_id: UUID) -> List[Dict]:
        """Get all chat rooms for a student with last message and unread count"""
        try:
            from ...models.tenant_specific.teacher import Teacher
            
            # Get chat rooms with teacher info
            stmt = select(ChatRoom, Teacher).join(
                Teacher, ChatRoom.teacher_id == Teacher.id
            ).where(
                and_(
                    ChatRoom.student_id == student_id,
                    ChatRoom.tenant_id == tenant_id,
                    ChatRoom.is_deleted == False
                )
            )
            result = await self.db.execute(stmt)
            chat_rooms = result.all()
            
            if not chat_rooms:
                return []
            
            chats = []
            for chat_room, teacher in chat_rooms:
                try:
                    # Get last message
                    last_msg_stmt = select(ChatMessage).where(
                        and_(
                            ChatMessage.chat_room_id == chat_room.id,
                            ChatMessage.is_deleted == False
                        )
                    ).order_by(desc(ChatMessage.created_at)).limit(1)
                    last_msg_result = await self.db.execute(last_msg_stmt)
                    last_message = last_msg_result.scalar_one_or_none()
                    
                    # Get unread count (messages from teacher that student hasn't read)
                    unread_stmt = select(func.count(ChatMessage.id)).where(
                        and_(
                            ChatMessage.chat_room_id == chat_room.id,
                            ChatMessage.sender_type == "teacher",
                            ChatMessage.is_read == False,
                            ChatMessage.is_deleted == False
                        )
                    )
                    unread_result = await self.db.execute(unread_stmt)
                    unread_count = unread_result.scalar() or 0
                    
                    from .websocket_manager import websocket_manager
                    
                    chat_data = {
                        "chat_room_id": str(chat_room.id),
                        "teacher": {
                            "id": str(teacher.id),
                            "name": f"{teacher.first_name or ''} {teacher.last_name or ''}".strip(),
                            "email": teacher.email or "",
                            "subject": getattr(teacher, 'subject_specialization', None) or "",
                            "is_online": websocket_manager.is_user_online(teacher.id)
                        },
                        "unread_count": unread_count
                    }
                    
                    if last_message:
                        chat_data["last_message"] = {
                            "message": last_message.message,
                            "sender_type": last_message.sender_type,
                            "created_at": last_message.created_at.isoformat()
                        }
                    else:
                        chat_data["last_message"] = None
                        
                    chats.append(chat_data)
                except Exception as e:
                    # Skip this chat room if there's an error
                    continue
            
            # Sort by last message time (most recent first)
            chats.sort(key=lambda x: x["last_message"]["created_at"] if x["last_message"] else "1970-01-01T00:00:00", reverse=True)
            return chats
        except Exception as e:
            # Return empty list if there's any error
            return []
    
    async def get_teacher_chats(self, teacher_id: UUID, tenant_id: UUID) -> List[Dict]:
        """Get all chat rooms for a teacher with last message and unread count"""
        try:
            from ...models.tenant_specific.student import Student
            
            # Get chat rooms with student info
            stmt = select(ChatRoom, Student).join(
                Student, ChatRoom.student_id == Student.id
            ).where(
                and_(
                    ChatRoom.teacher_id == teacher_id,
                    ChatRoom.tenant_id == tenant_id,
                    ChatRoom.is_deleted == False
                )
            )
            result = await self.db.execute(stmt)
            chat_rooms = result.all()
            
            if not chat_rooms:
                return []
            
            chats = []
            for chat_room, student in chat_rooms:
                try:
                    # Get last message
                    last_msg_stmt = select(ChatMessage).where(
                        and_(
                            ChatMessage.chat_room_id == chat_room.id,
                            ChatMessage.is_deleted == False
                        )
                    ).order_by(desc(ChatMessage.created_at)).limit(1)
                    last_msg_result = await self.db.execute(last_msg_stmt)
                    last_message = last_msg_result.scalar_one_or_none()
                    
                    # Get unread count (messages from student that teacher hasn't read)
                    unread_stmt = select(func.count(ChatMessage.id)).where(
                        and_(
                            ChatMessage.chat_room_id == chat_room.id,
                            ChatMessage.sender_type == "student",
                            ChatMessage.is_read == False,
                            ChatMessage.is_deleted == False
                        )
                    )
                    unread_result = await self.db.execute(unread_stmt)
                    unread_count = unread_result.scalar() or 0
                    
                    from .websocket_manager import websocket_manager
                    
                    chat_data = {
                        "chat_room_id": str(chat_room.id),
                        "student": {
                            "id": str(student.id),
                            "name": f"{student.first_name or ''} {student.last_name or ''}".strip(),
                            "email": student.email or "",
                            "student_id": getattr(student, 'student_id', None) or "",
                            "is_online": websocket_manager.is_user_online(student.id)
                        },
                        "unread_count": unread_count
                    }
                    
                    if last_message:
                        chat_data["last_message"] = {
                            "message": last_message.message,
                            "sender_type": last_message.sender_type,
                            "created_at": last_message.created_at.isoformat()
                        }
                    else:
                        chat_data["last_message"] = None
                        
                    chats.append(chat_data)
                except Exception as e:
                    # Skip this chat room if there's an error
                    continue
            
            # Sort by last message time (most recent first)
            chats.sort(key=lambda x: x["last_message"]["created_at"] if x["last_message"] else "1970-01-01T00:00:00", reverse=True)
            return chats
        except Exception as e:
            # Return empty list if there's any error
            return []
    
    async def mark_messages_as_read(self, chat_room_id: UUID, user_type: str):
        """Mark messages as read for opposite sender type"""
        opposite_type = "teacher" if user_type == "student" else "student"
        
        from sqlalchemy import update
        stmt = update(ChatMessage).where(
            and_(
                ChatMessage.chat_room_id == chat_room_id,
                ChatMessage.sender_type == opposite_type,
                ChatMessage.is_read == False
            )
        ).values(is_read=True)
        
        await self.db.execute(stmt)
        await self.db.commit()