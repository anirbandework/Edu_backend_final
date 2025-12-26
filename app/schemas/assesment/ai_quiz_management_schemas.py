# AI Quiz Management Schemas
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from .quiz_validation_schemas import QuestionType, DifficultyLevel

# AI Quiz Creation
class AIQuizCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    instructions: Optional[str] = None
    class_ids: List[UUID]
    subject: str = Field(..., max_length=100)
    grade_level: int = Field(..., ge=1, le=12)
    
    # AI Generation Parameters
    question_types: List[QuestionType] = Field(default=["multiple_choice"])
    difficulty_distribution: Dict[str, int] = Field(default={"easy": 30, "medium": 50, "hard": 20})
    total_questions: int = Field(default=10, ge=5, le=50)
    total_points: int = Field(default=100, ge=10, le=500)
    time_limit: Optional[int] = None  # minutes
    
    # Learning objectives for AI
    learning_objectives: Optional[str] = None
    topics_to_cover: Optional[List[str]] = None
    
    # Quiz settings
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    allow_retakes: bool = False
    show_results_immediately: bool = False

class AIQuizResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    total_questions: int
    total_points: int
    time_limit: Optional[int]
    is_active: bool
    created_at: datetime
    generation_metadata: Dict[str, Any]

# AI Quiz Templates
class AIQuizTemplateRequest(BaseModel):
    template_name: str = Field(..., max_length=100)
    subject: str = Field(..., max_length=50)
    grade_level: int = Field(..., ge=1, le=12)
    quiz_type: str = Field(default="assessment")  # "assessment", "practice", "exam"
    duration_minutes: int = Field(default=30, ge=10, le=180)
    difficulty_level: DifficultyLevel = DifficultyLevel.MEDIUM

class AIQuizTemplateResponse(BaseModel):
    template_id: UUID
    template_name: str
    suggested_questions: int
    estimated_duration: int
    difficulty_breakdown: Dict[str, int]
    recommended_settings: Dict[str, Any]

# Student AI Quiz Interaction
class AIQuizForStudent(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    instructions: Optional[str]
    total_questions: int
    total_points: int
    time_limit: Optional[int]
    questions: List[Dict[str, Any]]
    ai_hints_enabled: bool = True

class AIQuizAttemptStart(BaseModel):
    quiz_id: UUID
    use_ai_assistance: bool = Field(default=True)

class AIQuizHintRequest(BaseModel):
    attempt_id: UUID
    question_id: UUID
    student_answer_so_far: Optional[str] = None

class AIQuizHintResponse(BaseModel):
    hint_text: str
    hint_type: str  # "concept", "approach", "example"
    confidence_level: float
    remaining_hints: int

# AI Quiz Results and Analytics
class AIQuizResultsResponse(BaseModel):
    attempt_id: UUID
    quiz_title: str
    total_score: int
    max_score: int
    percentage: int
    time_taken: int
    ai_analysis: Dict[str, Any]
    strengths: List[str]
    weaknesses: List[str]
    recommendations: List[str]
    detailed_feedback: Dict[str, Any]

class AIQuizHistoryResponse(BaseModel):
    student_id: UUID
    quizzes: List[Dict[str, Any]]
    overall_performance: Dict[str, Any]
    learning_progress: Dict[str, Any]
    ai_insights: List[str]

# Teacher AI Quiz Management
class TeacherAIQuizDashboard(BaseModel):
    teacher_id: UUID
    active_quizzes: List[Dict[str, Any]]
    pending_reviews: int
    ai_generated_insights: List[str]
    class_performance_summary: Dict[str, Any]

class AIQuizClassAnalytics(BaseModel):
    quiz_id: UUID
    class_id: UUID
    participation_rate: float
    average_score: float
    completion_rate: float
    ai_insights: Dict[str, Any]
    struggling_students: List[Dict[str, Any]]
    top_performers: List[Dict[str, Any]]
    question_analysis: Dict[str, Any]