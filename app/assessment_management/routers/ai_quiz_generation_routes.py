# app/routers/ai_quiz.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from ...core.database import get_db
from ...assessment_management.services.ai_quiz_generation_service import AIQuizService
from ...core.rate_limiter import rate_limiter
from ...auth_rbac.security.deps import require_staff
from ...assessment_management.schemas.ai_analytics_schemas import (
    QuestionGenerationRequest, QuestionGenerationResponse,
    QuizAssemblyRequest, QuizAssemblyResponse,
    SubjectiveGradingRequest, SubjectiveGradingResponse,
    PerformanceAnalysisRequest, PerformanceAnalysisResponse,
    BatchQuestionGeneration, BatchQuestionResponse
)

# Every endpoint here is staff-facing AI authoring/grading/cohort-analytics — gate the
# whole router to staff (blocks students from question injection, cross-tenant grading,
# cohort analytics and AI cost-abuse). Per-endpoint tenant-binding still TODO (see
# ASSESSMENT_AUTHZ_REMEDIATION.md).
router = APIRouter(prefix="/ai-quiz", tags=["AI Quiz"], dependencies=[Depends(require_staff)])

@router.post("/generate-questions", response_model=QuestionGenerationResponse)
async def generate_questions(
    request: QuestionGenerationRequest,
    tenant_id: UUID,
    auto_save: bool = False,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(lambda req: rate_limiter.check_rate_limit(req, max_requests=10, window=60))
):
    """Generate questions using AI"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.generate_questions_ai(
            db=db,
            request=request,
            tenant_id=tenant_id,
            auto_save=auto_save
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate questions: {str(e)}"
        )

@router.post("/batch-generate-questions", response_model=BatchQuestionResponse)
async def batch_generate_questions(
    request: BatchQuestionGeneration,
    tenant_id: UUID,
    auto_save: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """Generate multiple sets of questions using AI"""
    try:
        ai_quiz_service = AIQuizService()
        results = []
        success_count = 0
        failed_count = 0
        total_questions = 0
        
        for gen_request in request.requests:
            try:
                result = await ai_quiz_service.generate_questions_ai(
                    db=db,
                    request=gen_request,
                    tenant_id=tenant_id,
                    auto_save=auto_save
                )
                results.append(result)
                success_count += 1
                total_questions += result.total_generated
            except Exception:
                failed_count += 1
        
        return BatchQuestionResponse(
            results=results,
            total_questions_generated=total_questions,
            success_count=success_count,
            failed_count=failed_count
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to batch generate questions: {str(e)}"
        )

@router.post("/suggest-quiz-assembly", response_model=QuizAssemblyResponse)
async def suggest_quiz_assembly(
    request: QuizAssemblyRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get AI suggestions for optimal quiz assembly"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.suggest_quiz_assembly_ai(
            db=db,
            request=request,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to suggest quiz assembly: {str(e)}"
        )

@router.post("/grade-subjective", response_model=SubjectiveGradingResponse)
async def grade_subjective_answer(
    request: SubjectiveGradingRequest
):
    """Grade subjective answers using AI"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.grade_subjective_answer_ai(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to grade answer: {str(e)}"
        )

@router.post("/analyze-performance", response_model=PerformanceAnalysisResponse)
async def analyze_quiz_performance(
    request: PerformanceAnalysisRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Analyze quiz performance using AI"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.analyze_quiz_performance_ai(
            db=db,
            request=request,
            tenant_id=tenant_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze performance: {str(e)}"
        )

@router.post("/enhanced-grading/{attempt_id}")
async def enhanced_quiz_grading(
    attempt_id: UUID,
    tenant_id: UUID,
    use_ai_grading: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """Enhanced quiz grading with AI for subjective questions"""
    try:
        ai_quiz_service = AIQuizService()
        return await ai_quiz_service.enhance_quiz_grading(
            db=db,
            attempt_id=attempt_id,
            tenant_id=tenant_id,
            use_ai_grading=use_ai_grading
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to grade quiz: {str(e)}"
        )

@router.get("/health")
async def ai_quiz_health():
    """Health check for AI quiz services"""
    return {"status": "healthy", "service": "AI Quiz Service"}