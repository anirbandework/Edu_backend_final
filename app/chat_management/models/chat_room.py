# app/models/chat/chat_room.py
from sqlalchemy import Column, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...models.base import Base

class ChatRoom(Base):
    __tablename__ = "chat_rooms"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    # Both parties are now members (dynamic model); column names kept, they hold members.id.
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False, index=True)

    # Relationships — two FKs to members, so each needs explicit foreign_keys.
    teacher = relationship("Member", foreign_keys=[teacher_id])
    student = relationship("Member", foreign_keys=[student_id])
    messages = relationship("ChatMessage", back_populates="chat_room", cascade="all, delete-orphan")
    
    # Composite index for unique teacher-student pair per tenant
    __table_args__ = (
        Index('idx_chat_room_unique', 'tenant_id', 'teacher_id', 'student_id', unique=True),
    )