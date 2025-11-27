# app/routers/chat/chat_router.py
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from ...core.database import get_db
from ...services.chat.chat_service import ChatService

# Pydantic Models
class SendMessageRequest(BaseModel):
    teacher_id: UUID
    student_id: UUID
    tenant_id: UUID
    message: str
    sender_type: str  # 'teacher' or 'student'

class ChatHistoryResponse(BaseModel):
    chat_room_id: str
    messages: List[dict]
    total_messages: int

router = APIRouter(prefix="/api/v1/chat", tags=["Chat System"])

@router.post("/send-message", response_model=dict)
async def send_message(
    request: SendMessageRequest,
    db: AsyncSession = Depends(get_db)
):
    """Send a message between teacher and student"""
    service = ChatService(db)
    
    try:
        # Get or create chat room
        chat_room = await service.get_or_create_chat_room(
            teacher_id=request.teacher_id,
            student_id=request.student_id,
            tenant_id=request.tenant_id
        )
        
        # Determine sender_id based on sender_type
        sender_id = request.teacher_id if request.sender_type == "teacher" else request.student_id
        
        # Send message
        message = await service.send_message(
            chat_room_id=chat_room.id,
            sender_id=sender_id,
            sender_type=request.sender_type,
            message=request.message
        )
        
        return {
            "message_id": str(message.id),
            "chat_room_id": str(chat_room.id),
            "message": "Message sent successfully",
            "timestamp": message.created_at.isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history/{chat_room_id}", response_model=dict)
async def get_chat_history(
    chat_room_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Get chat history for a specific chat room"""
    service = ChatService(db)
    
    try:
        messages = await service.get_chat_history(chat_room_id, limit, offset)
        
        formatted_messages = [
            {
                "id": str(msg.id),
                "sender_id": str(msg.sender_id),
                "sender_type": msg.sender_type,
                "message": msg.message,
                "is_read": msg.is_read,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
        
        return {
            "chat_room_id": str(chat_room_id),
            "messages": formatted_messages,
            "total_messages": len(formatted_messages),
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/student/{student_id}/chats", response_model=dict)
async def get_student_chats(
    student_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get all chat rooms for a student"""
    service = ChatService(db)
    
    try:
        chats = await service.get_student_chats(student_id, tenant_id)
        
        return {
            "student_id": str(student_id),
            "chats": chats,
            "total_chats": len(chats)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/teacher/{teacher_id}/chats", response_model=dict)
async def get_teacher_chats(
    teacher_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get all chat rooms for a teacher"""
    service = ChatService(db)
    
    try:
        chats = await service.get_teacher_chats(teacher_id, tenant_id)
        
        return {
            "teacher_id": str(teacher_id),
            "chats": chats,
            "total_chats": len(chats)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/teacher/{teacher_id}/available-students", response_model=dict)
async def get_available_students(
    teacher_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get all available students for a teacher to start chat with"""
    service = ChatService(db)
    
    try:
        students = await service.get_available_students(teacher_id, tenant_id)
        
        return {
            "teacher_id": str(teacher_id),
            "available_students": students,
            "total_students": len(students)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/student/{student_id}/available-teachers", response_model=dict)
async def get_available_teachers(
    student_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get all available teachers for a student to start chat with"""
    service = ChatService(db)
    
    try:
        teachers = await service.get_available_teachers(student_id, tenant_id)
        
        return {
            "student_id": str(student_id),
            "available_teachers": teachers,
            "total_teachers": len(teachers)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/mark-read/{chat_room_id}", response_model=dict)
async def mark_messages_as_read(
    chat_room_id: UUID,
    user_type: str = Query(..., regex="^(teacher|student)$"),
    db: AsyncSession = Depends(get_db)
):
    """Mark messages as read in a chat room"""
    service = ChatService(db)
    
    try:
        await service.mark_messages_as_read(chat_room_id, user_type)
        
        return {
            "message": "Messages marked as read",
            "chat_room_id": str(chat_room_id)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/room/{teacher_id}/{student_id}", response_model=dict)
async def get_or_create_chat_room(
    teacher_id: UUID,
    student_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get or create a chat room between teacher and student"""
    service = ChatService(db)
    
    try:
        chat_room = await service.get_or_create_chat_room(teacher_id, student_id, tenant_id)
        
        return {
            "chat_room_id": str(chat_room.id),
            "teacher_id": str(chat_room.teacher_id),
            "student_id": str(chat_room.student_id),
            "tenant_id": str(chat_room.tenant_id),
            "created_at": chat_room.created_at.isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))