# app/models/chat/chat_message.py
from sqlalchemy import Column, String, Text, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...models.base import Base

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    chat_room_id = Column(UUID(as_uuid=True), ForeignKey("chat_rooms.id"), nullable=False, index=True)
    sender_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sender_type = Column(String(10), nullable=False)  # 'teacher' or 'student'
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    chat_room = relationship("ChatRoom", back_populates="messages")
    
    # Index for efficient queries
    __table_args__ = (
        Index('idx_chat_message_room_time', 'chat_room_id', 'created_at'),
        Index('idx_chat_message_unread', 'chat_room_id', 'is_read'),
    )