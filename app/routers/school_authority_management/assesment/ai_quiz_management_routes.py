# AI Quiz Management Routes
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.services.assesment.ai_quiz_generation_service import AIQuizService
from app.schemas.assesment.ai_quiz_management_schemas import (
    AIQuizCreateRequest, AIQuizResponse, AIQuizTemplateRequest, AIQuizTemplateResponse,
    AIQuizForStudent, AIQuizAttemptStart, AIQuizHintRequest, AIQuizHintResponse,
    AIQuizResultsResponse, AIQuizHistoryResponse, TeacherAIQuizDashboard, AIQuizClassAnalytics
)
from app.schemas.assesment.quiz_validation_schemas import QuizAttemptResponse

router = APIRouter(prefix="/ai-quiz-management", tags=["AI Quiz Management"])

# AI Quiz Creation and Management
@router.post("/create-quiz", response_model=AIQuizResponse)
async def create_ai_quiz(
    request: AIQuizCreateRequest,
    teacher_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Create a complete AI-generated quiz with questions"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.create_complete_ai_quiz(
            db=db,
            request=request,
            teacher_id=teacher_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create AI quiz: {str(e)}"
        )

@router.get("/templates", response_model=List[AIQuizTemplateResponse])
async def get_ai_quiz_templates(
    subject: str,
    grade_level: int,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get AI-suggested quiz templates"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.get_quiz_templates(
            db=db,
            subject=subject,
            grade_level=grade_level,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get templates: {str(e)}"
        )

@router.post("/generate-from-template", response_model=AIQuizResponse)
async def generate_quiz_from_template(
    template_request: AIQuizTemplateRequest,
    teacher_id: UUID,
    tenant_id: UUID,
    class_ids: List[UUID],
    db: AsyncSession = Depends(get_db)
):
    """Generate quiz from AI template"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.generate_from_template(
            db=db,
            template_request=template_request,
            teacher_id=teacher_id,
            tenant_id=tenant_id,
            class_ids=class_ids
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate from template: {str(e)}"
        )

# Student AI Quiz Interaction
@router.get("/student/{quiz_id}", response_model=AIQuizForStudent)
async def get_ai_quiz_for_student(
    quiz_id: UUID,
    student_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get AI quiz for student with enhanced features"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.get_ai_quiz_for_student(
            db=db,
            quiz_id=quiz_id,
            student_id=student_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quiz not found: {str(e)}"
        )

@router.post("/start-attempt", response_model=QuizAttemptResponse)
async def start_ai_quiz_attempt(
    request: AIQuizAttemptStart,
    student_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Start AI quiz attempt with enhanced tracking"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.start_ai_quiz_attempt(
            db=db,
            request=request,
            student_id=student_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start attempt: {str(e)}"
        )

@router.post("/get-hint", response_model=AIQuizHintResponse)
async def get_ai_hint(
    request: AIQuizHintRequest,
    student_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get AI-powered hint for student"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.provide_ai_hint(
            db=db,
            request=request,
            student_id=student_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hint: {str(e)}"
        )

@router.get("/student/{student_id}/available-quizzes")
async def get_student_available_ai_quizzes(
    student_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get available AI quizzes for student"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.get_student_available_ai_quizzes(
            db=db,
            student_id=student_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get available quizzes: {str(e)}"
        )

# AI Quiz Results and Analytics
@router.get("/results/{attempt_id}", response_model=AIQuizResultsResponse)
async def get_ai_quiz_results(
    attempt_id: UUID,
    student_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed AI-analyzed quiz results"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.get_ai_quiz_results(
            db=db,
            attempt_id=attempt_id,
            student_id=student_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Results not found: {str(e)}"
        )

@router.get("/student/{student_id}/history", response_model=AIQuizHistoryResponse)
async def get_student_ai_quiz_history(
    student_id: UUID,
    tenant_id: UUID,
    subject: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get student's AI quiz history with insights"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.get_student_ai_quiz_history(
            db=db,
            student_id=student_id,
            tenant_id=tenant_id,
            subject=subject
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get history: {str(e)}"
        )

# Teacher AI Quiz Management
@router.get("/teacher/{teacher_id}/dashboard", response_model=TeacherAIQuizDashboard)
async def get_teacher_ai_quiz_dashboard(
    teacher_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get teacher's AI quiz management dashboard"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.get_teacher_ai_dashboard(
            db=db,
            teacher_id=teacher_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dashboard: {str(e)}"
        )

@router.get("/teacher/{teacher_id}/quizzes")
async def get_teacher_ai_quizzes(
    teacher_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get all AI quizzes created by teacher"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.get_teacher_ai_quizzes(
            db=db,
            teacher_id=teacher_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get teacher quizzes: {str(e)}"
        )

@router.get("/class-analytics/{quiz_id}/{class_id}", response_model=AIQuizClassAnalytics)
async def get_ai_quiz_class_analytics(
    quiz_id: UUID,
    class_id: UUID,
    teacher_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get AI-powered class analytics for quiz"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.get_ai_class_analytics(
            db=db,
            quiz_id=quiz_id,
            class_id=class_id,
            teacher_id=teacher_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analytics: {str(e)}"
        )

@router.delete("/quiz/{quiz_id}")
async def delete_ai_quiz(
    quiz_id: UUID,
    teacher_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Delete AI quiz (soft delete)"""
    try:
        ai_quiz_service = AIQuizService()
        success = await ai_quiz_service.delete_ai_quiz(
            db=db,
            quiz_id=quiz_id,
            teacher_id=teacher_id,
            tenant_id=tenant_id
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quiz not found or unauthorized"
            )
        return {"message": "AI quiz deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete quiz: {str(e)}"
        )

@router.patch("/quiz/{quiz_id}/status")
async def update_ai_quiz_status(
    quiz_id: UUID,
    is_active: bool,
    teacher_id: UUID,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Update AI quiz status"""
    try:
        ai_quiz_service = AIQuizService()
        success = await ai_quiz_service.update_ai_quiz_status(
            db=db,
            quiz_id=quiz_id,
            is_active=is_active,
            teacher_id=teacher_id,
            tenant_id=tenant_id
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quiz not found or unauthorized"
            )
        return {"message": "AI quiz status updated successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update status: {str(e)}"
        )

@router.get("/health")
async def ai_quiz_management_health():
    """Health check for AI quiz management"""
    return {"status": "healthy", "service": "AI Quiz Management"}