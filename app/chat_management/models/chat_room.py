# app/models/chat/chat_room.py
from sqlalchemy import Column, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...models.base import Base

class ChatRoom(Base):
    __tablename__ = "chat_rooms"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=False, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True)
    
    # Relationships
    teacher = relationship("Teacher")
    student = relationship("Student")
    messages = relationship("ChatMessage", back_populates="chat_room", cascade="all, delete-orphan")
    
    # Composite index for unique teacher-student pair per tenant
    __table_args__ = (
        Index('idx_chat_room_unique', 'tenant_id', 'teacher_id', 'student_id', unique=True),
    )