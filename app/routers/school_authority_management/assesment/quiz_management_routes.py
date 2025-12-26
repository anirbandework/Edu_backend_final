# app/routers/quiz.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.services.assesment.quiz_management_service import QuizService
from app.core.rate_limiter import rate_limiter
from app.schemas.assesment.quiz_validation_schemas import (
    TopicCreate, TopicResponse, QuestionCreate, QuestionResponse,
    QuizCreate, QuizResponse, QuizForStudent, QuizAttemptStart,
    QuizAttemptSubmit, QuizAttemptResponse, QuizResultResponse, QuizStatusUpdate,
    QuizCreateWithQuestions, GradeShortAnswer, PublishResults
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quiz", tags=["Quiz Management"])
quiz_service = QuizService()

# Topic endpoints
@router.post("/topics", response_model=TopicResponse)
async def create_topic(
    topic_data: TopicCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None  # This should come from authentication
):
    """Create a new topic for quizzes."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    topic = await quiz_service.create_topic(db, topic_data, tenant_id)
    return topic

@router.get("/topics", response_model=List[TopicResponse])
async def get_topics(
    subject: Optional[str] = None,
    grade_level: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None
):
    """Get all topics, optionally filtered by subject and grade level."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    # Cache key for topics
    from app.core.cache import cache_service
    cache_key = f"topics:{tenant_id}:{subject}:{grade_level}"
    
    # Try cache first
    cached_topics = await cache_service.get(cache_key)
    if cached_topics:
        return cached_topics
    
    topics = await quiz_service.get_topics(db, tenant_id, subject, grade_level)
    
    # Cache for 5 minutes
    await cache_service.set(cache_key, topics, ttl=300)
    return topics

# Question endpoints
@router.post("/questions", response_model=QuestionResponse)
async def create_question(
    question_data: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None
):
    """Create a new question for a topic."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    question = await quiz_service.create_question(db, question_data, tenant_id)
    return question

@router.get("/topics/{topic_id}/questions", response_model=List[QuestionResponse])
async def get_questions_by_topic(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None
):
    """Get all questions for a specific topic."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    questions = await quiz_service.get_questions_by_topic(db, tenant_id, topic_id)
    return questions

# Quiz endpoints
@router.post("/quizzes", response_model=QuizResponse)
async def create_quiz(
    quiz_data: QuizCreate,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,  # This should come from authentication
    tenant_id: UUID = None
):
    """Create a new quiz."""
    if not tenant_id or not teacher_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Teacher ID required")
    
    quiz = await quiz_service.create_quiz(db, quiz_data, teacher_id, tenant_id)
    return quiz

@router.get("/quizzes/{quiz_id}/student", response_model=QuizForStudent)
async def get_quiz_for_student(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None
):
    """Get quiz details for student (without correct answers)."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    quiz = await quiz_service.get_quiz_for_student(db, quiz_id, tenant_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # Format for student view (remove correct answers)
    questions = []
    for quiz_question in sorted(quiz.quiz_questions, key=lambda x: x.order_number):
        question = quiz_question.question
        questions.append({
            "id": question.id,
            "question_text": question.question_text,
            "question_type": question.question_type,
            "options": question.options,
            "points": quiz_question.points,
            "time_limit": question.time_limit
        })
    
    return {
        "id": quiz.id,
        "title": quiz.title,
        "description": quiz.description,
        "instructions": quiz.instructions,
        "total_questions": quiz.total_questions,
        "total_points": quiz.total_points,
        "time_limit": quiz.time_limit,
        "questions": questions
    }

# Quiz Attempt endpoints
@router.post("/attempts/start", response_model=QuizAttemptResponse)
async def start_quiz_attempt(
    attempt_data: QuizAttemptStart,
    db: AsyncSession = Depends(get_db),
    student_id: UUID = None,  # This should come from authentication
    tenant_id: UUID = None
):
    """Start a new quiz attempt for a student."""
    if not tenant_id or not student_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Student ID required")
    
    attempt = await quiz_service.start_quiz_attempt(db, student_id, attempt_data.quiz_id, tenant_id)
    return attempt

@router.post("/attempts/submit", response_model=QuizAttemptResponse)
async def submit_quiz_attempt(
    attempt_data: QuizAttemptSubmit,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None
):
    """Submit a completed quiz attempt."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    try:
        attempt = await quiz_service.submit_quiz_attempt(db, attempt_data, tenant_id)
        return attempt
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/students/{student_id}/available-quizzes")
async def get_student_available_quizzes(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None
):
    """Get available quizzes for a student based on their class."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    quizzes = await quiz_service.get_student_available_quizzes(db, student_id, tenant_id)
    return quizzes

@router.get("/teachers/{teacher_id}/quizzes")
async def get_teacher_quizzes(
    teacher_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None
):
    """Get all quizzes created by a teacher."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    quizzes = await quiz_service.get_teacher_quizzes(db, teacher_id, tenant_id)
    return quizzes

@router.get("/quizzes/{quiz_id}/results")
async def get_quiz_results(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None
):
    """Get all student results for a quiz (teacher view)."""
    if not tenant_id or not teacher_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Teacher ID required")
    
    results = await quiz_service.get_quiz_results(db, quiz_id, teacher_id, tenant_id)
    if results is None:
        raise HTTPException(status_code=404, detail="Quiz not found or unauthorized")
    return results

@router.delete("/quizzes/{quiz_id}")
async def delete_quiz(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None
):
    """Delete a quiz (soft delete)."""
    if not tenant_id or not teacher_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Teacher ID required")
    
    success = await quiz_service.delete_quiz(db, quiz_id, teacher_id, tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Quiz not found or unauthorized")
    return {"message": "Quiz deleted successfully"}

@router.get("/students/{student_id}/results", response_model=List[QuizAttemptResponse])
async def get_student_quiz_results(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None
):
    """Get all quiz results for a student."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    results = await quiz_service.get_student_quiz_results(db, student_id, tenant_id)
    return results

@router.patch("/quizzes/{quiz_id}/status")
async def update_quiz_status(
    quiz_id: UUID,
    status_data: QuizStatusUpdate,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None
):
    """Update quiz active status."""
    if not tenant_id or not teacher_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Teacher ID required")
    
    success = await quiz_service.update_quiz_status(db, quiz_id, teacher_id, tenant_id, status_data.is_active)
    if not success:
        raise HTTPException(status_code=404, detail="Quiz not found or unauthorized")
    
    return {"message": "Quiz status updated successfully"}

@router.post("/quizzes/create-with-questions", response_model=QuizResponse)
async def create_quiz_with_questions(
    quiz_data: QuizCreateWithQuestions,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None
):
    """Create a quiz with inline questions (no need for pre-existing topics/questions)."""
    if not tenant_id or not teacher_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Teacher ID required")
    
    quiz = await quiz_service.create_quiz_with_questions(db, quiz_data, teacher_id, tenant_id)
    return quiz

@router.get("/grading/pending")
async def get_pending_grading(
    teacher_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get short answer questions pending manual grading."""
    try:
        pending = await quiz_service.get_pending_grading(db, teacher_id, tenant_id)
        return pending
    except Exception as e:
        logger.error(f"Error in get_pending_grading: {e}")
        return []

@router.post("/grading/{answer_id}")
async def grade_short_answer(
    answer_id: UUID,
    grade_data: GradeShortAnswer,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None
):
    """Grade a short answer question."""
    if not tenant_id or not teacher_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Teacher ID required")
    
    success = await quiz_service.grade_short_answer(db, answer_id, grade_data.points_awarded, teacher_id, tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Answer not found or unauthorized")
    
    return {"message": "Answer graded successfully"}

@router.get("/grading/ready-to-publish")
async def get_attempts_ready_for_publishing(
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None
):
    """Get quiz attempts that are fully graded and ready for result publishing."""
    if not tenant_id or not teacher_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Teacher ID required")
    
    attempts = await quiz_service.get_attempts_ready_for_publishing(db, teacher_id, tenant_id)
    return attempts

@router.post("/results/publish")
async def publish_quiz_results(
    publish_data: PublishResults,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None
):
    """Publish results for completed quiz attempts after all grading is done."""
    if not tenant_id or not teacher_id:
        raise HTTPException(status_code=400, detail="Tenant ID and Teacher ID required")
    
    success = await quiz_service.publish_quiz_results(db, publish_data.attempt_ids, teacher_id, tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Some attempts not found or unauthorized")
    
    return {"message": "Results published successfully"}