from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from ...models.base import Base

class BookChunk(Base):
    __tablename__ = "book_chunks"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    subject = Column(String(50), nullable=False)
    
    chapter_name = Column(String(200), nullable=False)
    chunk_title = Column(String(200), nullable=False)
    chunk_number = Column(Integer, nullable=False)
    
    content = Column(Text, nullable=False)
    summary = Column(Text)
    key_concepts = Column(JSON)  # ["concept1", "concept2"]
    
    difficulty_level = Column(String(20), default="medium")
    estimated_time = Column(Integer)  # minutes
    
    # AI generated metadata
    learning_objectives = Column(JSON)
    prerequisite_concepts = Column(JSON)
    
class CBSESamplePaper(Base):
    __tablename__ = "cbse_sample_papers"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    subject = Column(String(50), nullable=False)
    
    paper_title = Column(String(200), nullable=False)
    paper_code = Column(String(10), nullable=False)  # 002, 085, 041, etc.
    duration_hours = Column(Integer, default=3)
    theory_marks = Column(Integer, default=80)
    internal_marks = Column(Integer, default=20)
    
    instructions = Column(Text)
    sections = Column(JSON)  # Section-wise structure
    
    is_official_pattern = Column(Boolean, default=True)
    academic_year = Column(String(10), default="2025-26")

class PaperSection(Base):
    __tablename__ = "paper_sections"
    
    paper_id = Column(UUID(as_uuid=True), ForeignKey("cbse_sample_papers.id"), nullable=False)
    section_type = Column(String(20), nullable=False)
    
    section_name = Column(String(100), nullable=False)
    total_marks = Column(Integer, nullable=False)
    question_count = Column(Integer, nullable=False)
    
    description = Column(Text)
    question_pattern = Column(JSON)  # MCQ, SA, LA mix details
    
    # Relationships removed to avoid circular imports

class SectionQuestion(Base):
    __tablename__ = "section_questions"
    
    section_id = Column(UUID(as_uuid=True), ForeignKey("paper_sections.id"), nullable=False)
    question_number = Column(String(10), nullable=False)  # Q1, Q2, etc.
    
    question_text = Column(Text, nullable=False)
    question_type = Column(String(20), nullable=False)  # MCQ, SA, LA, etc.
    marks = Column(Integer, nullable=False)
    
    options = Column(JSON)  # For MCQ
    correct_answer = Column(Text)
    marking_scheme = Column(Text)
    
    # Relationships removed to avoid circular imports