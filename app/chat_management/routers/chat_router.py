# app/routers/chat/chat_router.py
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from ...core.database import get_db
from ...chat_management.services.chat_service import ChatService
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal


# Pydantic Models
class SendMessageRequest(BaseModel):
    teacher_id: UUID
    student_id: UUID
    tenant_id: UUID
    message: str
    sender_type: str  # ignored for auth — the real sender is the authenticated principal


class ChatHistoryResponse(BaseModel):
    chat_room_id: str
    messages: List[dict]
    total_messages: int


router = APIRouter(prefix="/api/v1/chat", tags=["Chat System"])


def _scope_tenant(principal: Principal, tenant_id: UUID) -> UUID:
    """Non-super-admins are bound to their own tenant; the client value is ignored."""
    if principal.is_super_admin or not principal.tenant_id:
        return tenant_id
    return UUID(str(principal.tenant_id))


def _assert_self_or_admin(principal: Principal, target_id) -> None:
    """Allow the target user themselves, or a tenant authority / super-admin (moderation).
    Notably a *teacher* may NOT enumerate a student's whole chat list, and vice-versa."""
    if principal.is_super_admin or principal.is_authority:
        return
    if str(principal.user_id) != str(target_id):
        raise HTTPException(status_code=403, detail="You can only access your own chats")


async def _assert_chat_member(db: AsyncSession, principal: Principal, chat_room_id) -> tuple:
    """Verify the principal may access a chat room: super-admin anywhere; authority within
    their own tenant (moderation); teacher/student only if a participant and same tenant."""
    row = (await db.execute(
        text("SELECT teacher_id, student_id, tenant_id FROM chat_rooms WHERE id = :rid"),
        {"rid": str(chat_room_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Chat room not found")
    teacher_id, student_id, room_tenant = str(row[0]), str(row[1]), str(row[2])
    if principal.is_super_admin:
        return teacher_id, student_id, room_tenant
    if principal.tenant_id and room_tenant != str(principal.tenant_id):
        raise HTTPException(status_code=403, detail="Cross-tenant chat access denied")
    if principal.is_authority:
        return teacher_id, student_id, room_tenant
    if str(principal.user_id) not in (teacher_id, student_id):
        raise HTTPException(status_code=403, detail="Not a participant of this chat")
    return teacher_id, student_id, room_tenant


@router.post("/send-message", response_model=dict)
async def send_message(
    request: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Send a message. The sender is ALWAYS the authenticated principal, so a caller can
    never impersonate another user or post into another tenant."""
    if principal.role == "teacher":
        sender_type = "teacher"
        if str(principal.user_id) != str(request.teacher_id):
            raise HTTPException(status_code=403, detail="You can only send as yourself")
    elif principal.role == "student":
        sender_type = "student"
        if str(principal.user_id) != str(request.student_id):
            raise HTTPException(status_code=403, detail="You can only send as yourself")
    else:
        raise HTTPException(status_code=403, detail="Only teachers and students can send chat messages")

    tenant_id = _scope_tenant(principal, request.tenant_id)
    service = ChatService(db)
    try:
        chat_room = await service.get_or_create_chat_room(
            teacher_id=request.teacher_id, student_id=request.student_id, tenant_id=tenant_id,
        )
        message = await service.send_message(
            chat_room_id=chat_room.id,
            sender_id=UUID(str(principal.user_id)),
            sender_type=sender_type,
            message=request.message,
        )
        return {
            "message_id": str(message.id),
            "chat_room_id": str(chat_room.id),
            "message": "Message sent successfully",
            "timestamp": message.created_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{chat_room_id}", response_model=dict)
async def get_chat_history(
    chat_room_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Get chat history — only a participant (or a tenant authority/super-admin)."""
    await _assert_chat_member(db, principal, chat_room_id)
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
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ]
        return {
            "chat_room_id": str(chat_room_id),
            "messages": formatted_messages,
            "total_messages": len(formatted_messages),
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/student/{student_id}/chats", response_model=dict)
async def get_student_chats(
    student_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """All chat rooms for a student (the student themselves, or a tenant admin)."""
    _assert_self_or_admin(principal, student_id)
    service = ChatService(db)
    try:
        chats = await service.get_student_chats(student_id, _scope_tenant(principal, tenant_id))
        return {"student_id": str(student_id), "chats": chats, "total_chats": len(chats)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/teacher/{teacher_id}/chats", response_model=dict)
async def get_teacher_chats(
    teacher_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """All chat rooms for a teacher (the teacher themselves, or a tenant admin)."""
    _assert_self_or_admin(principal, teacher_id)
    service = ChatService(db)
    try:
        chats = await service.get_teacher_chats(teacher_id, _scope_tenant(principal, tenant_id))
        return {"teacher_id": str(teacher_id), "chats": chats, "total_chats": len(chats)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/teacher/{teacher_id}/available-students", response_model=dict)
async def get_available_students(
    teacher_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Students a teacher can start a chat with (the teacher themselves, or a tenant admin)."""
    _assert_self_or_admin(principal, teacher_id)
    service = ChatService(db)
    try:
        students = await service.get_available_students(teacher_id, _scope_tenant(principal, tenant_id))
        return {"teacher_id": str(teacher_id), "available_students": students, "total_students": len(students)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/student/{student_id}/available-teachers", response_model=dict)
async def get_available_teachers(
    student_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Teachers a student can start a chat with (the student themselves, or a tenant admin)."""
    _assert_self_or_admin(principal, student_id)
    service = ChatService(db)
    try:
        teachers = await service.get_available_teachers(student_id, _scope_tenant(principal, tenant_id))
        return {"student_id": str(student_id), "available_teachers": teachers, "total_teachers": len(teachers)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mark-read/{chat_room_id}", response_model=dict)
async def mark_messages_as_read(
    chat_room_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Mark messages as read — only a participant; the reader side is the principal's role."""
    await _assert_chat_member(db, principal, chat_room_id)
    user_type = "teacher" if principal.role == "teacher" else "student"
    service = ChatService(db)
    try:
        await service.mark_messages_as_read(chat_room_id, user_type)
        return {"message": "Messages marked as read", "chat_room_id": str(chat_room_id)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/room/{teacher_id}/{student_id}", response_model=dict)
async def get_or_create_chat_room(
    teacher_id: UUID,
    student_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Get/create a chat room — the caller must be one of the two participants (or a tenant admin)."""
    if not (principal.is_super_admin or principal.is_authority):
        if str(principal.user_id) not in (str(teacher_id), str(student_id)):
            raise HTTPException(status_code=403, detail="You can only open your own chats")
    service = ChatService(db)
    try:
        chat_room = await service.get_or_create_chat_room(teacher_id, student_id, _scope_tenant(principal, tenant_id))
        return {
            "chat_room_id": str(chat_room.id),
            "teacher_id": str(chat_room.teacher_id),
            "student_id": str(chat_room.student_id),
            "tenant_id": str(chat_room.tenant_id),
            "created_at": chat_room.created_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
