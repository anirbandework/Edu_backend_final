# app/schemas/ai_schemas.py

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import date
from .quiz_validation_schemas import QuestionType, DifficultyLevel

# AI Question Generation
class QuestionGenerationRequest(BaseModel):
    topic: str = Field(..., max_length=200)
    topic_id: Optional[UUID] = None  # Added topic_id for database lookup
    subject: str = Field(..., max_length=100)
    grade_level: int = Field(..., ge=1, le=12)
    question_type: QuestionType
    difficulty: DifficultyLevel
    count: int = Field(default=5, ge=1, le=20)
    learning_objectives: Optional[str] = None

class GeneratedQuestion(BaseModel):
    question_text: str
    options: Optional[Dict[str, str]] = None
    correct_answer: str
    explanation: str
    points: int

class QuestionGenerationResponse(BaseModel):
    questions: List[GeneratedQuestion]
    topic: str
    topic_name: Optional[str] = None  # Added topic name
    subject: str
    grade_level: int
    total_generated: int
    generation_metadata: Optional[Dict[str, Any]] = None  # Added metadata

# Smart Quiz Assembly
class QuizAssemblyRequest(BaseModel):
    topic_id: UUID
    target_duration: Optional[int] = None  # minutes
    difficulty_distribution: Optional[Dict[str, int]] = None  # {"easy": 2, "medium": 3, "hard": 1}
    total_questions: Optional[int] = None
    total_points: Optional[int] = None

class QuizAssemblyResponse(BaseModel):
    selected_questions: List[UUID]
    suggested_order: List[UUID]
    time_per_question: Dict[str, int]
    difficulty_balance: Dict[str, int]
    total_points: int
    estimated_duration: int
    recommendations: str
    question_details: Optional[Dict[str, Any]] = None
    topic_name: Optional[str] = None  # Added topic name
    quiz_title: Optional[str] = None  # Added quiz title suggestion

# AI Grading
class SubjectiveGradingRequest(BaseModel):
    question_text: str
    correct_answer: str
    student_answer: str
    max_points: int
    rubric: Optional[str] = None

class SubjectiveGradingResponse(BaseModel):
    points_earned: int
    percentage: float
    feedback: str
    strengths: List[str]
    improvements: List[str]
    is_correct: bool

# Performance Analytics
class PerformanceAnalysisRequest(BaseModel):
    quiz_id: UUID
    class_id: Optional[UUID] = None

class StudentPerformance(BaseModel):
    student_id: UUID
    student_name: str
    score: int
    percentage: float
    time_taken: Optional[int] = None
    answers: List[Dict[str, Any]]

class QuestionAnalysis(BaseModel):
    question_id: UUID
    question_text: str
    correct_rate: float
    average_time: Optional[float] = None
    common_mistakes: List[str]

class PerformanceAnalysisResponse(BaseModel):
    overall_stats: Dict[str, Any]
    weak_areas: List[str]
    strong_areas: List[str]
    at_risk_students: List[Dict[str, Any]]  # Now includes student names
    top_performers: List[Dict[str, Any]]    # Now includes student names
    recommendations: List[str]
    question_analysis: Dict[str, Any]
    class_average: float
    pass_rate: float
    quiz_name: Optional[str] = None  # Added quiz name
    class_name: Optional[str] = None  # Added class name
    topic_name: Optional[str] = None  # Added topic name

# Student Learning Insights
class StudentInsightsRequest(BaseModel):
    student_id: UUID
    subject: Optional[str] = None
    time_period: Optional[str] = None  # "last_month", "last_quarter", etc.

class StudentInsightsResponse(BaseModel):
    student_id: UUID
    student_name: Optional[str] = None
    overall_performance: Dict[str, Any]
    subject_breakdown: Dict[str, Any]
    learning_trends: List[str]
    strengths: List[str]
    weaknesses: List[str]
    recommendations: List[str]
    progress_score: float

# Study Recommendations
class StudyRecommendationRequest(BaseModel):
    student_id: UUID
    subject: Optional[str] = None
    study_goals: Optional[str] = None
    available_time_hours: Optional[int] = None

class StudyRecommendationResponse(BaseModel):
    student_id: UUID
    student_name: Optional[str] = None
    priority_topics: List[Dict[str, Any]]
    study_activities: List[Dict[str, Any]]
    weekly_schedule: Dict[str, List[str]]
    practice_recommendations: List[str]
    milestones: List[Dict[str, Any]]
    estimated_improvement: str

# Weakness Analysis
class WeaknessAnalysisRequest(BaseModel):
    student_id: UUID
    subject: Optional[str] = None
    analysis_depth: Optional[str] = "detailed"  # "basic", "detailed", "comprehensive"

class WeaknessAnalysisResponse(BaseModel):
    student_id: UUID
    student_name: Optional[str] = None
    knowledge_gaps: List[Dict[str, Any]]
    learning_patterns: List[str]
    skill_deficiencies: List[str]
    conceptual_misunderstandings: List[str]
    remediation_strategies: List[Dict[str, Any]]
    priority_order: List[str]

# Exam Preparation
class ExamPrepRequest(BaseModel):
    student_id: UUID
    exam_date: Optional[date] = None
    exam_subjects: Optional[List[str]] = None
    exam_type: Optional[str] = None  # "midterm", "final", "standardized"
    daily_study_hours: Optional[int] = None

class ExamPrepResponse(BaseModel):
    student_id: UUID
    student_name: Optional[str] = None
    exam_date: Optional[date]
    study_schedule: Dict[str, Any]
    topic_priorities: List[Dict[str, Any]]
    practice_plan: Dict[str, Any]
    revision_strategy: Dict[str, Any]
    success_metrics: List[str]
    estimated_readiness: float

# Performance Prediction
class PerformancePredictionRequest(BaseModel):
    student_id: UUID
    assessment_subject: Optional[str] = None
    assessment_type: Optional[str] = None
    assessment_date: Optional[date] = None

class PerformancePredictionResponse(BaseModel):
    student_id: UUID
    student_name: Optional[str] = None
    predicted_score: float
    confidence_level: float
    performance_trend: str
    risk_factors: List[str]
    improvement_potential: float
    recommendations: List[str]

# Report Generation
class ReportGenerationRequest(BaseModel):
    student_id: Optional[UUID] = None
    class_id: Optional[UUID] = None
    report_type: str  # "student_progress", "class_summary", "parent_report"
    time_period: Optional[str] = None
    include_recommendations: bool = True

class ReportGenerationResponse(BaseModel):
    report_id: str
    report_type: str
    generated_content: Dict[str, Any]
    summary: str
    recommendations: List[str]
    charts_data: Optional[Dict[str, Any]] = None
    report_title: Optional[str] = None  # Added report title
    student_name: Optional[str] = None  # Added student name for student reports
    class_name: Optional[str] = None  # Added class name for class reports
    generated_for: Optional[str] = None  # Added context (e.g., "John Doe - Mathematics Progress")

# Intervention Recommendations
class InterventionRequest(BaseModel):
    student_ids: List[UUID]
    risk_threshold: Optional[float] = 0.6  # Students below this performance level
    intervention_type: Optional[str] = "academic"  # "academic", "behavioral", "both"

class InterventionResponse(BaseModel):
    at_risk_students: List[Dict[str, Any]]
    intervention_strategies: List[Dict[str, Any]]
    priority_actions: List[str]
    monitoring_plan: Dict[str, Any]
    success_indicators: List[str]

# Batch Operations
class BatchQuestionGeneration(BaseModel):
    requests: List[QuestionGenerationRequest]

class BatchQuestionResponse(BaseModel):
    results: List[QuestionGenerationResponse]
    total_questions_generated: int
    success_count: int
    failed_count: int