# app/models/tenant_specific/quiz.py
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey, Text, Enum, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...models.base import Base
import enum

# Association table for question-category many-to-many relationship
question_categories = Table(
    'question_categories',
    Base.metadata,
    Column('question_id', UUID(as_uuid=True), ForeignKey('questions.id'), primary_key=True),
    Column('category_id', UUID(as_uuid=True), ForeignKey('categories.id'), primary_key=True)
)

# Association table for quiz-class many-to-many relationship
quiz_classes = Table(
    'quiz_classes',
    Base.metadata,
    Column('quiz_id', UUID(as_uuid=True), ForeignKey('quizzes.id'), primary_key=True),
    Column('class_id', UUID(as_uuid=True), ForeignKey('classes.id'), primary_key=True)
)

class DifficultyLevel(enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

class QuestionType(enum.Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"
    ESSAY = "essay"

class TemplateType(enum.Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"
    ESSAY = "essay"

class Topic(Base):
    __tablename__ = "topics"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    description = Column(Text)
    subject = Column(String(50), nullable=False)
    grade_level = Column(Integer, nullable=False)
    
    # Relationships
    tenant = relationship("Tenant")
    questions = relationship("Question", back_populates="topic")
    quizzes = relationship("Quiz", back_populates="topic")

class Category(Base):
    __tablename__ = "categories"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    description = Column(Text)
    color = Column(String(7), default="#007bff")  # Hex color code
    
    # Relationships
    tenant = relationship("Tenant")
    questions = relationship("Question", secondary=question_categories, back_populates="categories")

class QuestionTemplate(Base):
    __tablename__ = "question_templates"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    description = Column(Text)
    template_type = Column(Enum(TemplateType), nullable=False)
    template_data = Column(JSON)  # Stores template structure
    
    # Relationships
    tenant = relationship("Tenant")

class QuestionVersion(Base):
    __tablename__ = "question_versions"
    
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    
    question_text = Column(Text, nullable=False)
    options = Column(JSON)
    correct_answer = Column(String(500), nullable=False)
    explanation = Column(Text)
    points = Column(Integer, default=1)
    
    changed_by = Column(UUID(as_uuid=True), nullable=True)  # User who made the change
    change_reason = Column(Text)
    
    # Relationships
    question = relationship("Question", back_populates="versions")

class Question(Base):
    __tablename__ = "questions"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    topic_id = Column(UUID(as_uuid=True), ForeignKey("topics.id"), nullable=False, index=True)
    
    question_text = Column(Text, nullable=False)
    question_type = Column(Enum(QuestionType, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    difficulty_level = Column(Enum(DifficultyLevel, values_callable=lambda obj: [e.value for e in obj]), default=DifficultyLevel.MEDIUM)
    
    # For multiple choice questions
    options = Column(JSON)  # {"A": "option1", "B": "option2", ...}
    correct_answer = Column(String(500), nullable=False)
    explanation = Column(Text)
    
    points = Column(Integer, default=1)
    time_limit = Column(Integer)  # in seconds
    version = Column(Integer, default=1)
    original_source = Column(String(100))
    import_batch_id = Column(UUID(as_uuid=True))
    
    # Relationships
    tenant = relationship("Tenant")
    topic = relationship("Topic", back_populates="questions")
    quiz_questions = relationship("QuizQuestion", back_populates="question")
    categories = relationship("Category", secondary=question_categories, back_populates="questions")
    versions = relationship("QuestionVersion", back_populates="question", cascade="all, delete-orphan")
    


class Quiz(Base):
    __tablename__ = "quizzes"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    topic_id = Column(UUID(as_uuid=True), ForeignKey("topics.id"), nullable=False, index=True)
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False, index=True)  # was teachers.id; now the owning members.id

    title = Column(String(200), nullable=False)
    description = Column(Text)
    instructions = Column(Text)
    
    total_questions = Column(Integer, nullable=False)
    total_points = Column(Integer, nullable=False)
    time_limit = Column(Integer)  # in minutes
    
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    
    is_active = Column(Boolean, default=True)
    allow_retakes = Column(Boolean, default=False)
    show_results_immediately = Column(Boolean, default=True)
    
    # Relationships
    tenant = relationship("Tenant")
    topic = relationship("Topic", back_populates="quizzes")
    teacher = relationship("Member")  # attr kept 'teacher'; the owning member (was Teacher)
    quiz_questions = relationship("QuizQuestion", back_populates="quiz")
    quiz_attempts = relationship("QuizAttempt", back_populates="quiz")

class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id"), nullable=False, index=True)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=False, index=True)
    
    order_number = Column(Integer, nullable=False)
    points = Column(Integer, default=1)
    
    # Relationships
    quiz = relationship("Quiz", back_populates="quiz_questions")
    question = relationship("Question", back_populates="quiz_questions")

class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id"), nullable=False, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False, index=True)  # was students.id; now the attempter's members.id

    attempt_number = Column(Integer, default=1)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)
    
    total_score = Column(Integer, default=0)
    max_score = Column(Integer, nullable=False)
    percentage = Column(Integer, default=0)
    
    is_completed = Column(Boolean, default=False)
    is_submitted = Column(Boolean, default=False)
    results_published = Column(Boolean, default=False)  # New field for teacher result publishing
    
    # Relationships
    tenant = relationship("Tenant")
    quiz = relationship("Quiz", back_populates="quiz_attempts")
    student = relationship("Member")  # attr kept 'student'; the attempter member (was Student)
    answers = relationship("QuizAnswer", back_populates="attempt")

class QuizAnswer(Base):
    __tablename__ = "quiz_answers"
    
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("quiz_attempts.id"), nullable=False, index=True)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"), nullable=False, index=True)
    
    student_answer = Column(Text)
    is_correct = Column(Boolean, default=False)
    points_earned = Column(Integer, default=0)
    time_taken = Column(Integer)  # in seconds
    
    # Relationships
    attempt = relationship("QuizAttempt", back_populates="answers")
    question = relationship("Question")