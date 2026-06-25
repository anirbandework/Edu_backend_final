# app/routers/ai_learning.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID
import logging

from ...core.database import get_db
from ...assessment_management.services.ai_student_analytics_service import AILearningService
from ...assessment_management.services.ai_report_generation_service import AIReportService
from ...auth_rbac.security.deps import get_current_principal, require_staff
from ...auth_rbac.security.principal import Principal
from ...assessment_management.schemas.ai_analytics_schemas import (
    StudentInsightsRequest, StudentInsightsResponse,
    StudyRecommendationRequest, StudyRecommendationResponse,
    WeaknessAnalysisRequest, WeaknessAnalysisResponse,
    ExamPrepRequest, ExamPrepResponse,
    PerformancePredictionRequest, PerformancePredictionResponse,
    ReportGenerationRequest, ReportGenerationResponse,
    InterventionRequest, InterventionResponse
)

router = APIRouter(prefix="/ai-learning", tags=["AI Learning Analytics"])
logger = logging.getLogger(__name__)


def _self_scope(principal: Principal, request, tenant_id: UUID) -> UUID:
    """For single-student analytics: bind tenant to the principal and, for a student caller,
    force request.student_id to themselves (a student may only analyze their OWN data).
    Staff/super-admin keep the supplied student_id (scoped to their tenant)."""
    eff_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    if not (principal.is_super_admin or principal.is_staff):
        sid = getattr(request, "student_id", None)
        if sid is not None and str(sid) != str(principal.user_id):
            raise HTTPException(status_code=403, detail="You can only access your own analytics")
        if hasattr(request, "student_id"):
            request.student_id = UUID(str(principal.user_id))
    return eff_tenant


# Student Insights Endpoints (student self-service; staff may query any student in-tenant)
@router.post("/student-insights", response_model=StudentInsightsResponse)
async def analyze_student_insights(
    request: StudentInsightsRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Analyze student performance and provide personalized insights"""
    eff_tenant = _self_scope(principal, request, tenant_id)
    try:
        ai_learning_service = AILearningService()
        return await ai_learning_service.analyze_student_insights(db=db, request=request, tenant_id=eff_tenant)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to analyze student insights: {str(e)}")


@router.post("/study-recommendations", response_model=StudyRecommendationResponse)
async def generate_study_recommendations(
    request: StudyRecommendationRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Generate personalized study recommendations for student"""
    eff_tenant = _self_scope(principal, request, tenant_id)
    try:
        ai_learning_service = AILearningService()
        return await ai_learning_service.generate_study_recommendations(db=db, request=request, tenant_id=eff_tenant)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to generate study recommendations: {str(e)}")


@router.post("/weakness-analysis", response_model=WeaknessAnalysisResponse)
async def identify_knowledge_gaps(
    request: WeaknessAnalysisRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Identify specific knowledge gaps and learning weaknesses"""
    eff_tenant = _self_scope(principal, request, tenant_id)
    try:
        ai_learning_service = AILearningService()
        return await ai_learning_service.identify_knowledge_gaps(db=db, request=request, tenant_id=eff_tenant)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to analyze weaknesses: {str(e)}")


@router.post("/exam-preparation", response_model=ExamPrepResponse)
async def generate_exam_prep_plan(
    request: ExamPrepRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Generate AI-powered exam preparation plan"""
    eff_tenant = _self_scope(principal, request, tenant_id)
    try:
        ai_learning_service = AILearningService()
        return await ai_learning_service.generate_exam_prep_plan(db=db, request=request, tenant_id=eff_tenant)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to generate exam preparation plan: {str(e)}")


@router.post("/performance-prediction", response_model=PerformancePredictionResponse)
async def predict_student_performance(
    request: PerformancePredictionRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Predict student performance for upcoming assessments"""
    eff_tenant = _self_scope(principal, request, tenant_id)
    try:
        ai_learning_service = AILearningService()
        return await ai_learning_service.predict_performance(db=db, request=request, tenant_id=eff_tenant)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to predict performance: {str(e)}")


# Report Generation Endpoints (staff only — cohort/parent/progress reports)
@router.post("/generate-report", response_model=ReportGenerationResponse)
async def generate_intelligent_report(
    request: ReportGenerationRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Generate AI-enhanced reports (student progress, class summary, parent reports)"""
    eff_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    try:
        ai_report_service = AIReportService()
        if request.report_type == "student_progress":
            return await ai_report_service.generate_student_progress_report(db=db, request=request, tenant_id=eff_tenant)
        elif request.report_type == "class_summary":
            return await ai_report_service.generate_class_summary_report(db=db, request=request, tenant_id=eff_tenant)
        elif request.report_type == "parent_report":
            return await ai_report_service.generate_parent_report(db=db, request=request, tenant_id=eff_tenant)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Unsupported report type: {request.report_type}")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Report generation error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to generate report: {str(e)}")


@router.post("/intervention-analysis", response_model=InterventionResponse)
async def analyze_intervention_needs(
    request: InterventionRequest,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),  # cohort intervention: staff only
):
    """Identify students needing intervention and suggest strategies"""
    eff_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    try:
        ai_report_service = AIReportService()
        return await ai_report_service.identify_intervention_needs(db=db, request=request, tenant_id=eff_tenant)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to analyze intervention needs: {str(e)}")


# Batch Analysis Endpoints (staff only — runs over a list of students)
@router.post("/batch-student-analysis")
async def batch_analyze_students(
    student_ids: List[UUID],
    tenant_id: UUID,
    analysis_types: List[str] = ["insights", "recommendations", "weaknesses"],
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),  # bulk cohort analysis: staff only
):
    """Perform batch analysis for multiple students"""
    eff_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    try:
        ai_learning_service = AILearningService()
        results = {}
        for student_id in student_ids:
            student_results = {}
            if "insights" in analysis_types:
                insights_request = StudentInsightsRequest(student_id=student_id)
                student_results["insights"] = await ai_learning_service.analyze_student_insights(
                    db=db, request=insights_request, tenant_id=eff_tenant)
            if "recommendations" in analysis_types:
                rec_request = StudyRecommendationRequest(student_id=student_id)
                student_results["recommendations"] = await ai_learning_service.generate_study_recommendations(
                    db=db, request=rec_request, tenant_id=eff_tenant)
            if "weaknesses" in analysis_types:
                weakness_request = WeaknessAnalysisRequest(student_id=student_id)
                student_results["weaknesses"] = await ai_learning_service.identify_knowledge_gaps(
                    db=db, request=weakness_request, tenant_id=eff_tenant)
            results[str(student_id)] = student_results
        return {"batch_analysis_results": results, "total_students_analyzed": len(student_ids),
                "analysis_types": analysis_types}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to perform batch analysis: {str(e)}")


@router.get("/health")
async def ai_learning_health():
    """Health check for AI learning services"""
    return {
        "status": "healthy",
        "services": ["AI Learning Analytics", "AI Report Generation"],
        "features": [
            "Student Insights", "Study Recommendations", "Weakness Analysis",
            "Exam Preparation", "Performance Prediction", "Intelligent Reports",
            "Intervention Analysis"
        ]
    }
