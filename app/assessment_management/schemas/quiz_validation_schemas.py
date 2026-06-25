# app/schemas/quiz_schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum
from ..models.quiz_question_models import DifficultyLevel, QuestionType

class TemplateType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"
    ESSAY = "essay"

# Category Schemas
class CategoryResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    color: str
    created_at: datetime

# Topic Schemas
class TopicCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    subject: str = Field(..., max_length=50)
    grade_level: int = Field(..., ge=1, le=12)

class TopicResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    subject: str
    grade_level: int
    created_at: datetime

# Question Schemas
class QuestionCreate(BaseModel):
    topic_id: UUID
    question_text: str
    question_type: QuestionType
    difficulty_level: DifficultyLevel = DifficultyLevel.MEDIUM
    options: Optional[Dict[str, str]] = None
    correct_answer: str
    explanation: Optional[str] = None
    points: int = Field(default=1, ge=1)
    time_limit: Optional[int] = None
    category_ids: Optional[List[UUID]] = None
    original_source: Optional[str] = None

class QuestionResponse(BaseModel):
    id: UUID
    topic_id: UUID
    question_text: str
    question_type: QuestionType
    difficulty_level: DifficultyLevel
    options: Optional[Dict[str, str]]
    correct_answer: str
    explanation: Optional[str]
    points: int
    time_limit: Optional[int]
    version: Optional[int] = None
    original_source: Optional[str] = None
    created_at: datetime

class QuestionForQuiz(BaseModel):
    id: UUID
    question_text: str
    question_type: QuestionType
    options: Optional[Dict[str, str]]
    points: int
    time_limit: Optional[int]

# Quiz Schemas
class QuizCreate(BaseModel):
    topic_id: UUID
    class_ids: Optional[List[UUID]] = None  # Support multiple classes
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    instructions: Optional[str] = None
    question_ids: List[UUID]
    time_limit: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    allow_retakes: bool = False
    show_results_immediately: bool = True

class QuizResponse(BaseModel):
    id: UUID
    topic_id: UUID
    class_ids: Optional[List[UUID]] = None
    teacher_id: UUID
    title: str
    description: Optional[str]
    instructions: Optional[str]
    total_questions: int
    total_points: int
    time_limit: Optional[int]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    is_active: bool
    allow_retakes: bool
    show_results_immediately: bool
    created_at: datetime

class QuizForStudent(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    instructions: Optional[str]
    total_questions: int
    total_points: int
    time_limit: Optional[int]
    questions: List[QuestionForQuiz]

# Quiz Attempt Schemas
class QuizAttemptStart(BaseModel):
    quiz_id: UUID

class QuizAnswerSubmit(BaseModel):
    question_id: UUID
    student_answer: str

class QuizAttemptSubmit(BaseModel):
    attempt_id: UUID
    answers: List[QuizAnswerSubmit]

class QuizAttemptResponse(BaseModel):
    id: UUID
    quiz_id: UUID
    student_id: UUID
    attempt_number: int
    start_time: datetime
    end_time: Optional[datetime]
    total_score: int
    max_score: int
    percentage: int
    is_completed: bool
    is_submitted: bool

class QuizResultResponse(BaseModel):
    attempt: QuizAttemptResponse
    quiz_title: str
    topic_name: str
    answers: List[Dict[str, Any]]

class QuizStatusUpdate(BaseModel):
    is_active: bool

class GradeShortAnswer(BaseModel):
    points_awarded: int = Field(..., ge=0)

class PublishResults(BaseModel):
    attempt_ids: List[UUID]  # List of attempt IDs to publish results for

class InlineQuestion(BaseModel):
    question_text: str
    question_type: QuestionType
    difficulty_level: DifficultyLevel = DifficultyLevel.MEDIUM
    options: Optional[Dict[str, str]] = None
    correct_answer: str
    explanation: Optional[str] = None
    points: int = Field(default=1, ge=1)

class QuizCreateWithQuestions(BaseModel):
    class_ids: Optional[List[UUID]] = None
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    instructions: Optional[str] = None
    questions: List[InlineQuestion]
    time_limit: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    allow_retakes: bool = False
    show_results_immediately: bool = True
    subject: str = Field(..., max_length=50)
    grade_level: Optional[int] = Field(None, ge=1, le=12)

class CategoryCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    color: str = Field(default="#007bff", pattern=r"^#[0-9A-Fa-f]{6}$")

# Question Template Schemas
class QuestionTemplateCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    template_type: TemplateType
    template_data: Dict[str, Any]

class QuestionTemplateResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    template_type: TemplateType
    template_data: Dict[str, Any]
    created_at: datetime

# Question Import/Export Schemas
class QuestionImportRow(BaseModel):
    topic_name: str
    subject: str
    grade_level: int
    question_text: str
    question_type: QuestionType
    difficulty_level: DifficultyLevel = DifficultyLevel.MEDIUM
    option_a: Optional[str] = None
    option_b: Optional[str] = None
    option_c: Optional[str] = None
    option_d: Optional[str] = None
    correct_answer: str
    explanation: Optional[str] = None
    points: int = 1
    categories: Optional[str] = None  # Comma-separated category names

class QuestionImportResult(BaseModel):
    total_rows: int
    successful_imports: int
    failed_imports: int
    errors: List[str]
    import_batch_id: UUID

class QuestionExportFilter(BaseModel):
    topic_ids: Optional[List[UUID]] = None
    category_ids: Optional[List[UUID]] = None
    difficulty_levels: Optional[List[DifficultyLevel]] = None
    question_types: Optional[List[QuestionType]] = None

# Question Version Schemas
class QuestionVersionResponse(BaseModel):
    id: UUID
    version_number: int
    question_text: str
    options: Optional[Dict[str, str]]
    correct_answer: str
    explanation: Optional[str]
    points: int
    changed_by: Optional[UUID]
    change_reason: Optional[str]
    created_at: datetime