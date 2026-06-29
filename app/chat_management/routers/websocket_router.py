# app/routers/chat/websocket_router.py
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
import json
import logging
from ...core.database import get_db
from ...chat_management.services.chat_service import ChatService
from ...chat_management.services.websocket_manager import websocket_manager
from ...auth_rbac.security.tokens import decode_token, TokenError, ACCESS

logger = logging.getLogger(__name__)
router = APIRouter()

# WebSocket policy-violation close code (RFC 6455).
WS_POLICY_VIOLATION = 1008


@router.websocket("/ws/chat")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    """WebSocket endpoint for real-time chat.

    The connection is authenticated from the JWT `token` query param — identity
    (user_id, user_type, tenant_id) is derived from the token, never from the client.
    A bearer header can't be sent on a browser WebSocket, so the token is passed as a
    query param (use wss:// in production so it isn't exposed in plaintext)."""

    # 1) Authenticate BEFORE accepting the socket.
    try:
        payload = decode_token(token, expected_type=ACCESS)
    except TokenError:
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    role = payload.get("role", "")
    tenant = payload.get("tenant_id")
    if role not in ("teacher", "student") or not tenant:
        # Only the two chat participant roles may open a chat socket.
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    try:
        user_id = UUID(str(payload["sub"]))
        tenant_id = UUID(str(tenant))
    except (ValueError, KeyError, TypeError):
        await websocket.close(code=WS_POLICY_VIOLATION)
        return
    user_type = role  # 'teacher' | 'student'

    await websocket_manager.connect(websocket, user_id, user_type, tenant_id)
    service = ChatService(db)

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            message_type = message_data.get("type")

            if message_type == "join_room":
                chat_room_id = UUID(message_data.get("chat_room_id"))
                await websocket_manager.join_chat_room(user_id, chat_room_id)

            elif message_type == "leave_room":
                chat_room_id = UUID(message_data.get("chat_room_id"))
                await websocket_manager.leave_chat_room(user_id, chat_room_id)

            elif message_type == "send_message":
                try:
                    teacher_id = UUID(message_data.get("teacher_id"))
                    student_id = UUID(message_data.get("student_id"))
                    message_text = message_data.get("message")

                    # The authenticated user must be a participant of this room — they can
                    # only post into a teacher<->student pairing that includes themselves.
                    if str(user_id) not in (str(teacher_id), str(student_id)):
                        raise PermissionError("Not a participant of this chat")

                    # Tenant is bound to the token, never the client.
                    chat_room = await service.get_or_create_chat_room(
                        teacher_id=teacher_id, student_id=student_id, tenant_id=tenant_id,
                    )

                    # Sender is always the authenticated principal.
                    message = await service.send_message(
                        chat_room_id=chat_room.id, sender_id=user_id,
                        sender_type=user_type, message=message_text,
                    )

                    broadcast_data = {
                        "type": "new_message",
                        "message_id": str(message.id),
                        "chat_room_id": str(chat_room.id),
                        "sender_id": str(user_id),
                        "sender_type": user_type,
                        "message": message_text,
                        "timestamp": message.created_at.isoformat(),
                    }
                    await websocket_manager.broadcast_to_room(broadcast_data, chat_room.id, exclude_user=user_id)
                    await websocket_manager.send_personal_message({
                        "type": "message_sent",
                        "message_id": str(message.id),
                        "timestamp": message.created_at.isoformat(),
                    }, user_id)

                except Exception as e:
                    logger.error(f"Error sending message: {e}")
                    await websocket_manager.send_personal_message({
                        "type": "error", "message": "Failed to send message"
                    }, user_id)

            elif message_type == "mark_read":
                try:
                    chat_room_id = UUID(message_data.get("chat_room_id"))
                    await service.mark_messages_as_read(chat_room_id, user_type)
                    await websocket_manager.broadcast_to_room({
                        "type": "messages_read",
                        "chat_room_id": str(chat_room_id),
                        "reader_type": user_type,
                    }, chat_room_id, exclude_user=user_id)
                except Exception as e:
                    logger.error(f"Error marking messages as read: {e}")

            elif message_type == "typing":
                try:
                    chat_room_id = UUID(message_data.get("chat_room_id"))
                    is_typing = message_data.get("is_typing", False)
                    await websocket_manager.broadcast_to_room({
                        "type": "typing_indicator",
                        "chat_room_id": str(chat_room_id),
                        "user_id": str(user_id),
                        "user_type": user_type,
                        "is_typing": is_typing,
                    }, chat_room_id, exclude_user=user_id)
                except Exception as e:
                    logger.error(f"Error handling typing indicator: {e}")

            else:
                await websocket_manager.send_personal_message({
                    "type": "error", "message": f"Unknown message type: {message_type}"
                }, user_id)

    except WebSocketDisconnect:
        websocket_manager.disconnect(user_id)
        logger.info(f"User {user_id} disconnected from chat")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        websocket_manager.disconnect(user_id)
