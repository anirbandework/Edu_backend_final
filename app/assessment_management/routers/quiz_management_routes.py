# app/routers/quiz.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from ...core.database import get_db
from ...assessment_management.services.quiz_management_service import QuizService
from ...core.rate_limiter import rate_limiter
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal
from ...assessment_management.schemas.quiz_validation_schemas import (
    TopicCreate, TopicResponse, QuestionCreate, QuestionResponse,
    QuizCreate, QuizResponse, QuizForStudent, QuizAttemptStart,
    QuizAttemptSubmit, QuizAttemptResponse, QuizResultResponse, QuizStatusUpdate,
    QuizCreateWithQuestions, GradeShortAnswer, PublishResults
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quiz", tags=["Quiz Management"])
quiz_service = QuizService()


def _eff_tenant(principal: Principal, tenant_id) -> UUID:
    eff = tenant_id if principal.is_super_admin else principal.tenant_id
    if eff is None:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    return eff


def _eff_owner(principal: Principal, owner_id):
    """Teacher-owned resource id: teachers forced to self; authority/super-admin may specify."""
    if principal.is_super_admin or principal.is_authority:
        return owner_id
    return UUID(str(principal.user_id))


def _eff_subject(principal: Principal, subject_id):
    """Student data id: staff/super-admin may target any in-tenant; students forced to self."""
    if principal.is_super_admin or principal.is_staff:
        return subject_id
    return UUID(str(principal.user_id))


# Topic endpoints (staff)
@router.post("/topics", response_model=TopicResponse)
async def create_topic(
    topic_data: TopicCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Create a new topic for quizzes."""
    return await quiz_service.create_topic(db, topic_data, _eff_tenant(principal, tenant_id))


@router.get("/topics", response_model=List[TopicResponse])
async def get_topics(
    subject: Optional[str] = None,
    grade_level: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(get_current_principal),
):
    """Get all topics, optionally filtered by subject and grade level."""
    eff_tenant = _eff_tenant(principal, tenant_id)

    from ...core.cache import cache_service
    cache_key = f"topics:{eff_tenant}:{subject}:{grade_level}"
    cached_topics = await cache_service.get(cache_key)
    if cached_topics:
        return cached_topics

    topics = await quiz_service.get_topics(db, eff_tenant, subject, grade_level)
    await cache_service.set(cache_key, topics, ttl=300)
    return topics


# Question endpoints (staff — question banks contain answers)
@router.post("/questions", response_model=QuestionResponse)
async def create_question(
    question_data: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Create a new question for a topic."""
    return await quiz_service.create_question(db, question_data, _eff_tenant(principal, tenant_id))


@router.get("/topics/{topic_id}/questions", response_model=List[QuestionResponse])
async def get_questions_by_topic(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),  # full question bank incl. answers
):
    """Get all questions for a specific topic."""
    return await quiz_service.get_questions_by_topic(db, _eff_tenant(principal, tenant_id), topic_id)


# Quiz endpoints
@router.post("/quizzes", response_model=QuizResponse)
async def create_quiz(
    quiz_data: QuizCreate,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Create a new quiz."""
    return await quiz_service.create_quiz(db, quiz_data, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))


@router.get("/quizzes/{quiz_id}/student", response_model=QuizForStudent)
async def get_quiz_for_student(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(get_current_principal),  # students load quizzes to take them
):
    """Get quiz details for student (without correct answers)."""
    quiz = await quiz_service.get_quiz_for_student(db, quiz_id, _eff_tenant(principal, tenant_id))
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

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
        "id": quiz.id, "title": quiz.title, "description": quiz.description,
        "instructions": quiz.instructions, "total_questions": quiz.total_questions,
        "total_points": quiz.total_points, "time_limit": quiz.time_limit, "questions": questions
    }


# Quiz Attempt endpoints (student self-service)
@router.post("/attempts/start", response_model=QuizAttemptResponse)
async def start_quiz_attempt(
    attempt_data: QuizAttemptStart,
    db: AsyncSession = Depends(get_db),
    student_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(get_current_principal),
):
    """Start a new quiz attempt for the authenticated student."""
    eff_student = _eff_subject(principal, student_id)
    return await quiz_service.start_quiz_attempt(db, eff_student, attempt_data.quiz_id, _eff_tenant(principal, tenant_id))


@router.post("/attempts/submit", response_model=QuizAttemptResponse)
async def submit_quiz_attempt(
    attempt_data: QuizAttemptSubmit,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(get_current_principal),
):
    """Submit a completed quiz attempt (only the caller's own attempt)."""
    eff_tenant = _eff_tenant(principal, tenant_id)

    # Ownership guard: the service loads the attempt by id alone, so verify here that the
    # attempt belongs to the caller (a student may not submit/overwrite another's attempt).
    if not (principal.is_super_admin or principal.is_staff):
        aid = getattr(attempt_data, "attempt_id", None)
        if aid is not None:
            row = (await db.execute(
                text("SELECT student_id, tenant_id FROM quiz_attempts WHERE id = :a"), {"a": str(aid)}
            )).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Attempt not found")
            if str(row[0]) != str(principal.user_id) or (principal.tenant_id and str(row[1]) != str(principal.tenant_id)):
                raise HTTPException(status_code=403, detail="Not your attempt")

    try:
        return await quiz_service.submit_quiz_attempt(db, attempt_data, eff_tenant)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/students/{student_id}/available-quizzes")
async def get_student_available_quizzes(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(get_current_principal),
):
    """Get available quizzes for a student based on their class."""
    return await quiz_service.get_student_available_quizzes(db, _eff_subject(principal, student_id), _eff_tenant(principal, tenant_id))


@router.get("/teachers/{teacher_id}/quizzes")
async def get_teacher_quizzes(
    teacher_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Get all quizzes created by a teacher."""
    return await quiz_service.get_teacher_quizzes(db, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))


@router.get("/quizzes/{quiz_id}/results")
async def get_quiz_results(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),  # cohort results: staff only
):
    """Get all student results for a quiz (teacher view)."""
    results = await quiz_service.get_quiz_results(db, quiz_id, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))
    if results is None:
        raise HTTPException(status_code=404, detail="Quiz not found or unauthorized")
    return results


@router.delete("/quizzes/{quiz_id}")
async def delete_quiz(
    quiz_id: UUID,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Delete a quiz (soft delete)."""
    success = await quiz_service.delete_quiz(db, quiz_id, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))
    if not success:
        raise HTTPException(status_code=404, detail="Quiz not found or unauthorized")
    return {"message": "Quiz deleted successfully"}


@router.get("/students/{student_id}/results", response_model=List[QuizAttemptResponse])
async def get_student_quiz_results(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = None,
    principal: Principal = Depends(get_current_principal),
):
    """Get all quiz results for a student (own results, or staff in-tenant)."""
    return await quiz_service.get_student_quiz_results(db, _eff_subject(principal, student_id), _eff_tenant(principal, tenant_id))


@router.patch("/quizzes/{quiz_id}/status")
async def update_quiz_status(
    quiz_id: UUID,
    status_data: QuizStatusUpdate,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Update quiz active status."""
    success = await quiz_service.update_quiz_status(db, quiz_id, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id), status_data.is_active)
    if not success:
        raise HTTPException(status_code=404, detail="Quiz not found or unauthorized")
    return {"message": "Quiz status updated successfully"}


@router.post("/quizzes/create-with-questions", response_model=QuizResponse)
async def create_quiz_with_questions(
    quiz_data: QuizCreateWithQuestions,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Create a quiz with inline questions (no need for pre-existing topics/questions)."""
    return await quiz_service.create_quiz_with_questions(db, quiz_data, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))


@router.get("/grading/pending")
async def get_pending_grading(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Get short answer questions pending manual grading."""
    try:
        return await quiz_service.get_pending_grading(db, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))
    except Exception as e:
        logger.error(f"Error in get_pending_grading: {e}")
        return []


@router.post("/grading/{answer_id}")
async def grade_short_answer(
    answer_id: UUID,
    grade_data: GradeShortAnswer,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),  # grading: staff only (no self-grading)
):
    """Grade a short answer question."""
    success = await quiz_service.grade_short_answer(db, answer_id, grade_data.points_awarded, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))
    if not success:
        raise HTTPException(status_code=404, detail="Answer not found or unauthorized")
    return {"message": "Answer graded successfully"}


@router.get("/grading/ready-to-publish")
async def get_attempts_ready_for_publishing(
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),
):
    """Get quiz attempts that are fully graded and ready for result publishing."""
    return await quiz_service.get_attempts_ready_for_publishing(db, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))


@router.post("/results/publish")
async def publish_quiz_results(
    publish_data: PublishResults,
    db: AsyncSession = Depends(get_db),
    teacher_id: UUID = None,
    tenant_id: UUID = None,
    principal: Principal = Depends(require_authority_or_module('quizzes')),  # publishing grades: staff only
):
    """Publish results for completed quiz attempts after all grading is done."""
    success = await quiz_service.publish_quiz_results(db, publish_data.attempt_ids, _eff_owner(principal, teacher_id), _eff_tenant(principal, tenant_id))
    if not success:
        raise HTTPException(status_code=404, detail="Some attempts not found or unauthorized")
    return {"message": "Results published successfully"}
