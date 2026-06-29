# app/services/chat/websocket_manager.py
from typing import Dict, List, Set
from uuid import UUID
from fastapi import WebSocket
import json
import logging

logger = logging.getLogger(__name__)

class WebSocketManager:
    def __init__(self):
        # Store active connections: {user_id: {websocket, user_type, tenant_id}}
        self.active_connections: Dict[str, Dict] = {}
        # Store chat room subscriptions: {chat_room_id: {user_ids}}
        self.room_subscriptions: Dict[str, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: UUID, user_type: str, tenant_id: UUID):
        """Accept websocket connection and store user info"""
        await websocket.accept()
        user_key = str(user_id)
        
        self.active_connections[user_key] = {
            "websocket": websocket,
            "user_type": user_type,
            "tenant_id": str(tenant_id),
            "user_id": user_key
        }
        
        logger.info(f"User {user_key} ({user_type}) connected")
        
        # Send connection confirmation
        await self.send_personal_message({
            "type": "connection_status",
            "status": "connected",
            "user_id": user_key,
            "user_type": user_type
        }, user_id)
    
    def disconnect(self, user_id: UUID):
        """Remove user connection and clean up subscriptions"""
        user_key = str(user_id)
        
        if user_key in self.active_connections:
            # Remove from all room subscriptions
            for room_id, subscribers in self.room_subscriptions.items():
                subscribers.discard(user_key)
            
            # Clean up empty rooms
            self.room_subscriptions = {
                room_id: subscribers 
                for room_id, subscribers in self.room_subscriptions.items() 
                if subscribers
            }
            
            del self.active_connections[user_key]
            logger.info(f"User {user_key} disconnected")
    
    async def join_chat_room(self, user_id: UUID, chat_room_id: UUID):
        """Subscribe user to a chat room"""
        user_key = str(user_id)
        room_key = str(chat_room_id)
        
        if user_key not in self.active_connections:
            logger.warning(f"User {user_key} not connected, cannot join room {room_key}")
            return
        
        if room_key not in self.room_subscriptions:
            self.room_subscriptions[room_key] = set()
        
        self.room_subscriptions[room_key].add(user_key)
        logger.info(f"User {user_key} joined room {room_key}. Room now has: {self.room_subscriptions[room_key]}")
        
        await self.send_personal_message({
            "type": "room_joined",
            "chat_room_id": room_key
        }, user_id)
    
    async def leave_chat_room(self, user_id: UUID, chat_room_id: UUID):
        """Unsubscribe user from a chat room"""
        user_key = str(user_id)
        room_key = str(chat_room_id)
        
        if room_key in self.room_subscriptions:
            self.room_subscriptions[room_key].discard(user_key)
            
            if not self.room_subscriptions[room_key]:
                del self.room_subscriptions[room_key]
    
    async def send_personal_message(self, message: dict, user_id: UUID):
        """Send message to specific user"""
        user_key = str(user_id)
        
        if user_key in self.active_connections:
            websocket = self.active_connections[user_key]["websocket"]
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error sending message to {user_key}: {e}")
                self.disconnect(user_id)
    
    async def broadcast_to_room(self, message: dict, chat_room_id: UUID, exclude_user: UUID = None):
        """Send message to all users in a chat room"""
        room_key = str(chat_room_id)
        exclude_key = str(exclude_user) if exclude_user else None
        
        logger.info(f"Broadcasting to room {room_key}, exclude: {exclude_key}")
        logger.info(f"Room subscriptions: {self.room_subscriptions.get(room_key, set())}")
        logger.info(f"Active connections: {list(self.active_connections.keys())}")
        
        if room_key not in self.room_subscriptions:
            logger.warning(f"Room {room_key} has no subscriptions")
            return
        
        disconnected_users = []
        sent_count = 0
        
        for user_key in self.room_subscriptions[room_key]:
            if user_key == exclude_key:
                logger.info(f"Skipping excluded user {user_key}")
                continue
                
            if user_key in self.active_connections:
                websocket = self.active_connections[user_key]["websocket"]
                try:
                    await websocket.send_text(json.dumps(message))
                    sent_count += 1
                    logger.info(f"Message sent to user {user_key}")
                except Exception as e:
                    logger.error(f"Error broadcasting to {user_key}: {e}")
                    disconnected_users.append(UUID(user_key))
            else:
                logger.warning(f"User {user_key} in room but not connected")
        
        logger.info(f"Broadcast complete: sent to {sent_count} users")
        
        # Clean up disconnected users
        for user_id in disconnected_users:
            self.disconnect(user_id)
    
    def get_online_users_in_room(self, chat_room_id: UUID) -> List[str]:
        """Get list of online users in a chat room"""
        room_key = str(chat_room_id)
        
        if room_key not in self.room_subscriptions:
            return []
        
        return [
            user_key for user_key in self.room_subscriptions[room_key]
            if user_key in self.active_connections
        ]
    
    def is_user_online(self, user_id: UUID) -> bool:
        """Check if user is online"""
        return str(user_id) in self.active_connections

# Global WebSocket manager instance
websocket_manager = WebSocketManager()